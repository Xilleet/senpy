"""LSP handlers: workspace.

Вынесено из senpy/lsp/server.py в 0.6.0-8 (Фаза 5).

Handler'ы:
  - workspace_symbol   ← WORKSPACE_SYMBOL
  - folding_range      ← TEXT_DOCUMENT_FOLDING_RANGE
  - document_highlight ← TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT
  - initialized        ← INITIALIZED

Все функции принимают (ls, params) и обращаются к shared state через
server_mod._X (lazy import разрывает цикл импортов).
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    try:
        from pygls.lsp.server import LanguageServer
    except ImportError:
        from pygls.server import LanguageServer

from lsprotocol import types as lsp


def _get_server_mod():
    """Ленивый доступ к senpy.lsp.server, разрывает цикл импортов."""
    from senpy.lsp import server
    return server


def workspace_symbol(
    ls: LanguageServer, params: lsp.WorkspaceSymbolParams
) -> list[lsp.WorkspaceSymbol]:
    server_mod = _get_server_mod()
    """Возвращает все символы проекта (labels, screens, transforms).

    VS Code: Ctrl+T → поиск по всем файлам проекта.
    """
    if server_mod._active_analyzer is None or not server_mod._is_initialized:
        return []

    query = (params.query or "").lower()
    symbols: list[lsp.WorkspaceSymbol] = []

    def _matches(name: str) -> bool:
        """Проверяет, подходит ли имя под query (case-insensitive)."""
        if not query:
            return True
        return query in name.lower()

    # 1. Labels (SymbolKind.Function = 12)
    # UX-EXT-5: используем snapshot, не server_mod._active_analyzer.labels —
    # analyze_file_only чистит labels из других файлов.
    for name, lbl in server_mod._symbol_snapshot["labels"].items():
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
    for name, scr in server_mod._symbol_snapshot["screens"].items():
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
    for name, trn in server_mod._symbol_snapshot["transforms"].items():
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
    server_mod = _get_server_mod()
    """Возвращает folding ranges для .rpy файла.

    VS Code использует это для сворачивания блоков (Ctrl+Shift+[).
    """
    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc or not doc.lines:
        return []

    lines = doc.lines

    # Паттерны для scope-opening строк (как в formatter _build_contexts)
    _RE_LABEL = re.compile(r"^label\s+(\w+)")
    _RE_SCREEN = re.compile(r"^screen\s+(\w+)")
    _RE_INIT = re.compile(r"^init\s+python")
    _RE_MENU = re.compile(r"^menu\s*:?")
    _RE_TRANSFORM = re.compile(r"^transform\s+(\w+)")
    _RE_PYTHON_BLOCK = re.compile(r"^python\s*:")

    ranges: list[lsp.FoldingRange] = []

    # Стек открытых блоков: (start_line_0based, indent, keyword)
    open_blocks: list[tuple[int, int, str]] = []

    for i, raw_line in enumerate(lines):
        # Считаем отступ (в пробелах, с expandtabs)
        stripped = raw_line.lstrip(" \t")
        leading = raw_line[: len(raw_line) - len(stripped)]
        indent = len(leading.expandtabs(4))

        # Закрываем блоки с бОльшим или равным отступом
        while open_blocks and indent <= open_blocks[-1][1]:
            start_line, start_indent, keyword = open_blocks.pop()
            if i - 1 > start_line:  # минимум 2 строки в блоке
                ranges.append(
                    lsp.FoldingRange(
                        start_line=start_line,
                        end_line=i - 1,
                        kind=lsp.FoldingRangeKind.Region,
                    )
                )

        # Проверяем, открывает ли строка новый scope
        clean = stripped.split("#")[0].strip()  # убираем комментарий
        if clean:
            is_scope_opener = (
                _RE_LABEL.match(clean)
                or _RE_SCREEN.match(clean)
                or _RE_INIT.match(clean)
                or _RE_MENU.match(clean)
                or _RE_TRANSFORM.match(clean)
                or _RE_PYTHON_BLOCK.match(clean)
            )
            if is_scope_opener and clean.endswith(":"):
                open_blocks.append((i, indent, clean))

    # Закрываем оставшиеся открытые блоки (до конца файла)
    for start_line, start_indent, keyword in open_blocks:
        if len(lines) - 1 > start_line:
            ranges.append(
                lsp.FoldingRange(
                    start_line=start_line,
                    end_line=len(lines) - 1,
                    kind=lsp.FoldingRangeKind.Region,
                )
            )

    # Сортируем по start_line (блоки закрываются в обратном порядке —
    # внутренние раньше внешних, но клиент ожидает по порядку)
    ranges.sort(key=lambda r: r.start_line)
    return ranges


def document_highlight(
    ls: LanguageServer, params: lsp.DocumentHighlightParams
) -> list[lsp.DocumentHighlight]:
    server_mod = _get_server_mod()
    """Подсвечивает все упоминания слова под курсором в текущем файле."""
    if server_mod._active_analyzer is None or not server_mod._is_initialized:
        return []

    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc or not doc.lines:
        return []

    line_idx = params.position.line
    if line_idx >= len(doc.lines):
        return []

    line = doc.lines[line_idx]
    col = params.position.character

    # Извлекаем слово под курсором
    word = None
    for m in re.finditer(r"[a-zA-Z_][a-zA-Z0-9_\.]*", line):
        if m.start() <= col <= m.end():
            word = m.group(0)
            break

    if not word:
        return []

    # Проверяем, что это user-defined символ (label/screen/transform/variable)
    is_user_symbol = (
        word in server_mod._active_analyzer.labels
        or word in server_mod._active_analyzer.screens
        or word in server_mod._active_analyzer.transforms
        or word in server_mod._active_analyzer.variables
        or word in server_mod._active_analyzer.user_symbols
    )

    if not is_user_symbol:
        return []

    # Ищем все вхождения слова в текущем файле
    highlights: list[lsp.DocumentHighlight] = []
    file_path = server_mod._uri_to_path(params.text_document.uri)

    for i, file_line in enumerate(doc.lines):
        # Простое find для каждого вхождения слова в строке
        start = 0
        while True:
            pos = file_line.find(word, start)
            if pos == -1:
                break
            # Проверяем границы слова (не часть другого слова)
            before = file_line[pos - 1] if pos > 0 else " "
            after = file_line[pos + len(word)] if pos + len(word) < len(file_line) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                # Это полное слово, не подстрока
                # Определяем kind: Write если это строка объявления, Read иначе
                stripped = file_line.strip()
                is_declaration = (
                    stripped.startswith(f"label {word}")
                    or stripped.startswith(f"screen {word}")
                    or stripped.startswith(f"transform {word}")
                    or stripped.startswith(f"default {word}")
                    or stripped.startswith(f"define {word}")
                )
                kind = lsp.DocumentHighlightKind.Write if is_declaration else lsp.DocumentHighlightKind.Read
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
    """Запускает full project diagnostics сразу после инициализации LSP."""
    server_mod = _get_server_mod()

    try:
        root = ls.workspace.root_path
    except AttributeError:
        root = None

    if root:
        server_mod._current_workspace_root = root
        # Запускаем full scan в фоне (debounced)
        server_mod.schedule_full_diagnostics(ls, "")
