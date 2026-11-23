"""RED tests for fix-corruption cluster.

The first three share the same root cause: a fix-path
or parser walks the raw source line without masking string-literal
contents. The remaining five are about synthetic
``line_content``/``code_line``/``body`` fields and a multi-line
``$``-statement skip bug.

Each test below is the RED state: senpy currently fires the diagnostic
or produces the broken replacement. The corresponding GREEN fix masks
string literals before the relevant scan, or replaces the synthetic
field with the real source line.
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


# =============================================================================
# FIX-18: _verify_assign_target writes synthetic line_content
# =============================================================================


class TestRPY104LineContentIsRealSource:
    """RPY104 diagnostics from ``_verify_assign_target`` must carry the
    REAL source line in ``line_content``, not the synthetic
    ``f"{var_name} = ..."``.

    Before FIX-18: ``$ score = 10`` (with no ``default score``) produced
    a diagnostic with ``line_content="score = ..."`` — a fabricated
    string that does not appear in the source file. In JUnit SARIF,
    GitHub annotations, and the terminal, the snippet column did not
    match the actual code.

    After FIX-18: ``line_content`` is ``raw_line.strip()`` (the real
    source line), with a fallback to the synthetic string only when
    ``raw_line`` is empty.
    """

    def test_rpy104_line_content_is_real_source_not_synthetic(self) -> None:
        """RED: ``line_content`` is currently ``f"{var_name} = ..."``."""
        code = textwrap.dedent(
            """
            label start:
                $ score = 10
                return
            """
        )
        diags, _ = _analyze(code)
        rpy104 = [d for d in diags if d.code == "RPY104"]
        assert rpy104, "Expected RPY104 for $ score without default"
        d = rpy104[0]
        # The real source line is "$ score = 10" — the synthetic
        # placeholder would be "score = ...".
        assert "score = 10" in d.line_content, (
            f"line_content must be the real source line "
            f"(containing 'score = 10'), not a synthetic placeholder. "
            f"Got: {d.line_content!r}"
        )
        assert d.line_content != "score = ...", (
            f"line_content is the synthetic placeholder 'score = ...' — "
            f"must be the real source line. Got: {d.line_content!r}"
        )


# =============================================================================
# FIX-58: Synthetic code_line for Python block variables
# =============================================================================


class TestPythonBlockVariableCodeLine:
    """Variables found in ``init python:`` blocks must carry the REAL
    source line in ``VariableSymbol.code_line``, not the synthetic
    ``f"# definition of {name}"``.

    Before FIX-58: ``init python: score = 10`` produced a
    ``VariableSymbol`` with ``code_line="# definition of score"`` — a
    fabricated comment that does not appear in the source. LSP hover
    showed this fake string instead of the real ``$ score = 10`` line.

    After FIX-58: ``code_line`` is ``code_lines[line_offset - 1].strip()``
    (the real source line from the Python block).
    """

    def test_code_line_is_real_source_not_synthetic(self) -> None:
        """RED: ``code_line`` is currently ``# definition of score``."""
        code = textwrap.dedent(
            """
            init python:
                score = 10
            label start:
                return
            """
        )
        diags, _ = _analyze(code)
        # The variable 'score' should be registered in analyzer.variables.
        # We need to access the analyzer directly — _analyze returns
        # diagnostics, not the analyzer. Use a separate run.
        import tempfile

        with tempfile.TemporaryDirectory(prefix="senpy_094_") as tmp:
            game_dir = Path(tmp) / "game"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "script.rpy").write_text(code, encoding="utf-8")
            analyzer = SenpyAnalyzer(str(tmp), no_cache=True)
            analyzer.run(quiet=True)
            var_sym = analyzer.variables.get("score")
            assert var_sym is not None, "Variable 'score' must be registered"
            # The real source line is "score = 10" — the synthetic
            # placeholder would be "# definition of score".
            assert "score = 10" in var_sym.code_line, (
                f"code_line must be the real source line "
                f"(containing 'score = 10'), not a synthetic placeholder. "
                f"Got: {var_sym.code_line!r}"
            )
            assert var_sym.code_line != "# definition of score", (
                f"code_line is the synthetic placeholder "
                f"'# definition of score' — must be the real source line. "
                f"Got: {var_sym.code_line!r}"
            )


# =============================================================================
# FIX-59: Synthetic body="" for dynamic images
# =============================================================================


class TestDynamicImageBodyNotEmpty:
    """Images registered via ``renpy.image(NAME, ...)`` in
    ``init python:`` blocks must carry a non-empty ``body`` in
    ``ImageSymbol``, not the synthetic empty string.

    Before FIX-59: ``renpy.image("bg_room", ...)`` produced an
    ``ImageSymbol`` with ``body=""``. LSP hover showed an empty string
    instead of the actual ``renpy.image("bg_room", ...)`` call.

    After FIX-59: ``body`` is the real source line (or at least
    ``f"renpy.image({name_val!r}, ...)"`` as a fallback).
    """

    def test_body_is_not_empty_for_dynamic_renpy_image(self) -> None:
        """RED: ``body`` is currently ``""``."""
        code = textwrap.dedent(
            """
            init python:
                renpy.image("bg_room", "images/bg_room.png")
            label start:
                return
            """
        )
        import tempfile

        with tempfile.TemporaryDirectory(prefix="senpy_094_") as tmp:
            game_dir = Path(tmp) / "game"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "script.rpy").write_text(code, encoding="utf-8")
            analyzer = SenpyAnalyzer(str(tmp), no_cache=True)
            analyzer.run(quiet=True)
            img_sym = analyzer.images.get("bg_room")
            assert img_sym is not None, "Image 'bg_room' must be registered from renpy.image() call"
            assert img_sym.body, (
                f"body must not be empty for dynamic renpy.image() "
                f"registration — LSP hover shows nothing. Got: {img_sym.body!r}"
            )
            assert (
                "renpy.image" in img_sym.body or "bg_room" in img_sym.body
            ), f"body must contain the renpy.image() call or the image name. Got: {img_sym.body!r}"


# =============================================================================
# FIX-62: dialogue.py raw label name in message
# =============================================================================


class TestRPY308MessageUsesResolvedLabelName:
    """RPY308 message for a sublabel (``.sublabel``) must use the
    RESOLVED label name (``parent.sublabel``), not the raw
    ``.sublabel``.

    Before FIX-62: ``label .sublabel:`` preceded by fall-through
    produced ``message="Label '.sublabel' is preceded by..."`` —
    confusing because the actual label name after resolution is
    ``parent.sublabel``.

    After FIX-62: the message uses the resolved name.
    """

    def test_rpy308_message_uses_resolved_sublabel_name(self) -> None:
        """RED: message currently shows '.sublabel' not 'parent.sublabel'."""
        code = textwrap.dedent(
            """
            label parent:
                "hello"
            label .sublabel:
                return
            """
        )
        diags, _ = _analyze(code)
        rpy308 = [d for d in diags if d.code == "RPY308"]
        assert rpy308, "Expected RPY308 for label fallthrough"
        d = rpy308[0]
        # The resolved label name is "parent.sublabel", not ".sublabel".
        assert "parent.sublabel" in d.message, (
            f"RPY308 message must use the resolved label name "
            f"'parent.sublabel', not the raw '.sublabel'. "
            f"Got: {d.message!r}"
        )
        assert "'.sublabel'" not in d.message, (
            f"RPY308 message must not show the raw '.sublabel' — "
            f"it should be resolved to 'parent.sublabel'. "
            f"Got: {d.message!r}"
        )


# =============================================================================
# FIX-63: state.py $ line returns idx+1 instead of next_idx
# =============================================================================


class TestPythonInlineMultiLineContinuation:
    """``$``-statements with backslash continuation must consume ALL
    physical lines of the logical line, not just the first one.

    Before FIX-63: ``_check_python_inline`` returned ``idx + 1``
    instead of ``next_idx``. For a multi-line ``$ x = 1 + \\
    2`` statement, ``_get_logical_line`` joined both physical lines
    into one logical line starting at ``idx`` and ending at
    ``next_idx``. Returning ``idx + 1`` skipped the second physical
    line, so any diagnostics on the continuation line were lost and
    the line counter drifted.

    After FIX-63: ``_check_python_inline`` returns ``next_idx``.
    """

    def test_multiline_dollar_continuation_not_skipped(self) -> None:
        """RED: lines after ``$ \\`` continuation are currently skipped.

        We test this by placing an undefined variable reference on the
        continuation line — if the line is skipped, no RPY104 fires for
        the continuation's assignment.
        """
        code = textwrap.dedent(
            """
            label start:
                $ total = 1 + \\
                    2
                $ undefined_var = total
                return
            """
        )
        diags, _ = _analyze(code)
        # 'undefined_var' is assigned without a 'default' — RPY104 must
        # fire. If the continuation line of the first `$` was skipped
        # (FIX-63 bug), the analyzer's line counter drifts and the
        # second `$` statement may be mis-processed.
        rpy104 = [d for d in diags if d.code == "RPY104" and "undefined_var" in d.message]
        assert rpy104, (
            "RPY104 must fire for 'undefined_var' — if the multi-line "
            "$ continuation was skipped (FIX-63 bug), the line counter "
            "drifted and the second $ statement was mis-processed."
        )
