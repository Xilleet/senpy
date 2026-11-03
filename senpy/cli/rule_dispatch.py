"""`senpy rule` subcommand — rule metadata browser.

Provides machine-readable (JSON) and human-readable (Rich tables/panels)
access to the RULES_DATABASE without running the analyzer. Useful for
CI scripts that need to enumerate rules, plugin authors who want to
know which tags exist, and editor integrations that want to populate
autocomplete.

Usage:
    senpy rule list                                # text table of all rules
    senpy rule list --format json                  # machine-readable
    senpy rule list --tag rollback                 # filter by tag (union)
    senpy rule list --tag audio --tag images       # multiple tags = union
    senpy rule list --severity ERROR               # filter by severity
    senpy rule list -o rules.json                  # write to file
    senpy rule show RPY104                         # detail panel
    senpy rule show RPY104 --format json           # machine-readable detail
    senpy rule show rpy104                         # case-insensitive

Backward compatibility: the existing `--rules` and `--rule CODE` flags
on the main CLI continue to work (early-exit in _handle_early_exits).
This subcommand is the recommended replacement — it adds --format json,
--tag, --severity, and -o (output file) which the old flags lack.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from senpy.rules.rules_info import RULES_DATABASE

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def _filter_rules(
    *,
    tags: list[str] | None = None,
    severity: str | None = None,
) -> list[dict[str, Any]]:
    """Return a sorted list of rule dicts (with `code` field) matching filters.

    `tags` is a union filter: a rule passes if ANY of its tags is in the
    requested list. `severity` is an exact match (case-insensitive).
    """
    if tags:
        wanted_tags = {t.lower() for t in tags}
    else:
        wanted_tags = None
    if severity:
        wanted_sev = severity.upper()
    else:
        wanted_sev = None

    out: list[dict[str, Any]] = []
    for code, info in sorted(RULES_DATABASE.items()):
        if wanted_tags is not None:
            rule_tags = {t.lower() for t in info.get("tags", [])}
            if not (rule_tags & wanted_tags):
                continue
        if wanted_sev is not None and info["severity"].upper() != wanted_sev:
            continue
        out.append(_rule_to_dict(code, info))
    return out


def _rule_to_dict(code: str, info: dict[str, Any]) -> dict[str, Any]:
    """Convert a RULES_DATABASE entry to a JSON-serializable dict.

    The `code` field is added (it's the dict key in RULES_DATABASE, not
    a value, so we have to inject it explicitly for JSON output).
    """
    return {
        "code": code,
        "title": info["title"],
        "severity": info["severity"],
        "tags": list(info.get("tags", [])),
        "why": info["why"],
        "bad": info["bad"],
        "good": info["good"],
    }


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _render_list_text(rules: list[dict[str, Any]]) -> str:
    """Render a Rich table as a string (no console side-effects).

    We build the table manually (instead of capturing Console output)
    so the function is pure and testable. The format mirrors
    show_rules_table() in rules_info.py.
    """
    lines: list[str] = []
    lines.append(f"Senpy Linter Rules Reference ({len(rules)} rule(s))")
    lines.append("")
    lines.append(f"{'Rule':<8}  {'Severity':<8}  {'Tags':<32}  Description")
    lines.append(f"{'-' * 8}  {'-' * 8}  {'-' * 32}  {'-' * 40}")
    for r in rules:
        tags_str = ", ".join(r["tags"])
        if len(tags_str) > 32:
            tags_str = tags_str[:29] + "..."
        title = r["title"]
        if len(title) > 40:
            title = title[:37] + "..."
        lines.append(f"{r['code']:<8}  {r['severity']:<8}  {tags_str:<32}  {title}")
    lines.append("")
    lines.append("Run 'senpy rule show <CODE>' for detailed explanation and examples.")
    return "\n".join(lines) + "\n"


def _render_show_text(rule: dict[str, Any]) -> str:
    """Render a single rule's detail as plain text (mirrors show_rule_detail)."""
    lines: list[str] = []
    lines.append(f"{rule['code']}: {rule['title']}")
    lines.append(f"Severity: {rule['severity']}")
    if rule["tags"]:
        lines.append(f"Tags: {', '.join(rule['tags'])}")
    lines.append("")
    lines.append(rule["why"])
    lines.append("")
    lines.append("BAD PRACTICE:")
    lines.append(rule["bad"])
    lines.append("")
    lines.append("GOOD PRACTICE:")
    lines.append(rule["good"])
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _emit(text: str, args) -> int:
    """Write text to stdout or to args.output_file. Return 0."""
    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(text)
        return 0
    sys.stdout.write(text)
    return 0


def _emit_json(payload: Any, args) -> int:
    """Serialize payload to JSON and write to stdout or file. Return 0."""
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        return 0
    sys.stdout.write(text + "\n")
    return 0


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def _handle_list(args) -> int:
    rules = _filter_rules(tags=args.tag, severity=args.severity)
    if args.format == "json":
        return _emit_json(rules, args)
    return _emit(_render_list_text(rules), args)


def _handle_show(args) -> int:
    code = args.code.upper()
    if code not in RULES_DATABASE:
        sys.stderr.write(
            f"Unknown rule code: '{args.code}'. "
            f"Run 'senpy rule list' to see all available rules.\n"
        )
        return 1
    rule = _rule_to_dict(code, RULES_DATABASE[code])
    if args.format == "json":
        return _emit_json(rule, args)
    return _emit(_render_show_text(rule), args)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for `senpy rule`."""
    parser = argparse.ArgumentParser(
        prog="senpy rule",
        description=(
            "Browse Senpy rule metadata. List rules (with tag/severity "
            "filters) or show details for one rule. Output as text or JSON."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  senpy rule list\n"
            "  senpy rule list --format json -o rules.json\n"
            "  senpy rule list --tag rollback\n"
            "  senpy rule list --severity ERROR\n"
            "  senpy rule show RPY104\n"
            "  senpy rule show RPY104 --format json\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=False)

    # `list` subcommand
    list_p = subparsers.add_parser(
        "list",
        help="List all rules (or filtered subset) as a table or JSON array",
    )
    list_p.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    list_p.add_argument(
        "--tag",
        action="append",
        metavar="TAG",
        default=None,
        help=(
            "Filter rules by tag (any-tag match / union). "
            "Repeatable: --tag audio --tag images returns both groups."
        ),
    )
    list_p.add_argument(
        "--severity",
        choices=["ERROR", "WARNING", "HINT", "INFO"],
        default=None,
        help="Filter rules by severity (case-insensitive exact match)",
    )
    list_p.add_argument(
        "-o",
        "--output-file",
        metavar="FILE",
        help="Write output to FILE instead of stdout",
    )
    list_p.set_defaults(func=_handle_list)

    # `show` subcommand
    show_p = subparsers.add_parser(
        "show",
        help="Show detailed information for one rule (text panel or JSON)",
    )
    show_p.add_argument(
        "code",
        help="Rule code (e.g. RPY104). Case-insensitive.",
    )
    show_p.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    show_p.add_argument(
        "-o",
        "--output-file",
        metavar="FILE",
        default=None,
        help="Write output to FILE instead of stdout",
    )
    show_p.set_defaults(func=_handle_show)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def dispatch_rule(argv: list[str]) -> int:
    """Entry point for `senpy rule` subcommand.

    Returns exit code (0 = success, 1 = unknown rule, 2 = usage error).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "subcommand", None):
        # `senpy rule` with no subcommand → print help, exit non-zero.
        parser.print_help(sys.stderr)
        return 1

    return args.func(args)
