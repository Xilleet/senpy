"""Main orchestrator for the Senpy CLI.

Extracted from ``senpy.cli.main``.

This module is the top of the CLI import graph — it pulls together
:mod:`senpy.cli.args`, :mod:`senpy.cli.filters`, :mod:`senpy.cli.renderers`,
:mod:`senpy.cli.early_exits`, :mod:`senpy.cli.discover` and
:mod:`senpy.cli.commands` to implement the full ``senpy`` lint flow.

Public surface (re-exported via ``senpy.cli.main`` for back-compat):
  - :func:`main` — the console-script entry point.

The console-redirect helpers (:class:`_ReplaceConsole`, :func:`_replace_console`,
:func:`_exit_with_output_redirect`, :func:`_make_file_console`,
:class:`_NullRedirect`, :func:`_null_redirect`) also live here because they
are only used by :func:`main`'s ``--output-file`` redirect block. They use
``global console`` to rebind the module-level ``console`` binding in this
module — which is exactly what :func:`main` sees when it does
``console.print(...)`` or passes ``console`` as a parameter to the
renderers and command handlers.

Back-compat note:
    ``senpy.cli.main`` re-exports every name below, so external callers
    that did ``from senpy.cli.main import main`` keep working unchanged.
"""

from __future__ import annotations

import os
import sys
import time

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from senpy.cli._console import console
from senpy.cli.args import parse_args
from senpy.cli.commands import (
    handle_defaults,
    handle_export_html,
    handle_export_wiki,
    handle_graph,
    handle_stats,
    handle_stubs,
)
from senpy.cli.discover import discover_files
from senpy.cli.early_exits import (
    _dispatch_subcommand,
    _handle_early_exits,
    _validate_flag_combinations,
)
from senpy.cli.filters import filter_diagnostics, load_senpy_ignore
from senpy.cli.renderers import (
    render_github,
    render_gitlab,
    render_json,
    render_junit,
    render_rdjson,
    render_sarif,
    render_text,
)
from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.config import load_config
from senpy.domain.tsundere import TSUNDERE_UI
from senpy.formats.traceback import find_latest_traceback, parse_traceback_file

__all__ = [
    "_ReplaceConsole",
    "_replace_console",
    "_exit_with_output_redirect",
    "_make_file_console",
    "_NullRedirect",
    "_null_redirect",
    "_setup_rule_filters",
    "_print_scan_banner",
    "_run_analysis",
    "_handle_post_analysis",
    "_handle_output_format",
    "_handle_check_mode",
    "_handle_diff_mode",
    "main",
]


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


def _apply_noqa_comments(diagnostics, analyzer) -> list[str]:
    """Append ``# noqa: RPYxxx`` comments to source files for every diagnostic.

    For each diagnostic in ``diagnostics``, appends ``# noqa: RPYxxx``
    (where ``xxx`` is the diagnostic's rule code) to the end of the
    offending line in the source ``.rpy`` file. Multiple diagnostics on
    the same line are merged into one ``# noqa: RPY101, RPY104``
    directive.

    Idempotent: lines that already have a ``# noqa`` directive for a
    given code are not duplicated — the code is added to the existing
    directive if missing.

    Files are written back via the analyzer's ``_write_fixed_file``
    pipeline (same path as ``--fix``), so OSError on read-only files is
    logged at WARNING and recorded in ``analyzer.failed_writes`` — the
    caller (``runner.main``) surfaces failed writes via the existing
    ``_print_failed_writes_summary`` + ``_force_nonzero_if_failed_writes``
    path added in the ``--fix`` OSError fix.

    Args:
        diagnostics: List of ``Diagnostic`` objects from
            ``AnalysisResult.diagnostics``. Only ``file_path``,
            ``line_number`` and ``code`` are used.
        analyzer: ``SenpyAnalyzer`` instance — used to access
            ``_pipeline._write_fixed_file`` and ``failed_writes``.

    Returns:
        List of file paths that were written to disk. Empty list if
        no diagnostics (no-op).
    """
    if not diagnostics:
        return []

    # Group diagnostics by (file_path, line_number) → set of codes.
    # Using a set avoids duplicate codes on the same line.
    import re
    from collections import defaultdict

    from senpy.core.file_collector import parse_noqa
    from senpy.core.logging import get_logger

    logger = get_logger("cli")
    noqa_re = re.compile(r"#\s*noqa:\s*([^\n#]*)", re.IGNORECASE)

    # {file_path: {line_number: set of codes}}
    by_file: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    for diag in diagnostics:
        if not diag.code or not diag.file_path or diag.line_number < 1:
            continue
        by_file[diag.file_path][diag.line_number].add(diag.code)

    written_files: list[str] = []
    for file_path, lines_to_codes in by_file.items():
        try:
            with open(file_path, encoding="utf-8", newline="") as f:
                lines = f.readlines()
        except OSError as e:
            logger.warning("Failed to read %s for --add-noqa: %s", file_path, e)
            analyzer.failed_writes.append(file_path)
            continue

        modified = False
        for line_no, codes in lines_to_codes.items():
            # line_no is 1-indexed; lines is 0-indexed.
            idx = line_no - 1
            if idx >= len(lines):
                continue
            original_line = lines[idx]

            # Check if the line already has a # noqa directive.
            # parse_noqa is imported at the top of this function.
            has_noqa, existing_codes = parse_noqa(original_line)
            codes_to_add = codes if existing_codes is None else codes - existing_codes
            if not codes_to_add:
                # All codes already present in the existing directive.
                continue

            # Strip the trailing newline so we can append the directive
            # before re-adding the newline.
            stripped = original_line.rstrip("\r\n")
            line_ending = original_line[len(stripped) :]

            if has_noqa and existing_codes is not None:
                # Merge into the existing directive: append the new codes
                # to the comma-separated list inside `# noqa: ...`.
                # noqa_re is compiled once at the top of this function.
                merged_codes = sorted(existing_codes | codes_to_add)
                merged_str = ", ".join(merged_codes)
                # Use a lambda with default argument to bind merged_str at
                # definition time (avoids B023: closure over loop variable).
                new_line = (
                    noqa_re.sub(
                        lambda _m, s=merged_str: f"# noqa: {s}",
                        stripped,
                        count=1,
                    )
                    + line_ending
                )
            elif has_noqa and existing_codes is None:
                # Bare `# noqa` (suppress all) — nothing to add, it
                # already suppresses everything. Skip.
                continue
            else:
                # No existing noqa — append a new directive.
                # Format: `  # noqa: RPY101` (two spaces before # for
                # readability, matching the convention used in the
                # project's own source files).
                # Sort codes for deterministic output.
                codes_str = ", ".join(sorted(codes_to_add))
                # Preserve any trailing whitespace before the newline by
                # appending after the stripped content.
                new_line = f"{stripped}  # noqa: {codes_str}{line_ending}"

            if new_line != original_line:
                lines[idx] = new_line
                modified = True

        if modified:
            analyzer._pipeline._write_fixed_file(file_path, lines)
            written_files.append(file_path)

    return written_files


def _run_analysis(args, extra_rpy_files, is_quiet_mode: bool, dry_run_callback=None):
    """Run SenpyAnalyzer with appropriate fix/no_cache settings.

    Args:
        dry_run_callback: If set, passed to ``analyzer.run()`` so that
            ``_write_fixed_file`` calls the callback instead of writing
            to disk. Used by ``--diff`` mode (T-032/T-033) to capture
            what ``--fix`` would write without modifying files.

    Returns:
        Tuple of (result, analyzer, elapsed_seconds).
    """
    # --check: fix=False (don't modify, just count fixable_count)
    # --diff: fix=True (analyzer prepares changes, dry_run_callback captures)
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
    result = analyzer.run(quiet=is_quiet_mode, dry_run_callback=dry_run_callback)
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


def _force_nonzero_if_failed_writes(exit_code: int, had_failed_writes: bool) -> int:
    """Force exit code 1 if any ``--fix`` write failed.

    Without this, ``senpy --fix`` on a read-only file reports a successful
    run (exit 0) while the file on disk is unchanged. ``_write_fixed_file``
    already logs the warning and records the path in
    ``AnalysisResult.failed_writes`` — this helper turns that signal into a
    non-zero exit code so CI can detect the silent failure.
    """
    if had_failed_writes and exit_code == 0:
        return 1
    return exit_code


def _print_failed_writes_summary(result, console, is_quiet_mode: bool) -> bool:
    """Print a summary of files ``--fix`` could not write back.

    Returns True if any failed writes were recorded. ``is_quiet_mode`` is
    True for non-text output formats (sarif / json / junit / github /
    rdjson / gitlab) — in that case the warning still goes to ``console``
    but the rich-formatted summary is suppressed so machine-readable output
    stays clean.
    """
    failed = list(getattr(result, "failed_writes", []))
    if not failed:
        return False
    if not is_quiet_mode:
        console.print(f"[bold red]Failed to write fixes to {len(failed)} file(s):[/bold red]")
        for path in failed:
            console.print(f"  [red]- {path}[/red]")
    return True


def _handle_output_format(
    args,
    active_diagnostics,
    result,
    elapsed,
    console,
    ignored_codes,
    had_failed_writes: bool = False,
):
    """Dispatch output by format: sarif/json/junit/github/rdjson/gitlab exit directly,
    text format returns control to caller for further processing.

    ``had_failed_writes`` forces exit code 1 if any ``--fix`` write failed —
    a successful fix on a read-only file is a silent data loss that CI must
    be able to detect. The flag is OR'd with the format's own exit code so
    that a project with diagnostics still exits 1 (not 2).
    """
    if args.output_format == "sarif":
        exit_code = render_sarif(active_diagnostics, args, console)
    elif args.output_format == "json":
        exit_code = render_json(active_diagnostics, result, elapsed, args, console)
    elif args.output_format == "junit":
        exit_code = render_junit(active_diagnostics, args, console)
    elif args.output_format == "github":
        exit_code = render_github(active_diagnostics, args, console)
    elif args.output_format == "rdjson":
        exit_code = render_rdjson(active_diagnostics, args, console)
    elif args.output_format == "gitlab":
        exit_code = render_gitlab(active_diagnostics, args, console)
    else:
        # text format — caller handles output_redirect + render_text
        return

    sys.exit(_force_nonzero_if_failed_writes(exit_code, had_failed_writes))


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


def _handle_diff_mode(args, diff_collector, result, console) -> int | None:
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
            with open(file_path, encoding="utf-8") as f:
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
    # Initialize logging BEFORE anything else. autoload_plugins (next)
    # emits WARNING records for broken/skipped plugins, and config
    # loading logs TOMLDecodeError warnings — without setup_logging,
    # these hit Python's lastResort handler (a _StderrHandler at
    # WARNING level) and write to stderr. In LSP mode stderr is the
    # JSON-RPC transport, so unsilenced WARNINGs corrupt the protocol.
    # verbose=False installs a NullHandler: records are swallowed
    # silently. Use --verbose (when wired, see P3-1) for stderr output.
    from senpy.core.logging import setup_logging

    setup_logging(verbose=False)

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

    # --diff: capture what --fix would write via dry_run_callback (T-032).
    # The analyzer calls the callback instead of open(), so files on disk
    # are NOT modified. This replaces the old builtins.open monkey-patch.
    diff_collector: dict[str, str] = {}
    dry_run_callback = None
    if args.diff:

        def dry_run_callback(file_path: str, lines: list[str]) -> None:
            diff_collector[file_path] = "".join(lines)

    # Run analysis
    result, analyzer, elapsed = _run_analysis(
        args, extra_rpy_files, is_quiet_mode, dry_run_callback=dry_run_callback
    )

    # Surface --fix failures: if any file could not be written back (read-only,
    # permission denied, disk full), the user must know — otherwise the run
    # looks successful while the fixes were silently dropped. The warning
    # is logged per-file in _write_fixed_file; here we print a concise summary
    # and remember the flag so the final exit code can be forced to non-zero.
    had_failed_writes = _print_failed_writes_summary(result, console, is_quiet_mode)

    # --add-noqa: append `# noqa: RPYxxx` comments to source files for every
    # diagnostic, so the next run suppresses them. Writes files back via the
    # same _write_fixed_file pipeline as --fix, so failed writes surface
    # through the existing failed_writes path (already handled above + the
    # exit-code force below). Runs BEFORE --check/--diff/text output so the
    # output reflects the pre-suppression state (user sees what was suppressed).
    if args.add_noqa:
        _apply_noqa_comments(result.diagnostics, analyzer)
        # Refresh had_failed_writes — _apply_noqa_comments may have added
        # new failures (read-only files, etc.) via _write_fixed_file.
        had_failed_writes = (
            _print_failed_writes_summary(result, console, is_quiet_mode) or had_failed_writes
        )

    # Post-analysis output handlers (--stats, --export-wiki, --export-html, --graph, --defaults, --stubs)
    _handle_post_analysis(args, analyzer, result, console, is_tsundere, ignored_codes, elapsed)

    # Filter diagnostics by --ignore/--select/--errors-only/--info
    active_diagnostics, hidden_info_count = filter_diagnostics(result, args, ignored_codes)

    # Output format dispatch (sarif/json/junit/github exit directly, text continues)
    _handle_output_format(
        args,
        active_diagnostics,
        result,
        elapsed,
        console,
        ignored_codes,
        had_failed_writes=had_failed_writes,
    )

    # --output-file for text format: redirect console to file
    output_redirect = (
        _replace_console(_make_file_console(args))
        if (args.output_file and args.output_format == "text")
        else _null_redirect()
    )

    # --check dry-run: print fixable count and exit
    _handle_check_mode(args, result, console)

    # --diff dry-run: print unified diff and exit
    _handle_diff_mode(args, diff_collector, result, console)

    # Text output (default): render diagnostic cards + summary table + fixable report.
    # If --fix could not write some files, force exit 1 even when there are no
    # diagnostics — a successful fix on a read-only file is silent data loss.
    with output_redirect:
        _exit_with_output_redirect(
            args,
            _force_nonzero_if_failed_writes(
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
                had_failed_writes,
            ),
        )


if __name__ == "__main__":
    main()
