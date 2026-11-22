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

# Root of the senpy repo (parent of this script's directory).
REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "tests" / "_corpus"


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


def _clone(project: Project, force: bool, dry_run: bool) -> str:
    """Clone (or re-clone) one project. Returns 'cloned'|'skipped'|'forced'."""
    target = CORPUS_DIR / project.slug
    is_git_repo = target.exists() and (target / ".git").exists()

    if is_git_repo and not force:
        return "skipped"

    if dry_run:
        return "forced" if is_git_repo else "cloned"

    if target.exists():
        # Removes either an existing repo (when force=True) or a stale dir without .git.
        shutil.rmtree(target)

    # --depth 1 keeps the clone small (shallow). --single-branch avoids
    # pulling other branches' refs. We pin the cloned commit SHA into
    # .cloned_sha so CORPUS-3 / baseline tooling can detect upstream
    # movement (a re-clone is needed to pick up new commits).
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        _git("clone", "--depth", "1", "--single-branch", project.url, str(target))
    except subprocess.CalledProcessError as e:
        print(f"  ERROR cloning {project.slug}: {e.stderr.strip()}", file=sys.stderr)
        return "error"

    # Record the cloned HEAD SHA.
    try:
        sha = _git("rev-parse", "HEAD", cwd=target).stdout.strip()
        (target / ".cloned_sha").write_text(sha + "\n", encoding="utf-8")
    except subprocess.CalledProcessError:
        pass  # non-fatal — clone succeeded, just can't pin SHA

    return "cloned"


def list_catalog() -> None:
    """Print the catalog as a table."""
    print(f"{'SLUG':<28} {'REPO':<55} {'NOTES'}")
    print("-" * 28 + " " + "-" * 55 + " " + "-" * 40)
    for p in PROJECTS:
        print(f"{p.slug:<28} {p.repo:<55} {p.notes}")
    print(f"\n{len(PROJECTS)} projects. Clone destination: {CORPUS_DIR}")
    print("(tests/_corpus/ is gitignored — VN source stays local.)")


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
            print(f"ERROR: unknown slug(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            print(f"Run `python {Path(__file__).name} --list` for the catalog.", file=sys.stderr)
            return 2
        selected = tuple(p for p in PROJECTS if p.slug in wanted)

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)

    counts = {"cloned": 0, "skipped": 0, "forced": 0, "error": 0}
    print(f"Corpus directory: {CORPUS_DIR}")
    print(f"Projects to process: {len(selected)} (force={args.force}, dry_run={args.dry_run})\n")
    for p in selected:
        status = _clone(p, force=args.force, dry_run=args.dry_run)
        counts[status] = counts.get(status, 0) + 1
        marker = {
            "cloned": "+",
            "skipped": "=",
            "forced": "!",
            "error": "x",
        }.get(status, "?")
        print(f"  [{marker}] {p.slug:<28} {status}")
    print(
        f"\nDone. cloned={counts['cloned']} skipped={counts['skipped']} "
        f"forced={counts['forced']} error={counts['error']}"
    )
    if counts["error"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
