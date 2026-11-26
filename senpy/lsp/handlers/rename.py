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
    _WORD_BOUNDARY_TEMPLATE,
    _filter_occurrences_by_kind,
    _find_text_occurrences_in_project,
    _get_server_mod,
    _read_file_lines,
    _word_at_position,
)


def _word_edits_on_line(line: str, line_idx: int, word: str, new_name: str) -> list[lsp.TextEdit]:
    """Build a ``lsp.TextEdit`` for EVERY whole-word match of ``word`` on ``line``.

    Replaces the previous ``str.find(word)`` approach which only found
    the FIRST occurrence — on ``$ gold = gold + 1`` the second ``gold``
    was left untouched and the file became ``$ silver = gold + 1``,
    a silent corruption. The word-boundary regex (same template as
    ``_find_text_occurrences_in_project``) finds every whole-word
    occurrence; each gets its own edit with UTF-16 column offsets.
    """
    edits: list[lsp.TextEdit] = []
    pattern = re.compile(_WORD_BOUNDARY_TEMPLATE.format(re.escape(word)))
    word_len_utf16 = len(word.encode("utf-16-le")) // 2
    for m in pattern.finditer(line):
        start_utf16 = len(line[: m.start()].encode("utf-16-le")) // 2
        edits.append(
            lsp.TextEdit(
                range=lsp.Range(
                    start=lsp.Position(line=line_idx, character=start_utf16),
                    end=lsp.Position(line=line_idx, character=start_utf16 + word_len_utf16),
                ),
                new_text=new_name,
            )
        )
    return edits


def rename(ls: LanguageServer, params: lsp.RenameParams) -> lsp.WorkspaceEdit | None:
    """Label rename: updates the declaration + all jump/call references."""
    server_mod = _get_server_mod()
    # Phase 3.3c-e: state via _lsp_server.<attr>.
    lsp_server = server_mod._lsp_server
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

    # Extract the word under the cursor — delegate to the canonical
    # unicode-aware extractor in ``_shared.py``.
    word = _word_at_position(line, col)

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

    Reads file content via ``_read_file_lines`` (in-memory first, then disk)
    so line indices from the symbol snapshot (which reflect IN-MEMORY
    content) match the lines we read. Without this, rename would apply
    TextEdits at stale DISK positions when the user has unsaved buffer
    changes — silent file corruption (Task 74).

    Batches reads by file: a label with N references in the same file
    triggers ONE read of that file, not N reads (the previous code opened
    the file once per reference).
    """
    # Phase 3.3c-e: state via _lsp_server.<attr>.
    lsp_server = server_mod._lsp_server
    changes: dict[str, list[lsp.TextEdit]] = {}

    # Collect (file_path, line_1based) for declaration + all refs.
    # Group by file to amortise reads (1 read per file, not per ref).
    targets: list[tuple[str, int]] = []

    # 1. Declaration (label X:)
    lbl = lsp_server.symbol_snapshot["labels"][word]
    targets.append((lbl.file_path, lbl.line_number))

    # 2. All jump/call references (from jump_sources)
    # UX: also from the snapshot, to get references from all files.
    for ref_path, ref_line in lsp_server.symbol_snapshot["jump_sources"].get(word, []):
        targets.append((ref_path, ref_line))

    # Group by file path → list of 1-based line numbers.
    by_file: dict[str, list[int]] = {}
    for fpath, line_1 in targets:
        by_file.setdefault(fpath, []).append(line_1)

    for fpath, line_1s in by_file.items():
        # Read via _read_file_lines: in-memory (unsaved) content first,
        # then disk. The snapshot's line numbers reflect IN-MEMORY
        # content (set by analyze_file_only from in_memory_files) —
        # reading DISK here would index the wrong line (Task 74).
        lines = _read_file_lines(server_mod, fpath)
        if lines is None:
            continue
        uri = server_mod._path_to_uri(fpath)
        for line_1 in line_1s:
            line_0 = max(0, line_1 - 1)  # 0-based
            if line_0 >= len(lines):
                continue
            content = lines[line_0]
            # Replace EVERY whole-word occurrence on the line (not just
            # the first ``str.find`` hit) — the declaration line of a
            # label does not normally repeat the name, but using the
            # helper keeps the two paths consistent and protects
            # against pathological ``label gold gold:`` input. For
            # references, ``$ gold = gold + 1`` would otherwise become
            # ``$ silver = gold + 1`` (silent corruption: the second
            # reference left untouched).
            changes.setdefault(uri, []).extend(_word_edits_on_line(content, line_0, word, new_name))

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
    """Returns the Range of the word under the cursor for preview before rename."""
    server_mod = _get_server_mod()
    # Phase 3.3c-e: state via _lsp_server.<attr>.
    lsp_server = server_mod._lsp_server
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

    # Find the word under the cursor (same rule as in rename) — delegate
    # to the canonical unicode-aware extractor.
    word = _word_at_position(line, col)
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
    if not word:
        # No word under the cursor
        return None
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
        # ``_word_at_position`` returns the matched word but not its
        # position; re-find it via ``line.find(word)`` (first occurrence).
        # ``col`` is guaranteed to be inside the match (by _word_at_position),
        # so the first occurrence is correct for cursor-based rename.
        word_start = line.find(word)
        start_utf16 = len(line[:word_start].encode("utf-16-le")) // 2
        end_utf16 = start_utf16 + len(word.encode("utf-16-le")) // 2
        return lsp.Range(
            start=lsp.Position(line=line_idx, character=start_utf16),
            end=lsp.Position(line=line_idx, character=end_utf16),
        )
    # The word exists but is not a rename-able symbol — return None
    # ("can't rename here"). This includes words inside strings,
    # comments, and keywords that are not symbol names.
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
