"""LSP handler: textDocument/documentSymbol (Ctrl+Shift+O).

Extracted from senpy/lsp/handlers/navigation.py.
Builds the outline view for the current file — labels, screens,
transforms, variables, images.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    try:
        from pygls.lsp.server import LanguageServer
    except ImportError:
        from pygls.server import LanguageServer  # type: ignore[attr-defined, no-redef]

from lsprotocol import types as lsp

from senpy.lsp.handlers._shared import _get_server_mod


def document_symbols(
    ls: LanguageServer, params: lsp.DocumentSymbolParams
) -> list[lsp.DocumentSymbol]:
    """Builds the native symbol tree for Outline (Structure), Breadcrumbs and Ctrl+Shift+O."""
    server_mod = _get_server_mod()
    # Phase 3.3c-e: state via _lsp_server.<attr>.
    lsp_server = server_mod._lsp_server
    if lsp_server.active_analyzer is None:
        return []

    uri = params.text_document.uri
    file_path = server_mod._uri_to_path(uri)
    norm_path = server_mod._normalize_path(file_path)  # P0-6: unified normalization

    # Read the scope from the analyzer's file_scopes. If the scope is
    # missing, return [] — do NOT call _collect_symbols to populate it
    # on the fly. _collect_symbols mutates analyzer.file_scopes and
    # analyzer._stage1_lines, but document_symbols is registered with
    # @_with_analysis_lock (read lock) — readers must not write (P1-8).
    #
    # The empty-scope case happens during the did_open → full-analysis
    # race: did_open schedules run_full_project_diagnostics with a 300ms
    # debounce. If document_symbols arrives in those 300ms, file_scopes
    # is not yet populated. Returning [] is safe — the scheduled full
    # analysis will populate the scope, and VS Code re-requests the
    # outline on did_change / did_save, so the user sees it within ~1s.
    scope = lsp_server.active_analyzer.file_scopes.get(norm_path)
    if not scope:
        return []

    doc = ls.workspace.get_text_document(uri)
    lines = doc.lines if doc and doc.lines else []
    total_lines = len(lines) if lines else 1000

    raw_entries = _collect_symbol_entries(scope)
    raw_entries.sort(key=lambda x: x[0])
    return _build_document_symbols(raw_entries=raw_entries, lines=lines, total_lines=total_lines)


# A "raw entry" before it becomes a DocumentSymbol:
#   (start_line, name, kind, detail, is_block)
# `is_block` = True means the symbol's range should extend to the start of
# the next block entry (or end-of-file) — used for labels, screens, etc.
# that own a body. False means the range is a single line (variables, plain images).
RawSymbolEntry = tuple[int, str, "lsp.SymbolKind", str, bool]


def _collect_symbol_entries(scope) -> list[RawSymbolEntry]:
    """Collect every declared symbol in `scope` into a flat list of raw entries.

    Order: labels → screens → images → transforms → variables. The caller
    sorts by `start_line` before building the final DocumentSymbols.
    """
    entries: list[RawSymbolEntry] = []
    entries.extend(_collect_label_symbols(scope))
    entries.extend(_collect_screen_symbols(scope))
    entries.extend(_collect_image_symbols(scope))
    entries.extend(_collect_transform_symbols(scope))
    entries.extend(_collect_variable_symbols(scope))
    return entries


def _collect_label_symbols(scope) -> list[RawSymbolEntry]:
    """Labels (skip names starting with `_`). Treated as blocks (own a body)."""
    entries: list[RawSymbolEntry] = []
    for name, sym in scope.labels.items():
        if name.startswith("_"):
            continue
        entries.append((max(0, sym.line_number - 1), name, lsp.SymbolKind.Function, "Label", True))
    return entries


def _collect_screen_symbols(scope) -> list[RawSymbolEntry]:
    """Screens. Treated as blocks."""
    entries: list[RawSymbolEntry] = []
    for name, sym in scope.screens.items():
        entries.append(
            (max(0, sym.line_number - 1), name, lsp.SymbolKind.Interface, "Screen", True)
        )
    return entries


def _collect_image_symbols(scope) -> list[RawSymbolEntry]:
    """Images. Layered images are blocks (own an ATL body), plain images are not."""
    entries: list[RawSymbolEntry] = []
    for name, sym in scope.images.items():
        if sym.is_layered:
            entries.append(
                (max(0, sym.line_number - 1), name, lsp.SymbolKind.Class, "Layered Image", True)
            )
        else:
            entries.append(
                (max(0, sym.line_number - 1), name, lsp.SymbolKind.Field, "Image", False)
            )
    return entries


def _collect_transform_symbols(scope) -> list[RawSymbolEntry]:
    """ATL transforms. Treated as blocks (own an ATL body)."""
    entries: list[RawSymbolEntry] = []
    for name, sym in scope.transforms.items():
        entries.append(
            (max(0, sym.line_number - 1), name, lsp.SymbolKind.Function, "Transform", True)
        )
    return entries


def _collect_variable_symbols(scope) -> list[RawSymbolEntry]:
    """Variables (`default`) and constants (`define`). Skip `_`-prefixed and Character definitions.

    Treated as single-line entries (no body to span).
    """
    entries: list[RawSymbolEntry] = []
    for name, sym in scope.variables.items():
        if name.startswith("_") or sym.is_character:
            continue
        kind = lsp.SymbolKind.Constant if sym.is_constant else lsp.SymbolKind.Variable
        detail = "Constant (define)" if sym.is_constant else "Variable (default)"
        entries.append((max(0, sym.line_number - 1), name, kind, detail, False))
    return entries


def _build_document_symbols(
    *,
    raw_entries: list[RawSymbolEntry],
    lines: Sequence[str],
    total_lines: int,
) -> list[lsp.DocumentSymbol]:
    """Convert sorted `raw_entries` into LSP DocumentSymbols.

    For block entries (label/screen/transform/layered-image), the range
    extends to the start of the next block entry (or end-of-file). For
    non-block entries (variable/plain image), the range is a single line.

    The selection range (the highlighted region VS Code uses for "Go to
    Symbol") is just the identifier at the start of the line.
    """
    symbols: list[lsp.DocumentSymbol] = []
    for i, (start_line, name, kind, detail, is_block) in enumerate(raw_entries):
        line_text = lines[start_line] if start_line < len(lines) else ""
        col_idx = line_text.find(name)
        start_char = max(0, col_idx) if col_idx != -1 else 0

        if is_block:
            next_block = next((e for e in raw_entries[i + 1 :] if e[4]), None)
            end_line = (
                max(start_line, next_block[0] - 1)
                if next_block
                else max(start_line, total_lines - 1)
            )
        else:
            end_line = start_line

        end_char = len(lines[end_line].rstrip()) if end_line < len(lines) else 0

        symbols.append(
            lsp.DocumentSymbol(
                name=name,
                kind=kind,
                range=lsp.Range(
                    start=lsp.Position(line=start_line, character=0),
                    end=lsp.Position(line=end_line, character=end_char),
                ),
                selection_range=lsp.Range(
                    start=lsp.Position(line=start_line, character=start_char),
                    end=lsp.Position(line=start_line, character=start_char + len(name)),
                ),
                detail=detail,
            )
        )
    return symbols
