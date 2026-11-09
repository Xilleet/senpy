"""Infrastructure test: every QuickFix must preserve source validity.

For every Diagnostic with a ``fix_replacement`` produced against any of the
``tests/fixtures/rules/RPYxxx/bad_*.rpy`` fixtures, applying the LSP-style
TextEdit must not break the source:

    * For ``$``-prefixed lines and ``python:`` blocks, the resulting line
      (after the ``$`` prefix is stripped) must parse as valid Python.
    * For Ren'Py screen / menu / button lines, the resulting text must
      have balanced quotes and balanced brackets (after string-literal
      contents are masked).

This test is the architectural investment against future QuickFix damage
bugs of the kind where the LSP TextEdit range disagrees with the
replacement (e.g. replacement includes the line indent while the range
does not, or the range covers only part of a call expression). A new rule
that ships a broken QuickFix will fail this test before it can ship.

The test uses the same LSP TextEdit simulation that the regression
tests in ``test_quickfix_cluster.py`` use, so it mirrors what VS Code
actually applies when the user clicks a QuickFix.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer
from senpy.text_utils import _count_bracket_delta, strip_string_literals
from tests._helpers.paths import FIXTURES_DIR
from tests._helpers.quickfix import apply_quickfix_to_line

# FIXTURES_DIR is imported from tests._helpers.paths above.

# Rule codes whose ``$`` / ``python:`` QuickFix output must be valid Python.
# These are the rules that operate on Python statements embedded in Ren'Py.
_PYTHON_LINE_RULES = frozenset({"RPY001", "RPY002", "RPY106"})


def _iter_bad_fixtures() -> list[Path]:
    if not FIXTURES_DIR.exists():
        return []
    return sorted(FIXTURES_DIR.rglob("bad_*.rpy"))


def _python_parses(text: str) -> bool:
    """True if `text` parses as Python. Tolerates ``$`` prefix and indent."""
    body = text.lstrip()
    if body.startswith("$"):
        body = body[1:].lstrip()
    body = textwrap.dedent(body)
    try:
        ast.parse(body)
        return True
    except SyntaxError:
        return False


def _balanced_renpy(text: str) -> bool:
    """True if quotes and brackets in `text` are balanced after masking
    string-literal contents.
    """
    masked = strip_string_literals(text)
    if masked.count('"') % 2 != 0:
        return False
    if masked.count("'") % 2 != 0:
        return False
    return _count_bracket_delta(masked) == 0


def _is_python_statement_line(line: str, code: str) -> bool:
    """Heuristic: does this line carry a Python statement that must parse
    as valid Python after the fix?

    Only ``$``-prefixed lines are checked via ``ast.parse``. Other lines
    that RPY002 touches (``if``/``elif``/``default``/``define``) are Ren'Py
    declarations that *contain* a Python expression but are not themselves
    Python statements — ``ast.parse`` would reject them for missing body
    or for the trailing ``:``. Those lines are validated via the balanced
    quotes/brackets check instead.
    """
    if code in _PYTHON_LINE_RULES:
        return line.lstrip().startswith("$")
    return line.lstrip().startswith("$")


@pytest.mark.parametrize(
    "fixture",
    _iter_bad_fixtures(),
    ids=lambda p: f"{p.parent.name}/{p.name}",
)
def test_quickfix_preserves_validity(fixture: Path, tmp_path: Path) -> None:
    """For every Diagnostic with a fix_replacement produced by this
    fixture, applying the LSP-style TextEdit must yield syntactically
    valid source.
    """
    rule_id = fixture.parent.name
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    test_file = game_dir / fixture.name
    # Some fixtures are intentionally not valid UTF-8 (e.g. RPY100
    # `bad_cp1251.rpy` — encoding-error detection). Those test the
    # encoding path, not QuickFixes, so we skip them rather than crash
    # trying to read them as text.
    try:
        content = fixture.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        pytest.skip(f"Fixture {fixture.name} is not UTF-8 (encoding-error test)")
    test_file.write_text(content, encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)

    fixable_diags = [
        d for d in result.diagnostics if d.fix_replacement is not None and d.fix_replacement != ""
    ]
    if not fixable_diags:
        pytest.skip(f"Fixture {fixture.name} produced no fixable diagnostics")

    original_lines = content.splitlines()
    failures: list[str] = []

    for diag in fixable_diags:
        if diag.line_number < 1 or diag.line_number > len(original_lines):
            failures.append(f"{rule_id} diag line_number={diag.line_number} out of range")
            continue
        original_line = original_lines[diag.line_number - 1]

        fixed = apply_quickfix_to_line(
            original_line,
            code=diag.code,
            col=diag.col,
            end_col=diag.end_col,
            fix_replacement=diag.fix_replacement,
            fix_start_col=diag.fix_start_col,
            fix_end_col=diag.fix_end_col,
        )

        # Pick the validity check based on rule + line content. A single
        # fix may produce multiple lines (e.g. RPY401 inserts a newline);
        # we check each resulting line for its own validity.
        if _is_python_statement_line(original_line, diag.code):
            # For $ / python: lines, the entire fixed text must parse
            # as Python (after stripping $ and indent).
            if not _python_parses(fixed):
                failures.append(
                    f"{rule_id} L{diag.line_number}: fixed Python output {fixed!r} does not parse"
                )
        else:
            # For Ren'Py lines, every produced line must be balanced.
            for ln in fixed.splitlines():
                if not _balanced_renpy(ln):
                    failures.append(
                        f"{rule_id} L{diag.line_number}: fixed Ren'Py "
                        f"line {ln!r} has unbalanced quotes/brackets"
                    )
                    break

    assert not failures, (
        f"QuickFix validity check failed for {fixture.name}:\n  - " + "\n  - ".join(failures)
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
