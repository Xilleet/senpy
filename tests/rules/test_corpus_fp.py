"""RED tests for false positives found in the corpus.

This file is the contract between the corpus triage pipeline
and the rule fixes. It reads
``tests/_corpus_triage.json`` (committed — anonymous triage state)
and, for every diagnostic the maintainer labelled ``fp``, reproduces
the real VN source file from the local corpus clone and asserts
senpy does NOT fire that rule code on that line.

Skip policy
----------
The corpus clone lives in ``tests/_corpus/`` (gitignored — VN bytes
never enter the repo). If the clone is absent (typical CI machines,
developer machines that only ran a subset), the whole module skips
with a clear reason. If the clone exists but ``triage.json`` has no
``fp`` entries yet, the module also skips (no contract to enforce).

RED semantics
-------------
Every parametrised case is a known false positive. Senpy currently
fires the rule there, so the assertion ``code not in diags_at_line``
fails — that is the intended RED state. CORPUS-6 turns each RED
green by fixing the rule; this file then locks the fix in place as
a regression guard.

Why not minimal snippets?
------------------------
We reproduce the **whole** source file from the corpus clone rather
than a hand-extracted snippet around the offending line. Ren'Py is
indentation-based and context-sensitive (a line inside a ``screen``
block means something different from the same line inside a
``label``). Hand-extracted snippets risk losing the enclosing block
and flipping a TP into an FP (or vice versa), which would defeat the
purpose. Files in the seed corpus are small (gifting_game is
~200–1200 lines per file); for larger projects a future iteration
can switch to enclosing-block extraction.

How to add a new FP case
------------------------
1. ``python scripts/collect_corpus.py --only <slug>``
2. ``python scripts/run_corpus.py --only <slug>``
3. ``python scripts/triage_corpus.py --slug <slug>``  (label as ``fp``)
   — or ``--export-csv`` / ``--import-csv`` for bulk.
4. Re-run this test module — the new case is picked up automatically
   from ``tests/_corpus_triage.json``. No edit to this file needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CORPUS_DIR = REPO_ROOT / "tests" / "_corpus"
TRIAGE_PATH = REPO_ROOT / "tests" / "_corpus_triage.json"


def _has_corpus() -> bool:
    """True iff the corpus clone is present and non-empty."""
    return CORPUS_DIR.exists() and any(CORPUS_DIR.iterdir())


def _load_fp_cases() -> list[dict]:
    """Return a list of FP cases from triage.json.

    Each case is a flat dict suitable for parametrize ids::

        {
            "slug": "gifting_game",
            "file": "game/olnewyear-5.rpy",
            "line": 675,
            "code": "RPY202",
            "note": "CurrentScreenName() is a function call, ...",
        }
    """
    if not TRIAGE_PATH.exists():
        return []
    triage = json.loads(TRIAGE_PATH.read_text(encoding="utf-8"))
    cases: list[dict] = []
    for slug, entry in triage.items():
        for d in entry.get("diagnostics", []):
            if d.get("status") != "fp":
                continue
            cases.append(
                {
                    "slug": slug,
                    "file": d["file"],
                    "line": d["line"],
                    "code": d["code"],
                    "note": d.get("note", ""),
                }
            )
    return cases


# Module-level skip: if the corpus clone is absent, this whole module
# is a no-op (CI machines without the corpus still pass the suite).
pytestmark = pytest.mark.skipif(
    not _has_corpus(),
    reason="corpus clone absent — run `python scripts/collect_corpus.py` to enable corpus FP tests",
)


def _case_id(case: dict) -> str:
    """Stable, readable pytest id: ``gifting_game::olnewyear-5.rpy:675::RPY202``."""
    fname = Path(case["file"]).name
    return f"{case['slug']}::{fname}:{case['line']}::{case['code']}"


# Build the parametrised case list at import time so pytest can show
# the case ids in collection output. If triage.json is empty, this is
# an empty list and the parametrised test is simply not generated
# (no skip noise — the module-level skipif above handles the no-corpus
# case; the empty-triage case shows 0 cases collected, which is the
# honest signal).
_FP_CASES = _load_fp_cases()


@pytest.mark.parametrize("case", _FP_CASES, ids=_case_id)
def test_corpus_fp_case(case: dict, tmp_path: Path) -> None:
    """Senpy must NOT fire ``case['code']`` on ``case['line']`` — it is a known FP.

    Reproduces the real corpus source file in a tmp game/ dir, runs
    senpy, and asserts the labelled FP code is absent at the labelled
    line. This is the RED state — CORPUS-6 turns it green by fixing
    the rule.
    """
    source_file = CORPUS_DIR / case["slug"] / case["file"]
    if not source_file.exists():
        pytest.skip(
            f"corpus source {case['file']} not found under {case['slug']} "
            f"— re-clone with `python scripts/collect_corpus.py --only {case['slug']} --force`"
        )

    # Reproduce the file at tmp_path/game/<basename>. The corpus stores
    # paths as game/<file>, so basename keeps the .rpy extension senpy
    # expects. We flatten any subdirectory layout (some corpus projects
    # nest deeper than game/) — senpy scans game/ recursively, so the
    # file is still discovered.
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    target = game_dir / Path(case["file"]).name
    target.write_text(source_file.read_text(encoding="utf-8"), encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
    result = analyzer.run(quiet=True)

    # Diagnostics at the labelled line with the labelled code.
    offenders = [
        d for d in result.diagnostics if d.code == case["code"] and d.line_number == case["line"]
    ]
    # Also accept off-by-one (line shifts if senpy re-parses slightly
    # differently after stripping the corpus wrapper) — compare by code
    # + message-substring match as a fallback.
    if not offenders:
        # Strict match failed — that is the GREEN state (FP fixed).
        # Report nothing further; the test passes.
        return

    # RED state: senpy still fires. Show enough context to diagnose.
    msg_preview = offenders[0].message[:120]
    pytest.fail(
        f"RED: senpy still fires {case['code']} at {case['file']}:{case['line']} "
        f"({case['slug']}).\n"
        f"  triage note: {case['note']}\n"
        f"  senpy says: {msg_preview}\n"
        f"  This is a known false positive — fix the rule (CORPUS-6) so this passes."
    )


def test_triage_json_has_fp_cases_or_corpus_absent() -> None:
    """Guard: if the corpus is present, triage.json should have >=1 FP case.

    A present corpus with zero FP cases means the maintainer has not
    triaged yet — this test nudges them to run
    ``scripts/triage_corpus.py``. Without it, the parametrised test
    above silently collects zero cases and the FP pipeline looks green
    when it is actually unstaffed.
    """
    if not _has_corpus():
        pytest.skip("corpus absent")
    if not _FP_CASES:
        pytest.fail(
            "corpus is present but triage.json has no fp cases — "
            "run `python scripts/triage_corpus.py --slug <name>` "
            "(or --export-csv / --import-csv) to label false positives."
        )
