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


def load_plugin(entry_point, trust_callback: TrustCallback | None = None):
    """Load a single plugin entry point with security checks.

    Pipeline:
        1. Load entry_point value (the Rule subclass)
        2. Verify it's a Rule subclass (skip if not, with warning)
        3. Check plugin's api_version if declared (skip if incompatible)
        4. Trust check: call trust_callback (or default) — skip if declined
        5. Return _LoadedEntryPoint(name, rule_cls), or None if skipped

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

    # Step 1: Load entry_point value (catch import errors)
    try:
        rule_cls = entry_point.load()
    except Exception as e:
        print(f"[senpy.plugins] WARNING: Failed to load plugin '{plugin_name}': {e}",
              file=sys.stderr)
        return None

    # Step 2: Verify it's a Rule subclass
    from senpy.plugins.base import Rule
    if not isinstance(rule_cls, type) or not issubclass(rule_cls, Rule):
        print(f"[senpy.plugins] WARNING: Plugin '{plugin_name}' entry point does not "
              f"point to a Rule subclass (got: {rule_cls!r}). Skipping.",
              file=sys.stderr)
        return None

    # Step 3: Check plugin's api_version (SEC-P1)
    # Plugin can declare PLUGIN_API_VERSION as class attribute on the Rule subclass
    plugin_api_version = getattr(rule_cls, "PLUGIN_API_VERSION", None)
    if plugin_api_version is not None:
        from senpy.plugins.security import check_api_version
        if not check_api_version(plugin_api_version):
            from senpy.plugins.security import PLUGIN_API_VERSION
            print(f"[senpy.plugins] WARNING: Plugin '{plugin_name}' requires "
                  f"api_version {plugin_api_version!r}, but Senpy provides "
                  f"{PLUGIN_API_VERSION!r}. Skipping. "
                  f"(Update plugin or use compatible Senpy version.)",
                  file=sys.stderr)
            return None

    # Step 4: Trust check (SEC-P2)
    if trust_callback is None:
        trust_callback = _default_trust_callback

    if not trust_callback(plugin_name):
        # Trust declined — skip silently (don't warn, this is expected in CI)
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
        2. If in TTY (interactive): prompt user "Trust plugin X? [y/N]"
           - On 'y' or 'yes': trust_plugin(name), return True
           - On anything else (including empty): return False
        3. If non-TTY (CI, piped): decline all untrusted (fail-safe)

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

    # Step 2: Check if we're in interactive mode
    if not sys.stdin.isatty():
        # Non-interactive (CI, piped stdin) — fail-safe, decline
        return False

    # Step 3: Prompt user
    try:
        answer = input(
            f"\n[senpy] Plugin '{plugin_name}' wants to load. "
            f"Trust and enable? [y/N]: "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if answer in ("y", "yes"):
        trust_plugin(plugin_name)
        print(f"[senpy] Plugin '{plugin_name}' trusted and added to trust store.")
        return True

    return False


# =============================================================================
# Register loaded plugins in lint rule registry
# =============================================================================


def register_loaded_plugins(loaded: list[_LoadedEntryPoint]) -> None:
    """Register all loaded plugin rules in the lint rule registry.

    After this, plugin rules appear in get_registered_lint_rules() and
    SenpyAnalyzer can instantiate + run them during analysis.

    Args:
        loaded: List of _LoadedEntryPoint (from load_all_plugins()).
    """
    from senpy.plugins.registry import _REGISTERED_LINT_RULES

    for entry in loaded:
        rule_cls = entry.rule_cls
        # Get rule code from meta
        if rule_cls.meta is None:
            print(f"[senpy.plugins] WARNING: Plugin '{entry.name}' has no meta. "
                  f"Skipping registration.", file=sys.stderr)
            continue
        code = rule_cls.meta.code
        # Register (same as @register_rule decorator does)
        _REGISTERED_LINT_RULES.append((code, rule_cls))
