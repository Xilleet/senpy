"""TDD tests for Python syntax error diagnostics in $-statements.

``PythonAstChecker`` used to silently swallow ``SyntaxError`` from
``ast.parse(py_code)`` — a user writing ``$ x = )`` (invalid Python)
got no diagnostic at all. Ren'Py itself would crash with a traceback
at that line, so Senpy's silence was a missed opportunity to catch
the bug before runtime.

After the fix: ``SyntaxError`` emits a diagnostic with code ``RPY110``,
severity ``ERROR``, pointing at the line and offset where the parser
failed. This applies to the main ``check_python_ast`` method (the
entry point for ``$``-statement analysis).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer


def _make_project(tmp_path: Path, script: str) -> Path:
    game = tmp_path / "game"
    game.mkdir(parents=True, exist_ok=True)
    (game / "script.rpy").write_text(script, encoding="utf-8")
    return tmp_path


class TestPythonSyntaxErrorDiagnostic:
    """``$ x = )`` must emit ``RPY110`` (Python syntax error), not be
    silently swallowed.
    """

    def test_syntax_error_emits_rpy110(self, tmp_path: Path):
        """``$ x = )`` → ``RPY110`` diagnostic with ERROR severity."""
        project = _make_project(
            tmp_path,
            "label start:\n    $ x = )\n    return\n",
        )
        analyzer = SenpyAnalyzer(str(project), no_cache=True)
        result = analyzer.run(quiet=True)

        rpy110 = [d for d in result.diagnostics if d.code == "RPY110"]
        assert len(rpy110) >= 1, (
            f"Expected at least 1 RPY110 diagnostic for `$ x = )`, got {len(rpy110)}. "
            "SyntaxError in Python $-statements must be reported, not silently swallowed."
        )
        diag = rpy110[0]
        assert diag.severity == "ERROR", f"RPY110 must be ERROR severity, got {diag.severity!r}."
        assert (
            "syntax" in diag.message.lower()
        ), f"RPY110 message should mention 'syntax', got: {diag.message!r}"

    def test_syntax_error_points_at_correct_line(self, tmp_path: Path):
        """``RPY110`` line_number must point at the line with the error."""
        project = _make_project(
            tmp_path,
            "label start:\n    $ x = )\n    return\n",
        )
        analyzer = SenpyAnalyzer(str(project), no_cache=True)
        result = analyzer.run(quiet=True)

        rpy110 = [d for d in result.diagnostics if d.code == "RPY110"]
        assert len(rpy110) >= 1
        # The `$ x = )` is on line 2 (1-indexed).
        assert (
            rpy110[0].line_number == 2
        ), f"RPY110 should point at line 2 (the `$ x = )` line), got line {rpy110[0].line_number}."

    def test_valid_python_does_not_emit_rpy110(self, tmp_path: Path):
        """Valid Python in ``$``-statements must NOT emit RPY110."""
        project = _make_project(
            tmp_path,
            "label start:\n    $ x = 1 + 2\n    $ y = [a for a in range(10)]\n    return\n",
        )
        analyzer = SenpyAnalyzer(str(project), no_cache=True)
        result = analyzer.run(quiet=True)

        rpy110 = [d for d in result.diagnostics if d.code == "RPY110"]
        assert (
            rpy110 == []
        ), f"Valid Python should not emit RPY110, got {len(rpy110)} diagnostic(s)."

    def test_syntax_error_in_init_python(self, tmp_path: Path):
        """``init python:`` block with syntax error → ``RPY110``."""
        project = _make_project(
            tmp_path,
            "init python:\n    x = )\nlabel start:\n    return\n",
        )
        analyzer = SenpyAnalyzer(str(project), no_cache=True)
        result = analyzer.run(quiet=True)

        rpy110 = [d for d in result.diagnostics if d.code == "RPY110"]
        assert (
            len(rpy110) >= 1
        ), f"Expected RPY110 for syntax error in init python block, got {len(rpy110)}."

    def test_syntax_error_message_includes_error_text(self, tmp_path: Path):
        """``RPY110`` message should include the Python parser's error text
        (e.g. "unexpected ')'").
        """
        project = _make_project(
            tmp_path,
            "label start:\n    $ x = )\n    return\n",
        )
        analyzer = SenpyAnalyzer(str(project), no_cache=True)
        result = analyzer.run(quiet=True)

        rpy110 = [d for d in result.diagnostics if d.code == "RPY110"]
        assert len(rpy110) >= 1
        # The message should contain some hint about what went wrong.
        # Python's error for `x = )` is something like "unexpected ')'"
        # or "invalid syntax" depending on version.
        assert len(rpy110[0].message) > 10, (
            f"RPY110 message too short — should include Python parser error text: "
            f"{rpy110[0].message!r}"
        )
