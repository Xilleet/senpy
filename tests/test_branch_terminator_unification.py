"""Characterization tests for branch-merge terminator semantics.

Two distinct concepts of "terminator" exist in Senpy:

  1. ``RE_TERMINATOR`` (constants.py) — used by RPY308/RPY309 fall-through
     checks. Includes ``call`` because after ``call X`` at the end of a
     label, control returns from X and falls through to the next label
     (so RPY308's fall-through hazard does NOT apply when the previous
     line is ``call``). Wait — that's backwards. Let me re-read.

     Actually, RPY308 fires when the previous label does NOT end with
     a terminator. ``call`` is in ``RE_TERMINATOR`` so RPY308 does NOT
     fire after ``call X``. This is the existing behavior — kept.

  2. ``RE_BRANCH_TERMINATOR`` (constants.py, added by this change) — used
     by ``state.py:_manage_if_elif_else_stack`` and
     ``flow.py:_analyze_choice_body`` to mark if/menu branches as
     terminating. Does NOT include ``call``, because ``call X`` in an
     if-branch does NOT terminate that branch — after ``call X`` returns,
     execution continues in the same branch (and may set more variables
     or fall through to code after the if).

Before this change, ``state.py:155`` and ``flow.py:544`` had inline
regexes that were identical to ``RE_BRANCH_TERMINATOR`` in behavior,
but were duplicated copies. The refactor replaces both with a call to
``is_branch_terminator_line(stripped)`` — single source of truth.

These tests pin down the behavior so the refactor is provably
behavior-preserving:

  - ``call X`` in an if-branch → branch NOT marked terminating →
    variables set in sibling branches ARE marked MAYBE_SET (RPY404).
  - ``jump``/``return``/``$ renpy.quit()`` etc. in an if-branch →
    branch IS marked terminating → variables set ONLY in terminating
    branches do NOT contribute to MAYBE_SET.
  - Same for menu choices (flow.py:_analyze_choice_body).

The existing ``test_terminator_detection.py`` covers RPY308 fall-through
(``RE_TERMINATOR`` path). This file covers the branch-merge path
(``RE_BRANCH_TERMINATOR``).
"""

from __future__ import annotations

from pathlib import Path

from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.constants import (
    RE_BRANCH_TERMINATOR,
    RE_TERMINATOR,
    is_branch_terminator_line,
    is_terminator_line,
)

# =============================================================================
# Direct unit tests on the regexes / predicates
# =============================================================================


class TestBranchTerminatorRegexSemantics:
    """``RE_BRANCH_TERMINATOR`` matches jump/return/renpy.* but NOT call."""

    def test_jump_matches(self) -> None:
        assert RE_BRANCH_TERMINATOR.match("jump foo")
        assert is_branch_terminator_line("jump foo")

    def test_return_matches(self) -> None:
        assert RE_BRANCH_TERMINATOR.match("return")
        assert is_branch_terminator_line("return")

    def test_indented_jump_matches(self) -> None:
        assert RE_BRANCH_TERMINATOR.match("    jump foo")
        assert is_branch_terminator_line("    jump foo")

    def test_renpy_quit_matches(self) -> None:
        assert RE_BRANCH_TERMINATOR.match("$ renpy.quit()")
        assert is_branch_terminator_line("$ renpy.quit()")

    def test_renpy_full_restart_matches(self) -> None:
        assert RE_BRANCH_TERMINATOR.match("    $ renpy.full_restart()")
        assert is_branch_terminator_line("    $ renpy.full_restart()")

    def test_renpy_jump_function_matches(self) -> None:
        assert RE_BRANCH_TERMINATOR.match("$ renpy.jump('scene_b')")
        assert is_branch_terminator_line("$ renpy.jump('scene_b')")

    def test_renpy_utter_restart_matches(self) -> None:
        assert RE_BRANCH_TERMINATOR.match("    $ renpy.utter_restart()")
        assert is_branch_terminator_line("    $ renpy.utter_restart()")

    def test_renpy_jump_out_of_context_matches(self) -> None:
        assert RE_BRANCH_TERMINATOR.match("$ renpy.jump_out_of_context()")
        assert is_branch_terminator_line("$ renpy.jump_out_of_context()")

    def test_call_does_not_match(self) -> None:
        """``call X`` does NOT terminate a branch — after ``call`` returns,
        execution continues in the same branch."""
        assert not RE_BRANCH_TERMINATOR.match("call helper")
        assert not is_branch_terminator_line("call helper")

    def test_indented_call_does_not_match(self) -> None:
        assert not RE_BRANCH_TERMINATOR.match("    call helper")
        assert not is_branch_terminator_line("    call helper")

    def test_call_screen_does_not_match(self) -> None:
        """``call screen`` also returns (after the screen exits), so it
        does not terminate the branch either."""
        assert not RE_BRANCH_TERMINATOR.match("call screen foo")
        assert not is_branch_terminator_line("call screen foo")

    def test_pass_does_not_match(self) -> None:
        """``pass`` is a no-op, not a terminator."""
        assert not RE_BRANCH_TERMINATOR.match("pass")
        assert not is_branch_terminator_line("pass")

    def test_dialogue_does_not_match(self) -> None:
        assert not RE_BRANCH_TERMINATOR.match('    "Hello"')
        assert not is_branch_terminator_line('    "Hello"')


class TestTerminatorVsBranchTerminatorDivergence:
    """The two regexes differ ONLY on ``call``/``call screen``.

    ``RE_TERMINATOR`` (used by RPY308 fall-through) includes ``call``;
    ``RE_BRANCH_TERMINATOR`` (used by branch-merge) does not. Every other
    line class must agree between the two — this guards against drift
    if someone adds a new terminator construct to one regex but not the
    other.
    """

    _LINES_THAT_MUST_AGREE = [
        "jump foo",
        "return",
        "    jump bar",
        "    return",
        "$ renpy.quit()",
        "    $ renpy.full_restart()",
        "$ renpy.jump('x')",
        "    $ renpy.utter_restart()",
        "$ renpy.jump_out_of_context()",
        "pass",
        '    "dialogue"',
        "$ x = 1",
    ]

    _LINES_WHERE_CALL_DIFFERS = [
        "call helper",
        "    call helper",
        "call screen foo",
    ]

    def test_agreement_on_non_call_lines(self) -> None:
        for line in self._LINES_THAT_MUST_AGREE:
            assert is_terminator_line(line) == is_branch_terminator_line(line), (
                f"RE_TERMINATOR and RE_BRANCH_TERMINATOR disagree on {line!r}: "
                f"is_terminator_line={is_terminator_line(line)}, "
                f"is_branch_terminator_line={is_branch_terminator_line(line)}. "
                "These must agree on everything except `call`/`call screen`."
            )

    def test_call_terminator_but_not_branch_terminator(self) -> None:
        """For ``call``/``call screen``: RE_TERMINATOR matches (RPY308
        fall-through does not fire), RE_BRANCH_TERMINATOR does not match
        (branch is NOT marked terminating for merge purposes)."""
        for line in self._LINES_WHERE_CALL_DIFFERS:
            assert is_terminator_line(line), (
                f"RE_TERMINATOR must match {line!r} (RPY308 fall-through "
                "must not fire after `call`). If this fails, the RPY308 "
                "behavior changed — see test_terminator_detection.py."
            )
            assert not is_branch_terminator_line(line), (
                f"RE_BRANCH_TERMINATOR must NOT match {line!r} — `call` "
                "does not terminate a branch for merge purposes."
            )


# =============================================================================
# End-to-end: branch-merge behavior with call in if/menu branches
# =============================================================================


def _run_analyzer_get_diagnostics(project_path: Path) -> list[tuple[str, int, str]]:
    """Run analyzer and return (code, line_number, message) tuples."""
    analyzer = SenpyAnalyzer(str(project_path), no_cache=True)
    analyzer.run(quiet=True)
    return [(d.code, d.line_number, d.message) for d in analyzer.diagnostics]


class TestCallInIfBranchDoesNotTerminate:
    """``call X`` at the end of an if-branch must NOT mark that branch as
    terminating — so variables set in sibling branches are correctly
    flagged as MAYBE_SET (RPY404)."""

    def test_call_in_if_branch_does_not_mask_maybeset(self, tmp_path: Path) -> None:
        """If branch A ends with ``call helper`` and branch B sets ``var = 1``,
        then ``var`` is MAYBE_SET after the if-block — because ``call``
        does NOT terminate branch A (so branch A's lack of ``var`` counts
        as a missing initialization).

        If ``call`` were incorrectly treated as a branch terminator, branch
        A would be excluded from the merge, and branch B (the only
        non-terminating branch) would make ``var`` GUARANTEED — masking
        the MAYBE_SET condition.
        """
        (tmp_path / "script.rpy").write_text(
            "label helper:\n"
            "    return\n"
            "\n"
            "label start:\n"
            "    if True:\n"
            "        call helper\n"
            "    else:\n"
            "        $ var = 1\n"
            "\n"
            '    "Value: [var]"\n'
            "    return\n",
            encoding="utf-8",
        )
        diags = _run_analyzer_get_diagnostics(tmp_path)
        rpy404 = [d for d in diags if d[0] == "RPY404" and "var" in d[2]]
        assert rpy404, (
            "RPY404 must fire on `var` — `call helper` does NOT terminate "
            "the if-branch, so `var` is MAYBE_SET (only set in the else "
            "branch). If this fails, `call` is being treated as a branch "
            "terminator — see RE_BRANCH_TERMINATOR."
        )

    def test_jump_in_if_branch_does_mask_maybeset(self, tmp_path: Path) -> None:
        """Sanity: if branch A ends with ``jump`` (real terminator), then
        branch B's variables ARE guaranteed (jump terminates branch A,
        so only branch B contributes to the merge).

        This guards against over-broadening RE_BRANCH_TERMINATOR to
        include non-terminating constructs.
        """
        (tmp_path / "script.rpy").write_text(
            "label other:\n"
            "    return\n"
            "\n"
            "label start:\n"
            "    if True:\n"
            "        jump other\n"
            "    else:\n"
            "        $ var = 1\n"
            "\n"
            '    "Value: [var]"\n'
            "    return\n",
            encoding="utf-8",
        )
        diags = _run_analyzer_get_diagnostics(tmp_path)
        rpy404 = [d for d in diags if d[0] == "RPY404" and "var" in d[2]]
        assert not rpy404, (
            "RPY404 must NOT fire on `var` — `jump other` terminates the "
            "if-branch, so `var` is guaranteed (only the else branch "
            "contributes to the merge)."
        )

    def test_return_in_if_branch_does_mask_maybeset(self, tmp_path: Path) -> None:
        """Sanity: if branch A ends with ``return`` (real terminator), then
        branch B's variables ARE guaranteed."""
        (tmp_path / "script.rpy").write_text(
            "default var = 0\n"
            "\n"
            "label start:\n"
            "    if True:\n"
            "        return\n"
            "    else:\n"
            "        $ var = 1\n"
            "\n"
            '    "Value: [var]"\n'
            "    return\n",
            encoding="utf-8",
        )
        diags = _run_analyzer_get_diagnostics(tmp_path)
        rpy404 = [d for d in diags if d[0] == "RPY404" and "var" in d[2]]
        assert not rpy404, (
            "RPY404 must NOT fire on `var` — `return` terminates the "
            "if-branch, so `var` is guaranteed."
        )


class TestCallInMenuChoiceDoesNotTerminate:
    """Same as above, but for menu choices (flow.py:_analyze_choice_body)."""

    def test_call_in_menu_choice_does_not_mask_maybeset(self, tmp_path: Path) -> None:
        """``call helper`` in one menu choice must NOT mark that choice as
        terminating — so variables set in sibling choices are correctly
        flagged as MAYBE_SET (RPY404)."""
        (tmp_path / "script.rpy").write_text(
            "label helper:\n"
            "    return\n"
            "\n"
            "label start:\n"
            "    menu:\n"
            '        "Choice A":\n'
            "            call helper\n"
            '        "Choice B":\n'
            "            $ var = 1\n"
            "\n"
            '    "Value: [var]"\n'
            "    return\n",
            encoding="utf-8",
        )
        diags = _run_analyzer_get_diagnostics(tmp_path)
        rpy404 = [d for d in diags if d[0] == "RPY404" and "var" in d[2]]
        assert rpy404, (
            "RPY404 must fire on `var` — `call helper` in Choice A does "
            "NOT terminate that choice, so `var` (set only in Choice B) "
            "is MAYBE_SET. If this fails, `call` is being treated as a "
            "branch terminator for menu choices."
        )

    def test_jump_in_menu_choice_does_mask_maybeset(self, tmp_path: Path) -> None:
        """Sanity: ``jump`` in a menu choice terminates it."""
        (tmp_path / "script.rpy").write_text(
            "default var = 0\n"
            "label other:\n"
            "    return\n"
            "\n"
            "label start:\n"
            "    menu:\n"
            '        "Choice A":\n'
            "            jump other\n"
            '        "Choice B":\n'
            "            $ var = 1\n"
            "\n"
            '    "Value: [var]"\n'
            "    return\n",
            encoding="utf-8",
        )
        diags = _run_analyzer_get_diagnostics(tmp_path)
        rpy404 = [d for d in diags if d[0] == "RPY404" and "var" in d[2]]
        assert not rpy404, (
            "RPY404 must NOT fire on `var` — `jump other` terminates "
            "Choice A, so `var` is guaranteed."
        )
