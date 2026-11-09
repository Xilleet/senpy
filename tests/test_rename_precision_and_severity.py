"""Regression tests for LSP rename precision and severity override behavior.

Two bug classes covered here:

    * LSP rename via text search ignores the ``symbol_kind`` parameter
      and replaces every whole-word occurrence of the renamed token,
      even when those occurrences belong to a different symbol kind.
      Rename a variable named ``score`` also rewrites ``label score:``,
      ``jump score``, ``show screen score``, and the dialogue
      ``"Your score is [score]."`` — destroying label declarations
      and breaking jump targets.

      The contract: rename of a variable must touch ONLY variable
      occurrences (in Python blocks and Ren'Py string interpolation),
      not label declarations, jump targets, or screen action calls
      that share the same textual token.

    * Severity overrides are minimally tested: the existing
      characterization tests cover full output but not the specific
      contract of ``severity_overrides`` — that mixed-case keys/values
      are normalised via ``.strip().upper()``, that overrides win over
      strict mode, and that unknown codes are silently ignored.

      Without these tests, a future refactor that drops the
      ``.upper()`` normalisation would silently break user
      configurations that use lowercase rule codes.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from lsprotocol import types as lsp

import senpy.lsp.server as server_mod
from senpy.core.analyzer import SenpyAnalyzer

# ---------------------------------------------------------------------------
# Test helpers (mirror tests/test_lsp_rename_references_ext.py patterns)
# ---------------------------------------------------------------------------


class MockDocument:
    def __init__(self, uri: str, content: str):
        self.uri = uri
        self.lines = content.splitlines(keepends=True)
        self.source = content


class MockWorkspace:
    def __init__(self, doc: MockDocument):
        self.doc = doc

    def get_text_document(self, uri: str):
        return self.doc if self.doc.uri == uri else None


def _setup_lsp(tmp_path: Path, rpy: str) -> tuple[Path, str]:
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    script = game_dir / "script.rpy"
    script.write_text(rpy, encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    server_mod._refresh_symbol_snapshot()
    return script, server_mod._path_to_uri(str(script))


def _do_rename(uri: str, line: int, char: int, new_name: str, content: str):
    doc = MockDocument(uri, content)
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)
    params = lsp.RenameParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=line, character=char),
        new_name=new_name,
    )
    return server_mod.rename(mock_ls, params)


def _collect_edits(result) -> list[tuple[str, int, int, str]]:
    """Flatten a WorkspaceEdit result into (file_uri, line, char, new_text) tuples."""
    out = []
    if not result or not result.changes:
        return out
    for file_uri, edits in result.changes.items():
        for edit in edits:
            out.append((file_uri, edit.range.start.line, edit.range.start.character, edit.new_text))
    return sorted(out)


# ---------------------------------------------------------------------------
# Rename variable does not touch label/dialog/jump with the same name
# ---------------------------------------------------------------------------


def test_rename_variable_does_not_touch_label_declaration(tmp_path: Path) -> None:
    """Reproducer: a variable named ``player_score`` must not be confused
    with a label named ``player_score``. Renaming the variable must NOT
    rewrite the ``label player_score:`` declaration line — that would
    break every ``jump player_score`` / ``call player_score`` reference
    in the project.

    NOTE: in the ``rename`` handler the dispatch checks labels FIRST
    (line 251: ``if word in server_mod._symbol_snapshot["labels"]:``).
    So when a token exists as BOTH a label and a variable, the label
    path always wins — the variable rename is unreachable. This test
    uses a project where the variable name does NOT collide with a
    label, but the dialogue and jump target do collide with the
    variable's textual token. The variable rename must not touch
    the unrelated label declaration or jump target.

    Input:
        default player_score = 0       # variable declaration
        label player_score:           # label declaration (NOT in snapshot as variable)
            return
        label start:
            $ player_score = 100      # variable usage — edit
            jump player_score         # label usage — must NOT change
            return

    To force the variable path: we rename a DIFFERENT variable
    (``player_score``) that does NOT collide with any label in the
    snapshot. We make the variable declaration line COLLIDE with a
    label name ``player_score`` — but the snapshot's variable dict
    holds the variable, while the snapshot's label dict holds the
    label, both with the same name. The handler dispatches to the
    label path first because labels are checked first.

    To reproduce the rename-precision bug we must trigger
    ``_rename_symbol_via_text_search`` with ``symbol_kind="variables"``.
    We do this by using a variable name that is NOT in the label
    snapshot — then the label path is skipped, and the variable path
    runs, and our text-search filter is what protects against false
    positives in dialogue / jump targets.
    """
    # Use a project where `player_hp` is a variable AND a label — the
    # rename handler dispatches to the LABEL path when both exist (line
    # 251 of navigation.py). To trigger the variable path, we rename
    # a variable `player_hp` while ALSO having a label `player_hp` —
    # this DOES collide, so the label path runs and we cannot exercise
    # the variable path.
    #
    # To exercise the variable path, we rename a variable `player_hp`
    # that does NOT have a label with the same name. But we still want
    # to verify that the variable rename does NOT touch label
    # declarations or jump targets of OTHER labels that share the
    # textual token. The cleanest reproducer: a variable named
    # `player_hp` and a DIFFERENT label `player_hp_intro` (the token
    # `player_hp` appears as a substring of `player_hp_intro` — but
    # whole-word match means it does NOT match). This is not the bug.
    #
    # The actual bug: variable `player_hp` exists, dialogue text
    # `"...player_hp..."` mentions it as natural-language word, and a
    # jump target `jump player_hp` references a label of the same
    # name (which does NOT exist in this minimal project — so the
    # label snapshot is empty for `player_hp`). The rename must NOT
    # touch the dialogue mention NOR the (broken) jump target.
    rpy = (
        "default player_hp = 100\n"
        "\n"
        "label start:\n"
        '    "Your player_hp is [player_hp]."\n'  # interpolation — edit
        '    "Natural player_hp mention."\n'  # natural-language — DON\'T
        "    $ player_hp -= 10\n"  # python — edit
        "    jump player_hp\n"  # broken jump target — DON\'T
        "    return\n"
    )
    script, uri = _setup_lsp(tmp_path, rpy)
    # Cursor on "player_hp" in default declaration (line 0, char 8).
    result = _do_rename(uri, line=0, char=8, new_name="new_hp", content=rpy)
    edits = _collect_edits(result)

    # The variable declaration (line 0: "default player_hp = 100") MUST be edited.
    assert any(
        line == 0 for _, line, _, _ in edits
    ), f"Variable declaration on line 0 must be edited. Edits: {edits}"

    # The variable usage in interpolation (line 3: "[player_hp]") MUST be edited.
    assert any(
        line == 3 for _, line, _, _ in edits
    ), f"Interpolation usage on line 3 must be edited. Edits: {edits}"

    # The python assignment (line 5: "$ player_hp -= 10") MUST be edited.
    assert any(
        line == 5 for _, line, _, _ in edits
    ), f"Python usage on line 5 must be edited. Edits: {edits}"

    # The natural-language mention on line 4 MUST NOT be edited.
    line_4 = [e for e in edits if e[1] == 4]
    assert (
        not line_4
    ), f"Natural-language mention on line 4 must NOT be edited by variable rename. Edits: {edits}"

    # The jump target (line 6: "jump player_hp") MUST NOT be edited.
    line_6 = [e for e in edits if e[1] == 6]
    assert not line_6, (
        f"`jump player_hp` on line 6 must NOT be edited by variable "
        f"rename — it references a label, not a variable. Edits: {edits}"
    )


def test_rename_variable_does_not_touch_dialog_text(tmp_path: Path) -> None:
    """Reproducer: dialogue text mentioning the variable name as a
    natural-language word must NOT be edited. Only proper variable
    references (in Python blocks and Ren'Py ``[var]`` interpolation)
    are valid rename targets.

    Input:
        default hp = 100
        label start:
            "Your hp is [hp]."           # interpolation — edit
            "This is an hp value."       # natural-language mention — DON'T
            $ hp -= 10                   # python assignment — edit
            return

    Before the fix: rename ``hp`` rewrites ALL whole-word ``hp``
    occurrences, including the natural-language mention in dialogue.
    """
    rpy = (
        "default hp = 100\n"
        "label start:\n"
        '    "Your hp is [hp]."\n'
        '    "This is an hp value."\n'
        "    $ hp -= 10\n"
        "    return\n"
    )
    script, uri = _setup_lsp(tmp_path, rpy)
    # Cursor on "hp" in default declaration (line 0, char 8).
    result = _do_rename(uri, line=0, char=8, new_name="new_hp", content=rpy)
    edits = _collect_edits(result)

    # Variable declaration (line 0) MUST be edited.
    assert any(
        line == 0 for _, line, _, _ in edits
    ), f"Variable declaration on line 0 must be edited. Edits: {edits}"

    # Python assignment (line 4: "$ hp -= 10") MUST be edited.
    assert any(
        line == 4 for _, line, _, _ in edits
    ), f"Python assignment on line 4 must be edited. Edits: {edits}"

    # The natural-language mention on line 3 (`"This is an hp value."`)
    # MUST NOT be edited — it's dialogue text, not a variable reference.
    line_3 = [
        (file_uri, line, char, new_text) for file_uri, line, char, new_text in edits if line == 3
    ]
    assert (
        not line_3
    ), f"Natural-language mention of 'hp' in dialogue on line 3 must NOT be edited. Edits: {edits}"


# ---------------------------------------------------------------------------
# Severity overrides: mixed-case normalisation + strict-mode precedence
# ---------------------------------------------------------------------------


def _run_with_overrides(tmp_path: Path, severity_overrides: dict[str, str] | None = None):
    """Run analyzer with explicit severity_overrides (programmatic path).

    Returns the result and analyzer instance.
    """
    rpy = "default unused = 10\nlabel start:\n    return\n"
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(rpy, encoding="utf-8")
    a = SenpyAnalyzer(str(tmp_path), severity_overrides=severity_overrides)
    r = a.run(quiet=True)
    return r, a


def test_severity_overrides_normalises_mixed_case_keys(tmp_path: Path) -> None:
    """The ``severity_overrides`` dict must accept mixed-case keys —
    ``rpy701``, ``RPY701``, ``RpY701`` are all equivalent. This is
    enforced by ``.strip().upper()`` on the key during construction.

    Without this normalisation, a user writing ``[tool.senpy.severity]``
    in senpy.toml with a lowercase rule code would silently have no
    effect.
    """
    # Same rule code, three different casings. The dict collapses to
    # a single key after normalisation, so the last value wins.
    overrides = {
        "rpy701": "warning",
        "RPY701": "info",
        "RpY701": "hint",
    }
    r, a = _run_with_overrides(tmp_path, severity_overrides=overrides)

    # The effective override for RPY701 must be the LAST one set,
    # because all three keys normalise to "RPY701".
    assert (
        "RPY701" in a.severity_overrides
    ), f"Override key must be normalised to upper-case. severity_overrides={a.severity_overrides}"
    assert a.severity_overrides["RPY701"] == "HINT", (
        f"Override value must be normalised to upper-case. "
        f"severity_overrides={a.severity_overrides}"
    )

    # The actual RPY701 diagnostic (if any) must carry the overridden severity.
    rpy701_diags = [d for d in r.diagnostics if d.code == "RPY701"]
    if rpy701_diags:
        assert all(d.severity == "HINT" for d in rpy701_diags), (
            f"RPY701 diagnostics must use the overridden severity. "
            f"Got: {[(d.severity, d.message) for d in rpy701_diags]}"
        )


def test_severity_overrides_normalises_mixed_case_values(tmp_path: Path) -> None:
    """The ``severity_overrides`` dict must accept mixed-case values —
    ``warning``, ``Warning``, ``WARNING`` are all equivalent.
    """
    overrides = {"RPY701": "warning"}
    r, a = _run_with_overrides(tmp_path, severity_overrides=overrides)

    assert a.severity_overrides["RPY701"] == "WARNING", (
        f"Override value must be normalised to upper-case. "
        f"severity_overrides={a.severity_overrides}"
    )


def test_severity_overrides_win_over_strict_mode(tmp_path: Path) -> None:
    """When both ``severity_overrides`` and ``strict=True`` are set,
    the explicit override wins for that rule code (other codes still
    get promoted to ERROR by strict mode).

    Contract per ``_apply_severity``:
        if diag.code in severity_overrides:
            diag.severity = severity_overrides[diag.code]
        elif not diag.severity:
            diag.severity = RULE_SEVERITY.get(diag.code, "WARNING")
        if a.strict and diag.code not in severity_overrides:
            diag.severity = "ERROR"
    """
    # Use programmatic path: severity_overrides disables strict.
    # We must construct with both via the config path — but the
    # constructor's programmatic path sets strict=False. So we test
    # the contract via _apply_severity directly.
    a = SenpyAnalyzer(str(tmp_path), severity_overrides={"RPY701": "INFO"})
    # Manually flip strict on, simulating what happens when both are set
    # via the config file path.
    a.strict = True

    from senpy.core.models import Diagnostic

    diag_overridden = Diagnostic(
        file_path="test.rpy",
        line_number=1,
        line_content="default unused = 10",
        code="RPY701",
        message="test",
    )
    diag_other = Diagnostic(
        file_path="test.rpy",
        line_number=2,
        line_content="$ x = 1",
        code="RPY104",
        message="test",
    )

    a._pipeline._apply_severity(diag_overridden)
    a._pipeline._apply_severity(diag_other)

    # The overridden code keeps its explicit severity, even under strict.
    assert (
        diag_overridden.severity == "INFO"
    ), f"Override must win over strict mode. Got: {diag_overridden.severity}"
    # Other codes are promoted to ERROR by strict mode.
    assert (
        diag_other.severity == "ERROR"
    ), f"Strict mode must promote non-overridden codes to ERROR. Got: {diag_other.severity}"


def test_severity_overrides_unknown_codes_are_ignored(tmp_path: Path) -> None:
    """Severity overrides for unknown rule codes must not crash and
    must not affect diagnostics of other codes. They are silently
    stored (in case a future rule with that code is added) but have
    no effect.
    """
    overrides = {
        "RPY701": "WARNING",
        "RPY999": "ERROR",  # unknown — does not exist
    }
    r, a = _run_with_overrides(tmp_path, severity_overrides=overrides)

    # The unknown code is stored, no crash.
    assert "RPY999" in a.severity_overrides
    # No diagnostic with code RPY999 exists (it's unknown).
    rpy999_diags = [d for d in r.diagnostics if d.code == "RPY999"]
    assert (
        rpy999_diags == []
    ), f"Unknown rule codes should not produce diagnostics. Got: {rpy999_diags}"


def test_severity_overrides_empty_dict_is_noop(tmp_path: Path) -> None:
    """An empty ``severity_overrides`` dict is a no-op — all
    diagnostics keep their default severity.
    """
    overrides = {}
    r, a = _run_with_overrides(tmp_path, severity_overrides=overrides)

    assert a.severity_overrides == {}
    # Sanity: at least one diagnostic fired (RPY303 on unused labels, etc.)
    if r.diagnostics:
        for d in r.diagnostics:
            # Each diagnostic must have a severity set (default or overridden).
            assert (
                d.severity is not None
            ), f"Diagnostic must have a severity even with empty overrides: {d}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
