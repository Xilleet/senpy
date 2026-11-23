"""RED tests for fix-corruption cluster.

All three bugs share the same root cause: a fix-path or parser walks
the raw source line character-by-character (or applies a regex) without
first masking string-literal contents via ``strip_string_literals``.
This lets smart quotes / parens / commas inside a string literal bleed
into code-level logic, producing either false-positive diagnostics or
broken QuickFix replacements that corrupt valid source.

Each test below is the RED state: senpy currently fires the diagnostic
or produces the broken replacement. The corresponding GREEN fix masks
string literals before the relevant scan.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer


def _analyze(code: str, *, fix: bool = False) -> tuple[list, str]:
    """Run senpy on a single .rpy snippet in a tmp project.

    Returns ``(diagnostics, fixed_content)``. When ``fix=False``, the
    ``fixed_content`` is the original code (unchanged). When ``fix=True``,
    it is whatever ``--fix`` wrote to disk.
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="senpy_094_") as tmp:
        game_dir = Path(tmp) / "game"
        game_dir.mkdir(parents=True, exist_ok=True)
        script = game_dir / "script.rpy"
        script.write_text(code, encoding="utf-8")
        analyzer = SenpyAnalyzer(str(tmp), no_cache=True, fix=fix)
        result = analyzer.run(quiet=True)
        # Re-read inside the `with` block — the tmp dir is removed on exit.
        fixed_content = script.read_text(encoding="utf-8") if fix else code
        return list(result.diagnostics), fixed_content


# =============================================================================
# FIX-61: RPY002 fix replaces smart quotes inside string literals
# =============================================================================


class TestRPY002SmartQuotesInStringLiterals:
    """RPY002 must not fire on smart quotes that live INSIDE a string
    literal — those are valid Python string content, not a quoting bug.

    Before FIX-61: ``$ greeting = "He said «hello»"`` triggered RPY002,
    and ``--fix`` replaced ``«`` / ``»`` with ``"`` producing
    ``$ greeting = "He said "hello""`` — a Python SyntaxError.

    After FIX-61: the line is recognised as already-quoted Python
    (smart quotes are inside a ``"..."`` literal), so RPY002 does not
    fire and ``--fix`` leaves the line untouched.
    """

    def test_no_rpy002_when_smart_quotes_inside_string_literal(self) -> None:
        """RED: senpy currently fires RPY002 here (false positive)."""
        code = textwrap.dedent(
            """
            label start:
                $ greeting = "He said «hello»"
                return
            """
        )
        diags, _ = _analyze(code)
        rpy002 = [d for d in diags if d.code == "RPY002"]
        assert rpy002 == [], (
            f"RPY002 must not fire when smart quotes are inside a string "
            f"literal — they are valid Python string content. Got: "
            f"{[(d.line_number, d.message) for d in rpy002]}"
        )

    def test_fix_does_not_corrupt_string_literal_with_smart_quotes(self) -> None:
        """RED: ``--fix`` currently turns ``"He said «hello»"`` into
        ``"He said "hello""`` (Python SyntaxError). After FIX-61 the
        fix must leave the line unchanged.
        """
        original = textwrap.dedent(
            """
            label start:
                $ greeting = "He said «hello»"
                return
            """
        )
        diags, fixed_content = _analyze(original, fix=True)
        # The smart quotes inside the string literal must survive --fix.
        assert "«hello»" in fixed_content, (
            f"--fix corrupted the string literal: smart quotes inside "
            f'"..." were replaced with ", producing invalid Python. '
            f"Fixed content:\n{fixed_content}"
        )

    def test_rpy002_still_fires_when_smart_quotes_are_the_quotes(self) -> None:
        """Sanity: RPY002 must still fire when smart quotes are used AS
        the quotes (``$ x = «hello»`` with no outer ``"..."``). This is
        the genuine SyntaxError case the rule exists to catch.
        """
        code = textwrap.dedent(
            """
            label start:
                $ x = «hello»
                return
            """
        )
        diags, _ = _analyze(code)
        rpy002 = [d for d in diags if d.code == "RPY002"]
        assert rpy002, (
            "RPY002 must still fire when smart quotes are used AS the "
            "quotes (not inside a string literal). This is the real bug."
        )


# =============================================================================
# FIX-65: screen.py paren matching without string literal masking
# =============================================================================


class TestRPY206ParenMatchingWithStringLiteral:
    """RPY206's QuickFix range calculation walks the raw ``stripped``
    line to track paren depth. A ``)`` inside a string literal (e.g.
    ``action myfunc(")")``) closes the paren early, producing a
    fix_replacement that drops the closing args — broken screen code.

    Before FIX-65: ``textbutton "OK" action myfunc(")")`` produced
    ``fix_replacement="action Function(myfunc)"`` (args dropped).

    After FIX-65: the paren-depth tracker walks the masked line so
    parens inside string literals are invisible, producing
    ``fix_replacement="action Function(myfunc, \\")\\")"``.
    """

    def test_fix_keeps_string_literal_with_closing_paren_as_arg(self) -> None:
        """RED: fix currently drops the ``")"`` arg."""
        code = textwrap.dedent(
            """
            screen test_screen():
                textbutton "OK" action myfunc(")")
            """
        )
        diags, _ = _analyze(code)
        rpy206 = [d for d in diags if d.code == "RPY206"]
        assert rpy206, "Expected RPY206 for direct function call in action"
        fix = rpy206[0].fix_replacement
        assert fix is not None, "RPY206 must provide a fix_replacement"
        # The fix must wrap the call in Function(...) AND preserve the
        # string-literal arg including its closing paren.
        assert (
            "Function(myfunc" in fix
        ), f"fix_replacement must wrap call in Function(...); got: {fix!r}"
        # The string literal `")"`  must survive intact in the replacement.
        # Before FIX-65 the replacement was `action Function(myfunc)` (args
        # dropped because paren-depth tracker saw the `)` inside the string).
        assert '"")' in fix or '")")' in fix, (
            f"fix_replacement dropped the string-literal arg containing a "
            f'closing paren. Expected `Function(myfunc, ")")` or similar; '
            f"got: {fix!r}"
        )


# =============================================================================
# FIX-66: asset.py _split_at_clause paren depth without string masking
# =============================================================================


class TestSplitAtClauseWithStringLiteral:
    """``_split_at_clause`` splits an ATL ``at`` clause by commas at
    paren depth 0. A ``)`` inside a string literal (e.g.
    ``at center, ease("test)", 1.0)``) closes the paren early, so the
    comma after the string (inside the ease call) wrongly splits.

    Before FIX-66: ``at center, ease("test)", 1.0)`` split into 3+
    parts instead of 2.

    After FIX-66: the paren-depth tracker walks a masked copy of the
    clause so parens inside string literals are invisible.
    """

    def test_split_does_not_break_on_paren_inside_string_literal(self) -> None:
        """RED: current code splits inside the ease() call."""
        from senpy.rules.checkers.asset import _split_at_clause

        # `at center, ease("test)", 1.0)` — the `)` inside the string
        # literal must NOT close the ease() paren. Split must yield 2
        # parts: "center" and 'ease("test)", 1.0)'.
        clause = 'center, ease("test)", 1.0)'
        parts = _split_at_clause(clause)
        assert len(parts) == 2, (
            f"_split_at_clause must yield 2 parts for "
            f"'{clause}' — the `)` inside the string literal must not "
            f"close the ease() paren. Got {len(parts)} parts: {parts!r}"
        )
        assert parts[0] == "center", f"First part must be 'center'; got {parts[0]!r}"
        assert (
            "ease(" in parts[1]
        ), f"Second part must contain the ease() call intact; got {parts[1]!r}"

    def test_split_still_handles_normal_parens(self) -> None:
        """Sanity: without string literals, the splitter must still
        behave correctly (commas inside parens do not split)."""
        from senpy.rules.checkers.asset import _split_at_clause

        parts = _split_at_clause("center, ease(1.0, 2.0), other")
        assert parts == [
            "center",
            "ease(1.0, 2.0)",
            "other",
        ], f"_split_at_clause regression on normal parens; got: {parts!r}"

    def test_split_still_handles_string_literal_without_paren(self) -> None:
        """Sanity: a string literal without parens must not confuse the
        splitter either."""
        from senpy.rules.checkers.asset import _split_at_clause

        parts = _split_at_clause('center, ease("hello world"), other')
        assert parts == [
            "center",
            'ease("hello world")',
            "other",
        ], f"_split_at_clause regression on string literal without paren; got: {parts!r}"
