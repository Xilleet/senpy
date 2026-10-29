"""senpy.plugins — plugin system for Senpy lint rules.

This subpackage provides the foundation for extending Senpy with custom
lint rules. Plugin developers subclass Rule and register with @register_rule.

Public API (re-exported here for convenience):
    from senpy.plugins import Rule, RuleMeta, RuleContext, register_rule

For high-level public API, use senpy.api instead:
    from senpy.api import Diagnostic, analyze_code

Architecture:
    senpy/plugins/
    ├── base.py        — Rule, RuleMeta, RuleContext (EXT-3)
    ├── registry.py    — @register_rule decorator (EXT-2)
    └── security.py    — PLUGIN_API_VERSION, check_api_version (SEC-P1)

Plugin contract (STABLE — see senpy.api for the full public contract):
    1. Subclass Rule
    2. Set meta = RuleMeta(code="RPYxxx", docs="...", severity="WARNING", ...)
    3. Implement check(self, ctx: RuleContext) -> list[Diagnostic]
    4. Decorate with @register_rule("RPYxxx")

Example:
    from senpy.plugins import Rule, RuleMeta, RuleContext, register_rule
    from senpy.api import Diagnostic

    @register_rule("RPY901")
    class MyRule(Rule):
        meta = RuleMeta(
            code="RPY901",
            docs="Detect hard-coded dialogue strings without _()",
            severity="WARNING",
            fixable=False,
            tags=["translations", "accessibility"],
        )

        def check(self, ctx: RuleContext) -> list[Diagnostic]:
            diags = []
            for i, line in enumerate(ctx.lines, start=1):
                if line.startswith('"') and "_(" not in line:
                    diags.append(Diagnostic(
                        file_path=ctx.file_path,
                        line_number=i,
                        line_content=line,
                        code="RPY901",
                        message="Hard-coded dialogue without _()",
                        severity="WARNING",
                    ))
            return diags
"""
from __future__ import annotations

# Re-exports for convenience — see senpy.api for the canonical public API.
from senpy.plugins.base import Rule, RuleContext, RuleMeta
from senpy.plugins.registry import get_registered_lint_rules, register_rule
from senpy.plugins.security import (
    PLUGIN_API_VERSION,
    check_api_version,
    get_trust_store_path,
    get_trusted_plugins,
    is_plugin_trusted,
    trust_plugin,
    untrust_plugin,
)

__all__ = [
    # EXT-3: Base class + data
    "Rule",
    "RuleMeta",
    "RuleContext",
    # EXT-2: Registration
    "register_rule",
    "get_registered_lint_rules",
    # SEC-P1: API version
    "PLUGIN_API_VERSION",
    "check_api_version",
    # SEC-P2: Trust store
    "is_plugin_trusted",
    "trust_plugin",
    "untrust_plugin",
    "get_trusted_plugins",
    "get_trust_store_path",
]
