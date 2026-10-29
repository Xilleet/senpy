"""Tests for 0.6.0 Под-спринт 2 (Заход 1): Plugin system foundation.

Rule base class with RuleMeta (docs, severity, fixable, tags, deprecated).
@register_rule("RPYxxx") decorator for lint rules (similar to formatter's).
Plugin API version check — plugins must declare api_version, Senpy verifies compatibility.

This is the FOUNDATION for plugin system. entry_points loading (EXT-1) and
trust-on-first-use (SEC-P2) come in Заход 2.

Architecture:
    senpy/plugins/                 # NEW subpackage
    ├── __init__.py
    ├── base.py                    # EXT-3: Rule, RuleMeta, RuleContext
    ├── registry.py                # EXT-2: @register_rule, get_registered_lint_rules
    └── security.py                # SEC-P1: PLUGIN_API_VERSION, check_api_version
"""
from __future__ import annotations

import pytest

# =============================================================================
# Rule base class + RuleMeta
# =============================================================================


class TestRuleBaseClass:
    """EXT-3: Rule base class for lint rules.

    Plugin developers subclass Rule to define new lint rules:

        from senpy.plugins.base import Rule, RuleMeta

        class MyRule(Rule):
            meta = RuleMeta(
                code="RPY901",
                docs="Detect unused variables in init python blocks",
                severity="WARNING",
                fixable=False,
                tags=["dead-code", "performance"],
            )

            def check(self, ctx: RuleContext) -> list[Diagnostic]:
                # ctx.file_path, ctx.lines, ctx.symbols, ...
                ...
                return diagnostics
    """

    def test_rule_base_class_exists(self):
        """Rule base class must exist in senpy.plugins.base."""
        from senpy.plugins.base import Rule
        assert Rule is not None

    def test_rule_meta_dataclass_exists(self):
        """RuleMeta dataclass with required fields (ESLint-style)."""
        from senpy.plugins.base import RuleMeta
        meta = RuleMeta(
            code="RPY901",
            docs="Test rule",
            severity="WARNING",
        )
        assert meta.code == "RPY901"
        assert meta.docs == "Test rule"
        assert meta.severity == "WARNING"
        # Optional fields with defaults
        assert meta.fixable is False
        assert meta.tags == []
        assert meta.deprecated is False
        assert meta.replaced_by is None

    def test_rule_meta_severity_must_be_valid(self):
        """RuleMeta.severity must be one of ERROR/WARNING/HINT/INFO."""
        from senpy.plugins.base import RuleMeta
        for valid_severity in ("ERROR", "WARNING", "HINT", "INFO"):
            meta = RuleMeta(code="RPY999", docs="x", severity=valid_severity)
            assert meta.severity == valid_severity

    def test_rule_meta_invalid_severity_raises(self):
        """RuleMeta.severity = "FATAL" must raise ValueError."""
        from senpy.plugins.base import RuleMeta
        with pytest.raises(ValueError, match="severity"):
            RuleMeta(code="RPY999", docs="x", severity="FATAL")

    def test_rule_meta_deprecated_with_replaced_by(self):
        """Deprecated rule can declare replacement."""
        from senpy.plugins.base import RuleMeta
        meta = RuleMeta(
            code="RPY999",
            docs="Old rule",
            severity="WARNING",
            deprecated=True,
            replaced_by="RPY100",
        )
        assert meta.deprecated is True
        assert meta.replaced_by == "RPY100"

    def test_rule_subclass_must_implement_check(self):
        """Rule.check() must be overridden by subclass."""
        from senpy.plugins.base import Rule, RuleContext

        class MyRule(Rule):
            meta = None  # set in __init__ for test

            def __init__(self):
                self.meta = type("M", (), {"code": "RPY999", "docs": "x", "severity": "WARNING"})()

        rule = MyRule()
        # Base Rule.check() should raise NotImplementedError
        ctx = RuleContext(file_path="test.rpy", lines=[], symbols={})
        with pytest.raises(NotImplementedError):
            rule.check(ctx)

    def test_rule_meta_code_must_match_rpy_pattern(self):
        """RuleMeta.code must be RPY\\d{3} format."""
        from senpy.plugins.base import RuleMeta
        # Valid codes
        for code in ("RPY001", "RPY101", "RPY999"):
            meta = RuleMeta(code=code, docs="x", severity="WARNING")
            assert meta.code == code
        # Invalid codes must raise
        with pytest.raises(ValueError, match="code"):
            RuleMeta(code="X001", docs="x", severity="WARNING")
        with pytest.raises(ValueError, match="code"):
            RuleMeta(code="RPY99", docs="x", severity="WARNING")
        with pytest.raises(ValueError, match="code"):
            RuleMeta(code="RPY9999", docs="x", severity="WARNING")


# =============================================================================
# @register_rule decorator for lint rules
# =============================================================================


class TestRegisterRuleDecorator:
    """EXT-2: @register_rule decorator for lint rules.

    Similar to formatter's @register_rule, but for lint rules.

    Usage:
        from senpy.plugins.base import Rule, RuleMeta
        from senpy.plugins.registry import register_rule

        @register_rule("RPY901")
        class MyRule(Rule):
            meta = RuleMeta(code="RPY901", docs="...", severity="WARNING")
            def check(self, ctx):
                ...
    """

    def test_register_rule_decorator_exists(self):
        """@register_rule must be importable from senpy.plugins.registry."""
        from senpy.plugins.registry import register_rule
        assert callable(register_rule)

    def test_register_rule_returns_class(self):
        """@register_rule decorator returns the class unchanged (just registers it)."""
        from senpy.plugins.base import Rule, RuleMeta
        from senpy.plugins.registry import register_rule

        @register_rule("RPY901")
        class TestRule(Rule):
            meta = RuleMeta(code="RPY901", docs="test", severity="WARNING")

            def check(self, ctx):
                return []

        # Decorator should return the class itself
        assert TestRule.__name__ == "TestRule"
        assert issubclass(TestRule, Rule)

    def test_register_rule_rejects_non_rule_class(self):
        """@register_rule must reject classes that don't subclass Rule."""
        from senpy.plugins.registry import register_rule

        class NotARule:
            pass

        with pytest.raises(TypeError, match="Rule"):
            register_rule("RPY901")(NotARule)

    def test_get_registered_lint_rules_returns_list(self):
        """get_registered_lint_rules() returns list of (code, rule_cls) tuples."""
        from senpy.plugins.registry import get_registered_lint_rules
        rules = get_registered_lint_rules()
        assert isinstance(rules, list)
        # Each entry is (code: str, rule_cls: type[Rule])
        for entry in rules:
            assert isinstance(entry, tuple)
            assert len(entry) == 2
            assert isinstance(entry[0], str)
            assert isinstance(entry[1], type)

    def test_registered_rule_appears_in_registry(self):
        """When we @register_rule a class, it appears in get_registered_lint_rules()."""
        from senpy.plugins.base import Rule, RuleMeta
        from senpy.plugins.registry import get_registered_lint_rules, register_rule

        @register_rule("RPY901")
        class MyUniqueTestRule(Rule):
            meta = RuleMeta(code="RPY901", docs="test", severity="WARNING")

            def check(self, ctx):
                return []

        codes = [code for code, _ in get_registered_lint_rules()]
        assert "RPY901" in codes


# =============================================================================
# Plugin API version check
# =============================================================================


class TestPluginApiVersion:
    """SEC-P1: Plugin API version check.

    Each plugin must declare which Senpy plugin API version it was built against.
    Senpy verifies compatibility before loading the plugin.

    Why: if we change Rule.check() signature or RuleMeta fields in 0.7.0,
    plugins built for 0.6.0 will silently break at runtime. With api_version,
    we can show a clear error: "Plugin X requires Senpy plugin API 1.0,
    but you have 2.0. Please update the plugin."

    Versioning scheme (semver-like):
    - Major bump: breaking change (Rule.check() signature changed, RuleMeta field removed)
    - Minor bump: new optional field added to RuleMeta (backward-compatible)
    - Patch bump: bug fix in plugin loading logic (no API change)

    Initial version: "1.0"
    """

    def test_plugin_api_version_constant_exists(self):
        """PLUGIN_API_VERSION constant must be defined in senpy.plugins.security."""
        from senpy.plugins.security import PLUGIN_API_VERSION
        assert isinstance(PLUGIN_API_VERSION, str)
        # Initial version
        assert PLUGIN_API_VERSION == "1.0"

    def test_check_api_version_compatible(self):
        """Plugin declaring same major.minor as Senpy → compatible."""
        from senpy.plugins.security import PLUGIN_API_VERSION, check_api_version
        # Plugin version matches Senpy version
        assert check_api_version(PLUGIN_API_VERSION) is True

    def test_check_api_version_minor_higher_compatible(self):
        """Plugin declaring higher minor than Senpy → compatible (new optional fields)."""
        from senpy.plugins.security import check_api_version
        # Plugin built for 1.5, Senpy has 1.0 — plugin might use fields we don't know,
        # but since they're optional additions, it's OK
        # Actually: this is NOT compatible — plugin expects newer API than Senpy provides.
        # Plugin 1.5 might use RuleMeta field that doesn't exist in Senpy 1.0.
        assert check_api_version("1.5") is False

    def test_check_api_version_major_mismatch_incompatible(self):
        """Plugin declaring different major than Senpy → incompatible."""
        from senpy.plugins.security import PLUGIN_API_VERSION, check_api_version
        # Plugin built for 2.0, Senpy has 1.x
        assert check_api_version("2.0") is False
        # Plugin built for 1.0, Senpy has 2.x (hypothetical future)
        # We can't test this without changing PLUGIN_API_VERSION, so we test the inverse:
        # If Senpy has 2.0 and plugin has 1.0, plugin might use old API — incompatible.
        # check_api_version("1.0") with PLUGIN_API_VERSION="2.0" → False
        # (we trust PLUGIN_API_VERSION is "1.0" for now)

    def test_check_api_version_invalid_format(self):
        """Plugin declaring invalid version format → incompatible."""
        from senpy.plugins.security import check_api_version
        assert check_api_version("invalid") is False
        assert check_api_version("") is False
        assert check_api_version("1") is False  # must be X.Y
        assert check_api_version("1.0.0") is False  # must be X.Y, not X.Y.Z

    def test_api_version_mismatch_error_message(self):
        """When version mismatch, error message includes both versions."""
        from senpy.plugins.security import ApiVersionMismatchError, check_api_version
        with pytest.raises(ApiVersionMismatchError) as exc_info:
            # Force check with mismatched version
            check_api_version("2.0", raise_on_mismatch=True)
        error_msg = str(exc_info.value)
        assert "2.0" in error_msg  # plugin version
        assert "1.0" in error_msg  # senpy version (PLUGIN_API_VERSION)


# =============================================================================
# Integration: Rule + @register_rule + RuleContext
# =============================================================================


class TestRuleContext:
    """RuleContext: data passed to Rule.check() method.

    Provides everything a plugin rule needs to analyze a file:
    - file_path: path to .rpy file being analyzed
    - lines: list of raw lines (with newlines)
    - symbols: dict of all symbols in the project (labels, screens, etc.)
    - analyzer: reference to SenpyAnalyzer for advanced queries (optional)
    """

    def test_rule_context_dataclass_exists(self):
        """RuleContext dataclass with file_path, lines, symbols."""
        from senpy.plugins.base import RuleContext
        ctx = RuleContext(file_path="test.rpy", lines=[], symbols={})
        assert ctx.file_path == "test.rpy"
        assert ctx.lines == []
        assert ctx.symbols == {}

    def test_rule_context_with_real_data(self):
        """RuleContext can hold real .rpy data for analysis."""
        from senpy.plugins.base import RuleContext
        lines = [
            'label start:\n',
            '    "Hello, [name]!"\n',
            '    return\n',
        ]
        symbols = {"labels": {"start": {"line": 1}}, "variables": {"name": "str"}}
        ctx = RuleContext(file_path="game/script.rpy", lines=lines, symbols=symbols)
        assert ctx.lines == lines
        assert ctx.symbols == symbols
        assert ctx.file_path == "game/script.rpy"


class TestRuleEndToEnd:
    """End-to-end: register a rule, instantiate, call check(), get diagnostics."""

    def test_custom_rule_returns_diagnostics(self):
        """A custom @register_rule'd Rule can return Diagnostics from check()."""
        from senpy.api import Diagnostic
        from senpy.plugins.base import Rule, RuleContext, RuleMeta
        from senpy.plugins.registry import register_rule

        @register_rule("RPY999")
        class TestUnusedVarRule(Rule):
            meta = RuleMeta(
                code="RPY999",
                docs="Test rule: flags any line containing 'unused'",
                severity="WARNING",
                tags=["test"],
            )

            def check(self, ctx: RuleContext):
                diags = []
                for i, line in enumerate(ctx.lines, start=1):
                    if "unused" in line.lower():
                        diags.append(Diagnostic(
                            file_path=ctx.file_path,
                            line_number=i,
                            line_content=line,
                            code="RPY999",
                            message="Found 'unused' in line",
                            severity="WARNING",
                        ))
                return diags

        # Instantiate and call
        rule = TestUnusedVarRule()
        ctx = RuleContext(
            file_path="test.rpy",
            lines=['$ x = 1\n', '$ unused_var = 2\n', '"Hi"\n'],
            symbols={},
        )
        diags = rule.check(ctx)

        assert len(diags) == 1
        assert diags[0].code == "RPY999"
        assert diags[0].line_number == 2
        assert diags[0].severity == "WARNING"
