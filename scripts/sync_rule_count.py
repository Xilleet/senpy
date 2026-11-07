#!/usr/bin/env python3
"""Sync rule count across all documentation files.

Reads the actual rule count from ``RULES_DATABASE`` and replaces stale
counts in every documentation file. This avoids manually editing 30+
files every time a new rule is added.

Patterns replaced (case-insensitive where appropriate):
  - ``N rules`` / ``N Rules`` / ``N правил`` (total count, not per-category)
  - ``N/N rules`` (e.g. ``51/51 rules`` → ``52/52 rules``)
  - ``List all N available Senpy rules``
  - ``title: All Senpy Rules — N Rules Across 8 Categories``
  - ``table of all N rules`` / ``list all N rules``

Does NOT touch:
  - Per-category counts in parentheses (e.g. ``RPY1xx (10 rules)``).
  - CHANGELOG.md (historical record).

Files scanned:
  - README.md, README_ru.md, RULES.md, ARCHITECTURE.md, SECURITY.md
  - docs/**/*.md
  - senpy/cli/args.py
  - senpy-vscode/README.md

Usage:
    python scripts/sync_rule_count.py            # sync (update files)
    python scripts/sync_rule_count.py --check     # exit 1 if stale

Exit codes:
    0 — all files up to date (or successfully updated)
    1 — --check mode found stale files
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files to scan. Excludes CHANGELOG.md (historical, should not be rewritten).
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

# Replacements: (regex, replacement)
# Each regex matches a stale count and the replacement uses {count}.
# We use negative lookbehind/lookahead to avoid matching per-category
# counts in parentheses like "(10 rules)" or "(8 rules)".
PATTERNS = [
    # "all 52 rules" / "all 51 rules" — total count after "all"
    (re.compile(r"\ball\s+(\d{1,3})\s+rules\b", re.IGNORECASE), "all {count} rules"),
    # "all 52 Rules" — title case
    (re.compile(r"\ball\s+(\d{1,3})\s+Rules\b"), "all {count} Rules"),
    # "52 rules" / "51 rules" NOT inside parentheses — total count
    # Case-insensitive but preserves "Rules" (title-case) via a separate pattern.
    # Negative lookbehind for `(` and `(N/` to avoid per-category counts.
    (re.compile(r"(?<!\()\b(\d{1,3})\s+rules\b(?!\s*\))"), "{count} rules"),
    # "52 Rules" — title case only (e.g. in headings)
    (re.compile(r"(?<!\()\b(\d{1,3})\s+Rules\b(?!\s*\))"), "{count} Rules"),
    # "52 правил" — Russian
    (re.compile(r"(?<!\()\b(\d{1,3})\s+правил\b(?!\s*\))"), "{count} правил"),
    # "52/52 rules" → "52/52 rules"
    (re.compile(r"\b(\d{1,3})/(\d{1,3})\s+rules\b"), "{count}/{count} rules"),
    # "List all 52 available Senpy rules"
    (
        re.compile(r"List all\s+(\d{1,3})\s+available\s+Senpy\s+rules", re.IGNORECASE),
        "List all {count} available Senpy rules",
    ),
    # "title: All Senpy Rules — 52 Rules Across 8 Categories"
    (
        re.compile(r"(title:\s*All\s+Senpy\s+Rules\s+—\s+)\d{1,3}(\s+Rules\s+Across)"),
        r"\g<1>{count}\g<2>",
    ),
    # "52 rule" (singular)
    (re.compile(r"(?<!\()\b(\d{1,3})\s+rule\b(?!\s*s)", re.IGNORECASE), "{count} rule"),
    # "52 available" in args.py help text
    (
        re.compile(r"List all\s+(\d{1,3})\s+available\s+Senpy\s+rules\s+and", re.IGNORECASE),
        "List all {count} available Senpy rules and",
    ),
    # "table of all 52 rules" in docs/cli-reference.md
    (re.compile(r"table of all\s+(\d{1,3})\s+rules", re.IGNORECASE), "table of all {count} rules"),
    # "52 Rules Across 8 Categories" in title (case-sensitive for title)
    (
        re.compile(r"(\d{1,3})\s+Rules\s+Across\s+8\s+Categories"),
        "{count} Rules Across 8 Categories",
    ),
    # "52 правила" in README_ru.md (singular Russian form)
    (re.compile(r"из\s+(\d{1,3})\s+правила\b"), "из {count} правила"),
]


def get_actual_rule_count() -> int:
    """Get the actual rule count from RULES_DATABASE."""
    from senpy.rules.rules_info import RULES_DATABASE

    return len(RULES_DATABASE)


def collect_files() -> list[Path]:
    """Collect all files to scan, excluding CHANGELOG.md and .git."""
    files: set[Path] = set()
    for pattern in SCAN_GLOBS:
        for path in REPO_ROOT.glob(pattern):
            if not path.is_file():
                continue
            if path.name == "CHANGELOG.md":
                continue
            if ".git" in path.parts:
                continue
            if "node_modules" in path.parts:
                continue
            files.add(path)
    return sorted(files)


def sync_file(filepath: Path, new_count: int, dry_run: bool = False) -> bool:
    """Sync rule count in a single file. Returns True if file was changed."""
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
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if any file has a stale rule count.",
    )
    args = parser.parse_args()

    actual_count = get_actual_rule_count()
    print(f"Actual rule count from RULES_DATABASE: {actual_count}")

    files = collect_files()
    changed_files: list[Path] = []

    for filepath in files:
        if sync_file(filepath, actual_count, dry_run=args.check):
            changed_files.append(filepath)

    if not changed_files:
        print(f"All {len(files)} files are up to date (count={actual_count}).")
        return 0

    if args.check:
        print(f"\nSTALE: {len(changed_files)} file(s) have an outdated rule count:")
        for f in changed_files:
            print(f"  {f.relative_to(REPO_ROOT)}")
        print("\nRun `python scripts/sync_rule_count.py` to fix.")
        return 1

    print(f"\nUpdated {len(changed_files)} file(s):")
    for f in changed_files:
        print(f"  {f.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
