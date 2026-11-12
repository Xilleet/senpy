"""LSP handlers: workspace.

Extracted from senpy/lsp/server.py in 0.6.0-8 (Phase 5).

Handlers:
  - workspace_symbol   ← WORKSPACE_SYMBOL
  - folding_range      ← TEXT_DOCUMENT_FOLDING_RANGE
  - document_highlight ← TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT
  - initialized        ← INITIALIZED

All functions accept (ls, params) and access shared state via
server_mod._X (lazy import breaks the import cycle).
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


def _get_server_mod():
    """Lazy access to senpy.lsp.server, breaks the import cycle."""
    from senpy.lsp import server

    return server


def workspace_symbol(
    ls: LanguageServer, params: lsp.WorkspaceSymbolParams
) -> list[lsp.WorkspaceSymbol]:
    server_mod = _get_server_mod()
    """Returns all project symbols (labels, screens, transforms).

    VS Code: Ctrl+T → search across all files of the project.
    """
    # state via _lsp_server.<attr>.
    lsp_server = server_mod._lsp_server
    if lsp_server.active_analyzer is None or not lsp_server.is_initialized:
        return []

    query = (params.query or "").lower()
    symbols: list[lsp.WorkspaceSymbol] = []

    def _matches(name: str) -> bool:
        """Checks whether the name matches the query (case-insensitive)."""
        if not query:
            return True
        return query in name.lower()

    # 1. Labels (SymbolKind.Function = 12)
    # UX: use the snapshot, not server_mod._active_analyzer.labels —
    # analyze_file_only clears labels from other files.
    for name, lbl in lsp_server.symbol_snapshot["labels"].items():
        if not _matches(name):
            continue
        lbl_line = max(0, lbl.line_number - 1)
        symbols.append(
            lsp.WorkspaceSymbol(
                name=name,
                kind=lsp.SymbolKind.Function,
                location=lsp.Location(
                    uri=server_mod._path_to_uri(lbl.file_path),
                    range=lsp.Range(
                        start=lsp.Position(line=lbl_line, character=0),
                        end=lsp.Position(line=lbl_line, character=len(name)),
                    ),
                ),
            )
        )

    # 2. Screens (SymbolKind.Object = 26)
    for name, scr in lsp_server.symbol_snapshot["screens"].items():
        if not _matches(name):
            continue
        scr_line = max(0, scr.line_number - 1)
        symbols.append(
            lsp.WorkspaceSymbol(
                name=name,
                kind=lsp.SymbolKind.Object,
                location=lsp.Location(
                    uri=server_mod._path_to_uri(scr.file_path),
                    range=lsp.Range(
                        start=lsp.Position(line=scr_line, character=0),
                        end=lsp.Position(line=scr_line, character=len(name)),
                    ),
                ),
            )
        )

    # 3. Transforms (SymbolKind.Function = 12)
    for name, trn in lsp_server.symbol_snapshot["transforms"].items():
        if not _matches(name):
            continue
        trn_line = max(0, trn.line_number - 1)
        symbols.append(
            lsp.WorkspaceSymbol(
                name=name,
                kind=lsp.SymbolKind.Function,
                location=lsp.Location(
                    uri=server_mod._path_to_uri(trn.file_path),
                    range=lsp.Range(
                        start=lsp.Position(line=trn_line, character=0),
                        end=lsp.Position(line=trn_line, character=len(name)),
                    ),
                ),
            )
        )

    return symbols


def folding_range(ls: LanguageServer, params: lsp.FoldingRangeParams) -> list[lsp.FoldingRange]:
    """Returns folding ranges for a .rpy file.

    VS Code uses this to fold blocks (Ctrl+Shift+[).
    """
    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc or not doc.lines:
        return []

    lines = doc.lines

    # Patterns for scope-opening lines (as in formatter _build_contexts)
    _RE_LABEL = re.compile(r"^label\s+(\w+)")
    _RE_SCREEN = re.compile(r"^screen\s+(\w+)")
    _RE_INIT = re.compile(r"^init\s+python")
    _RE_MENU = re.compile(r"^menu\s*:?")
    _RE_TRANSFORM = re.compile(r"^transform\s+(\w+)")
    _RE_PYTHON_BLOCK = re.compile(r"^python\s*:")
    _SCOPE_PATTERNS = (_RE_LABEL, _RE_SCREEN, _RE_INIT, _RE_MENU, _RE_TRANSFORM, _RE_PYTHON_BLOCK)

    ranges: list[lsp.FoldingRange] = []
    # Stack of open blocks: (start_line_0based, indent, keyword)
    open_blocks: list[tuple[int, int, str]] = []

    for i, raw_line in enumerate(lines):
        stripped = raw_line.lstrip(" \t")
        leading = raw_line[: len(raw_line) - len(stripped)]
        indent = len(leading.expandtabs(4))

        _close_blocks_at_indent(i, indent, open_blocks, ranges)

        clean = stripped.split("#")[0].strip()  # strip the comment
        if clean and _is_scope_opener_line(clean, _SCOPE_PATTERNS):
            open_blocks.append((i, indent, clean))

    _flush_open_blocks(len(lines), open_blocks, ranges)

    # Sort by start_line (blocks close in reverse order —
    # inner before outer, but the client expects them in order)
    ranges.sort(key=lambda r: r.start_line)
    return ranges


def _close_blocks_at_indent(
    current_line: int,
    current_indent: int,
    open_blocks: list[tuple[int, int, str]],
    ranges: list[lsp.FoldingRange],
) -> None:
    """Pop and emit folding ranges for any open blocks at indent ≥ current_indent."""
    while open_blocks and current_indent <= open_blocks[-1][1]:
        start_line, _start_indent, _keyword = open_blocks.pop()
        if current_line - 1 > start_line:  # at least 2 lines in the block
            ranges.append(
                lsp.FoldingRange(
                    start_line=start_line,
                    end_line=current_line - 1,
                    kind=lsp.FoldingRangeKind.Region,
                )
            )


def _is_scope_opener_line(clean: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    """True if the cleaned line opens a new Ren'Py scope (label, screen, menu, ...)."""
    if not clean.endswith(":"):
        return False
    return any(p.match(clean) for p in patterns)


def _flush_open_blocks(
    total_lines: int,
    open_blocks: list[tuple[int, int, str]],
    ranges: list[lsp.FoldingRange],
) -> None:
    """Close remaining open blocks (until end of file)."""
    last_line_idx = total_lines - 1
    for start_line, _start_indent, _keyword in open_blocks:
        if last_line_idx > start_line:
            ranges.append(
                lsp.FoldingRange(
                    start_line=start_line,
                    end_line=last_line_idx,
                    kind=lsp.FoldingRangeKind.Region,
                )
            )


def document_highlight(
    ls: LanguageServer, params: lsp.DocumentHighlightParams
) -> list[lsp.DocumentHighlight]:
    server_mod = _get_server_mod()
    """Highlights all occurrences of the word under the cursor in the current file.
    """
    # state via _lsp_server.<attr>.
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
    word = _extract_word_at_position(line, params.position.character)
    if not word:
        return []

    if not _is_user_symbol(word, lsp_server.active_analyzer):
        return []

    return _find_all_occurrences(word, doc.lines)


def _extract_word_at_position(line: str, col: int) -> str | None:
    """Extract the identifier under the cursor position."""
    for m in re.finditer(r"[a-zA-Z_][a-zA-Z0-9_\.]*", line):
        if m.start() <= col <= m.end():
            return m.group(0)
    return None


def _is_user_symbol(word: str, analyzer) -> bool:
    """Check if word is a user-defined symbol (label/screen/transform/variable)."""
    return (
        word in analyzer.labels
        or word in analyzer.screens
        or word in analyzer.transforms
        or word in analyzer.variables
        or word in analyzer.user_symbols
    )


def _find_all_occurrences(word: str, lines: list[str]) -> list[lsp.DocumentHighlight]:
    """Find all whole-word occurrences of `word` in `lines`, classifying each
    as Read or Write (declaration lines get Write)."""
    highlights: list[lsp.DocumentHighlight] = []
    for i, file_line in enumerate(lines):
        start = 0
        while True:
            pos = file_line.find(word, start)
            if pos == -1:
                break
            before = file_line[pos - 1] if pos > 0 else " "
            after = file_line[pos + len(word)] if pos + len(word) < len(file_line) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                stripped = file_line.strip()
                is_declaration = (
                    stripped.startswith(f"label {word}")
                    or stripped.startswith(f"screen {word}")
                    or stripped.startswith(f"transform {word}")
                    or stripped.startswith(f"default {word}")
                    or stripped.startswith(f"define {word}")
                )
                kind = (
                    lsp.DocumentHighlightKind.Write
                    if is_declaration
                    else lsp.DocumentHighlightKind.Read
                )
                highlights.append(
                    lsp.DocumentHighlight(
                        range=lsp.Range(
                            start=lsp.Position(line=i, character=pos),
                            end=lsp.Position(line=i, character=pos + len(word)),
                        ),
                        kind=kind,
                    )
                )
            start = pos + 1
    return highlights


def initialized(ls: LanguageServer, params: lsp.InitializedParams) -> None:
    """Starts full project diagnostics immediately after LSP initialization."""
    server_mod = _get_server_mod()

    try:
        root = ls.workspace.root_path
    except AttributeError:
        root = None

    if root:
        # WRITE to module global via @property setter.
        # _lsp_server.current_workspace_root = X triggers the setter which
        # does `global _current_workspace_root; _current_workspace_root = X`.
        # Same state, different access path. Tested by test_lsp_server_properties.py.
        lsp_server = server_mod._lsp_server
        lsp_server.current_workspace_root = root
        # Start a full scan in the background (debounced)
        server_mod.schedule_full_diagnostics(ls, "")
