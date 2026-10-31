"""Handler for `senpy format` subcommand.

Extracted from cli/main.py in 0.6.4 (ARCH-4) to reduce god-function `_dispatch_format`
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
from pathlib import Path

from senpy.formatter.core import FormatConfig, Formatter


def dispatch_format(argv: list[str]) -> int:
    """Handle `senpy format` subcommand.

    Args:
        argv: Arguments after `format` (e.g. ["--check", "script.rpy"]).

    Returns:
        Exit code: 0 on success, 1 if --check/--diff found changes needed.
    """
    fmt_parser = argparse.ArgumentParser(
        prog="senpy format",
        description="Format .rpy files (Black-style). Idempotent, low-risk, Ren'Py-specific.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    fmt_parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to format (default: current dir)",
    )
    fmt_parser.add_argument(
        "--check",
        action="store_true",
        help="Don't write files, exit 1 if any file would be modified (CI-friendly)",
    )
    fmt_parser.add_argument(
        "--diff",
        action="store_true",
        help="Print diff of what would be changed, don't write files",
    )
    fmt_parser.add_argument(
        "--stdin-filename",
        metavar="NAME",
        help="Read from stdin, format, print to stdout. NAME is used for scope detection.",
    )

    fmt_args = fmt_parser.parse_args(argv)
    formatter = Formatter(FormatConfig())

    # Stdin mode: read from stdin, write to stdout, exit 0
    if fmt_args.stdin_filename:
        code = sys.stdin.read()
        formatted = formatter.format_code(code, filename=fmt_args.stdin_filename)
        sys.stdout.write(formatted)
        return 0

    # Collect .rpy files from given paths (files + directories)
    rpy_files: list[Path] = []
    for p_str in fmt_args.paths:
        p = Path(p_str)
        if p.is_file() and p.suffix == ".rpy":
            rpy_files.append(p)
        elif p.is_dir():
            rpy_files.extend(p.rglob("*.rpy"))
        else:
            print(f"[yellow]Skipping (not a .rpy file/dir): {p}[/yellow]")

    if not rpy_files:
        print("[yellow]No .rpy files found.[/yellow]")
        return 0

    changed_count = 0
    would_change_count = 0

    for f in rpy_files:
        try:
            original = f.read_text(encoding="utf-8")
        except OSError as e:
            print(f"[red]Error reading {f}: {e}[/red]")
            continue

        formatted = formatter.format_code(original, filename=str(f))

        if original == formatted:
            continue  # already formatted

        if fmt_args.check:
            would_change_count += 1
            print(f"[yellow]Would reformat:[/yellow] {f}")
        elif fmt_args.diff:
            diff = difflib.unified_diff(
                original.splitlines(keepends=True),
                formatted.splitlines(keepends=True),
                fromfile=str(f),
                tofile=str(f),
            )
            sys.stdout.writelines(diff)
            would_change_count += 1
        else:
            try:
                f.write_text(formatted, encoding="utf-8")
                changed_count += 1
                print(f"[green]Formatted:[/green] {f}")
            except OSError as e:
                print(f"[red]Error writing {f}: {e}[/red]")

    # Summary output
    if fmt_args.check or fmt_args.diff:
        if would_change_count > 0:
            print(
                f"\n[bold yellow]{would_change_count} file(s) would be reformatted.[/bold yellow]"
            )
            return 1
        print("\n[bold green]All files are already formatted![/bold green]")
        return 0

    if changed_count > 0:
        print(f"\n[bold green]{changed_count} file(s) formatted.[/bold green]")
    else:
        print("\n[bold green]All files are already formatted![/bold green]")
    return 0
