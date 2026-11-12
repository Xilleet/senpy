"""LSP handlers: callHierarchy/* (incoming/outgoing calls).

Extracted from senpy/lsp/handlers/navigation.py.
Prepares call hierarchy for labels — who jumps to this label
(incoming) and where this label jumps to (outgoing).
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

from senpy.lsp.handlers._shared import _get_server_mod


def prepare_call_hierarchy(
    ls: LanguageServer, params: lsp.CallHierarchyPrepareParams
) -> list[lsp.CallHierarchyItem]:
    """Return CallHierarchyItem for label under cursor.

    Returns empty list if cursor is not on a label declaration or reference.
    """
    server_mod = _get_server_mod()
    # Phase 3.3c-e: state via _lsp_server.<attr>.
    lsp_server = server_mod._lsp_server
    if lsp_server.active_analyzer is None or not lsp_server.is_initialized:
        return []

    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc or not doc.lines:
        return []

    line_idx = params.position.line
    if line_idx >= len(doc.lines):
        return []

    line = doc.lines[line_idx]
    col = params.position.character

    # Find word under cursor
    word = None
    for m in re.finditer(r"[a-zA-Z_][a-zA-Z0-9_\.]*", line):
        if m.start() <= col <= m.end():
            word = m.group(0)
            break

    if not word:
        return []

    # Check if word is a label (in snapshot, with fallback to analyzer)
    labels = lsp_server.symbol_snapshot.get("labels", {})
    if word not in labels and lsp_server.active_analyzer is not None:
        labels = lsp_server.active_analyzer.labels
    if word not in labels:
        return []

    label = labels[word]
    # Build CallHierarchyItem
    return [
        lsp.CallHierarchyItem(
            name=word,
            kind=lsp.SymbolKind.Function,  # labels are like functions
            uri=server_mod._path_to_uri(label.file_path),
            range=lsp.Range(
                start=lsp.Position(line=max(0, label.line_number - 1), character=0),
                end=lsp.Position(line=max(0, label.line_number - 1), character=len(line.rstrip())),
            ),
            selection_range=lsp.Range(
                start=lsp.Position(line=max(0, label.line_number - 1), character=0),
                end=lsp.Position(line=max(0, label.line_number - 1), character=len(word)),
            ),
        )
    ]


def incoming_calls(
    ls: LanguageServer, params: lsp.CallHierarchyIncomingCallsParams
) -> list[lsp.CallHierarchyIncomingCall]:
    """Find all labels that call/jump to the given label.

    Uses jump_sources reverse index from analyzer snapshot.
    """
    server_mod = _get_server_mod()
    # Phase 3.3c-e: state via _lsp_server.<attr>.
    lsp_server = server_mod._lsp_server
    if lsp_server.active_analyzer is None or not lsp_server.is_initialized:
        return []

    target_name = params.item.name
    labels = lsp_server.symbol_snapshot.get("labels", {})
    jump_sources = lsp_server.symbol_snapshot.get("jump_sources", {})
    labels_by_file = lsp_server.symbol_snapshot.get("labels_by_file", {})
    # Fallback: if not in snapshot, check analyzer directly
    if not jump_sources and lsp_server.active_analyzer is not None:
        jump_sources = lsp_server.active_analyzer.jump_sources
    if not labels and lsp_server.active_analyzer is not None:
        labels = lsp_server.active_analyzer.labels
    # Build labels_by_file on-the-fly if the snapshot is stale or empty —
    # keeps the handler correct even before the first _refresh_symbol_snapshot.
    if not labels_by_file and labels:
        labels_by_file = {}
        for name, lbl in labels.items():
            labels_by_file.setdefault(lbl.file_path, []).append((name, lbl.line_number))
        for file_labels in labels_by_file.values():
            file_labels.sort(key=lambda item: item[1])

    incoming: list[lsp.CallHierarchyIncomingCall] = []

    # jump_sources maps: target_label → list of (file_path, line_number)
    for caller_path, caller_line in jump_sources.get(target_name, []):
        # Find the label that contains this call site using the per-file
        # index — O(labels_in_file) instead of O(all_labels). The index
        # is sorted by line_number, so the last entry with line <= caller_line
        # is the containing label.
        caller_label = None
        caller_name = "<anonymous>"
        for name, line in labels_by_file.get(caller_path, []):
            if line <= caller_line:
                caller_label = labels.get(name)
                caller_name = name
            else:
                break  # sorted — no more labels <= caller_line

        if caller_label is None:
            # Fallback: use the file/line without a label name
            caller_name = "<anonymous>"
            caller_label_uri = server_mod._path_to_uri(caller_path)
            caller_range = lsp.Range(
                start=lsp.Position(line=max(0, caller_line - 1), character=0),
                end=lsp.Position(line=max(0, caller_line - 1), character=80),
            )
        else:
            caller_label_uri = server_mod._path_to_uri(caller_label.file_path)
            caller_range = lsp.Range(
                start=lsp.Position(line=max(0, caller_label.line_number - 1), character=0),
                end=lsp.Position(line=max(0, caller_label.line_number - 1), character=80),
            )

        # Build the caller's CallHierarchyItem
        caller_item = lsp.CallHierarchyItem(
            name=caller_name,
            kind=lsp.SymbolKind.Function,
            uri=caller_label_uri,
            range=caller_range,
            selection_range=caller_range,
        )

        # fromRanges: where the call happens (the line with jump/call)
        call_range = lsp.Range(
            start=lsp.Position(line=max(0, caller_line - 1), character=0),
            end=lsp.Position(line=max(0, caller_line - 1), character=80),
        )

        incoming.append(
            lsp.CallHierarchyIncomingCall(
                from_=caller_item,
                from_ranges=[call_range],
            )
        )

    return incoming


def outgoing_calls(
    ls: LanguageServer, params: lsp.CallHierarchyOutgoingCallsParams
) -> list[lsp.CallHierarchyOutgoingCall]:
    """Find all labels that this label jumps/calls to.

    Uses LabelSymbol.outgoing_jumps from analyzer snapshot.
    """
    server_mod = _get_server_mod()
    # Phase 3.3c-e: state via _lsp_server.<attr>.
    lsp_server = server_mod._lsp_server
    if lsp_server.active_analyzer is None or not lsp_server.is_initialized:
        return []

    source_name = params.item.name
    labels = lsp_server.symbol_snapshot.get("labels", {})
    jump_sources = lsp_server.symbol_snapshot.get("jump_sources", {})
    labels_by_file = lsp_server.symbol_snapshot.get("labels_by_file", {})
    # Fallback: if not in snapshot, check analyzer directly
    if source_name not in labels and lsp_server.active_analyzer is not None:
        labels = lsp_server.active_analyzer.labels
    if not jump_sources and lsp_server.active_analyzer is not None:
        jump_sources = lsp_server.active_analyzer.jump_sources
    if not labels_by_file and labels:
        labels_by_file = {}
        for name, lbl in labels.items():
            labels_by_file.setdefault(lbl.file_path, []).append((name, lbl.line_number))
        for file_labels in labels_by_file.values():
            file_labels.sort(key=lambda item: item[1])

    if source_name not in labels:
        return []

    source_label = labels[source_name]
    # Determine the source label's body range: [source_label.line_number + 1,
    # next_label_line_in_same_file). Jumps inside this range belong to source.
    # Without this bound, a jump to the same target from a LATER label in the
    # same file would be misattributed to source.
    source_end_line = float("inf")
    for _name, line in labels_by_file.get(source_label.file_path, []):
        if line > source_label.line_number:
            source_end_line = line
            break  # sorted — first label after source is the next sibling

    outgoing: list[lsp.CallHierarchyOutgoingCall] = []

    # outgoing_jumps is a set of target label names
    for target_name in source_label.outgoing_jumps:
        if target_name not in labels:
            continue  # target doesn't exist (will be flagged by RPY302)

        target_label = labels[target_name]
        target_item = lsp.CallHierarchyItem(
            name=target_name,
            kind=lsp.SymbolKind.Function,
            uri=server_mod._path_to_uri(target_label.file_path),
            range=lsp.Range(
                start=lsp.Position(line=max(0, target_label.line_number - 1), character=0),
                end=lsp.Position(line=max(0, target_label.line_number - 1), character=80),
            ),
            selection_range=lsp.Range(
                start=lsp.Position(line=max(0, target_label.line_number - 1), character=0),
                end=lsp.Position(
                    line=max(0, target_label.line_number - 1), character=len(target_name)
                ),
            ),
        )

        # fromRanges: where the call happens in the source label's body.
        # jump_sources maps target → list of (file, line) for every jump to
        # that target across the project. Filter to entries that originate
        # from THIS source label's body (same file, line between source
        # declaration and the next sibling label). Each matching entry
        # becomes one Range in from_ranges — the LSP spec explicitly allows
        # multiple ranges when the same target is called multiple times.
        jump_lines = [
            line
            for file_path, line in jump_sources.get(target_name, [])
            if file_path == source_label.file_path
            and source_label.line_number < line < source_end_line
        ]

        if jump_lines:
            from_ranges = [
                lsp.Range(
                    start=lsp.Position(line=max(0, line - 1), character=0),
                    end=lsp.Position(line=max(0, line - 1), character=80),
                )
                for line in jump_lines
            ]
        else:
            # Fallback: jump line not tracked (dynamic jump via
            # renpy.jump() in a string, or jump_sources not populated).
            # Fall back to the source label's declaration line rather
            # than dropping the outgoing call entirely — the user still
            # sees that source calls target, even if the exact line is
            # unknown.
            from_ranges = [
                lsp.Range(
                    start=lsp.Position(line=max(0, source_label.line_number - 1), character=0),
                    end=lsp.Position(line=max(0, source_label.line_number - 1), character=80),
                )
            ]

        outgoing.append(
            lsp.CallHierarchyOutgoingCall(
                to=target_item,
                from_ranges=from_ranges,
            )
        )

    return outgoing
