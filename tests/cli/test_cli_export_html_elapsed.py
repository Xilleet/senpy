"""TDD test for `handle_export_html` threading `elapsed` through to the report.

The HTML report template renders ``Analysis time: <b>{elapsed:.3f}s</b>``
(`senpy/formats/html_report.py:131`). The CLI measures elapsed time at
`senpy/cli/main.py:1376` (``elapsed = time.perf_counter() - start_time``)
but `handle_export_html` currently hardcodes ``elapsed=0.0`` when calling
`generate_html_report` — the measured value is never threaded through.

Result: every `senpy --export-html report.html` invocation shows
"Analysis time: 0.000s" in the generated report, regardless of how long
the analysis actually took.

RED: this test calls `handle_export_html` with an explicit `elapsed`
keyword argument. The current signature does not accept it, so the
test fails with TypeError. GREEN: the signature is extended to take
`elapsed: float`, the caller in `_handle_post_analysis` passes the
measured value, and `generate_html_report` receives it instead of 0.0.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console

from senpy.cli.commands import handle_export_html
from senpy.core.analyzer import SenpyAnalyzer


@pytest.fixture
def setup_project(tmp_path: Path):
    """Build a minimal Ren'Py project that `SenpyAnalyzer` can scan."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)
    return analyzer, result


def test_handle_export_html_accepts_elapsed_parameter(setup_project, tmp_path: Path):
    """handle_export_html must accept an `elapsed` keyword argument.

    Without it, the measured analysis time at senpy/cli/main.py:1376 has
    no way to reach generate_html_report — the call site hardcodes 0.0.
    """
    analyzer, result = setup_project
    out_html = tmp_path / "report.html"
    args = SimpleNamespace(
        export_html=str(out_html),
        errors_only=False,
        info=True,
    )
    console = Console(legacy_windows=False)

    # Must accept elapsed= as a keyword argument. RED: TypeError.
    handle_export_html(
        args,
        result,
        analyzer,
        console,
        is_tsundere=False,
        ignored_codes=set(),
        elapsed=0.123,
    )

    # Sanity: the HTML file was actually written.
    assert out_html.exists(), "handle_export_html did not write the HTML file"


def test_handle_export_html_threads_elapsed_into_report(setup_project, tmp_path: Path, monkeypatch):
    """The `elapsed` value passed to handle_export_html must reach
    generate_html_report verbatim — not be replaced with 0.0.

    Spies on senpy.formats.html_report.generate_html_report and records
    the kwargs it was called with. The spy delegates to the real
    implementation so the HTML file is still written.
    """
    analyzer, result = setup_project
    out_html = tmp_path / "report.html"
    args = SimpleNamespace(
        export_html=str(out_html),
        errors_only=False,
        info=True,
    )
    console = Console(legacy_windows=False)

    import senpy.formats.html_report as html_mod

    captured: dict[str, object] = {}
    real_generate = html_mod.generate_html_report

    def spy(**kwargs):
        captured.update(kwargs)
        return real_generate(**kwargs)

    monkeypatch.setattr(html_mod, "generate_html_report", spy)

    handle_export_html(
        args,
        result,
        analyzer,
        console,
        is_tsundere=False,
        ignored_codes=set(),
        elapsed=0.456,
    )

    assert "elapsed" in captured, (
        "generate_html_report was not called with an `elapsed` kwarg — "
        "handle_export_html dropped it"
    )
    assert captured["elapsed"] == 0.456, (
        f"generate_html_report received elapsed={captured['elapsed']!r} — "
        "handle_export_html must pass the caller's value through, not 0.0"
    )


def test_handle_export_html_report_shows_nonzero_time(setup_project, tmp_path: Path):
    """End-to-end: the HTML file written by handle_export_html must
    contain the elapsed value passed in, not '0.000s'.

    The HTML template renders ``Analysis time: <b>{elapsed:.3f}s</b>``.
    Passing elapsed=0.456 must produce 'Analysis time: <b>0.456s</b>' in
    the file. The pre-fix code hardcoded 0.0 → '0.000s'.
    """
    analyzer, result = setup_project
    out_html = tmp_path / "report.html"
    args = SimpleNamespace(
        export_html=str(out_html),
        errors_only=False,
        info=True,
    )
    console = Console(legacy_windows=False)

    handle_export_html(
        args,
        result,
        analyzer,
        console,
        is_tsundere=False,
        ignored_codes=set(),
        elapsed=0.789,
    )

    html = out_html.read_text(encoding="utf-8")
    assert "0.789s" in html, (
        "HTML report does not contain the real elapsed time — "
        "handle_export_html did not thread elapsed=0.789 through. "
        "Report still shows hardcoded '0.000s'."
    )
    assert "0.000s" not in html, (
        "HTML report shows '0.000s' — handle_export_html passed "
        "elapsed=0.0 to generate_html_report instead of the real value"
    )
