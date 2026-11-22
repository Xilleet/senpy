#!/usr/bin/env python3
"""Triage senpy diagnostics on the corpus — classify each as TP / FP / maybe-FP.

Corpus FP cleanup: ``run_corpus.py`` writes per-project JSON to ``tests/_corpus/<slug>/
senpy_results.json`` (gitignored, local). This script reads those JSON
files and lets a maintainer classify every diagnostic against the
actual VN source:

    TP        — true positive, a real Ren'Py bug/anti-pattern senpy
                caught correctly.
    FP        — false positive, senpy fired on legitimate code.
    maybe-FP  — needs a closer look; not yet decided.
    skip      — defer (the diagnostic is ambiguous or out of scope).

The classification is written to ``tests/_corpus_triage.json``
(committed — anonymous triage state, no VN source). The downstream
step takes every ``FP`` / ``maybe-FP`` and turns it into a
RED pytest in ``tests/rules/test_corpus_fp.py``.

Hybrid interface:

    --export-csv                 bulk dump every diagnostic across every
                                 cloned project to ``tests/_corpus_triage.csv``
                                 (gitignored) — for offline labelling in a
                                 spreadsheet. Maintainer fills the
                                 ``status`` column with ``tp``/``fp``/
                                 ``maybe_fp``/``skip`` and adds a ``note``.

    --import-csv                 read the labelled CSV back and write
                                 ``tests/_corpus_triage.json`` (committed).
                                 Idempotent: re-importing the same CSV
                                 produces the same JSON.

    --slug <name>                interactive per-diagnostic prompt for
                                 one project. Walks each diagnostic, shows
                                 file:line:code:message, and accepts
                                 ``t``/``f``/``m``/``s``/``q``. Saves to
                                 ``tests/_corpus_triage.json`` on exit.

    --status <tp|fp|maybe_fp|skip>  filter the summary (and the interactive
                                 mode) to a single classification.

    --summary                    print the per-project + overall triage
                                 breakdown (TP / FP / maybe-FP / unmarked)
                                 without writing anything.

Usage:
    python scripts/triage_corpus.py --export-csv           # bulk dump
    # ...label the CSV in LibreOffice / Excel offline...
    python scripts/triage_corpus.py --import-csv           # commit labels
    python scripts/triage_corpus.py --slug gifting_game     # interactive
    python scripts/triage_corpus.py --summary               # counts only
    python scripts/triage_corpus.py --summary --status fp   # FP count only

Triage JSON schema (``tests/_corpus_triage.json``, committed):
    {
      "gifting_game": {
        "fingerprint": "sha256:...",
        "total": 53,
        "by_status": {"tp": 30, "fp": 12, "maybe_fp": 5, "skip": 2, "unmarked": 4},
        "diagnostics": [
          {
            "file": "game/olnewyear-5.rpy", "line": 675, "code": "RPY202",
            "severity": "WARNING", "message": "Screen 'file_slots' ...",
            "status": "fp", "note": "CurrentScreenName is a user define."
          }, ...
        ]
      }, ...
    }
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import sys
from collections import Counter
from pathlib import Path

# Repo root on sys.path so ``from scripts.collect_corpus import ...``
# works when this file is invoked as a script.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.collect_corpus import CORPUS_DIR, PROJECTS

TRIAGE_PATH = REPO_ROOT / "tests" / "_corpus_triage.json"
CSV_PATH = CORPUS_DIR / "_corpus_triage.csv"  # gitignored (under tests/_corpus/)

# Allowed status values. The CSV uses lowercase short forms; the JSON
# uses the canonical form. ``unmarked`` is a synthetic status for
# diagnostics the maintainer has not yet classified.
STATUSES: tuple[str, ...] = ("tp", "fp", "maybe_fp", "skip")
STATUS_ALIASES: dict[str, str] = {
    "t": "tp",
    "tp": "tp",
    "true": "tp",
    "f": "fp",
    "fp": "fp",
    "false": "fp",
    "m": "maybe_fp",
    "mf": "maybe_fp",
    "maybe_fp": "maybe_fp",
    "maybe-fp": "maybe_fp",
    "maybe": "maybe_fp",
    "s": "skip",
    "skip": "skip",
}


def _diagnostic_key(diag: dict) -> tuple:
    """Stable identity for a diagnostic across runs (file, line, code, col)."""
    return (diag["file"], diag["line"], diag["code"], diag.get("col", 0))


def _load_results(slug: str) -> dict | None:
    """Read ``tests/_corpus/<slug>/senpy_results.json`` if present."""
    path = CORPUS_DIR / slug / "senpy_results.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_triage() -> dict:
    if not TRIAGE_PATH.exists():
        return {}
    return json.loads(TRIAGE_PATH.read_text(encoding="utf-8"))


def _save_triage(triage: dict) -> None:
    TRIAGE_PATH.write_text(
        json.dumps(triage, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _empty_entry(result: dict) -> dict:
    """A fresh triage entry mirroring the run_corpus.py result schema."""
    return {
        "fingerprint": result.get("fingerprint", "unknown"),
        "total": result["total_diagnostics"],
        "by_status": {},
        "diagnostics": [
            {
                "file": d["file"],
                "line": d["line"],
                "code": d["code"],
                "severity": d["severity"],
                "message": d["message"],
                "col": d.get("col", 0),
                "end_col": d.get("end_col", 0),
                "status": "unmarked",
                "note": "",
            }
            for d in result["diagnostics"]
        ],
    }


def _recompute_by_status(entry: dict) -> dict:
    """Recount by_status from the diagnostics list."""
    counts: Counter = Counter()
    for d in entry["diagnostics"]:
        counts[d.get("status", "unmarked")] += 1
    # Ensure canonical keys exist even at zero (skips make UI stable).
    for s in (*STATUSES, "unmarked"):
        counts.setdefault(s, 0)
    return dict(sorted(counts.items()))


def _merge_import(triage: dict, slug: str, labels: dict[tuple, tuple[str, str]]) -> dict:
    """Merge CSV labels into the triage entry for ``slug``.

    ``labels`` maps diagnostic-key -> (status, note). Diagnostics not
    present in ``labels`` keep their existing status (preserves prior
    interactive work). Diagnostics in ``labels`` but not in the result
    JSON are silently dropped (the corpus moved upstream).
    """
    result = _load_results(slug)
    if result is None:
        return triage
    entry = triage.get(slug) or _empty_entry(result)
    # Match by key; only update labels that exist in the result.
    for d in entry["diagnostics"]:
        key = _diagnostic_key(d)
        if key in labels:
            status, note = labels[key]
            d["status"] = status
            d["note"] = note
    entry["by_status"] = _recompute_by_status(entry)
    triage[slug] = entry
    return triage


# --- CSV import / export -----------------------------------------------------

CSV_COLUMNS = ["slug", "file", "line", "code", "severity", "col", "message", "status", "note"]


def _export_csv() -> int:
    """Dump every diagnostic from every cloned project to a CSV."""
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    triage = _load_triage()
    with CSV_PATH.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        rows = 0
        for p in PROJECTS:
            result = _load_results(p.slug)
            if result is None:
                print(
                    f"  [skip] {p.slug:<28} not run — invoke scripts/run_corpus.py", file=sys.stderr
                )
                continue
            existing = triage.get(p.slug, {})
            existing_by_key: dict[tuple, dict] = {}
            for d in existing.get("diagnostics", []):
                existing_by_key[_diagnostic_key(d)] = d
            for d in result["diagnostics"]:
                key = _diagnostic_key(d)
                prior = existing_by_key.get(key, {})
                writer.writerow(
                    {
                        "slug": p.slug,
                        "file": d["file"],
                        "line": d["line"],
                        "code": d["code"],
                        "severity": d["severity"],
                        "col": d.get("col", 0),
                        "message": d["message"],
                        "status": prior.get("status", "unmarked"),
                        "note": prior.get("note", ""),
                    }
                )
                rows += 1
            print(f"  [+] {p.slug:<28} exported {len(result['diagnostics'])} diagnostics")
    print(f"\nWrote {rows} rows -> {CSV_PATH}")
    print("Label the 'status' column with tp/fp/maybe_fp/skip and add a 'note',")
    print("then run `python scripts/triage_corpus.py --import-csv`.")
    return 0


def _import_csv() -> int:
    """Read a labelled CSV and merge into tests/_corpus_triage.json."""
    if not CSV_PATH.exists():
        print(f"ERROR: {CSV_PATH} not found. Run --export-csv first.", file=sys.stderr)
        return 1
    # labels[slug][diagnostic_key] = (status, note)
    labels_by_slug: dict[str, dict[tuple, tuple[str, str]]] = {}
    seen_keys: set[tuple] = set()
    bad_status_rows = 0
    with CSV_PATH.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            slug = row["slug"]
            key = (row["file"], int(row["line"]), row["code"], int(row["col"] or 0))
            raw_status = (row.get("status") or "unmarked").strip().lower()
            status = STATUS_ALIASES.get(raw_status, raw_status)
            if status not in STATUSES and status != "unmarked":
                bad_status_rows += 1
                print(
                    f"  WARN: row {reader.line_num} has bad status {raw_status!r} "
                    f"({slug} {row['file']}:{row['line']} {row['code']}) — skipped",
                    file=sys.stderr,
                )
                continue
            note = (row.get("note") or "").strip()
            labels_by_slug.setdefault(slug, {})[key] = (status, note)
            seen_keys.add((slug, key))
    if bad_status_rows:
        print(f"\n{bad_status_rows} row(s) skipped due to bad status.", file=sys.stderr)

    triage = _load_triage()
    for slug, labels in labels_by_slug.items():
        triage = _merge_import(triage, slug, labels)
    _save_triage(triage)
    print(f"Imported labels for {len(labels_by_slug)} project(s) -> {TRIAGE_PATH}")
    _print_summary(triage)
    return 0


# --- Interactive triage ------------------------------------------------------


def _read_source_context(slug: str, file: str, line: int, context: int = 5) -> str | None:
    """Read source lines around ``line`` from the corpus clone.

    Returns a formatted string with line numbers and an ``←`` marker on
    the flagged line, or ``None`` if the source file is not found (corpus
    not cloned, file moved upstream, encoding error).

    ``context`` lines are shown before and after the flagged line.
    """
    source_path = CORPUS_DIR / slug / file
    if not source_path.exists():
        return None

    try:
        lines = source_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None

    # Line numbers are 1-based; list index is 0-based.
    target_idx = line - 1
    if target_idx < 0 or target_idx >= len(lines):
        # Line out of range — file may have changed upstream.
        return None

    start = max(0, target_idx - context)
    end = min(len(lines), target_idx + context + 1)

    result = []
    for i in range(start, end):
        line_no = i + 1
        marker = " ←" if i == target_idx else "  "
        # Truncate very long lines so the prompt fits a normal terminal.
        content = lines[i]
        if len(content) > 100:
            content = content[:97] + "..."
        result.append(f"  {line_no:>5} │{marker} {content}")

    return "\n".join(result)


def _prompt_one(slug: str, diag: dict) -> tuple[str, str] | None:
    """Prompt the maintainer for one diagnostic's status + note.

    Returns ``(status, note)`` or ``None`` if the user chose to defer
    (keeps the existing status).

    Displays 5 lines of source context around the flagged line (read
    from the local corpus clone) plus a link to the rule's section in
    RULES.md so the triager can quickly check the rule's intent.
    """
    print(
        f"\n  {slug} | {diag['file']}:{diag['line']} "
        f"[{diag['code']} {diag.get('severity', '?')}]"
    )
    msg = diag.get("message", "")
    # Wrap long messages so the prompt fits a normal terminal.
    if len(msg) > 200:
        msg = msg[:197] + "..."
    print(f"    {msg}")

    # Show source context (5 lines before + flagged line + 5 lines after).
    # This is the single biggest UX improvement — without it the triager
    # has to open the VN source file in a separate editor for every
    # diagnostic, which makes triage ~5x slower.
    context = _read_source_context(slug, diag["file"], diag["line"])
    if context:
        print()
        print(context)
        print()
    else:
        print("    (source file not found — clone corpus or file moved upstream)")

    # Link to the rule's section in RULES.md. Anchors follow the pattern
    # ``rpyXXX`` (lowercase) — e.g. RPY202 → RULES.md#rpy202.
    code_lower = diag["code"].lower()
    print(f"    See RULES.md#{code_lower} for rule semantics.")
    print("    [t]p  [f]p  [m]aybe-fp  [s]kip  [q]uit (keep current)  [e]dit note")

    choice: str | None = None
    with contextlib.suppress(EOFError):
        choice = input("    > ").strip().lower()

    if choice is None:
        # Non-interactive stdin (piped input ran out) — keep current, stop.
        print("    (EOF — keeping current status)")
        return None
    if choice in ("q", ""):
        return None

    if choice == "e":
        with contextlib.suppress(EOFError):
            note = input("    note: ").strip()
            return ("unmarked", note)
        return None

    status = STATUS_ALIASES.get(choice)
    if status is None:
        print(f"    unknown choice {choice!r} — keeping current")
        return None

    note = ""
    if status in ("fp", "maybe_fp"):
        # Notes are most useful on FP / maybe-FP — they feed CORPUS-5.
        with contextlib.suppress(EOFError):
            note = input("    note (why FP/maybe? optional): ").strip()

    return (status, note)


def _interactive(slug: str) -> int:
    """Walk the diagnostics of one project and prompt for each."""
    result = _load_results(slug)
    if result is None:
        print(
            f"ERROR: no senpy_results.json for {slug}. "
            f"Run `python scripts/run_corpus.py --only {slug}` first.",
            file=sys.stderr,
        )
        return 1
    triage = _load_triage()
    entry = triage.get(slug) or _empty_entry(result)
    # Index existing labels by key so the interactive loop can carry
    # forward prior decisions.
    print(f"\nTriage: {slug} ({len(entry['diagnostics'])} diagnostics)")
    print("Ctrl-C aborts without saving; 'q' on a row keeps its current status.\n")
    try:
        for i, d in enumerate(entry["diagnostics"], 1):
            print(f"[{i}/{len(entry['diagnostics'])}]")
            verdict = _prompt_one(slug, d)
            if verdict is not None:
                d["status"], d["note"] = verdict
    except KeyboardInterrupt:
        print("\n\nAborted — no changes saved.")
        return 1
    entry["by_status"] = _recompute_by_status(entry)
    triage[slug] = entry
    _save_triage(triage)
    print(f"\nSaved -> {TRIAGE_PATH}")
    _print_summary(triage, only_slug=slug)
    return 0


def _interactive_by_rule(code: str) -> int:
    """Walk all diagnostics of one rule code across ALL projects.

    Groups diagnostics by rule code so the triager can build pattern
    recognition faster — e.g. all RPY305 cases across 15 projects
    are presented consecutively, making it obvious that they share
    a common FP pattern (multi-line dialogue).
    """
    triage = _load_triage()
    # Collect all matching diagnostics from all projects that have
    # senpy_results.json. Each case is (slug, diag_dict). The diag_dict
    # is a reference into the triage entry's diagnostics list, so
    # modifying it in-place persists when we save triage.
    cases: list[tuple[str, dict]] = []
    projects_with_code: set[str] = set()
    for p in PROJECTS:
        result = _load_results(p.slug)
        if result is None:
            continue
        entry = triage.get(p.slug) or _empty_entry(result)
        triage[p.slug] = entry  # ensure entry is in triage for save
        for d in entry["diagnostics"]:
            if d["code"] == code:
                cases.append((p.slug, d))
                projects_with_code.add(p.slug)

    if not cases:
        print(
            f"No diagnostics with code {code} found in corpus.\n"
            f"Run `python scripts/run_corpus.py` first to generate results.",
            file=sys.stderr,
        )
        return 1

    print(
        f"\nTriage by rule: {code} "
        f"({len(cases)} cases across {len(projects_with_code)} project(s))"
    )
    print("Ctrl-C aborts without saving; 'q' on a row keeps its current status.\n")

    dirty_slugs: set[str] = set()
    try:
        for i, (slug, d) in enumerate(cases, 1):
            print(f"[{i}/{len(cases)}]")
            verdict = _prompt_one(slug, d)
            if verdict is not None:
                d["status"], d["note"] = verdict
                dirty_slugs.add(slug)
    except KeyboardInterrupt:
        print("\n\nAborted — no changes saved.")
        return 1

    # Recompute by_status for all modified entries (the diag dicts were
    # modified in-place via shared references; the entries just need
    # their counts refreshed).
    for slug in dirty_slugs:
        triage[slug]["by_status"] = _recompute_by_status(triage[slug])
    _save_triage(triage)
    print(f"\nSaved -> {TRIAGE_PATH}")
    _print_summary(triage, status_filter="fp")
    return 0


# --- Summary -----------------------------------------------------------------


def _print_summary(
    triage: dict, only_slug: str | None = None, status_filter: str | None = None
) -> None:
    """Print per-project and overall triage counts."""
    overall: Counter = Counter()
    print(f"\n{'SLUG':<28} {'TOTAL':<6} {'TP':<5} {'FP':<5} {'MAYBE':<6} {'SKIP':<5} {'UNMARKED'}")
    print(
        "-" * 28
        + " "
        + "-" * 6
        + " "
        + "-" * 5
        + " "
        + "-" * 5
        + " "
        + "-" * 6
        + " "
        + "-" * 5
        + " "
        + "-" * 8
    )
    for p in PROJECTS:
        if only_slug and p.slug != only_slug:
            continue
        entry = triage.get(p.slug)
        if entry is None:
            print(f"{p.slug:<28} {'—':<6} (not triaged)")
            continue
        bs = entry.get("by_status", {})
        total = entry.get("total", 0)
        tp = bs.get("tp", 0)
        fp = bs.get("fp", 0)
        maybe = bs.get("maybe_fp", 0)
        skip = bs.get("skip", 0)
        unmarked = bs.get("unmarked", 0)
        overall["tp"] += tp
        overall["fp"] += fp
        overall["maybe_fp"] += maybe
        overall["skip"] += skip
        overall["unmarked"] += unmarked
        overall["total"] += total
        print(f"{p.slug:<28} {total:<6} {tp:<5} {fp:<5} {maybe:<6} {skip:<5} {unmarked}")
    if not only_slug:
        print("-" * 70)
        print(
            f"{'TOTAL':<28} {overall['total']:<6} {overall['tp']:<5} "
            f"{overall['fp']:<5} {overall['maybe_fp']:<6} {overall['skip']:<5} {overall['unmarked']}"
        )
    if status_filter:
        print(f"\nFilter '{status_filter}' total: {overall.get(status_filter, 0)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Triage senpy corpus diagnostics into TP / FP / maybe-FP.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--export-csv",
        action="store_true",
        help="dump all diagnostics to tests/_corpus/_corpus_triage.csv",
    )
    mode.add_argument(
        "--import-csv", action="store_true", help="read labelled CSV -> tests/_corpus_triage.json"
    )
    mode.add_argument("--slug", metavar="NAME", help="interactive triage for one project")
    mode.add_argument(
        "--by-rule",
        metavar="RPYXXX",
        help="interactive triage for all diagnostics of one rule code across all projects "
        "(e.g. --by-rule RPY305 — groups all multi-line dialogue FPs together)",
    )
    mode.add_argument("--summary", action="store_true", help="print triage counts and exit")
    parser.add_argument(
        "--status",
        choices=list(STATUSES) + ["unmarked"],
        help="filter the summary to one status (tp/fp/maybe_fp/skip/unmarked)",
    )
    args = parser.parse_args()

    if args.export_csv:
        return _export_csv()
    if args.import_csv:
        return _import_csv()
    if args.slug:
        unknown = args.slug not in {p.slug for p in PROJECTS}
        if unknown:
            print(f"ERROR: unknown slug {args.slug!r}", file=sys.stderr)
            return 2
        return _interactive(args.slug)
    if args.by_rule:
        code = args.by_rule.upper()
        if not code.startswith("RPY") or len(code) != 6:
            print(
                f"ERROR: rule code must be 'RPY' + 3 digits (e.g. RPY305), "
                f"got {args.by_rule!r}",
                file=sys.stderr,
            )
            return 2
        return _interactive_by_rule(code)
    # default: --summary (with optional --status filter)
    triage = _load_triage()
    _print_summary(triage, status_filter=args.status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
