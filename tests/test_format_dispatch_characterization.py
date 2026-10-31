"""Characterization tests for `senpy format` subcommand.

Before extracting `_dispatch_format` into `cli/format_dispatch.py`,
we capture its current behavior so refactoring doesn't break it.

These tests exercise _dispatch_format directly via subprocess-like
calls (it takes argv list, returns exit code, prints to stdout).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from senpy.cli.main import _dispatch_format


def _run_format(argv: list[str], capsys) -> tuple[int, str, str]:
    """Run _dispatch_format and capture stdout/stderr."""
    exit_code = _dispatch_format(argv)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


# =============================================================================
# 1. Help message
# =============================================================================

def test_format_help_exits_zero(capsys):
    """`senpy format --help` should print help and exit 0."""
    with pytest.raises(SystemExit) as exc_info:
        _dispatch_format(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "format" in captured.out.lower()
    assert "--check" in captured.out
    assert "--diff" in captured.out
    assert "--stdin-filename" in captured.out


# =============================================================================
# 2. Stdin mode (--stdin-filename)
# =============================================================================

def test_format_stdin_mode_formats_code(capsys, monkeypatch, tmp_path):
    """`senpy format --stdin-filename X.rpy` reads stdin, writes to stdout."""
    # Simulate stdin with poorly formatted code
    bad_code = "label start:\n\t$x=1\n"  # tab + no space around =
    monkeypatch.setattr("sys.stdin", type("FakeStdin", (), {"read": lambda self: bad_code})())

    exit_code, out, _ = _run_format(["--stdin-filename", "test.rpy"], capsys)

    assert exit_code == 0
    # Output should be formatted code (4 spaces indent, spaces around =)
    assert "    $ x = 1" in out or "    $x = 1" in out  # formatter may vary


def test_format_stdin_mode_idempotent(capsys, monkeypatch):
    """`senpy format --stdin-filename` on already-formatted code = same code."""
    good_code = "label start:\n    $ x = 1\n"
    monkeypatch.setattr("sys.stdin", type("FakeStdin", (), {"read": lambda self: good_code})())

    exit_code, out, _ = _run_format(["--stdin-filename", "test.rpy"], capsys)

    assert exit_code == 0
    assert out == good_code


# =============================================================================
# 3. File mode — basic formatting
# =============================================================================

def test_format_file_writes_formatted(tmp_path, capsys):
    """`senpy format X.rpy` writes formatted version to file."""
    f = tmp_path / "test.rpy"
    f.write_text("label start:\n\t$x=1\n", encoding="utf-8")  # tab + no spaces

    exit_code, out, _ = _run_format([str(f)], capsys)

    assert exit_code == 0
    # File should be reformatted
    content = f.read_text(encoding="utf-8")
    assert "\t" not in content  # tabs removed
    assert "Formatted:" in out


def test_format_file_already_formatted(tmp_path, capsys):
    """`senpy format X.rpy` on already-formatted file = no changes."""
    f = tmp_path / "test.rpy"
    f.write_text("label start:\n    $ x = 1\n", encoding="utf-8")

    exit_code, out, _ = _run_format([str(f)], capsys)

    assert exit_code == 0
    content = f.read_text(encoding="utf-8")
    # Content unchanged
    assert content == "label start:\n    $ x = 1\n"
    # Output should mention "already formatted"
    assert "already formatted" in out.lower()


def test_format_directory_recursively(tmp_path, capsys):
    """`senpy format DIR/` formats all .rpy files in directory."""
    sub = tmp_path / "sub"
    sub.mkdir()
    f1 = tmp_path / "a.rpy"
    f2 = sub / "b.rpy"
    f1.write_text("label a:\n\t$x=1\n", encoding="utf-8")
    f2.write_text("label b:\n\t$x=2\n", encoding="utf-8")

    exit_code, out, _ = _run_format([str(tmp_path)], capsys)

    assert exit_code == 0
    # Both files formatted
    assert "\t" not in f1.read_text(encoding="utf-8")
    assert "\t" not in f2.read_text(encoding="utf-8")


# =============================================================================
# 4. --check mode (CI-friendly, no writes)
# =============================================================================

def test_format_check_exits_1_if_changes_needed(tmp_path, capsys):
    """`senpy format --check X.rpy` exits 1 if file needs formatting."""
    f = tmp_path / "test.rpy"
    f.write_text("label start:\n\t$x=1\n", encoding="utf-8")  # needs formatting

    exit_code, out, _ = _run_format(["--check", str(f)], capsys)

    assert exit_code == 1
    assert "Would reformat" in out
    # File NOT modified
    assert "\t" in f.read_text(encoding="utf-8")


def test_format_check_exits_0_if_already_formatted(tmp_path, capsys):
    """`senpy format --check X.rpy` exits 0 if file is already formatted."""
    f = tmp_path / "test.rpy"
    f.write_text("label start:\n    $ x = 1\n", encoding="utf-8")

    exit_code, out, _ = _run_format(["--check", str(f)], capsys)

    assert exit_code == 0
    assert "already formatted" in out.lower()


# =============================================================================
# 5. --diff mode (show diff, no writes)
# =============================================================================

def test_format_diff_shows_diff_no_writes(tmp_path, capsys):
    """`senpy format --diff X.rpy` prints unified diff, doesn't write."""
    f = tmp_path / "test.rpy"
    f.write_text("label start:\n\t$x=1\n", encoding="utf-8")

    exit_code, out, _ = _run_format(["--diff", str(f)], capsys)

    assert exit_code == 1  # changes needed
    assert "---" in out or "+++" in out  # diff markers
    # File NOT modified
    assert "\t" in f.read_text(encoding="utf-8")


def test_format_diff_already_formatted_exits_0(tmp_path, capsys):
    """`senpy format --diff X.rpy` on already-formatted = exit 0, no diff."""
    f = tmp_path / "test.rpy"
    f.write_text("label start:\n    $ x = 1\n", encoding="utf-8")

    exit_code, out, _ = _run_format(["--diff", str(f)], capsys)

    assert exit_code == 0


# =============================================================================
# 6. Edge cases
# =============================================================================

def test_format_nonexistent_file_skipped(tmp_path, capsys):
    """`senpy format nonexistent.rpy` skips with warning."""
    exit_code, out, _ = _run_format([str(tmp_path / "nope.rpy")], capsys)

    assert exit_code == 0
    assert "Skipping" in out or "No .rpy files" in out


def test_format_empty_directory(tmp_path, capsys):
    """`senpy format EMPTY_DIR/` exits 0 with "No .rpy files"."""
    exit_code, out, _ = _run_format([str(tmp_path)], capsys)

    assert exit_code == 0
    assert "No .rpy files" in out


def test_format_multiple_files(tmp_path, capsys):
    """`senpy format A.rpy B.rpy` formats both."""
    f1 = tmp_path / "a.rpy"
    f2 = tmp_path / "b.rpy"
    f1.write_text("label a:\n\t$x=1\n", encoding="utf-8")
    f2.write_text("label b:\n\t$x=2\n", encoding="utf-8")

    exit_code, out, _ = _run_format([str(f1), str(f2)], capsys)

    assert exit_code == 0
    assert "\t" not in f1.read_text(encoding="utf-8")
    assert "\t" not in f2.read_text(encoding="utf-8")
    assert "2 file(s) formatted" in out


# =============================================================================
# 7. Backward compat — import path
# =============================================================================

def test_dispatch_format_importable_from_cli_main():
    """_dispatch_format must remain importable from senpy.cli.main after ARCH-4.

    The extraction to cli/format_dispatch.py should re-export it for
    backward compatibility — existing callers and tests use this path.
    """
    import senpy.cli.format_dispatch as fd_mod
    from senpy.cli.main import _dispatch_format as f1
    assert hasattr(fd_mod, "dispatch_format")
    # After ARCH-4: _dispatch_format in main.py should be re-export from format_dispatch
    # (we'll verify exact equality after extraction)
    assert callable(f1)
