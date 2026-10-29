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

In 0.6.0 Заход 2 (EXT-1), this registry will be populated from:
1. Built-in rules (declared with @register_rule in senpy source)
2. External plugins (discovered via [project.entry-points."senpy.plugins"])

For now (Заход 1), only #1 works — @register_rule in code.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from senpy.plugins.base import Rule


# =============================================================================
# Registry
# =============================================================================

# Module-level registry: list of (code, rule_cls) tuples.
# Using list (not dict) to preserve registration order (matches formatter).
_REGISTERED_LINT_RULES: list[tuple[str, type[Rule]]] = []


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
        # Validate that rule_cls subclasses Rule
        # (import here to avoid circular import at module load)
        from senpy.plugins.base import Rule as _Rule

        if not issubclass(rule_cls, _Rule):
            raise TypeError(
                f"@register_rule can only decorate subclasses of Rule, "
                f"got: {rule_cls.__name__} (bases: {rule_cls.__bases__})"
            )

        # Register (code, rule_cls) tuple
        _REGISTERED_LINT_RULES.append((code, rule_cls))
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
