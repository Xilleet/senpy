"""Regression tests for false positives caused by substring/regex matching
of identifiers that live inside string literals.

The checkers do substring checks and regex scans on arbitrary Ren'Py lines
to detect UI actions (`Jump`, `Call`, `Show`, `SetVariable`, ...) and
Python calls (`renpy.jump`, `renpy.call`). Before this fix, any mention of
those keywords inside a string literal — dialogue text, Python string
constants, image names — was matched as if it were real code. This
produced two kinds of bugs:

    * False positives — diagnostics fired on dialogue lines like
      ``"The syntax Jump('missing_label') is interesting."``.
    * False negative cascade — a dialogue mention of ``renpy.jump()`` set
      the global ``has_dynamic_jumps`` flag, suppressing RPY701-707 across
      the entire project.

The fix introduces a `strip_string_literals()` helper in
``senpy/text_utils.py`` that masks the *content* of string literals with
spaces while preserving column positions of code outside literals. Each
affected checker now applies the helper before its substring/regex scan
and filters out matches that land inside literals.

These tests reproduce the original false positives and assert that:
    1. Mentions inside string literals no longer trigger diagnostics.
    2. The global ``has_dynamic_jumps`` flag is not flipped by dialogue.
    3. Label names that appear only inside strings are not added to
       ``referenced_labels``.
    4. Real action calls and real ``renpy.jump()`` calls are still
       detected — the fix does not over-suppress legitimate cases.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer


def _run_analyzer_on(rpy_content: str, tmp_path: Path):
    """Run SenpyAnalyzer on a single .rpy file inside a minimal game/ dir."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "scenario.rpy").write_text(rpy_content, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)
    return result, analyzer


# ---------------------------------------------------------------------------
# RPY302 — Jump/Call UI action inside dialogue text
# ---------------------------------------------------------------------------


def test_jump_in_dialogue_does_not_emit_rpy302(tmp_path: Path) -> None:
    """A dialogue line that mentions `Jump('missing_label')` is plain
    text — it must not be parsed as a UI action and must not emit RPY302.
    """
    rpy = """label start:
    "The syntax Jump('missing_label') is interesting."
    return
"""
    result, analyzer = _run_analyzer_on(rpy, tmp_path)
    rpy302 = [d for d in result.diagnostics if d.code == "RPY302"]
    assert rpy302 == [], (
        f"Expected 0 RPY302 for dialogue mention of Jump(...), got: "
        f"{[(d.line_number, d.message) for d in rpy302]}"
    )


def test_call_in_dialogue_does_not_emit_rpy302(tmp_path: Path) -> None:
    """Symmetric case for `Call(...)` — must not fire on dialogue text."""
    rpy = """label start:
    "The Call('foo') action is documented here."
    return
"""
    result, _ = _run_analyzer_on(rpy, tmp_path)
    rpy302 = [d for d in result.diagnostics if d.code == "RPY302"]
    assert rpy302 == []


def test_real_jump_action_still_emits_rpy302(tmp_path: Path) -> None:
    """Counter-case: a real `Jump("missing_label")` screen action must still
    emit RPY302. The fix must not over-suppress legitimate detections.
    """
    rpy = """screen nav():
    textbutton "Go" action Jump("nonexistent_label")
"""
    result, _ = _run_analyzer_on(rpy, tmp_path)
    rpy302 = [d for d in result.diagnostics if d.code == "RPY302"]
    assert len(rpy302) == 1, f"Expected exactly 1 RPY302 for real Jump action, got {len(rpy302)}"
    assert "nonexistent_label" in rpy302[0].message


def test_real_renpy_jump_in_python_block_still_detected(tmp_path: Path) -> None:
    """Counter-case: real `renpy.jump("missing")` in a Python block must
    still trigger RPY302 and set `has_dynamic_jumps=True`.
    """
    rpy = """label start:
    $ renpy.jump("nonexistent_target")
    return
"""
    result, analyzer = _run_analyzer_on(rpy, tmp_path)
    rpy302 = [d for d in result.diagnostics if d.code == "RPY302"]
    assert len(rpy302) == 1
    assert analyzer.has_dynamic_jumps is True


# ---------------------------------------------------------------------------
# Dynamic jumps flag — false positive when ``renpy.jump`` is mentioned in
# a dialogue string, false negative on space-separated calls.
# ---------------------------------------------------------------------------


def test_renpy_jump_in_dialogue_does_not_set_dynamic_flag(tmp_path: Path) -> None:
    """A dialogue line that mentions `renpy.jump()` must NOT set the
    global ``has_dynamic_jumps=True`` flag — that flag disables
    RPY701-707 across the entire project, a serious false suppression.
    """
    rpy = """label start:
    e "Use renpy.jump() to switch scenes."
    return
"""
    result, analyzer = _run_analyzer_on(rpy, tmp_path)
    assert (
        analyzer.has_dynamic_jumps is False
    ), "Dialogue mention of 'renpy.jump()' must not flip has_dynamic_jumps."


def test_real_renpy_jump_still_sets_dynamic_flag(tmp_path: Path) -> None:
    """Counter-case: actual `renpy.jump(target)` in a Python block still
    sets the flag.
    """
    rpy = """label start:
    $ renpy.jump(target)
    return
"""
    result, analyzer = _run_analyzer_on(rpy, tmp_path)
    assert analyzer.has_dynamic_jumps is True


def test_call_expression_string_does_not_set_dynamic_flag(tmp_path: Path) -> None:
    """A string literal containing the substring `call expression` (e.g.
    a documentation comment in a dialogue line) must not be detected as
    a real `call expression` statement.
    """
    rpy = """label start:
    "See the docs for 'call expression' usage."
    return
"""
    result, analyzer = _run_analyzer_on(rpy, tmp_path)
    assert analyzer.has_dynamic_jumps is False


# ---------------------------------------------------------------------------
# Referenced labels — label name appearing inside a string literal must not
# be treated as a real reference (RPY303 must still fire on the unused label).
# ---------------------------------------------------------------------------


def test_label_name_in_python_string_does_not_mark_referenced(
    tmp_path: Path,
) -> None:
    """The line `$ config.label_overrides = "unused_label"` is a Python
    string assignment. The label `unused_label` is NOT actually called or
    jumped to — its name appears only as a string literal. RPY303 (label
    never referenced) must fire on `unused_label`.
    """
    rpy = """label unused_label:
    return

label start:
    $ config.label_overrides = "unused_label"
    return
"""
    result, analyzer = _run_analyzer_on(rpy, tmp_path)
    rpy303 = [d for d in result.diagnostics if d.code == "RPY303"]
    assert any("unused_label" in d.message for d in rpy303), (
        f"Expected RPY303 for 'unused_label' (it is not actually referenced), "
        f"got: {[(d.line_number, d.message) for d in rpy303]}"
    )
    assert "unused_label" not in analyzer.referenced_labels


def test_label_name_in_dialogue_does_not_mark_referenced(
    tmp_path: Path,
) -> None:
    """Symmetric case: a label name appearing inside a dialogue string
    must not be added to `referenced_labels`.
    """
    rpy = """label secret_ending:
    return

label start:
    "The secret_ending is not actually accessible."
    return
"""
    result, analyzer = _run_analyzer_on(rpy, tmp_path)
    rpy303 = [d for d in result.diagnostics if d.code == "RPY303"]
    assert any("secret_ending" in d.message for d in rpy303), (
        f"Expected RPY303 for 'secret_ending' — it is only mentioned in "
        f"dialogue, not referenced. Got: "
        f"{[(d.line_number, d.message) for d in rpy303]}"
    )


def test_real_jump_to_label_marks_referenced(tmp_path: Path) -> None:
    """Counter-case: a real `jump foo` statement must mark `foo` as
    referenced. The fix must not over-suppress legitimate references.
    """
    rpy = """label real_target:
    return

label start:
    jump real_target
"""
    result, analyzer = _run_analyzer_on(rpy, tmp_path)
    assert "real_target" in analyzer.referenced_labels
    rpy303 = [d for d in result.diagnostics if d.code == "RPY303"]
    assert not any("real_target" in d.message for d in rpy303)


def test_real_jump_action_in_screen_marks_referenced(tmp_path: Path) -> None:
    """Counter-case: `Jump("real_label")` in a screen action must add the
    label to `referenced_labels`. This is the legitimate detection that
    the fix must preserve.
    """
    rpy = """label real_target:
    return

screen nav():
    textbutton "Go" action Jump("real_target")
"""
    result, analyzer = _run_analyzer_on(rpy, tmp_path)
    assert "real_target" in analyzer.referenced_labels


# ---------------------------------------------------------------------------
# RPY204 — Show/ShowMenu/Hide inside screen `text "..."` lines
# ---------------------------------------------------------------------------


def test_show_in_screen_text_does_not_emit_rpy204(tmp_path: Path) -> None:
    """A `text "Press Show('missing_screen') to continue."` line inside a
    screen is a UI label, not an action call. It must not trigger RPY204.
    """
    rpy = """screen some_screen():
    text "Press Show('missing_screen') to continue."
"""
    result, _ = _run_analyzer_on(rpy, tmp_path)
    rpy204 = [d for d in result.diagnostics if d.code == "RPY204"]
    assert rpy204 == [], (
        f"Expected 0 RPY204 for Show() inside screen text dialog, got: "
        f"{[(d.line_number, d.message) for d in rpy204]}"
    )


def test_real_show_action_still_emits_rpy204(tmp_path: Path) -> None:
    """Counter-case: a real `Show("nonexistent_screen")` action must still
    emit RPY204.
    """
    rpy = """screen some_screen():
    textbutton "Open" action Show("nonexistent_screen")
"""
    result, _ = _run_analyzer_on(rpy, tmp_path)
    rpy204 = [d for d in result.diagnostics if d.code == "RPY204"]
    assert len(rpy204) == 1
    assert "nonexistent_screen" in rpy204[0].message


# ---------------------------------------------------------------------------
# RPY202 — SetVariable/ToggleVariable inside screen `text "..."` lines
# ---------------------------------------------------------------------------


def test_setvariable_in_screen_text_does_not_emit_rpy202(
    tmp_path: Path,
) -> None:
    """A `text "Press SetVariable('undeclared_var', 1) to debug."` line
    inside a screen is a UI label, not an action call. It must not
    trigger RPY202.
    """
    rpy = """screen my_screen():
    text "Press SetVariable('undeclared_var', 1) to debug."
"""
    result, _ = _run_analyzer_on(rpy, tmp_path)
    rpy202 = [d for d in result.diagnostics if d.code == "RPY202"]
    assert rpy202 == [], (
        f"Expected 0 RPY202 for SetVariable() inside screen text dialog, "
        f"got: {[(d.line_number, d.message) for d in rpy202]}"
    )


def test_togglevariable_in_screen_text_does_not_emit_rpy202(
    tmp_path: Path,
) -> None:
    """Symmetric case for `ToggleVariable(...)`."""
    rpy = """screen my_screen():
    text "Toggle 'ToggleVariable(flag)' to debug."
"""
    result, _ = _run_analyzer_on(rpy, tmp_path)
    rpy202 = [d for d in result.diagnostics if d.code == "RPY202"]
    assert rpy202 == []


def test_real_setvariable_action_still_emits_rpy202(tmp_path: Path) -> None:
    """Counter-case: a real `SetVariable("undeclared", 1)` action must
    still emit RPY202.
    """
    rpy = """screen my_screen():
    textbutton "Set" action SetVariable("undeclared_var", 1)
"""
    result, _ = _run_analyzer_on(rpy, tmp_path)
    rpy202 = [d for d in result.diagnostics if d.code == "RPY202"]
    assert len(rpy202) == 1
    assert "undeclared_var" in rpy202[0].message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
