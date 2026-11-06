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
        from rich.console import Console

        from senpy.cli.main import render_sarif

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        args = _make_args(output_format="sarif")
        exit_code = render_sarif(diags, args, console)
        assert isinstance(exit_code, int)

    def test_exit_1_when_errors_present(self):
        """Если есть ERROR diagnostics → exit code 1."""
        from rich.console import Console

        from senpy.cli.main import render_sarif

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        args = _make_args(output_format="sarif")
        exit_code = render_sarif(diags, args, console)
        assert exit_code == 1

    def test_exit_0_when_no_errors(self):
        """Если ERROR нет (только WARNING) → exit code 0."""
        from rich.console import Console

        from senpy.cli.main import render_sarif

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY104", severity="WARNING")]
        args = _make_args(output_format="sarif")
        exit_code = render_sarif(diags, args, console)
        assert exit_code == 0

    def test_exit_0_when_empty(self):
        """Пустой список diagnostics → exit code 0."""
        from rich.console import Console

        from senpy.cli.main import render_sarif

        console = Console(force_terminal=False, legacy_windows=False)
        args = _make_args(output_format="sarif")
        exit_code = render_sarif([], args, console)
        assert exit_code == 0

    def test_stdout_contains_sarif_json(self, capsys):
        """Без --output-file: SARIF JSON пишется в stdout."""
        from rich.console import Console

        from senpy.cli.main import render_sarif

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
        from rich.console import Console

        from senpy.cli.main import render_sarif

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
        from rich.console import Console

        from senpy.cli.main import render_json

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        result = MockResult(diagnostics=diags, total_lines=100, fixed_count=0)
        args = _make_args(output_format="json")
        exit_code = render_json(diags, result, 0.5, args, console)
        assert isinstance(exit_code, int)

    def test_exit_1_when_errors_present(self):
        """Если есть ERROR diagnostics → exit code 1."""
        from rich.console import Console

        from senpy.cli.main import render_json

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        result = MockResult(diagnostics=diags)
        args = _make_args(output_format="json")
        exit_code = render_json(diags, result, 0.5, args, console)
        assert exit_code == 1

    def test_exit_0_when_no_errors(self):
        """Если ERROR нет → exit code 0."""
        from rich.console import Console

        from senpy.cli.main import render_json

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY104", severity="WARNING")]
        result = MockResult(diagnostics=diags)
        args = _make_args(output_format="json")
        exit_code = render_json(diags, result, 0.5, args, console)
        assert exit_code == 0

    def test_stdout_contains_json(self, capsys):
        """Без --output-file: JSON пишется в stdout."""
        from rich.console import Console

        from senpy.cli.main import render_json

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [
            MockDiagnostic(
                code="RPY101", severity="ERROR", file_path="game/script.rpy", line_number=10
            ),
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
        from rich.console import Console

        from senpy.cli.main import render_json

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
        from rich.console import Console

        from senpy.cli.main import render_json

        console = Console(force_terminal=False, legacy_windows=False)
        result = MockResult(diagnostics=[], total_lines=0, fixed_count=0)
        args = _make_args(output_format="json")
        exit_code = render_json([], result, 0.1, args, console)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["diagnostics"] == []
        assert exit_code == 0


# =============================================================================
# render_rdjson() — Reviewdog NDJSON
# =============================================================================


class TestRenderRdjson:
    """Tests for render_rdjson() — the CLI-level wrapper around
    senpy.formats.rdjson.generate_rdjson.

    Contract: returns int exit code, prints NDJSON to stdout (or writes
    to args.output_file), exit 1 if any ERROR diagnostic is present.
    """

    def test_render_rdjson_exists(self):
        from senpy.cli.main import render_rdjson

        assert callable(render_rdjson)

    def test_returns_int_exit_code(self):
        from rich.console import Console

        from senpy.cli.main import render_rdjson

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        args = _make_args(output_format="rdjson")
        exit_code = render_rdjson(diags, args, console)
        assert isinstance(exit_code, int)

    def test_exit_1_when_errors_present(self):
        from rich.console import Console

        from senpy.cli.main import render_rdjson

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        args = _make_args(output_format="rdjson")
        assert render_rdjson(diags, args, console) == 1

    def test_exit_0_when_no_errors(self, capsys):
        from rich.console import Console

        from senpy.cli.main import render_rdjson

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY104", severity="WARNING")]
        args = _make_args(output_format="rdjson")
        exit_code = render_rdjson(diags, args, console)
        captured = capsys.readouterr()
        assert exit_code == 0
        # Output is one NDJSON line per diagnostic.
        lines = [ln for ln in captured.out.splitlines() if ln.strip()]
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["code"]["value"] == "RPY104"

    def test_writes_to_output_file_when_set(self, tmp_path, capsys):
        from rich.console import Console

        from senpy.cli.main import render_rdjson

        out_file = tmp_path / "report.rdjson"
        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY104", severity="WARNING")]
        args = _make_args(output_format="rdjson", output_file=str(out_file))
        exit_code = render_rdjson(diags, args, console)
        assert exit_code == 0
        # File contents are the NDJSON, not stdout.
        captured = capsys.readouterr()
        assert "saved to" in captured.out
        text = out_file.read_text(encoding="utf-8")
        assert "RPY104" in text


# =============================================================================
# render_gitlab() — GitLab Code Quality JSON
# =============================================================================


class TestRenderGitlab:
    """Tests for render_gitlab() — the CLI-level wrapper around
    senpy.formats.gitlab.generate_gitlab_json.

    Contract: returns int exit code, prints a JSON array to stdout
    (or writes to args.output_file), exit 1 if any ERROR diagnostic
    is present.
    """

    def test_render_gitlab_exists(self):
        from senpy.cli.main import render_gitlab

        assert callable(render_gitlab)

    def test_returns_int_exit_code(self):
        from rich.console import Console

        from senpy.cli.main import render_gitlab

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        args = _make_args(output_format="gitlab")
        exit_code = render_gitlab(diags, args, console)
        assert isinstance(exit_code, int)

    def test_exit_1_when_errors_present(self):
        from rich.console import Console

        from senpy.cli.main import render_gitlab

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        args = _make_args(output_format="gitlab")
        assert render_gitlab(diags, args, console) == 1

    def test_exit_0_and_emits_json_array(self, capsys):
        from rich.console import Console

        from senpy.cli.main import render_gitlab

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY104", severity="WARNING")]
        args = _make_args(output_format="gitlab")
        exit_code = render_gitlab(diags, args, console)
        captured = capsys.readouterr()
        assert exit_code == 0
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["check_name"] == "RPY104"
        assert data[0]["severity"] == "minor"

    def test_empty_diagnostics_emits_empty_array(self, capsys):
        from rich.console import Console

        from senpy.cli.main import render_gitlab

        console = Console(force_terminal=False, legacy_windows=False)
        args = _make_args(output_format="gitlab")
        exit_code = render_gitlab([], args, console)
        captured = capsys.readouterr()
        assert exit_code == 0
        assert json.loads(captured.out) == []

    def test_writes_to_output_file_when_set(self, tmp_path, capsys):
        from rich.console import Console

        from senpy.cli.main import render_gitlab

        out_file = tmp_path / "gl.json"
        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY104", severity="WARNING")]
        args = _make_args(output_format="gitlab", output_file=str(out_file))
        exit_code = render_gitlab(diags, args, console)
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "saved to" in captured.out
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data[0]["check_name"] == "RPY104"


# =============================================================================
# render_junit() — characterization safety net for T-017 split
# =============================================================================


class TestRenderJunit:
    """Characterization tests for ``render_junit`` — JUnit XML output.

    Safety net before the ``cli/main.py`` god-file split (T-017).
    Verifies the JUnit renderer's public contract: returns int exit code,
    exit 1 on ERROR diagnostics, exit 0 otherwise, produces well-formed
    XML with the expected structure, writes to --output-file when set.
    """

    def test_render_junit_exists(self):
        """render_junit must be importable from senpy.cli.main."""
        from senpy.cli.main import render_junit

        assert callable(render_junit)

    def test_returns_int_exit_code(self):
        from rich.console import Console

        from senpy.cli.main import render_junit

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        args = _make_args(output_format="junit")
        exit_code = render_junit(diags, args, console)
        assert isinstance(exit_code, int)

    def test_exit_1_when_errors_present(self):
        from rich.console import Console

        from senpy.cli.main import render_junit

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        args = _make_args(output_format="junit")
        exit_code = render_junit(diags, args, console)
        assert exit_code == 1

    def test_exit_0_when_no_errors(self):
        from rich.console import Console

        from senpy.cli.main import render_junit

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY104", severity="WARNING")]
        args = _make_args(output_format="junit")
        exit_code = render_junit(diags, args, console)
        assert exit_code == 0

    def test_exit_0_when_empty(self):
        from rich.console import Console

        from senpy.cli.main import render_junit

        console = Console(force_terminal=False, legacy_windows=False)
        args = _make_args(output_format="junit")
        exit_code = render_junit([], args, console)
        assert exit_code == 0

    def test_stdout_contains_junit_xml(self, capsys):
        """Without --output-file: JUnit XML written to stdout."""
        import xml.etree.ElementTree as ET

        from rich.console import Console

        from senpy.cli.main import render_junit

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [
            MockDiagnostic(code="RPY101", severity="ERROR", file_path="test.rpy", line_number=5),
            MockDiagnostic(code="RPY104", severity="WARNING", file_path="test.rpy", line_number=10),
        ]
        args = _make_args(output_format="junit")
        render_junit(diags, args, console)
        captured = capsys.readouterr()
        # Must be parseable XML
        root = ET.fromstring(captured.out)
        assert root.tag == "testsuites"
        assert root.get("name") == "senpy"
        assert int(root.get("tests")) == 2
        assert int(root.get("failures")) == 1  # one ERROR
        assert int(root.get("skipped")) == 1  # one WARNING

    def test_output_file_written(self, tmp_path, capsys):
        from rich.console import Console

        from senpy.cli.main import render_junit

        out_file = tmp_path / "report.xml"
        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        args = _make_args(output_format="junit", output_file=str(out_file))
        exit_code = render_junit(diags, args, console)
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "saved to" in captured.out
        content = out_file.read_text(encoding="utf-8")
        assert "<?xml" in content
        assert "<testsuites" in content
        assert "RPY101" in content

    def test_xml_special_chars_in_failure_do_not_break_parse(self, capsys):
        """``<failure>`` must escape ``<``, ``>``, ``&`` in code/line_content.

        Regression: a diagnostic whose ``line_content`` contains XML-special
        characters (e.g. ``if x < 5 and y > 3 and z & w:``) used to make the
        whole JUnit report unparseable by Jenkins / GitLab CI / TeamCity.
        """
        import xml.etree.ElementTree as ET

        from rich.console import Console

        from senpy.cli.main import render_junit

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [
            MockDiagnostic(
                code="RPY101",
                severity="ERROR",
                file_path="test.rpy",
                line_number=3,
                message='condition uses "quotes" & angle brackets',
                line_content="if x < 5 and y > 3 and z & w:",
            )
        ]
        args = _make_args(output_format="junit")
        render_junit(diags, args, console)
        captured = capsys.readouterr()
        # The whole document must parse as well-formed XML.
        root = ET.fromstring(captured.out)
        failures = root.findall(".//failure")
        assert len(failures) == 1
        # Raw ``<``/``>``/``&`` (unescaped) must never appear inside the
        # failure element — they break every standard XML parser.
        failure_xml = ET.tostring(failures[0], encoding="unicode")
        assert "if x < 5" not in failure_xml
        assert "y > 3" not in failure_xml
        assert "z & w" not in failure_xml
        # The escaped representation must round-trip back to the original text.
        assert (failures[0].text or "")[
            -len("if x < 5 and y > 3 and z & w:") :
        ] == "if x < 5 and y > 3 and z & w:"
        # The ``type`` attribute (rule code) must also survive intact.
        assert failures[0].get("type") == "RPY101"
        assert failures[0].get("message") == 'condition uses "quotes" & angle brackets'

    def test_xml_special_chars_in_skipped_do_not_break_parse(self, capsys):
        """``<skipped>`` must escape ``<``/``>``/``&`` in the rule ``code``.

        WARNING diagnostics render as ``<skipped>``, and their ``type``
        attribute is ``diag.code``. If a plugin rule code contains XML-special
        characters (or a malicious plugin injects them), the report must still
        parse.
        """
        import xml.etree.ElementTree as ET

        from rich.console import Console

        from senpy.cli.main import render_junit

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [
            MockDiagnostic(
                code='PLUGIN<X>&"rule"',
                severity="WARNING",
                file_path="test.rpy",
                line_number=7,
                message="warn < & > test",
            )
        ]
        args = _make_args(output_format="junit")
        render_junit(diags, args, console)
        captured = capsys.readouterr()
        # Must still parse as well-formed XML.
        root = ET.fromstring(captured.out)
        skipped = root.findall(".//skipped")
        assert len(skipped) == 1
        # The original (unescaped) code must round-trip through the attribute.
        assert skipped[0].get("type") == 'PLUGIN<X>&"rule"'
        assert skipped[0].get("message") == "warn < & > test"


# =============================================================================
# render_github() — characterization safety net for T-017 split
# =============================================================================


class TestRenderGithub:
    """Characterization tests for ``render_github`` — GitHub Actions format.

    Safety net before the ``cli/main.py`` god-file split (T-017).
    Verifies the GitHub renderer's public contract: returns int exit code,
    exit 1 on ERROR diagnostics, exit 0 otherwise, emits ``::error`` /
    ``::warning`` workflow commands, writes to --output-file when set.
    """

    def test_render_github_exists(self):
        from senpy.cli.main import render_github

        assert callable(render_github)

    def test_returns_int_exit_code(self):
        from rich.console import Console

        from senpy.cli.main import render_github

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        args = _make_args(output_format="github")
        exit_code = render_github(diags, args, console)
        assert isinstance(exit_code, int)

    def test_exit_1_when_errors_present(self):
        from rich.console import Console

        from senpy.cli.main import render_github

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        args = _make_args(output_format="github")
        exit_code = render_github(diags, args, console)
        assert exit_code == 1

    def test_exit_0_when_no_errors(self):
        from rich.console import Console

        from senpy.cli.main import render_github

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY104", severity="WARNING")]
        args = _make_args(output_format="github")
        exit_code = render_github(diags, args, console)
        assert exit_code == 0

    def test_stdout_contains_workflow_commands(self, capsys):
        """stdout must contain ``::error`` and ``::warning`` workflow commands."""
        from rich.console import Console

        from senpy.cli.main import render_github

        console = Console(force_terminal=False, legacy_windows=False)
        diags = [
            MockDiagnostic(code="RPY101", severity="ERROR", file_path="test.rpy", line_number=5),
            MockDiagnostic(code="RPY104", severity="WARNING", file_path="test.rpy", line_number=10),
        ]
        args = _make_args(output_format="github", path=".")
        render_github(diags, args, console)
        captured = capsys.readouterr()
        # GitHub Actions format: ::error file=X,line=N,col=C::CODE: msg
        assert "::error" in captured.out
        assert "::warning" in captured.out
        assert "RPY101" in captured.out
        assert "RPY104" in captured.out

    def test_output_file_written(self, tmp_path, capsys):
        from rich.console import Console

        from senpy.cli.main import render_github

        out_file = tmp_path / "annotations.txt"
        console = Console(force_terminal=False, legacy_windows=False)
        diags = [MockDiagnostic(code="RPY101", severity="ERROR")]
        args = _make_args(output_format="github", output_file=str(out_file), path=".")
        exit_code = render_github(diags, args, console)
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "saved to" in captured.out
        content = out_file.read_text(encoding="utf-8")
        assert "::error" in content
        assert "RPY101" in content
