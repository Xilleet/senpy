"""LSP handler: textDocument/references (Shift+F12).

Extracted from senpy/lsp/handlers/navigation.py.
Finds all references to a symbol across the project via text search
+ kind-specific filtering.
"""

from __future__ import annotations

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
    _word_at_position,
)


def references(ls: LanguageServer, params: lsp.ReferenceParams) -> list[lsp.Location] | None:
    """Find References: all static jump/call references to the label under the cursor."""
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

    # Delegate to the canonical unicode-aware word extractor in
    # ``_shared.py`` (previously inline ASCII-only regex).
    word = _word_at_position(line, col)

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
    #
    # Resolve the symbol_kind FIRST (the kind in which the word is
    # declared) and pass it down so the text-search path applies the
    # same ``_filter_occurrences_by_kind`` filter that ``rename``
    # uses. Without the filter, Find References shows natural-language
    # mentions in dialogue that Rename silently ignores — the two
    # handlers diverge (a user sees 12 references, hits F2, only 7
    # change). The kind is the FIRST of (variables, transforms, screens)
    # in which the snapshot has the word; if a name is overloaded
    # across kinds, the caller already disambiguates via cursor context
    # in practice.
    symbol_kind: str | None = None
    for kind in ("variables", "transforms", "screens"):
        if word in lsp_server.symbol_snapshot[kind]:
            symbol_kind = kind
            break
    if symbol_kind is not None:
        return _references_via_text_search(
            server_mod, word, params.context.include_declaration, symbol_kind
        )

    return None


def _references_via_text_search(
    server_mod, word: str, include_declaration: bool, symbol_kind: str
) -> list[lsp.Location]:
    """helper: references for variables/transforms/screens.

    Uses ``_find_text_occurrences_in_project`` to gather every whole-word
    match, then applies ``_filter_occurrences_by_kind`` so the result
    matches what ``rename`` would actually edit (parity: Find References
    and Rename must agree on which occurrences are real references).
    If ``include_declaration`` is False, the declaration location —
    identified via the snapshot — is excluded from the result.
    """

    lsp_server = server_mod._lsp_server
    occurrences = _find_text_occurrences_in_project(server_mod, word)
    if not occurrences:
        return []

    # Filter to real references of the requested kind — same filter
    # as ``rename._rename_symbol_via_text_search``. This drops
    # natural-language mentions in dialogue (e.g. ``"You have no gold
    # left."``) and label/jump/screen-declaration lines that share the
    # textual token but are not references of ``symbol_kind``.
    occurrences = _filter_occurrences_by_kind(occurrences, word, symbol_kind)
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
