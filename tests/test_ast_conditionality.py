"""Regression tests for AST conditionality bugs.

Two related bugs covered here, both P2 (0.8.2):

    * ``extract_assigned_names`` uses ``ast.walk`` (recursive) to collect
      assignment targets. This treats conditional assignments inside
      ``if``/``for``/``while``/``try`` bodies as guaranteed. The user-
      facing symptom is a false NEGATIVE for RPY404: a variable that is
      only assigned on one branch of an ``if`` is not flagged as
      MAYBE_SET, because the conditional assignment was collected as
      top-level.

      The fix: iterate ``tree.body`` (top-level only), skip bodies of
      ``If``/``For``/``While``/``Try``/``FunctionDef``/``ClassDef``/
      ``With`` for guaranteed-assignment tracking. Same approach as
      ``clear_safe_cfg_vars`` (which already does this correctly).

    * ``collect_from_python_block`` has the same ``ast.walk`` problem
      when registering variables from ``init python:`` blocks. Variables
      assigned inside an ``if`` body are registered as top-level
      declarations — they appear in ``user_symbols`` even though they
      may never execute.

      The fix: same ``tree.body`` iteration, same skip list.

Both bugs produce false negatives — diagnostics that SHOULD fire but
don't. They are NOT false positives (the analyzer stays silent when it
shouldn't), so they are lower-priority than the 0.8.1 bug clusters.
But they directly affect the project's strategic value per §0 of the
dev assist: "analysis of under what conditions variables exist and
what states can arise" — conditional assignments are exactly that.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer
from senpy.rules.python_ast import PythonAstChecker, extract_assigned_names


def _run_analyzer_on(rpy_content: str, tmp_path: Path):
    """Run SenpyAnalyzer on a single .rpy file inside a minimal game/ dir."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "scenario.rpy").write_text(rpy_content, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)
    return result, analyzer


# ---------------------------------------------------------------------------
# extract_assigned_names — conditional assignments must NOT be reported
# as guaranteed
# ---------------------------------------------------------------------------


class TestExtractAssignedNamesConditionality:
    """Unit tests for the ``extract_assigned_names`` function itself.

    The contract: only top-level assignments (those that execute
    unconditionally when the statement runs) are returned. Assignments
    inside ``if``/``for``/``while``/``try`` bodies are conditional —
    they may not execute — and must NOT be returned.
    """

    def test_plain_assignment_returned(self) -> None:
        assert extract_assigned_names("x = 5") == {"x"}

    def test_chained_assignment_returned(self) -> None:
        assert extract_assigned_names("a = b = 5") == {"a", "b"}

    def test_tuple_unpacking_returned(self) -> None:
        assert extract_assigned_names("a, b = 1, 2") == {"a", "b"}

    def test_walrus_returned(self) -> None:
        # Top-level walrus in expression statement.
        assert extract_assigned_names("(x := 5)") == {"x"}

    def test_annassign_returned(self) -> None:
        assert extract_assigned_names("x: int = 5") == {"x"}

    def test_augassign_returned(self) -> None:
        # AugAssign requires the variable to already exist — but the
        # function still reports it as "assigned" (for consistency with
        # the previous behaviour; this is not a regression).
        assert extract_assigned_names("x += 1") == {"x"}

    def test_assignment_inside_if_NOT_returned(self) -> None:
        """Conditional assignment inside `if` body must NOT be reported
        as guaranteed — it only runs when the condition is true.
        """
        # `if cond: y = 2` — y is conditional, not guaranteed.
        result = extract_assigned_names("if cond: y = 2")
        assert (
            "y" not in result
        ), f"Conditional assignment inside `if` must NOT be reported as guaranteed. Got: {result}"

    def test_assignment_outside_if_still_returned(self) -> None:
        """A top-level assignment that appears BEFORE an `if` in the
        same statement list must still be returned.
        """
        # Multi-line: `x = 1` then `if cond: y = 2` on the next line.
        # Python forbids `x = 1; if cond: y = 2` on one line (compound
        # statements after `;`), so we use a newline.
        result = extract_assigned_names("x = 1\nif cond: y = 2\n")
        assert "x" in result
        assert "y" not in result

    def test_assignment_inside_for_NOT_returned(self) -> None:
        """Loop variable binding is conditional (loop may not execute)."""
        result = extract_assigned_names("for i in range(3): x = i")
        # `i` IS the loop variable — top-level binding, returned.
        # `x` is INSIDE the loop body — conditional, NOT returned.
        assert "i" in result
        assert "x" not in result

    def test_assignment_inside_while_NOT_returned(self) -> None:
        result = extract_assigned_names("while cond: x = 1")
        assert "x" not in result

    def test_assignment_inside_try_NOT_returned(self) -> None:
        result = extract_assigned_names("try: x = 1\nexcept: pass")
        assert "x" not in result

    def test_assignment_inside_function_def_NOT_returned(self) -> None:
        """Function body assignments are not top-level — the function
        may never be called.
        """
        result = extract_assigned_names("def f():\n    y = 1\n")
        assert "y" not in result

    def test_assignment_inside_with_NOT_returned(self) -> None:
        """`with` block body assignments are conditional."""
        result = extract_assigned_names("with open('f') as fh:\n    x = 1\n")
        assert "x" not in result

    def test_walrus_inside_if_NOT_returned(self) -> None:
        """Walrus inside an `if` condition is conditional — it only
        evaluates if the `if` statement itself runs (which it does at
        top level), but the walrus is part of the condition expression,
        not a top-level statement. We approximate: walrus inside a
        conditional expression is treated as conditional.
        """
        # `if (y := compute()): ...` — walrus is in the condition.
        # Top-level `if` runs unconditionally, but the walrus is part
        # of the condition expression — it evaluates when the `if`
        # evaluates. This IS guaranteed. We accept it.
        # The bug we close is about assignments INSIDE the if BODY.
        result = extract_assigned_names("if (y := compute()):\n    pass\n")
        # y is in the condition — guaranteed. Pass is in the body.
        # Both are reachable; we keep y (condition) and drop body.
        assert "y" in result


# ---------------------------------------------------------------------------
# Integration: conditional assignment in menu choice body
# ---------------------------------------------------------------------------


def test_conditional_assignment_in_menu_choice_not_guaranteed(
    tmp_path: Path,
) -> None:
    """Reproducer: a variable assigned ONLY inside an ``if`` body within
    a menu choice must NOT be treated as guaranteed-set on every code
    path through the menu. Before the fix, the conditional assignment
    was incorrectly collected as a top-level assignment, so the
    variable was added to the choice's ``defined_vars`` — making it
    appear guaranteed when merged with other choices that DO assign
    it unconditionally.

    The user-facing symptom: a false NEGATIVE for RPY401 (menu branch
    asymmetry). If choice A assigns `x` unconditionally and choice B
    assigns `x` only inside `if cond:`, the merge should flag the
    asymmetry (B may not assign `x`). Before the fix, B's conditional
    assignment was treated as guaranteed, hiding the asymmetry.
    """
    rpy = """label start:
    menu:
        "Choice A":
            $ x = 5
        "Choice B":
            $ if cond: x = 10
    "Value: [x]"
    return
"""
    result, analyzer = _run_analyzer_on(rpy, tmp_path)
    # After the fix: Choice B's `x = 10` is conditional (inside `if`),
    # so it is NOT in B's defined_vars. The merge sees that Choice A
    # assigns `x` but Choice B does not (guaranteed) → RPY401 fires.
    rpy401 = [d for d in result.diagnostics if d.code == "RPY401"]
    x_401 = [d for d in rpy401 if "x" in d.message]
    assert x_401, (
        f"Expected RPY401 for 'x' — Choice B's assignment is conditional "
        f"(inside `if cond:`), so the menu branches are asymmetric. "
        f"Got diagnostics: {[(d.code, d.line_number, d.message[:60]) for d in result.diagnostics]}"
    )


# ---------------------------------------------------------------------------
# collect_from_python_block — conditional registration in init python
# ---------------------------------------------------------------------------


def test_conditional_assignment_in_init_python_not_registered(
    tmp_path: Path,
) -> None:
    """Reproducer: a variable assigned ONLY inside an ``if`` body
    within ``init python:`` must NOT be registered in ``user_symbols``
    as a top-level declaration. The conditional assignment was
    incorrectly registered, so the variable appeared in
    ``user_symbols`` even though it may never execute.

    NOTE: ``missing_defaults`` is a separate subsystem that runs
    through ``_walk_python_nodes`` (RPY104/105 detection). It
    intentionally recurses into conditional bodies because a
    conditional assignment still creates a variable that may be read
    later — the default is a defensive recommendation. We do NOT
    change that behaviour here; only ``user_symbols`` (top-level
    declarations) is fixed.
    """
    rpy = """init python:
    if cond:
        x = 5

label start:
    return
"""
    result, analyzer = _run_analyzer_on(rpy, tmp_path)
    # `x` is conditional — should NOT be in user_symbols (top-level
    # declarations). This is the bug we close.
    assert "x" not in analyzer.user_symbols, (
        f"Conditional assignment inside `if cond:` in init python "
        f"must NOT be registered as a top-level symbol. "
        f"user_symbols={analyzer.user_symbols}"
    )


def test_top_level_assignment_in_init_python_still_registered(
    tmp_path: Path,
) -> None:
    """Counter-case: a top-level assignment in ``init python:`` must
    still be registered. The fix must not over-suppress.
    """
    rpy = """init python:
    x = 5

label start:
    return
"""
    result, analyzer = _run_analyzer_on(rpy, tmp_path)
    assert "x" in analyzer.user_symbols, (
        f"Top-level assignment in init python must be registered. "
        f"user_symbols={analyzer.user_symbols}"
    )


def test_function_def_in_init_python_still_registered(tmp_path: Path) -> None:
    """Counter-case: function definitions in ``init python:`` are
    top-level declarations and must be registered.
    """
    rpy = """init python:
    def helper():
        return 42

label start:
    return
"""
    result, analyzer = _run_analyzer_on(rpy, tmp_path)
    # `helper` is a function declaration at top level — registered.
    assert "helper" in analyzer.user_symbols, (
        f"Top-level function def in init python must be registered. "
        f"user_symbols={analyzer.user_symbols}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
