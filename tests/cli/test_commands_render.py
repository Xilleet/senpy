"""Coverage push: Rich-render branches of senpy/cli/commands.py.

These tests directly invoke the ``handle_*`` CLI handlers with a captured
``rich.console.Console`` to cover the display branches (Panel / Table /
Text rendering) that the existing subprocess-based CLI tests skip — they
verify exit codes and stdout text, but the in-process Rich rendering
inside each handler is not exercised, leaving ~116 lines uncovered.

Each test constructs a real ``SenpyAnalyzer`` on a tiny in-memory
project (or calls the handler with mocked collaborators where the
analyzer isn't needed), passes a non-tty ``Console(file=StringIO,
no_color=True)``, and asserts that the captured output contains the
expected key strings (rule codes, file paths, tsundere/non-tsundere
messages). Assertions are intentionally loose — we're testing that
the rendering branches execute without crashing AND emit recognisable
text, not exact ANSI sequences.
"""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console

from senpy.cli.commands import (
    handle_clear_cache,
    handle_coverage,
    handle_defaults,
    handle_export_html,
    handle_export_wiki,
    handle_graph,
    handle_init_ci,
    handle_stats,
    handle_stubs,
    handle_traceback,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capturing_console() -> tuple[Console, io.StringIO]:
    """Return a non-tty Console whose output we can read back."""
    buf = io.StringIO()
    return Console(file=buf, force_terminal=False, no_color=True, width=200), buf


def _write_min_project(tmp_path: Path) -> Path:
    """Tiny Ren'Py project with one label + one screen, returns project root."""
    game = tmp_path / "game"
    game.mkdir(parents=True, exist_ok=True)
    (game / "script.rpy").write_text(
        "label start:\n" '    "Hello, world."\n' "    return\n",
        encoding="utf-8",
    )
    return tmp_path


def _args(**kw) -> SimpleNamespace:
    """Build a fake ``args`` namespace; missing flags default to falsy."""
    defaults = {
        "traceback": None,
        "init_ci": False,
        "coverage": False,
        "clear_cache": False,
        "stats": False,
        "export_wiki": None,
        "export_html": None,
        "graph": False,
        "graph_file": None,
        "defaults": False,
        "stubs": None,
        "output_format": None,
        "output_file": None,
        "errors_only": False,
        "info": False,
        "path": ".",
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# handle_traceback
# ---------------------------------------------------------------------------


class TestHandleTraceback:
    def test_returns_none_when_flag_not_set(self) -> None:
        console, _ = _capturing_console()
        rc = handle_traceback(_args(), console, is_tsundere=False)
        assert rc is None

    def test_missing_file_prints_warning(self, tmp_path: Path) -> None:
        console, buf = _capturing_console()
        args = _args(traceback="nonexistent.txt", path=str(tmp_path))
        rc = handle_traceback(args, console, is_tsundere=False)
        assert rc == 0
        out = buf.getvalue()
        assert "Could not find or parse crash log" in out
        assert "Hint" in out

    def test_valid_traceback_file_renders_panel(self, tmp_path: Path) -> None:
        # Build a minimal traceback.txt that parse_traceback_file recognises.
        tb = tmp_path / "traceback.txt"
        tb.write_text(
            "While running game script:\n"
            'File "game/script.rpy", line 5, in script\n'
            "    call bad_label\n"
            "Exception: NameError: name 'bad_label' is not defined\n"
            "-- Full Traceback ------------------------------------------------------------\n",
            encoding="utf-8",
        )
        console, buf = _capturing_console()
        args = _args(traceback=str(tb), path=str(tmp_path))
        rc = handle_traceback(args, console, is_tsundere=False)
        assert rc == 0
        out = buf.getvalue()
        # The panel title is always rendered.
        assert "Traceback Inspector" in out


# ---------------------------------------------------------------------------
# handle_init_ci
# ---------------------------------------------------------------------------


class TestHandleInitCi:
    def test_returns_none_when_flag_not_set(self, tmp_path: Path) -> None:
        console, _ = _capturing_console()
        rc = handle_init_ci(_args(path=str(tmp_path)), console, is_tsundere=False)
        assert rc is None

    def test_creates_workflow_and_prints_path(self, tmp_path: Path) -> None:
        console, buf = _capturing_console()
        args = _args(init_ci=True, path=str(tmp_path))
        rc = handle_init_ci(args, console, is_tsundere=False)
        assert rc == 0
        out = buf.getvalue()
        assert "Successfully created GitHub Actions workflow" in out
        # File should exist under .github/workflows/
        workflows = list((tmp_path / ".github" / "workflows").glob("*.yml"))
        assert workflows, "init_ci should create at least one workflow file"

    def test_tsundere_branch(self, tmp_path: Path) -> None:
        console, buf = _capturing_console()
        args = _args(init_ci=True, path=str(tmp_path))
        rc = handle_init_ci(args, console, is_tsundere=True)
        assert rc == 0
        # Tsundere message comes from TSUNDERE_UI['init_ci'] — no_color=True
        # strips the [bold magenta] markup, so we look for the Japanese
        # emoticon that's hardcoded into every tsundere message.
        out = buf.getvalue()
        assert "(//∇//)" in out or "baka" in out.lower()


# ---------------------------------------------------------------------------
# handle_coverage
# ---------------------------------------------------------------------------


class TestHandleCoverage:
    def test_returns_none_when_flag_not_set(self, tmp_path: Path) -> None:
        console, _ = _capturing_console()
        rc = handle_coverage(_args(path=str(tmp_path)), console, is_tsundere=False)
        assert rc is None

    def test_no_translations_prints_warning(self, tmp_path: Path) -> None:
        _write_min_project(tmp_path)
        console, buf = _capturing_console()
        args = _args(coverage=True, path=str(tmp_path))
        rc = handle_coverage(args, console, is_tsundere=False)
        assert rc == 0
        assert "No translations found" in buf.getvalue()

    def test_with_translations_renders_table(self, tmp_path: Path) -> None:
        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        (game / "script.rpy").write_text(
            'label start:\n    "Hello"\n    return\n', encoding="utf-8"
        )
        tl = game / "tl" / "russian"
        tl.mkdir(parents=True, exist_ok=True)
        (tl / "common.rpy").write_text(
            'translate russian start_1a2b3c4d:\n    old "Hello"\n    new "Привет"\n',
            encoding="utf-8",
        )
        console, buf = _capturing_console()
        args = _args(coverage=True, path=str(tmp_path))
        rc = handle_coverage(args, console, is_tsundere=False)
        assert rc == 0
        out = buf.getvalue()
        assert "Localization Coverage" in out
        assert "russian" in out


# ---------------------------------------------------------------------------
# handle_clear_cache
# ---------------------------------------------------------------------------


class TestHandleClearCache:
    def test_returns_none_when_flag_not_set(self, tmp_path: Path) -> None:
        console, _ = _capturing_console()
        rc = handle_clear_cache(_args(path=str(tmp_path)), console)
        assert rc is None

    def test_no_cache_dir_prints_warning(self, tmp_path: Path) -> None:
        console, buf = _capturing_console()
        args = _args(clear_cache=True, path=str(tmp_path))
        rc = handle_clear_cache(args, console)
        assert rc == 0
        assert "No cache directory found" in buf.getvalue()

    def test_clears_existing_cache(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / ".senpy_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "cache.pkl").write_bytes(b"junk")
        console, buf = _capturing_console()
        args = _args(clear_cache=True, path=str(tmp_path))
        rc = handle_clear_cache(args, console)
        assert rc == 0
        assert "Cache cleared successfully" in buf.getvalue()
        assert not cache_dir.exists()


# ---------------------------------------------------------------------------
# handle_stats
# ---------------------------------------------------------------------------


class TestHandleStats:
    def test_returns_none_when_flag_not_set(self, tmp_path: Path) -> None:
        from senpy.core.analyzer import SenpyAnalyzer

        _write_min_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        console, _ = _capturing_console()
        rc = handle_stats(_args(path=str(tmp_path)), analyzer, console, is_tsundere=False)
        assert rc is None

    def test_renders_dashboard(self, tmp_path: Path) -> None:
        from senpy.core.analyzer import SenpyAnalyzer

        _write_min_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        console, buf = _capturing_console()
        args = _args(stats=True, path=str(tmp_path), output_format=None)
        rc = handle_stats(args, analyzer, console, is_tsundere=False)
        assert rc == 0
        out = buf.getvalue()
        assert "Story & Script Analytics" in out
        assert "Total Dialogue Lines" in out

    def test_json_output_to_file(self, tmp_path: Path) -> None:
        from senpy.core.analyzer import SenpyAnalyzer

        _write_min_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        console, buf = _capturing_console()
        out_file = tmp_path / "stats.json"
        args = _args(
            stats=True,
            path=str(tmp_path),
            output_format="json",
            output_file=str(out_file),
        )
        rc = handle_stats(args, analyzer, console, is_tsundere=False)
        assert rc == 0
        assert out_file.exists()
        import json

        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert "total_dialogue_lines" in data
        assert "Stats saved to" in buf.getvalue()

    def test_json_output_to_stdout(self, tmp_path: Path, capsys) -> None:
        from senpy.core.analyzer import SenpyAnalyzer

        _write_min_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        console, _ = _capturing_console()
        args = _args(stats=True, path=str(tmp_path), output_format="json", output_file=None)
        rc = handle_stats(args, analyzer, console, is_tsundere=False)
        assert rc == 0
        captured = capsys.readouterr()
        import json

        data = json.loads(captured.out)
        assert "total_dialogue_lines" in data


# ---------------------------------------------------------------------------
# handle_export_wiki
# ---------------------------------------------------------------------------


class TestHandleExportWiki:
    def test_returns_none_when_flag_not_set(self, tmp_path: Path) -> None:
        from senpy.core.analyzer import SenpyAnalyzer

        _write_min_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        console, _ = _capturing_console()
        rc = handle_export_wiki(_args(path=str(tmp_path)), analyzer, console, is_tsundere=False)
        assert rc is None

    def test_writes_wiki_file(self, tmp_path: Path) -> None:
        from senpy.core.analyzer import SenpyAnalyzer

        _write_min_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        console, buf = _capturing_console()
        target = tmp_path / "wiki.md"
        args = _args(export_wiki=str(target), path=str(tmp_path))
        rc = handle_export_wiki(args, analyzer, console, is_tsundere=False)
        assert rc == 0
        assert target.exists()
        assert target.read_text(encoding="utf-8"), "wiki file should not be empty"
        assert "exported to" in buf.getvalue()


# ---------------------------------------------------------------------------
# handle_export_html
# ---------------------------------------------------------------------------


class TestHandleExportHtml:
    def test_returns_none_when_flag_not_set(self, tmp_path: Path) -> None:
        from senpy.core.analyzer import SenpyAnalyzer

        _write_min_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        result = analyzer.run(quiet=True)
        console, _ = _capturing_console()
        rc = handle_export_html(
            _args(path=str(tmp_path)),
            result,
            analyzer,
            console,
            is_tsundere=False,
            ignored_codes=set(),
        )
        assert rc is None

    def test_writes_html_report(self, tmp_path: Path) -> None:
        from senpy.core.analyzer import SenpyAnalyzer

        _write_min_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        result = analyzer.run(quiet=True)
        console, buf = _capturing_console()
        target = tmp_path / "report.html"
        args = _args(export_html=str(target), path=str(tmp_path))
        rc = handle_export_html(
            args, result, analyzer, console, is_tsundere=False, ignored_codes=set()
        )
        assert rc == 0
        assert target.exists()
        html = target.read_text(encoding="utf-8")
        assert "<html" in html.lower()
        assert "HTML report saved" in buf.getvalue()


# ---------------------------------------------------------------------------
# handle_graph
# ---------------------------------------------------------------------------


class TestHandleGraph:
    def test_returns_none_when_flags_not_set(self, tmp_path: Path) -> None:
        from senpy.core.analyzer import SenpyAnalyzer

        _write_min_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        console, _ = _capturing_console()
        rc = handle_graph(_args(path=str(tmp_path)), analyzer, console, is_tsundere=False)
        assert rc is None

    def test_graph_to_stdout(self, tmp_path: Path, capsys) -> None:
        from senpy.core.analyzer import SenpyAnalyzer

        _write_min_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        console, _ = _capturing_console()
        args = _args(graph=True, path=str(tmp_path))
        rc = handle_graph(args, analyzer, console, is_tsundere=False)
        assert rc == 0
        captured = capsys.readouterr()
        # Mermaid output goes to sys.stdout.write, not console.
        assert "graph" in captured.out.lower() or "mermaid" in captured.out.lower()

    def test_graph_file(self, tmp_path: Path) -> None:
        from senpy.core.analyzer import SenpyAnalyzer

        _write_min_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        console, buf = _capturing_console()
        target = tmp_path / "graph.mmd"
        args = _args(graph_file=str(target), path=str(tmp_path))
        rc = handle_graph(args, analyzer, console, is_tsundere=False)
        assert rc == 0
        assert target.exists()
        assert "Story flow graph saved" in buf.getvalue()


# ---------------------------------------------------------------------------
# handle_defaults
# ---------------------------------------------------------------------------


class TestHandleDefaults:
    def test_returns_none_when_flag_not_set(self, tmp_path: Path) -> None:
        from senpy.core.analyzer import SenpyAnalyzer

        _write_min_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        console, _ = _capturing_console()
        rc = handle_defaults(_args(path=str(tmp_path)), analyzer, console, is_tsundere=False)
        assert rc is None

    def test_no_missing_defaults(self, tmp_path: Path) -> None:
        from senpy.core.analyzer import SenpyAnalyzer

        _write_min_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        # Force empty missing_defaults so the "all already declared" branch fires.
        analyzer._symbols.missing_defaults.clear()
        console, buf = _capturing_console()
        args = _args(defaults=True, path=str(tmp_path))
        rc = handle_defaults(args, analyzer, console, is_tsundere=False)
        assert rc == 0
        assert "All variables are already properly declared" in buf.getvalue()


# ---------------------------------------------------------------------------
# handle_stubs
# ---------------------------------------------------------------------------


class TestHandleStubs:
    def test_returns_none_when_flag_not_set(self, tmp_path: Path) -> None:
        from senpy.core.analyzer import SenpyAnalyzer

        _write_min_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        console, _ = _capturing_console()
        rc = handle_stubs(_args(path=str(tmp_path)), analyzer, console, is_tsundere=False)
        assert rc is None

    def test_generates_stubs(self, tmp_path: Path) -> None:
        from senpy.core.analyzer import SenpyAnalyzer

        _write_min_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        console, buf = _capturing_console()
        target = tmp_path / "stubs"
        args = _args(stubs=str(target), path=str(tmp_path))
        rc = handle_stubs(args, analyzer, console, is_tsundere=False)
        assert rc == 0
        assert target.exists()
        assert any(target.iterdir()), "stubs dir should contain at least one .pyi"
        assert "Successfully generated Python type stubs" in buf.getvalue()
