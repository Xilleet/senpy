"""Characterization tests for ``_check_rpy403_condition`` (CC=24, max in project).

These tests document the CURRENT behaviour of the function before any
refactoring. The goal (per §5 of the dev assist: "Перед рефакторингом
добавляй characterization-тесты") is to lock in every branch so a
dispatch-table refactor cannot silently change semantics.

The function handles four RPY403 cases on an ``if``/``elif`` condition:

    1. Always-False: ``if False:``, ``if 0:``, ``if "":``, ``if []:``,
       ``if None:`` → emits RPY403 "always False".
    2. Always-True: ``if True:``, ``if 1:``, ``if "non-empty":`` →
       emits RPY403 "always True", EXCEPT for bare ``True`` and ``1``
       (which are treated as intentional and skipped).
    3. Contradiction in AND: ``if x and not x:`` → emits RPY403
       "contradiction, always False".
    4. Tautology in OR: ``if x or not x:`` → emits RPY403 "tautology,
       always True".

The function is called via ``check_condition`` which parses the
condition expression into an ``ast.Expression`` node. We test the
public entry point (``check_condition``) to capture the full path.

After the characterization tests are in place, the refactor can
proceed safely: any behavioural change will fail one of these tests.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.models import Diagnostic
from senpy.rules.python_ast import PythonAstChecker


def _make_checker(analyzer: SenpyAnalyzer) -> PythonAstChecker:
    return PythonAstChecker(analyzer)


def _check_condition(analyzer: SenpyChecker_fixture, expr: str) -> list[Diagnostic]:
    """Run ``check_condition`` on `expr` and return any RPY403 diagnostics."""
    analyzer.diagnostics.clear()
    checker = _make_checker(analyzer)
    checker.check_condition(
        file_path="test.rpy",
        line_idx=1,
        line_content=f"if {expr}:",
        expr=expr,
        screen_name=None,
        screen_local_symbols=set(),
        noqa_map={},
    )
    return [d for d in analyzer.diagnostics if d.code == "RPY403"]


# Type alias for clarity in fixture signatures.
SenpyChecker_fixture = SenpyAnalyzer


@pytest.fixture
def analyzer(tmp_path: Path) -> SenpyAnalyzer:
    """A minimal analyzer with an empty project."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "scenario.rpy").write_text("label start:\n    return\n", encoding="utf-8")
    a = SenpyAnalyzer(str(tmp_path))
    a.run(quiet=True)
    return a


# ---------------------------------------------------------------------------
# Always-False conditions
# ---------------------------------------------------------------------------


class TestAlwaysFalse:
    """``if False:``, ``if 0:``, ``if "":``, ``if None:``.

    NOTE: the current implementation only handles ``ast.Constant`` —
    empty containers like ``[]`` and ``{}`` are ``ast.List``/``ast.Dict``
    and are NOT detected as always-False. This is a known limitation
    that the characterization tests document.
    """

    @pytest.mark.parametrize("expr", ["False", "0", '""', "''", "None"])
    def test_emits_rpy403_always_false(self, analyzer, expr: str) -> None:
        diags = _check_condition(analyzer, expr)
        assert len(diags) == 1, f"Expected 1 RPY403 for {expr!r}, got {len(diags)}"
        assert "always False" in diags[0].message

    @pytest.mark.parametrize("expr", ["[]", "{}"])
    def test_empty_containers_NOT_detected(self, analyzer, expr: str) -> None:
        """Empty containers are ``ast.List``/``ast.Dict``, not ``ast.Constant`` —
        the current implementation does not detect them as always-False.
        This is a known limitation documented by this test.
        """
        diags = _check_condition(analyzer, expr)
        assert diags == [], (
            f"Empty container {expr!r} is not handled by the current "
            f"Constant-only check — no RPY403. (Known limitation.)"
        )

    def test_message_contains_expression(self, analyzer) -> None:
        diags = _check_condition(analyzer, "False")
        assert "False" in diags[0].message
        assert "never execute" in diags[0].message


# ---------------------------------------------------------------------------
# Always-True conditions (with the True/1 exception)
# ---------------------------------------------------------------------------


class TestAlwaysTrue:
    """``if True:``, ``if 1:``, ``if "non-empty":``, etc."""

    def test_bare_True_skipped(self, analyzer) -> None:
        """``if True:`` is treated as intentional — no RPY403."""
        diags = _check_condition(analyzer, "True")
        assert diags == [], f"Bare `True` should NOT emit RPY403. Got: {diags}"

    def test_bare_1_skipped(self, analyzer) -> None:
        """``if 1:`` is treated as intentional — no RPY403."""
        diags = _check_condition(analyzer, "1")
        assert diags == [], f"Bare `1` should NOT emit RPY403. Got: {diags}"

    @pytest.mark.parametrize("expr", ['"non-empty"', "'non-empty'", "2"])
    def test_non_bare_truthy_emits_rpy403(self, analyzer, expr: str) -> None:
        diags = _check_condition(analyzer, expr)
        assert len(diags) == 1, f"Expected 1 RPY403 for {expr!r}, got {len(diags)}"
        assert "always True" in diags[0].message
        assert "redundant" in diags[0].message or "simplify" in diags[0].message

    @pytest.mark.parametrize("expr", ["-1", "[1]", "{'k': 'v'}"])
    def test_non_constant_truthy_NOT_detected(self, analyzer, expr: str) -> None:
        """Non-Constant truthy expressions (UnaryOp/List/Dict) are NOT
        detected as always-True by the current implementation — it only
        checks ``ast.Constant``. Known limitation.
        """
        diags = _check_condition(analyzer, expr)
        assert diags == [], (
            f"Non-Constant truthy {expr!r} is not handled by the current "
            f"Constant-only check — no RPY403. (Known limitation.)"
        )

    def test_message_contains_expression(self, analyzer) -> None:
        diags = _check_condition(analyzer, '"non-empty"')
        assert '"non-empty"' in diags[0].message


# ---------------------------------------------------------------------------
# Contradiction in AND
# ---------------------------------------------------------------------------


class TestContradictionAnd:
    """``if x and not x:`` → contradiction, always False."""

    def test_simple_contradiction(self, analyzer) -> None:
        diags = _check_condition(analyzer, "x and not x")
        assert len(diags) == 1
        assert "contradiction" in diags[0].message.lower()
        assert "always" in diags[0].message.lower()
        assert "False" in diags[0].message or "false" in diags[0].message.lower()
        assert "x" in diags[0].message

    def test_contradiction_with_other_clauses(self, analyzer) -> None:
        """``if y and x and not x:`` — contradiction still detected."""
        diags = _check_condition(analyzer, "y and x and not x")
        assert len(diags) == 1
        assert "x" in diags[0].message

    def test_no_contradiction_for_distinct_vars(self, analyzer) -> None:
        """``if x and not y:`` — no contradiction, no RPY403."""
        diags = _check_condition(analyzer, "x and not y")
        assert diags == []

    def test_no_contradiction_for_double_negation(self, analyzer) -> None:
        """``if not not x:`` — not a contradiction pattern (the function
        only checks `x and not x` form, not arbitrary boolean algebra).
        """
        diags = _check_condition(analyzer, "not not x")
        # No contradiction detected — function only checks `x and not x`.
        assert diags == []


# ---------------------------------------------------------------------------
# Tautology in OR
# ---------------------------------------------------------------------------


class TestTautologyOr:
    """``if x or not x:`` → tautology, always True."""

    def test_simple_tautology(self, analyzer) -> None:
        diags = _check_condition(analyzer, "x or not x")
        assert len(diags) == 1
        assert "tautology" in diags[0].message.lower()
        assert "always" in diags[0].message.lower()
        assert "True" in diags[0].message or "true" in diags[0].message.lower()
        assert "x" in diags[0].message

    def test_tautology_with_other_clauses(self, analyzer) -> None:
        """``if y or x or not x:`` — tautology still detected."""
        diags = _check_condition(analyzer, "y or x or not x")
        assert len(diags) == 1
        assert "x" in diags[0].message

    def test_no_tautology_for_distinct_vars(self, analyzer) -> None:
        """``if x or not y:`` — no tautology, no RPY403."""
        diags = _check_condition(analyzer, "x or not y")
        assert diags == []


# ---------------------------------------------------------------------------
# Conditions that should NOT trigger RPY403
# ---------------------------------------------------------------------------


class TestNoRpy403:
    """Conditions that are neither always-True, always-False,
    contradictions, nor tautologies — must NOT emit RPY403.
    """

    @pytest.mark.parametrize(
        "expr",
        [
            "has_key",
            "player_level > 5",
            "has_key and player_level > 5",
            "x or y",
            "x and y",
            "not x",
            "len(items) > 0",
            "score == 100",
        ],
    )
    def test_no_rpy403(self, analyzer, expr: str) -> None:
        diags = _check_condition(analyzer, expr)
        assert diags == [], f"Expected no RPY403 for {expr!r}, got: {diags}"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases that the current implementation handles (or not)."""

    def test_empty_string_is_falsy(self, analyzer) -> None:
        """``if "":`` — empty string is falsy → always False."""
        diags = _check_condition(analyzer, '""')
        assert len(diags) == 1
        assert "always False" in diags[0].message

    def test_zero_is_falsy(self, analyzer) -> None:
        """``if 0:`` — zero is falsy → always False."""
        diags = _check_condition(analyzer, "0")
        assert len(diags) == 1
        assert "always False" in diags[0].message

    def test_negative_number_NOT_detected(self, analyzer) -> None:
        """``-1`` is ``UnaryOp(USub, Constant(1))`` — not a bare ``Constant``.
        The current implementation does not detect it as always-True.
        Known limitation.
        """
        diags = _check_condition(analyzer, "-1")
        assert diags == [], (
            "`-1` is UnaryOp, not Constant — not handled by the current "
            "Constant-only check. (Known limitation.)"
        )

    def test_contradiction_message_format(self, analyzer) -> None:
        """The contradiction message mentions both `x` and `not x`."""
        diags = _check_condition(analyzer, "x and not x")
        msg = diags[0].message
        assert "x" in msg
        assert "not x" in msg or "not {var}".format(var="x") in msg

    def test_tautology_message_format(self, analyzer) -> None:
        """The tautology message mentions both `x` and `not x`."""
        diags = _check_condition(analyzer, "x or not x")
        msg = diags[0].message
        assert "x" in msg
        assert "not x" in msg or "not {var}".format(var="x") in msg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
