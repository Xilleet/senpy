"""Output renderers for the Senpy CLI.

Extracted from ``senpy.cli.main``.

Public surface (all re-exported via ``senpy.cli.main`` for back-compat):
  - :func:`render_sarif`   — SARIF (GitHub Code Scanning)
  - :func:`render_rdjson`  — Reviewdog NDJSON
  - :func:`render_gitlab`  — GitLab Code Quality JSON
  - :func:`render_json`    — plain JSON for VS Code
  - :func:`render_junit`   — JUnit XML for CI
  - :func:`render_github`  — GitHub Actions workflow commands
  - :func:`render_text`    — default human-readable output (cards + table)

Each ``render_*`` function returns the exit code (0 / 1) without calling
``sys.exit`` — the caller (``senpy.cli.runner._handle_output_format``)
decides how to surface it. ``render_text`` orchestrates four private
helpers (``_render_diagnostic_cards``, ``_render_summary_table``,
``_render_fixable_report``, ``_render_summary_line``) plus the
:func:`_xml_escape` helper used by the JUnit path.

The :data:`SEVERITY_STYLES` mapping also lives here — it is consumed by
``_render_diagnostic_cards`` and ``_render_summary_table`` only.
"""

from __future__ import annotations

import json
import os
from collections import Counter

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from senpy.domain.tsundere import TSUNDERE_FLAVORS, TSUNDERE_UI

__all__ = [
    "SEVERITY_STYLES",
    "render_sarif",
    "render_rdjson",
    "render_gitlab",
    "render_json",
    "render_junit",
    "render_github",
    "_xml_escape",
    "_render_diagnostic_cards",
    "_render_summary_table",
    "_render_fixable_report",
    "_render_summary_line",
    "render_text",
]


SEVERITY_STYLES = {
    "ERROR": ("bold red", "red dim"),
    "WARNING": ("bold yellow", "yellow dim"),
    "HINT": ("bold cyan", "cyan dim"),
    "INFO": ("bold blue", "blue dim"),
}


def render_sarif(active_diagnostics, args, console) -> int:
    """Renders diagnostics in SARIF format. Returns the exit code (does not call sys.exit).

    Extracted from main() in 0.5.6.
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
    return _exit_code(args, error_count)


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
    return _exit_code(args, error_count)


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
    return _exit_code(args, error_count)


def render_json(active_diagnostics, result, elapsed, args, console) -> int:
    """Renders diagnostics in JSON format. Returns the exit code (does not call sys.exit).

    Extracted from main() in 0.5.6.
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
    return _exit_code(args, error_count)


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
                    f'type="{_xml_escape(diag.code)}">line {diag.line_number}: '
                    f"{_xml_escape(diag.line_content.strip())}</failure>"
                )
            elif diag.severity == "WARNING":
                lines.append(
                    f'      <skipped message="{_xml_escape(diag.message)}" '
                    f'type="{_xml_escape(diag.code)}">line {diag.line_number}</skipped>'
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
    return _exit_code(args, error_count)


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
    return _exit_code(args, error_count)


def _xml_escape(text: str) -> str:
    """Escape special XML characters for JUnit output."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _exit_code(args, error_count: int) -> int:
    """Compute the CLI exit code from diagnostics + ``--exit-zero`` flag.

    ``--exit-zero`` is a documented CLI contract for non-blocking CI runs
    (nightly reports, informational scans): the run always exits 0 even with
    ERROR diagnostics, so the job does not fail the workflow. Every output
    format must honour this flag — previously only ``render_text`` did, the
    other six renderers returned ``1 if error_count > 0 else 0`` unconditionally.

    Note: this only covers the diagnostics→exit-code path. A separate
    ``failed_writes`` signal (``--fix`` could not write the file back) is
    OR'd into the exit code by ``runner._force_nonzero_if_failed_writes``
    — that signal is orthogonal to ``--exit-zero`` and is NOT suppressed
    by it (silent data loss must remain detectable regardless of the
    exit-zero mode).
    """
    if getattr(args, "exit_zero", False):
        return 0
    return 1 if error_count > 0 else 0


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

    # --exit-zero forces exit 0 even with errors (for non-blocking CI).
    # Same contract as every other renderer (see _exit_code).
    return _exit_code(args, error_count)
