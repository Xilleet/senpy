"""Handler for `senpy format` subcommand.

Extracted from cli/main.py in 0.6.4 to reduce god-function `_dispatch_format`
(117 lines) into a dedicated module. The function is re-exported from cli/main.py
as `_dispatch_format` for backward compatibility.

Usage:
    senpy format [PATHS...] [OPTIONS]

Options:
    --check              Don't write files, exit 1 if changes needed (CI-friendly)
    --diff               Print unified diff, don't write files
    --stdin-filename NAME  Read from stdin, format, write to stdout
    --help, -h           Show help
"""

from __future__ import annotations

import argparse
import difflib
import sys
from dataclasses import dataclass
from pathlib import Path

from senpy.formatter.core import FormatConfig, Formatter


def dispatch_format(argv: list[str]) -> int:
    """Handle `senpy format` subcommand.

    Args:
        argv: Arguments after `format` (e.g. ["--check", "script.rpy"]).

    Returns:
        Exit code: 0 on success, 1 if --check/--diff found changes needed.
    """
    args = _build_format_parser().parse_args(argv)
    formatter = Formatter(FormatConfig())

    if args.stdin_filename:
        return _format_stdin(formatter, args.stdin_filename)

    rpy_files = _collect_rpy_files(args.paths)
    if not rpy_files:
        print("[yellow]No .rpy files found.[/yellow]")
        return 0

    stats = _process_files(rpy_files, formatter, check=args.check, diff=args.diff)
    return _print_format_summary(stats, check=args.check, diff=args.diff)


def _build_format_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the `senpy format` subcommand."""
    parser = argparse.ArgumentParser(
        prog="senpy format",
        description="Format .rpy files (Black-style). Idempotent, low-risk, Ren'Py-specific.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to format (default: current dir)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Don't write files, exit 1 if any file would be modified (CI-friendly)",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="Print diff of what would be changed, don't write files",
    )
    parser.add_argument(
        "--stdin-filename",
        metavar="NAME",
        help="Read from stdin, format, print to stdout. NAME is used for scope detection.",
    )
    return parser


def _format_stdin(formatter: Formatter, filename: str) -> int:
    """Read stdin, format, write to stdout. Always exits 0."""
    code = sys.stdin.read()
    formatted = formatter.format_code(code, filename=filename)
    sys.stdout.write(formatted)
    return 0


def _collect_rpy_files(paths: list[str]) -> list[Path]:
    """Collect `.rpy` files from given paths (files + directories).

    Non-`.rpy` files and non-existent paths are skipped with a warning.
    """
    rpy_files: list[Path] = []
    for p_str in paths:
        p = Path(p_str)
        if p.is_file() and p.suffix == ".rpy":
            rpy_files.append(p)
        elif p.is_dir():
            rpy_files.extend(p.rglob("*.rpy"))
        else:
            print(f"[yellow]Skipping (not a .rpy file/dir): {p}[/yellow]")
    return rpy_files


@dataclass(slots=True)
class _FormatStats:
    """Counters for the format summary."""

    changed: int = 0  # files actually written
    would_change: int = 0  # files that would change (check/diff mode)


def _process_files(
    files: list[Path], formatter: Formatter, *, check: bool, diff: bool
) -> _FormatStats:
    """Format each file in `files`. In `check`/`diff` mode, count what would
    change without writing. Otherwise, write the formatted content back.
    """
    stats = _FormatStats()
    for f in files:
        try:
            original = f.read_text(encoding="utf-8")
        except OSError as e:
            print(f"[red]Error reading {f}: {e}[/red]")
            continue

        formatted = formatter.format_code(original, filename=str(f))
        if original == formatted:
            continue  # already formatted

        if check:
            stats.would_change += 1
            print(f"[yellow]Would reformat:[/yellow] {f}")
        elif diff:
            _print_diff(original, formatted, f)
            stats.would_change += 1
        else:
            try:
                f.write_text(formatted, encoding="utf-8")
                stats.changed += 1
                print(f"[green]Formatted:[/green] {f}")
            except OSError as e:
                print(f"[red]Error writing {f}: {e}[/red]")
    return stats


def _print_diff(original: str, formatted: str, f: Path) -> None:
    """Print a unified diff between `original` and `formatted` to stdout."""
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        formatted.splitlines(keepends=True),
        fromfile=str(f),
        tofile=str(f),
    )
    sys.stdout.writelines(diff)


def _print_format_summary(stats: _FormatStats, *, check: bool, diff: bool) -> int:
    """Print the summary line and return the exit code.

    In `check`/`diff` mode: exit 1 if any file would change, 0 if all clean.
    Otherwise: exit 0 always (writes are best-effort).
    """
    if check or diff:
        if stats.would_change > 0:
            print(
                f"\n[bold yellow]{stats.would_change} file(s) would be reformatted.[/bold yellow]"
            )
            return 1
        print("\n[bold green]All files are already formatted![/bold green]")
        return 0

    if stats.changed > 0:
        print(f"\n[bold green]{stats.changed} file(s) formatted.[/bold green]")
    else:
        print("\n[bold green]All files are already formatted![/bold green]")
    return 0
