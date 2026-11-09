"""Characterization tests for the synthesized RPY000 diagnostic.

RPY000 is not a user-facing rule — it is the internal error code that
``AnalysisPipeline._analyze_all_files`` emits when a built-in checker raises
an unhandled exception while analyzing a file. The pipeline already wraps
``_analyze_file`` in try/except and constructs::

    Diagnostic(code="RPY000", severity="ERROR", ...)

These tests pin down three properties that the rest of the codebase
(``senpy rule show``, ``senpy rule list``, renderers, severity overrides)
implicitly rely on:

  1. RPY000 is in ``RULES_DATABASE`` so that ``senpy rule show RPY000``
     can print its description instead of "Unknown rule code".
  2. RPY000's database severity is ``ERROR`` — internal errors must not
     be silently downgraded to WARNING by ``_apply_severity``'s fallback
     branch (``RULE_SEVERITY.get(code, "WARNING")``). This was the latent
     risk in audit BUG-1: the fallback only fires when a Diagnostic is
     constructed without a severity, but having RPY000 in the database
     with severity=ERROR makes the contract explicit and single-sourced.
  3. End-to-end: when ``_analyze_file`` raises, the resulting RPY000
     diagnostic actually reaches the final diagnostics list with
     ``severity == "ERROR"``, regardless of strict mode or overrides.

The third test exercises the full pipeline (not a unit test of
``_apply_severity``) — it constructs a real ``SenpyAnalyzer`` on a real
.rpy file and monkeypatches ``_analyze_file`` to raise. This is the
behaviour users see when they hit a Senpy bug.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from senpy.cli.rule_dispatch import dispatch_rule
from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.models import RULE_SEVERITY
from senpy.rules.rules_info import RULES_DATABASE

# =============================================================================
# Database membership / severity
# =============================================================================


class TestRPY000InRulesDatabase:
    def test_rpy000_is_in_rules_database(self) -> None:
        """RPY000 must be a registered rule, not an ad-hoc code.

        Without this, ``senpy rule show RPY000`` reports "Unknown rule
        code" and ``RULE_SEVERITY`` falls back to "WARNING" for any
        Diagnostic constructed without an explicit severity.
        """
        assert "RPY000" in RULES_DATABASE, (
            "RPY000 must be in RULES_DATABASE so `senpy rule show RPY000` "
            "works and the severity lookup is single-sourced."
        )

    def test_rpy000_severity_is_error(self) -> None:
        """The database entry for RPY000 must declare ERROR severity.

        Internal errors are not warnings — they signal a Senpy bug and
        should fail ``--fail-on-error`` runs and CI gates.
        """
        assert RULES_DATABASE["RPY000"]["severity"] == "ERROR"

    def test_rpy000_rule_severity_lookup_returns_error(self) -> None:
        """``RULE_SEVERITY`` (derived from RULES_DATABASE) must return
        ERROR for RPY000, not fall back to the WARNING default."""
        assert "RPY000" in RULE_SEVERITY
        assert RULE_SEVERITY["RPY000"] == "ERROR"

    def test_rpy000_has_internal_tag(self) -> None:
        """RPY000 carries the ``internal`` tag so it can be grouped
        separately in ``senpy rule list`` output."""
        tags = RULES_DATABASE["RPY000"].get("tags", [])
        assert "internal" in tags, (
            "RPY000 must carry the 'internal' tag so the rule list can "
            "render it in a separate Internal section, distinct from "
            "user-facing RPY001-RPY802."
        )


# =============================================================================
# End-to-end: synthesized RPY000 reaches the diagnostics list as ERROR
# =============================================================================


_MINIMAL_RPY = """label start:
    "Hello, world."
    return
"""


def _make_project(tmp_path: Path) -> Path:
    """Create a minimal Senpy project under ``tmp_path/game`` and return
    the project root (the dir SenpyAnalyzer.open() expects)."""
    project = tmp_path / "game"
    project.mkdir()
    (project / "script.rpy").write_text(_MINIMAL_RPY, encoding="utf-8")
    return project


class TestRPY000EndToEndSeverity:
    def test_internal_error_emits_rpy000_with_error_severity(self, tmp_path: Path) -> None:
        """When ``_analyze_file`` raises, the synthesized RPY000
        diagnostic must reach ``analyzer.diagnostics`` with
        ``severity == 'ERROR'`` — not downgraded to WARNING by the
        ``RULE_SEVERITY.get(code, 'WARNING')`` fallback.

        This is the end-to-end characterization that the BUG-1 audit
        flagged: even though ``Diagnostic(severity='ERROR')`` is set
        explicitly at construction, a future regression in
        ``_apply_severity`` could silently downgrade it. The test guards
        against that.
        """
        project = _make_project(tmp_path)
        a = SenpyAnalyzer(str(project))

        with patch.object(
            a._pipeline,
            "_analyze_file",
            side_effect=RuntimeError("forced internal error"),
        ):
            a.run(quiet=True)

        rpy000_diags = [d for d in a.diagnostics if d.code == "RPY000"]
        assert len(rpy000_diags) == 1, (
            f"Expected exactly one RPY000 diagnostic, got {len(rpy000_diags)}. "
            f"All diagnostics: {[(d.code, d.severity) for d in a.diagnostics]}"
        )
        diag = rpy000_diags[0]
        assert diag.severity == "ERROR", (
            f"RPY000 severity must be ERROR end-to-end, got {diag.severity!r}. "
            "This means _apply_severity downgraded it via the WARNING fallback."
        )
        assert "forced internal error" in diag.message

    def test_rpy000_severity_survives_strict_mode(self, tmp_path: Path) -> None:
        """In strict mode every diagnostic becomes ERROR, so RPY000 must
        still be ERROR (this is a sanity check — strict mode must not
        downgrade it to anything weaker)."""
        project = _make_project(tmp_path)
        a = SenpyAnalyzer(str(project))
        a.strict = True

        with patch.object(
            a._pipeline,
            "_analyze_file",
            side_effect=RuntimeError("forced internal error"),
        ):
            a.run(quiet=True)

        rpy000 = next(d for d in a.diagnostics if d.code == "RPY000")
        assert rpy000.severity == "ERROR"


# =============================================================================
# CLI: `senpy rule show RPY000` and `senpy rule list`
# =============================================================================


class TestRPY000Cli:
    def test_show_rpy000_prints_detail(self, capsys) -> None:
        """``senpy rule show RPY000`` must print a detail panel, not
        'Unknown rule code'."""
        rc = dispatch_rule(["show", "RPY000"])
        captured = capsys.readouterr()
        assert rc == 0
        assert "RPY000" in captured.out
        # Severity must appear in the detail output.
        assert "ERROR" in captured.out

    def test_show_rpy000_json(self, capsys) -> None:
        """``senpy rule show RPY000 --format json`` returns a JSON object
        with the expected fields."""
        rc = dispatch_rule(["show", "RPY000", "--format", "json"])
        captured = capsys.readouterr()
        assert rc == 0
        data = json.loads(captured.out)
        assert data["code"] == "RPY000"
        assert data["severity"] == "ERROR"
        assert "internal" in data["tags"]

    def test_list_includes_rpy000(self, capsys) -> None:
        """``senpy rule list`` text output must include RPY000."""
        dispatch_rule(["list"])
        captured = capsys.readouterr()
        assert "RPY000" in captured.out

    def test_list_has_internal_section(self, capsys) -> None:
        """``senpy rule list`` text output must render an explicit
        'Internal' section, separate from the main rules table, so that
        users understand RPY000 is a Senpy signal, not a user-triggered
        rule they can fix in their .rpy code."""
        dispatch_rule(["list"])
        captured = capsys.readouterr()
        # Section header — case-insensitive search keeps the test robust
        # to minor wording changes ("Internal" / "Internal rules").
        assert "internal" in captured.out.lower()

    def test_list_json_includes_rpy000(self, capsys) -> None:
        """JSON output of ``senpy rule list`` must include RPY000 as a
        structured entry, so external consumers (CI integrations, docs
        generators) see it consistently."""
        dispatch_rule(["list", "--format", "json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        codes = {entry["code"] for entry in data}
        assert "RPY000" in codes
        rpy000 = next(e for e in data if e["code"] == "RPY000")
        assert rpy000["severity"] == "ERROR"
        assert "internal" in rpy000["tags"]

    def test_list_filter_by_internal_tag_returns_only_rpy000(self, capsys) -> None:
        """``--tag internal`` filter must return RPY000 (and only
        internal rules)."""
        rc = dispatch_rule(["list", "--format", "json", "--tag", "internal"])
        captured = capsys.readouterr()
        assert rc == 0
        data = json.loads(captured.out)
        codes = {entry["code"] for entry in data}
        assert "RPY000" in codes
        for entry in data:
            assert "internal" in entry["tags"]
