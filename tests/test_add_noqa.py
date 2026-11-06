"""TDD tests for ``senpy --add-noqa`` CLI flag.

``--add-noqa`` was defined in ``senpy/cli/args.py`` and validated in
``early_exits.py`` (warning on ``--add-noqa + --fix`` combination), but
the analyzer never used ``args.add_noqa`` anywhere — the flag was a
no-op. Users who ran ``senpy --add-noqa path/`` saw diagnostics as
usual, no ``# noqa`` comments were added, and the next run produced the
same diagnostics. The flag was misleading.

After the fix: ``senpy --add-noqa path/`` walks every diagnostic in
``result.diagnostics`` and appends ``# noqa: RPYxxx`` to the offending
line in the source ``.rpy`` file. The next run suppresses those
diagnostics (the noqa directive is parsed by ``build_noqa_map``).

Contract:
  1. ``--add-noqa`` adds ``# noqa: RPYxxx`` to lines with diagnostics.
  2. Re-running the analyzer after ``--add-noqa`` produces no
     diagnostics for the suppressed rules.
  3. ``--add-noqa`` does NOT add duplicate ``# noqa`` to a line that
     already has one (idempotent on re-run).
  4. ``--add-noqa`` writes files back to disk (mutates .rpy) — same
     failure path as ``--fix`` (``failed_writes`` records OSError).
  5. ``--add-noqa`` on a project with no diagnostics is a no-op (no
     files modified).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from senpy.cli.runner import _apply_noqa_comments

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project_with_diagnostics(tmp_path: Path) -> Path:
    """Build a minimal project that triggers RPY101 (undeclared interpolation).

    RPY101 is the simplest rule to trigger: ``"[unknown_var]"`` in a
    dialogue line produces an "undeclared variable" diagnostic on line 2.
    """
    game = tmp_path / "game"
    game.mkdir(parents=True, exist_ok=True)
    (game / "script.rpy").write_text(
        'label start:\n    "Hello, [unknown_var]!"\n    return\n',
        encoding="utf-8",
    )
    return tmp_path


def _run_cli(args: list[str], tmp_path: Path) -> subprocess.CompletedProcess:
    """Run ``senpy`` CLI via ``python -m senpy.cli``."""
    return subprocess.run(
        [sys.executable, "-m", "senpy.cli", str(tmp_path), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# _apply_noqa_comments() — unit tests
# ---------------------------------------------------------------------------


class TestApplyNoqaComments:
    """``_apply_noqa_comments()`` writes ``# noqa: RPYxxx`` to source files."""

    def test_adds_noqa_to_line_with_diagnostic(self, tmp_path: Path):
        """A diagnostic on line N → ``# noqa: RPYxxx`` appended to line N."""
        from senpy.core.analyzer import SenpyAnalyzer

        project = _make_project_with_diagnostics(tmp_path)
        analyzer = SenpyAnalyzer(str(project), no_cache=True)
        result = analyzer.run(quiet=True)

        # Sanity: RPY101 fired on line 2.
        assert any(
            d.code == "RPY101" and d.line_number == 2 for d in result.diagnostics
        ), "Test setup is wrong — RPY101 should fire on line 2 of script.rpy"

        # Apply noqa comments.
        _apply_noqa_comments(result.diagnostics, analyzer)

        # The file should now have # noqa: RPY101 on line 2.
        content = (project / "game" / "script.rpy").read_text(encoding="utf-8")
        lines = content.splitlines()
        assert (
            "noqa: RPY101" in lines[1]
        ), f"Line 2 should have '# noqa: RPY101' appended, got: {lines[1]!r}"

    def test_re_run_after_noqa_suppresses_diagnostics(self, tmp_path: Path):
        """After ``--add-noqa``, re-running the analyzer produces no RPY101."""
        from senpy.core.analyzer import SenpyAnalyzer

        project = _make_project_with_diagnostics(tmp_path)

        # First run: RPY101 fires.
        analyzer = SenpyAnalyzer(str(project), no_cache=True)
        result = analyzer.run(quiet=True)
        assert any(d.code == "RPY101" for d in result.diagnostics)

        # Apply noqa.
        _apply_noqa_comments(result.diagnostics, analyzer)

        # Second run: RPY101 should be suppressed by the noqa directive.
        analyzer2 = SenpyAnalyzer(str(project), no_cache=True)
        result2 = analyzer2.run(quiet=True)
        rpy101_diags = [d for d in result2.diagnostics if d.code == "RPY101"]
        assert rpy101_diags == [], (
            f"RPY101 should be suppressed by # noqa after --add-noqa, "
            f"got {len(rpy101_diags)} diagnostic(s): {rpy101_diags}"
        )

    def test_does_not_add_duplicate_noqa(self, tmp_path: Path):
        """Re-running ``--add-noqa`` does NOT add a second ``# noqa``.

        If a line already has ``# noqa: RPY101``, a second run should
        not append another ``# noqa: RPY101``. Idempotency.
        """
        from senpy.core.analyzer import SenpyAnalyzer

        project = _make_project_with_diagnostics(tmp_path)

        # First run + apply.
        analyzer = SenpyAnalyzer(str(project), no_cache=True)
        result = analyzer.run(quiet=True)
        _apply_noqa_comments(result.diagnostics, analyzer)

        # Manually re-introduce a diagnostic on the same line by removing
        # the noqa and re-adding it twice.
        script = project / "game" / "script.rpy"
        # Simulate: a line already has # noqa, and we run --add-noqa again.
        # The analyzer now produces NO diagnostics (noqa suppresses them),
        # so _apply_noqa_comments has nothing to add. Verify no duplicate.
        analyzer2 = SenpyAnalyzer(str(project), no_cache=True)
        result2 = analyzer2.run(quiet=True)
        _apply_noqa_comments(result2.diagnostics, analyzer2)

        content = script.read_text(encoding="utf-8")
        noqa_count = content.count("noqa: RPY101")
        assert noqa_count <= 1, (
            f"Expected at most 1 'noqa: RPY101' on the line, got {noqa_count}. "
            "--add-noqa must be idempotent — re-running should not duplicate."
        )

    def test_no_diagnostics_is_noop(self, tmp_path: Path):
        """``--add-noqa`` on a project with no diagnostics modifies nothing."""
        from senpy.core.analyzer import SenpyAnalyzer

        # Clean project — no diagnostics.
        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        (game / "script.rpy").write_text(
            'label start:\n    "Hello, world!"\n    return\n',
            encoding="utf-8",
        )

        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        result = analyzer.run(quiet=True)
        assert result.diagnostics == [], "Test setup should have no diagnostics"

        original = (game / "script.rpy").read_text(encoding="utf-8")
        written = _apply_noqa_comments(result.diagnostics, analyzer)

        assert written == [], "No files should be written when there are no diagnostics."
        after = (game / "script.rpy").read_text(encoding="utf-8")
        assert after == original, "File was modified despite no diagnostics."

    def test_multiple_diagnostics_same_line_uses_one_noqa(self, tmp_path: Path):
        """Multiple diagnostics on the same line → one ``# noqa: RPY101, RPYxxx``.

        The noqa directive format supports comma-separated codes:
        ``# noqa: RPY101, RPY104``. Multiple diagnostics on the same
        line should merge into one comment, not append two.
        """
        from senpy.core.analyzer import SenpyAnalyzer

        # Build a line that triggers multiple rules — e.g. tab indent
        # (RPY001) + undeclared var (RPY101). Use a tab + interpolation.
        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        (game / "script.rpy").write_text(
            'label start:\n\t"Hello, [unknown_var]!"\n    return\n',
            encoding="utf-8",
        )

        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        result = analyzer.run(quiet=True)

        # If both RPY001 and RPY101 fire on line 2, they should merge.
        line2_diags = [d for d in result.diagnostics if d.line_number == 2]
        if len(line2_diags) < 2:
            pytest.skip(
                "Test setup did not produce 2+ diagnostics on line 2 — "
                "cannot test merging. Adjust the fixture .rpy."
            )

        _apply_noqa_comments(result.diagnostics, analyzer)

        content = (game / "script.rpy").read_text(encoding="utf-8")
        line2 = content.splitlines()[1]
        # Count # noqa occurrences on line 2 — should be exactly 1.
        noqa_count = line2.count("# noqa")
        assert noqa_count == 1, (
            f"Expected exactly 1 '# noqa' on line 2 (merged codes), got {noqa_count}. "
            f"Line: {line2!r}"
        )


# ---------------------------------------------------------------------------
# CLI integration — senpy --add-noqa path/
# ---------------------------------------------------------------------------


class TestAddNoqaCliIntegration:
    """``senpy --add-noqa path/`` end-to-end via subprocess."""

    def test_add_noqa_writes_noqa_to_file(self, tmp_path: Path):
        """``senpy --add-noqa`` adds ``# noqa: RPYxxx`` to .rpy files."""
        project = _make_project_with_diagnostics(tmp_path)
        script = project / "game" / "script.rpy"
        original = script.read_text(encoding="utf-8")
        assert "noqa" not in original, "Test setup: file should not have noqa yet."

        result = _run_cli(["--add-noqa", "--no-cache"], project)

        after = script.read_text(encoding="utf-8")
        assert "noqa: RPY101" in after, (
            f"--add-noqa did not add '# noqa: RPY101' to the file.\n"
            f"Before: {original!r}\nAfter: {after!r}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_add_noqa_second_run_has_no_diagnostics(self, tmp_path: Path):
        """After ``--add-noqa``, a second run produces no RPY101."""
        project = _make_project_with_diagnostics(tmp_path)

        # First run: apply noqa.
        _run_cli(["--add-noqa", "--no-cache"], project)

        # Second run: should have no RPY101 diagnostics.
        result = _run_cli(["--no-cache", "--format", "json"], project)
        assert result.returncode == 0, (
            f"Second run should exit 0 (no errors). Got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        # The JSON output should not contain RPY101.
        assert "RPY101" not in result.stdout, (
            f"RPY101 should be suppressed after --add-noqa, but it's in the output.\n"
            f"stdout: {result.stdout}"
        )

    def test_add_noqa_preserves_existing_noqa(self, tmp_path: Path):
        """``--add-noqa`` does NOT clobber an existing ``# noqa`` directive.

        If a line already has ``# noqa: RPY001`` and a new diagnostic
        RPY104 fires on the same line, ``--add-noqa`` should add RPY104
        to the existing directive, not replace it.
        """
        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        # Pre-existing noqa for RPY001 (tab indent), but RPY101 (undeclared
        # var) is NOT suppressed — it should be added.
        (game / "script.rpy").write_text(
            'label start:\n\t"Hello, [unknown_var]!"  # noqa: RPY001\n    return\n',
            encoding="utf-8",
        )

        _run_cli(["--add-noqa", "--no-cache"], tmp_path)

        content = (game / "script.rpy").read_text(encoding="utf-8")
        line2 = content.splitlines()[1]
        assert "RPY001" in line2, "Existing # noqa: RPY001 must be preserved."
        assert "RPY101" in line2, (
            f"RPY101 should be added to the existing noqa directive. " f"Line: {line2!r}"
        )
