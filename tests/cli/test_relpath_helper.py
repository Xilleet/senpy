"""Cover the ``_relpath_to_cwd`` defensive helper in ``senpy/cli/commands.py``.

On Linux/macOS ``os.path.relpath`` never raises ``ValueError``, so the
``except`` branch (which exists for the Windows cross-mount scenario
where ``C:\\projects`` and ``D:\\repo`` are on different drives) is
covered by mocking ``os.path.relpath`` to raise.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from senpy.cli.commands import _relpath_to_cwd


def test_same_dir_returns_dot() -> None:
    """When path == cwd, relpath returns ``.``."""
    assert _relpath_to_cwd(os.getcwd()) == "."


def test_subdir_returns_relative(tmp_path: Path) -> None:
    """A path on the same mount as cwd yields a relative path."""
    result = _relpath_to_cwd(str(tmp_path))
    assert not os.path.isabs(result), f"expected relative path, got absolute: {result!r}"


def test_cross_mount_falls_back_to_absolute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate the Windows cross-mount ValueError.

    ``os.path.relpath`` on Windows raises ``ValueError`` when the two
    paths are on different drives (e.g. ``C:\\games\\myvn`` project vs
    ``D:\\projects`` cwd). The helper must catch this and fall back to
    the raw absolute path so the user-facing message still prints
    something useful instead of crashing the CLI.
    """

    def _raise_value_error(path: str, start: str) -> str:
        raise ValueError("path is on mount 'C:', start on mount 'D:'")

    monkeypatch.setattr(os.path, "relpath", _raise_value_error)
    raw = "/some/absolute/path.yml"
    assert _relpath_to_cwd(raw) == raw
