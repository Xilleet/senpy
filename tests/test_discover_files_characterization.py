"""Characterization tests for discover_files.

discover_files does 5 things:
  1. Setup sandbox dirs (.senpy_cache/decompiled, .senpy_cache/rpa_extracted)
  2. Find existing .rpy files (relative paths + basenames for dedup)
  3. Find .rpa archives + extract scripts from them
  4. Sync .rpyc orphan cache (use cached .rpy if fresh, else queue for decompile)
  5. Decompile orphaned .rpyc into sandbox (if --decompile or interactive yes)

After: discover_files will call 3 helpers (_find_rpy_files,
_find_orphaned_rpyc, _decompile_sandbox). Behavior must be identical.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from senpy.cli.main import discover_files


def _make_args(**kwargs) -> argparse.Namespace:
    """Create args Namespace for discover_files."""
    defaults = {
        "path": ".",
        "decompile": False,
        "graph": False,
        "graph_file": None,
        "stats": False,
        "unrpyc": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# =============================================================================
# 1. Empty directory — no .rpy, no .rpyc, no .rpa
# =============================================================================

def test_discover_files_empty_directory(tmp_path: Path):
    """discover_files on empty dir returns [] and creates sandbox dirs."""
    args = _make_args(path=str(tmp_path))
    config = {}

    result = discover_files(args, config, str(tmp_path))

    assert result == []
    # Sandbox dirs created
    assert (tmp_path / ".senpy_cache" / "decompiled").is_dir()
    assert (tmp_path / ".senpy_cache" / "rpa_extracted").is_dir()


# =============================================================================
# 2. .rpy files only (no orphans, no RPA)
# =============================================================================

def test_discover_files_with_rpy_only(tmp_path: Path):
    """discover_files on dir with .rpy files only returns [] (no extras)."""
    (tmp_path / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")
    (tmp_path / "other.rpy").write_text("label other:\n    return\n", encoding="utf-8")

    args = _make_args(path=str(tmp_path))
    config = {}

    result = discover_files(args, config, str(tmp_path))

    # No extras — .rpy files are picked up by analyzer directly, not via discover_files
    assert result == []


# =============================================================================
# 3. .rpyc orphan (no matching .rpy) — without --decompile
# =============================================================================

def test_discover_files_rpyc_orphan_no_decompile(tmp_path: Path, monkeypatch):
    """Orphan .rpyc without --decompile + non-interactive → no extras."""
    # Create orphan .rpyc (no matching .rpy)
    (tmp_path / "orphan.rpyc").write_bytes(b"\x00\x01\x02 fake rpyc")

    args = _make_args(path=str(tmp_path), decompile=False)
    config = {}

    # Force non-interactive (no TTY)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    result = discover_files(args, config, str(tmp_path))

    # No decompilation happened, no extras
    assert result == []


def test_discover_files_rpyc_orphan_with_decompile_flag(tmp_path: Path, monkeypatch):
    """Orphan .rpyc with --decompile=True attempts decompilation."""
    (tmp_path / "orphan.rpyc").write_bytes(b"\x00\x01\x02 fake rpyc")

    args = _make_args(path=str(tmp_path), decompile=True)
    config = {"decompile": True}

    # Mock unrpyc functions in cli.main module (where they're imported by name)
    import sys
    cli_main_mod = sys.modules["senpy.cli.main"]
    monkeypatch.setattr(
        cli_main_mod,
        "decompile_to_sandbox",
        lambda orphans, cmd, sandbox: [],
    )
    monkeypatch.setattr(
        cli_main_mod,
        "find_unrpyc_executable",
        lambda *a, **kw: ["python", "-m", "unrpyc"],
    )
    # Force non-interactive
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    result = discover_files(args, config, str(tmp_path))

    # Decompilation attempted but no .rpy produced (fake bytes)
    assert result == []


# =============================================================================
# 4. .rpyc with matching .rpy — not an orphan, no decompile needed
# =============================================================================

def test_discover_files_rpyc_with_matching_rpy(tmp_path: Path):
    """If orphan.rpyc has matching orphan.rpy — not an orphan, skipped."""
    (tmp_path / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")
    (tmp_path / "script.rpyc").write_bytes(b"\x00\x01\x02 fake rpyc")

    args = _make_args(path=str(tmp_path))
    config = {}

    result = discover_files(args, config, str(tmp_path))

    # script.rpyc is not an orphan (has matching .rpy) → no decompile
    assert result == []


# =============================================================================
# 5. RPA archive extraction
# =============================================================================

def test_discover_files_rpa_extraction(tmp_path: Path, monkeypatch):
    """If .rpa archive exists — extract scripts, add to extras."""
    (tmp_path / "game.rpa").write_bytes(b"RPA-3.0 00000000\nfake rpa content")

    # Mock extract_scripts_from_rpa — return fake .rpy
    fake_rpy_path = os.path.join(
        str(tmp_path), ".senpy_cache", "rpa_extracted", "extracted.rpy"
    )
    os.makedirs(os.path.dirname(fake_rpy_path), exist_ok=True)
    Path(fake_rpy_path).write_text("label extracted:\n    return\n", encoding="utf-8")

    # Patch in cli.main module (where the function is imported by name)
    import sys
    cli_main_mod = sys.modules["senpy.cli.main"]
    monkeypatch.setattr(
        cli_main_mod,
        "extract_scripts_from_rpa",
        lambda rpa, sandbox: [fake_rpy_path],
    )

    args = _make_args(path=str(tmp_path))
    config = {}

    result = discover_files(args, config, str(tmp_path))

    # Extracted .rpy should be in extras
    assert any("extracted.rpy" in p for p in result), f"Expected extracted.rpy in {result}"


# =============================================================================
# 6. RPA extraction respects IGNORED_DIRS
# =============================================================================

def test_discover_files_ignored_dirs_skipped(tmp_path: Path):
    """Files in IGNORED_DIRS (like .senpy_cache) should not be picked up."""
    # Create .rpy inside .senpy_cache (should be ignored)
    cache_dir = tmp_path / ".senpy_cache"
    cache_dir.mkdir()
    (cache_dir / "cached.rpy").write_text("label cached:\n    return\n", encoding="utf-8")

    args = _make_args(path=str(tmp_path))
    config = {}

    result = discover_files(args, config, str(tmp_path))

    # .senpy_cache contents not picked up
    assert result == []


# =============================================================================
# 7. Backward compat — discover_files importable from cli.main
# =============================================================================

def test_discover_files_importable_from_cli_main():
    """discover_files must remain importable from senpy.cli.main after ARCH-5."""
    from senpy.cli.main import discover_files as f1
    assert callable(f1)
    # After ARCH-5: helpers _find_rpy_files, _find_orphaned_rpyc, _decompile_sandbox
    # may or may not be exposed — only discover_files is part of public API.
