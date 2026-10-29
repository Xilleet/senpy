"""Tests for 0.6.0 Под-спринт 1: senpy.api public module + FMT-QUOTES/OP-SPACING/COMMA-SPACING/COLON-SPACING.

senpy.api — explicitly public API module.
  - Diagnostic, RULE_SEVERITY, AnalysisResult (re-exported from core.models)
  - Location (NEW: simple dataclass for line:col position)
  - analyze_code(code: str) -> list[Diagnostic] — high-level one-liner API
  - This module is the STABLE public contract for plugin developers.

FMT-QUOTES — smart quotes (U+2018..U+201F) → straight quotes in CODE statements.
       Does NOT touch dialogue strings (those are display text, smart quotes are stylistic).

FMT-OP-SPACING — $ x=1+2 → $ x = 1 + 2 (binary operators, not unary).
       Respects strings — no spaces added inside "..." quotes.

FMT-COMMA-SPACING — f(a,b,c) → f(a, b, c). Also: [a,b] → [a, b], {a,b} → {a, b}.

FMT-COLON-SPACING — if x : → if x: and def f() : → def f():. NOT menu: (Ren'Py menu: must stay as-is).

Idempotency tests on each new rule.
"""
from __future__ import annotations

import pytest

# =============================================================================
# senpy.api public module
# =============================================================================


class TestSenpyApiModule:
    """senpy.api — explicitly public API for plugin developers and library users.

    This module is the STABLE public contract. Internal modules (senpy.core.*,
    senpy.rules.*, etc.) may change between minor versions, but senpy.api
    must stay backward-compatible.
    """

    def test_api_module_exists(self):
        """senpy.api module must exist as the public entry point."""
        import senpy.api
        assert senpy.api is not None

    def test_diagnostic_re_exported(self):
        """Diagnostic must be re-exported from senpy.api."""
        from senpy.api import Diagnostic
        from senpy.core.models import Diagnostic as CoreDiagnostic
        assert Diagnostic is CoreDiagnostic, (
            "senpy.api.Diagnostic must be the same object as senpy.core.models.Diagnostic"
        )

    def test_rule_severity_re_exported(self):
        """RULE_SEVERITY dict must be re-exported from senpy.api."""
        from senpy.api import RULE_SEVERITY
        from senpy.core.models import RULE_SEVERITY as CoreRuleSeverity  # noqa: N811
        assert RULE_SEVERITY is CoreRuleSeverity

    def test_analysis_result_re_exported(self):
        """AnalysisResult must be re-exported from senpy.api."""
        from senpy.api import AnalysisResult
        assert AnalysisResult is not None

    def test_analyze_code_function_exists(self):
        """analyze_code(code: str) -> list[Diagnostic] — high-level one-liner API.

        This is the canonical way for external code (plugins, scripts, notebooks)
        to lint a snippet of .rpy code without setting up SenpyAnalyzer.
        """
        from senpy.api import analyze_code
        assert callable(analyze_code)

    def test_analyze_code_returns_list_of_diagnostics(self):
        """analyze_code() must return list[Diagnostic] for a simple input."""
        from senpy.api import Diagnostic, analyze_code
        code = 'label start:\n    "Hello, [unknown_var]!"\n    jump nonexistent\n    return\n'
        result = analyze_code(code)
        assert isinstance(result, list), f"Expected list, got {type(result)}"
        assert all(isinstance(d, Diagnostic) for d in result), (
            f"All items must be Diagnostic, got {[type(d).__name__ for d in result]}"
        )
        # Should detect RPY101 (unknown_var) and RPY302 (nonexistent label)
        codes = {d.code for d in result}
        assert "RPY101" in codes, f"Expected RPY101 in {codes}"
        assert "RPY302" in codes, f"Expected RPY302 in {codes}"

    def test_analyze_code_empty_input(self):
        """analyze_code() on empty input returns empty list, not None or error."""
        from senpy.api import analyze_code
        assert analyze_code("") == []
        assert analyze_code("    ") == []

    def test_analyze_code_clean_input(self):
        """analyze_code() on already-clean code returns empty list (no diagnostics)."""
        from senpy.api import analyze_code
        code = 'label start:\n    "Hello"\n    return\n'
        result = analyze_code(code)
        assert result == [], f"Clean code should produce no diagnostics, got {result}"

    def test_location_dataclass_exists(self):
        """Location dataclass for line:col positions (used by plugins)."""
        from senpy.api import Location
        loc = Location(line=5, character=10)
        assert loc.line == 5
        assert loc.character == 10

    def test_api_all_exports(self):
        """__all__ must list all public names (for `from senpy.api import *`)."""
        import senpy.api
        expected = {"Diagnostic", "RULE_SEVERITY", "AnalysisResult", "Location", "analyze_code"}
        assert expected.issubset(set(senpy.api.__all__)), (
            f"Missing from __all__: {expected - set(senpy.api.__all__)}"
        )


# =============================================================================
# FMT-QUOTES — smart quotes → straight quotes in code
# =============================================================================


class TestFmtQuotes:
    """FMT-QUOTES: smart/curly quotes (“ ” ‘ ’ « ») in CODE statements → straight (" ').

    Critical: does NOT touch dialogue lines. In Ren'Py:
        "Hello, “world”!"  →  DIALOGUE, smart quotes preserved (stylistic)
        $ x = “active”     →  CODE, smart quotes replaced with "active"

    Dialogue detection: a line is "dialogue" if its first non-whitespace char
    is " or ' (Ren'Py dialogue convention).
    """

    def test_smart_double_quotes_in_code(self):
        """$ status = “active” → $ status = "active"."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = '$ status = \u201cactive\u201d\n'
        result = fmt.format_code(code)
        assert '\u201c' not in result, f"Smart quote not replaced: {result!r}"
        assert '\u201d' not in result
        assert '"active"' in result

    def test_smart_single_quotes_in_code(self):
        """$ x = ‘value’ → $ x = 'value'."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "$ x = \u2018value\u2019\n"
        result = fmt.format_code(code)
        assert '\u2018' not in result
        assert '\u2019' not in result
        assert "'value'" in result

    def test_dialogue_smart_quotes_preserved(self):
        """Smart quotes in dialogue (line starts with ") must be PRESERVED."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = '    "She said \u201chello\u201d to him."\n'
        result = fmt.format_code(code)
        # Smart quotes in dialogue are stylistic, do not replace
        assert '\u201c' in result, f"Dialogue smart quote should be preserved: {result!r}"
        assert '\u201d' in result

    def test_idempotent(self):
        """FMT-QUOTES: format(format(x)) == format(x)."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = '$ x = \u201ctest\u201d\n$ y = \u2018single\u2019\n'
        once = fmt.format_code(code)
        twice = fmt.format_code(once)
        assert once == twice, f"Not idempotent:\n--- once ---\n{once}\n--- twice ---\n{twice}"


# =============================================================================
# FMT-OP-SPACING — binary operators
# =============================================================================


class TestFmtOpSpacing:
    """FMT-OP-SPACING: $ x=1+2 → $ x = 1 + 2.

    Rules:
    - Binary operators: + - * / % = == != < > <= >= += -= *= /= // ** << >> &
    - Unary minus/plus preserved: -5, +x, not -x → -5
    - Strings preserved: "$ x = 'a=b'" — no change inside '...'
    - Skip blocks: # senpy: format off ... untouched
    """

    def test_simple_assignment(self):
        """$ x=1 → $ x = 1."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "$ x=1\n"
        result = fmt.format_code(code)
        assert "$ x = 1" in result, f"Expected '$ x = 1', got: {result!r}"

    def test_arithmetic(self):
        """$ x=1+2*3 → $ x = 1 + 2 * 3."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "$ x=1+2*3\n"
        result = fmt.format_code(code)
        assert "$ x = 1 + 2 * 3" in result, f"Got: {result!r}"

    def test_augmented_assignment(self):
        """$ x+=1 → $ x += 1."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "$ x+=1\n"
        result = fmt.format_code(code)
        assert "$ x += 1" in result, f"Got: {result!r}"

    def test_unary_minus_preserved(self):
        """$ x = -5 → $ x = -5 (NOT $ x = - 5)."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "$ x=-5\n"
        result = fmt.format_code(code)
        assert "-5" in result, f"Unary minus should be preserved: {result!r}"
        assert "- 5" not in result, f"Unary minus should NOT be spaced: {result!r}"

    def test_string_content_preserved(self):
        """Strings: $ x = 'a=b' → unchanged (no space added inside string)."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "$ x = 'a=b'\n"
        result = fmt.format_code(code)
        assert "'a=b'" in result, f"String content should be preserved: {result!r}"
        assert "'a = b'" not in result

    def test_idempotent(self):
        """FMT-OP-SPACING: format(format(x)) == format(x)."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "$ x=1+2\n$ y =3*4-5\n$ z=a*b+c\n"
        once = fmt.format_code(code)
        twice = fmt.format_code(once)
        assert once == twice, f"Not idempotent:\n--- once ---\n{once}\n--- twice ---\n{twice}"


# =============================================================================
# FMT-COMMA-SPACING
# =============================================================================


class TestFmtCommaSpacing:
    """FMT-COMMA-SPACING: f(a,b,c) → f(a, b, c). Also: [a,b], {a,b}.

    Rules:
    - Comma followed by non-space: insert space (a,b → a, b)
    - Comma followed by space: leave (a, b → a, b)
    - Comma at end of line: leave (a,\n → a,\n)
    - Trailing comma in last position: leave (f(a,) → f(a,))
    - Strings preserved: no change inside "..." or '...'
    """

    def test_function_args(self):
        """f(a,b,c) → f(a, b, c)."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "$ x = f(a,b,c)\n"
        result = fmt.format_code(code)
        assert "f(a, b, c)" in result, f"Got: {result!r}"

    def test_list_literal(self):
        """$ x = [1,2,3] → $ x = [1, 2, 3]."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "$ x = [1,2,3]\n"
        result = fmt.format_code(code)
        assert "[1, 2, 3]" in result, f"Got: {result!r}"

    def test_dict_literal(self):
        """$ x = {a:1,b:2} → $ x = {a:1, b:2}."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "$ x = {1:2,3:4}\n"
        result = fmt.format_code(code)
        assert ", " in result
        assert ",3" not in result or "'{}'" in result  # no comma-without-space

    def test_already_spaced(self):
        """f(a, b, c) → f(a, b, c) (no change, idempotent)."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "$ x = f(a, b, c)\n"
        result = fmt.format_code(code)
        assert "f(a, b, c)" in result

    def test_string_content_preserved(self):
        """$ x = 'a,b,c' → unchanged."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "$ x = 'a,b,c'\n"
        result = fmt.format_code(code)
        assert "'a,b,c'" in result
        assert "'a, b, c'" not in result

    def test_idempotent(self):
        """FMT-COMMA-SPACING: format(format(x)) == format(x)."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "$ x = f(a,b,c)\n$ y = [1,2,3]\n$ z = {1:2,3:4,5:6}\n"
        once = fmt.format_code(code)
        twice = fmt.format_code(once)
        assert once == twice


# =============================================================================
# FMT-COLON-SPACING
# =============================================================================


class TestFmtColonSpacing:
    """FMT-COLON-SPACING: if x : → if x:, def f() : → def f():.

    Rules:
    - " :" before block opener → ":"  (remove space before colon)
    - "( ):" → "():" — no space inside empty parens before colon
    - "menu :" → "menu:" (Ren'Py menu: block opener)
    - "label start :" → "label start:" 
    - Dict literal: {a:1} NOT touched (colon in dict has no space anyway)
    - Slice: x[1:2] NOT touched (colon in slice)
    - Strings preserved
    """

    def test_if_with_space_before_colon(self):
        """if x : → if x:"""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "if x :\n    pass\n"
        result = fmt.format_code(code)
        assert "if x:" in result, f"Got: {result!r}"
        assert "if x :" not in result

    def test_function_def(self):
        """def f() : → def f():"""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "init python:\n    def f() :\n        return 1\n"
        result = fmt.format_code(code)
        assert "def f():" in result, f"Got: {result!r}"

    def test_label_with_space_before_colon(self):
        """label start : → label start:"""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "label start :\n    return\n"
        result = fmt.format_code(code)
        assert "label start:" in result, f"Got: {result!r}"

    def test_menu_with_space_before_colon(self):
        """menu : → menu:"""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "menu :\n    \"Option\":\n        pass\n"
        result = fmt.format_code(code)
        assert "menu:" in result, f"Got: {result!r}"

    def test_dict_colon_not_touched(self):
        """$ x = {a:1} → unchanged (dict colon has no space, formatter shouldn't add or remove)."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "$ x = {1:2}\n"
        result = fmt.format_code(code)
        assert "{1:2}" in result, f"Dict colon should be preserved: {result!r}"

    def test_slice_not_touched(self):
        """$ x = a[1:2] → unchanged (slice colon, no space)."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "$ x = a[1:2]\n"
        result = fmt.format_code(code)
        assert "a[1:2]" in result, f"Slice should be preserved: {result!r}"

    def test_string_content_preserved(self):
        """Strings: $ x = 'a:b' → unchanged."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "$ x = 'a:b'\n"
        result = fmt.format_code(code)
        assert "'a:b'" in result
        assert "'a : b'" not in result

    def test_idempotent(self):
        """FMT-COLON-SPACING: format(format(x)) == format(x)."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        code = "if x :\n    pass\nlabel start :\n    return\n"
        once = fmt.format_code(code)
        twice = fmt.format_code(once)
        assert once == twice


# =============================================================================
# Cross-rule idempotency + interaction
# =============================================================================


class TestFmtCombinedIdempotency:
    """All 4 new rules + existing rules combined — idempotency + no regressions."""

    @pytest.fixture
    def fmt(self):
        from senpy.formatter import FormatConfig, Formatter
        return Formatter(FormatConfig())

    def test_combined_idempotency(self, fmt):
        """Realistic .rpy with quotes, ops, commas, colons — format(format(x)) == format(x)."""
        code = (
            'label start:\n'
            '    $ x=\u201cactive\u201d\n'           # smart quotes in code
            '    $ y =1+2*3\n'                       # missing op spacing
            '    $ z = f(a,b,c)\n'                   # missing comma spacing
            '    if x :\n'                            # space before colon
            '        "Hello, [name]!"\n'              # dialogue, smart quotes preserved
            '    return\n'
        )
        once = fmt.format_code(code)
        twice = fmt.format_code(once)
        assert once == twice, (
            f"Combined idempotency broken:\n--- once ---\n{once}\n--- twice ---\n{twice}"
        )

    def test_combined_makes_expected_changes(self, fmt):
        """All 4 fixes apply correctly on combined input."""
        code = (
            'label start:\n'
            '    $ status = \u201cactive\u201d\n'
            '    $ result=1+2\n'
            '    $ items = [1,2,3]\n'
            '    if status :\n'
            '        "Hi"\n'
            '    return\n'
        )
        result = fmt.format_code(code)

        # FMT-QUOTES: smart quotes in code → straight
        assert '\u201c' not in result or '"Hi"' in result.split('\n')[5]  # dialogue ok
        assert '"active"' in result, f"FMT-QUOTES failed: {result!r}"

        # FMT-OP-SPACING: 1+2 → 1 + 2
        assert "1 + 2" in result, f"FMT-OP-SPACING failed: {result!r}"

        # FMT-COMMA-SPACING: [1,2,3] → [1, 2, 3]
        assert "[1, 2, 3]" in result, f"FMT-COMMA-SPACING failed: {result!r}"

        # FMT-COLON-SPACING: if status : → if status:
        assert "if status:" in result, f"FMT-COLON-SPACING failed: {result!r}"
        assert "if status :" not in result

    def test_skip_block_untouched(self, fmt):
        """# senpy: format off ... on — все 4 правила НЕ трогают содержимое skip-блока."""
        code = (
            '# senpy: format off\n'
            '$ x=\u201cactive\u201d y=1+2 z=f(a,b,c) if x :\n'
            '# senpy: format on\n'
        )
        result = fmt.format_code(code)
        # Skip block content must be unchanged
        assert '\u201cactive\u201d' in result, f"Skip block touched quotes: {result!r}"
        assert "y=1+2" in result, f"Skip block touched ops: {result!r}"
        assert "f(a,b,c)" in result, f"Skip block touched commas: {result!r}"
        assert "if x :" in result, f"Skip block touched colons: {result!r}"
