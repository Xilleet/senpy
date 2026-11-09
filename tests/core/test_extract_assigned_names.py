"""TDD tests for ``extract_assigned_names`` and ``clear_safe_cfg_vars`` —
tuple unpacking, walrus, AnnAssign, AugAssign support.

Both functions used to only handle ``ast.Assign`` with ``ast.Name``
targets, missing:
  - **Tuple unpacking:** ``$ a, b = 1, 2`` → ``ast.Tuple`` target.
  - **Walrus:** ``$ (x := 5)`` → ``ast.NamedExpr``.
  - **AnnAssign:** ``$ x: int = 5`` → ``ast.AnnAssign``.
  - **AugAssign:** ``$ x += 1`` → ``ast.AugAssign`` (roadmap mentions
    this as RPY104 false-negative).

Consequences:
  - False-positive RPY404 after ``$ a, x = f()`` — ``x`` not in
    ``defined_vars``, falls into ``maybe_set``, then RPY404 on read.
  - False-negative RPY104 — augmented assign ``x += 1`` not detected
    as missing default.
"""

from __future__ import annotations

import logging

import pytest

from senpy.rules.python_ast import PythonAstChecker, extract_assigned_names

# ===========================================================================
# extract_assigned_names — new AST forms
# ===========================================================================


class TestExtractAssignedNamesTupleUnpacking:
    """``$ a, b = 1, 2`` must extract both ``a`` and ``b``."""

    def test_tuple_unpacking_extracts_all_names(self):
        """``a, b = 1, 2`` → {a, b}."""
        result = extract_assigned_names("a, b = 1, 2")
        assert "a" in result, "Tuple unpacking: 'a' was not extracted."
        assert "b" in result, "Tuple unpacking: 'b' was not extracted."

    def test_tuple_unpacking_three_vars(self):
        """``a, b, c = 1, 2, 3`` → {a, b, c}."""
        result = extract_assigned_names("a, b, c = 1, 2, 3")
        assert result == {"a", "b", "c"}

    def test_nested_tuple_unpacking(self):
        """``a, (b, c) = 1, (2, 3)`` → {a, b, c}."""
        result = extract_assigned_names("a, (b, c) = 1, (2, 3)")
        assert "a" in result
        assert "b" in result
        assert "c" in result

    def test_list_unpacking(self):
        """``[a, b] = 1, 2`` → {a, b} (list target, not tuple)."""
        result = extract_assigned_names("[a, b] = 1, 2")
        assert "a" in result
        assert "b" in result

    def test_starred_unpacking(self):
        """``a, *b = [1, 2, 3]`` → {a, b}."""
        result = extract_assigned_names("a, *b = [1, 2, 3]")
        assert "a" in result
        assert "b" in result


class TestExtractAssignedNamesWalrus:
    """``$ (x := 5)`` must extract ``x``."""

    def test_walrus_extracts_name(self):
        """``(x := 5)`` → {x}."""
        result = extract_assigned_names("(x := 5)")
        assert "x" in result, "Walrus operator: 'x' was not extracted."

    def test_nested_walrus(self):
        """``(x := (y := 5))`` → {x, y}."""
        result = extract_assigned_names("(x := (y := 5))")
        assert "x" in result
        assert "y" in result

    def test_walrus_in_expression(self):
        """``result = (x := 5) + 10`` → {result, x}."""
        result = extract_assigned_names("result = (x := 5) + 10")
        assert "result" in result
        assert "x" in result


class TestExtractAssignedNamesAnnAssign:
    """``$ x: int = 5`` must extract ``x``."""

    def test_annassign_extracts_name(self):
        """``x: int = 5`` → {x}."""
        result = extract_assigned_names("x: int = 5")
        assert "x" in result, "AnnAssign: 'x' was not extracted."

    def test_annassign_without_value(self):
        """``x: int`` (no value) → {x} (declaration without assignment).

        In Ren'Py ``$ x: int`` is unusual but valid Python — the variable
        is declared but not assigned. We still want to track it as
        "assigned" (declared) so it doesn't trigger RPY404.
        """
        result = extract_assigned_names("x: int")
        assert "x" in result, "AnnAssign without value: 'x' was not extracted."

    def test_annassign_complex_type(self):
        """``x: list[str] = []`` → {x}."""
        result = extract_assigned_names("x: list[str] = []")
        assert "x" in result


class TestExtractAssignedNamesAugAssign:
    """``$ x += 1`` must extract ``x`` (augmented assignment).

    Roadmap mentions this as RPY104 false-negative — augmented assign
    ``x += 1`` was not detected, meaning ``x`` was not tracked as
    "used/assigned", so RPY104 (missing default) could miss it.
    """

    def test_augassign_extracts_name(self):
        """``x += 1`` → {x}."""
        result = extract_assigned_names("x += 1")
        assert "x" in result, "AugAssign: 'x' was not extracted."

    def test_augassign_subtract(self):
        """``x -= 5`` → {x}."""
        result = extract_assigned_names("x -= 5")
        assert "x" in result


class TestExtractAssignedNamesRegression:
    """Regression: existing plain assignments must still work."""

    def test_plain_assignment(self):
        """``x = 5`` → {x} (existing behaviour, must not break)."""
        result = extract_assigned_names("x = 5")
        assert result == {"x"}

    def test_multiple_assignments(self):
        """``x = 5; y = 10`` → {x, y}."""
        result = extract_assigned_names("x = 5\ny = 10")
        assert result == {"x", "y"}

    def test_chained_assignment(self):
        """``a = b = 5`` → {a, b}."""
        result = extract_assigned_names("a = b = 5")
        assert "a" in result
        assert "b" in result

    def test_syntax_error_returns_empty(self):
        """SyntaxError → empty set (existing behaviour)."""
        result = extract_assigned_names("x = :")
        assert result == set()


# ===========================================================================
# clear_safe_cfg_vars — new AST forms
# ===========================================================================


class TestClearSafeCfgVarsTupleUnpacking:
    """``clear_safe_cfg_vars`` must remove tuple-unpacked vars from
    ``branch_uninitialized``.
    """

    def test_tuple_unpacking_clears_all_names(self):
        """``a, b = 1, 2`` removes both ``a`` and ``b`` from
        ``branch_uninitialized``.
        """
        from unittest.mock import MagicMock

        checker = PythonAstChecker.__new__(PythonAstChecker)
        branch_uninitialized = {"a": True, "b": True, "c": True}
        checker.clear_safe_cfg_vars("a, b = 1, 2", branch_uninitialized)

        assert (
            "a" not in branch_uninitialized
        ), "Tuple unpacking: 'a' should be removed from branch_uninitialized."
        assert (
            "b" not in branch_uninitialized
        ), "Tuple unpacking: 'b' should be removed from branch_uninitialized."
        assert "c" in branch_uninitialized, "Unrelated 'c' should remain."

    def test_annassign_clears_name(self):
        """``x: int = 5`` removes ``x`` from ``branch_uninitialized``."""
        checker = PythonAstChecker.__new__(PythonAstChecker)
        branch_uninitialized = {"x": True, "y": True}
        checker.clear_safe_cfg_vars("x: int = 5", branch_uninitialized)

        assert "x" not in branch_uninitialized, "AnnAssign: 'x' should be removed."
        assert "y" in branch_uninitialized

    def test_augassign_clears_name(self):
        """``x += 1`` removes ``x`` from ``branch_uninitialized``.

        Augmented assign means ``x`` is used (and must have existed
        before), so it should be cleared from the "maybe uninitialized"
        set.
        """
        checker = PythonAstChecker.__new__(PythonAstChecker)
        branch_uninitialized = {"x": True}
        checker.clear_safe_cfg_vars("x += 1", branch_uninitialized)

        assert (
            "x" not in branch_uninitialized
        ), "AugAssign: 'x' should be removed from branch_uninitialized."

    def test_walrus_clears_name(self):
        """``(x := 5)`` removes ``x`` from ``branch_uninitialized``."""
        checker = PythonAstChecker.__new__(PythonAstChecker)
        branch_uninitialized = {"x": True, "y": True}
        checker.clear_safe_cfg_vars("(x := 5)", branch_uninitialized)

        assert "x" not in branch_uninitialized, "Walrus: 'x' should be removed."
        assert "y" in branch_uninitialized

    def test_plain_assignment_still_works(self):
        """``x = 5`` removes ``x`` (existing behaviour, regression guard)."""
        checker = PythonAstChecker.__new__(PythonAstChecker)
        branch_uninitialized = {"x": True, "y": True}
        checker.clear_safe_cfg_vars("x = 5", branch_uninitialized)

        assert "x" not in branch_uninitialized
        assert "y" in branch_uninitialized
