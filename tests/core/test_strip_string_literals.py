"""Tests for `strip_string_literals()` helper.

This helper is the architectural investment of Sprint 1 (Pattern 4 cluster):
every checker that does a substring check or regex scan on an arbitrary
Ren'Py line must apply it first, so that string-literal contents (dialogue,
Python string constants, image names) are masked out and cannot produce
false positives.

Contract:
    - Replace the *content* of `"..."` and `'...'` literals with spaces
      (one space per source character inside the quotes), preserving
      column positions so UTF-16 ranges and regex offsets remain valid
      for code outside the literals.
    - Preserve escape sequences: `\"`, `\'`, `\\` — these stay literal
      so the consumer can still tell that a quote was escaped.
    - Recognise triple-quoted strings.
    - Lines without quotes are returned unchanged.
    - Unclosed strings are handled defensively: the trailing content from
      the opening quote to the end of line is masked.

Edge cases that must NOT crash:
    - backslash at end of line
    - empty string literal `""`
    - triple-quote opened but not closed
    - mixed quote styles on one line
"""

from __future__ import annotations

import pytest

from senpy.text_utils import strip_string_literals


class TestStripStringLiteralsBasicContract:
    """The function must mask literal contents and preserve positions."""

    def test_no_quotes_returned_unchanged(self) -> None:
        assert strip_string_literals("jump start") == "jump start"

    def test_double_quoted_content_masked_with_spaces(self) -> None:
        result = strip_string_literals('e "Hello, world!"')
        # The content between quotes becomes spaces, length unchanged.
        assert len(result) == len('e "Hello, world!"')
        assert result == 'e "             "'

    def test_single_quoted_content_masked_with_spaces(self) -> None:
        result = strip_string_literals("$ x = 'foo'")
        assert result == "$ x = '   '"

    def test_positions_preserved_code_outside_literals(self) -> None:
        # Code before and after the literal must stay at the same column.
        line = 'action Jump("missing")'
        result = strip_string_literals(line)
        assert result == 'action Jump("       ")'
        # The 'Jump(' part is at columns 0-5 — preserved.
        assert result[:6] == line[:6]
        # The closing ')' is at column 22 — preserved.
        assert result[-1] == ")"

    def test_length_preserved(self) -> None:
        line = "text \"Press Show('missing_screen') to continue.\""
        result = strip_string_literals(line)
        assert len(result) == len(line)


class TestStripStringLiteralsEscapes:
    """Escaped quotes must not terminate the literal — they stay literal."""

    def test_escaped_double_quote_inside_double_string(self) -> None:
        # `\"` inside a `"..."` literal must not close the literal.
        line = r'$ x = "say \"hi\""'
        result = strip_string_literals(line)
        # The escaped quotes stay literal; everything else inside is masked.
        assert "\\" in result  # backslash preserved
        assert '"' in result  # the escaped quotes preserved
        # The closing quote at the very end is preserved.
        assert result.endswith('"')

    def test_escaped_single_quote_inside_single_string(self) -> None:
        line = r"$ x = 'don\'t'"
        result = strip_string_literals(line)
        assert "\\" in result

    def test_backslash_at_end_of_string_does_not_crash(self) -> None:
        # Trailing backslash: don't index past end of line.
        line = '$ x = "trailing\\'
        # Must not raise.
        result = strip_string_literals(line)
        assert isinstance(result, str)
        assert len(result) == len(line)


class TestStripStringLiteralsTriples:
    """Triple-quoted strings must be recognised."""

    def test_triple_double_quote_recognised(self) -> None:
        # Single line case — opens triple, content masked.
        # We test on a single-line representation; multi-line handling is
        # caller's responsibility (caller passes one line at a time).
        single = '$ x = """abc"""'
        result = strip_string_literals(single)
        assert result == '$ x = """   """'

    def test_triple_single_quote_recognised(self) -> None:
        single = "$ x = '''abc'''"
        result = strip_string_literals(single)
        assert result == "$ x = '''   '''"


class TestStripStringLiteralsMixedAndEmpty:
    """Edge cases that must not crash or silently corrupt code."""

    def test_empty_string_literal(self) -> None:
        # `""` — no content between quotes, output identical.
        assert strip_string_literals('$ x = ""') == '$ x = ""'

    def test_two_literals_on_one_line(self) -> None:
        line = 'action Jump("foo"), Call("bar")'
        result = strip_string_literals(line)
        assert result == 'action Jump("   "), Call("   ")'

    def test_mixed_single_and_double_quotes(self) -> None:
        line = """$ x = "double" + 'single\'"""
        result = strip_string_literals(line)
        # Both literals masked, length preserved.
        assert len(result) == len(line)
        assert result.count('"') == 2  # outer double quotes preserved
        assert result.count("'") == 2  # outer single quotes preserved

    def test_unclosed_string_handled_defensively(self) -> None:
        # An unclosed literal — the rest of the line is masked, no crash.
        line = 'text "never closed'
        result = strip_string_literals(line)
        # The opening quote and the prefix are preserved.
        assert result.startswith('text "')
        assert len(result) == len(line)


class TestStripStringLiteralsUseCases:
    """Concrete use cases that motivated the helper — false positives where
    a substring check matches an identifier that lives inside a string
    literal (dialogue, Python string constant, image name).
    """

    def test_jump_inside_dialogue_text_masked(self) -> None:
        # Reproducer: a dialogue line mentioning `Jump('missing_label')`.
        # After stripping, "Jump(" must NOT appear as a code call.
        line = '''"The syntax Jump('missing_label') is interesting."'''
        result = strip_string_literals(line)
        assert "Jump(" not in result
        assert "missing_label" not in result

    def test_setvariable_inside_dialogue_text_masked(self) -> None:
        # Reproducer: `text "Press SetVariable('undeclared_var', 1) to debug."`
        line = '''text "Press SetVariable('undeclared_var', 1) to debug."'''
        result = strip_string_literals(line)
        assert "SetVariable(" not in result
        assert "undeclared_var" not in result

    def test_show_inside_dialogue_text_masked(self) -> None:
        # Reproducer: `text "Press Show('missing_screen') to continue."`
        line = '''text "Press Show('missing_screen') to continue."'''
        result = strip_string_literals(line)
        assert "Show(" not in result
        assert "missing_screen" not in result

    def test_renpy_jump_in_dialogue_masked(self) -> None:
        # False-positive case: `e "Use renpy.jump() to switch scenes."`
        line = '''e "Use renpy.jump() to switch scenes."'''
        result = strip_string_literals(line)
        assert "renpy.jump" not in result

    def test_label_name_in_string_does_not_become_referenced(self) -> None:
        # Reproducer: `$ config.label_overrides = "unused_label"`
        # After stripping, `unused_label` must not be visible to a regex
        # that searches for `["']([^\W\d]\w*)["\']`.
        line = '$ config.label_overrides = "unused_label"'
        result = strip_string_literals(line)
        # A regex `["\']([^\W\d]\w*)["\']` should not match `unused_label`
        # in the masked result because the content is spaces.
        import re

        RE_QUOTED_IDENTIFIER = re.compile(r'["\']([^\W\d]\w*)["\']')
        match = RE_QUOTED_IDENTIFIER.search(result)
        # Either no match, or the captured group is spaces (which the
        # regex `[^\W\d]\w*` cannot match because spaces are not in
        # `[^\W\d]`), so effectively: no match.
        assert match is None or not match.group(1).strip()


class TestStripStringLiteralsRealRenpyJumpsPreserved:
    """Critical counter-case: real code calls outside string literals must
    survive the strip — the helper only masks literal contents, not code.
    """

    def test_real_renpy_jump_in_python_block_preserved(self) -> None:
        # Counter-case — `renpy.jump(target)` outside string.
        line = "$ renpy.jump(target)"
        result = strip_string_literals(line)
        assert "renpy.jump(" in result  # code preserved
        assert "target" in result  # variable name preserved

    def test_real_jump_action_in_screen_preserved(self) -> None:
        line = 'textbutton "Go" action Jump("start")'
        result = strip_string_literals(line)
        # The dialogue "Go" is masked; the Jump("start") is partially masked
        # (its argument "start" is inside quotes), but `Jump(` itself is
        # outside any literal — must be preserved.
        assert "Jump(" in result
        # The "start" inside Jump's argument is now spaces — but Jump( is
        # detectable, which is the point.
        assert "start" not in result

    def test_real_show_in_screen_preserved(self) -> None:
        line = 'textbutton "Legit" action Show("inventory_hud")'
        result = strip_string_literals(line)
        assert "Show(" in result
        # "Legit" masked, "inventory_hud" masked — that's the contract.
        assert "Legit" not in result
        assert "inventory_hud" not in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
