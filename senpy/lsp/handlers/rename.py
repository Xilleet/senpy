"""LSP handlers: textDocument/rename (F2) + prepareRename.

Extracted from senpy/lsp/handlers/navigation.py.
Rename labels (via jump_sources reverse index) and
variables/transforms/screens (via text search + kind filtering).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    try:
        from pygls.lsp.server import LanguageServer
    except ImportError:
        from pygls.server import LanguageServer  # type: ignore[attr-defined, no-redef]

from lsprotocol import types as lsp

from senpy.lsp.handlers._shared import (
    _filter_occurrences_by_kind,
    _find_text_occurrences_in_project,
    _get_server_mod,
)


def rename(ls: LanguageServer, params: lsp.RenameParams) -> lsp.WorkspaceEdit | None:
    server_mod = _get_server_mod()
    # Phase 3.3c-e: state via _lsp_server.<attr>.
    lsp_server = server_mod._lsp_server
    """Label rename: updates the declaration + all jump/call references."""
    if lsp_server.active_analyzer is None or not lsp_server.is_initialized:
        return None

    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc or not doc.lines:
        return None

    line_idx = params.position.line
    if line_idx >= len(doc.lines):
        return None

    line = doc.lines[line_idx]
    col = params.position.character

    # Extract the word under the cursor
    word = None
    for m in re.finditer(r"[a-zA-Z_][a-zA-Z0-9_\.]*", line):
        if m.start() <= col <= m.end():
            word = m.group(0)
            break

    if not word:
        return None

    new_name = params.new_name

    # rename for labels, variables, transforms, screens.
    # use the snapshot, not lsp_server.active_analyzer.labels —
    # analyze_file_only clears labels from other files.
    if word in lsp_server.symbol_snapshot["labels"]:
        # Existing logic for labels (via jump_sources reverse index)
        return _rename_label(server_mod, word, new_name)
    elif word in lsp_server.symbol_snapshot["variables"]:
        return _rename_symbol_via_text_search(server_mod, word, new_name, "variables")
    elif word in lsp_server.symbol_snapshot["transforms"]:
        return _rename_symbol_via_text_search(server_mod, word, new_name, "transforms")
    elif word in lsp_server.symbol_snapshot["screens"]:
        return _rename_symbol_via_text_search(server_mod, word, new_name, "screens")

    return None


def _rename_label(server_mod, word: str, new_name: str) -> lsp.WorkspaceEdit | None:
    """Rename for a label: updates the declaration + all jump/call references.

    Uses the jump_sources reverse index from the analyzer — more precise than
    text search (does not catch false positives in strings/comments).
    """
    # Phase 3.3c-e: state via _lsp_server.<attr>.
    lsp_server = server_mod._lsp_server
    changes: dict[str, list[lsp.TextEdit]] = {}

    # 1. Declaration (label X:)
    lbl = lsp_server.symbol_snapshot["labels"][word]
    lbl_uri = server_mod._path_to_uri(lbl.file_path)
    lbl_line = max(0, lbl.line_number - 1)  # 0-based

    # Read the line to find the exact position of the word
    try:
        with open(lbl.file_path, encoding="utf-8") as f:
            file_lines = f.readlines()
        if lbl_line < len(file_lines):
            lbl_content = file_lines[lbl_line]
            # Find the position of the word in the line
            word_start = lbl_content.find(word)
            if word_start >= 0:
                word_start_utf16 = len(lbl_content[:word_start].encode("utf-16-le")) // 2
                word_end_utf16 = word_start_utf16 + len(word.encode("utf-16-le")) // 2
                changes.setdefault(lbl_uri, []).append(
                    lsp.TextEdit(
                        range=lsp.Range(
                            start=lsp.Position(line=lbl_line, character=word_start_utf16),
                            end=lsp.Position(line=lbl_line, character=word_end_utf16),
                        ),
                        new_text=new_name,
                    )
                )
    except OSError:
        pass

    # 2. All jump/call references (from jump_sources)
    # UX: also from the snapshot, to get references from all files.
    for ref_path, ref_line in lsp_server.symbol_snapshot["jump_sources"].get(word, []):
        ref_uri = server_mod._path_to_uri(ref_path)
        ref_line_0 = max(0, ref_line - 1)  # 0-based

        # Read the line to find the exact position of the word
        try:
            with open(ref_path, encoding="utf-8") as f:
                ref_lines = f.readlines()
            if ref_line_0 < len(ref_lines):
                ref_content = ref_lines[ref_line_0]
                # Find the position of the word in the line
                word_start = ref_content.find(word)
                if word_start >= 0:
                    word_start_utf16 = len(ref_content[:word_start].encode("utf-16-le")) // 2
                    word_end_utf16 = word_start_utf16 + len(word.encode("utf-16-le")) // 2
                    changes.setdefault(ref_uri, []).append(
                        lsp.TextEdit(
                            range=lsp.Range(
                                start=lsp.Position(line=ref_line_0, character=word_start_utf16),
                                end=lsp.Position(line=ref_line_0, character=word_end_utf16),
                            ),
                            new_text=new_name,
                        )
                    )
        except OSError:
            pass

    if not changes:
        return None

    return lsp.WorkspaceEdit(changes=changes)


# =============================================================================
# helpers: rename for variables/transforms/screens via text search
# =============================================================================

# Regex template to find occurrences of a word as a whole-word (not part of another name).
# Boundaries: not alphanumeric/underscore on either side.
# Example: for "player_gold" it should not match "player_gold_count" or "my_player_gold".


def _rename_symbol_via_text_search(
    server_mod, word: str, new_name: str, symbol_kind: str
) -> lsp.WorkspaceEdit | None:
    """Rename a variable/transform/screen via text search across all .rpy files.

    For variables/transforms/screens there is no reverse index (like jump_sources
    for labels). We use text search — all whole-word occurrences of the word in
    .rpy files of the project are replaced with `new_name`.
    """
    occurrences = _find_text_occurrences_in_project(server_mod, word)
    if not occurrences:
        return None

    # Filter occurrences by symbol_kind so a variable rename does NOT
    # touch label declarations, jump targets, screen actions, or
    # natural-language mentions in dialogue that happen to share the
    # same textual token. Same for transforms and screens — only real
    # references of the requested kind survive the filter.
    occurrences = _filter_occurrences_by_kind(occurrences, word, symbol_kind)
    if not occurrences:
        return None

    changes: dict[str, list[lsp.TextEdit]] = {}
    word_len_utf16 = len(word.encode("utf-16-le")) // 2

    for fpath, line_idx, col_utf16 in occurrences:
        uri = server_mod._path_to_uri(fpath)
        changes.setdefault(uri, []).append(
            lsp.TextEdit(
                range=lsp.Range(
                    start=lsp.Position(line=line_idx, character=col_utf16),
                    end=lsp.Position(line=line_idx, character=col_utf16 + word_len_utf16),
                ),
                new_text=new_name,
            )
        )

    if not changes:
        return None

    return lsp.WorkspaceEdit(changes=changes)


def prepare_rename(
    ls: LanguageServer, params: lsp.PrepareRenameParams
) -> lsp.Range | lsp.PrepareRenameResult | None:
    server_mod = _get_server_mod()
    # Phase 3.3c-e: state via _lsp_server.<attr>.
    lsp_server = server_mod._lsp_server
    """Returns the Range of the word under the cursor for preview before rename."""
    if lsp_server.active_analyzer is None or not lsp_server.is_initialized:
        return None

    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc or not doc.lines:
        return None

    line_idx = params.position.line
    if line_idx >= len(doc.lines):
        return None

    line = doc.lines[line_idx]
    col = params.position.character

    # Find the word under the cursor (same rule as in rename)
    for m in re.finditer(r"[a-zA-Z_][a-zA-Z0-9_\.]*", line):
        if m.start() <= col <= m.end():
            word = m.group(0)
            # Eligibility: prepare_rename must return a Range for any symbol
            # type that rename() supports. rename() handles labels (via
            # _rename_label) and variables/transforms/screens (via
            # _rename_symbol_via_text_search). If the word is in any of
            # these snapshot sets, return its Range — VS Code then starts
            # the F2 session and calls rename().
            #
            # Previously this only checked labels — F2 silently did
            # nothing on variables/transforms/screens (P1-6 bug).
            #
            # UX: use the snapshot, not lsp_server.active_analyzer.*,
            # so F2 works even after did_change (analyze_file_only).
            snapshot = lsp_server.symbol_snapshot
            if (
                word in snapshot["labels"]
                or word in snapshot["variables"]
                or word in snapshot["transforms"]
                or word in snapshot["screens"]
            ):
                # Return the Range of the word. pygls/lsprotocol accepts a Range
                # or PrepareRenameResult(placeholder=...). A Range is enough.
                # UTF-16 positions for VS Code compatibility.
                start_utf16 = len(line[: m.start()].encode("utf-16-le")) // 2
                end_utf16 = start_utf16 + len(word.encode("utf-16-le")) // 2
                return lsp.Range(
                    start=lsp.Position(line=line_idx, character=start_utf16),
                    end=lsp.Position(line=line_idx, character=end_utf16),
                )
            # The word exists but is not a rename-able symbol — return None
            # ("can't rename here"). This includes words inside strings,
            # comments, and keywords that are not symbol names.
            return None

    # No word under the cursor
    return None


# =============================================================================
# textDocument/prepareCallHierarchy + incomingCalls + outgoingCalls
# =============================================================================
# Right-click on label → "Find Callers" / "Find References".
#
# Pipeline:
#   1. prepareCallHierarchy(item under cursor) → list[CallHierarchyItem]
#   2. callHierarchy/incomingCalls(item) → list[CallHierarchyIncomingCall] (who calls this?)
#   3. callHierarchy/outgoingCalls(item) → list[CallHierarchyOutgoingCall] (where does this go?)
#
# Sources:
#   - lsp_server.symbol_snapshot["labels"] for label lookup
#   - lsp_server.symbol_snapshot["jump_sources"] for incoming calls (who jumps to this label)
#   - LabelSymbol.outgoing_jumps for outgoing calls (where this label jumps to)
