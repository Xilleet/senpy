#!/usr/bin/env python3
"""CLEAN-1: scrub internal task IDs from user-facing files.

The Senpy worklog uses internal IDs (DOC-1, CLI-17, LSP-19, QUA-12,
ARCH-3, EXT-12, SEC-6, RULE-15, FMT-2, FIX-1, TEST-6, IDEA-9, PERF-3,
SEO-13, CLEAN-1, AUD-001, ECO-9, SSA-1, STUDIO-1, WL-506, etc.) as task
identifiers — that is fine INSIDE the worklog file itself. But during
0.6.2-0.6.3 these IDs leaked into code comments, docstrings, the
CHANGELOG, README, CONTRIBUTING, and other user-facing artifacts.

This script scrubs the IDs from every file except:
  - CHANGELOG.md (historical changelog entries — IDs are part of the
    release narrative and removing them would erase context)
  - Senpy_Consolidated_Backlog_*.md (the worklog itself — IDs are the
    intended reference mechanism there)
  - senpy/vendor/** (vendored unrpyc — third-party code, do not touch)
  - .git/**, node_modules/**, build artifacts

Cleanup strategies per context (auto-detected per line):
  1. Comment / docstring prefix: ``# ECO-9: версия...`` → ``# версия...``
     The ID plus a single trailing colon-space pair is stripped.
  2. Bare ID mention mid-sentence: ``After ARCH-1 it will:`` → ``After the
     refactor it will:``. Hard to do safely with a regex — instead we
     strip the ID plus one trailing space (so "After ARCH-1 it" becomes
     "After it"). The user is expected to read these in --dry-run mode
     and flag any awkward results.
  3. Inside string literals: ``"Senpy-LSP-21-fetcher"`` → ``"Senpy-fetcher"``.
     Same regex as above — the ID plus one trailing dash is stripped.
  4. As a commit-message prefix in scripts: ``"ECO-4: pin unrpyc..."``
     → ``"pin unrpyc..."``. Same as case 1.

Usage:
    python scripts/clean_internal_ids.py --dry-run    # show diff, write nothing
    python scripts/clean_internal_ids.py --apply      # write changes
    python scripts/clean_internal_ids.py --apply --paths senpy/ tests/  # restrict

Exit code 0 always (unless --help). The script never deletes files, never
removes lines entirely — only edits ID occurrences in place.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Pattern: ID-NNNN[a-z?]?, e.g. DOC-1, CLI-17, LSP-19, QUA-12, AUD-001,
# DOC-8a, ARCH-22. We match on a word boundary so "RPY101" (a Ren'Py rule
# code, NOT an internal task ID) is not matched. The ID prefix list is
# exhaustive — any new ID family added to the worklog must be added here.
# We allow an optional preceding "-" so we can collapse "Senpy-LSP-21-fetcher"
# to "Senpy-fetcher" (not "Senpy--fetcher").
_ID_PATTERN = re.compile(
    r"(?P<pre>-?)"
    r"\b("
    r"DOC|CLI|LSP|QUA|ARCH|EXT|SEC|RULE|FMT|FIX|TEST|IDEA|PERF|SEO|CLEAN|"
    r"AUD|SSA|ECO|STUDIO|WL"
    r")-\d+[a-z]?\b"
)

# Whitelist of paths the script will NOT touch. Relative to repo root.
# Each entry is a glob pattern.
_WHITELIST_PATHS = [
    "CHANGELOG.md",
    "Senpy_Consolidated_Backlog_*.md",
    "senpy/vendor/**",
    "senpy-vscode/package-lock.json",  # auto-generated, contains versions
    "senpy.sarif",  # auto-generated SARIF report
    "scripts/clean_internal_ids.py",  # this script — describes IDs as objects
    "tests/test_clean_internal_ids.py",  # this test — describes IDs as objects
    "tests/test_no_russian_comments.py",  # CLEAN-2 guard — references CLEAN-1 and CLEAN-2
    "tests/test_ruff_clean.py",  # CI-1 test — describes IDs in comments
    ".pre-commit-config.yaml",  # CI-8 config — references CLEAN-1 hook
    ".github/workflows/ci.yml",  # CI workflow — references CI-1, QUA-7, etc. in comments
    ".github/PULL_REQUEST_TEMPLATE.md",  # meta-doc about ID format itself
    ".github/ISSUE_TEMPLATE/**",  # templates reference ID format
    ".git/**",
    "node_modules/**",
    "build/**",
    "dist/**",
    ".senpy_cache/**",
    "__pycache__/**",
    "*.pyc",
]

# Lines containing any of these substrings are skipped entirely (the ID
# match is a false positive — e.g. shields.io badge URLs that happen to
# contain "LSP-20" as part of "LSP: 20+ handlers").
_LINE_SKIP_SUBSTRINGS = (
    "shields.io",
    "%2B",  # URL-encoded "+" — appears in badge data
    "img.shields.io",
)

# File extensions we will scan. Skip binaries, images, lockfiles.
_SCANNABLE_EXTS = {
    ".py",
    ".md",
    ".ts",
    ".js",
    ".toml",
    ".yml",
    ".yaml",
    ".json",
    ".bat",
    ".sh",
    ".rst",
    ".txt",
    ".cfg",
    ".ini",
    ".spec",
}


def _is_whitelisted(path: Path, repo_root: Path) -> bool:
    """Return True if *path* matches any whitelist glob."""
    import fnmatch

    rel = path.relative_to(repo_root).as_posix()
    for pattern in _WHITELIST_PATHS:
        if fnmatch.fnmatch(rel, pattern):
            return True
        # Also try without leading "./"
        if pattern.endswith("/**") and rel.startswith(pattern[:-4] + "/"):
            return True
    return False


def _is_scannable(path: Path) -> bool:
    """Return True if *path* has a scannable extension."""
    return path.suffix.lower() in _SCANNABLE_EXTS


def _final_cleanup(line: str) -> str:
    """Apply post-substitution cleanups: collapse empty parens, fix
    stray leading punctuation, double spaces, trailing space-period.
    """
    line = re.sub(r"\(\s+\)", "", line)  # "( )" → ""
    line = re.sub(r"\(\s*\)", "", line)  # "()" → ""
    line = re.sub(r"\(\s+", "(", line)  # "( text" → "(text"
    line = re.sub(r"\s+\)", ")", line)  # "text )" → "text)"
    line = re.sub(r"(?<=\S)  (?=\S)", " ", line)  # "a  b" → "a b"
    # Stray " ," or " /" at start of a content run (after comment marker):
    # "# / CI fix" → "# CI fix"; "  , 0.6.2)" → "  0.6.2)".
    line = re.sub(r"((?:^|\s)#\s*)[/,]\s+", r"\1", line)
    line = re.sub(r"(^\s+)[/,]\s+", r"\1", line)
    # Trailing " ." (space before period at end of sentence after ID removal):
    # "after ." → "after."
    line = re.sub(r"\s+\.", ".", line)
    # Strip trailing whitespace left after ID removal at end of line
    # (e.g. "# TODO (ARCH-22)\n" → "# TODO \n" → "# TODO\n"). Preserve
    # the newline if present.
    line = re.sub(r"[ \t]+\n", "\n", line)
    line = re.sub(r"[ \t]+$", "", line)
    return line


def _scrub_line(line: str) -> tuple[str, int]:
    """Scrub IDs from one line. Returns (new_line, n_replacements).

    Lines containing any of ``_LINE_SKIP_SUBSTRINGS`` are returned unchanged
    (the ID match is assumed to be a false positive — e.g. a shields.io
    badge URL that happens to contain "LSP-20" as part of "LSP: 20+").

    Strategy (per ID match) — see source comments for the exact regex.
    After all substitutions, we collapse empty parens "()" and double
    spaces "  " left behind by the ID removal.
    """
    if any(s in line for s in _LINE_SKIP_SUBSTRINGS):
        return line, 0

    n = 0

    # Detect "ID is the first token" case. Pattern: line starts with
    # optional whitespace + optional comment/docstring/quote marker + ID.
    # We check this once per line, before substitutions. Covers:
    #   "ECO-9: ..."          (docstring open)
    #   # ECO-9: ...           (Python comment)
    #   // ECO-9: ...          (JS/TS comment)
    #   "ECO-4: pin unrpyc..." (string literal opening quote, no space)
    #   LSP-6: textDocument... (raw text — e.g. inside a docstring body)
    _LEADING_ID = re.compile(
        r"^(?P<prefix>\s*(?:#|//|\"\"\"|'|\"|\*)?\s*)"
        r"(?P<id>(?:DOC|CLI|LSP|QUA|ARCH|EXT|SEC|RULE|FMT|FIX|TEST|IDEA|PERF|SEO|CLEAN|AUD|SSA|ECO|STUDIO)-\d+[a-z]?)"
        r":\s?"  # colon + optional space
    )
    leading_m = _LEADING_ID.match(line)
    if leading_m:
        # Strip "ID: " or "ID:" from the start of the line (keep prefix).
        prefix = leading_m.group("prefix")
        rest = line[leading_m.end() :]
        line = prefix + rest
        n += 1
        # Re-run for any remaining IDs mid-line. They use the inline logic.
        if not _ID_PATTERN.search(line):
            line = _final_cleanup(line)
            return line, n

    # Special case: ID inside a string literal as a commit-message prefix,
    # e.g. git commit -m "ECO-4: pin unrpyc..." → git commit -m "pin unrpyc...".
    # Match a quote (single or double, possibly escaped) followed by ID + colon.
    _QUOTE_PREFIXED_ID = re.compile(
        r"""(?P<q>["'])"""
        r"(?P<id>(?:DOC|CLI|LSP|QUA|ARCH|EXT|SEC|RULE|FMT|FIX|TEST|IDEA|PERF|SEO|CLEAN|AUD|SSA|ECO|STUDIO)-\d+[a-z]?)"
        r":\s?"
    )
    new_line, q_n = _QUOTE_PREFIXED_ID.subn(lambda m: m.group("q"), line)
    if q_n > 0:
        n += q_n
        line = new_line
        if not _ID_PATTERN.search(line):
            line = _final_cleanup(line)
            return line, n

    def _replace(m: re.Match) -> str:
        nonlocal n
        n += 1
        pre = m.group("pre")
        end = m.end()
        # If we matched a preceding dash, swallow it (avoids "Senpy--fetcher").
        if pre == "-":
            return ""
        rest = line[end : end + 2]
        # "ID: " → strip "ID: "
        if rest == ": ":
            return ""
        # "ID:" at end of token (no space) → strip "ID:"
        if rest.startswith(":"):
            return ""
        # "ID-" → strip "ID-" (defensive; pre-group usually catches this)
        if rest.startswith("-"):
            return ""
        # "ID " → strip "ID "
        if rest.startswith(" "):
            return ""
        # Bare ID, no special suffix → strip just the ID
        return ""

    new_line = _ID_PATTERN.sub(_replace, line)
    return _final_cleanup(new_line), n


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Scan *path*, return list of (line_no, old_line, new_line) tuples
    for lines that would change. Line numbers are 1-indexed.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    changes: list[tuple[int, str, str]] = []
    for i, line in enumerate(text.splitlines(keepends=True), start=1):
        # Skip pathological lines (minified JS / generated JSON can have
        # single-line files of hundreds of KB — regex would be slow).
        if len(line) > 10_000:
            continue
        new_line, n = _scrub_line(line)
        if n > 0 and new_line != line:
            changes.append((i, line, new_line))
    return changes


def walk_repo(repo_root: Path, restrict_paths: list[Path] | None = None):
    """Yield scannable, non-whitelisted files under *repo_root*.

    If *restrict_paths* is given, only walk those subtrees (each must be
    a path under repo_root).
    """
    if restrict_paths:
        roots = restrict_paths
    else:
        roots = [repo_root]

    for root in roots:
        if root.is_file():
            if _is_scannable(root) and not _is_whitelisted(root, repo_root):
                yield root
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            # Skip non-repo directories that rglob can leak into (especially
            # on Windows where .vscode-test/ downloads a full VS Code instance
            # and would hang the script for minutes). Use substring match on
            # '/dir/' to catch nested occurrences (e.g. 'senpy-vscode/node_modules/'
            # was leaking through rel.startswith('node_modules/') which only
            # matches the root).
            try:
                rel = path.relative_to(repo_root).as_posix()
            except ValueError:
                continue
            skip_subdirs = (
                "/.git/",
                "/node_modules/",
                "/build/",
                "/dist/",
                "/.senpy_cache/",
                "/__pycache__/",
                "/.vscode-test/",
                "/.vscode-test-cache/",
                "/.cache/",
                "/htmlcov/",
                "/.pytest_cache/",
                "/.ruff_cache/",
                "/.mypy_cache/",
            )
            if any(s in "/" + rel for s in skip_subdirs):
                continue
            if rel.startswith(
                (
                    "node_modules/",
                    "build/",
                    "dist/",
                    "__pycache__/",
                    ".git/",
                    ".senpy_cache/",
                    ".vscode-test/",
                    ".vscode-test-cache/",
                    ".cache/",
                    "htmlcov/",
                    ".pytest_cache/",
                    ".ruff_cache/",
                    ".mypy_cache/",
                )
            ):
                continue
            if not _is_scannable(path):
                continue
            if _is_whitelisted(path, repo_root):
                continue
            # Skip files larger than 1 MB — they are not source code and
            # would slow the scan.
            try:
                if path.stat().st_size > 1_000_000:
                    continue
            except OSError:
                continue
            yield path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrub internal task IDs from user-facing files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n\n", 1)[1] if "\n\n" in __doc__ else "",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run", action="store_true", help="Show what would change; do not write files."
    )
    mode.add_argument("--apply", action="store_true", help="Write changes to disk.")
    parser.add_argument(
        "--paths",
        nargs="*",
        type=Path,
        default=None,
        help="Restrict scan to these paths (default: whole repo).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print every change, not just files with changes.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    print(f"Repo root: {repo_root}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    print()

    total_changes = 0
    files_changed = 0
    for path in walk_repo(repo_root, args.paths):
        changes = scan_file(path)
        if not changes:
            continue
        files_changed += 1
        rel = path.relative_to(repo_root)
        print(f"=== {rel} ({len(changes)} change{'s' if len(changes) != 1 else ''}) ===")
        for line_no, old, new in changes:
            total_changes += 1
            if args.verbose or args.dry_run:
                # Show a unified-diff-style snippet.
                print(f"  L{line_no}:")
                print(f"    - {old.rstrip()!r}")
                print(f"    + {new.rstrip()!r}")
        if args.apply:
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines(keepends=True)
            for line_no, _, new in changes:
                lines[line_no - 1] = new
            path.write_text("".join(lines), encoding="utf-8", newline="\n")
        print()

    print(f"Summary: {total_changes} line change(s) across {files_changed} file(s).")
    if args.dry_run and total_changes > 0:
        print("Re-run with --apply to write the changes.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
