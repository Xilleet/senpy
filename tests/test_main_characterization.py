"""Characterization tests for main() (ARCH-1 safety net).

main() is the CLI entry point with ~277 lines, high cyclomatic complexity.
After ARCH-1 it will:
  - Use Subcommand registry for dispatch (instead of `if sys.argv[1] == "format"`)
  - Extract early-exit handlers to _handle_early_exits()
  - Extract config+filter setup to _setup_rule_filters()
  - Keep builtins.open monkey-patch for --diff (TODO: move to analyzer in 0.6.6)

These tests run main() via subprocess to capture real CLI behavior.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_senpy(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """Run senpy CLI as subprocess, return (exit_code, stdout, stderr).

    Uses `python -m senpy.cli` instead of bare `senpy` command for
    cross-platform compatibility:
      - On Linux/macOS: `senpy` is found in PATH via shell lookup.
      - On Windows: `senpy.exe` may not be in PATH (especially in venvs
        without Scripts/ in PATH), and subprocess with shell=False doesn't
        search PATHEXT extensions. `python -m senpy.cli` works everywhere
        because it uses sys.executable (the Python running the tests).

    Also forces UTF-8 encoding for stdout/stderr decoding:
      - Senpy outputs Unicode symbols (✔ ✖ ⚠ ╬ Ò﹏Ó — tsundere banners,
        severity icons, etc.) which don't fit in Windows cp1251 locale.
      - Without encoding='utf-8', subprocess uses locale encoding (cp1251
        on Russian Windows) and crashes with UnicodeDecodeError, leaving
        result.stdout as None.
      - errors='replace' ensures we never crash on decode — any undecodable
        byte becomes '?' (acceptable for test assertions on text content).

    PYTHONPATH handling:
      - When cwd is set to tmp_path (e.g. for format tests), Python won't
        find the `senpy` package because cwd != repo root.
      - We add the repo root (parent of tests/) to PYTHONPATH so `senpy`
        is importable regardless of cwd.
      - This matters for users who don't `pip install -e .` (e.g. they
        test in fresh clones, or in configurations where senpy isn't
        installed in the venv).
    """
    cmd = [sys.executable, "-m", "senpy.cli"] + args
    env = dict(os.environ)
    # Force UTF-8 for child process stdout/stderr (avoids cp1251 crash on
    # Russian Windows when senpy prints Unicode symbols like ✔ ✖ ⚠).
    env["PYTHONIOENCODING"] = "utf-8"

    # Ensure senpy package is importable even when cwd != repo root.
    # Repo root = parent of tests/ directory (where this file lives).
    repo_root = str(Path(__file__).parent.parent)
    existing_pythonpath = env.get("PYTHONPATH", "")
    if existing_pythonpath:
        env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{existing_pythonpath}"
    else:
        env["PYTHONPATH"] = repo_root

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd) if cwd else None,
        env=env,
        timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


# =============================================================================
# 1. --version flag
# =============================================================================

def test_main_version_flag_prints_version_exits_0():
    """`senpy --version` prints 'senpy X.Y.Z' and exits 0."""
    code, out, _ = _run_senpy(["--version"])
    assert code == 0
    assert "senpy" in out.lower()
    # Should contain version number like 0.6.3
    assert "0.6" in out


# =============================================================================
# 2. --help flag
# =============================================================================

def test_main_help_flag_prints_help_exits_0():
    """`senpy --help` prints help and exits 0."""
    code, out, _ = _run_senpy(["--help"])
    assert code == 0
    assert "senpy" in out.lower()
    # Key flags should be in help
    assert "--fix" in out
    assert "--output-format" in out
    assert "--lsp" in out


# =============================================================================
# 3. format subcommand dispatch
# =============================================================================

def test_main_format_subcommand_dispatches(tmp_path: Path):
    """`senpy format X.rpy` dispatches to format subcommand."""
    f = tmp_path / "test.rpy"
    f.write_text("label start:\n\t$x=1\n", encoding="utf-8")  # needs formatting

    code, out, err = _run_senpy(["format", str(f)], cwd=tmp_path)

    assert code == 0, (
        f"Expected exit 0, got {code}.\nstdout: {out!r}\nstderr: {err!r}"
    )
    # File should be reformatted (tabs removed)
    content = f.read_text(encoding="utf-8")
    assert "\t" not in content, f"File not reformatted. stdout: {out!r}\nstderr: {err!r}"
    assert "Formatted" in out or "formatted" in out.lower(), (
        f"Expected 'Formatted' in output.\nstdout: {out!r}\nstderr: {err!r}"
    )


def test_main_format_subcommand_check_mode(tmp_path: Path):
    """`senpy format --check X.rpy` exits 1 if changes needed."""
    f = tmp_path / "test.rpy"
    f.write_text("label start:\n\t$x=1\n", encoding="utf-8")

    code, out, err = _run_senpy(["format", "--check", str(f)], cwd=tmp_path)

    assert code == 1, f"Expected exit 1, got {code}.\nstdout: {out!r}\nstderr: {err!r}"
    assert "Would reformat" in out, (
        f"Expected 'Would reformat' in output.\nstdout: {out!r}\nstderr: {err!r}"
    )
    # File NOT modified
    assert "\t" in f.read_text(encoding="utf-8")


# =============================================================================
# 4. Basic analysis on test_game
# =============================================================================

def test_main_analyzes_test_game_finds_diagnostics():
    """`senpy test_game --no-cache --exit-zero` finds diagnostics (12+ errors)."""
    # Find test_game directory (relative to repo root)
    repo_root = Path(__file__).parent.parent
    test_game = repo_root / "test_game"

    code, out, _ = _run_senpy([
        str(test_game),
        "--no-cache",
        "--exit-zero",
    ])

    assert code == 0  # --exit-zero forces 0
    # Should find diagnostics (test_game has known issues)
    assert "RPY" in out or "error" in out.lower() or "warning" in out.lower()


def test_main_json_output_format():
    """`senpy test_game --output-format json` produces valid JSON.

    NB: --exit-zero doesn't work for JSON output (sys.exit before exit_zero check).
    We accept exit code 1 (diagnostics found) but validate JSON output structure.
    """
    repo_root = Path(__file__).parent.parent
    test_game = repo_root / "test_game"

    code, out, _ = _run_senpy([
        str(test_game),
        "--no-cache",
        "--output-format", "json",
    ])

    # Exit 1 is OK — JSON output path calls sys.exit before --exit-zero check
    assert code in (0, 1)
    # Output should be valid JSON
    import json
    data = json.loads(out)
    assert isinstance(data, dict)
    assert "diagnostics" in data


# =============================================================================
# 5. --rules flag
# =============================================================================

def test_main_rules_flag_lists_rules():
    """`senpy --rules` lists available rules and exits 0."""
    code, out, _ = _run_senpy(["--rules"])
    assert code == 0
    # Should mention rule codes
    assert "RPY" in out


# =============================================================================
# 6. Invalid arguments
# =============================================================================

def test_main_invalid_output_format_exits_nonzero():
    """`senpy --output-format invalid` exits with error."""
    code, _, err = _run_senpy(["--output-format", "invalid"])
    assert code != 0
    # Error message about invalid choice
    assert "invalid" in err.lower() or "choice" in err.lower()


# =============================================================================
# 7. --check and --diff dry-run modes (monkey-patch open preserved)
# =============================================================================

def test_main_check_mode_dry_run(tmp_path: Path):
    """`senpy --check test_game --no-cache` is dry-run, doesn't modify files."""
    # Create a copy of test_game (only .rpy files, skip .senpy_cache dir)
    repo_root = Path(__file__).parent.parent
    test_game_orig = repo_root / "test_game"
    test_game_copy = tmp_path / "test_game"
    test_game_copy.mkdir()
    for f in test_game_orig.iterdir():
        if f.is_file() and f.suffix == ".rpy":
            (test_game_copy / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

    original_content = (test_game_copy / "script.rpy").read_text(encoding="utf-8")

    code, out, _ = _run_senpy([
        str(test_game_copy),
        "--no-cache",
        "--check",
    ])

    # --check exits 1 if fixable issues found, 0 if none
    # test_game has fixable issues (RPY001 tabs, RPY002 smart quotes)
    assert code in (0, 1)
    # File NOT modified
    assert (test_game_copy / "script.rpy").read_text(encoding="utf-8") == original_content


def test_main_diff_mode_dry_run(tmp_path: Path):
    """`senpy --diff test_game --no-cache` is dry-run, doesn't modify files."""
    repo_root = Path(__file__).parent.parent
    test_game_orig = repo_root / "test_game"
    test_game_copy = tmp_path / "test_game"
    test_game_copy.mkdir()
    for f in test_game_orig.iterdir():
        if f.is_file() and f.suffix == ".rpy":
            (test_game_copy / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

    original_content = (test_game_copy / "script.rpy").read_text(encoding="utf-8")

    code, out, _ = _run_senpy([
        str(test_game_copy),
        "--no-cache",
        "--diff",
    ])

    # --diff exits 1 if changes would be applied, 0 if none
    assert code in (0, 1)
    # File NOT modified (monkey-patch open should prevent writes)
    assert (test_game_copy / "script.rpy").read_text(encoding="utf-8") == original_content


# =============================================================================
# 8. Backward compat — main importable
# =============================================================================

def test_main_importable_from_cli_main():
    """main must remain importable from senpy.cli.main after ARCH-1."""
    from senpy.cli.main import main as f1
    assert callable(f1)
