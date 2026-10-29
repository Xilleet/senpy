"""TDD тесты для render_sarif() и render_json() — Phase 3, Step 2b (0.5.6).

RED: эти тесты падают, потому что функции ещё не существуют.
GREEN: после extraction из main() — тесты проходят.

Ключевое отличие от main(): функции ВОЗВРАЩАЮТ exit code,
а НЕ вызывают sys.exit() напрямую. main() делает sys.exit(render_sarif(...)).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest


# =============================================================================
# Helpers: mock Diagnostic и AnalysisResult (как в test_filter_diagnostics)
# =============================================================================

@dataclass
class MockDiagnostic:
    code: str
    severity: str
    file_path: str = "test.rpy"
    line_number: int = 1
    col: int = 1
    end_col: int = 2
    message: str = "test message"
    line_content: str = "test line"


@dataclass
class MockResult:
    diagnostics: list = None
    total_lines: int = 100
    file_count: int = 1
    fixed_count: int = 0
    fixable_count: int = 0

    def __post_init__(self):
        if self.diagnostics is None:
            self.diagnostics = []


def _make_args(**kwargs):
    """Создаёт mock Namespace с нужными атрибутами."""
    from argparse import Namespace
    defaults = {
        "path": ".",
        "output_file": None,
        "output_format": "text",
    }
    defaults.update(kwargs)
    return Namespace(**defaults)


# =============================================================================
# render_sarif()
# =============================================================================

class TestRenderSarif:
    """Тесты для render_sarif() — извлечено из main() в Phase 3 Step 2b."""

    def test_render_sarif_exists(self):
        """render_sarif() должна существовать в senpy.cli.main."""
        from senpy.cli.main import render_sarif
        assert callable(render_sarif)

    def test_returns_int_exit_code(self):
        """render_sarif() возвращает int (exit code), не вызывает sys.exit."""
        from senpy.cli.main import render_sarif
        from rich.console import Console
        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        args = _make_args(output_format="sarif")
        result = MockResult(diagnostics=diags)
        exit_code = render_sarif(diags, args, console)
        assert isinstance(exit_code, int)

    def test_exit_1_when_errors_present(self):
        """Если есть ERROR diagnostics → exit code 1."""
        from senpy.cli.main import render_sarif
        from rich.console import Console
        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        args = _make_args(output_format="sarif")
        exit_code = render_sarif(diags, args, console)
        assert exit_code == 1

    def test_exit_0_when_no_errors(self):
        """Если ERROR нет (только WARNING) → exit code 0."""
        from senpy.cli.main import render_sarif
        from rich.console import Console
        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY104", severity="WARNING")]
        args = _make_args(output_format="sarif")
        exit_code = render_sarif(diags, args, console)
        assert exit_code == 0

    def test_exit_0_when_empty(self):
        """Пустой список diagnostics → exit code 0."""
        from senpy.cli.main import render_sarif
        from rich.console import Console
        console = Console(force_terminal=False, legacy_windows=False)
        args = _make_args(output_format="sarif")
        exit_code = render_sarif([], args, console)
        assert exit_code == 0

    def test_stdout_contains_sarif_json(self, capsys):
        """Без --output-file: SARIF JSON пишется в stdout."""
        from senpy.cli.main import render_sarif
        from rich.console import Console
        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        args = _make_args(output_format="sarif")
        render_sarif(diags, args, console)
        captured = capsys.readouterr()
        # SARIF — валидный JSON
        data = json.loads(captured.out)
        assert data["version"] == "2.1.0"
        assert "runs" in data

    def test_output_file_written(self, tmp_path, capsys):
        """С --output-file: SARIF пишется в файл, не в stdout."""
        from senpy.cli.main import render_sarif
        from rich.console import Console
        console = Console(force_terminal=False, legacy_windows=False)
        out_file = tmp_path / "report.sarif"
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        args = _make_args(output_format="sarif", output_file=str(out_file))
        render_sarif(diags, args, console)
        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["version"] == "2.1.0"


# =============================================================================
# render_json()
# =============================================================================

class TestRenderJson:
    """Тесты для render_json() — извлечено из main() в Phase 3 Step 2b."""

    def test_render_json_exists(self):
        """render_json() должна существовать в senpy.cli.main."""
        from senpy.cli.main import render_json
        assert callable(render_json)

    def test_returns_int_exit_code(self):
        """render_json() возвращает int (exit code), не вызывает sys.exit."""
        from senpy.cli.main import render_json
        from rich.console import Console
        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        result = MockResult(diagnostics=diags, total_lines=100, fixed_count=0)
        args = _make_args(output_format="json")
        exit_code = render_json(diags, result, 0.5, args, console)
        assert isinstance(exit_code, int)

    def test_exit_1_when_errors_present(self):
        """Если есть ERROR diagnostics → exit code 1."""
        from senpy.cli.main import render_json
        from rich.console import Console
        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        result = MockResult(diagnostics=diags)
        args = _make_args(output_format="json")
        exit_code = render_json(diags, result, 0.5, args, console)
        assert exit_code == 1

    def test_exit_0_when_no_errors(self):
        """Если ERROR нет → exit code 0."""
        from senpy.cli.main import render_json
        from rich.console import Console
        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY104", severity="WARNING")]
        result = MockResult(diagnostics=diags)
        args = _make_args(output_format="json")
        exit_code = render_json(diags, result, 0.5, args, console)
        assert exit_code == 0

    def test_stdout_contains_json(self, capsys):
        """Без --output-file: JSON пишется в stdout."""
        from senpy.cli.main import render_json
        from rich.console import Console
        console = Console(force_terminal=False, legacy_windows=False)
        diags = [
            MockDiagnostic(code="RPY101", severity="ERROR", file_path="game/script.rpy", line_number=10),
        ]
        result = MockResult(diagnostics=diags, total_lines=500, fixed_count=2)
        args = _make_args(output_format="json")
        render_json(diags, result, 1.234, args, console)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "diagnostics" in data
        assert "summary" in data
        assert len(data["diagnostics"]) == 1
        assert data["diagnostics"][0]["code"] == "RPY101"
        assert data["diagnostics"][0]["severity"] == "error"  # lowercase
        assert data["summary"]["total_lines"] == 500
        assert data["summary"]["fixed"] == 2
        assert data["summary"]["time_sec"] == 1.234

    def test_output_file_written(self, tmp_path, capsys):
        """С --output-file: JSON пишется в файл, не в stdout."""
        from senpy.cli.main import render_json
        from rich.console import Console
        console = Console(force_terminal=False, legacy_windows=False)
        out_file = tmp_path / "report.json"
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        result = MockResult(diagnostics=diags, total_lines=100, fixed_count=0)
        args = _make_args(output_format="json", output_file=str(out_file))
        render_json(diags, result, 0.5, args, console)
        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert "diagnostics" in data

    def test_empty_diagnostics_json(self, capsys):
        """Пустой список → JSON с пустым diagnostics array."""
        from senpy.cli.main import render_json
        from rich.console import Console
        console = Console(force_terminal=False, legacy_windows=False)
        result = MockResult(diagnostics=[], total_lines=0, fixed_count=0)
        args = _make_args(output_format="json")
        exit_code = render_json([], result, 0.1, args, console)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["diagnostics"] == []
        assert exit_code == 0
