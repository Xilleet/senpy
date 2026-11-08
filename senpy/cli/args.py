"""Argparse builders for the Senpy CLI.

Extracted from ``senpy.cli.main``. This module
is a **leaf**: it only depends on the Python standard library (``argparse``)
so it can be imported by any other CLI module without creating cycles.

The single public entry point is :func:`parse_args`, which orchestrates
five argument-group helpers:

  1. :func:`_add_general_args` — ``--version``, positional ``path``
  2. :func:`_add_rules_args` — ``--rules``, ``--rule``
  3. :func:`_add_lint_args` — 16 analysis/autofix flags
  4. :func:`_add_export_args` — visualization & reports
  5. :func:`_add_tools_args` — LSP, CI, traceback, stubs, decompile, etc.

Backward compatibility:
    ``senpy.cli.main`` re-exports every name in this module, so existing
    callers (and tests) that did ``from senpy.cli.main import parse_args``
    keep working unchanged.
"""

from __future__ import annotations

import argparse

__all__ = [
    "_add_general_args",
    "_add_rules_args",
    "_add_lint_args",
    "_add_export_args",
    "_add_tools_args",
    "parse_args",
]


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
        help="List all 52 available Senpy rules and their descriptions",
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
        "--strict",
        action="store_true",
        help="Promote every diagnostic to ERROR severity, except those explicitly "
        "downgraded via [tool.senpy.severity] in senpy.toml. Same as setting "
        "`strict = true` in senpy.toml; the CLI flag overrides the config value. "
        "Useful for CI runs that must fail on any non-downgraded rule.",
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
        "--fail-on-error",
        action="store_true",
        help="Exit 1 if any ERROR-severity diagnostic is found (default behavior, "
        "made explicit for self-documenting CI scripts). Conflicts with --exit-zero. "
        "Useful alongside --strict to make the CI contract obvious in the command line.",
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
