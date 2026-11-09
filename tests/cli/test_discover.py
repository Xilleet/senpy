"""Tests for `senpy/cli/discover.py` — the file-discovery module
extracted from `senpy/cli/main.py` in 0.7.4.

These tests focus on the NEW `interactive` parameter that the
extraction introduced. The existing characterization tests for
`discover_files` (in `test_discover_files_characterization.py`)
verify that the move did not change behavior with `interactive=True`
(the default, used by `senpy [PATH]`).

The new behavior under test:
  - `interactive=False` (used by `senpy inspect`) suppresses the
    "Decompile them into a sandbox?" prompt even on a TTY, when
    neither `--decompile` nor `config['decompile']` is set.
  - `interactive=False` still honors explicit `--decompile` /
    `config['decompile']`.
  - `interactive=True` (default) preserves the prompt behavior.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pytest

from senpy.cli.discover import (
    _decompile_sandbox,
    discover_files,
)


def _make_args(**kwargs) -> argparse.Namespace:
    """Build minimal args Namespace for discover_files / _decompile_sandbox."""
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
# interactive=False — prompt suppressed even on a TTY
# =============================================================================


def test_decompile_sandbox_interactive_false_skips_prompt_on_tty(tmp_path: Path, monkeypatch):
    """With interactive=False, the decompile prompt is suppressed even
    when stdin.isatty() returns True. No input() call should happen.
    """
    # Force TTY True — interactive=True would prompt; interactive=False must not.
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    # Sentinel: if input() is called, raise to fail the test.
    def _no_input(*a, **kw):
        raise AssertionError("input() was called with interactive=False")

    monkeypatch.setattr("builtins.input", _no_input)

    # Create a fake .rpyc orphan so _decompile_sandbox has work to do.
    orphan = str(tmp_path / "orphan.rpyc")
    with open(orphan, "wb") as f:
        f.write(b"\x00\x01\x02 fake rpyc")

    args = _make_args(path=str(tmp_path), decompile=False)
    config = {}

    result = _decompile_sandbox(
        [orphan],
        args,
        config,
        str(tmp_path / "decomp_sandbox"),
        interactive=False,
    )

    # No decompilation happened (decompile=False, prompt suppressed)
    assert result == []


def test_decompile_sandbox_interactive_true_prompts_on_tty(tmp_path: Path, monkeypatch):
    """With interactive=True (default), on a TTY, the decompile prompt
    IS shown and user input 'y' triggers decompilation.
    """
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **kw: "y")

    # Mock unrpyc to make _decompile_sandbox succeed without real unrpyc.
    import senpy.cli.discover as discover_mod

    monkeypatch.setattr(
        discover_mod, "find_unrpyc_executable", lambda *a, **kw: ["python", "-m", "unrpyc"]
    )
    fake_decompiled = str(tmp_path / "decompiled.rpy")
    monkeypatch.setattr(
        discover_mod, "decompile_to_sandbox", lambda orphans, cmd, sandbox: [fake_decompiled]
    )

    orphan = str(tmp_path / "orphan.rpyc")
    with open(orphan, "wb") as f:
        f.write(b"\x00\x01\x02 fake rpyc")

    args = _make_args(path=str(tmp_path), decompile=False)
    config = {}

    result = _decompile_sandbox(
        [orphan],
        args,
        config,
        str(tmp_path / "decomp_sandbox"),
        interactive=True,
    )

    # User said 'y' → decompilation ran → fake .rpy returned
    assert result == [fake_decompiled]


def test_decompile_sandbox_interactive_false_honors_explicit_decompile(tmp_path: Path, monkeypatch):
    """With interactive=False, explicit args.decompile=True still works."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def _no_input(*a, **kw):
        raise AssertionError("input() should not be called when --decompile is set")

    monkeypatch.setattr("builtins.input", _no_input)

    import senpy.cli.discover as discover_mod

    monkeypatch.setattr(
        discover_mod, "find_unrpyc_executable", lambda *a, **kw: ["python", "-m", "unrpyc"]
    )
    fake_decompiled = str(tmp_path / "decompiled.rpy")
    monkeypatch.setattr(
        discover_mod, "decompile_to_sandbox", lambda orphans, cmd, sandbox: [fake_decompiled]
    )

    orphan = str(tmp_path / "orphan.rpyc")
    with open(orphan, "wb") as f:
        f.write(b"\x00\x01\x02 fake rpyc")

    args = _make_args(path=str(tmp_path), decompile=True)
    config = {}

    result = _decompile_sandbox(
        [orphan],
        args,
        config,
        str(tmp_path / "decomp_sandbox"),
        interactive=False,
    )

    assert result == [fake_decompiled]


def test_decompile_sandbox_interactive_false_ignores_config_decompile(tmp_path: Path, monkeypatch):
    """With interactive=False, config['decompile']=True is IGNORED.

    Only explicit --decompile flag triggers decompilation when interactive=False.
    This ensures deterministic behavior (e.g., for `senpy inspect`).

    Regression test: after user testing (2026-11-03), it was decided that
    `senpy inspect` must NOT honor config['decompile'] — only the explicit
    --decompile flag. This prevents unexpected decompilation when running
    inspect on a project with decompile=true in senpy.toml.
    """
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def _no_input(*a, **kw):
        raise AssertionError("input() should not be called when interactive=False")

    monkeypatch.setattr("builtins.input", _no_input)

    import senpy.cli.discover as discover_mod

    monkeypatch.setattr(
        discover_mod, "find_unrpyc_executable", lambda *a, **kw: ["python", "-m", "unrpyc"]
    )
    fake_decompiled = str(tmp_path / "decompiled.rpy")
    monkeypatch.setattr(
        discover_mod, "decompile_to_sandbox", lambda orphans, cmd, sandbox: [fake_decompiled]
    )

    orphan = str(tmp_path / "orphan.rpyc")
    with open(orphan, "wb") as f:
        f.write(b"\x00\x01\x02 fake rpyc")

    # config says decompile=true, but args.decompile=False (no explicit flag)
    args = _make_args(path=str(tmp_path), decompile=False)
    config = {"decompile": True}

    result = _decompile_sandbox(
        [orphan],
        args,
        config,
        str(tmp_path / "decomp_sandbox"),
        interactive=False,
    )

    # With interactive=False, config['decompile'] is IGNORED.
    # Only explicit --decompile flag would trigger decompilation.
    assert result == [], (
        "interactive=False must ignore config['decompile'] to ensure "
        "deterministic behavior (e.g., for `senpy inspect`)"
    )


def test_decompile_sandbox_interactive_false_honors_explicit_flag(tmp_path: Path, monkeypatch):
    """With interactive=False, explicit --decompile flag still works.

    Even if config['decompile']=False, the explicit --decompile flag
    triggers decompilation when interactive=False.
    """
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def _no_input(*a, **kw):
        raise AssertionError("input() should not be called when interactive=False")

    monkeypatch.setattr("builtins.input", _no_input)

    import senpy.cli.discover as discover_mod

    monkeypatch.setattr(
        discover_mod, "find_unrpyc_executable", lambda *a, **kw: ["python", "-m", "unrpyc"]
    )
    fake_decompiled = str(tmp_path / "decompiled.rpy")
    monkeypatch.setattr(
        discover_mod, "decompile_to_sandbox", lambda orphans, cmd, sandbox: [fake_decompiled]
    )

    orphan = str(tmp_path / "orphan.rpyc")
    with open(orphan, "wb") as f:
        f.write(b"\x00\x01\x02 fake rpyc")

    # config says decompile=False, but args.decompile=True (explicit flag)
    args = _make_args(path=str(tmp_path), decompile=True)
    config = {"decompile": False}

    result = _decompile_sandbox(
        [orphan],
        args,
        config,
        str(tmp_path / "decomp_sandbox"),
        interactive=False,
    )

    # Explicit --decompile flag overrides config, even with interactive=False
    assert result == [
        fake_decompiled
    ], "Explicit --decompile flag must work even when interactive=False"


def test_decompile_sandbox_interactive_false_non_tty_no_input(tmp_path: Path, monkeypatch):
    """With interactive=False on non-TTY, no input() call, no decompile
    unless --decompile is explicit."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    def _no_input(*a, **kw):
        raise AssertionError("input() should not be called when non-TTY")

    monkeypatch.setattr("builtins.input", _no_input)

    orphan = str(tmp_path / "orphan.rpyc")
    with open(orphan, "wb") as f:
        f.write(b"\x00\x01\x02 fake rpyc")

    args = _make_args(path=str(tmp_path), decompile=False)
    config = {}

    result = _decompile_sandbox(
        [orphan],
        args,
        config,
        str(tmp_path / "decomp_sandbox"),
        interactive=False,
    )

    assert result == []


# =============================================================================
# discover_files — interactive parameter propagates to _decompile_sandbox
# =============================================================================


def test_discover_files_interactive_false_no_prompt_on_tty(tmp_path: Path, monkeypatch):
    """discover_files(interactive=False) suppresses the prompt for the
    full pipeline (not just the inner _decompile_sandbox helper)."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def _no_input(*a, **kw):
        raise AssertionError("input() should not be called with interactive=False")

    monkeypatch.setattr("builtins.input", _no_input)

    (tmp_path / "orphan.rpyc").write_bytes(b"\x00\x01\x02 fake rpyc")

    args = _make_args(path=str(tmp_path), decompile=False)
    config = {}

    result = discover_files(args, config, str(tmp_path), interactive=False)

    assert result == []


def test_discover_files_interactive_true_default_backwards_compat(tmp_path: Path, monkeypatch):
    """discover_files() without interactive kwarg defaults to True
    (backwards compatibility with `senpy [PATH]` main CLI usage)."""
    # Force TTY True, mock input to return 'n' (decline prompt).
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **kw: "n")

    (tmp_path / "orphan.rpyc").write_bytes(b"\x00\x01\x02 fake rpyc")

    args = _make_args(path=str(tmp_path), decompile=False)
    config = {}

    # No explicit interactive kwarg → defaults to True → prompt IS shown.
    result = discover_files(args, config, str(tmp_path))

    # User declined → no decompile → no extras
    assert result == []


# =============================================================================
# discover.py module — importable, no circular dependency
# =============================================================================


def test_discover_module_importable():
    """senpy.cli.discover imports cleanly (no circular import with main.py)."""
    import senpy.cli.discover as mod

    assert hasattr(mod, "discover_files")
    assert hasattr(mod, "_find_rpy_files")
    assert hasattr(mod, "_find_orphaned_rpyc")
    assert hasattr(mod, "_decompile_sandbox")
