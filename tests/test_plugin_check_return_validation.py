"""Tests for plugin check() return-type validation.

``analysis_pipeline.py:550-554`` iterated over the list returned by a
plugin's ``check()`` method and called ``_add_diagnostic_by_file(diag)``
on each element without validating the type. If a plugin returned
``[None]``, ``["string"]``, or any list containing non-``Diagnostic``
elements, ``_add_diagnostic_by_file`` crashed with
``AttributeError: 'NoneType'/'str' object has no attribute 'file_path'``.

The crash happened OUTSIDE the ``try/except`` around ``check()`` (lines
537-545) — that try/except only catches exceptions raised BY ``check()``,
not exceptions raised while iterating its return value. The result: one
bad plugin killed the entire analysis run, violating the "plugin
isolation" contract (``base.py:163`` says errors in one rule must not
stop the analyzer).

The fix: add ``isinstance(diag, Diagnostic)`` check inside the
``for diag in returned:`` loop. Non-``Diagnostic`` elements are logged
as WARNING and skipped — the analyzer continues with the valid
diagnostics from the same plugin and from other plugins.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.models import Diagnostic
from senpy.plugins.base import Rule, RuleContext, RuleMeta
from senpy.plugins.registry import _REGISTERED_LINT_RULES


def _make_project(tmp_path: Path) -> Path:
    """Create a minimal project with one .rpy file."""
    game = tmp_path / "game"
    game.mkdir(parents=True, exist_ok=True)
    (game / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")
    return tmp_path


def _enable_plugins(analyzer: SenpyAnalyzer) -> None:
    """Force-enable plugin execution on the analyzer (default is False)."""
    analyzer.enable_plugins = True


class _GoodRule(Rule):
    """A well-behaved plugin rule that returns a valid Diagnostic."""

    meta = RuleMeta(
        code="RPY900",
        docs="test",
        severity="WARNING",
        tags=["test"],
    )

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        return [
            Diagnostic(
                file_path=ctx.file_path,
                line_number=1,
                line_content="label start:",
                code="RPY900",
                message="Good rule fired",
                severity="WARNING",
            )
        ]


class _BadReturnNoneElement(Rule):
    """A plugin rule that returns a list containing None — contract violation."""

    meta = RuleMeta(
        code="RPY901",
        docs="test",
        severity="WARNING",
        tags=["test"],
    )

    def check(self, ctx: RuleContext) -> list:
        # Contract violation: returns [None] instead of [Diagnostic].
        # Before P1-9: _add_diagnostic_by_file(None) → AttributeError.
        return [None]


class _BadReturnStringElement(Rule):
    """A plugin rule that returns a list containing a string."""

    meta = RuleMeta(
        code="RPY902",
        docs="test",
        severity="WARNING",
        tags=["test"],
    )

    def check(self, ctx: RuleContext) -> list:
        return ["not a diagnostic"]


class _MixedReturnRule(Rule):
    """A plugin rule that returns [None, 'string', valid_diagnostic]."""

    meta = RuleMeta(
        code="RPY903",
        docs="test",
        severity="WARNING",
        tags=["test"],
    )

    def check(self, ctx: RuleContext) -> list:
        return [
            None,
            "not a diagnostic",
            Diagnostic(
                file_path=ctx.file_path,
                line_number=1,
                line_content="label start:",
                code="RPY903",
                message="Mixed rule valid diagnostic",
                severity="WARNING",
            ),
        ]


class TestPluginCheckReturnTypeValidation:
    """Plugin check() return-type must be validated — bad elements skipped, not crashed."""

    def test_plugin_returning_none_element_does_not_crash(self, tmp_path: Path):
        """A plugin returning [None] must not crash the analyzer.

        Before P1-9: _add_diagnostic_by_file(None) raised AttributeError
        ('NoneType' has no attribute 'file_path'), killing the analysis.
        After P1-9: None is logged as WARNING and skipped.
        """
        project = _make_project(tmp_path)
        analyzer = SenpyAnalyzer(str(project), no_cache=True)
        _enable_plugins(analyzer)

        # Register the bad plugin rule directly (bypass autoload).
        _REGISTERED_LINT_RULES.append((_BadReturnNoneElement.meta.code, _BadReturnNoneElement))
        try:
            # Must not raise.
            analyzer.run(quiet=True)
        finally:
            _REGISTERED_LINT_RULES.remove((_BadReturnNoneElement.meta.code, _BadReturnNoneElement))

        # No RPY901 diagnostics (the None was skipped, not added).
        rpy901 = [d for d in analyzer.diagnostics if d.code == "RPY901"]
        assert rpy901 == [], f"Plugin returning [None] must not produce diagnostics. Got: {rpy901}"

    def test_plugin_returning_string_element_does_not_crash(self, tmp_path: Path):
        """A plugin returning ['string'] must not crash the analyzer."""
        project = _make_project(tmp_path)
        analyzer = SenpyAnalyzer(str(project), no_cache=True)
        _enable_plugins(analyzer)
        _REGISTERED_LINT_RULES.append((_BadReturnStringElement.meta.code, _BadReturnStringElement))
        try:
            analyzer.run(quiet=True)
        finally:
            _REGISTERED_LINT_RULES.remove(
                (_BadReturnStringElement.meta.code, _BadReturnStringElement)
            )

        rpy902 = [d for d in analyzer.diagnostics if d.code == "RPY902"]
        assert (
            rpy902 == []
        ), f"Plugin returning ['string'] must not produce diagnostics. Got: {rpy902}"

    def test_mixed_return_keeps_valid_diagnostics(self, tmp_path: Path):
        """[None, 'string', Diagnostic] — valid Diagnostic kept, others skipped.

        The key assertion: the analyzer does NOT crash (isolation holds),
        AND the valid Diagnostic from the same plugin IS recorded. This
        proves the fix skips bad elements individually, not the whole list.
        """
        project = _make_project(tmp_path)
        analyzer = SenpyAnalyzer(str(project), no_cache=True)
        _enable_plugins(analyzer)
        _REGISTERED_LINT_RULES.append((_MixedReturnRule.meta.code, _MixedReturnRule))
        try:
            analyzer.run(quiet=True)
        finally:
            _REGISTERED_LINT_RULES.remove((_MixedReturnRule.meta.code, _MixedReturnRule))

        # The valid Diagnostic (RPY903) must be recorded.
        rpy903 = [d for d in analyzer.diagnostics if d.code == "RPY903"]
        assert len(rpy903) == 1, (
            f"Plugin returning [None, 'str', Diagnostic] must keep the valid "
            f"Diagnostic (RPY903). Got: {rpy903}"
        )
        assert rpy903[0].message == "Mixed rule valid diagnostic"

    def test_good_plugin_still_works(self, tmp_path: Path):
        """Sanity: a well-behaved plugin must still produce diagnostics.

        Guards against the fix accidentally rejecting valid Diagnostics.
        """
        project = _make_project(tmp_path)
        analyzer = SenpyAnalyzer(str(project), no_cache=True)
        _enable_plugins(analyzer)
        _REGISTERED_LINT_RULES.append((_GoodRule.meta.code, _GoodRule))
        try:
            analyzer.run(quiet=True)
        finally:
            _REGISTERED_LINT_RULES.remove((_GoodRule.meta.code, _GoodRule))

        rpy900 = [d for d in analyzer.diagnostics if d.code == "RPY900"]
        assert len(rpy900) == 1, f"Good plugin must still produce its Diagnostic. Got: {rpy900}"

    def test_bad_plugin_does_not_kill_other_plugins(self, tmp_path: Path):
        """Isolation: a bad plugin must not prevent a good plugin from running.

        Register both _BadReturnNoneElement and _GoodRule. The good plugin
        must still produce its diagnostic even though the bad plugin
        returned [None]. Before P1-9: the bad plugin crashed the analysis
        loop, so the good plugin (registered after) never ran.
        """
        project = _make_project(tmp_path)
        analyzer = SenpyAnalyzer(str(project), no_cache=True)
        _enable_plugins(analyzer)
        _REGISTERED_LINT_RULES.append((_BadReturnNoneElement.meta.code, _BadReturnNoneElement))
        _REGISTERED_LINT_RULES.append((_GoodRule.meta.code, _GoodRule))
        try:
            analyzer.run(quiet=True)
        finally:
            _REGISTERED_LINT_RULES.remove((_BadReturnNoneElement.meta.code, _BadReturnNoneElement))
            _REGISTERED_LINT_RULES.remove((_GoodRule.meta.code, _GoodRule))

        # The good plugin's diagnostic must be present — isolation held.
        rpy900 = [d for d in analyzer.diagnostics if d.code == "RPY900"]
        assert rpy900, (
            "Good plugin must still run after a bad plugin returned [None]. "
            "If this fails, the bad plugin crashed the analysis loop — "
            "isolation contract violated."
        )
