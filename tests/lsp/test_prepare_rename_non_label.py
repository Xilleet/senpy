"""Tests for LSP prepare_rename on non-label symbols.

``prepare_rename`` in ``senpy/lsp/handlers/navigation.py`` returned a
Range only for labels — for variables, transforms, and screens it
returned ``None``. But ``rename`` already supported all four symbol
types (labels via ``_rename_label``, variables/transforms/screens via
``_rename_symbol_via_text_search``).

VS Code does not start an F2 rename session if ``prepareRename``
returns ``None`` — the user presses F2 on a variable, nothing happens,
and they conclude "renaming doesn't work for variables".

The fix extends ``prepare_rename`` to return the word's Range when the
word under the cursor is in any of the four rename-supported symbol
sets: labels, variables, transforms, screens. The Range calculation
(UTF-16 positions for VS Code) is unchanged — only the eligibility
check is broadened.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from lsprotocol import types as lsp

from senpy.lsp import server as server_mod
from senpy.lsp.handlers.navigation import prepare_rename
from tests._helpers.lsp import MockDocument, MockWorkspace, setup_test_workspace


def _make_params(uri: str, line: int, char: int) -> lsp.PrepareRenameParams:
    """Build PrepareRenameParams for the given position."""
    return lsp.PrepareRenameParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=line, character=char),
    )


def _extract_range(result):
    """Extract a Range from prepare_rename's return value.

    pygls/lsprotocol accepts a Range or a PrepareRenameResult(placeholder=...).
    Normalize to a Range for assertions.
    """
    if result is None:
        return None
    if hasattr(result, "range"):
        return result.range
    if hasattr(result, "start"):
        return result  # already a Range
    pytest.fail(f"prepare_rename returned unexpected type: {type(result)}")


class TestPrepareRenameForVariables:
    """prepare_rename must return a Range for variables (not just labels)."""

    def test_prepare_rename_returns_range_for_variable(self, tmp_path: Path):
        """F2 on a variable name must start a rename session.

        The test workspace (from test_lsp.setup_test_workspace) defines:
            default player_gold = 100
        and uses it on line 8 (0-based): ``$ player_gold += 10``.

        Before P1-6: prepare_rename returned None for variables — VS Code
        did not start F2, user thought "renaming doesn't work".
        After P1-6: prepare_rename returns the Range of the word, F2 works.
        """
        setup_test_workspace(tmp_path)
        uri = "file:///test/script.rpy"
        script_content = (tmp_path / "game" / "script.rpy").read_text(encoding="utf-8")
        doc = MockDocument(uri, script_content)
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        # Find the line with "player_gold += 10" (line 8 in 0-based, but
        # setup_test_workspace adds a leading newline — verify by reading).
        lines = script_content.split("\n")
        target_line = None
        for i, line in enumerate(lines):
            if "player_gold += 10" in line:
                target_line = i
                break
        assert target_line is not None, "Test workspace must contain 'player_gold += 10'"

        # Cursor on "player_gold" — find the character position.
        char_in_line = lines[target_line].index("player_gold") + 3
        params = _make_params(uri, target_line, char_in_line)

        result = prepare_rename(mock_ls, params)
        assert result is not None, (
            "prepare_rename on a variable (player_gold) must return a Range, "
            "not None. rename() already supports variables — prepare_rename "
            "must be consistent so VS Code starts the F2 session."
        )

        rng = _extract_range(result)
        assert rng.start.line == target_line
        assert rng.end.line == target_line
        # The Range must cover the cursor position.
        assert rng.start.character <= char_in_line <= rng.end.character

    def test_prepare_rename_returns_range_for_define(self, tmp_path: Path):
        """F2 on a `define` constant must also work.

        `define max_hp = 50` creates a variable symbol. Cursor on `max_hp`
        in its declaration must return a Range.
        """
        setup_test_workspace(tmp_path)
        uri = "file:///test/script.rpy"
        script_content = (tmp_path / "game" / "script.rpy").read_text(encoding="utf-8")
        doc = MockDocument(uri, script_content)
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        lines = script_content.split("\n")
        target_line = None
        for i, line in enumerate(lines):
            if "define max_hp" in line:
                target_line = i
                break
        assert target_line is not None, "Test workspace must contain 'define max_hp'"

        char_in_line = lines[target_line].index("max_hp") + 2
        params = _make_params(uri, target_line, char_in_line)

        result = prepare_rename(mock_ls, params)
        assert result is not None, (
            "prepare_rename on a define constant (max_hp) must return a Range. "
            "define creates a variable symbol — rename supports it, "
            "prepare_rename must too."
        )


class TestPrepareRenameForTransforms:
    """prepare_rename must return a Range for transforms."""

    def test_prepare_rename_returns_range_for_transform(self, tmp_path: Path):
        """F2 on a transform name must start a rename session.

        Creates a project with a ``transform`` declaration (which the
        analyzer classifies as a transform symbol, not an image).
        Cursor on the transform name must return a Range.
        """
        from senpy.core.analyzer import SenpyAnalyzer

        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        (game / "script.rpy").write_text(
            "transform slide_left:\n"
            "    linear 0.5 xoffset -100\n"
            "\n"
            "label start:\n"
            "    show bg slide_left\n"
            "    return\n",
            encoding="utf-8",
        )
        analyzer = SenpyAnalyzer(str(tmp_path))
        analyzer.run(quiet=True)
        server_mod._active_analyzer = analyzer
        server_mod._is_initialized = True
        server_mod._refresh_symbol_snapshot()

        # Verify slide_left is in transforms snapshot.
        assert "slide_left" in server_mod._symbol_snapshot["transforms"], (
            "Test setup: slide_left must be in transforms snapshot. "
            f"Got transforms: {list(server_mod._symbol_snapshot['transforms'])}"
        )

        uri = f"file://{tmp_path}/game/script.rpy"
        script_content = (game / "script.rpy").read_text(encoding="utf-8")
        doc = MockDocument(uri, script_content)
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        lines = script_content.split("\n")
        target_line = None
        for i, line in enumerate(lines):
            if "transform slide_left" in line:
                target_line = i
                break
        assert target_line is not None

        char_in_line = lines[target_line].index("slide_left") + 2
        params = _make_params(uri, target_line, char_in_line)

        result = prepare_rename(mock_ls, params)
        assert result is not None, (
            "prepare_rename on a transform (slide_left) must return a Range. "
            "rename() supports transforms — prepare_rename must be consistent."
        )


class TestPrepareRenameStillReturnsNoneForNonSymbols:
    """Sanity: prepare_rename must still return None for non-symbol words.

    Guards against over-broadening: if prepare_rename returned a Range for
    ANY word (not just symbols), F2 would start on strings, comments, etc.
    — misleading the user into thinking they can rename arbitrary text.
    """

    def test_prepare_rename_returns_none_for_non_symbol_word(self, tmp_path: Path):
        """A word that is not a label/variable/transform/screen → None.

        The test workspace has dialogue like ``"В лесу..."`` — the word
        ``В`` (or any word inside the string) is not a symbol.
        """
        setup_test_workspace(tmp_path)
        uri = "file:///test/script.rpy"
        script_content = (tmp_path / "game" / "script.rpy").read_text(encoding="utf-8")
        doc = MockDocument(uri, script_content)
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        # Find a dialogue line — the word inside quotes is not a symbol.
        lines = script_content.split("\n")
        target_line = None
        for i, line in enumerate(lines):
            if "В лесу" in line:
                target_line = i
                break
        if target_line is None:
            pytest.skip("Test workspace no longer has 'В лесу' dialogue")

        # Cursor on a word inside the string (not a symbol).
        char_in_line = lines[target_line].index("В")
        params = _make_params(uri, target_line, char_in_line)

        result = prepare_rename(mock_ls, params)
        # "В" is not in any symbol snapshot — must return None.
        assert result is None, (
            "prepare_rename on a non-symbol word (inside a dialogue string) "
            "must return None. F2 should not start on arbitrary text."
        )


class TestPrepareRenameLabelStillWorks:
    """Sanity: the existing label support must not break."""

    def test_prepare_rename_returns_range_for_label(self, tmp_path: Path):
        """F2 on a label must still work (regression guard)."""
        setup_test_workspace(tmp_path)
        uri = "file:///test/script.rpy"
        script_content = (tmp_path / "game" / "script.rpy").read_text(encoding="utf-8")
        doc = MockDocument(uri, script_content)
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        lines = script_content.split("\n")
        target_line = None
        for i, line in enumerate(lines):
            if "label forest_scene" in line:
                target_line = i
                break
        assert target_line is not None, "Test workspace must contain 'label forest_scene'"

        char_in_line = lines[target_line].index("forest_scene") + 3
        params = _make_params(uri, target_line, char_in_line)

        result = prepare_rename(mock_ls, params)
        assert result is not None, (
            "prepare_rename on a label (forest_scene) must still return a Range. "
            "The P1-6 fix broadened eligibility — label support must not regress."
        )
