"""LSP handler: textDocument/references (Shift+F12).

Extracted from senpy/lsp/handlers/navigation.py.
Finds all references to a symbol across the project via text search
+ kind-specific filtering.
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
    _find_text_occurrences_in_project,
    _get_server_mod,
)


def references(ls: LanguageServer, params: lsp.ReferenceParams) -> list[lsp.Location] | None:
    server_mod = _get_server_mod()
    # Phase 3.3c-e: state via _lsp_server.<attr>.
    lsp_server = server_mod._lsp_server
    """Find References: all static jump/call references to the label under the cursor."""
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

    # Same word extractor as in definition/hover
    word = None
    for m in re.finditer(r"[a-zA-Z_][a-zA-Z0-9_\.]*", line):
        if m.start() <= col <= m.end():
            word = m.group(0)
            break

    if not word:
        return None

    locations: list[lsp.Location] = []

    # references for labels: use _symbol_snapshot, not _active_analyzer.
    # After did_change → analyze_file_only, the live analyzer's label
    # registry is rebuilt for the edited file only — labels from other
    # files disappear from the live registry. _symbol_snapshot is
    # refreshed on did_open / did_save / did_change_watched_files and
    # retains labels from all files. Other handlers (rename,
    # prepare_rename, incoming_calls, outgoing_calls, workspace_symbol)
    # already use the snapshot — references must be consistent (P1-7).
    snapshot = lsp_server.symbol_snapshot
    if word in snapshot["labels"]:
        if params.context.include_declaration:
            lbl = snapshot["labels"][word]
            locations.append(
                lsp.Location(
                    uri=server_mod._path_to_uri(lbl.file_path),
                    range=lsp.Range(
                        start=lsp.Position(line=max(0, lbl.line_number - 1), character=0),
                        end=lsp.Position(line=max(0, lbl.line_number - 1), character=len(word)),
                    ),
                )
            )
        for ref_path, ref_line in snapshot["jump_sources"].get(word, []):
            locations.append(
                lsp.Location(
                    uri=server_mod._path_to_uri(ref_path),
                    range=lsp.Range(
                        start=lsp.Position(line=max(0, ref_line - 1), character=0),
                        end=lsp.Position(line=max(0, ref_line - 1), character=len(word)),
                    ),
                )
            )
        return locations

    # references for variables/transforms/screens via text search.
    # They have no reverse index (like jump_sources for labels), so we use
    # _find_text_occurrences_in_project — a whole-word grep across all .rpy files.
    if (
        word in lsp_server.symbol_snapshot["variables"]
        or word in lsp_server.symbol_snapshot["transforms"]
        or word in lsp_server.symbol_snapshot["screens"]
    ):
        return _references_via_text_search(server_mod, word, params.context.include_declaration)

    return None


def _references_via_text_search(
    server_mod, word: str, include_declaration: bool
) -> list[lsp.Location]:
    """helper: references for variables/transforms/screens.

    Uses _find_text_occurrences_in_project. If include_declaration=False,
    excludes the first location (the declaration) — it is identified via the snapshot.
    """
    # Phase 3.3c-e: state via _lsp_server.<attr>.
    lsp_server = server_mod._lsp_server
    occurrences = _find_text_occurrences_in_project(server_mod, word)
    if not occurrences:
        return []

    # If the declaration should not be included — find it via the snapshot and exclude it.
    declaration_loc: tuple[str, int] | None = None  # (file_path, line_idx_0based)
    for kind in ("variables", "transforms", "screens"):
        sym = lsp_server.symbol_snapshot[kind].get(word)
        if sym is not None:
            declaration_loc = (sym.file_path, max(0, sym.line_number - 1))
            break

    locations: list[lsp.Location] = []
    word_len_utf16 = len(word.encode("utf-16-le")) // 2

    for fpath, line_idx, col_utf16 in occurrences:
        if (
            not include_declaration
            and declaration_loc is not None
            and fpath == declaration_loc[0]
            and line_idx == declaration_loc[1]
        ):
            continue
        locations.append(
            lsp.Location(
                uri=server_mod._path_to_uri(fpath),
                range=lsp.Range(
                    start=lsp.Position(line=line_idx, character=col_utf16),
                    end=lsp.Position(line=line_idx, character=col_utf16 + word_len_utf16),
                ),
            )
        )

    return locations
