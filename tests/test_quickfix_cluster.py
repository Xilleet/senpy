"""Regression tests for QuickFixes that damage user source code.

The QuickFix contract: a Diagnostic that carries `fix_replacement` plus
optionally `fix_start_col`/`fix_end_col` produces an LSP `TextEdit` that
replaces exactly the characters in the range with the replacement
string. If the range and the replacement disagree about whether they
include leading indent, the closing parenthesis of a call, or the
menu-choice colon, the user's source ends up syntactically broken
after they accept the QuickFix.

This file reproduces three such bugs and asserts that, after the fix,
the resulting line (or lines, when the replacement inserts a newline)
is syntactically valid:
    * For ``$`` and ``python:`` statements, the resulting content must
      be parseable as Python (after stripping the ``$`` prefix).
    * For Ren'Py screen/button/menu lines, the resulting content must
      have balanced quotes and brackets.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from _quickfix_sim import apply_quickfix_to_line

from senpy.core.analyzer import SenpyAnalyzer
from senpy.domain.text_tags import get_utf16_range


def _run_analyzer_on(rpy_content: str, tmp_path: Path):
    """Run SenpyAnalyzer on a single .rpy file inside a minimal game/ dir."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "scenario.rpy").write_text(rpy_content, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)
    return result, analyzer


def _first_diag_for(result, code: str):
    matches = [d for d in result.diagnostics if d.code == code and d.fix_replacement]
    assert matches, f"No fixable diagnostic with code {code!r} produced"
    return matches[0]


def _original_line(rpy_content: str, line_number_1_indexed: int) -> str:
    lines = rpy_content.splitlines()
    return lines[line_number_1_indexed - 1]


def _python_statement_parses(text: str) -> bool:
    """True if `text` (a single $-line stripped of `$` and indent) parses
    as a Python statement. Tolerates multiple lines.
    """
    body = text
    if body.lstrip().startswith("$"):
        body = body.lstrip()[1:].lstrip()
    # If multiple lines, dedent each before parsing.
    import textwrap

    body = textwrap.dedent(body)
    try:
        ast.parse(body)
        return True
    except SyntaxError:
        return False


def _balanced_quotes_and_brackets(text: str) -> bool:
    """True if all `"`/`'` quotes and `()`/`[]`/`{}` brackets in `text`
    are balanced when string literals are masked.
    """
    from senpy.text_utils import _count_bracket_delta, strip_string_literals

    masked = strip_string_literals(text)
    # No quote char should remain unbalanced.
    if masked.count('"') % 2 != 0:
        return False
    if masked.count("'") % 2 != 0:
        return False
    return _count_bracket_delta(masked) == 0


# ---------------------------------------------------------------------------
# RPY002 — QuickFix duplicates the line indent
# ---------------------------------------------------------------------------


def test_rpy002_quickfix_does_not_duplicate_indent(tmp_path: Path) -> None:
    """Reproducer: RPY002 QuickFix on a `    $ x = “hello”` line.

    Input line: `    $ x = "hello"`  (4-space indent, smart quote inside).
    Before the fix:
        fix_replacement = '    $ x = "hello"'  (entire line WITH indent)
        fix_start_col/fix_end_col unset → LSP fallback range [4, 17)
        Result: 4 leading spaces preserved + 4 leading spaces inserted = 8.

    After the fix the result must equal the replacement verbatim (no
    indent duplication) and must remain a valid Python statement under `$`.
    """
    rpy = """label start:
    $ x = “hello”
    return
"""
    result, _ = _run_analyzer_on(rpy, tmp_path)
    diag = _first_diag_for(result, "RPY002")

    original_line = _original_line(rpy, diag.line_number)
    assert original_line == "    $ x = “hello”"

    fixed = apply_quickfix_to_line(
        original_line,
        code=diag.code,
        col=diag.col,
        end_col=diag.end_col,
        fix_replacement=diag.fix_replacement,
        fix_start_col=diag.fix_start_col,
        fix_end_col=diag.fix_end_col,
    )

    # The fixed line must be exactly `    $ x = "hello"` — no doubled indent.
    assert fixed == '    $ x = "hello"', (
        f"RPY002 QuickFix produced {fixed!r}; expected exactly the line "
        f"with smart quotes replaced and indent preserved (no doubling)."
    )
    # And it must remain a valid Python statement under `$`.
    assert _python_statement_parses(
        fixed
    ), f"RPY002 QuickFix produced {fixed!r}, which is not valid Python."


# ---------------------------------------------------------------------------
# RPY206 — QuickFix breaks `action myfunc(args)`
# ---------------------------------------------------------------------------


def test_rpy206_quickfix_with_args_produces_valid_action(tmp_path: Path) -> None:
    """Reproducer: RPY206 QuickFix on a `textbutton ... action myfunc(arg1, arg2)` line.

    Input line: `    textbutton "Click" action myfunc(arg1, arg2)`
    Before the fix:
        range = [col of "action myfunc(", col after "(")
        replacement = "Function(myfunc)"
        Result: `    textbutton "Click" Function(myfunc)arg1, arg2)` —
        lost `action ` prefix, leftover `arg1, arg2)` after replacement.

    After the fix the result must be a valid Ren'Py screen line of the
    form `    textbutton "Click" action Function(myfunc, arg1, arg2)`.
    """
    rpy = """screen my_screen():
    textbutton "Click" action myfunc(arg1, arg2)
"""
    result, _ = _run_analyzer_on(rpy, tmp_path)
    diag = _first_diag_for(result, "RPY206")

    original_line = _original_line(rpy, diag.line_number)
    assert "action myfunc(arg1, arg2)" in original_line

    fixed = apply_quickfix_to_line(
        original_line,
        code=diag.code,
        col=diag.col,
        end_col=diag.end_col,
        fix_replacement=diag.fix_replacement,
        fix_start_col=diag.fix_start_col,
        fix_end_col=diag.fix_end_col,
    )

    # The fixed line must contain `action Function(myfunc, ...)` — the
    # `action ` prefix is preserved and the args are wrapped correctly.
    assert (
        "action Function(myfunc" in fixed
    ), f"RPY206 QuickFix lost the `action ` prefix: {fixed!r}"
    assert (
        "myfunc(arg1, arg2)" not in fixed
    ), f"RPY206 QuickFix left the bare call intact: {fixed!r}"
    # No leftover args after the replacement.
    assert not fixed.endswith(")arg1, arg2)"), f"RPY206 QuickFix left trailing args: {fixed!r}"
    # Result must be balanced (quotes and brackets).
    assert _balanced_quotes_and_brackets(
        fixed
    ), f"RPY206 QuickFix produced unbalanced line: {fixed!r}"


def test_rpy206_quickfix_without_args_produces_valid_action(tmp_path: Path) -> None:
    """Symmetric case: `action myfunc()` with no args.

    After the fix: `    textbutton "Heal" action Function(myfunc)`.
    """
    rpy = """screen my_screen():
    textbutton "Heal" action myfunc()
"""
    result, _ = _run_analyzer_on(rpy, tmp_path)
    diag = _first_diag_for(result, "RPY206")

    original_line = _original_line(rpy, diag.line_number)
    fixed = apply_quickfix_to_line(
        original_line,
        code=diag.code,
        col=diag.col,
        end_col=diag.end_col,
        fix_replacement=diag.fix_replacement,
        fix_start_col=diag.fix_start_col,
        fix_end_col=diag.fix_end_col,
    )
    assert "action Function(myfunc)" in fixed
    assert _balanced_quotes_and_brackets(fixed)


# ---------------------------------------------------------------------------
# RPY401 — QuickFix corrupts the menu item
# ---------------------------------------------------------------------------


def test_rpy401_quickfix_inserts_assignment_in_branch_body(tmp_path: Path) -> None:
    """Reproducer: RPY401 QuickFix on a menu with asymmetric branches.

    Input:
        label start:
            menu:
                "Take the left path":
                    $ route = "left"
                "Take the right path":
                    pass

    Before the fix:
        range = position of "Take the right path" (the choice text)
        replacement = "$ route = 0"
        Result: `$ route = 0:` — choice text replaced, dangling colon.

    After the fix the QuickFix must INSERT a new line in the body of
    the missing branch, leaving the choice text intact. The result
    must be valid Ren'Py (choice line intact + indented assignment).
    """
    rpy = """label start:
    menu:
        "Take the left path":
            $ route = "left"
        "Take the right path":
            pass

    return
"""
    result, _ = _run_analyzer_on(rpy, tmp_path)
    diag = _first_diag_for(result, "RPY401")

    original_line = _original_line(rpy, diag.line_number)
    # The diagnostic points at the missing branch's choice line.
    assert '"Take the right path"' in original_line
    assert original_line.rstrip().endswith(":"), (
        f"Diagnostic line_number should point at the choice line (ends "
        f"with ':'); got {original_line!r}"
    )

    fixed = apply_quickfix_to_line(
        original_line,
        code=diag.code,
        col=diag.col,
        end_col=diag.end_col,
        fix_replacement=diag.fix_replacement,
        fix_start_col=diag.fix_start_col,
        fix_end_col=diag.fix_end_col,
    )

    # The choice text MUST remain intact (not replaced by an assignment).
    assert '"Take the right path"' in fixed, f"RPY401 QuickFix destroyed the choice text: {fixed!r}"
    # The line must still end with `:` (the choice line itself unchanged).
    fixed_lines = fixed.splitlines()
    assert (
        fixed_lines[0].rstrip().endswith(":")
    ), f"RPY401 QuickFix broke the choice line: {fixed!r}"
    # A new assignment line must be inserted in the body.
    assert any("$ route = " in ln for ln in fixed_lines[1:]), (
        f"RPY401 QuickFix did not insert `$ route = ...` in the branch body: " f"{fixed!r}"
    )
    # The inserted line must be indented deeper than the choice line.
    choice_indent = len(fixed_lines[0]) - len(fixed_lines[0].lstrip(" "))
    inserted_line = next(ln for ln in fixed_lines[1:] if "$ route = " in ln)
    inserted_indent = len(inserted_line) - len(inserted_line.lstrip(" "))
    assert inserted_indent > choice_indent, (
        f"RPY401 QuickFix inserted line at indent {inserted_indent}, "
        f"but choice indent is {choice_indent} — body must be deeper."
    )


def test_rpy401_quickfix_preserves_existing_branch_body(tmp_path: Path) -> None:
    """If the missing branch already has body lines (e.g. `pass`), the
    QuickFix must still insert the assignment BEFORE them, not replace
    them. The existing body must remain visible after the fix.
    """
    rpy = """label start:
    menu:
        "Take the left path":
            $ route = "left"
        "Take the right path":
            "You hesitate."

    return
"""
    result, _ = _run_analyzer_on(rpy, tmp_path)
    diag = _first_diag_for(result, "RPY401")

    original_line = _original_line(rpy, diag.line_number)
    fixed = apply_quickfix_to_line(
        original_line,
        code=diag.code,
        col=diag.col,
        end_col=diag.end_col,
        fix_replacement=diag.fix_replacement,
        fix_start_col=diag.fix_start_col,
        fix_end_col=diag.fix_end_col,
    )

    # The choice line must remain unchanged.
    assert '"Take the right path"' in fixed
    # The insertion must be on a new line, not in-place.
    assert fixed.count("\n") >= 1, f"RPY401 QuickFix did not insert a new line: {fixed!r}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
