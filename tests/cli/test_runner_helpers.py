"""Coverage push: senpy/cli/runner.py helper functions.

The existing ``tests/cli/test_main_characterization.py`` exercises
``runner.main()`` end-to-end via subprocess, but several helper
functions called from ``main()`` have display / exit-code branches not
exercised by the subprocess path. This file targets those helpers
directly: ``_apply_noqa_comments``, ``_force_nonzero_if_failed_writes``,
``_print_failed_writes_summary``, ``_handle_check_mode``,
``_handle_diff_mode``, ``_print_scan_banner``, ``_setup_rule_filters``,
``_ReplaceConsole`` / ``_NullRedirect``, ``_make_file_console``, and
``_handle_output_format``.

Each test asserts captured console output, exit code via ``SystemExit``,
or mutated analyzer state (``failed_writes``).
"""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console

from senpy.cli import runner
from senpy.cli.runner import (
    _apply_noqa_comments,
    _exit_with_output_redirect,
    _force_nonzero_if_failed_writes,
    _handle_check_mode,
    _handle_diff_mode,
    _handle_output_format,
    _make_file_console,
    _null_redirect,
    _NullRedirect,
    _print_failed_writes_summary,
    _print_scan_banner,
    _replace_console,
    _ReplaceConsole,
    _setup_rule_filters,
)
from senpy.core.models import AnalysisResult, Diagnostic


def _capturing_console() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, force_terminal=False, no_color=True, width=200), buf


def _diag(
    file_path: str,
    line_number: int,
    code: str = "RPY001",
    severity: str = "WARNING",
) -> Diagnostic:
    return Diagnostic(
        file_path=file_path,
        line_number=line_number,
        line_content="example",
        code=code,
        message="msg",
        severity=severity,
    )


def _args(**kw) -> SimpleNamespace:
    defaults = {
        "path": ".",
        "ignore": None,
        "extend_ignore": None,
        "select": None,
        "extend_select": None,
        "max_errors": None,
        "output_format": "text",
        "output_file": None,
        "check": False,
        "diff": False,
        "fix": False,
        "add_noqa": False,
        "tsundere": False,
        "errors_only": False,
        "info": False,
        "graph": False,
        "graph_file": None,
        "stats": False,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


class TestForceNonzeroIfFailedWrites:
    def test_no_failed_writes_keeps_exit_code(self) -> None:
        assert _force_nonzero_if_failed_writes(0, False) == 0
        assert _force_nonzero_if_failed_writes(1, False) == 1

    def test_failed_writes_promotes_zero_to_one(self) -> None:
        assert _force_nonzero_if_failed_writes(0, True) == 1

    def test_failed_writes_keeps_nonzero(self) -> None:
        assert _force_nonzero_if_failed_writes(1, True) == 1
        assert _force_nonzero_if_failed_writes(2, True) == 2


class TestPrintFailedWritesSummary:
    def test_no_failed_writes_returns_false(self) -> None:
        console, _ = _capturing_console()
        result = AnalysisResult(diagnostics=[], file_count=0, total_lines=0)
        assert _print_failed_writes_summary(result, console, False) is False

    def test_failed_writes_verbose_prints_summary(self) -> None:
        console, buf = _capturing_console()
        result = AnalysisResult(
            diagnostics=[], file_count=0, total_lines=0, failed_writes=["a.rpy", "b.rpy"]
        )
        rc = _print_failed_writes_summary(result, console, False)
        assert rc is True
        out = buf.getvalue()
        assert "Failed to write fixes to 2 file(s)" in out
        assert "a.rpy" in out
        assert "b.rpy" in out

    def test_failed_writes_quiet_mode_no_summary(self) -> None:
        console, buf = _capturing_console()
        result = AnalysisResult(
            diagnostics=[], file_count=0, total_lines=0, failed_writes=["a.rpy"]
        )
        rc = _print_failed_writes_summary(result, console, True)
        assert rc is True
        # In quiet mode the rich summary is suppressed — the warning still
        # goes to console via logger (not console.print), so the buffer
        # should be empty.
        assert "Failed to write fixes" not in buf.getvalue()


class TestHandleCheckMode:
    def test_returns_none_when_flag_not_set(self) -> None:
        console, _ = _capturing_console()
        result = AnalysisResult(diagnostics=[], file_count=0, total_lines=0)
        assert _handle_check_mode(_args(), result, console) is None

    def test_fixable_issues_exit_one(self, tmp_path: Path) -> None:
        console, buf = _capturing_console()
        result = AnalysisResult(diagnostics=[], file_count=2, total_lines=10, fixable_count=3)
        with pytest.raises(SystemExit) as exc:
            _handle_check_mode(_args(check=True), result, console)
        assert exc.value.code == 1
        assert "Would fix 3 issue(s)" in buf.getvalue()
        assert "Run with --fix" in buf.getvalue()

    def test_no_fixable_issues_exit_zero(self) -> None:
        console, buf = _capturing_console()
        result = AnalysisResult(diagnostics=[], file_count=1, total_lines=5, fixable_count=0)
        with pytest.raises(SystemExit) as exc:
            _handle_check_mode(_args(check=True), result, console)
        assert exc.value.code == 0
        assert "No fixable issues found" in buf.getvalue()


class TestHandleDiffMode:
    def test_returns_none_when_flag_not_set(self) -> None:
        console, _ = _capturing_console()
        result = AnalysisResult(diagnostics=[], file_count=0, total_lines=0)
        assert _handle_diff_mode(_args(), {}, result, console) is None

    def test_empty_diff_collector_exit_zero(self) -> None:
        console, buf = _capturing_console()
        result = AnalysisResult(diagnostics=[], file_count=0, total_lines=0)
        with pytest.raises(SystemExit) as exc:
            _handle_diff_mode(_args(diff=True), {}, result, console)
        assert exc.value.code == 0
        assert "No changes would be applied by --fix" in buf.getvalue()

    def test_diff_with_changes_exit_one(self, tmp_path: Path) -> None:
        console, _ = _capturing_console()
        # Create a file with original content, then provide new content
        # in diff_collector that differs — exercises the unified_diff path.
        f = tmp_path / "script.rpy"
        f.write_text('label start:\n    "Hello"\n', encoding="utf-8")
        result = AnalysisResult(diagnostics=[], file_count=1, total_lines=2, fixable_count=1)
        diff_collector = {str(f): 'label start:\n    "Hi"\n'}
        with pytest.raises(SystemExit) as exc:
            _handle_diff_mode(_args(diff=True), diff_collector, result, console)
        assert exc.value.code == 1

    def test_diff_with_unchanged_content_exit_zero(self, tmp_path: Path) -> None:
        console, _ = _capturing_console()
        f = tmp_path / "script.rpy"
        original = 'label start:\n    "Hello"\n'
        f.write_text(original, encoding="utf-8")
        result = AnalysisResult(diagnostics=[], file_count=1, total_lines=2)
        # diff_collector has same content as on-disk — no actual changes.
        diff_collector = {str(f): original}
        with pytest.raises(SystemExit) as exc:
            _handle_diff_mode(_args(diff=True), diff_collector, result, console)
        assert exc.value.code == 0


class TestApplyNoqaComments:
    def test_no_diagnostics_returns_empty(self) -> None:
        # SimpleNamespace with the attributes _apply_noqa_comments reads.
        analyzer = SimpleNamespace(failed_writes=[], _pipeline=SimpleNamespace())
        assert _apply_noqa_comments([], analyzer) == []

    def test_appends_noqa_to_clean_line(self, tmp_path: Path) -> None:
        f = tmp_path / "script.rpy"
        f.write_text('label start:\n    "Hello"\n', encoding="utf-8")
        analyzer = SimpleNamespace(
            failed_writes=[],
            _pipeline=SimpleNamespace(
                _write_fixed_file=lambda path, lines: Path(path).write_text(
                    "".join(lines), encoding="utf-8"
                )
            ),
        )
        diags = [_diag(str(f), line_number=2, code="RPY001")]
        written = _apply_noqa_comments(diags, analyzer)
        assert str(f) in written
        content = f.read_text(encoding="utf-8")
        assert "# noqa: RPY001" in content

    def test_merges_into_existing_noqa(self, tmp_path: Path) -> None:
        f = tmp_path / "script.rpy"
        f.write_text('    "Hello"  # noqa: RPY101\n', encoding="utf-8")
        analyzer = SimpleNamespace(
            failed_writes=[],
            _pipeline=SimpleNamespace(
                _write_fixed_file=lambda path, lines: Path(path).write_text(
                    "".join(lines), encoding="utf-8"
                )
            ),
        )
        # Add RPY104 — should merge with existing RPY101 into "RPY101, RPY104".
        diags = [_diag(str(f), line_number=1, code="RPY104")]
        written = _apply_noqa_comments(diags, analyzer)
        assert str(f) in written
        content = f.read_text(encoding="utf-8")
        assert "RPY101" in content
        assert "RPY104" in content

    def test_skips_bare_noqa(self, tmp_path: Path) -> None:
        f = tmp_path / "script.rpy"
        f.write_text('    "Hello"  # noqa\n', encoding="utf-8")
        analyzer = SimpleNamespace(
            failed_writes=[],
            _pipeline=SimpleNamespace(
                _write_fixed_file=lambda path, lines: Path(path).write_text(
                    "".join(lines), encoding="utf-8"
                )
            ),
        )
        # Bare # noqa suppresses everything — nothing to add.
        diags = [_diag(str(f), line_number=1, code="RPY001")]
        written = _apply_noqa_comments(diags, analyzer)
        assert str(f) not in written  # No write happened.
        # File unchanged.
        assert f.read_text(encoding="utf-8") == '    "Hello"  # noqa\n'

    def test_skips_already_present_code(self, tmp_path: Path) -> None:
        f = tmp_path / "script.rpy"
        f.write_text('    "Hello"  # noqa: RPY001\n', encoding="utf-8")
        analyzer = SimpleNamespace(
            failed_writes=[],
            _pipeline=SimpleNamespace(_write_fixed_file=lambda path, lines: None),
        )
        # RPY001 is already in the directive — should be a no-op.
        diags = [_diag(str(f), line_number=1, code="RPY001")]
        written = _apply_noqa_comments(diags, analyzer)
        assert str(f) not in written

    def test_skips_diag_without_code_or_path(self, tmp_path: Path) -> None:
        analyzer = SimpleNamespace(
            failed_writes=[],
            _pipeline=SimpleNamespace(_write_fixed_file=lambda path, lines: None),
        )
        # Missing code, missing path, line_number < 1 — all skipped.
        diags = [
            _diag(str(tmp_path / "x.rpy"), line_number=1, code=""),
            _diag("", line_number=1, code="RPY001"),
            _diag(str(tmp_path / "x.rpy"), line_number=0, code="RPY001"),
        ]
        assert _apply_noqa_comments(diags, analyzer) == []

    def test_unreadable_file_records_failed_write(self, tmp_path: Path) -> None:
        # Reference a file that does not exist — OSError on read.
        analyzer = SimpleNamespace(
            failed_writes=[],
            _pipeline=SimpleNamespace(_write_fixed_file=lambda path, lines: None),
        )
        diags = [_diag(str(tmp_path / "missing.rpy"), line_number=1, code="RPY001")]
        written = _apply_noqa_comments(diags, analyzer)
        assert written == []
        assert str(tmp_path / "missing.rpy") in analyzer.failed_writes

    def test_line_out_of_range_skipped(self, tmp_path: Path) -> None:
        f = tmp_path / "script.rpy"
        f.write_text("label start:\n    return\n", encoding="utf-8")
        analyzer = SimpleNamespace(
            failed_writes=[],
            _pipeline=SimpleNamespace(_write_fixed_file=lambda path, lines: None),
        )
        # line_number=99 — way beyond the 2-line file.
        diags = [_diag(str(f), line_number=99, code="RPY001")]
        written = _apply_noqa_comments(diags, analyzer)
        assert written == []


class TestPrintScanBanner:
    def test_non_tsundere_banner(self, tmp_path: Path) -> None:
        console, buf = _capturing_console()
        _print_scan_banner(_args(path=str(tmp_path)), console, is_tsundere=False)
        out = buf.getvalue()
        assert "Scanning directory" in out
        assert str(tmp_path) in out

    def test_tsundere_banner(self, tmp_path: Path) -> None:
        console, buf = _capturing_console()
        _print_scan_banner(_args(path=str(tmp_path)), console, is_tsundere=True)
        out = buf.getvalue()
        # The tsundere intro contains the path and a Japanese-style emoticon.
        assert "(¬_¬ )" in out or str(tmp_path) in out

    def test_recent_traceback_banner(self, tmp_path: Path) -> None:
        # Drop a traceback.txt that parse_traceback_file recognises.
        (tmp_path / "traceback.txt").write_text(
            "While running game script:\n"
            'File "game/script.rpy", line 5, in script\n'
            "    call bad_label\n"
            "Exception: NameError: name 'bad_label' is not defined\n",
            encoding="utf-8",
        )
        console, buf = _capturing_console()
        _print_scan_banner(_args(path=str(tmp_path)), console, is_tsundere=False)
        out = buf.getvalue()
        assert "Recent crash log detected" in out


class TestSetupRuleFilters:
    def test_picks_config_select_when_cli_select_none(self) -> None:
        args = _args(select=None, extend_select=None, ignore=None, extend_ignore=None)
        config = {
            "ignore": ["RPY999"],
            "extend_ignore": ["rpy100"],
            "select": ["RPY001", "RPY002"],
            "extend_select": ["rpy003"],
            "max_errors": 100,
        }
        ignored, max_err = _setup_rule_filters(args, config)
        # ignored_codes are normalized to upper; select/extend_select are
        # copied verbatim from config (callers normalize later).
        assert "RPY999" in ignored
        assert "RPY100" in ignored
        assert args.select == ["RPY001", "RPY002"]
        assert args.extend_select == ["rpy003"]
        assert max_err == 100

    def test_cli_overrides_config_max_errors(self) -> None:
        args = _args(max_errors=42)
        config = {"max_errors": 100, "ignore": [], "extend_ignore": []}
        _, max_err = _setup_rule_filters(args, config)
        assert max_err == 42


class TestReplaceConsole:
    def test_replace_and_restore(self, tmp_path: Path) -> None:
        original = runner.console
        f = tmp_path / "out.txt"
        f.write_text("", encoding="utf-8")
        # ruff: noqa: SIM115 — Console takes a file object directly;
        # closing is handled by _ReplaceConsole.__exit__ via .file.close().
        file_console = Console(file=open(f, "w", encoding="utf-8"), force_terminal=False)
        with _replace_console(file_console):
            assert runner.console is file_console
        assert runner.console is original

    def test_exit_with_output_redirect(self) -> None:
        # _exit_with_output_redirect just calls sys.exit — verify it raises.
        with pytest.raises(SystemExit) as exc:
            _exit_with_output_redirect(None, 42)
        assert exc.value.code == 42


class TestNullRedirect:
    def test_null_redirect_noop(self) -> None:
        ctx = _null_redirect()
        assert ctx.__enter__() is ctx
        # __exit__ returns False (does not suppress exceptions).
        assert ctx.__exit__(None, None, None) is False


class TestMakeFileConsole:
    def test_creates_console_with_file(self, tmp_path: Path) -> None:
        out = tmp_path / "subdir" / "report.txt"
        # subdir doesn't exist yet — _make_file_console creates it.
        console_obj = _make_file_console(_args(output_file=str(out)))
        assert console_obj.file is not None
        assert out.parent.exists()
        console_obj.file.close()

    def test_force_terminal_false(self, tmp_path: Path) -> None:
        out = tmp_path / "out.txt"
        console_obj = _make_file_console(_args(output_file=str(out)))
        # Rich stores the constructor's force_terminal under _force_terminal
        # (the public attribute is _file / no_color). Check the private slot
        # — it determines whether ANSI codes are emitted to the file.
        assert console_obj._force_terminal is False or console_obj.no_color is True
        console_obj.file.close()


class TestHandleOutputFormat:
    def test_text_format_returns_without_exit(self) -> None:
        console, _ = _capturing_console()
        result = AnalysisResult(diagnostics=[], file_count=0, total_lines=0)
        # Text format falls through (returns None implicitly) without exit.
        _handle_output_format(
            _args(output_format="text"),
            [],
            result,
            0.0,
            console,
            ignored_codes=set(),
            had_failed_writes=False,
        )

    @pytest.mark.parametrize(
        "fmt",
        ["sarif", "json", "junit", "github", "rdjson", "gitlab"],
    )
    def test_machine_formats_exit(self, fmt: str, tmp_path: Path) -> None:
        console, _ = _capturing_console()
        result = AnalysisResult(diagnostics=[], file_count=0, total_lines=0)
        args = _args(output_format=fmt, path=str(tmp_path), output_file=None)
        with pytest.raises(SystemExit):
            _handle_output_format(
                args,
                [],
                result,
                0.0,
                console,
                ignored_codes=set(),
                had_failed_writes=False,
            )

    def test_failed_writes_promote_exit_to_one(self, tmp_path: Path) -> None:
        # sarif format returns exit code 0 normally — with failed writes
        # the gate should force exit 1.
        console, _ = _capturing_console()
        result = AnalysisResult(diagnostics=[], file_count=0, total_lines=0)
        args = _args(output_format="sarif", path=str(tmp_path))
        with pytest.raises(SystemExit) as exc:
            _handle_output_format(
                args,
                [],
                result,
                0.0,
                console,
                ignored_codes=set(),
                had_failed_writes=True,
            )
        assert exc.value.code == 1
