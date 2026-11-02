"""File discovery: .rpy files, .rpyc orphans, .rpa archives.

Extracted from `senpy/cli/main.py` in 0.7.4 so that `senpy inspect`
(and other future subcommands) can reuse the same file-discovery
pipeline without coupling to the main CLI's argparse Namespace.

The only behavioral change from the original main.py code is the
`interactive: bool = True` parameter on `discover_files` and
`_decompile_sandbox`. When `interactive=False` (used by `senpy inspect`),
the decompile prompt is suppressed — the function silently skips
decompilation unless `--decompile` was explicitly passed or
`config['decompile']` is set. This keeps `senpy inspect` deterministic
(no `input()` call that would hang in a piped / CI environment).
"""

from __future__ import annotations

import os
import sys

from rich.console import Console

from senpy.cli.unrpyc import (
    decompile_to_sandbox,
    extract_scripts_from_rpa,
    find_unrpyc_executable,
)
from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.constants import IGNORED_DIRS

# A separate Console instance for discover's interactive prompts.
# `legacy_windows=False` is correct here because discover is invoked
# from the main CLI (which already has its own console for non-prompt
# output) and from `senpy inspect` (which uses stdout for JSON, so any
# prompt must go to stderr via the legacy renderer).
_console = Console(legacy_windows=sys.stdout.isatty())


def _find_rpy_files(project_path: str) -> tuple[set[str], set[str]]:
    """Walk project_path and find all .rpy files.

    Returns:
        Tuple of (relative_paths, basenames) for deduplication.
        - relative_paths: set of relative paths (e.g. "game/script.rpy")
        - basenames: set of just filenames (e.g. "script.rpy")
    """
    relative_paths: set[str] = set()
    basenames: set[str] = set()
    for root, dirs, files in os.walk(project_path, followlinks=False):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for f in files:
            if f.endswith(".rpy"):
                full_path = os.path.join(root, f)
                try:
                    rel = os.path.relpath(full_path, project_path)
                except ValueError:
                    rel = f
                relative_paths.add(rel)
                basenames.add(f)
    return relative_paths, basenames


def _find_orphaned_rpyc(
    args,
    raw_orphans: list[str],
    rpa_sandbox: str,
    existing_rpy_basenames: set[str],
) -> tuple[list[str], list[str]]:
    """Find orphaned .rpyc files + extract scripts from .rpa archives.

    Returns:
        Tuple of (extra_rpy_files, updated_raw_orphans):
        - extra_rpy_files: .rpy files extracted from RPA archives
        - updated_raw_orphans: original raw_orphans + .rpyc from RPA archives
    """
    extra_rpy_files: list[str] = []
    updated_orphans = list(raw_orphans)

    # Find .rpa archives
    rpa_files: list[str] = []
    for root, dirs, files in os.walk(args.path, followlinks=False):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for f in files:
            if f.lower().endswith(".rpa"):
                rpa_files.append(os.path.join(root, f))

    # Extract scripts from each .rpa
    for rpa in rpa_files:
        rpa_base = os.path.splitext(os.path.basename(rpa))[0].lower()
        # Extract if archive looks like main game archive OR if no orphans yet
        if (
            any(term in rpa_base for term in ("script", "archive", "data", "game", "code"))
            or not raw_orphans
        ):
            extracted = extract_scripts_from_rpa(rpa, rpa_sandbox)
            for item in extracted:
                base_name = os.path.basename(item)
                rpy_name = base_name[:-1] if base_name.endswith(".rpyc") else base_name
                if rpy_name not in existing_rpy_basenames:
                    if item.endswith(".rpy"):
                        extra_rpy_files.append(item)
                    elif item.endswith(".rpyc"):
                        updated_orphans.append(item)

    return extra_rpy_files, updated_orphans


def _decompile_sandbox(
    orphaned_rpyc: list[str],
    args,
    config: dict,
    decomp_sandbox: str,
    *,
    interactive: bool = True,
) -> list[str]:
    """Decompile orphaned .rpyc files into sandbox.

    Prompts user (if `interactive=True` and stdin is a TTY and neither
    `--decompile` nor config says yes) or uses the `--decompile` flag /
    `config['decompile']` setting. When `interactive=False`, the prompt
    is suppressed — only explicit `--decompile` or `config['decompile']`
    triggers decompilation. This is used by `senpy inspect` to keep its
    output deterministic (no `input()` call that would hang in a piped
    or CI environment).

    Returns list of decompiled .rpy file paths.
    """
    if not orphaned_rpyc:
        return []

    # When interactive=False (senpy inspect), ignore config['decompile']
    # to keep inspect deterministic. Only honor explicit --decompile flag.
    if interactive:
        should_decompile = config.get("decompile", False) or args.decompile
    else:
        should_decompile = args.decompile
    is_interactive_tty = interactive and hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
    if (
        not should_decompile
        and is_interactive_tty
        and not (args.graph or args.graph_file or args.stats)
    ):
        _console.print(
            f"[bold yellow]Found {len(orphaned_rpyc)} compiled .rpyc file(s) without source code.[/bold yellow]"
        )
        try:
            answer = input("Decompile them into a sandbox for analysis? [y/N]: ").strip().lower()
            should_decompile = answer in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            should_decompile = False

    if not should_decompile:
        return []

    custom_unrpyc = args.unrpyc or config.get("unrpyc_path")
    unrpyc_cmd = find_unrpyc_executable(custom_unrpyc, args.path, auto_download=is_interactive_tty)
    if not unrpyc_cmd:
        return []

    return decompile_to_sandbox(orphaned_rpyc, unrpyc_cmd, decomp_sandbox)


def discover_files(
    args,
    config: dict,
    project_path: str,
    *,
    interactive: bool = True,
) -> list[str]:
    """Find .rpy files, .rpyc orphans, extract RPA, decompile .rpyc.

    Orchestrates 3 helpers:
      1. _find_rpy_files — existing .rpy files for dedup
      2. _find_orphaned_rpyc — .rpyc orphans + RPA extraction
      3. _decompile_sandbox — decompile orphans into sandbox

    Returns list of extra_rpy_files (paths to .rpy from RPA/decompilation).

    Args:
        args: argparse Namespace with `path`, `decompile`, `unrpyc`,
            `graph`, `graph_file`, `stats` attributes (used by helpers).
        config: Senpy config dict (from `load_config`).
        project_path: Absolute path to the project root.
        interactive: When True (default, used by `senpy [PATH]`), may
            prompt the user to decompile orphaned .rpyc files. When
            False (used by `senpy inspect`), never prompts — only
            decompiles if `--decompile` or `config['decompile']` is set.
    """
    decomp_sandbox = os.path.join(os.path.abspath(args.path), ".senpy_cache", "decompiled")
    rpa_sandbox = os.path.join(os.path.abspath(args.path), ".senpy_cache", "rpa_extracted")
    os.makedirs(decomp_sandbox, exist_ok=True)
    os.makedirs(rpa_sandbox, exist_ok=True)

    raw_orphans = list(SenpyAnalyzer.find_orphaned_rpyc(args.path))

    # 1. Find existing .rpy files for dedup
    _, existing_rpy_basenames = _find_rpy_files(args.path)

    # 2. Find .rpyc orphans + extract RPA scripts
    extra_rpy_files, raw_orphans = _find_orphaned_rpyc(
        args, raw_orphans, rpa_sandbox, existing_rpy_basenames
    )

    # 3. Sync: add extracted .rpy basenames to existing set
    for f in extra_rpy_files:
        existing_rpy_basenames.add(os.path.basename(f))

    # 4. Cache check: use cached .rpy if fresh, else queue for decompile
    orphaned_rpyc: list[str] = []
    for rpyc in raw_orphans:
        rpy_name = os.path.basename(rpyc)[:-1]
        if rpy_name in existing_rpy_basenames:
            continue
        cached_rpy = os.path.join(decomp_sandbox, rpy_name)
        if os.path.exists(cached_rpy) and os.path.getmtime(cached_rpy) >= os.path.getmtime(rpyc):
            if cached_rpy not in extra_rpy_files:
                extra_rpy_files.append(cached_rpy)
        else:
            if rpyc not in orphaned_rpyc:
                orphaned_rpyc.append(rpyc)

    # 5. Decompile orphans
    new_decompiled = _decompile_sandbox(
        orphaned_rpyc,
        args,
        config,
        decomp_sandbox,
        interactive=interactive,
    )
    for f_rpy in new_decompiled:
        if f_rpy not in extra_rpy_files:
            extra_rpy_files.append(f_rpy)

    return extra_rpy_files
