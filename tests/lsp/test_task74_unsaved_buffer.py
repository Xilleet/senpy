"""Regression tests for Task 74: LSP rename/references must use in-memory
(unsaved) content, not disk content, when computing TextEdit positions.

The bug: ``_rename_label`` and ``_find_text_occurrences_in_project`` read
files from DISK, while the symbol snapshot's ``line_number`` reflects
IN-MEMORY content (set by ``analyze_file_only`` from
``in_memory_files``). When the user has unsaved buffer changes that add
or remove lines above a label/reference, the disk line at the snapshot's
index is the WRONG line → rename applies TextEdits at stale positions,
silently corrupting the file (or missing edits entirely).

The fix: a new ``_read_file_lines`` helper in ``_shared.py`` reads
``in_memory_files`` first (keyed by ``normalize_path(path)``), falling
back to disk only when the file isn't in memory. All 4 disk-read sites
in ``_shared.py`` and ``rename.py`` now use this helper.

These tests construct the unsaved-buffer scenario manually:
1. Write disk content (what the user last saved).
2. Run analyzer on disk → snapshot reflects disk line numbers.
3. Simulate ``did_change``: put NEW content in ``in_memory_files`` and
   re-run ``analyze_file_only`` → snapshot now reflects IN-MEMORY line
   numbers (different from disk).
4. Call ``rename`` (or ``references``) → assert the returned TextEdits
   (or Locations) point at IN-MEMORY line indices, not disk indices.

Without the fix, step 4 fails: edits point at disk line indices (or
the rename returns None / empty changes because the disk line at the
snapshot's index doesn't contain the word).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from lsprotocol import types as lsp

import senpy.lsp.server as server_mod
from senpy.core.analyzer import SenpyAnalyzer
from tests._helpers.lsp import MockDocument, MockWorkspace


def _make_rename_params(uri: str, line: int, char: int, new_name: str) -> lsp.RenameParams:
    return lsp.RenameParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=line, character=char),
        new_name=new_name,
    )


def _make_reference_params(
    uri: str, line: int, char: int, include_decl: bool = True
) -> lsp.ReferenceParams:
    return lsp.ReferenceParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=line, character=char),
        context=lsp.ReferenceContext(include_declaration=include_decl),
    )


def _setup_unsaved_buffer_project(tmp_path: Path):
    """Build a project where disk content and in-memory content differ.

    Disk content (2 lines):
        label my_label:
            return

    In-memory content (7 lines — 5 blank lines added at top, unsaved):
        \\n\\n\\n\\n\\n
        label my_label:
            return

    After ``analyze_file_only`` with the in-memory content, the snapshot's
    ``my_label.line_number`` is 6 (1-based, counting the 5 blank lines).
    Disk line 6 (0-based 5) doesn't exist (disk has only 2 lines) →
    without the fix, rename reads disk, indexes past the end, returns
    None or empty changes (silent missing edit).

    With the fix, rename reads in-memory content (7 lines), finds
    ``label my_label:`` at line 5 (0-based), applies the edit correctly.
    """
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    script_file = game_dir / "script.rpy"

    disk_content = "label my_label:\n    return\n"
    script_file.write_text(disk_content, encoding="utf-8")

    # Step 1: analyzer reads disk → snapshot has disk line numbers.
    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    server_mod._lsp_server.active_analyzer = analyzer
    server_mod._lsp_server.is_initialized = True

    # Step 2: simulate did_change — user added 5 blank lines at top (unsaved).
    unsaved_content = "\n\n\n\n\n" + disk_content  # 5 blank lines + original
    norm_path = server_mod._normalize_path(str(script_file))
    analyzer.in_memory_files[norm_path] = unsaved_content

    # Step 3: re-analyze THIS file only → snapshot now reflects IN-MEMORY
    # line numbers (my_label at 1-based line 6, 0-based 5).
    analyzer.analyze_file_only(str(script_file))
    server_mod._refresh_symbol_snapshot()

    uri = server_mod._path_to_uri(str(script_file))
    return script_file, analyzer, uri, unsaved_content


class TestRenameLabelWithUnsavedBuffer:
    """``textDocument/rename`` must use in-memory content for line positions.

    Without the fix (Task 74): rename reads DISK, but the snapshot's
    ``lbl.line_number`` reflects IN-MEMORY content → TextEdits at stale
    disk positions → silent file corruption or missing edits.
    """

    def test_rename_label_returns_edits_at_in_memory_line(self, tmp_path: Path):
        """Rename ``my_label`` → edits must be at in-memory line 5 (0-based),
        not disk line 0."""
        script_file, analyzer, uri, unsaved_content = _setup_unsaved_buffer_project(tmp_path)

        # Cursor on "my_label" in the IN-MEMORY buffer (line 5, char 6).
        # The workspace doc must reflect the unsaved buffer (pygls contract).
        doc = MockDocument(uri, unsaved_content)
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        params = _make_rename_params(uri, 5, 6, "renamed_label")
        result = server_mod.rename(mock_ls, params)

        assert result is not None, (
            "rename returned None — the disk read indexed past disk length "
            "(disk has 2 lines, snapshot says line 6) and produced no edits. "
            "This is the Task 74 bug: rename must read in-memory content."
        )
        assert result.changes is not None
        all_edits = [e for edits in result.changes.values() for e in edits]
        assert len(all_edits) >= 1, "Rename must produce at least one edit"
        # The edit must be at IN-MEMORY line 5 (0-based), NOT disk line 0.
        decl_edit = all_edits[0]
        assert decl_edit.range.start.line == 5, (
            f"Edit must be at in-memory line 5 (0-based, where 'label my_label:' "
            f"lives after 5 blank lines were added unsaved), got line "
            f"{decl_edit.range.start.line}. Disk line 0 would be the bug."
        )
        assert decl_edit.new_text == "renamed_label"

    def test_rename_label_no_rogue_edit_on_unrelated_disk_line(self, tmp_path: Path):
        """If the disk line at the snapshot's index happens to contain the
        same word, rename must NOT produce a rogue edit on that disk line —
        it must produce the edit at the in-memory line only.

        Setup: disk has ``my_label`` on BOTH line 0 (label decl) and line 5
        (a coincidental mention in a comment). In-memory content has the
        label at line 5 (after 5 blank lines added unsaved). Without the
        fix, rename reads disk line 5 (the comment) and applies the edit
        there — a rogue edit on an unrelated line. With the fix, rename
        reads in-memory line 5 (the real declaration) and the edit is
        correct.
        """
        game_dir = tmp_path / "game"
        game_dir.mkdir(parents=True, exist_ok=True)
        script_file = game_dir / "script.rpy"
        # Disk: label on line 0, coincidental "my_label" on line 5.
        disk_content = (
            "label my_label:\n"  # line 0
            "    return\n"  # line 1
            "# comment\n"  # line 2
            "# another\n"  # line 3
            "# more\n"  # line 4
            "# my_label mention\n"  # line 5 — coincidental!
            "label end:\n"  # line 6
            "    return\n"  # line 7
        )
        script_file.write_text(disk_content, encoding="utf-8")

        analyzer = SenpyAnalyzer(str(tmp_path))
        analyzer.run(quiet=True)
        server_mod._lsp_server.active_analyzer = analyzer
        server_mod._lsp_server.is_initialized = True

        # Simulate did_change: replace the comment block with 5 blank lines,
        # so the label moves from line 0 to line 5 IN-MEMORY.
        unsaved_content = (
            "\n\n\n\n\n"  # lines 0-4: blank (unsaved)
            "label my_label:\n"  # line 5: label decl (in-memory)
            "    return\n"  # line 6
            "label end:\n"  # line 7
            "    return\n"  # line 8
        )
        norm_path = server_mod._normalize_path(str(script_file))
        analyzer.in_memory_files[norm_path] = unsaved_content
        analyzer.analyze_file_only(str(script_file))
        server_mod._refresh_symbol_snapshot()

        uri = server_mod._path_to_uri(str(script_file))
        doc = MockDocument(uri, unsaved_content)
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        params = _make_rename_params(uri, 5, 6, "renamed_label")
        result = server_mod.rename(mock_ls, params)

        assert result is not None and result.changes is not None
        all_edits = [e for edits in result.changes.values() for e in edits]
        # All edits must be at line 5 (the in-memory declaration line).
        # If any edit is at a different line, that's a rogue edit from
        # reading disk content at the wrong index.
        edit_lines = {e.range.start.line for e in all_edits}
        assert edit_lines == {5}, (
            f"Expected all edits at in-memory line 5, got lines: {edit_lines}. "
            f"A different line would indicate rename read disk content "
            f"(Task 74 bug — rogue edit on unrelated disk line)."
        )

    def test_rename_label_works_when_no_unsaved_changes(self, tmp_path: Path):
        """Baseline: when in_memory_files is EMPTY (no unsaved changes),
        rename must still work — reading from disk (the helper's fallback).
        This test guards against the fix breaking the no-unsaved-changes
        common case.
        """
        game_dir = tmp_path / "game"
        game_dir.mkdir(parents=True, exist_ok=True)
        script_file = game_dir / "script.rpy"
        disk_content = "label my_label:\n    return\n"
        script_file.write_text(disk_content, encoding="utf-8")

        analyzer = SenpyAnalyzer(str(tmp_path))
        analyzer.run(quiet=True)
        server_mod._lsp_server.active_analyzer = analyzer
        server_mod._lsp_server.is_initialized = True
        # NB: in_memory_files is EMPTY — no did_change simulated.
        server_mod._refresh_symbol_snapshot()

        uri = server_mod._path_to_uri(str(script_file))
        doc = MockDocument(uri, disk_content)
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        params = _make_rename_params(uri, 0, 6, "renamed_label")
        result = server_mod.rename(mock_ls, params)

        assert result is not None and result.changes is not None
        all_edits = [e for edits in result.changes.values() for e in edits]
        assert len(all_edits) >= 1
        assert all_edits[0].range.start.line == 0  # disk == in-memory here
        assert all_edits[0].new_text == "renamed_label"


class TestReferencesWithUnsavedBuffer:
    """``textDocument/references`` (Shift+F12) must use in-memory content.

    Non-destructive (just shows wrong line numbers in the references
    panel when unsaved changes exist), but still a correctness bug.
    """

    def test_references_label_returns_in_memory_line(self, tmp_path: Path):
        """References for ``my_label`` must point at the in-memory line
        (5), not the disk line (0)."""
        script_file, analyzer, uri, unsaved_content = _setup_unsaved_buffer_project(tmp_path)

        doc = MockDocument(uri, unsaved_content)
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        params = _make_reference_params(uri, 5, 6, True)
        result = server_mod.references(mock_ls, params)

        assert result is not None
        assert len(result) >= 1, "References must include the declaration"
        # The declaration location must be at in-memory line 5, not disk line 0.
        decl_locs = [loc for loc in result if loc.uri == uri]
        assert decl_locs, "Expected at least one location in the script file"
        decl_line = decl_locs[0].range.start.line
        assert decl_line == 5, (
            f"Reference declaration must be at in-memory line 5, got {decl_line}. "
            f"Disk line 0 would indicate references read disk instead of in-memory."
        )
