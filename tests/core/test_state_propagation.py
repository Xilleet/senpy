"""Regression tests for state-propagation bugs.

The bug covered here is P2 (0.8.1 желательно): menu flow analysis
ignores ``guaranteed_vars`` from the context before the menu. A
variable assigned before the menu is treated as MAYBE_SET after the
menu because ``_merge_menu_branches`` passes ``already_guaranteed=set()``
to ``merge_flow_branches``, unlike the ``if`` block path which correctly
forwards ``self.guaranteed_vars``. The user-facing symptom is a false
positive RPY404 ("Variable may be uninitialized") on a variable that is
guaranteed-set before the menu.

A second bug from the same sprint (``_consume_block`` aborting on
top-level comments) was investigated but found NOT to be reproducible
on syntactically valid Python code: any top-level comment inside an
indent-0 ``init python:`` block immediately followed by body-level
code is a Python syntax error (RPY110). The current behaviour
(breaking on such comments) is therefore defensible: there is no
valid input where the break loses user symbols. Marked as wontfix in
the roadmap.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer


def _run_analyzer_on(rpy_content: str, tmp_path: Path):
    """Run SenpyAnalyzer on a single .rpy file inside a minimal game/ dir."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "scenario.rpy").write_text(rpy_content, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)
    return result, analyzer


# ---------------------------------------------------------------------------
# Menu flow ignores pre-menu `guaranteed_vars`
# ---------------------------------------------------------------------------


def test_menu_flow_honours_pre_menu_guaranteed_vars(tmp_path: Path) -> None:
    """Reproducer: a variable assigned before ``menu:`` is guaranteed-set
    on every code path. After the menu, RPY404 must NOT fire on reads of
    that variable, because it was already initialised before the
    branching point.
    """
    rpy = """label start:
    $ score = 0

    menu:
        "Win":
            $ score = 100
        "Continue":
            pass

    "Current score: [score]"
    return
"""
    result, analyzer = _run_analyzer_on(rpy, tmp_path)

    rpy404 = [d for d in result.diagnostics if d.code == "RPY404"]
    score_404 = [d for d in rpy404 if "score" in d.message]
    assert score_404 == [], (
        f"Expected 0 RPY404 for 'score' (it is guaranteed-set before "
        f"the menu), but got: {[(d.line_number, d.message) for d in score_404]}"
    )


def test_menu_flow_still_detects_truly_uninit_vars(tmp_path: Path) -> None:
    """Counter-case: a variable assigned ONLY inside one menu branch
    (not before the menu) must still trigger RPY404 after the menu.
    """
    rpy = """label start:
    menu:
        "Win":
            $ branch_only_var = 100
        "Continue":
            pass

    "Value: [branch_only_var]"
    return
"""
    result, _ = _run_analyzer_on(rpy, tmp_path)

    rpy404 = [d for d in result.diagnostics if d.code == "RPY404"]
    branch_only_404 = [d for d in rpy404 if "branch_only_var" in d.message]
    assert branch_only_404, (
        "Expected RPY404 for 'branch_only_var' — it is only assigned "
        "in one menu branch, not before the menu."
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
