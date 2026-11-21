#!/usr/bin/env python3
"""Diff two ``renpy_api_generated.json`` snapshots and print a human-readable summary.

By default compares the JSON at ``senpy/domain/data/renpy_api_generated.json``
(currently on disk, expected to be the NEW version) against the previous
commit's version of the same file. This is the workflow used when bumping
the Ren'Py pin: regenerate the JSON via ``scripts/fetch_renpy_docs.py``,
then run this script to see what changed in the Ren'Py API surface.

The script classifies changes into three buckets:
  - Added   — entries present in NEW but absent in OLD.
  - Removed — entries present in OLD but absent in NEW.
  - Changed — entries present in both but with different field values.
              Only field-level changes are reported (a single entry may
              produce multiple change rows). For each change the script
              prints the field name and a truncated old → new value diff.

Usage:
    # Compare working tree vs HEAD (the typical workflow after
    # `python scripts/fetch_renpy_docs.py`):
    python scripts/diff_renpy_api.py

    # Compare two explicit JSON files:
    python scripts/diff_renpy_api.py old.json new.json

    # Write the report to a markdown file (in addition to stdout):
    python scripts/diff_renpy_api.py --md docs/renpy_api_diff.md

Exit code: 0 if no differences, 1 if any differences found (useful in CI).

The previous JSON is fetched via ``git show`` if not given explicitly —
this means the workflow is: regenerate JSON → ``git diff`` shows binary
blob changes (unhelpful) → run this script for a readable summary →
commit the JSON + the markdown report.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSON_PATH = REPO_ROOT / "senpy" / "domain" / "data" / "renpy_api_generated.json"

# Fields whose values are typically long (signatures, descriptions). For
# these we truncate the printed value to keep the report readable.
_TRUNCATE_FIELDS = {"signature", "description", "doc"}
_TRUNCATE_LEN = 80


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: cannot read {path}: {e}", file=sys.stderr)
        sys.exit(2)


def _load_old_from_git(json_path: Path) -> dict[str, Any]:
    """Read the previous-committed version of ``json_path`` via ``git show``.

    Walks the git history backwards from HEAD to find the LAST commit before
    the current one that touched ``json_path``. This way the script compares
    the working-tree JSON against the version that was committed BEFORE the
    current regeneration — i.e. the workflow is: ``fetch_renpy_docs.py``
    modifies the JSON on disk, then ``diff_renpy_api.py`` shows what changed
    relative to the previously-committed JSON (which is what users want to
    see in a PR that bumps the Ren'Py pin).
    """
    rel = json_path.relative_to(REPO_ROOT)
    # Find the most recent commit that touched json_path. ``git log -1`` returns
    # the current commit (the one where the JSON was last regenerated). We want
    # the commit BEFORE that — so we ask for ``HEAD~N`` style by walking back.
    # The simplest reliable way: ``git log --format=%H -2 -- <path>`` gives us
    # the last two commits; the second line is the one BEFORE the most recent.
    try:
        result = subprocess.run(
            ["git", "log", "--format=%H", "-2", "--", str(rel)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(
            f"ERROR: cannot find git history for {rel}: {e}",
            file=sys.stderr,
        )
        sys.exit(2)

    commits = result.stdout.strip().split("\n")
    commits = [c for c in commits if c]
    if len(commits) < 2:
        print(
            f"ERROR: only {len(commits)} commit(s) in git history for {rel}. "
            f"Cannot diff against a previous version — pass an explicit OLD "
            f"json path as the first argument.",
            file=sys.stderr,
        )
        sys.exit(2)

    # The second commit (older) is the one BEFORE the most recent change.
    previous_commit = commits[1]
    try:
        result = subprocess.run(
            ["git", "show", f"{previous_commit}:{rel}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(
            f"ERROR: cannot read {previous_commit}:{rel} via git: {e.stderr.strip() or e}",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(
            f"ERROR: {previous_commit}:{rel} is not valid JSON: {e}",
            file=sys.stderr,
        )
        sys.exit(2)


def _truncate(value: Any, max_len: int = _TRUNCATE_LEN) -> str:
    s = repr(value) if not isinstance(value, str) else value
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def _field_diff(name: str, key: str, old_val: Any, new_val: Any) -> str:
    if key in _TRUNCATE_FIELDS:
        old_repr = _truncate(old_val)
        new_repr = _truncate(new_val)
    else:
        old_repr = repr(old_val)
        new_repr = repr(new_val)
    return f"  - {name}.{key}: {old_repr} → {new_repr}"


def diff_json(old: dict[str, Any], new: dict[str, Any]) -> dict[str, list]:
    """Return a dict with three keys: 'added', 'removed', 'changed'."""
    old_docs = old.get("docs", {})
    new_docs = new.get("docs", {})
    old_names = set(old_docs)
    new_names = set(new_docs)

    added = sorted(new_names - old_names)
    removed = sorted(old_names - new_names)

    changed: list[str] = []
    for name in sorted(old_names & new_names):
        old_entry = old_docs[name]
        new_entry = new_docs[name]
        if old_entry == new_entry:
            continue
        # Find which fields differ.
        all_keys = set(old_entry) | set(new_entry)
        for key in sorted(all_keys):
            old_v = old_entry.get(key, "<absent>")
            new_v = new_entry.get(key, "<absent>")
            if old_v != new_v:
                changed.append(_field_diff(name, key, old_v, new_v))

    return {"added": added, "removed": removed, "changed": changed}


def render_report(old_version: str, new_version: str, diff: dict[str, list]) -> str:
    added = diff["added"]
    removed = diff["removed"]
    changed = diff["changed"]
    total_changes = len(added) + len(removed) + len(changed)

    lines: list[str] = []
    lines.append("# Ren'Py API diff")
    lines.append("")
    lines.append(
        "Generated by `python scripts/diff_renpy_api.py`. Compares two snapshots "
        "of `senpy/domain/data/renpy_api_generated.json` (the data file that "
        "drives LSP hover/completion, RPY107 deprecated-API checks, and RPY502 "
        "transform-property validation)."
    )
    lines.append("")
    lines.append(
        "Regenerate this file after running `python scripts/fetch_renpy_docs.py` "
        "when bumping the Ren'Py pin (e.g. for a 0.9.x Ren'Py compatibility release)."
    )
    lines.append("")
    lines.append(f"- Old version: **{old_version}**")
    lines.append(f"- New version: **{new_version}**")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Added:   **{len(added)}** entries")
    lines.append(f"- Removed: **{len(removed)}** entries")
    # Count unique entries that have at least one changed field (each change line
    # starts with "  - NAME.field: ..." — extract the NAME to count uniques).
    changed_entries = {line.strip().lstrip("- ").split(".", 1)[0] for line in changed}
    lines.append(
        f"- Changed: **{len(changed)}** field(s) across **{len(changed_entries)}** entries"
    )
    lines.append(f"- Total changes: **{total_changes}**")
    lines.append("")

    if added:
        lines.append("## Added")
        lines.append("")
        lines.append(
            "These entries appear in the new JSON but were absent in the old. "
            "New APIs available in Ren'Py " + new_version + "."
        )
        lines.append("")
        for name in added:
            lines.append(f"- `{name}`")
        lines.append("")

    if removed:
        lines.append("## Removed")
        lines.append("")
        lines.append(
            "These entries were present in the old JSON but absent in the new. "
            "Likely deprecated and finally dropped in Ren'Py " + new_version + "."
        )
        lines.append("")
        for name in removed:
            lines.append(f"- `{name}`")
        lines.append("")

    if changed:
        lines.append("## Changed")
        lines.append("")
        lines.append("Field-level differences for entries present in both JSONs.")
        lines.append("")
        # Group changed entries by entry name for readability.
        current_name: str | None = None
        for line in changed:
            # Each line starts with "  - NAME.field: ..."
            name_part = line.strip().lstrip("- ").split(".", 1)[0]
            if name_part != current_name:
                lines.append(f"### `{name_part}`")
                lines.append("")
                current_name = name_part
            lines.append(line)
        lines.append("")

    if total_changes == 0:
        lines.append("## No changes")
        lines.append("")
        lines.append(
            "The two JSON snapshots are identical (apart from `version` and "
            "`generated_at` top-level fields)."
        )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "old",
        nargs="?",
        help="Path to the OLD JSON. If omitted, read HEAD version of the default JSON via git.",
    )
    parser.add_argument(
        "new",
        nargs="?",
        help="Path to the NEW JSON. If omitted, use the default on-disk path.",
    )
    parser.add_argument(
        "--md",
        metavar="PATH",
        help="Also write the report to this markdown file.",
    )
    args = parser.parse_args()

    new_path = Path(args.new) if args.new else DEFAULT_JSON_PATH
    if args.old:
        old_path = Path(args.old)
        old = _load_json(old_path)
    else:
        old = _load_old_from_git(DEFAULT_JSON_PATH)
    new = _load_json(new_path)

    old_version = old.get("version", "?")
    new_version = new.get("version", "?")

    diff = diff_json(old, new)
    report = render_report(old_version, new_version, diff)
    print(report)

    if args.md:
        md_path = Path(args.md)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(report + "\n", encoding="utf-8")
        print(f"\nWrote markdown report to {md_path}", file=sys.stderr)

    total_changes = len(diff["added"]) + len(diff["removed"]) + len(diff["changed"])
    return 1 if total_changes > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
