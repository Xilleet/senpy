"""TDD tests for ``--fix`` failure reporting.

When ``SenpyAnalyzer.run()`` is called with ``fix=True`` and the underlying
``open(file_path, "w")`` raises ``OSError`` (read-only file, full disk,
permission denied, ...), the analyzer used to swallow the exception
silently (``except OSError: pass``). The user saw a successful run and
believed the fixes were applied, while the file on disk was unchanged.

After the fix:
- ``AnalysisResult.failed_writes`` lists every file path that could not
  be written.
- A warning is logged for each failure (with the path and the OS error).
- ``runner.main()`` exits non-zero when any write failed.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.models import AnalysisResult


def _make_fixable_project(tmp_path: Path) -> Path:
    """Create a minimal project with a file that ``--fix`` would modify.

    Uses tabs for indentation + no spaces around ``=`` — both are
    fixable by the Senpy formatter (FMT-INDENT, FMT-OP-SPACING).
    """
    game = tmp_path / "game"
    game.mkdir(parents=True, exist_ok=True)
    script = game / "script.rpy"
    script.write_text(
        "label start:\n\t$x=1\n\treturn\n",
        encoding="utf-8",
    )
    return script


def _make_readonly(path: Path) -> None:
    """Make ``path`` read-only on the current platform.

    On POSIX, ``chmod 0o444`` is enough to make ``open(..., "w")`` raise
    ``PermissionError`` (a subclass of ``OSError``). On Windows the
    semantics differ (``chmod`` does not always prevent writes for the
    owner), but CI runs on Linux/macOS for this project — and the same
    code path triggers the same ``OSError`` regardless of platform.
    """
    path.chmod(0o444)


def _restore_writable(path: Path) -> None:
    """Restore write permission so the test fixture can be cleaned up."""
    try:
        path.chmod(0o644)
    except OSError:
        pass


class TestFailedWritesField:
    """``AnalysisResult`` must expose ``failed_writes`` to callers."""

    def test_failed_writes_default_empty(self):
        """``AnalysisResult`` must accept ``failed_writes`` and default to []."""
        result = AnalysisResult(
            diagnostics=[],
            file_count=0,
            total_lines=0,
            fixed_count=0,
            fixable_count=0,
        )
        assert hasattr(result, "failed_writes"), (
            "AnalysisResult has no `failed_writes` field — runner.main() cannot "
            "report fix failures to the user"
        )
        assert list(result.failed_writes) == []

    def test_failed_writes_independent_per_instance(self):
        """Each AnalysisResult must have its own ``failed_writes`` list."""
        a = AnalysisResult(diagnostics=[], file_count=0, total_lines=0)
        b = AnalysisResult(diagnostics=[], file_count=0, total_lines=0)
        a.failed_writes.append("foo.rpy")
        assert b.failed_writes == [], (
            "AnalysisResult.failed_writes is shared across instances — "
            "default_factory=list is missing"
        )


class TestFixRecordsFailedWrites:
    """When ``open(..., "w")`` raises OSError, the failure must be recorded."""

    def test_fix_records_failed_writes_when_oserror(self, tmp_path: Path):
        """Read-only file + ``fix=True`` → ``result.failed_writes`` contains the path."""
        script = _make_fixable_project(tmp_path)
        _make_readonly(script)

        try:
            analyzer = SenpyAnalyzer(str(tmp_path), fix=True, no_cache=True)
            result = analyzer.run(quiet=True)

            assert any(
                os.path.normcase(p) == os.path.normcase(str(script)) or p.endswith("script.rpy")
                for p in result.failed_writes
            ), f"failed_writes should contain script.rpy, got: {list(result.failed_writes)}"
        finally:
            _restore_writable(script)

    def test_fix_logs_warning_when_oserror(self, tmp_path: Path, caplog):
        """A warning must be logged with the file path when the write fails."""
        script = _make_fixable_project(tmp_path)
        _make_readonly(script)

        try:
            analyzer = SenpyAnalyzer(str(tmp_path), fix=True, no_cache=True)
            with caplog.at_level("WARNING"):
                analyzer.run(quiet=True)

            # At least one WARNING record must mention the script path.
            script_name = script.name
            matching = [
                r
                for r in caplog.records
                if r.levelname == "WARNING" and script_name in r.getMessage()
            ]
            assert matching, (
                f"No WARNING log mentioning {script_name} was emitted. "
                f"Got records: {[(r.levelname, r.getMessage()) for r in caplog.records]}"
            )
        finally:
            _restore_writable(script)

    def test_fix_without_oserror_does_not_record_failed_writes(self, tmp_path: Path):
        """Normal ``--fix`` (writable file) → ``failed_writes`` stays empty."""
        _make_fixable_project(tmp_path)

        analyzer = SenpyAnalyzer(str(tmp_path), fix=True, no_cache=True)
        result = analyzer.run(quiet=True)

        assert (
            list(result.failed_writes) == []
        ), f"failed_writes should be empty on a successful fix, got: {list(result.failed_writes)}"

    def test_fix_does_not_raise_on_oserror(self, tmp_path: Path):
        """``--fix`` on a read-only file must NOT raise — it must record and continue.

        Other files in the same project must still be analysed; the read-only
        file must not abort the whole run.
        """
        script = _make_fixable_project(tmp_path)
        _make_readonly(script)

        try:
            analyzer = SenpyAnalyzer(str(tmp_path), fix=True, no_cache=True)
            # Must not raise
            result = analyzer.run(quiet=True)
            assert result is not None
        finally:
            _restore_writable(script)
