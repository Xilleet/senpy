"""Plugin loading via [project.entry-points."senpy.plugins"].

Discovers plugins installed via pip, loads them with security checks.

Pipeline:
    discover_plugins() → list of EntryPoint
        ↓
    load_plugin(entry_point, trust_callback) → _LoadedEntryPoint | None
        ↓ (per plugin, isolated)
    load_all_plugins(trust_callback) → list of _LoadedEntryPoint
        ↓
    register_loaded_plugins(loaded) → registers in lint rule registry

Security checks (per plugin, in order):
    1. api_version check (SEC-P1) — skip if incompatible
    2. trust check (SEC-P2) — ask user, or use trust store
    3. Type check — skip if entry point doesn't load a Rule subclass

Isolation: if any plugin fails to load (import error, etc.), it's skipped
with a warning. Other plugins continue to load.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from senpy.core.logging import get_logger

_logger = get_logger("plugins")

if TYPE_CHECKING:
    from senpy.plugins.base import Rule


# =============================================================================
# Constants
# =============================================================================

# Entry point group name. Plugins declare in their pyproject.toml:
#   [project.entry-points."senpy.plugins"]
#   my_rule = "my_senpy_plugin.rules:MyRule"
_PLUGIN_ENTRY_POINT_GROUP = "senpy.plugins"

# Trust callback signature: takes plugin name, returns True (trust) or False (decline)
TrustCallback = Callable[[str], bool]


# =============================================================================
# _LoadedEntryPoint dataclass
# =============================================================================


@dataclass
class _LoadedEntryPoint:
    """Result of successfully loading a plugin entry point.

    Attributes:
        name: Plugin name (entry_point.name, e.g. "my-senpy-plugin")
        rule_cls: Rule subclass loaded from the entry point
    """

    name: str
    rule_cls: type[Rule]


# =============================================================================
# Discovery
# =============================================================================


def _get_entry_points():
    """Returns entry points in the 'senpy.plugins' group.

    Uses importlib.metadata (Python 3.10+, recommended).
    Returns empty list if no plugins installed or importlib unavailable.
    """
    try:
        from importlib.metadata import entry_points
    except ImportError:
        # Python < 3.10 (shouldn't happen, requires-python = ">=3.11")
        return []

    # Python 3.10+: entry_points() returns EntryPoints (selectable by group)
    try:
        # Python 3.12+: entry_points(group=...) directly
        return list(entry_points(group=_PLUGIN_ENTRY_POINT_GROUP))
    except TypeError:
        # Python 3.10-3.11: entry_points() returns dict-like, need .select()
        try:
            eps = entry_points()
            # Old API: EntryPoints.select(group=...)
            if hasattr(eps, "select"):
                return list(eps.select(group=_PLUGIN_ENTRY_POINT_GROUP))
            # Even older: returns dict {group: [EntryPoint, ...]}
            if isinstance(eps, dict):
                return list(eps.get(_PLUGIN_ENTRY_POINT_GROUP, []))
            return list(eps)
        except Exception:
            return []


def discover_plugins():
    """Discover installed Senpy plugins via entry_points.

    Returns:
        List of EntryPoint objects (NOT loaded yet — loading is deferred
        to load_plugin() so we can do trust check first).

    Note: returns a COPY of the internal list (safe to modify).
    """
    return _get_entry_points()


# =============================================================================
# Loading  + Security
# =============================================================================


def _resolve_plugin_api_version(rule_cls: type) -> str | None:
    """Resolve PLUGIN_API_VERSION declared by a plugin Rule.

    Plugins may declare PLUGIN_API_VERSION in two ways:

    1. As a class attribute on the Rule subclass (e.g.
       ``class MyRule(Rule): PLUGIN_API_VERSION = "1.0"``).
    2. As a module-level constant in the module that defines the Rule
       (e.g. ``PLUGIN_API_VERSION = "1.0"`` at the top of ``rules.py``).
       This is the convention used by both shipped example plugins
       (examples/my_senpy_plugin/rules.py:22,
       examples/todo_comment_plugin/todo_comment_plugin/rules.py:37).

    Returns the version string if declared in either place, otherwise None.
    The class attribute takes precedence (more specific scope).
    """
    class_attr = getattr(rule_cls, "PLUGIN_API_VERSION", None)
    if class_attr is not None:
        return class_attr

    module = sys.modules.get(getattr(rule_cls, "__module__", None))
    if module is None:
        return None
    return getattr(module, "PLUGIN_API_VERSION", None)


def load_plugin(entry_point, trust_callback: TrustCallback | None = None):
    """Load a single plugin entry point with security checks.

    Pipeline (trust BEFORE load — see TOFU fix):
        1. Trust check: call trust_callback (or default) — skip if declined.
           This runs BEFORE ``entry_point.load()`` so that a declined
           plugin's top-level Python code (``__init__.py``, ``rules.py``,
           ``@register_rule`` decorators, class body) never executes.
           Previously load() ran first, then trust was checked — meaning
           a malicious plugin's top-level code ran on every Senpy start
           (including CI/LSP), and ``@register_rule`` import-time side
           effects mutated ``_REGISTERED_LINT_RULES`` even when trust
           was declined.
        2. Load entry_point value (the Rule subclass) — only if trust approved.
        3. Verify it's a Rule subclass (skip if not, with warning).
        4. Check plugin's api_version (class attribute OR module-level
           constant — see _resolve_plugin_api_version). Skip if incompatible.
        5. Return _LoadedEntryPoint(name, rule_cls), or None if skipped.

    Isolation: any exception during loading is caught and logged. Returns None.

    Args:
        entry_point: EntryPoint object (from importlib.metadata)
        trust_callback: Optional callable(name: str) -> bool.
                       If None, uses _default_trust_callback (prompts in TTY,
                       declines in non-TTY unless pre-trusted).

    Returns:
        _LoadedEntryPoint if loaded successfully, None if skipped/failed.
    """
    plugin_name = getattr(entry_point, "name", "<unknown>")

    # Step 1: Trust check (SEC-P2) — MUST run before entry_point.load().
    # The trust decision is based solely on the plugin name (a string),
    # so it does not require loading the plugin module. Running trust
    # first guarantees that a declined plugin's top-level code never
    # executes — no import-time side effects, no registry mutation,
    # no network calls, no file writes.
    if trust_callback is None:
        trust_callback = _default_trust_callback

    if not trust_callback(plugin_name):
        # Trust declined — skip silently (don't warn, this is expected in CI).
        # CRITICAL: return here, before entry_point.load(), so the plugin
        # module is never imported.
        return None

    # Step 2: Load entry_point value (catch import errors).
    # Only reached after trust is approved — the plugin module is now
    # allowed to execute its top-level code.
    try:
        rule_cls = entry_point.load()
    except Exception as e:
        _logger.warning("Failed to load plugin %r: %s", plugin_name, e)
        return None

    # Step 3: Verify it's a Rule subclass
    from senpy.plugins.base import Rule

    if not isinstance(rule_cls, type) or not issubclass(rule_cls, Rule):
        _logger.warning(
            "Plugin %r entry point does not point to a Rule subclass (got: %r). Skipping.",
            plugin_name,
            rule_cls,
        )
        return None

    # Step 4: Check plugin's api_version (SEC-P1)
    # Plugins may declare PLUGIN_API_VERSION either as a class attribute on
    # the Rule subclass or as a module-level constant. Both shipped example
    # plugins (examples/my_senpy_plugin/rules.py:22,
    # examples/todo_comment_plugin/todo_comment_plugin/rules.py:37) follow
    # the module-level convention, so a class-only lookup is insufficient —
    # the version check would be silently skipped for the documented pattern.
    plugin_api_version = _resolve_plugin_api_version(rule_cls)
    if plugin_api_version is not None:
        from senpy.plugins.security import check_api_version

        if not check_api_version(plugin_api_version):
            from senpy.plugins.security import PLUGIN_API_VERSION

            _logger.warning(
                "Plugin %r requires api_version %r, but Senpy provides %r. "
                "Skipping. (Update plugin or use compatible Senpy version.)",
                plugin_name,
                plugin_api_version,
                PLUGIN_API_VERSION,
            )
            return None
    else:
        # enforce PLUGIN_API_VERSION declaration. The contract
        # (docs/plugin-development.md:62) says plugins "must declare"
        # PLUGIN_API_VERSION. Previously this was a DEBUG log + continue
        # (opt-out) — a plugin without the declaration was silently loaded.
        # Now: WARNING + skip (opt-in). Fail-safe: a plugin that doesn't
        # declare its API version is incompatible by default.
        _logger.warning(
            "Plugin %r does not declare PLUGIN_API_VERSION "
            "(neither class nor module attribute). Skipping — "
            "plugins must declare PLUGIN_API_VERSION for compatibility "
            "(see docs/plugin-development.md).",
            plugin_name,
        )
        return None

    # All checks passed
    return _LoadedEntryPoint(name=plugin_name, rule_cls=rule_cls)


def load_all_plugins(trust_callback: TrustCallback | None = None) -> list:
    """Discover and load all installed Senpy plugins with security checks.

    Args:
        trust_callback: Optional callable(name: str) -> bool.
                       If None, uses _default_trust_callback.

    Returns:
        List of _LoadedEntryPoint (successfully loaded plugins only).
        Failed/skipped plugins are excluded (isolation).
    """
    if trust_callback is None:
        trust_callback = _default_trust_callback

    entry_points = discover_plugins()
    loaded: list[_LoadedEntryPoint] = []

    for ep in entry_points:
        result = load_plugin(ep, trust_callback=trust_callback)
        if result is not None:
            loaded.append(result)

    return loaded


# =============================================================================
# Default trust callback
# =============================================================================


def _default_trust_callback(plugin_name: str) -> bool:
    """Default trust callback: trust-on-first-use with prompt.

    Behavior:
        1. If plugin is in trust store (pre-trusted): accept without prompt
        2. If in LSP mode (--lsp in argv): decline all untrusted (fail-safe,
           no prompt — input() would hang the LSP process)
        3. If in TTY (interactive CLI): prompt user "Trust plugin X? [y/N]"
           - On 'y' or 'yes': trust_plugin(name), return True
           - On anything else (including empty): return False
        4. If non-TTY (CI, piped): decline all untrusted (fail-safe)

    Args:
        plugin_name: Name of the plugin to trust-check.

    Returns:
        True if plugin is trusted (pre-trusted or just approved),
        False if declined or non-interactive.
    """
    from senpy.plugins.security import is_plugin_trusted, trust_plugin

    # Step 1: Check trust store
    if is_plugin_trusted(plugin_name):
        return True

    # Step 2: If running as LSP server, never prompt — input() would
    # hang the process (LSP communicates via stdio, not interactive TTY).
    if "--lsp" in sys.argv:
        _logger.warning(
            "Plugin %r is not trusted. In LSP mode, untrusted plugins are "
            "skipped (no interactive prompt). Use 'senpy --trust-plugin %r' "
            "from CLI to trust it first.",
            plugin_name,
            plugin_name,
        )
        return False

    # Step 3: Check if we're in interactive mode
    if not sys.stdin.isatty():
        # Non-interactive (CI, piped stdin) — fail-safe, decline
        return False

    # Step 4: Prompt user
    try:
        answer = (
            input(f"\n[senpy] Plugin '{plugin_name}' wants to load. Trust and enable? [y/N]: ")
            .strip()
            .lower()
        )
    except (EOFError, KeyboardInterrupt):
        return False

    if answer in ("y", "yes"):
        trust_plugin(plugin_name)
        _logger.info("Plugin %r trusted and added to trust store.", plugin_name)
        return True

    return False


# =============================================================================
# Register loaded plugins in lint rule registry
# =============================================================================


def register_loaded_plugins(loaded: list[_LoadedEntryPoint]) -> None:
    """Register all loaded plugin rules in the lint rule registry.

    After this, plugin rules appear in get_registered_lint_rules() and
    SenpyAnalyzer can instantiate + run them during analysis.

    Plugin rules whose ``code`` collides with a built-in ``RULES_DATABASE``
    entry are rejected — they are logged at WARNING and never enter the
    registry. This is the runtime half of the "built-in code wins on
    collision" contract: ``rule_dispatch.py`` already filters the
    collision client-side for ``senpy rule list/show``, but without
    this check the plugin rule would still be registered and still run
    during ``analyzer.run()`` via ``_run_plugin_rules``, producing
    duplicate diagnostics or shadowing the built-in behaviour.

    Code range contract:
        - ``RPY0xx``–``RPY8xx`` are reserved for built-in rules
          (see ``RULES_DATABASE``). Plugin rules with a code in this
          range that matches an existing built-in are rejected here.
        - ``RPY9xx`` is reserved for plugin rules — built-in will never
          use this range, so plugin authors can pick any ``RPY9xx``
          code without fear of collision with a future built-in.

    Args:
        loaded: List of _LoadedEntryPoint (from load_all_plugins()).
    """
    from senpy.plugins.registry import _REGISTERED_LINT_RULES
    from senpy.rules.rules_info import RULES_DATABASE

    for entry in loaded:
        rule_cls = entry.rule_cls
        # Get rule code from meta
        if rule_cls.meta is None:
            _logger.warning("Plugin %r has no meta. Skipping registration.", entry.name)
            continue
        code = rule_cls.meta.code
        # Reject plugin rules that collide with a built-in RULES_DATABASE
        # entry. The built-in is the canonical source for the code — a
        # plugin cannot shadow it. This check is the runtime counterpart
        # of the cosmetic filter in rule_dispatch.py (which only affects
        # `senpy rule list/show` output).
        if code in RULES_DATABASE:
            _logger.warning(
                "Plugin %r declares code %r, which is already a built-in rule. "
                "Plugin rules with built-in codes are rejected to prevent "
                "duplicate diagnostics and shadowing. Use a code in the "
                "reserved RPY9xx plugin range instead.",
                entry.name,
                code,
            )
            continue
        # Register (same as @register_rule decorator does)
        _REGISTERED_LINT_RULES.append((code, rule_cls))
