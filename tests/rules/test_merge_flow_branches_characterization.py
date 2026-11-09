"""Characterization tests for ``merge_flow_branches`` (CC=22, #2 in project).

These tests document the CURRENT behaviour of the function before any
refactoring. The goal (per §5 of the dev assist: "Перед рефакторингом
добавляй characterization-тесты") is to lock in every branch so a
split refactor cannot silently change semantics.

The function merges parallel branches (if/elif/else or menu choices)
and returns:
    - guaranteed_vars: variables guaranteed to be set on all non-terminating paths
    - uninitialized_vars: dict of MAYBE_SET variables with metadata
    - all_terminating: True if absolutely all branches exit via jump/return

Key branches:
    1. No non-terminating branches → return (set(), {}, True).
    2. Menu: guaranteed = intersection of non-terminating branches.
    3. If with else: guaranteed = intersection of non-terminating branches.
    4. If without else: guaranteed = set() (no branch is guaranteed).
    5. Maybe_set = all_defined - guaranteed.
    6. Skip vars in known_symbols or already_guaranteed.
    7. For each maybe_set var, build metadata tuple.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from senpy.rules.flow import FlowBranch, merge_flow_branches


def _branch(
    name: str,
    defined_vars: set[str] | None = None,
    terminates: bool = False,
    kind: str = "choice",
    line: int = 1,
) -> FlowBranch:
    """Build a FlowBranch with sensible defaults for tests."""
    return FlowBranch(
        kind=kind,
        name=name,
        line=line,
        defined_vars=defined_vars or set(),
        terminates=terminates,
        raw="",
    )


# ---------------------------------------------------------------------------
# Edge cases: empty / all-terminating
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_branches_list(self) -> None:
        """Empty branches list → no non-terminating branches →
        return (set(), {}, True).
        """
        guaranteed, uninit, all_term = merge_flow_branches(
            branches=[],
            block_kind="if",
            block_line=1,
            has_else=False,
            known_symbols=set(),
            already_guaranteed=set(),
        )
        assert guaranteed == set()
        assert uninit == {}
        assert all_term is True

    def test_all_branches_terminating(self) -> None:
        """All branches terminate (jump/return) → all_term=True."""
        branches = [
            _branch("a", terminates=True),
            _branch("b", terminates=True),
        ]
        guaranteed, uninit, all_term = merge_flow_branches(
            branches=branches,
            block_kind="if",
            block_line=1,
            has_else=False,
            known_symbols=set(),
            already_guaranteed=set(),
        )
        assert guaranteed == set()
        assert uninit == {}
        assert all_term is True


# ---------------------------------------------------------------------------
# Menu: intersection of non-terminating branches
# ---------------------------------------------------------------------------


class TestMenuGuaranteed:
    def test_intersection_when_all_branches_set_var(self) -> None:
        """Menu with two choices both setting `x` → `x` is guaranteed."""
        branches = [
            _branch("A", defined_vars={"x"}),
            _branch("B", defined_vars={"x"}),
        ]
        guaranteed, _, _ = merge_flow_branches(
            branches=branches,
            block_kind="menu",
            block_line=1,
            has_else=True,
            known_symbols=set(),
            already_guaranteed=set(),
        )
        assert "x" in guaranteed

    def test_no_guaranteed_when_one_branch_missing_var(self) -> None:
        """Menu: A sets x, B does not → x is MAYBE_SET, not guaranteed."""
        branches = [
            _branch("A", defined_vars={"x"}),
            _branch("B", defined_vars=set()),
        ]
        guaranteed, uninit, _ = merge_flow_branches(
            branches=branches,
            block_kind="menu",
            block_line=1,
            has_else=True,
            known_symbols=set(),
            already_guaranteed=set(),
        )
        assert "x" not in guaranteed
        assert "x" in uninit

    def test_intersection_of_multiple_vars(self) -> None:
        """Menu: A sets {x, y}, B sets {x, z} → only x is guaranteed."""
        branches = [
            _branch("A", defined_vars={"x", "y"}),
            _branch("B", defined_vars={"x", "z"}),
        ]
        guaranteed, uninit, _ = merge_flow_branches(
            branches=branches,
            block_kind="menu",
            block_line=1,
            has_else=True,
            known_symbols=set(),
            already_guaranteed=set(),
        )
        assert guaranteed == {"x"}
        assert "y" in uninit
        assert "z" in uninit


# ---------------------------------------------------------------------------
# If/elif/else: guaranteed only when has_else and >1 branches
# ---------------------------------------------------------------------------


class TestIfGuaranteed:
    def test_if_with_else_intersection(self) -> None:
        """if/else with both branches setting x → x guaranteed."""
        branches = [
            _branch("if", defined_vars={"x"}, kind="if"),
            _branch("else", defined_vars={"x"}, kind="else"),
        ]
        guaranteed, _, _ = merge_flow_branches(
            branches=branches,
            block_kind="if",
            block_line=1,
            has_else=True,
            known_symbols=set(),
            already_guaranteed=set(),
        )
        assert "x" in guaranteed

    def test_if_without_else_no_guaranteed(self) -> None:
        """if without else: no branch is guaranteed (if-condition may be False)."""
        branches = [
            _branch("if", defined_vars={"x"}, kind="if"),
        ]
        guaranteed, uninit, _ = merge_flow_branches(
            branches=branches,
            block_kind="if",
            block_line=1,
            has_else=False,
            known_symbols=set(),
            already_guaranteed=set(),
        )
        assert guaranteed == set()
        assert "x" in uninit

    def test_if_without_else_single_branch_terminating(self) -> None:
        """Single if branch that terminates → all_term=True (no non-terminating)."""
        branches = [
            _branch("if", defined_vars={"x"}, kind="if", terminates=True),
        ]
        guaranteed, uninit, all_term = merge_flow_branches(
            branches=branches,
            block_kind="if",
            block_line=1,
            has_else=False,
            known_symbols=set(),
            already_guaranteed=set(),
        )
        assert guaranteed == set()
        assert uninit == {}
        assert all_term is True


# ---------------------------------------------------------------------------
# Maybe_set computation
# ---------------------------------------------------------------------------


class TestMaybeSet:
    def test_maybe_set_excludes_guaranteed(self) -> None:
        """maybe_set = all_defined - guaranteed."""
        branches = [
            _branch("A", defined_vars={"x", "y"}),
            _branch("B", defined_vars={"x"}),
        ]
        guaranteed, uninit, _ = merge_flow_branches(
            branches=branches,
            block_kind="menu",
            block_line=1,
            has_else=True,
            known_symbols=set(),
            already_guaranteed=set(),
        )
        assert guaranteed == {"x"}
        assert "y" in uninit
        assert "x" not in uninit

    def test_maybe_set_excludes_known_symbols(self) -> None:
        """Vars in known_symbols (default/define declared) are skipped."""
        branches = [
            _branch("A", defined_vars={"x"}),
            _branch("B", defined_vars=set()),
        ]
        guaranteed, uninit, _ = merge_flow_branches(
            branches=branches,
            block_kind="menu",
            block_line=1,
            has_else=True,
            known_symbols={"x"},
            already_guaranteed=set(),
        )
        # x is in known_symbols → not flagged as MAYBE_SET
        assert "x" not in uninit

    def test_maybe_set_excludes_already_guaranteed(self) -> None:
        """Vars in already_guaranteed (set before the block) are skipped."""
        branches = [
            _branch("A", defined_vars={"x"}),
            _branch("B", defined_vars=set()),
        ]
        guaranteed, uninit, _ = merge_flow_branches(
            branches=branches,
            block_kind="menu",
            block_line=1,
            has_else=True,
            known_symbols=set(),
            already_guaranteed={"x"},
        )
        # x is already guaranteed → not flagged as MAYBE_SET
        assert "x" not in uninit


# ---------------------------------------------------------------------------
# Metadata tuple format
# ---------------------------------------------------------------------------


class TestMetadataTuple:
    def test_menu_metadata_format(self) -> None:
        """Menu metadata: (missing_desc, defined_desc, missing_line_str)."""
        branches = [
            _branch("Choice A", defined_vars={"x"}, line=10),
            _branch("Choice B", defined_vars=set(), line=15),
        ]
        _, uninit, _ = merge_flow_branches(
            branches=branches,
            block_kind="menu",
            block_line=1,
            has_else=True,
            known_symbols=set(),
            already_guaranteed=set(),
        )
        assert "x" in uninit
        missing_desc, defined_desc, missing_line = uninit["x"]
        assert "Choice B" in missing_desc  # missing branch name
        assert "Choice A" in defined_desc  # defined branch name
        assert missing_line == "15"  # missing branch line as string

    def test_if_with_else_metadata(self) -> None:
        """if/else metadata: missing_desc mentions the missing branch kind."""
        branches = [
            _branch("if branch", defined_vars={"x"}, kind="if", line=5),
            _branch("else branch", defined_vars=set(), kind="else", line=8),
        ]
        _, uninit, _ = merge_flow_branches(
            branches=branches,
            block_kind="if",
            block_line=1,
            has_else=True,
            known_symbols=set(),
            already_guaranteed=set(),
        )
        assert "x" in uninit
        missing_desc, defined_desc, missing_line = uninit["x"]
        assert "else" in missing_desc.lower()
        assert "if" in defined_desc.lower()

    def test_if_without_else_metadata(self) -> None:
        """if without else: missing_desc = "condition is False (no else branch)"."""
        branches = [
            _branch("if", defined_vars={"x"}, kind="if", line=3),
        ]
        _, uninit, _ = merge_flow_branches(
            branches=branches,
            block_kind="if",
            block_line=1,
            has_else=False,
            known_symbols=set(),
            already_guaranteed=set(),
        )
        assert "x" in uninit
        missing_desc, _, missing_line = uninit["x"]
        assert "False" in missing_desc or "no else" in missing_desc.lower()
        assert missing_line == "1"  # block_line as string


# ---------------------------------------------------------------------------
# all_terminating semantics
# ---------------------------------------------------------------------------


class TestAllTerminating:
    def test_all_terminating_when_all_branches_terminate(self) -> None:
        branches = [
            _branch("A", terminates=True, defined_vars={"x"}),
            _branch("B", terminates=True, defined_vars={"x"}),
        ]
        _, _, all_term = merge_flow_branches(
            branches=branches,
            block_kind="if",
            block_line=1,
            has_else=True,
            known_symbols=set(),
            already_guaranteed=set(),
        )
        assert all_term is True

    def test_not_all_terminating_when_one_continues(self) -> None:
        branches = [
            _branch("A", terminates=True, defined_vars={"x"}),
            _branch("B", terminates=False, defined_vars={"x"}),
        ]
        _, _, all_term = merge_flow_branches(
            branches=branches,
            block_kind="if",
            block_line=1,
            has_else=True,
            known_symbols=set(),
            already_guaranteed=set(),
        )
        assert all_term is False

    def test_all_terminating_false_when_no_terminating(self) -> None:
        branches = [
            _branch("A", terminates=False, defined_vars={"x"}),
            _branch("B", terminates=False, defined_vars={"x"}),
        ]
        _, _, all_term = merge_flow_branches(
            branches=branches,
            block_kind="if",
            block_line=1,
            has_else=True,
            known_symbols=set(),
            already_guaranteed=set(),
        )
        assert all_term is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
