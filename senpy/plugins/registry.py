"""@register_rule decorator for lint rules.

Similar to senpy.formatter.core.register_rule, but for lint rules.

Usage:
    from senpy.plugins import Rule, RuleMeta, register_rule

    @register_rule("RPY901")
    class MyRule(Rule):
        meta = RuleMeta(code="RPY901", docs="...", severity="WARNING")

        def check(self, ctx):
            ...
            return diagnostics

Rules are stored in module-level registry. They can be retrieved via
get_registered_lint_rules() for instantiation by SenpyAnalyzer.

The registry is populated from:
1. Built-in rules (declared with @register_rule in senpy source)
2. External plugins (discovered via [project.entry-points."senpy.plugins"])

Both paths work since 0.7.5 (plugin autoload).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from senpy.core.logging import get_logger

if TYPE_CHECKING:
    from senpy.plugins.base import Rule

_logger = get_logger("plugins.registry")

# =============================================================================
# Constants
# =============================================================================

# Rule code pattern: RPY + 3 digits. Matches the same pattern enforced by
# ``RuleMeta.__post_init__`` in ``base.py`` — duplicated here (rather than
# imported) so ``registry.py`` does not need to import ``base.py`` at module
# load (avoids a circular import: base → registry → base). The two patterns
# are kept in sync by ``test_register_rule_validates_code_format``.
_RE_RULE_CODE = re.compile(r"^RPY\d{3}$")


# =============================================================================
# Registry
# =============================================================================

# Module-level registry: list of (code, rule_cls) tuples.
# Using list (not dict) to preserve registration order (matches formatter).
_REGISTERED_LINT_RULES: list[tuple[str, type[Rule]]] = []


def _register_rule_cls(code: str, rule_cls: type[Rule]) -> bool:
    """Shared validation + registration primitive.

    Used by both ``@register_rule`` (for built-in / decorator-registered
    rules) and ``register_loaded_plugins`` (for plugin entry-point rules).
    Centralising the validation here means the two registration paths
    cannot drift in what they enforce.

    Validation (in order):
        1. ``code`` matches ``RPY\\d{3}`` — caught early before any class
           introspection, so a typo in the decorator argument (e.g.
           ``@register_rule("RPY")`` or ``@register_rule("rpy901")``)
           surfaces with a clear message instead of silently registering
           a rule that ``rule_dispatch`` and the analyzer cannot find.
        2. ``rule_cls`` subclasses ``Rule`` — the documented contract.
        3. ``code`` matches ``rule_cls.meta.code`` — the decorator argument
           and the class attribute must agree. A mismatch indicates either
           a copy-paste bug (rule class copied from another rule but the
           decorator not updated) or a deliberate shadowing attempt (plugin
           trying to override a built-in by passing its code to the
           decorator while keeping a different ``meta.code``).
        4. ``code`` is not already in the registry — duplicate registration
           is a sign of either double-import (e.g. ``@register_rule`` on a
           class imported from two places) or a plugin-vs-plugin collision.
           Warns and skips; the FIRST registration wins (matches
           ``register_loaded_plugins``'s built-in-collision policy).

    Returns ``True`` if the rule was registered, ``False`` if it was
    skipped (with a WARNING log explaining why). Never raises — callers
    that want hard failures on validation (e.g. ``@register_rule`` at
    import time) wrap the call in their own ``raise``.
    """
    # 1. Code format — fast check before any class introspection.
    if not _RE_RULE_CODE.match(code):
        _logger.warning(
            "Cannot register rule %r from %r: code must match RPY\\d{3} "
            "pattern (e.g. 'RPY901'). Skipping.",
            code,
            getattr(rule_cls, "__name__", rule_cls),
        )
        return False

    # 2. Subclass check (import here to avoid circular import at module load).
    from senpy.plugins.base import Rule as _Rule

    if not issubclass(rule_cls, _Rule):
        _logger.warning(
            "Cannot register rule %r from %r: not a subclass of Rule " "(bases: %s). Skipping.",
            code,
            getattr(rule_cls, "__name__", rule_cls),
            getattr(rule_cls, "__bases__", ()),
        )
        return False

    # 3. Decorator code must match RuleMeta.code (if meta is set).
    #    ``rule_cls.meta`` is None for plugins that haven't set it yet —
    #    skip the check in that case (the plugin loader rejects meta-less
    #    rules separately in ``register_loaded_plugins``).
    meta = getattr(rule_cls, "meta", None)
    if meta is not None and meta.code != code:
        _logger.warning(
            "Cannot register rule %r from %r: decorator code %r does not "
            "match RuleMeta.code %r. The two must agree — update either "
            "the decorator argument or the meta.code field. Skipping.",
            code,
            getattr(rule_cls, "__name__", rule_cls),
            code,
            meta.code,
        )
        return False

    # 4. Duplicate detection — first registration wins.
    for existing_code, existing_cls in _REGISTERED_LINT_RULES:
        if existing_code == code:
            _logger.warning(
                "Cannot register rule %r from %r: code already registered "
                "by %r. First registration wins; the duplicate is skipped. "
                "(If this is a plugin-vs-plugin collision, rename one of "
                "the plugins to use a different code. If this is a "
                "double-import, check that the module is not imported "
                "under two names.)",
                code,
                getattr(rule_cls, "__name__", rule_cls),
                getattr(existing_cls, "__name__", existing_cls),
            )
            return False

    _REGISTERED_LINT_RULES.append((code, rule_cls))
    return True


def register_rule(code: str):
    """Decorator to register a lint rule.

    Args:
        code: Rule code (e.g. "RPY901"). Must match RPY\\d{3} pattern.
              Also must match RuleMeta.code in the decorated class.

    Returns:
        Decorator function that returns the class unchanged (just registers it).

    Raises:
        TypeError: If decorated class doesn't subclass Rule.

    Example:
        @register_rule("RPY901")
        class MyRule(Rule):
            meta = RuleMeta(code="RPY901", docs="...", severity="WARNING")
            def check(self, ctx):
                return []
    """

    def decorator(rule_cls: type[Rule]) -> type[Rule]:
        # Delegate to the shared registration primitive. It logs warnings
        # on validation failure and returns False — for the decorator path
        # we want a hard failure (the decorated class is broken and should
        # not silently disappear from the registry), so we raise TypeError
        # to match the original contract on the subclass check.
        registered = _register_rule_cls(code, rule_cls)
        if not registered:
            # Distinguish "not a Rule subclass" (TypeError, original contract)
            # from the other validation failures (which are logged warnings
            # — the decorator returns the class unchanged so import-time
            # code that catches nothing is not surprised by a raise).
            from senpy.plugins.base import Rule as _Rule

            if not issubclass(rule_cls, _Rule):
                raise TypeError(
                    f"@register_rule can only decorate subclasses of Rule, "
                    f"got: {rule_cls.__name__} (bases: {rule_cls.__bases__})"
                )
            # Other validation failures (code format, meta mismatch, dup):
            # logged as WARNING, class returned unchanged. The rule will
            # not appear in get_registered_lint_rules() — downstream code
            # (rule list, analyzer) silently ignores it.
        return rule_cls

    return decorator


def get_registered_lint_rules() -> list[tuple[str, type[Rule]]]:
    """Returns list of (code, rule_cls) tuples in registration order.

    Used by SenpyAnalyzer to instantiate all registered rules and run them
    on each file during analysis.

    Returns:
        List of tuples (code, rule_cls). Each rule_cls is a subclass of Rule.
        Returns a COPY of the internal list (safe to modify).
    """
    return list(_REGISTERED_LINT_RULES)


def clear_registered_lint_rules() -> None:
    """Clear the registry. ONLY for testing — do not use in production.

    Plugin rules registered at import time persist for the process lifetime.
    Tests that register rules need to clean up to avoid polluting other tests.
    """
    _REGISTERED_LINT_RULES.clear()
