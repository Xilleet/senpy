#!/usr/bin/env python3
"""Sync rule count across all documentation files.

Reads the actual rule count from RULES_DATABASE and replaces stale
counts in every documentation file.

Design: uses ONLY specific, high-context patterns to avoid false
positives. Each pattern matches a known phrase — never a bare
"N rules" which would match formatter counts, per-category counts,
and other numbers.

Usage:
    python scripts/sync_rule_count.py            # sync (update files)
    python scripts/sync_rule_count.py --check     # exit 1 if stale
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SCAN_GLOBS = [
    "README.md",
    "README_ru.md",
    "RULES.md",
    "ARCHITECTURE.md",
    "SECURITY.md",
    "docs/**/*.md",
    "senpy/cli/args.py",
    "senpy-vscode/README.md",
]

# Each entry: (regex, replacement_template)
# ALL patterns are case-sensitive — no re.IGNORECASE.
# Patterns match specific phrases, not bare "N rules".
PATTERNS = [
    # "52 Rules Across 8 Categories"
    (re.compile(r"\d{1,3}(\s+Rules\s+Across\s+8\s+Categories)"), r"{count}\1"),
    # "All Senpy Rules — 52 Rules Across"
    (re.compile(r"(All\s+Senpy\s+Rules\s+—\s+)\d{1,3}(\s+Rules\s+Across)"), r"\g<1>{count}\g<2>"),
    # "All 52 rules" — case-sensitive
    (re.compile(r"\bAll\s+\d{1,3}\s+rules\b"), r"All {count} rules"),
    # "all 52 rules" — case-sensitive
    (re.compile(r"\ball\s+\d{1,3}\s+rules\b"), r"all {count} rules"),
    # "RULES_DATABASE (52 rules"
    (re.compile(r"(RULES_DATABASE\s*\()\s*\d{1,3}(\s+rules)"), r"\g<1>{count}\g<2>"),
    # "includes **52 rules**"
    (re.compile(r"(includes\s+\*{2})\d{1,3}(\s+rules\s*\*{2})"), r"\g<1>{count}\g<2>"),
    # "table of all 52 rules"
    (re.compile(r"(table of all\s+)\d{1,3}(\s+rules)"), r"\g<1>{count}\g<2>"),
    # "list all 52 rules"
    (re.compile(r"(list all\s+)\d{1,3}(\s+rules)"), r"\g<1>{count}\g<2>"),
    # "List all 52 available Senpy rules"
    (re.compile(r"(List all\s+)\d{1,3}(\s+available\s+Senpy\s+rules)"), r"\g<1>{count}\g<2>"),
    # "prints a table of all 52 rules"
    (re.compile(r"(prints a table of all\s+)\d{1,3}(\s+rules)"), r"\g<1>{count}\g<2>"),
    # "52/52 rules"
    (re.compile(r"\d{1,3}/\d{1,3}(\s+rules)"), r"{count}/{count}\1"),
    # "52 rules, runs on every keystroke"
    (re.compile(r"\d{1,3}(\s+rules,\s+runs\s+on\s+every\s+keystroke)"), r"{count}\1"),
    # "same 52 rules" — NOT across newlines
    (re.compile(r"(same[ \t]+)\d{1,3}([ \t]+rules)"), r"\g<1>{count}\g<2>"),
    # "52 rules across 8 categories"
    (re.compile(r"\d{1,3}(\s+rules\s+across\s+8\s+categories)"), r"{count}\1"),
    # "of all 52 rules"
    (re.compile(r"(of all\s+)\d{1,3}(\s+rules)"), r"\g<1>{count}\g<2>"),
    # "for all 52 rules"
    (re.compile(r"(for all\s+)\d{1,3}(\s+rules)"), r"\g<1>{count}\g<2>"),
    # Russian: "52 правил" (NOT in parentheses)
    (re.compile(r"(?<!\()\b\d{1,3}(\s+правил\b)(?!\s*\))"), r"{count}\1"),
    # "из 52 правила"
    (re.compile(r"(из\s+)\d{1,3}(\s+правила\b)"), r"\g<1>{count}\g<2>"),
    # "[all 52 rules]" in markdown links
    (re.compile(r"(\[all\s+)\d{1,3}(\s+rules\])"), r"\g<1>{count}\g<2>"),
    # "[All 52 rules]" in markdown links
    (re.compile(r"(\[All\s+)\d{1,3}(\s+rules\])"), r"\g<1>{count}\g<2>"),
    # "see the same 52 rules"
    (re.compile(r"(see the same\s+)\d{1,3}(\s+rules)"), r"\g<1>{count}\g<2>"),
]


def get_actual_rule_count() -> int:
    from senpy.rules.rules_info import RULES_DATABASE

    return len(RULES_DATABASE)


def collect_files() -> list[Path]:
    files: set[Path] = set()
    for pattern in SCAN_GLOBS:
        for path in REPO_ROOT.glob(pattern):
            if not path.is_file():
                continue
            if path.name == "CHANGELOG.md":
                continue
            if ".git" in path.parts or "node_modules" in path.parts:
                continue
            files.add(path)
    return sorted(files)


def sync_file(filepath: Path, new_count: int, dry_run: bool = False) -> bool:
    try:
        content = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False

    original = content
    for regex, template in PATTERNS:
        replacement = template.format(count=new_count)
        content = regex.sub(replacement, content)

    if content == original:
        return False

    if not dry_run:
        filepath.write_text(content, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync rule count in documentation.")
    parser.add_argument("--check", action="store_true", help="Exit 1 if stale.")
    args = parser.parse_args()

    actual_count = get_actual_rule_count()
    print(f"Actual rule count from RULES_DATABASE: {actual_count}")

    files = collect_files()
    changed: list[Path] = []

    for filepath in files:
        if sync_file(filepath, actual_count, dry_run=args.check):
            changed.append(filepath)

    if not changed:
        print(f"All {len(files)} files are up to date (count={actual_count}).")
        return 0

    if args.check:
        print(f"\nSTALE: {len(changed)} file(s) have an outdated rule count:")
        for f in changed:
            print(f"  {f.relative_to(REPO_ROOT)}")
        print("\nRun `python scripts/sync_rule_count.py` to fix.")
        return 1

    print(f"\nUpdated {len(changed)} file(s):")
    for f in changed:
        print(f"  {f.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
