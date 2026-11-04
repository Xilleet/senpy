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

    Sources are merged: built-in `RULES_DATABASE` first, then plugin rules
    discovered via `senpy.plugins.registry.get_registered_lint_rules()`. If a
    plugin registers a code that collides with a built-in (e.g. someone ships
    a plugin with `code="RPY001"`), the built-in wins — plugin is skipped
    with a warning. This prevents user confusion: the docs URL and `why/bad/good`
    for built-in rules must always point at the canonical built-in definition.
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
    seen_codes: set[str] = set()

    # 1. Built-in rules (canonical source — wins on code collisions).
    for code, info in sorted(RULES_DATABASE.items()):
        if wanted_tags is not None:
            rule_tags = {t.lower() for t in info.get("tags", [])}
            if not (rule_tags & wanted_tags):
                continue
        if wanted_sev is not None and str(info["severity"]).upper() != wanted_sev:
            continue
        out.append(_rule_to_dict(code, info))
        seen_codes.add(code)

    # 2. Plugin rules (only codes not already provided by built-ins).
    for plugin_dict in _plugin_rules():
        code = plugin_dict["code"]
        if code in seen_codes:
            # Plugin is shadowing a built-in code. Skip — built-in is the
            # canonical source for code/severity/docs/why/bad/good.
            continue
        if wanted_tags is not None:
            rule_tags = {t.lower() for t in plugin_dict.get("tags", [])}
            if not (rule_tags & wanted_tags):
                continue
        if wanted_sev is not None and plugin_dict["severity"].upper() != wanted_sev:
            continue
        out.append(plugin_dict)
        seen_codes.add(code)

    # Sort the merged result by rule code for stable output.
    out.sort(key=lambda r: r["code"])
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


def _plugin_rule_dict(code: str, rule_cls: type) -> dict[str, Any] | None:
    """Convert a plugin Rule subclass to a JSON-serializable dict.

    Plugin rules use `RuleMeta` (dataclass on `rule_cls.meta`), not the
    `RULES_DATABASE` dict. We adapt the meta into the same shape as built-in
    rule dicts so downstream renderers (text table, JSON output) can treat
    them uniformly.

    Returns None if the plugin rule is malformed (no meta, or meta missing
    required fields). Such rules are skipped silently — a broken plugin
    should not crash `senpy rule list`.

    Plugin rule dicts have `why`/`bad`/`good` set to placeholder strings
    (RuleMeta only carries `docs`, not full BAD/GOOD examples). The text
    renderer tolerates this; JSON consumers see `"why": "<plugin rule: see plugin docs>"`
    so they can disambiguate from built-in entries.
    """
    meta = getattr(rule_cls, "meta", None)
    if meta is None:
        return None

    # Required fields on RuleMeta (validated in __post_init__, but be defensive).
    meta_code = getattr(meta, "code", None)
    meta_severity = getattr(meta, "severity", None)
    if not meta_code or not meta_severity:
        return None

    docs = getattr(meta, "docs", "") or ""
    tags = list(getattr(meta, "tags", []) or [])

    return {
        "code": meta_code,
        "title": _plugin_title(rule_cls, docs),
        "severity": meta_severity,
        "tags": tags,
        # Plugin rules don't ship with the structured `why/bad/good` triple
        # that built-in RULES_DATABASE entries carry. Provide stable
        # placeholder strings so the JSON shape matches built-in entries
        # (consumers don't have to special-case missing keys).
        "why": docs or f"Plugin rule {meta_code} (see plugin documentation).",
        "bad": "(see plugin documentation)",
        "good": "(see plugin documentation)",
    }


def _plugin_title(rule_cls: type, docs: str) -> str:
    """Derive a human-readable title for a plugin rule.

    Heuristic: take the first sentence of `meta.docs`. If empty, fall back
    to the rule class name. This matches the brevity of built-in titles
    in `RULES_DATABASE` (e.g. "Tab character in indentation" for RPY001).
    """
    if docs:
        # First sentence = up to first '. ' or end of string.
        first_period = docs.find(". ")
        if first_period != -1 and first_period < 80:
            return docs[: first_period + 1]
        # No sentence break or very long — take first 80 chars.
        if len(docs) <= 80:
            return docs
        return docs[:77] + "..."
    return f"Plugin rule {rule_cls.__name__}"


def _plugin_rules() -> list[dict[str, Any]]:
    """Return plugin rule dicts currently registered in the lint rule registry.

    Reads `senpy.plugins.registry.get_registered_lint_rules()` and converts
    each (code, rule_cls) tuple into a JSON-serializable dict via
    `_plugin_rule_dict()`. Malformed entries are skipped (return None from
    `_plugin_rule_dict`).

    This function is the bridge between the plugin registry (which stores
    Rule subclasses) and the rule list/show output (which expects dicts
    with code/title/severity/tags/why/bad/good keys).
    """
    from senpy.plugins.registry import get_registered_lint_rules

    out: list[dict[str, Any]] = []
    for code, rule_cls in get_registered_lint_rules():
        rule_dict = _plugin_rule_dict(code, rule_cls)
        if rule_dict is not None:
            out.append(rule_dict)
    return out


def _find_plugin_rule(code: str) -> dict[str, Any] | None:
    """Look up a single plugin rule by code (case-sensitive on meta.code).

    Returns the rule dict (same shape as `_plugin_rule_dict`) or None if no
    plugin rule with that code is currently registered. Used by
    `senpy rule show <CODE>` to handle codes that aren't in built-in
    `RULES_DATABASE` (e.g. RPY901 from the example plugin).
    """
    for rule_dict in _plugin_rules():
        if rule_dict["code"] == code:
            return rule_dict
    return None


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
    # Built-in rules first (canonical source — wins on code collisions).
    if code in RULES_DATABASE:
        rule: dict[str, Any] = _rule_to_dict(code, RULES_DATABASE[code])
    else:
        # Fall back to plugin rules. Covers `senpy rule show RPY901` when
        # examples/my_senpy_plugin is installed and autoloaded.
        plugin_rule = _find_plugin_rule(code)
        if plugin_rule is None:
            sys.stderr.write(
                f"Unknown rule code: '{args.code}'. "
                f"Run 'senpy rule list' to see all available rules.\n"
            )
            return 1
        rule = plugin_rule
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
    # Make installed-and-trusted plugin rules visible in `senpy rule list/show`.
    # Idempotent: if `main()` already autoloaded plugins, this is a no-op.
    # Required here because tests call `dispatch_rule([...])` directly without
    # going through `main()` — otherwise plugin rules would be invisible
    # in unit tests, breaking parity with the real CLI.
    from senpy.plugins.autoload import autoload_plugins

    autoload_plugins()

    parser = _build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "subcommand", None):
        # `senpy rule` with no subcommand → print help, exit non-zero.
        parser.print_help(sys.stderr)
        return 1

    return args.func(args)
