"""LSP handlers: navigation (definition, references, rename, document_symbols).

Вынесено из senpy/lsp/server.py в 0.6.0-4 (Фаза 5).

Handler'ы:
  - definition        ← TEXT_DOCUMENT_DEFINITION (F12)
  - references        ← TEXT_DOCUMENT_REFERENCES (Shift+F12)
  - document_symbols  ← TEXT_DOCUMENT_DOCUMENT_SYMBOL (Ctrl+Shift+O, Breadcrumbs)
  - prepare_rename    ← TEXT_DOCUMENT_PREPARE_RENAME (F2 preview)
  - rename            ← TEXT_DOCUMENT_RENAME (F2 apply)

Все функции принимают (ls, params) и обращаются к shared state через
server_mod._X (lazy import разрывает цикл импортов).
"""
from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    try:
        from pygls.lsp.server import LanguageServer
    except ImportError:
        from pygls.server import LanguageServer

from lsprotocol import types as lsp

from senpy.core.constants import CLAUSE_KEYWORDS


def _get_server_mod():
    """Ленивый доступ к senpy.lsp.server, разрывает цикл импортов.

    Все обращения к shared state (_active_analyzer, _is_initialized, ...)
    идут через server_mod = _get_server_mod() в начале каждой функции.
    """
    from senpy.lsp import server
    return server


def definition(ls: LanguageServer, params: lsp.DefinitionParams) -> lsp.Location | None:
    server_mod = _get_server_mod()
    """Нативный переход по F12 к меткам, экранам, переменным, спрайтам и файлам ассетов."""
    if server_mod._active_analyzer is None or not server_mod._is_initialized:
        return None

    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc or not doc.lines:
        return None

    line_idx = params.position.line
    if line_idx >= len(doc.lines):
        return None

    line = doc.lines[line_idx]
    col = params.position.character
    stripped = line.strip()

    # 1. Проверяем клик внутри кавычек (путь к аудио или графическому файлу на диске)
    for qm in re.finditer(r'("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')', line):
        if qm.start() <= col <= qm.end():
            raw_path = qm.group(0)[1:-1].strip()
            norm_q = raw_path.replace("\\", "/").lower()
            norm_q = re.sub(r"^<[^>]+>\s*", "", norm_q)
            base_q = os.path.basename(norm_q)

            for rel_path, full_path in server_mod._active_analyzer.media_disk_files.items():
                clean_rel = rel_path.removeprefix("game/")
                if (
                    rel_path == norm_q
                    or clean_rel == norm_q
                    or os.path.basename(rel_path) == base_q
                ):
                    return lsp.Location(
                        uri=server_mod._path_to_uri(full_path),
                        range=lsp.Range(start=lsp.Position(0, 0), end=lsp.Position(0, 0)),
                    )

    # 2. Проверяем клик по спрайтам/фонам в строках show, scene, hide
    if stripped.startswith(("show ", "scene ", "hide ")):
        parts = stripped.split()[1:]
        img_tokens = []
        for p in parts:
            clean_p = p.rstrip(":")
            if clean_p in CLAUSE_KEYWORDS:
                break
            img_tokens.append(clean_p)
            if p.endswith(":"):
                break

        if img_tokens:
            full_tag = " ".join(img_tokens)
            base_tag = img_tokens[0]
            tag_start = line.find(base_tag)
            tag_end = tag_start + len(full_tag) if tag_start != -1 else -1

            if tag_start != -1 and tag_start <= col <= tag_end:
                for candidate in (full_tag, base_tag):
                    if candidate in server_mod._active_analyzer.images:
                        img = server_mod._active_analyzer.images[candidate]
                        return lsp.Location(
                            uri=server_mod._path_to_uri(img.file_path),
                            range=lsp.Range(
                                start=lsp.Position(line=max(0, img.line_number - 1), character=0),
                                end=lsp.Position(
                                    line=max(0, img.line_number - 1), character=len(candidate)
                                ),
                            ),
                        )

                for candidate in (full_tag, base_tag):
                    cand_norm = candidate.lower()
                    for rel_path, full_path in server_mod._active_analyzer.media_disk_files.items():
                        clean_rel = rel_path.removeprefix("game/")
                        clean_no_ext = os.path.splitext(clean_rel)[0]
                        tokenized = (
                            clean_no_ext.removeprefix("images/").replace("/", " ").replace("_", " ")
                        )
                        if tokenized == cand_norm or os.path.basename(clean_no_ext) == cand_norm:
                            return lsp.Location(
                                uri=server_mod._path_to_uri(full_path),
                                range=lsp.Range(start=lsp.Position(0, 0), end=lsp.Position(0, 0)),
                            )

    # 3. Извлекаем идентификатор под курсором
    word = None
    for m in re.finditer(r"[^\W\d][\w\.]*", line):
        if m.start() <= col <= m.end():
            word = m.group(0)
            break

    if not word:
        return None

    # 3.1. Метка сюжета (jump/call)
    if word in server_mod._active_analyzer.labels:
        lbl = server_mod._active_analyzer.labels[word]
        return lsp.Location(
            uri=server_mod._path_to_uri(lbl.file_path),
            range=lsp.Range(
                start=lsp.Position(line=max(0, lbl.line_number - 1), character=0),
                end=lsp.Position(line=max(0, lbl.line_number - 1), character=len(word)),
            ),
        )

    # 3.2. Экран (screen)
    if word in server_mod._active_analyzer.screens:
        scr = server_mod._active_analyzer.screens[word]
        return lsp.Location(
            uri=server_mod._path_to_uri(scr.file_path),
            range=lsp.Range(
                start=lsp.Position(line=max(0, scr.line_number - 1), character=0),
                end=lsp.Position(line=max(0, scr.line_number - 1), character=len(word)),
            ),
        )

    # 3.3. Переменная или константа
    target_var = word if word in server_mod._active_analyzer.variables else word.split(".")[-1]
    if target_var in server_mod._active_analyzer.variables:
        var = server_mod._active_analyzer.variables[target_var]
        return lsp.Location(
            uri=server_mod._path_to_uri(var.file_path),
            range=lsp.Range(
                start=lsp.Position(line=max(0, var.line_number - 1), character=0),
                end=lsp.Position(line=max(0, var.line_number - 1), character=len(target_var)),
            ),
        )

    # 3.4. Имя изображения (image) вне строк show/scene
    if word in server_mod._active_analyzer.images:
        img = server_mod._active_analyzer.images[word]
        return lsp.Location(
            uri=server_mod._path_to_uri(img.file_path),
            range=lsp.Range(
                start=lsp.Position(line=max(0, img.line_number - 1), character=0),
                end=lsp.Position(line=max(0, img.line_number - 1), character=len(word)),
            ),
        )

    # 3.5. ATL трансформация (transform)
    if word in server_mod._active_analyzer.transforms:
        trans = server_mod._active_analyzer.transforms[word]
        return lsp.Location(
            uri=server_mod._path_to_uri(trans.file_path),
            range=lsp.Range(
                start=lsp.Position(line=max(0, trans.line_number - 1), character=0),
                end=lsp.Position(line=max(0, trans.line_number - 1), character=len(word)),
            ),
        )

    return None


def rename(ls: LanguageServer, params: lsp.RenameParams) -> lsp.WorkspaceEdit | None:
    server_mod = _get_server_mod()
    """Переименование метки: обновляет объявление + все jump/call ссылки."""
    if server_mod._active_analyzer is None or not server_mod._is_initialized:
        return None

    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc or not doc.lines:
        return None

    line_idx = params.position.line
    if line_idx >= len(doc.lines):
        return None

    line = doc.lines[line_idx]
    col = params.position.character

    # Извлекаем слово под курсором
    word = None
    for m in re.finditer(r"[a-zA-Z_][a-zA-Z0-9_\.]*", line):
        if m.start() <= col <= m.end():
            word = m.group(0)
            break

    if not word:
        return None

    new_name = params.new_name

    # rename для labels, variables, transforms, screens.
    # используем snapshot, не server_mod._active_analyzer.labels —
    # analyze_file_only чистит labels из других файлов.
    if word in server_mod._symbol_snapshot["labels"]:
        # Существующая логика для labels (через jump_sources reverse index)
        return _rename_label(server_mod, word, new_name)
    elif word in server_mod._symbol_snapshot["variables"]:
        return _rename_symbol_via_text_search(server_mod, word, new_name, "variables")
    elif word in server_mod._symbol_snapshot["transforms"]:
        return _rename_symbol_via_text_search(server_mod, word, new_name, "transforms")
    elif word in server_mod._symbol_snapshot["screens"]:
        return _rename_symbol_via_text_search(server_mod, word, new_name, "screens")

    return None


def _rename_label(
    server_mod, word: str, new_name: str
) -> lsp.WorkspaceEdit | None:
    """Rename для label: обновляет объявление + все jump/call ссылки.

    Использует jump_sources reverse index из analyzer'а — точнее, чем
    text search (не ловит false positives в строках/комментариях).
    """
    changes: dict[str, list[lsp.TextEdit]] = {}

    # 1. Объявление (label X:)
    lbl = server_mod._symbol_snapshot["labels"][word]
    lbl_uri = server_mod._path_to_uri(lbl.file_path)
    lbl_line = max(0, lbl.line_number - 1)  # 0-based

    # Читаем строку, чтобы найти точную позицию слова
    try:
        with open(lbl.file_path, encoding="utf-8") as f:
            file_lines = f.readlines()
        if lbl_line < len(file_lines):
            lbl_content = file_lines[lbl_line]
            # Находим позицию слова в строке
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

    # 2. Все jump/call ссылки (из jump_sources)
    # UX-EXT-5: тоже из snapshot, чтобы получить ссылки из всех файлов.
    for ref_path, ref_line in server_mod._symbol_snapshot["jump_sources"].get(word, []):
        ref_uri = server_mod._path_to_uri(ref_path)
        ref_line_0 = max(0, ref_line - 1)  # 0-based

        # Читаем строку, чтобы найти точную позицию слова
        try:
            with open(ref_path, encoding="utf-8") as f:
                ref_lines = f.readlines()
            if ref_line_0 < len(ref_lines):
                ref_content = ref_lines[ref_line_0]
                # Находим позицию слова в строке
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
# helpers: rename для variables/transforms/screens via text search
# =============================================================================

# Regex template для поиска вхождений слова как whole-word (не частью другого имени).
# Границы: не alphanumeric/underscore с обеих сторон.
# Пример: для "player_gold" не должно матчить "player_gold_count" или "my_player_gold".
_WORD_BOUNDARY_TEMPLATE = r"(?<![A-Za-z0-9_])({})(?![A-Za-z0-9_])"


def _find_text_occurrences_in_project(
    server_mod, word: str
) -> list[tuple[str, int, int]]:
    """Ищет все text-вхождения word как whole-word во всех .rpy файлах проекта.

    Возвращает list of (file_path, line_idx_0based, col_utf16).

    Используется для rename/references variables/transforms/screens, у которых
    нет reverse index (в отличие от labels с jump_sources).

    NB: Может ловить false positives в строковых литералах и комментариях
    (например, "$ x = 'player_gold'"). Это компромисс — точный анализ потребовал
    бы AST-обхода по всем .rpy файлам, что медленно. Для rename/references
    текстовый поиск приемлем: пользователь видит все вхождения и может отменить.
    """
    if server_mod._active_analyzer is None:
        return []

    project_path = server_mod._active_analyzer.project_path
    occurrences: list[tuple[str, int, int]] = []
    pattern = re.compile(_WORD_BOUNDARY_TEMPLATE.format(re.escape(word)))

    for root, _, files in os.walk(project_path, followlinks=False):
        # Пропускаем служебные директории
        dirs_skip = [d for d in _get_ignored_dirs() if d in root.split(os.sep)]
        if dirs_skip:
            continue
        for fname in files:
            if not fname.endswith(".rpy"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except OSError:
                continue

            for line_idx, line in enumerate(lines):
                for m in re.finditer(pattern, line):
                    col_utf16 = len(line[: m.start()].encode("utf-16-le")) // 2
                    occurrences.append((fpath, line_idx, col_utf16))

    return occurrences


def _get_ignored_dirs() -> set[str]:
    """Список директорий которые не надо обходить."""
    from senpy.core.constants import IGNORED_DIRS
    return set(IGNORED_DIRS) if IGNORED_DIRS else {".senpy_cache", "tl", "cache"}


def _rename_symbol_via_text_search(
    server_mod, word: str, new_name: str, symbol_kind: str
) -> lsp.WorkspaceEdit | None:
    """Rename variable/transform/screen через text search по всем .rpy файлам.

    LSP-17: для variables/transforms/screens нет reverse index (как jump_sources
    для labels). Используем text search — все whole-word вхождения слова в .rpy
    файлах проекта заменяются на new_name.
    """
    occurrences = _find_text_occurrences_in_project(server_mod, word)
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


def references(ls: LanguageServer, params: lsp.ReferenceParams) -> list[lsp.Location] | None:
    server_mod = _get_server_mod()
    """Find References: все статические jump/call-ссылки на метку под курсором."""
    if server_mod._active_analyzer is None or not server_mod._is_initialized:
        return None

    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc or not doc.lines:
        return None

    line_idx = params.position.line
    if line_idx >= len(doc.lines):
        return None

    line = doc.lines[line_idx]
    col = params.position.character

    # Тот же экстрактор слова, что в definition/hover
    word = None
    for m in re.finditer(r"[a-zA-Z_][a-zA-Z0-9_\.]*", line):
        if m.start() <= col <= m.end():
            word = m.group(0)
            break

    if not word:
        return None

    locations: list[lsp.Location] = []

    # Обратный индекс jump_sources [(файл, строка 1-базная)]
    # строится анализатором для таргетов jump И call, поддерживается
    # дифференциальной чисткой (_differential_purge_file) и переживает
    # перестройку кэша (_rebuild_aggregates).
    if word in server_mod._active_analyzer.labels:
        if params.context.include_declaration:
            lbl = server_mod._active_analyzer.labels[word]
            locations.append(
                lsp.Location(
                    uri=server_mod._path_to_uri(lbl.file_path),
                    range=lsp.Range(
                        start=lsp.Position(line=max(0, lbl.line_number - 1), character=0),
                        end=lsp.Position(line=max(0, lbl.line_number - 1), character=len(word)),
                    ),
                )
            )
        for ref_path, ref_line in server_mod._active_analyzer.jump_sources.get(word, []):
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

    # LSP-18: references для variables/transforms/screens через text search.
    # Для них нет reverse index (как jump_sources для labels), поэтому используем
    # _find_text_occurrences_in_project — grep whole-word по всем .rpy файлам.
    if (
        word in server_mod._symbol_snapshot["variables"]
        or word in server_mod._symbol_snapshot["transforms"]
        or word in server_mod._symbol_snapshot["screens"]
    ):
        return _references_via_text_search(
            server_mod, word, params.context.include_declaration
        )

    return None


def _references_via_text_search(
    server_mod, word: str, include_declaration: bool
) -> list[lsp.Location]:
    """LSP-18 helper: references для variables/transforms/screens.

    Использует _find_text_occurrences_in_project. Если include_declaration=False,
    исключает первую локацию (объявление) — она определяется через snapshot.
    """
    occurrences = _find_text_occurrences_in_project(server_mod, word)
    if not occurrences:
        return []

    # Если не нужно включать объявление — найдём его через snapshot и исключим.
    declaration_loc: tuple[str, int] | None = None  # (file_path, line_idx_0based)
    for kind in ("variables", "transforms", "screens"):
        sym = server_mod._symbol_snapshot[kind].get(word)
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


def document_symbols(
    ls: LanguageServer, params: lsp.DocumentSymbolParams
) -> list[lsp.DocumentSymbol]:
    server_mod = _get_server_mod()
    """Генерирует нативное дерево символов для Outline (Структура), Breadcrumbs и Ctrl+Shift+O."""
    symbols: list[lsp.DocumentSymbol] = []
    if server_mod._active_analyzer is None:
        return symbols

    uri = params.text_document.uri
    file_path = server_mod._uri_to_path(uri)
    norm_path = server_mod._normalize_path(file_path)  # P0-6: единая нормализация

    scope = server_mod._active_analyzer.file_scopes.get(norm_path)
    if not scope:
        server_mod._active_analyzer._collect_symbols(file_path)
        scope = server_mod._active_analyzer.file_scopes.get(norm_path)

    if not scope:
        return symbols

    doc = ls.workspace.get_text_document(uri)
    lines = doc.lines if doc and doc.lines else []
    total_lines = len(lines) if lines else 1000

    raw_entries: list[tuple[int, str, lsp.SymbolKind, str, bool]] = []

    for lbl_name, lbl_sym in scope.labels.items():
        if not lbl_name.startswith("_"):
            raw_entries.append(
                (max(0, lbl_sym.line_number - 1), lbl_name, lsp.SymbolKind.Function, "Label", True)
            )

    for scr_name, scr_sym in scope.screens.items():
        raw_entries.append(
            (max(0, scr_sym.line_number - 1), scr_name, lsp.SymbolKind.Interface, "Screen", True)
        )

    for img_name, img_sym in scope.images.items():
        if img_sym.is_layered:
            raw_entries.append(
                (
                    max(0, img_sym.line_number - 1),
                    img_name,
                    lsp.SymbolKind.Class,
                    "Layered Image",
                    True,
                )
            )
        else:
            raw_entries.append(
                (max(0, img_sym.line_number - 1), img_name, lsp.SymbolKind.Field, "Image", False)
            )

    for trans_name, trans_sym in scope.transforms.items():
        raw_entries.append(
            (
                max(0, trans_sym.line_number - 1),
                trans_name,
                lsp.SymbolKind.Function,
                "Transform",
                True,
            )
        )

    for var_name, var_sym in scope.variables.items():
        if var_name.startswith("_") or var_sym.is_character:
            continue
        kind = lsp.SymbolKind.Constant if var_sym.is_constant else lsp.SymbolKind.Variable
        detail = "Constant (define)" if var_sym.is_constant else "Variable (default)"
        raw_entries.append((max(0, var_sym.line_number - 1), var_name, kind, detail, False))

    raw_entries.sort(key=lambda x: x[0])

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


def prepare_rename(
    ls: LanguageServer, params: lsp.PrepareRenameParams
) -> lsp.Range | lsp.PrepareRenameResult | None:
    server_mod = _get_server_mod()
    """Возвращает Range слова под курсором для preview перед rename."""
    if server_mod._active_analyzer is None or not server_mod._is_initialized:
        return None

    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc or not doc.lines:
        return None

    line_idx = params.position.line
    if line_idx >= len(doc.lines):
        return None

    line = doc.lines[line_idx]
    col = params.position.character

    # Ищем слово под курсором (то же правило, что в rename)
    for m in re.finditer(r"[a-zA-Z_][a-zA-Z0-9_\.]*", line):
        if m.start() <= col <= m.end():
            word = m.group(0)
            # Поддерживаем rename только для label'ов.
            # Для переменных/transform/screen — пока нет (can't be renamed).
            # UX-EXT-5: используем snapshot, не server_mod._active_analyzer.labels,
            # чтобы F2 работал даже после did_change (analyze_file_only).
            if word in server_mod._symbol_snapshot["labels"]:
                # Возвращаем Range слова. pygls/lsprotocol принимает Range
                # или PrepareRenameResult(placeholder=...). Range достаточно.
                # UTF-16 позиции для совместимости с VS Code.
                start_utf16 = len(line[: m.start()].encode("utf-16-le")) // 2
                end_utf16 = start_utf16 + len(word.encode("utf-16-le")) // 2
                return lsp.Range(
                    start=lsp.Position(line=line_idx, character=start_utf16),
                    end=lsp.Position(line=line_idx, character=end_utf16),
                )
            # Слово есть, но не label — можно вернуть None ("can't rename here")
            return None

    # Нет слова под курсором
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
#   - server_mod._symbol_snapshot["labels"] for label lookup
#   - server_mod._symbol_snapshot["jump_sources"] for incoming calls (who jumps to this label)
#   - LabelSymbol.outgoing_jumps for outgoing calls (where this label jumps to)


def prepare_call_hierarchy(
    ls: LanguageServer, params: lsp.CallHierarchyPrepareParams
) -> list[lsp.CallHierarchyItem]:
    """LSP-5: Return CallHierarchyItem for label under cursor.

    Returns empty list if cursor is not on a label declaration or reference.
    """
    server_mod = _get_server_mod()
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

    # Find word under cursor
    word = None
    for m in re.finditer(r"[a-zA-Z_][a-zA-Z0-9_\.]*", line):
        if m.start() <= col <= m.end():
            word = m.group(0)
            break

    if not word:
        return []

    # Check if word is a label (in snapshot, with fallback to analyzer)
    labels = server_mod._symbol_snapshot.get("labels", {})
    if word not in labels and server_mod._active_analyzer is not None:
        labels = server_mod._active_analyzer.labels
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
    """LSP-5: Find all labels that call/jump to the given label.

    Uses jump_sources reverse index from analyzer snapshot.
    """
    server_mod = _get_server_mod()
    if server_mod._active_analyzer is None or not server_mod._is_initialized:
        return []

    target_name = params.item.name
    labels = server_mod._symbol_snapshot.get("labels", {})
    jump_sources = server_mod._symbol_snapshot.get("jump_sources", {})
    # Fallback: if not in snapshot, check analyzer directly
    if not jump_sources and server_mod._active_analyzer is not None:
        jump_sources = server_mod._active_analyzer.jump_sources
    if not labels and server_mod._active_analyzer is not None:
        labels = server_mod._active_analyzer.labels

    incoming: list[lsp.CallHierarchyIncomingCall] = []

    # jump_sources maps: target_label → list of (file_path, line_number)
    for caller_path, caller_line in jump_sources.get(target_name, []):
        # Find the label that contains this call site
        # (label whose line_number <= caller_line and is in the same file)
        caller_label = None
        for name, lbl in labels.items():
            if lbl.file_path == caller_path and lbl.line_number <= caller_line:  # noqa: SIM102
                if caller_label is None or lbl.line_number > caller_label.line_number:
                    caller_label = lbl
                    caller_name = name

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

        incoming.append(lsp.CallHierarchyIncomingCall(
            from_=caller_item,
            from_ranges=[call_range],
        ))

    return incoming


def outgoing_calls(
    ls: LanguageServer, params: lsp.CallHierarchyOutgoingCallsParams
) -> list[lsp.CallHierarchyOutgoingCall]:
    """LSP-5: Find all labels that this label jumps/calls to.

    Uses LabelSymbol.outgoing_jumps from analyzer snapshot.
    """
    server_mod = _get_server_mod()
    if server_mod._active_analyzer is None or not server_mod._is_initialized:
        return []

    source_name = params.item.name
    labels = server_mod._symbol_snapshot.get("labels", {})
    # Fallback: if not in snapshot, check analyzer directly
    if source_name not in labels and server_mod._active_analyzer is not None:
        labels = server_mod._active_analyzer.labels

    if source_name not in labels:
        return []

    source_label = labels[source_name]
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
                end=lsp.Position(line=max(0, target_label.line_number - 1), character=len(target_name)),
            ),
        )

        # fromRanges: where the call happens in the source label
        # We don't track exact line of each jump, so use the label's range
        from_range = lsp.Range(
            start=lsp.Position(line=max(0, source_label.line_number - 1), character=0),
            end=lsp.Position(line=max(0, source_label.line_number - 1), character=80),
        )

        outgoing.append(lsp.CallHierarchyOutgoingCall(
            to=target_item,
            from_ranges=[from_range],
        ))

    return outgoing
