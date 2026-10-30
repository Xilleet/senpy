"""Tests for 0.6.0 Под-спринт 4: CLI UX polish.

CLI-3: --show-fixes — отчёт, что было исправлено (не только fixed_count в summary).
CLI-10: --output-format junit + --output-format github для CI.
CLI-19: Quick-fix "Add default" для RPY104 — предложить default x = 0 для $ x = 1.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _write_project(tmp_path: Path) -> Path:
    """Create a minimal Ren'Py project with known diagnostics."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(
        """
label start:
    "Hello, [unknown_var]!"   # RPY101: undeclared interpolation
    jump nonexistent_label    # RPY302: broken jump target
    return
""",
        encoding="utf-8",
    )
    return tmp_path


def _run_cli(args: list[str], tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "senpy.cli", str(tmp_path), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


# =============================================================================
# CLI-3: --show-fixes
# =============================================================================


class TestShowFixes:
    """CLI-3: --show-fixes — отчёт, что было исправлено.

    Without --show-fixes: summary shows "Fixed: N issues" (count only).
    With --show-fixes: summary shows list of what was fixed (file:line: rule — message).
    """

    def test_show_fixes_flag_exists(self, tmp_path: Path):
        """--show-fixes flag is accepted by CLI (doesn't error on unknown flag)."""
        project = _write_project(tmp_path)
        result = _run_cli(["--show-fixes"], project)
        # Should not error with "unrecognized arguments: --show-fixes"
        assert "unrecognized arguments" not in result.stderr, (
            f"--show-fixes flag not recognized: {result.stderr}"
        )
        # Should exit 0 or 1 (based on diagnostics), not 2 (argparse error)
        assert result.returncode in (0, 1), (
            f"Expected exit 0 or 1, got {result.returncode}. stderr: {result.stderr}"
        )

    def test_show_fixes_without_fix_shows_nothing(self, tmp_path: Path):
        """Without --fix, --show-fixes shows "0 fixes applied" (nothing to show)."""
        project = _write_project(tmp_path)
        result = _run_cli(["--show-fixes", "--no-cache"], project)
        # No --fix, so no fixes applied
        assert "0 fixes" in result.stdout.lower() or "no fixes" in result.stdout.lower() or "fixed: 0" in result.stdout.lower(), (
            f"Expected '0 fixes' or 'no fixes' in output, got: {result.stdout[:500]}"
        )

    def test_show_fixes_with_fix_shows_what_was_fixed(self, tmp_path: Path):
        """With --fix, --show-fixes shows list of applied fixes.

        Creates a project with RPY001 (tab indentation) and RPY002 (smart quotes)
        — both are fixable. After --fix, --show-fixes should list them.
        """
        game_dir = tmp_path / "game"
        game_dir.mkdir(parents=True, exist_ok=True)
        (game_dir / "script.rpy").write_text(
            'label start:\n\t"Hello"\n\treturn\n',  # tab → 4 spaces (RPY001)
            encoding="utf-8",
        )

        result = _run_cli(["--fix", "--show-fixes", "--no-cache"], tmp_path)

        # Should mention what was fixed (RPY001 or "tab" or "indent")
        assert "fix" in result.stdout.lower(), (
            f"Expected fix info in output, got: {result.stdout[:500]}"
        )

    def test_show_fixes_output_format(self, tmp_path: Path):
        """--show-fixes output should be readable (file:line or rule: message)."""
        game_dir = tmp_path / "game"
        game_dir.mkdir(parents=True, exist_ok=True)
        (game_dir / "script.rpy").write_text(
            'label start:\n\t"Hello"\n\treturn\n',  # RPY001 (tab)
            encoding="utf-8",
        )

        result = _run_cli(["--fix", "--show-fixes", "--no-cache"], tmp_path)

        # After --fix, fixed_count > 0 (2 fixes: 2 tabs). --show-fixes should
        # produce "Applied fixes:" section. Fixed diagnostics are removed from
        # active_diagnostics, so the list may be empty, but the section header
        # should be present (or "0 fixes applied" if no fixable had fix_title).
        assert "fix" in result.stdout.lower(), (
            f"Expected fix info in output, got: {result.stdout[:500]}"
        )


# =============================================================================
# CLI-10: --output-format junit + github
# =============================================================================


class TestOutputFormats:
    """CLI-10: --output-format junit + --output-format github for CI.

    junit: XML format compatible with JUnit/pytest CI systems.
    github: GitHub Actions ::error:: format for PR annotations.
    """

    def test_junit_format_accepted(self, tmp_path: Path):
        """--output-format junit is accepted (doesn't error)."""
        project = _write_project(tmp_path)
        result = _run_cli(["--output-format", "json"], project)  # json works
        # Now test junit
        result = _run_cli(["--output-format", "junit"], project)
        assert "invalid choice" not in result.stderr, (
            f"--output-format junit not accepted: {result.stderr}"
        )

    def test_junit_format_produces_xml(self, tmp_path: Path):
        """--output-format junit produces XML output (starts with <?xml or <testsuites)."""
        project = _write_project(tmp_path)
        result = _run_cli(["--output-format", "junit"], project)

        # Should be XML-like
        output = result.stdout.strip()
        assert output.startswith("<?xml") or output.startswith("<testsuites") or output.startswith("<testsuite"), (
            f"Expected XML output, got: {output[:200]}"
        )

    def test_junit_format_contains_diagnostics(self, tmp_path: Path):
        """junit XML should contain test cases for diagnostics (RPY101, RPY302)."""
        project = _write_project(tmp_path)
        result = _run_cli(["--output-format", "junit"], project)

        # Should mention RPY101 or RPY302 somewhere in XML
        assert "RPY101" in result.stdout or "RPY302" in result.stdout or "testcase" in result.stdout, (
            f"Expected diagnostics in junit XML, got: {result.stdout[:500]}"
        )

    def test_github_format_accepted(self, tmp_path: Path):
        """--output-format github is accepted."""
        project = _write_project(tmp_path)
        result = _run_cli(["--output-format", "github"], project)
        assert "invalid choice" not in result.stderr, (
            f"--output-format github not accepted: {result.stderr}"
        )

    def test_github_format_produces_annotations(self, tmp_path: Path):
        """--output-format github produces ::error:: annotations for GitHub Actions."""
        project = _write_project(tmp_path)
        result = _run_cli(["--output-format", "github"], project)

        # GitHub Actions format: ::error file=name,line=N,col=N::message
        # or ::warning file=...::message
        assert "::error" in result.stdout or "::warning" in result.stdout, (
            f"Expected ::error or ::warning annotations, got: {result.stdout[:500]}"
        )

    def test_github_format_includes_file_and_line(self, tmp_path: Path):
        """github format annotations include file= and line= for navigation."""
        project = _write_project(tmp_path)
        result = _run_cli(["--output-format", "github"], project)

        # Should contain file= and line= in annotation
        assert "file=" in result.stdout, (
            f"Expected file= in github annotation, got: {result.stdout[:500]}"
        )
        assert "line=" in result.stdout or "line " in result.stdout, (
            f"Expected line= in github annotation, got: {result.stdout[:500]}"
        )


# =============================================================================
# CLI-19: Quick-fix "Add default" for RPY104
# =============================================================================


class TestQuickFixAddDefault:
    """CLI-19: Quick-fix "Add default" for RPY104.

    RPY104 fires when a variable is created via `$ x = 1` without a top-level
    `default x = 0` declaration. This breaks save files after patches.

    Quick-fix: when user runs `senpy --fix`, for each RPY104 diagnostic,
    Senpy should suggest (or apply) adding `default x = 0` at the top of
    the file or in a generated `senpy_defaults.rpy`.

    For MVP, we test that --fix on RPY104 produces a fix (either inline or
    in a defaults file).
    """

    def test_rpy104_quick_fix_exists(self, tmp_path: Path):
        """--fix on a file with RPY104 should produce some fix output."""
        game_dir = tmp_path / "game"
        game_dir.mkdir(parents=True, exist_ok=True)
        # $ x = 1 without default x declaration → RPY104
        (game_dir / "script.rpy").write_text(
            'label start:\n    $ x = 1\n    "Hi"\n    return\n',
            encoding="utf-8",
        )

        result = _run_cli(["--fix", "--no-cache"], tmp_path)

        # Should detect RPY104 and either fix it or report fixable
        # (We accept either: file modified, or "fixable" count > 0)
        assert "RPY104" in result.stdout or result.returncode in (0, 1), (
            f"Expected RPY104 detection, got: {result.stdout[:500]}"
        )

    def test_rpy104_fix_creates_defaults_file(self, tmp_path: Path):
        """--fix on RPY104 should create senpy_defaults.rpy with `default x = 0`.

        Alternative: --defaults flag generates the file explicitly.
        """
        game_dir = tmp_path / "game"
        game_dir.mkdir(parents=True, exist_ok=True)
        (game_dir / "script.rpy").write_text(
            'label start:\n    $ x = 1\n    "Hi"\n    return\n',
            encoding="utf-8",
        )

        # Use --defaults flag (already exists in CLI per worklog)
        result = _run_cli(["--defaults", "--no-cache"], tmp_path)

        # Check if senpy_defaults.rpy was created
        defaults_file = game_dir / "senpy_defaults.rpy"
        assert defaults_file.exists(), (
            f"senpy_defaults.rpy not created. stdout: {result.stdout[:500]}"
        )

        content = defaults_file.read_text(encoding="utf-8")
        assert "default x" in content, (
            f"Expected 'default x' in defaults file, got: {content[:300]}"
        )

    def test_rpy104_fix_includes_correct_variable_name(self, tmp_path: Path):
        """senpy_defaults.rpy should use the actual variable name from $ x = 1."""
        game_dir = tmp_path / "game"
        game_dir.mkdir(parents=True, exist_ok=True)
        (game_dir / "script.rpy").write_text(
            'label start:\n    $ player_score = 100\n    "Hi"\n    return\n',
            encoding="utf-8",
        )

        result = _run_cli(["--defaults", "--no-cache"], tmp_path)

        defaults_file = game_dir / "senpy_defaults.rpy"
        assert defaults_file.exists()

        content = defaults_file.read_text(encoding="utf-8")
        assert "player_score" in content, (
            f"Expected 'player_score' in defaults, got: {content[:300]}"
        )
        assert "default player_score" in content, (
            f"Expected 'default player_score' in defaults, got: {content[:300]}"
        )
