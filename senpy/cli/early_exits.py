"""Early-exit paths for the Senpy CLI.

Extracted from ``senpy.cli.main``.

Public surface (all re-exported via ``senpy.cli.main`` for back-compat):
  - :func:`_dispatch_subcommand` — checks ``sys.argv`` for a subcommand
    (``senpy format``, ``senpy inspect``, ``senpy rule``) and dispatches
    to the matching ``dispatch_*`` function. Returns ``None`` if no
    subcommand matched so the caller can continue with the lint flow.
  - :func:`_handle_early_exits` — handles ``--version``, ``--lsp``,
    ``--rules``, ``--rule``, ``--traceback``, ``--init-ci``, ``--coverage``,
    ``--clear-cache``, ``--trust-plugin``, ``--untrust-plugin`` and
    ``--show-settings``. Returns the exit code if the run is over,
    ``None`` otherwise.
  - :func:`_validate_flag_combinations` — validates ``--fix``/``--check``/
    ``--diff``/``--select``/``--add-noqa`` combinations after parsing.

Dependencies: ``senpy.cli.commands`` (the handler functions) plus a
handful of lazy imports for rarely-used dispatchers (LSP server, rule
table, plugin trust store, format/inspect/rule subcommands). No imports
from :mod:`senpy.cli.main`, :mod:`senpy.cli.runner`, or
:mod:`senpy.cli.renderers` — this module is strictly below them in the
import graph.
"""

from __future__ import annotations

import sys

from rich.console import Console

from senpy.cli.commands import (
    handle_clear_cache,
    handle_coverage,
    handle_init_ci,
    handle_traceback,
)

__all__ = [
    "_dispatch_subcommand",
    "_handle_early_exits",
    "_validate_flag_combinations",
]


def _dispatch_subcommand(argv: list[str]) -> int | None:
    """Check for subcommand (e.g. `senpy format`) and dispatch.

    Returns exit code if subcommand was dispatched, None otherwise.
    """
    # Subcommand registry — extensible for future subcommands (check, lsp, graph, ci, clean)
    if len(argv) > 1 and argv[1] == "format":
        # Delegated to senpy.cli.format_dispatch (extracted in 0.6.4).
        # The back-compat wrapper `senpy.cli.main._dispatch_format` exists
        # for callers that import it directly; here we go straight to the
        # implementation to avoid an early_exits -> main edge in the
        # static import graph (scripts/check_cycles.py).
        from senpy.cli.format_dispatch import dispatch_format

        return dispatch_format(argv[2:])
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
        # Honor --config FILE (and SENPY_CONFIG env var) the same way
        # SenpyAnalyzer does — without this, --show-settings bypassed
        # the config_path wiring from P1-5 and showed the default config
        # even when the user passed --config (N1 post-0.8.3 fix).
        config = load_config(project_path, config_path=getattr(args, "config", None))
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

    # --fail-on-error says "exit 1 on ERROR"; --exit-zero says "always exit 0".
    # They contradict — the user almost certainly meant one or the other.
    # Default behavior (neither flag) is already "exit 1 on ERROR", so
    # --fail-on-error only makes the contract explicit; --exit-zero opts out.
    if getattr(args, "fail_on_error", False) and getattr(args, "exit_zero", False):
        console.print(
            "[bold red]Error:[/bold red] --fail-on-error and --exit-zero cannot be "
            "used together. --fail-on-error exits 1 on any ERROR; --exit-zero always "
            "exits 0. The default behavior (no flags) is already 'fail on ERROR' — "
            "use --exit-zero only for non-blocking runs."
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
