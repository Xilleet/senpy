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

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

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

# Shared rich console — mirrors collect_corpus.py so the two scripts
# visually match (same Panel border, same Table styling, same spinner).
console = Console()


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
        # Skip — caller shows status in the summary table.
        return None

    project_root = _find_project_root(clone_dir)
    cloned_sha_path = clone_dir / ".cloned_sha"
    fingerprint = "unknown"
    if cloned_sha_path.exists():
        # Prefix is "git:" (not "sha256:") because the value is a git
        # commit SHA, not a SHA-256 content hash. The prefix lets the
        # CI job and triage tooling distinguish fingerprint types in the
        # future (e.g. "content:" for a hash of the VN source itself).
        fingerprint = "git:" + cloned_sha_path.read_text(encoding="utf-8").strip()

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
    """Compare a current run against the baseline.

    Returns human-readable deltas with rich markup for color-coded
    ``+/-`` deltas: green when diagnostics decreased (improvement),
    red when increased (regression), yellow for ``NEW``, blue for
    fingerprint movement. Lines are printed via ``console.print(...)``
    in ``main()`` so the markup renders.
    """
    diffs: list[str] = []
    base = baseline.get(slug, {})
    if not base:
        diffs.append(
            f"  {slug}: [yellow]NEW[/yellow] — no baseline entry (run with --update-baseline)"
        )
        return diffs
    if base.get("fingerprint") != current["fingerprint"]:
        diffs.append(
            f"  {slug}: [blue]fingerprint moved[/blue] "
            f"{base['fingerprint'][:24]}.. -> {current['fingerprint'][:24]}.."
        )
    if base.get("total") != current["total_diagnostics"]:
        delta = current["total_diagnostics"] - base["total"]
        sign = "+" if delta > 0 else ""
        # Green when diags decreased (improvement); red when increased (regression).
        delta_style = "red" if delta > 0 else "green"
        diffs.append(
            f"  {slug}: total {base['total']} -> {current['total_diagnostics']} "
            f"([{delta_style}]{sign}{delta}[/{delta_style}])"
        )
    # Per-code delta.
    base_codes = base.get("by_code", {})
    cur_codes = current["by_code"]
    all_codes = set(base_codes) | set(cur_codes)
    code_deltas = []
    for code in sorted(all_codes):
        delta = cur_codes.get(code, 0) - base_codes.get(code, 0)
        if delta != 0:
            sign = "+" if delta > 0 else ""
            delta_style = "red" if delta > 0 else "green"
            code_deltas.append(f"{code}:[{delta_style}]{sign}{delta}[/{delta_style}]")
    if code_deltas:
        diffs.append(f"  {slug}: codes {', '.join(code_deltas)}")
    return diffs


# Per-status styling for the summary table (mirrors collect_corpus.py).
# ``ran`` = analyzed in compare mode; ``baseline`` = analyzed + baseline
# written in ``--update-baseline`` mode; ``skipped`` = clone absent.
# TODO: if SenpyAnalyzer.run() ever gains a structured error return
# (instead of raising), add an ``error`` status here (red ✗) so a
# single bad project does not kill the whole corpus run.
_STATUS_STYLE: dict[str, tuple[str, str]] = {
    "ran": ("green", "✓"),
    "skipped": ("yellow", "≈"),
    "baseline": ("blue", "B"),
}


def _run_summary_table(
    results: list[tuple[str, str, dict | None]],
) -> Table:
    """Build the per-project result table shown after the run.

    Each row: ``(slug, status, result_dict_or_None)``. Status drives
    the mark + color via ``_STATUS_STYLE``; the result dict populates
    Diags / Files / Codes columns (``-`` when skipped).
    """
    table = Table(title="Run results", show_lines=False, expand=True)
    table.add_column("", width=1)
    table.add_column("Slug", style="bold", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Diags", justify="right")
    table.add_column("Files", justify="right")
    table.add_column("Codes", justify="right")
    for slug, status, result in results:
        style, mark = _STATUS_STYLE.get(status, ("white", "?"))
        if result is not None:
            diags = str(result["total_diagnostics"])
            files = str(result["file_count"])
            codes = str(len(result["by_code"]))
        else:
            diags = "-"
            files = "-"
            codes = "-"
        table.add_row(
            mark,
            slug,
            f"[{style}]{status}[/{style}]",
            diags,
            files,
            codes,
        )
    return table


def _print_list_table() -> None:
    """Print the corpus run plan as a rich table (``--list`` mode)."""
    table = Table(title="Corpus run plan", show_lines=False, expand=True)
    table.add_column("Slug", style="bold cyan", no_wrap=True)
    table.add_column("Cloned", no_wrap=True)
    table.add_column("Game/")
    for p in PROJECTS:
        clone = CORPUS_DIR / p.slug
        cloned_yes = (clone / ".git").exists()
        cloned = "yes" if cloned_yes else "no"
        if clone.exists():
            root = _find_project_root(clone)
            game_rel = str(root.relative_to(clone)).replace("\\", "/")
        else:
            game_rel = "?"
        cloned_style = "green" if cloned_yes else "dim"
        table.add_row(p.slug, f"[{cloned_style}]{cloned}[/{cloned_style}]", game_rel)
    console.print(table)
    baseline_state = "exists" if BASELINE_PATH.exists() else "absent"
    baseline_style = "green" if BASELINE_PATH.exists() else "red"
    console.print(
        f"\nBaseline: [dim]{BASELINE_PATH}[/dim] "
        f"([{baseline_style}]{baseline_state}[/{baseline_style}])"
    )


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
        _print_list_table()
        return 0

    if args.json_only:
        # Pure JSON to stdout — no Panel, no Progress, no rich markup.
        # ``triage_corpus.py`` pipes this output into ``jq`` / CSV import,
        # so any non-JSON bytes on stdout would break downstream pipes.
        result = _run_one(args.json_only)
        if result is None:
            print(
                f"ERROR: project {args.json_only!r} not cloned — " "run scripts/collect_corpus.py",
                file=sys.stderr,
            )
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    selected = PROJECTS
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        unknown = wanted - {p.slug for p in PROJECTS}
        if unknown:
            console.print(f"[red]ERROR:[/red] unknown slug(s): {', '.join(sorted(unknown))}")
            console.print(f"Run `python {Path(__file__).name} --list` for the catalog.")
            return 2
        selected = tuple(p for p in PROJECTS if p.slug in wanted)

    is_update = args.update_baseline
    mode = "update" if is_update else "compare"
    baseline = _load_baseline() if not is_update else {}
    new_baseline: dict[str, dict] = {}
    drift: list[str] = []

    console.print(
        Panel.fit(
            f"[bold]Corpus directory[/bold] [dim]{CORPUS_DIR}[/dim]\n"
            f"[bold]Baseline:[/bold] [dim]{BASELINE_PATH}[/dim] "
            f"[bold]mode={mode}[/bold]\n"
            f"[bold]Projects to process:[/bold] {len(selected)}",
            border_style="cyan",
        )
    )

    results: list[tuple[str, str, dict | None]] = []
    counts = {"ran": 0, "skipped": 0, "baseline": 0}

    # Rich progress bar: spinner + current-slug description + bar + N/M + elapsed.
    # ``transient=False`` keeps the bar visible after completion so the user
    # sees the final state; the summary table is printed below it.
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )
    with progress:
        task = progress.add_task("[cyan]Analyzing corpus…", total=len(selected))
        for p in selected:
            # Live description shows the slug currently being analyzed so
            # the user knows which project the bar is sitting on (matters
            # for monika_after_story at 122 .rpy — takes 3+ seconds).
            progress.update(task, description=f"[cyan]Analyzing [bold]{p.slug}[/bold]…")
            result = _run_one(p.slug)
            if result is None:
                counts["skipped"] += 1
                results.append((p.slug, "skipped", None))
            elif is_update:
                new_baseline[p.slug] = _baseline_entry(result)
                counts["baseline"] += 1
                results.append((p.slug, "baseline", result))
            else:
                drift.extend(_drift_report(p.slug, result, baseline))
                counts["ran"] += 1
                results.append((p.slug, "ran", result))
            progress.advance(task)

    console.print()  # blank line between progress bar and summary table
    console.print(_run_summary_table(results))

    # Final count line, color-coded by status. Only non-zero counts are
    # shown — in compare mode ``baseline`` is always 0 (and vice versa),
    # so we skip the noise.
    summary_parts: list[str] = []
    if counts["ran"]:
        summary_parts.append(f"[green]ran={counts['ran']}[/green]")
    if counts["baseline"]:
        summary_parts.append(f"[blue]baseline={counts['baseline']}[/blue]")
    if counts["skipped"]:
        summary_parts.append(f"[yellow]skipped={counts['skipped']}[/yellow]")
    console.print("\n[bold]Done.[/bold] " + "  ".join(summary_parts))

    if is_update and new_baseline:
        _save_baseline(new_baseline)
        console.print(
            f"Wrote baseline ([bold]{len(new_baseline)}[/bold] projects) "
            f"-> [dim]{BASELINE_PATH}[/dim]"
        )

    if not is_update and drift:
        console.print("\n[bold]Drift vs baseline:[/bold]")
        for line in drift:
            # Lines from _drift_report carry rich markup tags
            # (e.g. ``[green]+2[/green]``) — console.print renders them.
            console.print(line)
        return 1  # signal drift to CI (CORPUS-8 catches this)

    return 0


if __name__ == "__main__":
    sys.exit(main())
