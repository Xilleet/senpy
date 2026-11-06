from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from senpy.cli._console import console
from senpy.cli.unrpyc import (  # noqa: F401 — re-exported for backward compat with tests
    decompile_to_sandbox,
    extract_scripts_from_rpa,
    find_unrpyc_executable,
)
from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.config import load_config
from senpy.domain.tsundere import TSUNDERE_FLAVORS, TSUNDERE_UI
from senpy.formats.traceback import find_latest_traceback, parse_traceback_file
from senpy.formatter import FormatConfig, Formatter  # noqa: F401 — re-exported for backward compat

SEVERITY_STYLES = {
    "ERROR": ("bold red", "red dim"),
    "WARNING": ("bold yellow", "yellow dim"),
    "HINT": ("bold cyan", "cyan dim"),
    "INFO": ("bold blue", "blue dim"),
}

# P1-1: unrpyc/rpa functions moved to senpy/_unrpyc_bootstrap.py
# (Option B — moderate refactoring of cli.py)
from senpy.cli.commands import (  # noqa: E402
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


class _ReplaceConsole:
    """Context manager: temporarily replaces the module-level `console` with `file_console`,
    properly closing the file on exit (even on sys.exit inside the block)."""

    def __init__(self, file_console: Console):
        self._file_console = file_console
        self._original_console: Console | None = None

    def __enter__(self):
        global console
        self._original_console = console
        console = self._file_console
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        global console
        # Restore the original console
        if self._original_console is not None:
            console = self._original_console
        # Close the file stream (rich Console stores it in .file)
        try:
            if hasattr(self._file_console.file, "close"):
                self._file_console.file.close()
        except Exception:
            pass
        # Do not suppress exceptions
        return False


def _replace_console(file_console: Console) -> _ReplaceConsole:
    """Factory for the with-block: with _replace_console(file_console): ..."""
    return _ReplaceConsole(file_console)


def _exit_with_output_redirect(args, exit_code: int) -> None:
    """Closes the file (if it was open) and exits with exit_code.
    Used instead of sys.exit() inside the with-block of text output."""
    # sys.exit() raises SystemExit, which is properly handled by
    # the context manager's __exit__ — the file closes automatically.
    sys.exit(exit_code)


def _make_file_console(args) -> Console:
    """Creates a file Console for the text format with --output-file.
    Force_terminal=False so rich does not apply ANSI colors to the file."""
    out_dir = os.path.dirname(os.path.abspath(args.output_file))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    # file expects IO[str], a file object fits
    return Console(
        file=open(args.output_file, "w", encoding="utf-8"),
        force_terminal=False,
        legacy_windows=False,
    )


class _NullRedirect:
    """No-op context manager for the case without --output-file."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def _null_redirect() -> _NullRedirect:
    return _NullRedirect()


def _dispatch_format(argv: list[str]) -> int:
    """Handle `senpy format` subcommand.

    Re-exported from cli/format_dispatch.py (extracted in 0.6.4,).
    Kept here for backward compatibility — existing callers and tests use
    `from senpy.cli.main import _dispatch_format`.
    """
    from senpy.cli.format_dispatch import dispatch_format

    return dispatch_format(argv)


def _add_general_args(parser: argparse.ArgumentParser) -> None:
    """Add --version flag and positional path argument."""
    # --version: prints version and exits (like ruff/black).
    # Uses senpy.__version__ (single source of truth).
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show Senpy version and exit",
    )
    # Positional: path to project
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the Ren'Py project or 'game' directory (default: current dir)",
    )
    parser.add_argument(
        "--respect-gitignore",
        action="store_true",
        help="Skip files matching patterns in .gitignore (reduces noise in large repos).",
    )
    parser.add_argument(
        "--config",
        metavar="FILE",
        help="Path to a custom senpy.toml config file (default: senpy.toml in the project root). "
        "Can also be set via SENPY_CONFIG environment variable.",
    )
    parser.add_argument(
        "--show-settings",
        action="store_true",
        help="Print the resolved configuration (from senpy.toml + CLI flags) and exit. "
        "Useful for debugging which rules are enabled/ignored.",
    )


def _add_rules_args(parser: argparse.ArgumentParser) -> None:
    """Add Rules & Documentation argument group (--rules, --rule)."""
    g = parser.add_argument_group("Rules & Documentation")
    g.add_argument(
        "--rules",
        action="store_true",
        help="List all 40 available Senpy rules and their descriptions",
    )
    g.add_argument(
        "--rule",
        metavar="CODE",
        help="Show detailed explanation and code examples for a specific rule (e.g. --rule RPY104)",
    )


def _add_lint_args(parser: argparse.ArgumentParser) -> None:
    """Add Analysis & Autofix argument group (16 flags)."""
    g = parser.add_argument_group("Analysis & Autofix")
    g.add_argument(
        "--fix",
        action="store_true",
        help="Automatically fix safe errors (unclosed tags RPY301, smart quotes RPY002, tabs RPY001)",
    )
    g.add_argument(
        "--coverage",
        action="store_true",
        help="Display translation coverage metrics and completion percentages for game/tl/",
    )
    g.add_argument(
        "--stats",
        action="store_true",
        help="Calculate story & character dialogue statistics, word count and reading time",
    )
    g.add_argument(
        "--defaults",
        action="store_true",
        help="Generate 'senpy_defaults.rpy' containing 'default' declarations for all RPY104 variables",
    )
    g.add_argument(
        "--errors-only",
        action="store_true",
        help="Show only critical ERRORs, hiding WARNINGs and INFO notices",
    )
    g.add_argument(
        "--info",
        action="store_true",
        help="Display informational notices (e.g. unreferenced labels RPY303)",
    )
    g.add_argument(
        "--ignore",
        nargs="+",
        metavar="CODE",
        default=None,
        help="Ignore specific error codes (e.g. --ignore RPY104 RPY101)",
    )
    g.add_argument(
        "--select",
        nargs="+",
        metavar="CODE",
        default=None,
        help="Run ONLY these rules (e.g. --select RPY101 RPY102). All other rules are disabled.",
    )
    g.add_argument(
        "--extend-select",
        nargs="+",
        metavar="CODE",
        default=None,
        help="Add these rules to --select (no effect without --select).",
    )
    g.add_argument(
        "--extend-ignore",
        nargs="+",
        metavar="CODE",
        default=None,
        help="Add these rules to --ignore (extends the blacklist).",
    )
    g.add_argument(
        "--tag",
        nargs="+",
        metavar="TAG",
        default=None,
        help=(
            "Run ONLY rules with these tags (e.g. --tag rollback state). "
            "Tag matching is case-insensitive and a rule passes if ANY "
            "of its tags is in the list. See `senpy rule list` for the "
            "full tag taxonomy."
        ),
    )
    g.add_argument(
        "--ignore-tag",
        nargs="+",
        metavar="TAG",
        default=None,
        help=(
            "Skip rules with these tags (e.g. --ignore-tag dead-code). "
            "Useful to silence a whole category without enumerating "
            "individual rule codes."
        ),
    )
    g.add_argument(
        "--max-errors",
        type=int,
        metavar="NUM",
        default=None,
        help="Maximum errors to display in terminal (default: 50)",
    )
    g.add_argument("--no-cache", action="store_true", help="Disable disk caching (.senpy_cache)")
    g.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear project cache directory (.senpy_cache) and exit",
    )
    # dry-run and CI-friendly options for --fix
    g.add_argument(
        "--check",
        action="store_true",
        help="Dry-run for --fix: report what would be fixed, but don't write. "
        "Exit 1 if any fixable issues found (CI-friendly).",
    )
    g.add_argument(
        "--diff",
        action="store_true",
        help="Show unified diff of what --fix would change, but don't write files. "
        "Useful for reviewing auto-fixes before applying.",
    )
    g.add_argument(
        "--exit-zero",
        action="store_true",
        help="Always exit 0, even if errors found. Useful for non-blocking CI runs "
        "(e.g. nightly reports). Still prints diagnostics to stdout.",
    )
    g.add_argument(
        "--show-fixes",
        action="store_true",
        help="Show detailed list of fixes applied by --fix (file:line: rule — message). "
        "Without --fix, shows '0 fixes applied'. Useful for CI logs and audit.",
    )
    g.add_argument(
        "--statistics",
        action="store_true",
        help="Print a summary table of diagnostics by rule code (count per rule, sorted by frequency).",
    )
    g.add_argument(
        "--add-noqa",
        action="store_true",
        help="Automatically add '# noqa' suppression comments to all fixable diagnostics. "
        "Useful for suppressing known false positives without editing senpy.toml.",
    )
    g.add_argument(
        "--cache-dir",
        metavar="DIR",
        help="Custom cache directory (default: .senpy_cache in the project root). "
        "Useful for CI with shared cache between runs.",
    )


def _add_export_args(parser: argparse.ArgumentParser) -> None:
    """Add Visualization & Reports argument group."""
    g = parser.add_argument_group("Visualization & Reports")
    g.add_argument(
        "--export-html",
        metavar="FILE",
        help="Generate a standalone HTML report with an interactive story map and diagnostics",
    )
    g.add_argument(
        "--export-wiki",
        nargs="?",
        const="PROJECT_WIKI.md",
        metavar="FILE",
        help="Generate project documentation (characters, variables, endings) in Markdown (default: PROJECT_WIKI.md)",
    )
    g.add_argument(
        "--graph",
        action="store_true",
        help="Generate a Mermaid.js diagram of the story flow and label transitions",
    )
    g.add_argument(
        "--graph-file",
        metavar="FILE",
        help="Save the Mermaid.js story diagram directly to a file (e.g. story.md)",
    )
    g.add_argument(
        "--output-format",
        "--format",
        dest="output_format",
        choices=["text", "json", "sarif", "junit", "github", "rdjson", "gitlab"],
        default="text",
        help="Output format: 'text' (default), 'json' for VS Code, 'sarif' for "
        "GitHub Actions, 'junit' for CI (XML), 'github' for PR annotations, "
        "'rdjson' for Reviewdog (NDJSON), 'gitlab' for GitLab Code Quality",
    )
    g.add_argument(
        "--output-file",
        metavar="FILE",
        help="Save report to a specific file (e.g. report.json or report.txt)",
    )


def _add_tools_args(parser: argparse.ArgumentParser) -> None:
    """Add Tools & Integrations argument group."""
    g = parser.add_argument_group("Tools & Integrations")
    g.add_argument(
        "--lsp",
        action="store_true",
        help="Run Senpy as a Language Server (LSP) for editors like VS Code / Neovim",
    )
    g.add_argument(
        "--init-ci",
        action="store_true",
        help="Generate a GitHub Actions workflow (.github/workflows/senpy.yml) with automated SARIF scanning",
    )
    g.add_argument(
        "--traceback",
        nargs="?",
        const="traceback.txt",
        metavar="FILE",
        help="Inspect runtime crash log (traceback.txt or errors.txt) and explain the crash using Senpy rules",
    )
    g.add_argument(
        "--stubs",
        nargs="?",
        const="typings",
        metavar="DIR",
        help="Generate Python type stubs (.pyi) for Pylance / MyPy in VS Code (default: typings/)",
    )
    g.add_argument(
        "--decompile",
        action="store_true",
        help="Automatically decompile orphaned .rpyc files into a temporary sandbox",
    )
    g.add_argument("--unrpyc", metavar="PATH", help="Custom path to unrpyc.py or unrpyc executable")
    g.add_argument(
        "--tsundere",
        action="store_true",
        help="B-Baka! It's not like I want to check your visual novel!",
    )
    g.add_argument(
        "--trust-plugin",
        metavar="NAME",
        help="Trust a plugin by name (adds to ~/.senpy/trusted_plugins.json). "
        "Use once from CLI to enable a plugin for LSP/IDE without interactive prompt.",
    )
    g.add_argument(
        "--untrust-plugin",
        metavar="NAME",
        help="Remove a plugin from the trust store. The plugin will be skipped on next load.",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Create argparse parser and parse CLI arguments.

    Orchestrates 5 helpers for argument groups:
      1. _add_general_args — --version, path positional
      2. _add_rules_args — --rules, --rule
      3. _add_lint_args — 16 analysis/autofix flags
      4. _add_export_args — visualization & reports
      5. _add_tools_args — LSP, CI, traceback, stubs, decompile, etc.

    Args:
        argv: Command-line arguments. None = use sys.argv.

    Returns:
        argparse.Namespace with parsed arguments.
    """
    parser = argparse.ArgumentParser(
        prog="senpy",
        description="Notice me, Senpy! Fast semantic linter & LSP for Ren'Py.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    _add_general_args(parser)
    _add_rules_args(parser)
    _add_lint_args(parser)
    _add_export_args(parser)
    _add_tools_args(parser)

    return parser.parse_args(argv)


def load_senpy_ignore(project_path: str) -> set[str]:
    """Reads the .senpy-ignore file from the project root.

    The file contains one rule code per line. Supported formats:
      - Full-line comments (line starts with `#`).
      - Inline comments (`RPY101 # typo in dialogue`).
      - Empty lines.
      - Case-insensitive (normalized to uppercase).

    Args:
        project_path: Path to the project root (where .senpy-ignore is located).

    Returns:
        Set of rule codes (uppercase) to exclude. Empty set if the
        file does not exist or is empty.

    Example file:
        # .senpy-ignore
        RPY101  # typo in dialogue variable
        RPY104
        # RPY105  # commented out — rule will fire
        RPY301
    """
    ignore_file = os.path.join(project_path, ".senpy-ignore")
    if not os.path.isfile(ignore_file):
        return set()

    codes: set[str] = set()
    try:
        with open(ignore_file, encoding="utf-8", errors="replace") as f:
            for line in f:
                # Remove the inline comment (everything after #)
                line = line.split("#", 1)[0]
                code = line.strip().upper()
                if code:
                    codes.add(code)
    except OSError:
        # Could not read — silently return an empty set.
        # DEBUG-level logging is already present in load_config.
        pass

    return codes


def filter_diagnostics(
    result,
    args,
    ignored_codes: set[str],
) -> tuple[list, int]:
    """Filters diagnostics by --ignore, --select, --tag, --ignore-tag, --errors-only, --info."""
    select_codes = _build_select_codes(args)
    full_ignored = _build_full_ignored(ignored_codes, args)
    wanted_tags, ignored_tags = _build_tag_filters(args)

    from senpy.rules.rules_info import RULES_DATABASE

    def _passes_tag_filters(code: str) -> bool:
        info = RULES_DATABASE.get(code)
        rule_tags = {t.lower() for t in info.get("tags", [])} if info else set()
        if wanted_tags is not None and not (rule_tags & wanted_tags):
            return False
        return not (ignored_tags and (rule_tags & ignored_tags))

    hidden_info_count = _count_hidden_info(
        result.diagnostics, full_ignored, select_codes, _passes_tag_filters, args.info
    )
    active_diagnostics = _filter_active(
        result.diagnostics, full_ignored, select_codes, _passes_tag_filters, args
    )
    return active_diagnostics, hidden_info_count


def _build_select_codes(args) -> set[str]:
    """Build the whitelist from --select + --extend-select."""
    select_codes: set[str] = set()
    if getattr(args, "select", None):
        select_codes.update(c.strip().upper() for c in args.select)
        if getattr(args, "extend_select", None):
            select_codes.update(c.strip().upper() for c in args.extend_select)
    return select_codes


def _build_full_ignored(ignored_codes: set[str], args) -> set[str]:
    """Combine ignored_codes with --extend-ignore."""
    full_ignored = set(ignored_codes)
    if getattr(args, "extend_ignore", None):
        full_ignored.update(c.strip().upper() for c in args.extend_ignore)
    return full_ignored


def _build_tag_filters(args) -> tuple[set[str] | None, set[str]]:
    """Extract --tag (whitelist) and --ignore-tag (blacklist) from args."""
    wanted_tags: set[str] | None = None
    if getattr(args, "tag", None):
        wanted_tags = {t.lower() for t in args.tag}
    ignored_tags: set[str] = set()
    if getattr(args, "ignore_tag", None):
        ignored_tags = {t.lower() for t in args.ignore_tag}
    return wanted_tags, ignored_tags


def _count_hidden_info(
    diagnostics: list,
    full_ignored: set[str],
    select_codes: set[str],
    passes_tag_filters,
    show_info: bool,
) -> int:
    """Count INFO-severity diagnostics that are filtered out (for the 'use --info' message)."""
    return sum(
        1
        for e in diagnostics
        if e.severity == "INFO"
        and e.code not in full_ignored
        and (not select_codes or e.code in select_codes)
        and passes_tag_filters(e.code)
        and not show_info
    )


def _filter_active(
    diagnostics: list,
    full_ignored: set[str],
    select_codes: set[str],
    passes_tag_filters,
    args,
) -> list:
    """Apply all filters to produce the active diagnostics list."""
    return [
        e
        for e in diagnostics
        if e.code not in full_ignored
        and (not select_codes or e.code in select_codes)
        and passes_tag_filters(e.code)
        and (not args.errors_only or e.severity == "ERROR")
        and (args.info or e.severity != "INFO")
    ]


def render_sarif(active_diagnostics, args, console) -> int:
    """Renders diagnostics in SARIF format. Returns the exit code (does not call sys.exit).

    Extracted from main() in Phase 3 Step 2b (0.5.6).
    """
    from senpy.formats.sarif import generate_sarif

    sarif_str = generate_sarif(active_diagnostics, args.path)
    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(sarif_str)
        console.print(f"[bold green]✔ SARIF report saved to {args.output_file}[/bold green]")
    else:
        print(sarif_str)
    error_count = sum(1 for e in active_diagnostics if e.severity == "ERROR")
    return 1 if error_count > 0 else 0


def render_rdjson(active_diagnostics, args, console) -> int:
    """Render diagnostics as Reviewdog RDJSON (NDJSON).

    One diagnostic per line; suitable for piping into ``reviewdog -f=rdjson``.
    """
    from senpy.formats.rdjson import generate_rdjson

    out_str = generate_rdjson(active_diagnostics, args.path)
    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(out_str)
        console.print(f"[bold green]✔ RDJSON report saved to {args.output_file}[/bold green]")
    else:
        # NDJSON: print without an extra trailing newline (generate_rdjson
        # already ends with '\n' when non-empty).
        if out_str:
            print(out_str, end="")
        else:
            print()
    error_count = sum(1 for e in active_diagnostics if e.severity == "ERROR")
    return 1 if error_count > 0 else 0


def render_gitlab(active_diagnostics, args, console) -> int:
    """Render diagnostics as a GitLab Code Quality JSON report (array)."""
    from senpy.formats.gitlab import generate_gitlab_json

    out_str = generate_gitlab_json(active_diagnostics, args.path)
    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(out_str)
        console.print(
            f"[bold green]✔ GitLab Code Quality report saved to {args.output_file}[/bold green]"
        )
    else:
        print(out_str)
    error_count = sum(1 for e in active_diagnostics if e.severity == "ERROR")
    return 1 if error_count > 0 else 0


def render_json(active_diagnostics, result, elapsed, args, console) -> int:
    """Renders diagnostics in JSON format. Returns the exit code (does not call sys.exit).

    Extracted from main() in Phase 3 Step 2b (0.5.6).
    """
    json_output = []
    for err in active_diagnostics:
        json_output.append(
            {
                "file": err.file_path,
                "line": err.line_number,
                "col": err.col,
                "end_col": err.end_col,
                "code": err.code,
                "severity": err.severity.lower(),
                "message": err.message,
            }
        )
    output_data = {
        "diagnostics": json_output,
        "summary": {
            "total_lines": result.total_lines,
            "fixed": result.fixed_count,
            "time_sec": round(elapsed, 3),
        },
    }
    json_str = json.dumps(output_data, indent=2, ensure_ascii=False)
    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(json_str)
        console.print(f"[bold green]✔ Report saved to {args.output_file}[/bold green]")
    else:
        print(json_str)
    error_count = sum(1 for e in active_diagnostics if e.severity == "ERROR")
    return 1 if error_count > 0 else 0


def render_junit(active_diagnostics, args, console) -> int:
    """Renders diagnostics in JUnit XML format for CI. Returns the exit code.

    JUnit XML format compatible with
    Jenkins, GitLab CI, TeamCity, etc.
    """
    error_count = sum(1 for e in active_diagnostics if e.severity == "ERROR")
    warning_count = sum(1 for e in active_diagnostics if e.severity == "WARNING")

    # Group diagnostics by file
    by_file: dict[str, list] = {}
    for err in active_diagnostics:
        by_file.setdefault(err.file_path, []).append(err)

    # Build JUnit XML
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append(
        f'<testsuites name="senpy" tests="{len(active_diagnostics)}" '
        f'failures="{error_count}" errors="0" skipped="{warning_count}">'
    )
    for file_path, diags in sorted(by_file.items()):
        suite_name = os.path.basename(file_path)
        lines.append(
            f'  <testsuite name="{_xml_escape(suite_name)}" '
            f'tests="{len(diags)}" failures="{sum(1 for d in diags if d.severity == "ERROR")}" '
            f'errors="0" skipped="{sum(1 for d in diags if d.severity == "WARNING")}">'
        )
        for diag in diags:
            case_name = f"{diag.code}: {diag.message[:80]}"
            lines.append(
                f'    <testcase name="{_xml_escape(case_name)}" classname="{_xml_escape(suite_name)}">'
            )
            if diag.severity == "ERROR":
                lines.append(
                    f'      <failure message="{_xml_escape(diag.message)}" '
                    f'type="{diag.code}">line {diag.line_number}: {diag.line_content.strip()}</failure>'
                )
            elif diag.severity == "WARNING":
                lines.append(
                    f'      <skipped message="{_xml_escape(diag.message)}" '
                    f'type="{diag.code}">line {diag.line_number}</skipped>'
                )
            lines.append("    </testcase>")
        lines.append("  </testsuite>")
    lines.append("</testsuites>")

    junit_str = "\n".join(lines)
    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(junit_str)
        console.print(f"[bold green]✔ JUnit report saved to {args.output_file}[/bold green]")
    else:
        print(junit_str)
    return 1 if error_count > 0 else 0


def render_github(active_diagnostics, args, console) -> int:
    """Renders diagnostics in GitHub Actions format for PR annotations.

    ::error file=X,line=N::message format.
    GitHub Actions automatically picks these up and shows them as PR annotations.
    """
    error_count = sum(1 for e in active_diagnostics if e.severity == "ERROR")

    for diag in active_diagnostics:
        # GitHub Actions workflow command format:
        # ::error file=app/index.js,line=10,col=15::Something went wrong
        file_rel = os.path.relpath(diag.file_path, args.path) if args.path else diag.file_path
        level = (
            "error"
            if diag.severity == "ERROR"
            else "warning"
            if diag.severity == "WARNING"
            else "notice"
        )
        # Escape message: newlines and special chars
        msg = diag.message.replace("\n", " ").replace("::", " ")
        print(
            f"::{level} file={file_rel},line={diag.line_number},col={diag.col}::{diag.code}: {msg}"
        )

    if args.output_file:
        # Also save to file if requested
        with open(args.output_file, "w", encoding="utf-8") as f:
            for diag in active_diagnostics:
                file_rel = (
                    os.path.relpath(diag.file_path, args.path) if args.path else diag.file_path
                )
                level = (
                    "error"
                    if diag.severity == "ERROR"
                    else "warning"
                    if diag.severity == "WARNING"
                    else "notice"
                )
                msg = diag.message.replace("\n", " ").replace("::", " ")
                f.write(
                    f"::{level} file={file_rel},line={diag.line_number},col={diag.col}::{diag.code}: {msg}\n"
                )
        console.print(f"[bold green]✔ GitHub annotations saved to {args.output_file}[/bold green]")
    return 1 if error_count > 0 else 0


def _xml_escape(text: str) -> str:
    """Escape special XML characters for JUnit output."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _render_diagnostic_cards(
    active_diagnostics,
    max_errors: int,
    is_tsundere: bool,
    console: Console,
) -> None:
    """Render diagnostic cards (one Panel per diagnostic) up to max_errors.

    If there are more diagnostics than max_errors, prints an "omitted" notice.
    """
    displayed = active_diagnostics[:max_errors]
    for err in displayed:
        text = Text()
        text.append(f"{err.file_path}:{err.line_number}\n", style="bold cyan")
        text.append(f"  {err.line_number} │ ", style="dim")
        text.append(f"{err.line_content}\n\n", style="bright_white")

        if is_tsundere and err.code in TSUNDERE_FLAVORS:
            text.append(f"  {TSUNDERE_FLAVORS[err.code]}\n", style="bold italic #ff79c6")

        badge_style, border_style = SEVERITY_STYLES.get(err.severity, ("bold red", "red dim"))
        text.append(f"  [{err.severity}] {err.code}: ", style=badge_style)
        text.append(f"{err.message}", style="bright_white")

        panel_border = "magenta dim" if is_tsundere else border_style
        console.print(Panel(text, border_style=panel_border, expand=False))

    if len(active_diagnostics) > max_errors:
        hidden = len(active_diagnostics) - max_errors
        console.print(
            f"\n[dim]... and {hidden} more diagnostic(s) omitted (use --max-errors to show more).[/dim]\n"
        )


def _render_summary_table(
    active_diagnostics,
    is_tsundere: bool,
    console: Console,
) -> None:
    """Render summary table with Rule/Severity/Count columns."""
    counts = Counter((e.code, e.severity) for e in active_diagnostics)
    table = Table(
        title="Diagnostics Summary" if not is_tsundere else TSUNDERE_UI["summary"],
        border_style="dim",
    )
    table.add_column("Rule", style="bold cyan")
    table.add_column("Severity", justify="center")
    table.add_column("Count", justify="right", style="bold white")

    for (code, severity), count in sorted(counts.items()):
        sev_badge = Text(severity, style=SEVERITY_STYLES.get(severity, ("white", ""))[0])
        table.add_row(code, sev_badge, str(count))

    console.print(table)


def _render_fixable_report(
    result,
    args,
    is_tsundere: bool,
    hidden_info_count: int,
    active_diagnostics,
    console: Console,
) -> None:
    """Render fixable/fixed report + hidden info notice.

    Handles 4 cases:
    1. fixed_count > 0 — "Automatically fixed N error(s)" + optional --show-fixes detail
    2. fixable_count > 0 without --fix — "fixable with --fix"
    3. --show-fixes without --fix — "0 fixes applied"
    4. hidden_info_count > 0 — "info notice(s) omitted"
    """
    if result.fixed_count > 0:
        if is_tsundere:
            console.print(
                f"\n[bold magenta](//∇//) «{TSUNDERE_UI['fixed'].format(count=result.fixed_count)}»[/bold magenta]"
            )
        else:
            console.print(
                f"\n[bold green]✔ Automatically fixed {result.fixed_count} error(s)![/bold green]"
            )
        # --show-fixes — detailed "what was fixed" report
        if getattr(args, "show_fixes", False):
            console.print("\n[bold cyan]Applied fixes:[/bold cyan]")
            for diag in active_diagnostics:
                if diag.fix_title:
                    file_name = os.path.basename(diag.file_path)
                    console.print(
                        f"  [dim]{file_name}:{diag.line_number}[/dim] "
                        f"[bold yellow]{diag.code}[/bold yellow] — {diag.fix_title}"
                    )
    elif result.fixable_count > 0 and not args.fix:
        if is_tsundere:
            console.print(
                f"\n[dim magenta][*] {TSUNDERE_UI['fixable'].format(count=result.fixable_count)}[/dim magenta]"
            )
        else:
            console.print(f"\n[dim][*] {result.fixable_count} fixable with the --fix option[/dim]")
    elif getattr(args, "show_fixes", False) and result.fixed_count == 0:
        # --show-fixes without --fix — "0 fixes applied"
        console.print("\n[dim]0 fixes applied (use --fix to apply fixes).[/dim]")

    if hidden_info_count > 0:
        if is_tsundere:
            console.print(
                f"\n[dim magenta](¬_¬ ) «{TSUNDERE_UI['info_omitted'].format(count=hidden_info_count)}»[/dim magenta]"
            )
        else:
            console.print(
                f"\n[dim]ℹ {hidden_info_count} info notice(s) omitted (use --info to view them).[/dim]"
            )


def _render_summary_line(
    active_diagnostics,
    result,
    elapsed: float,
    is_tsundere: bool,
    console: Console,
) -> int:
    """Render final summary line ("Found N errors, M warnings...") and return exit code.

    Exit code: 0 if no ERRORs (or --exit-zero flag), 1 otherwise.
    """
    # Count by category
    error_count = sum(1 for e in active_diagnostics if e.severity == "ERROR")
    warn_count = sum(1 for e in active_diagnostics if e.severity == "WARNING")
    hint_count = sum(1 for e in active_diagnostics if e.severity == "HINT")
    info_count = sum(1 for e in active_diagnostics if e.severity == "INFO")

    summary_parts = []
    if error_count:
        summary_parts.append(f"[bold red]{error_count} error(s)[/bold red]")
    if warn_count:
        summary_parts.append(f"[bold yellow]{warn_count} warning(s)[/bold yellow]")
    if hint_count:
        summary_parts.append(f"[bold cyan]{hint_count} hint(s)[/bold cyan]")
    if info_count:
        summary_parts.append(f"[bold blue]{info_count} info notice(s)[/bold blue]")

    summary_str = ", ".join(summary_parts)

    if is_tsundere:
        if error_count > 0:
            console.print(
                f"\n[bold magenta](╬ Ò﹏Ó) {TSUNDERE_UI['errors'].format(summary_str=summary_str, elapsed=elapsed)}[/bold magenta]"
            )
        else:
            console.print(
                f"\n[bold magenta](¬_¬ ) {TSUNDERE_UI['warnings'].format(summary_str=summary_str, elapsed=elapsed)}[/bold magenta]"
            )
    else:
        status_icon = (
            "[bold red]✖[/bold red]" if error_count > 0 else "[bold yellow]⚠[/bold yellow]"
        )
        console.print(
            f"\n{status_icon} Found {summary_str} "
            f"across [bold]{result.file_count}[/bold] file(s) ({result.total_lines:,} lines) "
            f"in [cyan]{elapsed:.3f}s[/cyan]."
        )

    return error_count


def render_text(
    active_diagnostics,
    hidden_info_count: int,
    result,
    args,
    console: Console,
    is_tsundere: bool,
    elapsed: float,
    max_errors: int,
) -> int:
    """Render diagnostics in text format (cards + table + summary).

    Orchestrates 4 helpers:
      1. _render_diagnostic_cards — Panel per diagnostic
      2. _render_summary_table — Rule/Severity/Count table
      3. _render_fixable_report — fixed/fixable/info-omitted messages
      4. _render_summary_line — final "Found N errors..." line + exit code

    Returns exit code (does not call sys.exit).
    """
    # Empty case — "All clean!" message
    if not active_diagnostics:
        if is_tsundere:
            console.print(
                f"[bold magenta](⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄) «{TSUNDERE_UI['clean_title']}»[/bold magenta]\n"
                f"[dim]{TSUNDERE_UI['clean_sub'].format(lines=result.total_lines, elapsed=elapsed)}[/dim]"
            )
        else:
            msg = f"[bold green]✔ All clean![/bold green] Scanned [bold]{result.total_lines:,}[/bold] lines across [bold]{result.file_count}[/bold] file(s) in [cyan]{elapsed:.3f}s[/cyan]."
            if result.fixed_count > 0:
                msg += f" [bold cyan]({result.fixed_count} fix(es) applied!)[/bold cyan]"
            console.print(msg)
        return 0

    # 1. Diagnostic cards
    _render_diagnostic_cards(active_diagnostics, max_errors, is_tsundere, console)

    # 2. Summary table
    _render_summary_table(active_diagnostics, is_tsundere, console)

    # 3. Fixable/fixed report
    _render_fixable_report(
        result, args, is_tsundere, hidden_info_count, active_diagnostics, console
    )

    # 4. Summary line + exit code
    error_count = _render_summary_line(active_diagnostics, result, elapsed, is_tsundere, console)

    # --exit-zero forces exit 0 even with errors (for non-blocking CI)
    return 0 if args.exit_zero else (1 if error_count > 0 else 0)


# discover_files + helpers (_find_rpy_files, _find_orphaned_rpyc,
# _decompile_sandbox) extracted to senpy/cli/discover.py in 0.7.4
# alongside the `senpy inspect` subcommand. Re-imported here for
# backward compat with tests and external code that may have done
# `from senpy.cli.main import discover_files`.
from senpy.cli.discover import (  # noqa: E402, F401
    _decompile_sandbox,
    _find_orphaned_rpyc,
    _find_rpy_files,
    discover_files,
)


def _dispatch_subcommand(argv: list[str]) -> int | None:
    """Check for subcommand (e.g. `senpy format`) and dispatch.

    Returns exit code if subcommand was dispatched, None otherwise.
    """
    # Subcommand registry — extensible for future subcommands (check, lsp, graph, ci, clean)
    if len(argv) > 1 and argv[1] == "format":
        return _dispatch_format(argv[2:])
    if len(argv) > 1 and argv[1] == "inspect":
        from senpy.cli.inspect_dispatch import dispatch_inspect

        return dispatch_inspect(argv[2:])
    if len(argv) > 1 and argv[1] == "rule":
        from senpy.cli.rule_dispatch import dispatch_rule

        return dispatch_rule(argv[2:])
    return None


def _handle_early_exits(args, console, is_tsundere: bool) -> int | None:
    """Handle early-exit flags: --version, --lsp, --rules, --rule,
    --traceback, --init-ci, --coverage, --clear-cache.

    Returns exit code if early exit happened, None otherwise.
    """
    # --version: prints version and returns 0
    if args.version:
        from senpy.__version__ import __version__

        print(f"senpy {__version__}", flush=True)
        return 0

    # --lsp: starts LSP server and exits
    if args.lsp:
        from senpy.lsp.server import start_lsp

        start_lsp()
        sys.exit(0)

    # --rules / --rule: lists rules or shows one
    if args.rules or args.rule:
        from senpy.rules.rules_info import show_rule_detail, show_rules_table

        if args.rule:
            show_rule_detail(args.rule.upper())
        else:
            show_rules_table()
        sys.exit(0)

    # Handlers return exit code or None (continue)
    _ec = handle_traceback(args, console, is_tsundere)
    if _ec is not None:
        sys.exit(_ec)

    _ec = handle_init_ci(args, console, is_tsundere)
    if _ec is not None:
        sys.exit(_ec)

    _ec = handle_coverage(args, console, is_tsundere)
    if _ec is not None:
        sys.exit(_ec)

    _ec = handle_clear_cache(args, console)
    if _ec is not None:
        sys.exit(_ec)

    # --trust-plugin / --untrust-plugin: manage plugin trust store
    if getattr(args, "trust_plugin", None):
        from senpy.plugins.security import trust_plugin as _trust

        _trust(args.trust_plugin)
        console.print(f"[green]Plugin '{args.trust_plugin}' added to trust store.[/green]")
        console.print(
            "[dim]The plugin will be loaded automatically on next Senpy run (CLI or LSP).[/dim]"
        )
        sys.exit(0)

    if getattr(args, "untrust_plugin", None):
        from senpy.plugins.security import untrust_plugin as _untrust

        removed = _untrust(args.untrust_plugin)
        if removed:
            console.print(
                f"[green]Plugin '{args.untrust_plugin}' removed from trust store.[/green]"
            )
        else:
            console.print(
                f"[yellow]Plugin '{args.untrust_plugin}' was not in the trust store.[/yellow]"
            )
        sys.exit(0)

    # --show-settings: print resolved config and exit
    if getattr(args, "show_settings", False):
        from senpy.core.config import load_config

        project_path = args.path if args.path else "."
        config = load_config(project_path)
        console.print("[bold]Resolved Senpy configuration:[/bold]")
        console.print(f"  project_path: {project_path}")
        for key, val in sorted(config.items()):
            console.print(f"  {key}: {val}")
        sys.exit(0)

    return None


def _validate_flag_combinations(args, console: Console) -> int | None:
    """Validate CLI flag combinations after parse_args, before any work starts.

    Catches user mistakes that would otherwise produce confusing output or
    silently incorrect behavior. Errors print a clear message to stderr and
    return exit code 2 (usage error, matches argparse convention). Warnings
    print to stderr but allow the run to continue.

    Errors (return 2):
      - --fix + --check     — can't apply fixes AND dry-run simultaneously
      - --fix + --diff      — can't apply fixes AND only-show-diff simultaneously
      - --check + --diff    — two dry-run modes at once is ambiguous
      - --select without codes — argparse rejects via `nargs='+'`, but
        defensive check for None/empty (e.g. via senpy.toml config injection)

    Warnings (continue, return None):
      - --extend-select without --select — has no effect; user probably
        meant --select. Print a warning so they notice.
      - --extend-ignore without --ignore AND no config.ignore — has no
        effect; user probably meant --ignore.
      - --add-noqa + --fix — --add-noqa suppresses fixable diagnostics,
        but --fix applies fixes to them. The two flags fight each other.
        We let the run proceed (the user may have a reason), but warn.

    Returns:
        None if validation passed (possibly with warnings printed).
        int exit code (2) if a hard error was found — caller should return
        this from main().
    """
    # Hard errors: combinations that contradict each other.
    if args.fix and args.check:
        console.print(
            "[bold red]Error:[/bold red] --fix and --check cannot be used together. "
            "--fix writes changes; --check only reports what would be fixed (dry-run). "
            "Use one or the other."
        )
        return 2

    if args.fix and args.diff:
        console.print(
            "[bold red]Error:[/bold red] --fix and --diff cannot be used together. "
            "--fix writes changes; --diff only shows what would change (dry-run). "
            "Use --diff to preview, then --fix to apply."
        )
        return 2

    if args.check and args.diff:
        console.print(
            "[bold red]Error:[/bold red] --check and --diff cannot be used together. "
            "Both are dry-run modes for --fix. --check reports a fixable count "
            "(CI-friendly exit code); --diff prints a unified diff. Pick one."
        )
        return 2

    # --select must come with at least one code. argparse `nargs='+'`
    # rejects `--select` with no values, but a config-injected empty
    # list could slip through. Be defensive.
    if args.select is not None and len(args.select) == 0:
        console.print(
            "[bold red]Error:[/bold red] --select requires at least one rule code. "
            "Example: --select RPY101 RPY102. "
            "Run 'senpy rule list' to see all available rules."
        )
        return 2

    # Warnings: combinations that have no effect or fight each other,
    # but don't make the run incorrect. Print and continue.
    if args.extend_select and not args.select:
        console.print(
            "[yellow]Warning:[/yellow] --extend-select has no effect without --select. "
            "--extend-select adds rules to the --select list; without --select, "
            "all rules run by default. Did you mean --select?"
        )

    if args.extend_ignore and not args.ignore and not args.select:
        # --extend-ignore extends the --ignore blacklist. Without any
        # --ignore base (CLI or config), it's a no-op extension.
        # Note: --select + --extend-ignore is fine (select defines a
        # whitelist, extend-ignore removes from it).
        console.print(
            "[yellow]Warning:[/yellow] --extend-ignore has no effect without --ignore "
            "(or config.ignore). --extend-ignore adds rules to the ignore list; "
            "without a base ignore list, nothing changes. Did you mean --ignore?"
        )

    if args.add_noqa and args.fix:
        console.print(
            "[yellow]Warning:[/yellow] --add-noqa and --fix both target fixable "
            "diagnostics. --add-noqa suppresses them with # noqa comments; "
            "--fix applies code changes. --fix will win (applied first), "
            "leaving nothing for --add-noqa to suppress. Did you mean one or the other?"
        )

    return None


def _setup_rule_filters(args, config: dict) -> tuple[set[str], int]:
    """Set up rule filtering: ignored_codes (blacklist) + max_errors.

    Combines sources of ignored rules:
      - args.ignore (CLI --ignore) OR config.ignore (TOML)
      - args.extend_ignore (CLI --extend-ignore)
      - config.extend_ignore (TOML)
      -.senpy-ignore file

    Also reads select/extend_select from config if not set on CLI.

    Returns:
        Tuple of (ignored_codes set, max_errors int).
    """
    cfg_ignore = set(config.get("ignore", []))
    cli_ignore = set(args.ignore) if args.ignore is not None else set()
    cli_extend_ignore = set(args.extend_ignore) if args.extend_ignore is not None else set()
    cfg_extend_ignore = set(config.get("extend_ignore", []))
    senpy_ignore_codes = load_senpy_ignore(args.path)

    base_ignore = cli_ignore if args.ignore is not None else cfg_ignore
    ignored_codes = {
        c.strip().upper()
        for c in (base_ignore | cli_extend_ignore | cfg_extend_ignore | senpy_ignore_codes)
    }

    # --select / --extend-select from config if not set on CLI
    if args.select is None and config.get("select"):
        args.select = list(config.get("select", []))
    if args.extend_select is None and config.get("extend_select"):
        args.extend_select = list(config.get("extend_select", []))

    max_errors = args.max_errors or config.get("max_errors", 50)
    return ignored_codes, max_errors


def _print_scan_banner(args, console, is_tsundere: bool) -> None:
    """Print intro banner + recent crash log warning (if any)."""
    if is_tsundere:
        console.print(
            f"[bold magenta](¬_¬ ) «{TSUNDERE_UI['intro'].format(path=args.path)}»[/bold magenta]\n"
        )
    else:
        console.print(f"[bold cyan]Scanning directory:[/bold cyan] {args.path}...\n")

    recent_tb = find_latest_traceback(args.path)
    if recent_tb:
        auto_crash = parse_traceback_file(recent_tb)
        if auto_crash:
            tb_name = os.path.basename(recent_tb)
            tb_text = Text()
            tb_text.append(f"Recent crash log detected ({tb_name})!\n", style="bold red")
            tb_text.append(
                f"Crashed at: {auto_crash.file_path}:{auto_crash.line_number} — {auto_crash.exception_type}\n",
                style="yellow",
            )
            tb_text.append(
                f"[{auto_crash.rule_code}] {auto_crash.explanation}", style="bright_white"
            )
            console.print(Panel(tb_text, border_style="red dim", expand=False))
            console.print()


def _setup_diff_interception(args) -> tuple[dict[str, str], Any]:
    """Set up builtins.open monkey-patch for --diff mode.

    TODO(0.6.6): Move this into analyzer.run() via dry-run callback.
    The monkey-patch is a hack — analyzer writes to disk via open(), and we
    intercept to capture what would be written without actually writing.
    After analyzer refactor (0.6.6,..15), analyzer should accept a
    dry_run_callback parameter and call it instead of open().

    Returns:
        Tuple of (diff_collector dict, real_open function).
    """
    diff_collector: dict[str, str] = {}
    _real_open = open
    if not args.diff:
        return diff_collector, _real_open

    import builtins

    _real_open = builtins.open

    def _intercept_open(file, mode="r", *a, **kw):
        if "w" in mode and isinstance(file, str) and file.endswith(".rpy"):

            class _DiffCapture:
                def __init__(self):
                    self._buf = []

                def write(self, s):
                    self._buf.append(s)

                def writelines(self, lines):
                    self._buf.extend(lines)

                def close(self):
                    pass

                def flush(self):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    diff_collector[file] = "".join(self._buf)

            return _DiffCapture()
        return _real_open(file, mode, *a, **kw)

    builtins.open = _intercept_open
    return diff_collector, _real_open


def _run_analysis(args, extra_rpy_files, is_quiet_mode: bool):
    """Run SenpyAnalyzer with appropriate fix/no_cache settings.

    Returns:
        Tuple of (result, elapsed_seconds).
    """
    # --check: fix=False (don't modify, just count fixable_count)
    # --diff: fix=True (analyzer prepares changes, but open() intercepted)
    # --fix: fix=True
    # no flags: fix=False
    should_apply_fix = args.fix or args.diff

    # --check and --diff force --no-cache: tier 2 cache stores diagnostics
    # but NOT fixable_count (only incremented in _analyze_file).
    no_cache = args.no_cache or args.check or args.diff

    start_time = time.perf_counter()
    analyzer = SenpyAnalyzer(
        args.path, extra_files=extra_rpy_files, fix=should_apply_fix, no_cache=no_cache
    )
    result = analyzer.run(quiet=is_quiet_mode)
    elapsed = time.perf_counter() - start_time
    return result, analyzer, elapsed


def _handle_post_analysis(args, analyzer, result, console, is_tsundere, ignored_codes, elapsed):
    """Handle post-analysis output flags: --stats, --export-wiki, --export-html,
    --graph, --defaults, --stubs.

    Returns exit code if any handler exited, None otherwise.

    ``elapsed`` is the wall-clock analysis time, threaded through to
    ``handle_export_html`` so the HTML report's "Analysis time" line
    shows the real measurement instead of a hardcoded 0.0.
    """
    _ec = handle_stats(args, analyzer, console, is_tsundere)
    if _ec is not None:
        sys.exit(_ec)
    _ec = handle_export_wiki(args, analyzer, console, is_tsundere)
    if _ec is not None:
        sys.exit(_ec)
    _ec = handle_export_html(
        args, result, analyzer, console, is_tsundere, ignored_codes, elapsed=elapsed
    )
    if _ec is not None:
        sys.exit(_ec)
    _ec = handle_graph(args, analyzer, console, is_tsundere)
    if _ec is not None:
        sys.exit(_ec)
    _ec = handle_defaults(args, analyzer, console, is_tsundere)
    if _ec is not None:
        sys.exit(_ec)
    _ec = handle_stubs(args, analyzer, console, is_tsundere)
    if _ec is not None:
        sys.exit(_ec)
    return None


def _handle_output_format(args, active_diagnostics, result, elapsed, console, ignored_codes):
    """Dispatch output by format: sarif/json/junit/github/rdjson/gitlab exit directly,
    text format returns control to caller for further processing."""
    if args.output_format == "sarif":
        sys.exit(render_sarif(active_diagnostics, args, console))
    elif args.output_format == "json":
        sys.exit(render_json(active_diagnostics, result, elapsed, args, console))
    elif args.output_format == "junit":
        sys.exit(render_junit(active_diagnostics, args, console))
    elif args.output_format == "github":
        sys.exit(render_github(active_diagnostics, args, console))
    elif args.output_format == "rdjson":
        sys.exit(render_rdjson(active_diagnostics, args, console))
    elif args.output_format == "gitlab":
        sys.exit(render_gitlab(active_diagnostics, args, console))
    # text format — caller handles output_redirect + render_text


def _handle_check_mode(args, result, console) -> int | None:
    """Handle --check dry-run mode: print fixable count, exit 0 or 1."""
    if not args.check:
        return None
    if result.fixable_count > 0:
        console.print(
            f"[bold yellow]Would fix {result.fixable_count} issue(s) in {result.file_count} file(s).[/bold yellow]"
        )
        console.print("[dim]Run with --fix to apply these changes.[/dim]")
        sys.exit(1)
    else:
        console.print("[bold green]No fixable issues found.[/bold green]")
        sys.exit(0)


def _handle_diff_mode(args, diff_collector, result, console, _real_open) -> int | None:
    """Handle --diff dry-run mode: print unified diff, exit 0 or 1."""
    if not args.diff:
        return None
    import difflib

    if not diff_collector:
        console.print("[bold green]No changes would be applied by --fix.[/bold green]")
        sys.exit(0)

    console.print(f"[bold cyan]--fix would change {len(diff_collector)} file(s):[/bold cyan]\n")
    has_changes = False
    for file_path, new_content in diff_collector.items():
        try:
            with _real_open(file_path, "r", encoding="utf-8") as f:
                original = f.read()
        except OSError:
            continue
        if original == new_content:
            continue
        has_changes = True
        diff = difflib.unified_diff(
            original.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=file_path,
            tofile=file_path + " (after --fix)",
        )
        sys.stdout.writelines(diff)
        sys.stdout.write("\n")

    if has_changes:
        console.print(
            f"[bold yellow]\n{result.fixable_count} fixable issue(s) across {len(diff_collector)} file(s).[/bold yellow]"
        )
        console.print("[dim]Run with --fix to apply these changes.[/dim]")
        sys.exit(1)
    else:
        console.print("[bold green]No changes would be applied by --fix.[/bold green]")
        sys.exit(0)


def main():
    """CLI entry point. Orchestrates subcommand dispatch, early exits,
    config loading, file discovery, analysis, and output rendering.
    """
    # Load installed-and-trusted plugins once per process. Done before
    # subcommand dispatch so plugin rules are visible to `senpy rule list`,
    # `senpy inspect`, and the main lint loop alike. Idempotent: subsequent
    # calls inside subcommand dispatch are no-ops. Safe: a broken plugin is
    # skipped with a warning, never crashes the linter.
    from senpy.plugins.autoload import autoload_plugins

    autoload_plugins()

    # Subcommand dispatch (e.g. `senpy format ...`)
    sub_exit = _dispatch_subcommand(sys.argv)
    if sub_exit is not None:
        return sub_exit

    # Parse CLI arguments
    args = parse_args()

    # Early exits: --version, --lsp, --rules, --rule, --traceback, --init-ci, --coverage, --clear-cache
    config = load_config(args.path)
    is_tsundere = args.tsundere or config.get("tsundere", False)
    early_exit = _handle_early_exits(args, console, is_tsundere)
    if early_exit is not None:
        return early_exit

    # Validate flag combinations (--fix + --check → error, etc.)
    # Done after early exits (so --version / --rules skip validation) but
    # before any analysis work (so we don't waste time on an invalid run).
    #
    # We use sys.exit() rather than `return validation_error` because the
    # `senpy` console_script wrapper in some Python versions does not
    # propagate the int return value of main() to the OS exit code —
    # SystemExit is the only reliable way to set a non-zero exit code from
    # a console_scripts entry point. Other early-exits in `_handle_early_exits`
    # follow the same pattern (sys.exit(0), sys.exit(_ec)).
    validation_error = _validate_flag_combinations(args, console)
    if validation_error is not None:
        sys.exit(validation_error)

    # Set up rule filtering (ignored_codes + max_errors)
    ignored_codes, max_errors = _setup_rule_filters(args, config)

    # File discovery (.rpy files, .rpyc orphans, .rpa extraction, decompile)
    extra_rpy_files = discover_files(args, config, args.path)

    is_quiet_mode = bool(
        args.graph
        or args.graph_file
        or args.stats
        or args.output_format in ("json", "sarif", "junit", "github", "rdjson", "gitlab")
    )

    if not is_quiet_mode:
        _print_scan_banner(args, console, is_tsundere)

    # --diff: monkey-patch builtins.open to capture what --fix would write
    # TODO(0.6.6): move into analyzer.run() via dry-run callback
    diff_collector, _real_open = _setup_diff_interception(args)

    # Run analysis
    result, analyzer, elapsed = _run_analysis(args, extra_rpy_files, is_quiet_mode)

    # Restore open() after --diff monkey-patch
    if args.diff:
        import builtins

        builtins.open = _real_open

    # Post-analysis output handlers (--stats, --export-wiki, --export-html, --graph, --defaults, --stubs)
    _handle_post_analysis(args, analyzer, result, console, is_tsundere, ignored_codes, elapsed)

    # Filter diagnostics by --ignore/--select/--errors-only/--info
    active_diagnostics, hidden_info_count = filter_diagnostics(result, args, ignored_codes)

    # Output format dispatch (sarif/json/junit/github exit directly, text continues)
    _handle_output_format(args, active_diagnostics, result, elapsed, console, ignored_codes)

    # --output-file for text format: redirect console to file
    output_redirect = (
        _replace_console(_make_file_console(args))
        if (args.output_file and args.output_format == "text")
        else _null_redirect()
    )

    # --check dry-run: print fixable count and exit
    _handle_check_mode(args, result, console)

    # --diff dry-run: print unified diff and exit
    _handle_diff_mode(args, diff_collector, result, console, _real_open)

    # Text output (default): render diagnostic cards + summary table + fixable report
    with output_redirect:
        _exit_with_output_redirect(
            args,
            render_text(
                active_diagnostics,
                hidden_info_count,
                result,
                args,
                console,
                is_tsundere,
                elapsed,
                max_errors,
            ),
        )


if __name__ == "__main__":
    main()
