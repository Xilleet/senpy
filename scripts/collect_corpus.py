#!/usr/bin/env python3
"""Clone a curated corpus of open-source Ren'Py visual novels.

The corpus is used to catch false positives / false negatives in the
senpy rule set against real-world VN code.

Architecture (hybrid):
    - VN source lives in ``tests/_corpus/<project>/`` LOCALLY only.
      The directory is gitignored — no VN bytes enter the repo.
    - Metadata (baseline + triage JSON, pytest tests) is committed.
    - ``scripts/run_corpus.py`` runs senpy per project;
      ``tests/rules/test_corpus_fp.py`` compares against
      ``tests/_corpus_baseline.json`` and skips if the corpus is absent.

This script:
    - shallow-clones (``--depth 1``) each project into
      ``tests/_corpus/<slug>/``;
    - is idempotent — if ``<slug>/.git`` exists, the project is skipped
      unless ``--force`` is passed (which removes and re-clones);
    - records the cloned commit SHA in ``tests/_corpus/<slug>/.cloned_sha``
      so CORPUS-3 / baseline tooling can pin to a specific revision.

Usage:
    python scripts/collect_corpus.py                 # clone all 15
    python scripts/collect_corpus.py --list          # print the catalog
    python scripts/collect_corpus.py --only ddlc     # clone one by slug
    python scripts/collect_corpus.py --force         # re-clone existing
    python scripts/collect_corpus.py --dry-run        # plan only, no clone

The catalog (``PROJECTS`` below) was built by web-searching GitHub for
public OSS VN projects, then verifying each URL with ``git ls-remote``
and a shallow clone + ``find ... -name '*.rpy'`` to confirm it actually
contains Ren'Py scripts. Projects with 0 ``.rpy`` files were dropped
(e.g. ``gcammisa/KatawaShoujo-RenPy8`` is a port without scripts, and
``fleetingheart/ksre`` is a re-engineered fork that stores scripts in a
non-standard layout).

License hygiene: each project keeps its own ``LICENSE`` (or lack of
one) inside its shallow clone — we never redistribute VN source, only
run senpy against it locally. Do not commit anything under
``tests/_corpus/``.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
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

# Root of the senpy repo (parent of this script's directory).
REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "tests" / "_corpus"

console = Console()


@dataclass(frozen=True)
class Project:
    """A corpus entry."""

    slug: str  # short identifier, also the directory name under tests/_corpus/
    repo: str  # GitHub ``owner/name``
    url: str  # full HTTPS clone URL
    notes: str  # one-line description (type + size class) for the catalog


def _p(slug: str, repo: str, notes: str) -> Project:
    return Project(slug=slug, repo=repo, url=f"https://github.com/{repo}.git", notes=notes)


# Curated corpus. 15 projects spanning DDLC mods, full VN games, mod
# templates, starter templates, educational VNs and small demos —
# deliberately diverse so the rule set is exercised against a wide
# range of Ren'Py idioms (label/label-call, screen actions, define
# audio, image references, ATL transforms, python blocks).
PROJECTS: tuple[Project, ...] = (
    _p(
        "ddlc",
        "SecondThundeR/DokiDoki-RenPy",
        "DDLC 1.1.1 decompiled (~35 .rpy). Real-world VN with heavy screen action / python use.",
    ),
    _p(
        "learntocode",
        "freeCodeCamp/LearnToCodeRPG",
        "Educational VN from freeCodeCamp (~60 .rpy). Large, well-structured, modern Ren'Py.",
    ),
    _p(
        "ddlc_mod_template",
        "Bronya-Rand/DDLCModTemplate2.0",
        "DDLC mod template 2.0 (~40 .rpy). Community-standard mod scaffolding.",
    ),
    _p(
        "monika_after_story",
        "Monika-After-Story/MonikaModDev",
        "Monika After Story (~122 .rpy). Largest entry — long-running mod with complex state.",
    ),
    _p(
        "ddlc_mod_template_zchrxh",
        "zchrxh/Doki-Doki-Mod-Template",
        "Alternate DDLC mod template (~49 .rpy). Different idioms than Bronya-Rand.",
    ),
    _p(
        "renpy_template_ruolin",
        "RuolinZheng08/renpy-template",
        "Starter template (~11 .rpy). Small, well-commented reference code.",
    ),
    _p(
        "renpy_vn_template_dual",
        "dualfighter1/Renpy-VN-Template",
        "Simple VN template (~10 .rpy). Minimal label/return structure.",
    ),
    _p(
        "bytes_of_love",
        "ufosc/VisualNovel",
        "BytesOfLove VN by ufosc (~29 .rpy). Student-built, university club.",
    ),
    _p(
        "avnovel",
        "crcdng/avnovel",
        "Audiovisual novel demo (~4 .rpy). Tiny project — smoke-tests minimal fixtures.",
    ),
    _p(
        "cross_channel",
        "MewX/cross-channel_chinese-localization_project",
        "cross_channel Chinese localization (~302 .rpy). Largest .rpy count — broad coverage.",
    ),
    _p(
        "love69",
        "luckykeeper/LOVE69_renpy_remaster",
        "LOVE69 Ren'Py remaster (~29 .rpy). Localization-heavy, defines audio channels.",
    ),
    _p(
        "aqua_guardians",
        "sk66641/AquaGuardians",
        "AquaGuardians VN (~10 .rpy). Small standalone game.",
    ),
    _p(
        "personal_space2",
        "qirien/personal-space2",
        "personal-space2 VN (~31 .rpy). Indie VN with translations.",
    ),
    _p("cold_hands", "hud0shnik/cold_hands", "cold_hands VN (~8 .rpy). Small modern VN."),
    _p(
        "gifting_game",
        "alchemmist/gifting-game",
        "gifting-game VN (~4 .rpy). Holiday-themed short VN.",
    ),
)


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run git with captured output, defaulting to check=True."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _clone(project: Project, force: bool, dry_run: bool) -> tuple[str, str]:
    """Clone (or re-clone) one project.

    Returns ``(status, detail)`` where status is one of
    ``cloned``|``skipped``|``forced``|``error`` and detail is a short
    human-readable note (the cloned SHA, the skip reason, or the
    error message).
    """
    target = CORPUS_DIR / project.slug
    is_git_repo = target.exists() and (target / ".git").exists()

    if is_git_repo and not force:
        return ("skipped", "already cloned")

    if dry_run:
        return ("forced", "dry-run") if is_git_repo else ("cloned", "dry-run")

    if target.exists():
        # Removes either an existing repo (when force=True) or a stale dir without .git.
        # Remember whether we are re-cloning (force=True on an existing repo) so
        # the caller can report ``forced`` rather than ``cloned`` for re-clones.
        was_force_reclone = force and is_git_repo
        shutil.rmtree(target)
    else:
        was_force_reclone = False

    # --depth 1 keeps the clone small (shallow). --single-branch avoids
    # pulling other branches' refs. We pin the cloned commit SHA into
    # .cloned_sha so CORPUS-3 / baseline tooling can detect upstream
    # movement (a re-clone is needed to pick up new commits).
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        _git("clone", "--depth", "1", "--single-branch", project.url, str(target))
    except subprocess.CalledProcessError as e:
        return ("error", e.stderr.strip() or "git clone failed")

    # Record the cloned HEAD SHA.
    sha = ""
    try:
        sha = _git("rev-parse", "HEAD", cwd=target).stdout.strip()
        (target / ".cloned_sha").write_text(sha + "\n", encoding="utf-8")
    except subprocess.CalledProcessError:
        pass  # non-fatal — clone succeeded, just can't pin SHA

    detail = sha[:10] if sha else "HEAD (SHA unavailable)"
    return ("forced" if was_force_reclone else "cloned", detail)


def list_catalog() -> None:
    """Print the catalog as a rich table."""
    table = Table(title="Corpus catalog", show_lines=False, expand=True)
    table.add_column("Slug", style="bold cyan", no_wrap=True)
    table.add_column("Repo", style="white")
    table.add_column("Notes", style="dim")
    for p in PROJECTS:
        table.add_row(p.slug, p.repo, p.notes)
    console.print(table)
    console.print(
        f"\n[bold]{len(PROJECTS)}[/bold] projects. "
        f"Clone destination: [dim]{CORPUS_DIR}[/dim] (gitignored — VN source stays local.)"
    )


# Per-status styling for the final summary table.
_STATUS_STYLE: dict[str, tuple[str, str]] = {
    "cloned": ("green", "✓"),
    "skipped": ("yellow", "≈"),
    "forced": ("blue", "↻"),
    "error": ("red", "✗"),
}


def _summary_table(results: list[tuple[Project, str, str]]) -> Table:
    """Build the per-project result table shown after the run."""
    table = Table(title="Clone results", show_lines=False, expand=True)
    table.add_column("", width=1)
    table.add_column("Slug", style="bold", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Detail")
    for project, status, detail in results:
        style, mark = _STATUS_STYLE.get(status, ("white", "?"))
        table.add_row(mark, project.slug, f"[{style}]{status}[/{style}]", detail)
    return table


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clone a curated corpus of open-source Ren'Py VNs for senpy FP/FN testing.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the project catalog and exit (no network)",
    )
    parser.add_argument(
        "--only",
        metavar="SLUG",
        help="clone only one project (by slug); can be repeated via comma, e.g. --only ddlc,monika",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-clone projects that already exist (removes and re-clones)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan (what would be cloned / skipped) without touching the filesystem",
    )
    args = parser.parse_args()

    if args.list:
        list_catalog()
        return 0

    # Filter to the requested subset.
    selected = PROJECTS
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        unknown = wanted - {p.slug for p in PROJECTS}
        if unknown:
            console.print(f"[red]ERROR:[/red] unknown slug(s): {', '.join(sorted(unknown))}")
            console.print(f"Run `python {Path(__file__).name} --list` for the catalog.")
            return 2
        selected = tuple(p for p in PROJECTS if p.slug in wanted)

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)

    console.print(
        Panel.fit(
            f"[bold]Corpus directory[/bold] [dim]{CORPUS_DIR}[/dim]\n"
            f"[bold]Projects to process:[/bold] {len(selected)}  "
            f"[dim](force={args.force}, dry_run={args.dry_run})[/dim]",
            border_style="cyan",
        )
    )

    results: list[tuple[Project, str, str]] = []
    counts: dict[str, int] = {"cloned": 0, "skipped": 0, "forced": 0, "error": 0}

    # Rich progress bar: spinner + description + bar + N/M + elapsed.
    # ``transient=False`` keeps the bar visible after completion so the
    # user sees the final state; the summary table is printed below it.
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
        task = progress.add_task("[cyan]Cloning corpus…", total=len(selected))
        for p in selected:
            # Live label shows the slug currently being worked on so
            # the user knows which clone the bar is sitting on.
            progress.update(task, description=f"[cyan]Cloning [bold]{p.slug}[/bold]…")
            status, detail = _clone(p, force=args.force, dry_run=args.dry_run)
            counts[status] = counts.get(status, 0) + 1
            results.append((p, status, detail))
            progress.advance(task)

    console.print()  # blank line between progress bar and summary table
    console.print(_summary_table(results))

    # Final count line, color-coded by whether any errors happened.
    summary_parts = [
        f"[green]cloned={counts['cloned']}[/green]",
        f"[yellow]skipped={counts['skipped']}[/yellow]",
        f"[blue]forced={counts['forced']}[/blue]",
        f"[red]error={counts['error']}[/red]",
    ]
    console.print("\n[bold]Done.[/bold] " + "  ".join(summary_parts))
    if counts["error"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
