"""Regression tests for ``generate_defaults_file`` error handling.

When ``--defaults`` is invoked on a project whose ``game/`` directory is
read-only (or the disk is full, or the path is too long, etc.),
``SenpyAnalyzer.generate_defaults_file`` previously called
``open(out_file, "w")`` without a try/except. The resulting ``OSError``
propagated up through ``handle_defaults`` and crashed the CLI with a
raw traceback — audit BUG-3.

The fix:
- Catch ``OSError`` (which includes ``PermissionError`` for read-only
  dirs, ``FileNotFoundError`` for missing parent dirs after a race, and
  ``OSError`` for disk full / path-too-long).
- Log a WARNING with the file path and the OS error (same pattern as
  ``_write_fixed_file``).
- Append the path to ``analyzer.failed_writes`` so
  ``_force_nonzero_if_failed_writes`` forces exit code 1 and
  ``_print_failed_writes_summary`` prints a clean summary — reuses the
  existing failed-writes infrastructure instead of inventing a parallel
  defaults-error path.
- Return ``("", 0)`` so the caller (``handle_defaults``) treats it as
  "nothing was generated" rather than crashing.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from senpy.core.analyzer import SenpyAnalyzer

# =============================================================================
# Fixtures
# =============================================================================


def _make_project_with_missing_defaults(tmp_path: Path) -> Path:
    """Create a minimal project where ``generate_defaults_file`` would
    actually want to write something.

    ``$ score = 0`` without a top-level ``default`` triggers RPY104 and
    populates ``analyzer.missing_defaults['score'] = '0'``. Without this,
    ``generate_defaults_file`` short-circuits at
    ``if not self.missing_defaults: return "", 0`` and the error path
    is never reached.
    """
    game = tmp_path / "game"
    game.mkdir(parents=True, exist_ok=True)
    (game / "script.rpy").write_text(
        'label start:\n    $ score = 0\n    $ player_name = "Eileen"\n    return\n',
        encoding="utf-8",
    )
    return game


def _make_readonly(path: Path) -> None:
    """Make ``path`` (a directory) read-only on POSIX.

    On POSIX, ``chmod 0o555`` on the directory prevents creating new
    files inside it — ``open(..., "w")`` raises ``PermissionError``.
    """
    path.chmod(0o555)


def _restore_writable(path: Path) -> None:
    """Restore write permission so the test fixture can be cleaned up."""
    try:
        path.chmod(0o755)
    except OSError:
        pass


# =============================================================================
# Unit tests on generate_defaults_file directly
# =============================================================================


class TestGenerateDefaultsFileErrorHandling:
    """``generate_defaults_file`` must not crash on OSError."""

    def test_readonly_dir_does_not_raise(self, tmp_path: Path) -> None:
        """A read-only ``game/`` directory must not crash generate_defaults_file."""
        game = _make_project_with_missing_defaults(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        # Sanity: missing_defaults must be populated, otherwise the error
        # path is unreachable.
        assert analyzer.missing_defaults, (
            "Test fixture must produce missing_defaults — otherwise "
            "generate_defaults_file short-circuits before the open() call."
        )

        _make_readonly(game)
        try:
            # Must NOT raise — must return ("", 0).
            out_file, gen_count = analyzer.generate_defaults_file()
            assert (
                out_file == ""
            ), f"out_file should be empty string on write failure, got: {out_file!r}"
            assert gen_count == 0, f"gen_count should be 0 on write failure, got: {gen_count}"
        finally:
            _restore_writable(game)

    def test_readonly_dir_records_failed_writes(self, tmp_path: Path) -> None:
        """A read-only ``game/`` must record the path in failed_writes.

        Reuses the existing ``failed_writes`` infrastructure so
        ``_force_nonzero_if_failed_writes`` forces exit 1 and
        ``_print_failed_writes_summary`` prints a clean summary —
        same pattern as ``--fix`` write failures.
        """
        game = _make_project_with_missing_defaults(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        assert analyzer.missing_defaults

        _make_readonly(game)
        try:
            analyzer.generate_defaults_file()
            # failed_writes must contain the senpy_defaults.rpy path.
            assert any("senpy_defaults.rpy" in p for p in analyzer.failed_writes), (
                f"failed_writes should contain senpy_defaults.rpy path, "
                f"got: {list(analyzer.failed_writes)}"
            )
        finally:
            _restore_writable(game)

    def test_readonly_dir_logs_warning(self, tmp_path: Path, caplog) -> None:
        """A WARNING must be logged with the file path — same pattern as
        ``_write_fixed_file``."""
        game = _make_project_with_missing_defaults(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        assert analyzer.missing_defaults

        _make_readonly(game)
        try:
            with caplog.at_level("WARNING"):
                analyzer.generate_defaults_file()
            matching = [
                r
                for r in caplog.records
                if r.levelname == "WARNING" and "senpy_defaults.rpy" in r.getMessage()
            ]
            assert matching, (
                f"No WARNING log mentioning senpy_defaults.rpy was emitted. "
                f"Got records: {[(r.levelname, r.getMessage()) for r in caplog.records]}"
            )
        finally:
            _restore_writable(game)

    def test_disk_full_does_not_raise(self, tmp_path: Path) -> None:
        """Simulate disk-full (OSError) via mock — must not raise."""
        _make_project_with_missing_defaults(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        assert analyzer.missing_defaults

        # Patch builtins.open to raise OSError (simulating ENOSPC).
        with patch("builtins.open", side_effect=OSError("[Errno 28] No space left on device")):
            # Must NOT raise.
            out_file, gen_count = analyzer.generate_defaults_file()
            assert out_file == ""
            assert gen_count == 0
        assert any(
            "senpy_defaults.rpy" in p for p in analyzer.failed_writes
        ), "failed_writes must contain senpy_defaults.rpy on disk-full"

    def test_clean_write_unaffected(self, tmp_path: Path) -> None:
        """A normal write (writable directory) must succeed and not record
        a failed_write. Guards against the fix being too broad."""
        _make_project_with_missing_defaults(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        assert analyzer.missing_defaults

        out_file, gen_count = analyzer.generate_defaults_file()

        assert gen_count == len(analyzer.missing_defaults), (
            f"gen_count should match missing_defaults size, got: "
            f"{gen_count} vs {len(analyzer.missing_defaults)}"
        )
        assert out_file.endswith("senpy_defaults.rpy")
        assert os.path.exists(out_file), "senpy_defaults.rpy must be written"
        assert (
            list(analyzer.failed_writes) == []
        ), f"failed_writes should be empty on a clean write, got: {list(analyzer.failed_writes)}"
        # Cleanup the generated file.
        try:
            os.unlink(out_file)
        except OSError:
            pass

    def test_empty_missing_defaults_short_circuits(self, tmp_path: Path) -> None:
        """If missing_defaults is empty, the function returns ("", 0)
        without attempting to open any file — this is the existing
        behavior, must be preserved."""
        # Project with NO missing_defaults — use 'default' declaration.
        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        (game / "script.rpy").write_text(
            "default score = 0\nlabel start:\n    $ score += 1\n    return\n",
            encoding="utf-8",
        )
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        assert not analyzer.missing_defaults, (
            "Test fixture must NOT produce missing_defaults — 'default score = 0' "
            "is a proper declaration."
        )

        out_file, gen_count = analyzer.generate_defaults_file()
        assert out_file == ""
        assert gen_count == 0
        assert list(analyzer.failed_writes) == []


# =============================================================================
# End-to-end: read-only game/ + --defaults CLI flag → exit code 1
# =============================================================================


class TestDefaultsCliExitCodeOnWriteFailure:
    """When ``--defaults`` is invoked on a project with a read-only
    ``game/`` directory, the CLI must exit non-zero (not crash with
    a traceback)."""

    def test_defaults_on_readonly_dir_exits_nonzero(self, tmp_path: Path) -> None:
        """``senpy --defaults`` on read-only game/ must exit 1, not crash."""
        from rich.console import Console

        from senpy.cli.commands import handle_defaults

        game = _make_project_with_missing_defaults(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        assert analyzer.missing_defaults

        _make_readonly(game)
        try:
            # Simulate `senpy --defaults` invocation.
            # handle_defaults checks args.defaults; we set it to True.
            class _Args:
                defaults = True

            handle_defaults(_Args(), analyzer, Console(quiet=True), is_tsundere=False)
            # handle_defaults returns 0 on "success" (even if write failed silently
            # before the fix). The contract change: when failed_writes is non-empty,
            # the caller (runner.main) must force exit 1 via
            # _force_nonzero_if_failed_writes. So handle_defaults itself can still
            # return 0, but analyzer.failed_writes must be populated so the
            # runner can detect it.
            assert analyzer.failed_writes, (
                "handle_defaults must populate analyzer.failed_writes when "
                "generate_defaults_file fails — otherwise runner.main cannot "
                "force a non-zero exit code."
            )
        finally:
            _restore_writable(game)
