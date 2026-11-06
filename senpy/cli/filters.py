"""Diagnostic filtering for the Senpy CLI.

Extracted from ``senpy.cli.main``. This module
is a **leaf**: it only depends on the standard library (``os``) and on
``senpy.rules.rules_info`` + ``senpy.core.models`` — never on another
``senpy.cli.*`` module, so it cannot create a CLI-internal cycle.

Public surface:
  - :func:`load_senpy_ignore` — reads ``.senpy-ignore`` from the project root
  - :func:`filter_diagnostics` — applies all CLI filters and returns the
    active diagnostics plus the count of INFO notices that were hidden

The five ``_build_*`` / ``_count_*`` / ``_filter_*`` helpers are private
to this module but re-exported via ``senpy.cli.main`` for backward
compatibility with existing tests that poke at the internals.
"""

from __future__ import annotations

import os

__all__ = [
    "load_senpy_ignore",
    "filter_diagnostics",
    "_build_select_codes",
    "_build_full_ignored",
    "_build_tag_filters",
    "_count_hidden_info",
    "_filter_active",
]


def load_senpy_ignore(project_path: str) -> set[str]:
    """Reads the .senpy-ignore file from the project root.

    The file contains one rule code per line. Supported formats:
      - Full-line comments (line starts with `#`).
      - Inline comments (`RPY101 # typo in dialogue`).
      - Empty lines.
      - Case-insensitive (normalized to uppercase).

    Args:
        project_path: Path to the project root (where .senpy-ignore is located).

    Returns:
        Set of rule codes (uppercase) to exclude. Empty set if the
        file does not exist or is empty.

    Example file:
        # .senpy-ignore
        RPY101  # typo in dialogue variable
        RPY104
        # RPY105  # commented out — rule will fire
        RPY301
    """
    ignore_file = os.path.join(project_path, ".senpy-ignore")
    if not os.path.isfile(ignore_file):
        return set()

    codes: set[str] = set()
    try:
        with open(ignore_file, encoding="utf-8", errors="replace") as f:
            for line in f:
                # Remove the inline comment (everything after #)
                line = line.split("#", 1)[0]
                code = line.strip().upper()
                if code:
                    codes.add(code)
    except OSError:
        # Could not read — silently return an empty set.
        # DEBUG-level logging is already present in load_config.
        pass

    return codes


def filter_diagnostics(
    result,
    args,
    ignored_codes: set[str],
) -> tuple[list, int]:
    """Filters diagnostics by --ignore, --select, --tag, --ignore-tag, --errors-only, --info."""
    select_codes = _build_select_codes(args)
    full_ignored = _build_full_ignored(ignored_codes, args)
    wanted_tags, ignored_tags = _build_tag_filters(args)

    from senpy.rules.rules_info import RULES_DATABASE

    def _passes_tag_filters(code: str) -> bool:
        info = RULES_DATABASE.get(code)
        rule_tags = {t.lower() for t in info.get("tags", [])} if info else set()
        if wanted_tags is not None and not (rule_tags & wanted_tags):
            return False
        return not (ignored_tags and (rule_tags & ignored_tags))

    hidden_info_count = _count_hidden_info(
        result.diagnostics, full_ignored, select_codes, _passes_tag_filters, args.info
    )
    active_diagnostics = _filter_active(
        result.diagnostics, full_ignored, select_codes, _passes_tag_filters, args
    )
    return active_diagnostics, hidden_info_count


def _build_select_codes(args) -> set[str]:
    """Build the whitelist from --select + --extend-select."""
    select_codes: set[str] = set()
    if getattr(args, "select", None):
        select_codes.update(c.strip().upper() for c in args.select)
        if getattr(args, "extend_select", None):
            select_codes.update(c.strip().upper() for c in args.extend_select)
    return select_codes


def _build_full_ignored(ignored_codes: set[str], args) -> set[str]:
    """Combine ignored_codes with --extend-ignore."""
    full_ignored = set(ignored_codes)
    if getattr(args, "extend_ignore", None):
        full_ignored.update(c.strip().upper() for c in args.extend_ignore)
    return full_ignored


def _build_tag_filters(args) -> tuple[set[str] | None, set[str]]:
    """Extract --tag (whitelist) and --ignore-tag (blacklist) from args."""
    wanted_tags: set[str] | None = None
    if getattr(args, "tag", None):
        wanted_tags = {t.lower() for t in args.tag}
    ignored_tags: set[str] = set()
    if getattr(args, "ignore_tag", None):
        ignored_tags = {t.lower() for t in args.ignore_tag}
    return wanted_tags, ignored_tags


def _count_hidden_info(
    diagnostics: list,
    full_ignored: set[str],
    select_codes: set[str],
    passes_tag_filters,
    show_info: bool,
) -> int:
    """Count INFO-severity diagnostics that are filtered out (for the 'use --info' message)."""
    return sum(
        1
        for e in diagnostics
        if e.severity == "INFO"
        and e.code not in full_ignored
        and (not select_codes or e.code in select_codes)
        and passes_tag_filters(e.code)
        and not show_info
    )


def _filter_active(
    diagnostics: list,
    full_ignored: set[str],
    select_codes: set[str],
    passes_tag_filters,
    args,
) -> list:
    """Apply all filters to produce the active diagnostics list."""
    return [
        e
        for e in diagnostics
        if e.code not in full_ignored
        and (not select_codes or e.code in select_codes)
        and passes_tag_filters(e.code)
        and (not args.errors_only or e.severity == "ERROR")
        and (args.info or e.severity != "INFO")
    ]
