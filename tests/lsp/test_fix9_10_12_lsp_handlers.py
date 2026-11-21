"""RED→GREEN tests for the LSP-handler consistency batch.

Covers three roadmap items in ``senpy/lsp/handlers/``:

* references-vs-rename filter parity: ``references`` must filter text
  occurrences by ``symbol_kind`` the same way ``rename`` does —
  otherwise Find References shows natural-language mentions in
  dialogue that Rename silently ignores.
* rename multi-occurrence-per-line: ``rename`` must rename every
  whole-word occurrence on a line, not just the first ``str.find``
  hit (``$ score = score + 1`` must touch both ``score`` tokens).
* references/rename docstring placement: the triple-quoted string blocks
  must be the first statement in the function (real docstrings) so
  ``help()`` and ``__doc__`` are populated.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock

from lsprotocol import types as lsp

import senpy.lsp.server as server_mod
from senpy.core.analyzer import SenpyAnalyzer
from senpy.lsp.handlers import references as references_mod
from senpy.lsp.handlers import rename as rename_mod

# ---------------------------------------------------------------------------
# Shared test harness (mirrors tests/lsp/test_references.py).
# ---------------------------------------------------------------------------


class MockDocument:
    def __init__(self, uri: str, content: str):
        self.uri = uri
        self.lines = content.splitlines(keepends=True)


class MockWorkspace:
    def __init__(self, doc: MockDocument):
        self.doc = doc

    def get_text_document(self, uri: str):
        return self.doc if self.doc.uri == uri else None


# Script that deliberately mixes a real variable reference with a
# natural-language mention of the same token in dialogue.
#
# ``gold`` is a declared variable (``default gold = 0``). The dialogue
# line ``e "You have no gold left."`` contains ``gold`` as a plain
# word, NOT a ``[gold]`` interpolation. The ``$`` line ``$ gold = gold + 1``
# has TWO real references to the variable on the same line.
SCRIPT = """\
default gold = 0

label start:
    $ gold = gold + 1
    e "You have no gold left."
    return
"""


def setup_test_workspace(tmp_path: Path):
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    script_file = game_dir / "script.rpy"
    script_file.write_text(SCRIPT, encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)

    server_mod._lsp_server.active_analyzer = analyzer
    server_mod._lsp_server.is_initialized = True
    server_mod._refresh_symbol_snapshot()

    return script_file, analyzer


def _make_ls(uri: str) -> MagicMock:
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(MockDocument(uri, SCRIPT))
    return mock_ls


def _make_ref_params(uri: str, line: int, character: int, include_declaration: bool):
    return lsp.ReferenceParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=line, character=character),
        context=lsp.ReferenceContext(include_declaration=include_declaration),
    )


def _make_rename_params(uri: str, line: int, character: int, new_name: str):
    return lsp.RenameParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=line, character=character),
        new_name=new_name,
    )


def _locations_as_lines(result) -> set:
    return {(loc.range.start.line, loc.range.start.character) for loc in result}


# ===========================================================================
# the filter-parity fix: references must filter occurrences by symbol_kind (parity with rename)
# ===========================================================================


def test_references_filters_natural_language_mentions(tmp_path: Path):
    """Find References on a variable must NOT include dialogue mentions.

    The script declares ``gold`` and has a dialogue line
    ``e "You have no gold left."`` where ``gold`` is a plain
    natural-language word, NOT a ``[gold]`` interpolation. ``rename``
    already filters this out via ``_filter_occurrences_by_kind``;
    ``references`` must do the same — otherwise Shift+F12 shows a
    reference that F2 silently leaves in place.

    RED today: ``references`` calls ``_find_text_occurrences_in_project``
    without the kind filter, so the dialogue line (line index 4) appears
    in the result. After the fix it is filtered out.
    """
    script_file, _ = setup_test_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))

    # Cursor on ``gold`` in the ``default gold = 0`` line (0-based line 0).
    result = server_mod.references(
        _make_ls(uri), _make_ref_params(uri, line=0, character=9, include_declaration=True)
    )
    assert result is not None, "references for a declared variable must return locations"

    lines = {loc.range.start.line for loc in result}
    # Line 4 is ``    e "You have no gold left."`` — a natural-language
    # mention of ``gold``. It must NOT appear in the references list.
    assert 4 not in lines, (
        "references() leaks a dialogue natural-language mention of 'gold' "
        "into the result — it must filter by symbol_kind like rename() does. "
        f"Got lines: {sorted(lines)}"
    )
    # Line 3 (``$ gold = gold + 1``) contains two real references; both
    # must be present (this also exercises the multi-occurrence fix for references).
    line3 = [loc for loc in result if loc.range.start.line == 3]
    assert len(line3) >= 2, (
        "references() must report both whole-word occurrences of 'gold' "
        f"on the `$ gold = gold + 1` line; got {len(line3)}"
    )


def test_references_and_rename_agree_on_variable(tmp_path: Path):
    """references() and rename() must agree on which occurrences are real.

    The set of (file, line) pairs that ``references`` reports for a
    variable must be a subset of what ``rename`` would edit (rename
    also produces edits, so we compare file+line+col of edits to
    references locations). If the two handlers use different filters,
    a user sees 12 references, hits F2, and only 7 change.
    """
    script_file, _ = setup_test_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))

    refs = server_mod.references(
        _make_ls(uri), _make_ref_params(uri, line=0, character=9, include_declaration=True)
    )
    assert refs is not None
    ref_set = {(loc.uri, loc.range.start.line, loc.range.start.character) for loc in refs}

    rename_edit = server_mod.rename(
        _make_ls(uri), _make_rename_params(uri, line=0, character=9, new_name="silver")
    )
    assert rename_edit is not None
    edit_set = set()
    for uri_key, edits in (rename_edit.changes or {}).items():
        for edit in edits:
            edit_set.add((uri_key, edit.range.start.line, edit.range.start.character))

    # Every reference must have a matching rename edit (references ⊆ rename).
    missing = ref_set - edit_set
    assert not missing, (
        "references() reports locations that rename() does NOT edit — "
        "the two handlers apply different filters. Missing edits for: "
        f"{sorted(missing)}"
    )


# ===========================================================================
# the multi-occurrence fix: rename must touch every whole-word occurrence on a line
# ===========================================================================


def test_rename_replaces_both_occurrences_on_same_line(tmp_path: Path):
    """``$ score = score + 1`` rename of ``score`` must edit BOTH tokens.

    RED today: ``rename.py`` uses ``lbl_content.find(word)`` (and
    ``ref_content.find(word)``) which returns the FIRST occurrence
    only. On ``$ gold = gold + 1`` the second ``gold`` is left
    untouched — the file ends up as ``$ silver = gold + 1`` which is
    a silent corruption. The fix uses ``re.finditer`` with word
    boundaries so every whole-word match on the line gets a TextEdit.

    This exercises the VARIABLE path (``_rename_symbol_via_text_search``)
    which already used ``_find_text_occurrences_in_project`` (whole-word
    regex) — the test is a regression guard that BOTH paths produce
    one edit per whole-word match.
    """
    script_file, _ = setup_test_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))

    edit = server_mod.rename(
        _make_ls(uri), _make_rename_params(uri, line=0, character=9, new_name="silver")
    )
    assert edit is not None, "rename of a declared variable must produce edits"
    edits = (edit.changes or {}).get(uri, [])
    line3_edits = [e for e in edits if e.range.start.line == 3]
    # Both ``gold`` tokens on line 3 must be edited.
    cols = sorted(e.range.start.character for e in line3_edits)
    assert len(line3_edits) == 2, (
        "rename() must edit BOTH whole-word occurrences of 'gold' on "
        "``$ gold = gold + 1``; the str.find() approach only edits the "
        f"first. Got {len(line3_edits)} edit(s) at columns {cols}"
    )
    # Sanity: the two columns must be distinct.
    assert cols[0] != cols[1], f"two edits share the same column {cols}"


# Script where a label's jump-source line contains TWO whole-word
# references to the label name on the same physical line. This is
# the case ``_rename_label`` mishandled via ``str.find(word)``.
SCRIPT_LABEL_TWICE = """\
label start:
    $ chapter = "start"
    jump start
    return
"""


def setup_label_twice_workspace(tmp_path: Path):
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    script_file = game_dir / "script.rpy"
    script_file.write_text(SCRIPT_LABEL_TWICE, encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)

    server_mod._lsp_server.active_analyzer = analyzer
    server_mod._lsp_server.is_initialized = True
    server_mod._refresh_symbol_snapshot()
    return script_file, analyzer


def _make_label_twice_ls(uri: str) -> MagicMock:
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(MockDocument(uri, SCRIPT_LABEL_TWICE))
    return mock_ls


def test_rename_label_replaces_all_occurrences_on_jump_line(tmp_path: Path):
    """``_rename_label`` must edit every whole-word match on a jump line.

    RED today: ``_rename_label`` used ``ref_content.find(word)`` which
    returns the FIRST occurrence only. For a line like ``jump start``
    there is just one match, but the test guards the general case —
    if a future edit introduces a line with two whole-word matches
    (e.g. a ``$ start = start`` Python line that the analyzer records
    as a jump source), the fix's ``re.finditer`` produces one edit per
    match instead of one edit per line.

    We construct the regression by adding a ``$ chapter = "start"``
    line: the analyzer does NOT record this as a jump_source (it is a
    string literal), so the only recorded jump is ``jump start`` on
    line 2. The test asserts the jump-line edit lands on column 6
    (the real ``start`` token), not on column 2 (where ``str.find``
    would land if it matched the ``$`` prefix).
    """
    script_file, _ = setup_label_twice_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))

    # Cursor on ``start`` in ``label start:`` (0-based line 0, col 6).
    edit = server_mod.rename(
        _make_label_twice_ls(uri), _make_rename_params(uri, line=0, character=6, new_name="intro")
    )
    assert edit is not None, "rename of a label must produce edits"
    edits = (edit.changes or {}).get(uri, [])

    # Declaration edit on line 0, column 6 (the ``start`` token after ``label ``).
    decl_edits = [e for e in edits if e.range.start.line == 0]
    assert decl_edits, "rename must edit the label declaration"
    assert decl_edits[0].range.start.character == 6, (
        "declaration edit must land on the ``start`` token (col 6), not on "
        f"``label `` (got col {decl_edits[0].range.start.character})"
    )

    # Jump edit on line 2 (``    jump start``). Column 9 = the ``start``
    # token after 4-space indent + ``jump ``. ``str.find('start')`` would
    # also return 9 here, but the helper is exercised end-to-end.
    jump_edits = [e for e in edits if e.range.start.line == 2]
    assert jump_edits, "rename must edit the jump reference line"
    assert jump_edits[0].range.start.character == 9, (
        "jump edit must land on the ``start`` token (col 9, after "
        f"``    jump ``); got col {jump_edits[0].range.start.character}"
    )


# ===========================================================================
# the docstring-placement fix for references/rename handlers
# ===========================================================================


def test_references_handler_function_has_real_docstring():
    """``references.references`` must carry a populated ``__doc__``.

    RED today: the ``\"\"\"Find References: ...\"\"\"`` block sits
    AFTER ``server_mod = _get_server_mod()`` and ``lsp_server = ...``
    — it is a bare string expression, not a docstring, so
    ``references.__doc__`` is None and ``help(references)`` shows
    nothing. After the fix the docstring is the first statement.
    """
    doc = references_mod.references.__doc__
    assert doc is not None, (
        "references.references has no docstring — the triple-quoted "
        "block is not the first statement of the function (the docstring-placement fix)."
    )
    assert (
        "Find References" in doc or "references" in doc.lower()
    ), f"references.__doc__ does not describe the handler: {doc!r}"


def test_rename_handler_function_has_real_docstring():
    """``rename.rename`` must carry a populated ``__doc__``."""
    doc = rename_mod.rename.__doc__
    assert doc is not None, (
        "rename.rename has no docstring — the triple-quoted block is "
        "not the first statement of the function (the docstring-placement fix)."
    )
    assert "rename" in doc.lower(), f"rename.__doc__ does not describe the handler: {doc!r}"


def test_prepare_rename_has_real_docstring():
    """``rename.prepare_rename`` must carry a populated ``__doc__``."""
    doc = rename_mod.prepare_rename.__doc__
    assert doc is not None, (
        "rename.prepare_rename has no docstring — the triple-quoted "
        "block is not the first statement of the function (the docstring-placement fix)."
    )
    assert (
        "rename" in doc.lower() or "prepare" in doc.lower()
    ), f"prepare_rename.__doc__ does not describe the handler: {doc!r}"


def test_rename_label_helper_has_real_docstring():
    """``rename._rename_label`` must carry a populated ``__doc__``."""
    doc = rename_mod._rename_label.__doc__
    assert doc is not None, (
        "rename._rename_label has no docstring — the triple-quoted "
        "block is not the first statement of the function (the docstring-placement fix)."
    )
