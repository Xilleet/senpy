"""`senpy inspect` subcommand — WL-506.

Parallel mini-CLI (like `senpy format`) that shares only the
`SenpyAnalyzer` engine with the main lint CLI. Does NOT share the
main parser, render functions, or post-analysis pipeline.

Usage:
    senpy inspect [PATH]              # full JSON to stdout
    senpy inspect game/ -o dump.json  # full JSON to file
    senpy inspect game/ --summary     # only stats
    senpy inspect game/ --unresolved  # only unresolved
    senpy inspect game/ --label X     # .labels[X] (auto --with-source)
    senpy inspect game/ --screen X    # .screens[X]
    senpy inspect game/ --transform X # .transforms[X]
    senpy inspect game/ --no-cache   # cold run
    senpy inspect game/ --with-source # include code_line for all
    senpy inspect game/ --decompile  # also decompile .rpyc/.rpa
    senpy inspect game/ --unrpyc P   # custom unrpyc path

Output is JSON, sorted keys, indent=2, ensure_ascii=False (for Cyrillic
in Russian dialogue strings). Determinism is important for future
snapshot-style regression testing.
"""

from __future__ import annotations

import argparse
import json
import sys

from senpy.cli.discover import discover_files
from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.config import load_config
from senpy.formats.inspect import dump_symbols


def dispatch_inspect(argv: list[str]) -> int:
    """Handle `senpy inspect [...]` — parse argv, run, emit JSON.

    Args:
        argv: Arguments after the `inspect` subcommand (e.g.
            `["game/", "--summary"]` for `senpy inspect game/ --summary`).

    Returns:
        Exit code: 0 on success, 1 on error (e.g. label not found with
        an explicit error code if we add that in the future).
    """
    args = _build_inspect_parser().parse_args(argv)
    config = load_config(args.path)

    # Build a minimal Namespace compatible with discover_files (which
    # expects `path`, `decompile`, `unrpyc`, `graph`, `graph_file`,
    # `stats` attributes from the main CLI's argparse).
    #
    # IMPORTANT: inspect intentionally does NOT honor `config['decompile']`.
    # The main CLI honors it because the user explicitly invoked lint and
    # likely wants the project analyzed as fully as possible. `inspect`,
    # however, must be deterministic: the same `senpy inspect PATH` command
    # must produce the same JSON regardless of any `senpy.toml` settings
    # that happen to live in PATH or its ancestors. Otherwise a project's
    # `decompile = true` would silently trigger decompilation (and its
    # noisy stdout from unrpyc's progress printer: "[Preparing] 1/1 ...",
    # "[Decompiling] 1/1 ...") every time someone runs
    # `senpy inspect PATH | jq`, polluting the JSON.
    #
    # Decompile is opt-in for inspect: pass `--decompile` explicitly.
    # `--unrpyc` still honors `config['unrpyc_path']` because that's a
    # pure configuration (which unrpyc to use), not a behavior toggle.
    discover_args = argparse.Namespace(
        path=args.path,
        decompile=args.decompile,  # NOT config.get("decompile", False)
        unrpyc=args.unrpyc or config.get("unrpyc_path"),
        graph=False,
        graph_file=False,
        stats=False,
    )

    # inspect is deterministic: never prompt. interactive=False suppresses
    # the "Decompile them into a sandbox?" prompt that the main CLI shows.
    extra_rpy_files = discover_files(
        discover_args,
        config,
        args.path,
        interactive=False,
    )

    analyzer = SenpyAnalyzer(
        args.path,
        extra_files=extra_rpy_files,
        no_cache=args.no_cache,
    )
    analyzer.run(quiet=True)

    # Auto-enable --with-source for single-symbol lookups.
    with_source = args.with_source or any((args.label, args.screen, args.transform))

    data = dump_symbols(analyzer, with_source=with_source)
    output = _apply_filter(data, args)
    return _emit(output, args)


def _build_inspect_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for `senpy inspect`."""
    parser = argparse.ArgumentParser(
        prog="senpy inspect",
        description=(
            "Dump all symbols Senpy sees in a project (JSON). "
            "Useful for debugging hover, asset resolution, and lint "
            "behavior. Output is JSON; pipe through `jq` to filter."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  senpy inspect game/ | jq '.labels | length'\n"
            "  senpy inspect game/ --summary\n"
            "  senpy inspect game/ --unresolved\n"
            "  senpy inspect game/ --label start\n"
        ),
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Project directory to inspect (default: current dir)",
    )
    # Shortcut filters (mutually compatible: only one applies at a time
    # because they target different sub-trees of the dump).
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print only the `stats` section (quick overview)",
    )
    parser.add_argument(
        "--unresolved",
        action="store_true",
        help="Print only the `unresolved` section (broken jumps, etc.)",
    )
    parser.add_argument(
        "--label",
        metavar="NAME",
        help="Print details of one label (auto-enables --with-source)",
    )
    parser.add_argument(
        "--screen",
        metavar="NAME",
        help="Print details of one screen (auto-enables --with-source)",
    )
    parser.add_argument(
        "--transform",
        metavar="NAME",
        help="Print details of one transform (auto-enables --with-source)",
    )
    # Source inclusion.
    parser.add_argument(
        "--with-source",
        action="store_true",
        help="Include `code_line`/`body` for each symbol (default: omit)",
    )
    # Cache.
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Cold run (no cache read). For debugging fresh state.",
    )
    # Decompile / unrpyc.
    parser.add_argument(
        "--decompile",
        action="store_true",
        help="Also decompile .rpyc / extract .rpa (default: honor config)",
    )
    parser.add_argument(
        "--unrpyc",
        metavar="PATH",
        help="Custom path to unrpyc (default: from config or vendored)",
    )
    # Output.
    parser.add_argument(
        "-o",
        "--output-file",
        metavar="FILE",
        help="Write JSON to FILE instead of stdout",
    )
    return parser


def _apply_filter(data: dict, args) -> object:
    """Apply shortcut filters based on args. Return the sub-object to emit."""
    if args.summary:
        return data["stats"]
    if args.unresolved:
        return data["unresolved"]
    if args.label is not None:
        return data["labels"].get(args.label)
    if args.screen is not None:
        return data["screens"].get(args.screen)
    if args.transform is not None:
        return data["transforms"].get(args.transform)
    return data


def _emit(payload: object, args) -> int:
    """Serialize `payload` to JSON and write to stdout or file.

    Returns exit code (0 always on successful serialization).
    """
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)

    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        # Silent on stdout when -o is used (so `senpy inspect game/ -o x | jq`
        # doesn't get polluted with a "Wrote x" notice).
        return 0

    sys.stdout.write(text + "\n")
    return 0
