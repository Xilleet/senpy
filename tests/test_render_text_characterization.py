"""Characterization tests for render_text.

render_text renders diagnostics in text format (cards + table + summary).
After:
  - _render_diagnostic_cards
  - _render_summary_table
  - _render_fixable_report
  - _render_summary_line

These tests capture current behavior so refactoring doesn't break it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from senpy.cli.main import render_text

# =============================================================================
# Helpers: mock Diagnostic and AnalysisResult (same pattern as test_render_formats)
# =============================================================================

@dataclass
class MockDiagnostic:
    code: str = "RPY101"
    severity: str = "ERROR"
    file_path: str = "test.rpy"
    line_number: int = 1
    col: int = 1
    end_col: int = 2
    message: str = "test message"
    line_content: str = "test line"
    fix_title: str | None = None


@dataclass
class MockResult:
    diagnostics: list = field(default_factory=list)
    total_lines: int = 100
    file_count: int = 1
    fixed_count: int = 0
    fixable_count: int = 0


def _make_args(**kwargs) -> MagicMock:
    """Create args Namespace for render_text."""
    args = MagicMock()
    args.exit_zero = kwargs.get("exit_zero", False)
    args.fix = kwargs.get("fix", False)
    args.show_fixes = kwargs.get("show_fixes", False)
    args.info = kwargs.get("info", True)
    return args


def _make_console() -> Console:
    """Create a Console that captures output (no terminal)."""
    return Console(force_terminal=False, no_color=True, width=120)


def _run_render(
    diagnostics: list,
    result: MockResult | None = None,
    hidden_info: int = 0,
    is_tsundere: bool = False,
    elapsed: float = 0.5,
    max_errors: int = 50,
    **args_kwargs,
) -> tuple[int, str]:
    """Run render_text, return (exit_code, captured_output)."""
    if result is None:
        result = MockResult(diagnostics=list(diagnostics))

    args = _make_args(**args_kwargs)
    console = _make_console()

    # Capture console output via redirect
    import io
    buf = io.StringIO()
    console.file = buf

    exit_code = render_text(
        active_diagnostics=diagnostics,
        hidden_info_count=hidden_info,
        result=result,
        args=args,
        console=console,
        is_tsundere=is_tsundere,
        elapsed=elapsed,
        max_errors=max_errors,
    )
    return exit_code, buf.getvalue()


# =============================================================================
# 1. Empty diagnostics — "All clean!" message
# =============================================================================

def test_render_text_empty_diags_exits_0():
    """No diagnostics → "All clean!" message, exit 0."""
    exit_code, output = _run_render(diagnostics=[])

    assert exit_code == 0
    assert "All clean" in output or "clean" in output.lower()


def test_render_text_empty_diags_shows_line_count():
    """Empty diagnostics output includes total_lines and file_count."""
    result = MockResult(diagnostics=[], total_lines=500, file_count=3)
    exit_code, output = _run_render(diagnostics=[], result=result)

    assert exit_code == 0
    assert "500" in output  # total_lines
    assert "3" in output  # file_count


def test_render_text_empty_diags_with_fixed_count():
    """Empty diagnostics + fixed_count > 0 → mentions fixes applied."""
    result = MockResult(diagnostics=[], fixed_count=5)
    exit_code, output = _run_render(diagnostics=[], result=result)

    assert exit_code == 0
    assert "5" in output
    assert "fix" in output.lower()


# =============================================================================
# 2. With diagnostics — cards + table + summary
# =============================================================================

def test_render_text_with_errors_exits_1():
    """Diagnostics with ERROR severity → exit 1."""
    diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
    exit_code, output = _run_render(diagnostics=diags)

    assert exit_code == 1


def test_render_text_with_warnings_only_exits_0():
    """Diagnostics with only WARNING severity (no ERROR) → exit 0."""
    diags = [MockDiagnostic(code="RPY104", severity="WARNING")]
    exit_code, output = _run_render(diagnostics=diags)

    assert exit_code == 0  # warnings don't trigger exit 1


def test_render_text_with_errors_exit_zero_flag():
    """--exit-zero flag forces exit 0 even with ERRORs."""
    diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
    exit_code, output = _run_render(diagnostics=diags, exit_zero=True)

    assert exit_code == 0


def test_render_text_shows_diagnostic_cards():
    """Output includes diagnostic cards with file:line, code, message."""
    diags = [
        MockDiagnostic(
            code="RPY101",
            severity="ERROR",
            file_path="game/script.rpy",
            line_number=42,
            message="Variable not declared",
            line_content="$ x = 1",
        )
    ]
    exit_code, output = _run_render(diagnostics=diags)

    assert "game/script.rpy" in output
    assert "42" in output
    assert "RPY101" in output
    assert "Variable not declared" in output


def test_render_text_shows_summary_table():
    """Output includes summary table with Rule/Severity/Count columns."""
    diags = [
        MockDiagnostic(code="RPY101", severity="ERROR"),
        MockDiagnostic(code="RPY101", severity="ERROR"),
        MockDiagnostic(code="RPY104", severity="WARNING"),
    ]
    exit_code, output = _run_render(diagnostics=diags)

    # Table header
    assert "Rule" in output
    assert "Severity" in output
    assert "Count" in output
    # RPY101 count = 2
    assert "2" in output


def test_render_text_summary_line_counts():
    """Summary line shows correct error/warning counts."""
    diags = [
        MockDiagnostic(code="RPY101", severity="ERROR"),
        MockDiagnostic(code="RPY102", severity="ERROR"),
        MockDiagnostic(code="RPY104", severity="WARNING"),
        MockDiagnostic(code="RPY703", severity="HINT"),
    ]
    exit_code, output = _run_render(diagnostics=diags)

    assert "2 error" in output
    assert "1 warning" in output
    assert "1 hint" in output


# =============================================================================
# 3. max_errors limit
# =============================================================================

def test_render_text_max_errors_limits_cards():
    """--max-errors limits number of diagnostic cards shown."""
    diags = [
        MockDiagnostic(code=f"RPY10{i}", severity="ERROR", line_number=i)
        for i in range(10)
    ]
    exit_code, output = _run_render(diagnostics=diags, max_errors=3)

    # Should mention that 7 more were omitted
    assert "7 more" in output or "omitted" in output


# =============================================================================
# 4. Fixable / fixed report
# =============================================================================

def test_render_text_fixable_count_without_fix_flag():
    """fixable_count > 0 without --fix → "fixable with --fix" message."""
    result = MockResult(diagnostics=[MockDiagnostic()], fixable_count=3)
    exit_code, output = _run_render(
        diagnostics=[MockDiagnostic()],
        result=result,
        fix=False,
    )

    assert "3" in output
    assert "fixable" in output.lower()
    assert "--fix" in output


def test_render_text_fixed_count_with_fix_flag():
    """fixed_count > 0 with --fix → "fixed N error(s)" message."""
    result = MockResult(diagnostics=[MockDiagnostic()], fixed_count=2)
    exit_code, output = _run_render(
        diagnostics=[MockDiagnostic()],
        result=result,
        fix=True,
    )

    assert "2" in output
    assert "fixed" in output.lower() or "fix" in output.lower()


def test_render_text_show_fixes_lists_fix_titles():
    """--show-fixes with fixed_count > 0 → lists fix titles."""
    diag = MockDiagnostic(fix_title="Added 'default x = 0'")
    result = MockResult(diagnostics=[diag], fixed_count=1)
    exit_code, output = _run_render(
        diagnostics=[diag],
        result=result,
        fix=True,
        show_fixes=True,
    )

    assert "Applied fixes" in output
    assert "Added 'default x = 0'" in output


def test_render_text_show_fixes_without_fix_says_zero():
    """--show-fixes without --fix → "0 fixes applied" message."""
    exit_code, output = _run_render(
        diagnostics=[MockDiagnostic()],
        result=MockResult(diagnostics=[MockDiagnostic()], fixed_count=0),
        fix=False,
        show_fixes=True,
    )

    assert "0 fixes applied" in output


# =============================================================================
# 5. hidden_info_count
# =============================================================================

def test_render_text_hidden_info_count_message():
    """hidden_info_count > 0 → "info notice(s) omitted" message."""
    exit_code, output = _run_render(
        diagnostics=[MockDiagnostic()],
        hidden_info=5,
    )

    assert "5" in output
    assert "info" in output.lower()
    assert "omitted" in output.lower() or "--info" in output


# =============================================================================
# 6. Tsundere mode
# =============================================================================

def test_render_text_tsundere_empty_diags():
    """Tsundere mode + empty diagnostics → tsundere clean message."""
    exit_code, output = _run_render(diagnostics=[], is_tsundere=True)

    assert exit_code == 0
    # Tsundere UI has specific phrases
    assert "бака" in output or "baka" in output.lower() or "hmph" in output.lower() or "senpy" in output.lower()


def test_render_text_tsundere_with_errors():
    """Tsundere mode + errors → tsundere error message, exit 1."""
    diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
    exit_code, output = _run_render(diagnostics=diags, is_tsundere=True)

    assert exit_code == 1


# =============================================================================
# 7. Backward compat — render_text importable
# =============================================================================

def test_render_text_importable_from_cli_main():
    """render_text must remain importable from senpy.cli.main after ARCH-3."""
    from senpy.cli.main import render_text as f1
    assert callable(f1)
