"""Branch-clear (MAYBE_SET propagation through nested blocks).

These tests cover the edge cases where a variable that was declared
BEFORE a branching block (``$ x = 0`` immediately above, or
``default x = 0`` at module level) must remain DECLARED — not be
re-flagged as MAYBE_SET — when read after the block, even when the
block contains NESTED ``menu:`` / ``if`` / ``elif`` / ``else``
constructs.

Background
---------
``merge_flow_branches`` (flow.py) returns three values:

    (guaranteed_vars, uninitialized_vars, all_terminating)

``guaranteed_vars`` — variables assigned in EVERY non-terminating branch
(safe to read after the block).
``uninitialized_vars`` (a.k.a. ``branch_uninitialized`` / MAYBE_SET) —
variables assigned in SOME branches but not all; reading them after the
block is the RPY404 bug.

To prevent false-positive RPY404 on variables that were already
guaranteed-set BEFORE the block (e.g. ``$ score = 0`` above ``menu:``),
the caller passes ``already_guaranteed=self.guaranteed_vars`` to
``merge_flow_branches``, which excludes them from the MAYBE_SET set.

The bug
----------------
When a ``menu:`` choice body contains a NESTED ``menu:``, the nested
call to ``analyze_menu_flow`` in ``_analyze_choice_body`` (flow.py:527)
does NOT receive the parent's ``already_guaranteed`` set. The nested
menu's ``merge_flow_branches`` then re-discovers the parent's pre-block
variables as MAYBE_SET in branches where they are not re-assigned —
even though they were declared above the OUTER menu and remain
guaranteed-set on every code path through both menus.

User-facing symptom: a variable declared at the top of a label,
mutated in only one branch of a nested menu, fires a false RPY404
"Variable 'x' may be uninitialized (MAYBE_SET) if player took choice
'Skip' on line N" — even though ``x`` was set to ``0`` on line 1 of
the label.

The fix: forward ``already_guaranteed`` to the nested
``analyze_menu_flow`` call so the inner menu also treats pre-block
variables as "already known, do not flag as MAYBE_SET".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _run_analyzer_on(rpy_content: str, tmp_path: Path):
    """Run SenpyAnalyzer on a single .rpy file inside a minimal game/ dir."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "scenario.rpy").write_text(rpy_content, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)
    return result, analyzer


def _rpy404_for_var(result, var_name: str) -> list:
    """Return all RPY404 diagnostics whose message mentions ``var_name``."""
    return [d for d in result.diagnostics if d.code == "RPY404" and var_name in d.message]


# ---------------------------------------------------------------------------
# The bug: nested menu does not propagate already_guaranteed
# ---------------------------------------------------------------------------


class TestNestedMenuPreDeclaredVar:
    """Variable declared BEFORE the outer menu must remain DECLARED
    after the outer menu, even if a NESTED menu inside one of the
    outer choices mutates it in only some branches.

    Pre-fix expectation: false-positive RPY404 on the pre-declared
    variable, blaming the inner "Skip" branch for the "missing"
    assignment — even though the variable was set on the line above
    the outer menu and is therefore guaranteed-set on every code path
    through both menus.
    """

    def test_nested_menu_with_pre_declared_var_no_false_rpy404(self, tmp_path: Path) -> None:
        rpy = """label start:
    $ score = 0
    menu:
        "Branch 1":
            pass
        "Branch 2":
            menu:
                "Deep":
                    $ score = 100
                "Shallow":
                    pass
    "Score: [score]"
    return
"""
        result, _ = _run_analyzer_on(rpy, tmp_path)
        score_404 = _rpy404_for_var(result, "score")
        assert score_404 == [], (
            "Variable 'score' is DECLARED on line 2 (`$ score = 0`) before "
            "the outer menu. It must remain DECLARED after the outer menu, "
            "regardless of whether the nested inner menu re-assigns it in "
            "some branches. Got false-positive RPY404: "
            f"{[(d.line_number, d.message) for d in score_404]}"
        )

    def test_nested_menu_truly_uninit_var_still_detected(self, tmp_path: Path) -> None:
        """Counter-case (regression guard): a variable assigned ONLY in
        one branch of the nested menu (not pre-declared above the outer
        menu) must STILL trigger RPY404 after the block.
        """
        rpy = """label start:
    menu:
        "Branch 1":
            pass
        "Branch 2":
            menu:
                "Deep":
                    $ uninit_var = 100
                "Shallow":
                    pass
    "Value: [uninit_var]"
    return
"""
        result, _ = _run_analyzer_on(rpy, tmp_path)
        uninit_404 = _rpy404_for_var(result, "uninit_var")
        assert uninit_404, (
            "Variable 'uninit_var' is ONLY assigned in one nested menu "
            "branch — not pre-declared. RPY404 must fire on the read "
            "after the block."
        )

    def test_three_level_nested_menu_pre_declared(self, tmp_path: Path) -> None:
        """Three-level nesting: pre-declared var must survive all three
        menu layers without becoming MAYBE_SET.
        """
        rpy = """label start:
    $ level = 0
    menu:
        "Top A":
            menu:
                "Mid A":
                    menu:
                        "Deep A":
                            $ level = 1
                        "Deep B":
                            pass
                "Mid B":
                    pass
        "Top B":
            pass
    "Level: [level]"
    return
"""
        result, _ = _run_analyzer_on(rpy, tmp_path)
        level_404 = _rpy404_for_var(result, "level")
        assert level_404 == [], (
            "Variable 'level' declared at top must survive 3-level nested "
            "menus without false-positive RPY404. Got: "
            f"{[(d.line_number, d.message) for d in level_404]}"
        )


# ---------------------------------------------------------------------------
# Related edge cases: if-inside-menu, menu-inside-if, default-then-nested
# ---------------------------------------------------------------------------


class TestRelatedNestedBlocks:
    """Cover the related patterns where ``already_guaranteed`` must
    propagate across nested constructs:

      - if inside menu choice (variable declared before menu)
      - menu inside if branch (variable declared before if)
      - ``default x = ...`` at module level, then nested block reads x
    """

    def test_if_inside_menu_pre_declared(self, tmp_path: Path) -> None:
        """Variable declared above ``menu:`` and re-assigned inside an
        ``if`` (no else) inside one menu choice — must remain DECLARED
        after the menu.

        This already worked before the fix (because ``_check_python_inline``
        forwards ``self.guaranteed_vars`` correctly via the StateChecker
        path), but is included as a regression guard to make sure the
        nested-menu fix does not break the nested-if path.
        """
        rpy = """label start:
    $ score = 0
    menu:
        "Branch 1":
            pass
        "Branch 2":
            if cond:
                $ score = 100
    "Score: [score]"
    return
"""
        result, _ = _run_analyzer_on(rpy, tmp_path)
        assert _rpy404_for_var(result, "score") == []

    def test_menu_inside_if_pre_declared(self, tmp_path: Path) -> None:
        """Variable declared above ``if`` and re-assigned in only one
        branch of a ``menu:`` inside the if-branch — must remain DECLARED
        after the outer if.
        """
        rpy = """label start:
    $ score = 0
    if outer_cond:
        menu:
            "Deep":
                $ score = 100
            "Shallow":
                pass
    "Score: [score]"
    return
"""
        result, _ = _run_analyzer_on(rpy, tmp_path)
        assert _rpy404_for_var(result, "score") == []

    def test_default_then_nested_menu_pre_declared(self, tmp_path: Path) -> None:
        """``default x = 0`` at module level must also propagate as
        already_guaranteed through nested menus — same as ``$ x = 0``
        inside the label body. This covers the ``known_symbols`` /
        ``declared_symbols`` path used by ``_merge_menu_branches``.
        """
        rpy = """default score = 0

label start:
    menu:
        "Branch 1":
            pass
        "Branch 2":
            menu:
                "Deep":
                    $ score = 100
                "Shallow":
                    pass
    "Score: [score]"
    return
"""
        result, _ = _run_analyzer_on(rpy, tmp_path)
        assert _rpy404_for_var(result, "score") == []


# ---------------------------------------------------------------------------
# Unit-level characterization: merge_flow_branches with already_guaranteed
# ---------------------------------------------------------------------------


class TestMergeFlowBranchesAlreadyGuaranteed:
    """Direct unit tests on ``merge_flow_branches`` to lock in the
    behaviour that the nested-menu fix relies on: variables in
    ``already_guaranteed`` are NOT included in the returned
    ``uninitialized_vars`` dict.

    These tests pass both before and after the fix — they pin the
    contract so a future refactor cannot silently break the
    already_guaranteed exclusion.
    """

    def test_already_guaranteed_excluded_from_uninit(self) -> None:
        from senpy.rules.flow import FlowBranch, merge_flow_branches

        branches = [
            FlowBranch(kind="choice", name="A", line=1, defined_vars={"x"}),
            FlowBranch(kind="choice", name="B", line=2, defined_vars=set()),
        ]
        _, uninit, _ = merge_flow_branches(
            branches=branches,
            block_kind="menu",
            block_line=1,
            has_else=True,
            known_symbols=set(),
            already_guaranteed={"x"},
        )
        assert "x" not in uninit, (
            "Variable 'x' is in `already_guaranteed` — it was declared "
            "above the block and must NOT appear in MAYBE_SET (uninit)."
        )

    def test_already_guaranteed_not_included_in_guaranteed_either(self) -> None:
        """``already_guaranteed`` vars are excluded from ``uninit``,
        but they are NOT added to the returned ``guaranteed`` set —
        that set tracks ONLY vars guaranteed-set INSIDE this block.
        The caller is responsible for unioning them with its own
        ``guaranteed_vars`` tracker.
        """
        from senpy.rules.flow import FlowBranch, merge_flow_branches

        branches = [
            FlowBranch(kind="choice", name="A", line=1, defined_vars=set()),
            FlowBranch(kind="choice", name="B", line=2, defined_vars=set()),
        ]
        guaranteed, _, _ = merge_flow_branches(
            branches=branches,
            block_kind="menu",
            block_line=1,
            has_else=True,
            known_symbols=set(),
            already_guaranteed={"x"},
        )
        assert "x" not in guaranteed, (
            "already_guaranteed vars must not bleed into the returned "
            "guaranteed set — caller tracks them separately."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
