#!/usr/bin/env python3
"""Run senpy on each corpus project and emit per-project JSON diagnostics.

The corpus was cloned by ``scripts/collect_corpus.py``; this script runs
the senpy analyzer against each project, serialises the diagnostics
to ``tests/_corpus/<slug>/senpy_results.json`` (gitignored — local
artefact) and optionally regenerates ``tests/_corpus_baseline.json``
(committed — the contract that ``tests/rules/test_corpus_fp.py`` in
CORPUS-5 compares against).

VN source stays local + gitignored; only anonymised
counts (per-rule and total) enter the committed baseline.

Auto-detection of the Ren'Py project root:
    Corpus projects are shallow-cloned with arbitrary nesting of
    ``game/`` — e.g. ``gifting_game/game/``, ``ddlc/ddlc-renpy-project/
    game/``, ``bytes_of_love/BytesOfLove/game/``, ``avnovel/avdemo/
    game/``. This script searches the clone for the first ``game/``
    directory (BFS, shallowest match wins) and passes its parent as
    ``project_path`` to ``SenpyAnalyzer``. If no ``game/`` is found,
    the clone root is used as a fallback (some VN repos store
    ``.rpy`` files directly in the repo root without a ``game/``
    wrapper — e.g. cross_channel's localization layout).

Usage:
    python scripts/run_corpus.py                          # run all
    python scripts/run_corpus.py --only gifting_game      # run one
    python scripts/run_corpus.py --update-baseline        # regen baseline
    python scripts/run_corpus.py --list                   # plan only
    python scripts/run_corpus.py --json-only gifting_game  # print JSON to stdout

Skip-if-absent:
    Projects without a clone dir are skipped with a warning (the
    ``test_corpus_fp.py`` pytest in CORPUS-5 mirrors this with
    ``pytest.skip``). This keeps ``run_corpus.py`` usable on machines
    that only cloned a subset.

Baseline format (``tests/_corpus_baseline.json``, committed):
    {
      "gifting_game": {
        "fingerprint": "sha256:<git-sha-of-clone>",
        "total": 53,
        "by_code": {"RPY503": 17, "RPY305": 16, "RPY104": 15, ...},
        "by_severity": {"WARNING": 50, "ERROR": 3}
      },
      ...
    }
    ``fingerprint`` lets the CI job (CORPUS-8) detect upstream
    movement — a stale baseline against a moved commit is a smell,
    not necessarily a regression.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# Allow running this script from anywhere (``python scripts/run_corpus.py``)
# by prepending the repo root to sys.path so ``from senpy.core.analyzer``
# and ``from scripts.collect_corpus`` resolve. Without this, a bare
# ``python scripts/run_corpus.py`` invocation from the repo root fails
# with ModuleNotFoundError: No module named 'senpy' because the cwd is
# not on sys.path when invoked as a script file (only the script's own
# directory is).
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Reuse the catalog from collect_corpus.py so the two scripts stay in
# lockstep — adding a project to the corpus means editing one place.
from scripts.collect_corpus import CORPUS_DIR, PROJECTS
from senpy.core.analyzer import SenpyAnalyzer

BASELINE_PATH = REPO_ROOT / "tests" / "_corpus_baseline.json"


def _find_project_root(clone_dir: Path) -> Path:
    """Locate the Ren'Py project root (parent of ``game/``) in a clone.

    BFS for the shallowest ``game/`` directory. If none is found, fall
    back to the clone root (covers repos that store ``.rpy`` files
    without the standard ``game/`` wrapper).
    """
    if not clone_dir.exists():
        return clone_dir  # caller handles the missing case
    # BFS — shallowest first. One level of nesting is the norm; two is
    # rare but supported (e.g. a repo with ``wrapper/game-src/game/``).
    for level in (0, 1, 2, 3):
        for candidate in clone_dir.glob("*/" * level + "game"):
            if candidate.is_dir():
                return candidate.parent
    # No game/ found — fall back to the clone root.
    return clone_dir


def _run_one(slug: str) -> dict | None:
    """Run senpy on one corpus project. Returns the result dict or None.

    The dict is suitable for both the per-project ``senpy_results.json``
    (full diagnostics list, gitignored) and the committed baseline
    (anonymised counts only). The caller decides what to persist.
    """
    clone_dir = CORPUS_DIR / slug
    if not clone_dir.exists() or not any(clone_dir.iterdir()):
        print(f"  [skip] {slug:<28} not cloned — run scripts/collect_corpus.py", file=sys.stderr)
        return None

    project_root = _find_project_root(clone_dir)
    cloned_sha_path = clone_dir / ".cloned_sha"
    fingerprint = "unknown"
    if cloned_sha_path.exists():
        fingerprint = "sha256:" + cloned_sha_path.read_text(encoding="utf-8").strip()

    # no_cache=True so each run is independent of any stale Tier-2 cache
    # left from a previous dev run on the same project (the corpus dir
    # is gitignored, so the cache would be invisible to git and could
    # mask a regression — force cold every time).
    analyzer = SenpyAnalyzer(str(project_root), no_cache=True)
    result = analyzer.run(quiet=True)

    by_code = Counter(d.code for d in result.diagnostics)
    by_severity = Counter(d.severity or "UNSPECIFIED" for d in result.diagnostics)

    # Full diagnostics for the per-project JSON (gitignored). Paths are
    # made repo-relative so the JSON is portable across dev machines
    # (the absolute prefix differs per clone location).
    rel_diags = []
    for d in result.diagnostics:
        try:
            rel_file = str(Path(d.file_path).relative_to(project_root)).replace("\\", "/")
        except ValueError:
            rel_file = d.file_path
        rel_diags.append(
            {
                "file": rel_file,
                "line": d.line_number,
                "code": d.code,
                "severity": d.severity,
                "message": d.message,
                "col": d.col,
                "end_col": d.end_col,
            }
        )

    full_result = {
        "slug": slug,
        "fingerprint": fingerprint,
        "project_root": str(project_root.relative_to(REPO_ROOT)),
        "file_count": result.file_count,
        "total_lines": result.total_lines,
        "total_diagnostics": len(result.diagnostics),
        "by_code": dict(sorted(by_code.items())),
        "by_severity": dict(sorted(by_severity.items())),
        "diagnostics": rel_diags,
    }

    # Write per-project JSON (gitignored — local artefact for triage).
    out_path = clone_dir / "senpy_results.json"
    out_path.write_text(
        json.dumps(full_result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return full_result


def _baseline_entry(result: dict) -> dict:
    """Strip the diagnostics list — keep only the committed metadata."""
    return {
        "fingerprint": result["fingerprint"],
        "total": result["total_diagnostics"],
        "by_code": result["by_code"],
        "by_severity": result["by_severity"],
    }


def _load_baseline() -> dict:
    """Load the committed baseline, or return {} if absent."""
    if not BASELINE_PATH.exists():
        return {}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _save_baseline(baseline: dict) -> None:
    BASELINE_PATH.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _drift_report(slug: str, current: dict, baseline: dict) -> list[str]:
    """Compare a current run against the baseline. Returns human-readable deltas."""
    diffs: list[str] = []
    base = baseline.get(slug, {})
    if not base:
        diffs.append(f"  {slug}: NEW — no baseline entry (run with --update-baseline)")
        return diffs
    if base.get("fingerprint") != current["fingerprint"]:
        diffs.append(
            f"  {slug}: fingerprint moved {base['fingerprint'][:24]}.. -> {current['fingerprint'][:24]}.."
        )
    if base.get("total") != current["total_diagnostics"]:
        diffs.append(
            f"  {slug}: total {base['total']} -> {current['total_diagnostics']} "
            f"({'+' if current['total_diagnostics'] > base['total'] else ''}"
            f"{current['total_diagnostics'] - base['total']})"
        )
    # Per-code delta.
    base_codes = base.get("by_code", {})
    cur_codes = current["by_code"]
    all_codes = set(base_codes) | set(cur_codes)
    code_deltas = []
    for code in sorted(all_codes):
        delta = cur_codes.get(code, 0) - base_codes.get(code, 0)
        if delta != 0:
            code_deltas.append(f"{code}:{'+' if delta > 0 else ''}{delta}")
    if code_deltas:
        diffs.append(f"  {slug}: codes {', '.join(code_deltas)}")
    return diffs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run senpy on each corpus VN and emit per-project JSON + optional baseline.",
    )
    parser.add_argument(
        "--list", action="store_true", help="print which projects would run and exit"
    )
    parser.add_argument(
        "--only",
        metavar="SLUG",
        help="run only one project (comma-separated slugs, e.g. --only ddlc,learntocode)",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="regenerate tests/_corpus_baseline.json from this run (committable contract)",
    )
    parser.add_argument(
        "--json-only",
        metavar="SLUG",
        help="run one project and print its full JSON to stdout (no file write)",
    )
    args = parser.parse_args()

    if args.list:
        print(f"{'SLUG':<28} {'CLONED':<8} {'GAME/'}")
        print("-" * 28 + " " + "-" * 8 + " " + "-" * 40)
        for p in PROJECTS:
            clone = CORPUS_DIR / p.slug
            cloned = "yes" if (clone / ".git").exists() else "no"
            root = _find_project_root(clone) if clone.exists() else clone
            game_rel = str(root.relative_to(clone)).replace("\\", "/") if clone.exists() else "?"
            print(f"{p.slug:<28} {cloned:<8} {game_rel}")
        print(f"\nBaseline: {BASELINE_PATH} ({'exists' if BASELINE_PATH.exists() else 'absent'})")
        return 0

    if args.json_only:
        result = _run_one(args.json_only)
        if result is None:
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    selected = PROJECTS
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        unknown = wanted - {p.slug for p in PROJECTS}
        if unknown:
            print(f"ERROR: unknown slug(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        selected = tuple(p for p in PROJECTS if p.slug in wanted)

    baseline = _load_baseline() if not args.update_baseline else {}
    new_baseline: dict[str, dict] = {}
    drift: list[str] = []

    print(f"Corpus: {CORPUS_DIR}")
    print(f"Baseline: {BASELINE_PATH} (mode={'update' if args.update_baseline else 'compare'})\n")
    counts = {"ran": 0, "skipped": 0}
    for p in selected:
        result = _run_one(p.slug)
        if result is None:
            counts["skipped"] += 1
            continue
        counts["ran"] += 1
        marker = "+"
        if args.update_baseline:
            new_baseline[p.slug] = _baseline_entry(result)
            marker = "B"  # baseline written
        else:
            drift.extend(_drift_report(p.slug, result, baseline))
        print(
            f"  [{marker}] {p.slug:<28} diags={result['total_diagnostics']:<4} "
            f"files={result['file_count']:<3} codes={len(result['by_code'])}"
        )

    print(f"\nDone. ran={counts['ran']} skipped={counts['skipped']}")

    if args.update_baseline and new_baseline:
        _save_baseline(new_baseline)
        print(f"Wrote baseline ({len(new_baseline)} projects) -> {BASELINE_PATH}")

    if not args.update_baseline and drift:
        print("\nDrift vs baseline:")
        for line in drift:
            print(line)
        return 1  # signal drift to CI (CORPUS-8 catches this)

    return 0


if __name__ == "__main__":
    sys.exit(main())
