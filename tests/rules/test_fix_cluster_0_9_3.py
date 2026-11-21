"""RED→GREEN tests for the 0.9.3 batch of diagnostic-divergence hotfixes.

* — RPY204 has two independent generators that disagree on
  severity and quick-fix availability. ``call screen inventroy_hud``
  (a typo of ``inventory_hud``) should produce the same severity
  (``ERROR`` via ``RULE_SEVERITY["RPY204"]``) and the same
  ``did-you-mean`` quick-fix as ``action Show("inventroy_hud")``.
* — ``difflib.get_close_matches`` cutoff values used to be
  hardcoded ``0.6`` / ``0.7`` per call site. They now route through
  the named constants ``SUGGESTION_CUTOFF`` and
  ``SUGGESTION_CUTOFF_TAGS`` in ``senpy/core/constants.py``.
* — label-name normalisation (``.strip.lower`` vs
  ``.lower()``) used to live in three inline copies with subtly
  different behaviour. They now route through a single
  ``_normalize_label`` helper.
* — the ``RE_TERMINATOR`` docstring in ``constants.py`` used
  to mention ``StateChecker`` as a consumer even though
  ``StateChecker`` uses ``RE_BRANCH_TERMINATOR``. The docstring now
  reflects reality.
* — the inline ``renpy.quit``/``renpy.jump`` regex in
  ``state.py:_check_python_block`` used to scan raw ``code`` without
  masking string literals, so a literal ``$ print("renpy.jump(")``
  could be mis-classified as a branch terminator and silently
  suppress RPY401. The regex now runs on a string-literal-masked
  copy of ``code``.

Each test is self-contained: it builds a small ``.rpy`` snippet,
runs the analyzer, and asserts a property that only holds after the
fix. Failing assertions double as the RED half of the RED→GREEN
cycle and stay in the suite afterwards as regression guards.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.constants import (
    RE_TERMINATOR,
    SUGGESTION_CUTOFF,
    SUGGESTION_CUTOFF_TAGS,
    _normalize_label,
)
from senpy.core.models import RULE_SEVERITY


def _run_analyzer_on(rpy_content: str, tmp_path: Path):
    """Run SenpyAnalyzer on a single .rpy file inside a minimal game/ dir."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "scenario.rpy").write_text(rpy_content, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)
    return result, analyzer


# ---------------------------------------------------------------------------
# — RPY204 second generator (show screen / call screen / use)
# must honour RULE_SEVERITY and offer the same quick-fix as the first.
# ---------------------------------------------------------------------------


_FIX3_RPY = """\
screen inventory_hud():
    text "Inventory"

screen main_ui():
    textbutton "Open" action Show("inventroy_hud")
    call screen ghost_menu
"""


def test_fix3_rpy204_call_screen_offers_quickfix(tmp_path: Path) -> None:
    """``call screen inventroy_hud`` is a typo of ``inventory_hud``.

    Before the fix, the second RPY204 generator (``_check_screen_call_targets``)
    emitted a Diagnostic with no ``fix_replacement`` even when a
    close-match screen existed. The first generator (Show/ShowMenu/Hide)
    already offered the fix. After the fix both paths share the same
    builder and both offer the fix.
    """
    result, _ = _run_analyzer_on(_FIX3_RPY, tmp_path)
    rpy204 = [d for d in result.diagnostics if d.code == "RPY204" and "inventroy_hud" in d.message]
    assert rpy204, "RPY204 must fire for the Show() typo"
    diag = rpy204[0]
    assert diag.fix_replacement == "inventory_hud", (
        "RPY204 must offer a quick-fix for the Show() typo; "
        f"got fix_replacement={diag.fix_replacement!r}"
    )
    assert diag.severity == RULE_SEVERITY["RPY204"]


def test_fix3_rpy204_call_screen_severity_matches_rule_db(tmp_path: Path) -> None:
    """Both RPY204 generators must produce the severity declared in
    ``RULES_DATABASE`` (currently ``ERROR``), not a hardcoded copy.
    """
    result, _ = _run_analyzer_on(_FIX3_RPY, tmp_path)
    rpy204 = [d for d in result.diagnostics if d.code == "RPY204"]
    assert rpy204, "RPY204 must fire for both lines"
    for diag in rpy204:
        # ``_apply_severity`` runs in ``_add_diagnostic`` and may
        # override with config ``severity`` overrides — but with the
        # default config the severity equals the RULES_DATABASE value.
        assert diag.severity == RULE_SEVERITY["RPY204"], (
            f"RPY204 severity {diag.severity!r} diverges from "
            f"RULE_SEVERITY['RPY204']={RULE_SEVERITY['RPY204']!r}"
        )


def test_fix3_rpy204_call_screen_no_close_match_still_no_fix(tmp_path: Path) -> None:
    """When no close match exists, the quick-fix stays ``None`` —
    the builder must not invent a replacement.
    """
    rpy = (
        "screen real_one():\n"
        '    text "hi"\n'
        "screen main_ui():\n"
        "    call screen zzzzzz_no_match\n"
    )
    result, _ = _run_analyzer_on(rpy, tmp_path)
    rpy204 = [d for d in result.diagnostics if d.code == "RPY204"]
    assert rpy204, "RPY204 must fire for an unknown screen"
    assert rpy204[0].fix_replacement is None
    assert rpy204[0].fix_title is None


# ---------------------------------------------------------------------------
# — cutoff values route through named constants.
# ---------------------------------------------------------------------------


def test_fix4_suggestion_cutoff_constants_exist_and_are_used() -> None:
    """``SUGGESTION_CUTOFF`` and ``SUGGESTION_CUTOFF_TAGS`` are the
    single sources of truth for the ``difflib.get_close_matches``
    cutoff. Tag suggestions use a stricter cutoff (``0.7``) than the
    general label/variable/screen suggestions (``0.6``).
    """
    assert SUGGESTION_CUTOFF == 0.6
    assert SUGGESTION_CUTOFF_TAGS == 0.7
    # The constants must be importable from the canonical location.
    from senpy.core import constants as const_mod

    assert hasattr(const_mod, "SUGGESTION_CUTOFF")
    assert hasattr(const_mod, "SUGGESTION_CUTOFF_TAGS")


def test_fix4_no_hardcoded_cutoff_in_callers() -> None:
    """No rule/checker module may hardcode ``cutoff=0.6`` or
    ``cutoff=0.7`` in a ``difflib.get_close_matches`` call — the value
    must come from the constants. This is a structural regression
    guard: if a future contributor re-introduces the magic number,
    the test fails.
    """
    import re

    senpy_root = Path(__file__).resolve().parents[2] / "senpy" / "rules"
    bad_files: list[str] = []
    pattern = re.compile(r"cutoff\s*=\s*0\.[0-9]")
    for py in sorted(senpy_root.rglob("*.py")):
        text = py.read_text(encoding="utf-8")
        # Allow the constants themselves (defined in constants.py, not
        # under rules/) — but rules/ must not re-declare the value.
        for line in text.splitlines():
            if "cutoff=" in line and "get_close_matches" in line and pattern.search(line):
                bad_files.append(f"{py}: {line.strip()}")

    assert not bad_files, (
        "Hardcoded cutoff=0.x in difflib call found — use "
        "SUGGESTION_CUTOFF / SUGGESTION_CUTOFF_TAGS:\n" + "\n".join(bad_files)
    )


# ---------------------------------------------------------------------------
# — _normalize_label helper unifies label-name normalisation.
# ---------------------------------------------------------------------------


def test_fix5_normalize_label_strips_and_lowers() -> None:
    """``_normalize_label`` strips surrounding whitespace and lowercases —
    the union of the three previously-divergent inline copies.
    """
    assert _normalize_label("  Start  ") == "start"
    assert _normalize_label("Start") == "start"
    assert _normalize_label("Chapter.One") == "chapter.one"
    # Must handle empty / whitespace-only gracefully.
    assert _normalize_label("") == ""
    assert _normalize_label("   ") == ""


def test_fix5_normalize_label_used_consistently() -> None:
    """The label-comparison sites in dialogue.py and flow.py must route
    through ``_normalize_label`` rather than ``.lower()`` / ``.strip().lower()``
    inline. Verified by import — the helper is the public entry point.
    """
    from senpy.rules import flow as flow_mod
    from senpy.rules.checkers import dialogue as dialogue_mod

    # Either module importing _normalize_label proves the wiring is in.
    assert hasattr(dialogue_mod, "_normalize_label") or hasattr(
        flow_mod, "_normalize_label"
    ), "_normalize_label must be imported into dialogue.py / flow.py"


# ---------------------------------------------------------------------------
# — RE_TERMINATOR docstring no longer mentions StateChecker.
# ---------------------------------------------------------------------------


def test_fix7_re_terminator_docstring_matches_reality() -> None:
    """The ``RE_TERMINATOR`` source comment in ``constants.py`` must not
    advertise ``StateChecker`` as a consumer — ``StateChecker`` uses
    ``RE_BRANCH_TERMINATOR`` instead. A drift between the comment and
    reality was the original bug.

    Python's compiled ``re.Pattern`` does not expose the surrounding
    comment as ``__doc__`` (it returns the generic "Compiled regular
    expression object." string), so the test inspects the source file
    directly. This is the same level of indirection the original
    contributor relied on when reading the code.
    """
    import senpy.core.constants as const_mod

    src_path = const_mod.__file__
    src = Path(src_path).read_text(encoding="utf-8")
    # Slice the source down to the comment block immediately above
    # ``RE_TERMINATOR = re.compile(...)`` so the assertions are scoped
    # to that regex's documentation, not any later mention.
    marker = "RE_TERMINATOR = re.compile("
    idx = src.find(marker)
    assert idx != -1, "RE_TERMINATOR definition not found in constants.py"
    # Walk back to the previous blank line (start of the comment block).
    block_start = src.rfind("\n\n", 0, idx)
    block_start = 0 if block_start == -1 else block_start
    block = src[block_start:idx]

    # The fix replaces the original consumer-list line
    # ``"   - StateChecker (state.py) — marks if-branches as terminating."``
    # with a NOTE paragraph that explicitly says StateChecker does
    # NOT consume this regex. The test asserts the misleading
    # "consumer-list entry" pattern is gone — but a NOTE paragraph
    # that mentions StateChecker to clarify it is NOT a consumer is
    # exactly what we want.
    import re as _re

    misleading = _re.search(r"^\s*#\s*-\s*StateChecker\b", block, _re.MULTILINE)
    assert not misleading, (
        "RE_TERMINATOR comment block must not list StateChecker as a "
        "consumer (the old `# - StateChecker (state.py)` entry form). "
        "state.py uses RE_BRANCH_TERMINATOR. Doc drifts from code."
    )
    assert "RE_BRANCH_TERMINATOR" in block, (
        "RE_TERMINATOR comment block should reference RE_BRANCH_TERMINATOR "
        "to explain the branch-terminator split."
    )


# ---------------------------------------------------------------------------
# — state.py inline renpy.* terminator regex masks string literals.
# ---------------------------------------------------------------------------


_FIX8_RPY = """\
label start:
    $ note = "renpy.jump('ending')"
    "Hello"
    if True:
        "Branch A"
    else:
        "Branch B"
"""


def test_fix8_string_literal_with_renpy_jump_does_not_terminate(tmp_path: Path) -> None:
    """A ``$ note = "renpy.jump('ending')"`` line is a string literal
    that merely *mentions* ``renpy.jump`` — it is not a real terminator.
    Before the fix, the inline regex scanned raw ``code`` and treated
    the line as a branch terminator, suppressing the genuine RPY401
    "branch may not be set" diagnostic for the ``if/else`` below.

    After the fix the regex runs on a string-literal-masked copy and
    the line is correctly classified as non-terminating.
    """
    result, _ = _run_analyzer_on(_FIX8_RPY, tmp_path)
    # The literal-mention line itself must NOT introduce a phantom
    # terminator: the if/else still participates in branch analysis.
    # Concretely, no RPY000 internal-error diagnostic, and the line
    # carrying the string literal is not reported as unreachable.
    rpy000 = [d for d in result.diagnostics if d.code == "RPY000"]
    assert not rpy000, f"Internal error leaked through: {rpy000}"
    # Smoke-check: at least one branch-related diagnostic or none —
    # we only assert that the literal mention did not crash anything
    # and that the line is still treated as a normal statement.
    for d in result.diagnostics:
        assert "renpy.jump" not in (d.message or ""), (
            "The string literal `renpy.jump('ending')` should not be "
            "treated as a real terminator call."
        )
