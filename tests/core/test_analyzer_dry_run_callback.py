"""TDD tests for `SenpyAnalyzer.run(dry_run_callback=...)`.

The ``--diff`` mode previously worked by monkey-patching ``builtins.open``
globally (``senpy/cli/runner.py:_setup_diff_interception``) to intercept
what ``--fix`` would write. The monkey-patch is a hack — it affects EVERY
``open()`` call in the process during the analysis window, not just the
analyzer's writes.

Replaces the monkey-patch with a ``dry_run_callback`` parameter on
``SenpyAnalyzer.run()`` → ``AnalysisPipeline._write_fixed_file``. When
the callback is set, ``_write_fixed_file`` calls it with
``(file_path, lines)`` instead of calling ``open()``. The file on disk
is NOT modified.

``runner.py`` to use the new callback
API and removes ``_setup_diff_interception`` entirely.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer


def _make_fixable_project(tmp_path: Path) -> Path:
    """Create a minimal project with a file that --fix would modify.

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
    return tmp_path


class TestDryRunCallback:
    """SenpyAnalyzer.run(dry_run_callback=cb) must capture writes, not write to disk."""

    def test_run_accepts_dry_run_callback_parameter(self, tmp_path: Path):
        """run() must accept dry_run_callback as a keyword argument."""
        _make_fixable_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), fix=True, no_cache=True)

        captured: dict[str, str] = {}

        def cb(file_path: str, lines: list[str]) -> None:
            captured[file_path] = "".join(lines)

        # Must not raise TypeError
        analyzer.run(quiet=True, dry_run_callback=cb)

    def test_dry_run_callback_called_with_file_path_and_lines(self, tmp_path: Path):
        """When fix=True and the file has fixable issues, the callback must
        be called with (file_path, lines) for each file that would be written.
        """
        project = _make_fixable_project(tmp_path)
        script = project / "game" / "script.rpy"

        analyzer = SenpyAnalyzer(str(project), fix=True, no_cache=True)

        captured: dict[str, str] = {}

        def cb(file_path: str, lines: list[str]) -> None:
            captured[file_path] = "".join(lines)

        analyzer.run(quiet=True, dry_run_callback=cb)

        assert len(captured) >= 1, (
            "dry_run_callback was not called — analyzer either wrote to disk "
            "directly (bypassing the callback) or no fixable issues were found"
        )
        # The script file must be among the captured paths
        script_captured = any(p.endswith("script.rpy") or p.endswith(str(script)) for p in captured)
        assert script_captured, f"script.rpy not in captured files: {list(captured.keys())}"

    def test_dry_run_does_not_modify_file_on_disk(self, tmp_path: Path):
        """The file on disk must NOT be modified when dry_run_callback is set.

        This is the whole point of the dry-run: capture what --fix would
        write WITHOUT actually writing it.
        """
        project = _make_fixable_project(tmp_path)
        script = project / "game" / "script.rpy"
        original_content = script.read_text(encoding="utf-8")

        analyzer = SenpyAnalyzer(str(project), fix=True, no_cache=True)

        captured: dict[str, str] = {}

        def cb(file_path: str, lines: list[str]) -> None:
            captured[file_path] = "".join(lines)

        analyzer.run(quiet=True, dry_run_callback=cb)

        disk_content = script.read_text(encoding="utf-8")
        assert disk_content == original_content, (
            "File on disk was modified despite dry_run_callback being set — "
            "the analyzer did not respect the callback and wrote via open()"
        )

    def test_dry_run_callback_receives_formatted_content(self, tmp_path: Path):
        """The captured content must be the FORMATTED version (tabs → spaces),
        not the original — proving the formatter ran and the callback
        received the result.
        """
        project = _make_fixable_project(tmp_path)

        analyzer = SenpyAnalyzer(str(project), fix=True, no_cache=True)

        captured: dict[str, str] = {}

        def cb(file_path: str, lines: list[str]) -> None:
            captured[file_path] = "".join(lines)

        analyzer.run(quiet=True, dry_run_callback=cb)

        assert len(captured) >= 1
        captured_content = next(iter(captured.values()))
        # Tabs must be gone — the formatter converts to 4 spaces
        assert "\t" not in captured_content, (
            "Captured content still has tabs — formatter did not run, "
            "or the callback received raw lines instead of formatted ones"
        )

    def test_dry_run_callback_none_writes_normally(self, tmp_path: Path):
        """When dry_run_callback is None (default), the analyzer must write
        to disk normally — back-compat for all callers that don't use the
        new parameter.
        """
        project = _make_fixable_project(tmp_path)
        script = project / "game" / "script.rpy"
        original_content = script.read_text(encoding="utf-8")

        analyzer = SenpyAnalyzer(str(project), fix=True, no_cache=True)

        # No dry_run_callback — default None → normal write
        analyzer.run(quiet=True)

        disk_content = script.read_text(encoding="utf-8")
        assert disk_content != original_content, (
            "File was NOT modified with fix=True and no dry_run_callback — "
            "the analyzer should have written the fixed version to disk"
        )
        assert "\t" not in disk_content, "Tabs remain after --fix — formatter did not run"

    def test_dry_run_callback_not_called_without_fix(self, tmp_path: Path):
        """When fix=False, the callback must NOT be called — there's nothing
        to write. The analyzer should accept the parameter without error
        but never invoke the callback.
        """
        project = _make_fixable_project(tmp_path)

        analyzer = SenpyAnalyzer(str(project), fix=False, no_cache=True)

        captured: dict[str, str] = {}

        def cb(file_path: str, lines: list[str]) -> None:
            captured[file_path] = "".join(lines)

        analyzer.run(quiet=True, dry_run_callback=cb)

        assert len(captured) == 0, (
            f"dry_run_callback was called {len(captured)} time(s) with fix=False — "
            "the analyzer should not attempt to write files when fix is disabled"
        )
