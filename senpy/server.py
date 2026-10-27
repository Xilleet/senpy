from __future__ import annotations

import functools
import os
import re
import threading
import warnings
from urllib.parse import unquote, urlparse

warnings.filterwarnings("ignore", category=SyntaxWarning)

from lsprotocol import types as lsp

try:
    from pygls.lsp.server import LanguageServer
except ImportError:
    from pygls.server import LanguageServer

# ECO-9: читаем версию из единого источника (senpy/__version__.py),
# а не хардкодим здесь. Раньше это была одна из 4 точек правды о версии.
from senpy.__version__ import VERSION_WITH_PREFIX as _SENPY_VERSION
from senpy.analyzer import Diagnostic, SenpyAnalyzer
from senpy.constants import CLAUSE_KEYWORDS
from senpy.renpy_api import get_renpy_api_hover

server = LanguageServer("senpy-lsp", _SENPY_VERSION)


def _uri_to_path(uri: str) -> str:
    parsed = urlparse(uri)
    path = unquote(parsed.path)
    if os.name == "nt" and path.startswith("/"):
        path = path[1:]
    return os.path.normpath(path)


def _path_to_uri(path: str) -> str:
    from pathlib import Path

    return Path(os.path.abspath(path)).as_uri()


def _normalize_path(path: str) -> str:
    """P0-6: единая нормализация путей для ключей _latest_diagnostics_by_path.

    Раньше в разных местах использовались разные нормализации:
    - os.path.normcase(os.path.abspath(...)) — в run_full_project_diagnostics (L127),
      run_single_file_diagnostics (L155), did_save (L219), document_symbols (L673)
    - os.path.normcase(_uri_to_path(uri)) без abspath — в code_action (L237)

    Из-за этого на относительных путях lookup в _latest_diagnostics_by_path
    не находил diagnostics, и срабатывал небезопасный basename-fallback,
    который в multi-module проектах мог выбрать QuickFix из неправильного
    файла (например, game/script.rpy и mods/script.rpy коллайдили).

    Теперь все 4 места используют _normalize_path — единый контракт.
    """
    return os.path.normcase(os.path.abspath(path))


def _get_workspace_root(ls: LanguageServer, fallback_file_path: str) -> str:
    if ls.workspace.root_path:
        return ls.workspace.root_path
    return os.path.dirname(fallback_file_path)


_analysis_lock = threading.Lock()
_previously_diagnosed_uris: set[str] = set()
_latest_diagnostics_by_path: dict[str, list[tuple[Diagnostic, lsp.Diagnostic]]] = {}
_change_timer: threading.Timer | None = None
_full_timer: threading.Timer | None = None
_active_analyzer: SenpyAnalyzer | None = None
_current_workspace_root: str | None = None
_is_initialized: bool = False

SEVERITY_MAP = {
    "ERROR": lsp.DiagnosticSeverity.Error,
    "WARNING": lsp.DiagnosticSeverity.Warning,
    "HINT": lsp.DiagnosticSeverity.Hint,
    "INFO": lsp.DiagnosticSeverity.Information,
}


def _create_lsp_diagnostic(diag: Diagnostic) -> lsp.Diagnostic:
    line_idx = max(0, diag.line_number - 1)
    if diag.end_col > diag.col:
        start_char, end_char = diag.col, diag.end_col
    else:
        raw_text = diag.line_content
        indent = len(raw_text) - len(raw_text.lstrip())
        start_char = indent
        end_char = max(indent + 1, len(raw_text.rstrip()))

    return lsp.Diagnostic(
        range=lsp.Range(
            start=lsp.Position(line=line_idx, character=start_char),
            end=lsp.Position(line=line_idx, character=end_char),
        ),
        message=f"[{diag.code}] {diag.message}",
        severity=SEVERITY_MAP.get(diag.severity, lsp.DiagnosticSeverity.Warning),
        source="senpy",
        code=diag.code,
        code_description=lsp.CodeDescription(
            href=f"https://github.com/Xilleet/senpy/blob/main/RULES.md#{diag.code.lower()}"
        ),
    )


def _with_analysis_lock(func):
    """Читающие обработчики обязаны ждать _analysis_lock.

    Писатели (run_full_project_diagnostics / run_single_file_diagnostics)
    мутируют реестры _active_analyzer только под локом; без него читатели
    ловят RuntimeError: dictionary changed size during iteration и видят
    половинные снапшоты. Сигнатура wrapper — строго (ls, params): pygls
    инспектирует первый параметр (wrap_with_server) и решает, передавать ли
    серверный инстанс первым аргументом.
    """

    @functools.wraps(func)
    def wrapper(ls, params):
        with _analysis_lock:
            return func(ls, params)

    return wrapper


def run_full_project_diagnostics(ls: LanguageServer, trigger_uri: str):
    """Полное сканирование проекта в одном потоке с блокировкой от параллельных запусков."""
    global \
        _previously_diagnosed_uris, \
        _latest_diagnostics_by_path, \
        _active_analyzer, \
        _current_workspace_root, \
        _is_initialized

    with _analysis_lock:
        file_path = _uri_to_path(trigger_uri)
        project_root = _get_workspace_root(ls, file_path)

        if _active_analyzer is None or _current_workspace_root != project_root:
            _current_workspace_root = project_root
            _active_analyzer = SenpyAnalyzer(project_root)

        result = _active_analyzer.run(quiet=True)
        _is_initialized = True

        files_diags: dict[str, list[lsp.Diagnostic]] = {}
        new_diagnostics_by_path: dict[str, list[tuple[Diagnostic, lsp.Diagnostic]]] = {}

        for diag in result.diagnostics:
            diag_uri = _path_to_uri(diag.file_path)
            lsp_diag = _create_lsp_diagnostic(diag)
            files_diags.setdefault(diag_uri, []).append(lsp_diag)
            norm_file = _normalize_path(diag.file_path)  # P0-6: единая нормализация
            new_diagnostics_by_path.setdefault(norm_file, []).append((diag, lsp_diag))

        # Атомарно обновляем общий кэш (без .clear())
        _latest_diagnostics_by_path = new_diagnostics_by_path

        current_uris = set(files_diags.keys())
        for uri, diags in files_diags.items():
            ls.text_document_publish_diagnostics(
                lsp.PublishDiagnosticsParams(uri=uri, diagnostics=diags)
            )

        for uri in _previously_diagnosed_uris - current_uris:
            ls.text_document_publish_diagnostics(
                lsp.PublishDiagnosticsParams(uri=uri, diagnostics=[])
            )

        _previously_diagnosed_uris = current_uris


def run_single_file_diagnostics(ls: LanguageServer, uri: str, content: str):
    """Сверхбыстрый анализ одного файла на лету (15 мс)."""
    if _active_analyzer is None or not _is_initialized:
        schedule_full_diagnostics(ls, uri)
        return

    with _analysis_lock:
        file_path = _uri_to_path(uri)
        norm_file = _normalize_path(file_path)  # P0-6: единая нормализация

        _active_analyzer.in_memory_files[norm_file] = content
        diags = _active_analyzer.analyze_file_only(file_path)

        lsp_diags: list[lsp.Diagnostic] = []
        pairs: list[tuple[Diagnostic, lsp.Diagnostic]] = []

        for diag in diags:
            lsp_diag = _create_lsp_diagnostic(diag)
            lsp_diags.append(lsp_diag)
            pairs.append((diag, lsp_diag))

        _latest_diagnostics_by_path[norm_file] = pairs
        ls.text_document_publish_diagnostics(
            lsp.PublishDiagnosticsParams(uri=uri, diagnostics=lsp_diags)
        )


def schedule_full_diagnostics(ls: LanguageServer, uri: str):
    """Дебаунс для полного сканирования (гасит пачку одновременных didOpen)."""
    global _full_timer
    if _full_timer is not None:
        _full_timer.cancel()
    _full_timer = threading.Timer(0.3, run_full_project_diagnostics, args=[ls, uri])
    _full_timer.daemon = True
    _full_timer.start()


def schedule_change_diagnostics(ls: LanguageServer, uri: str):
    """Дебаунс при наборе текста."""
    global _change_timer
    if _change_timer is not None:
        _change_timer.cancel()

    doc = ls.workspace.get_text_document(uri)
    if not doc:
        return

    _change_timer = threading.Timer(0.15, run_single_file_diagnostics, args=[ls, uri, doc.source])
    _change_timer.daemon = True
    _change_timer.start()


@server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: LanguageServer, params: lsp.DidOpenTextDocumentParams):
    if params.text_document.uri.endswith(".rpy"):
        schedule_full_diagnostics(ls, params.text_document.uri)


@server.feature(lsp.WORKSPACE_DID_CHANGE_WATCHED_FILES)
def did_change_watched_files(ls: LanguageServer, params: lsp.DidChangeWatchedFilesParams):
    """Гасит уведомления об изменении файлов от VS Code, предотвращая спам в Output лог."""


@server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
def did_save(ls: LanguageServer, params: lsp.DidSaveTextDocumentParams):
    if params.text_document.uri.endswith(".rpy"):
        schedule_full_diagnostics(ls, params.text_document.uri)


@server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)
def did_close(ls: LanguageServer, params: lsp.DidCloseTextDocumentParams):
    """Очищает файл из in-memory буфера анализатора при закрытии вкладки в редакторе."""
    uri = params.text_document.uri
    if _active_analyzer is not None:
        norm_file = _normalize_path(_uri_to_path(uri))  # P0-6: единая нормализация
        _active_analyzer.in_memory_files.pop(norm_file, None)


@server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: LanguageServer, params: lsp.DidChangeTextDocumentParams):
    if params.text_document.uri.endswith(".rpy"):
        schedule_change_diagnostics(ls, params.text_document.uri)


@server.feature(
    lsp.TEXT_DOCUMENT_CODE_ACTION,
    lsp.CodeActionOptions(code_action_kinds=[lsp.CodeActionKind.QuickFix]),
)
@_with_analysis_lock
def code_action(ls: LanguageServer, params: lsp.CodeActionParams) -> list[lsp.CodeAction]:
    actions: list[lsp.CodeAction] = []
    try:
        uri = params.text_document.uri
        # P0-6: единая нормализация через _normalize_path (с os.path.abspath),
        # как и во всех остальных местах. Раньше тут было os.path.normcase()
        # без abspath, из-за чего lookup промахивался и срабатывал
        # basename-fallback, который в multi-module проектах мог выбрать
        # QuickFix из неправильного файла.
        norm_path = _normalize_path(_uri_to_path(uri))

        diags_for_file = _latest_diagnostics_by_path.get(norm_path)
        # P0-6: basename-fallback УБРАН. Если diagnostics для файла не найдены
        # через точный путь — возвращаем пустой список, как и должно быть.
        # Если lookup промахивается, это баг в нормализации, его надо чинить
        # в _normalize_path, а не обходить небезопасным угадыванием по basename.
        if not diags_for_file:
            return actions

        cursor_start = params.range.start.line
        cursor_end = params.range.end.line
        context_codes = {d.code for d in (params.context.diagnostics or []) if d.code}

        for diag, lsp_diag in diags_for_file:
            diag_line = max(0, diag.line_number - 1)
            is_on_cursor_line = cursor_start <= diag_line <= cursor_end
            is_in_context = diag.code in context_codes

            if not (is_on_cursor_line or is_in_context):
                continue

            if not (diag.fix_title and diag.fix_replacement):
                continue

            fix_start = getattr(diag, "fix_start_col", None)
            fix_end = getattr(diag, "fix_end_col", None)

            if fix_start is not None and fix_end is not None:
                edit_range = lsp.Range(
                    start=lsp.Position(line=diag_line, character=fix_start),
                    end=lsp.Position(line=diag_line, character=fix_end),
                )
            elif diag.code == "RPY301":
                raw = diag.line_content
                q_pos = max(raw.rfind('"'), raw.rfind("'"))
                ins_char = (
                    len(raw[:q_pos].encode("utf-16-le")) // 2
                    if q_pos != -1
                    else lsp_diag.range.end.character
                )
                edit_range = lsp.Range(
                    start=lsp.Position(line=diag_line, character=ins_char),
                    end=lsp.Position(line=diag_line, character=ins_char),
                )
            else:
                edit_range = lsp_diag.range

            action = lsp.CodeAction(
                title=f"Senpy: {diag.fix_title}",
                kind=lsp.CodeActionKind.QuickFix,
                diagnostics=[lsp_diag],
                is_preferred=True,
                edit=lsp.WorkspaceEdit(
                    changes={
                        uri: [
                            lsp.TextEdit(
                                range=edit_range,
                                new_text=diag.fix_replacement,
                            )
                        ]
                    }
                ),
            )
            actions.append(action)

    except (KeyError, IndexError, ValueError, AttributeError) as e:
        ls.show_message_log(f"Error in code_action: {e}")

    return actions


@server.feature(lsp.TEXT_DOCUMENT_COMPLETION)
@_with_analysis_lock
def completions(ls: LanguageServer, params: lsp.CompletionParams) -> lsp.CompletionList:
    """Контекстный автокомплит для меток, спрайтов и экранов."""
    items: list[lsp.CompletionItem] = []
    if _active_analyzer is None or not _is_initialized:
        return lsp.CompletionList(is_incomplete=False, items=items)

    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc:
        return lsp.CompletionList(is_incomplete=False, items=items)

    line = doc.lines[params.position.line]
    prefix = line[: params.position.character].lstrip()

    # 1. Автокомплит меток для jump / call
    if prefix.startswith(("jump ", "call ")):
        for label_name, lbl in sorted(_active_analyzer.labels.items()):
            if label_name.startswith("_"):
                continue
            items.append(
                lsp.CompletionItem(
                    label=label_name,
                    kind=lsp.CompletionItemKind.Reference,
                    detail=f"Label ({os.path.basename(lbl.file_path)}:{lbl.line_number})",
                )
            )

    # 2. Автокомплит экранов для show screen / call screen / use
    elif prefix.startswith(("show screen ", "call screen ", "use ")):
        for screen_name, scr in sorted(_active_analyzer.screens.items()):
            items.append(
                lsp.CompletionItem(
                    label=screen_name,
                    kind=lsp.CompletionItemKind.Interface,
                    detail=f"Screen ({os.path.basename(scr.file_path)}:{scr.line_number})",
                )
            )

    # 3. Автокомплит спрайтов, атрибутов и трансформаций для show / scene
    elif prefix.startswith(("show ", "scene ")):
        if " at " in prefix or prefix.endswith(" at"):
            standard_positions = [
                "center",
                "truecenter",
                "left",
                "right",
                "top",
                "topleft",
                "topright",
                "offscreenleft",
                "offscreenright",
                "reset",
                "default",
            ]
            for pos in standard_positions:
                items.append(
                    lsp.CompletionItem(
                        label=pos,
                        kind=lsp.CompletionItemKind.EnumMember,
                        detail="Position (Built-in)",
                    )
                )
            for trans_name, trans_sym in sorted(_active_analyzer.transforms.items()):
                items.append(
                    lsp.CompletionItem(
                        label=trans_name,
                        kind=lsp.CompletionItemKind.Function,
                        detail=f"Transform ({os.path.basename(trans_sym.file_path)}:{trans_sym.line_number})",
                    )
                )
        else:
            tokens = prefix.split()
            if len(tokens) == 1 or (len(tokens) == 2 and not prefix.endswith(" ")):
                all_tags = {img.split()[0] for img in _active_analyzer.images}
                for tag in sorted(all_tags):
                    items.append(
                        lsp.CompletionItem(
                            label=tag,
                            kind=lsp.CompletionItemKind.Class,
                            detail="Sprite Tag",
                        )
                    )
            elif len(tokens) >= 2:
                base_tag = tokens[1]
                all_valid = _active_analyzer.valid_images.union(_active_analyzer.images.keys())
                attrs = _active_analyzer._get_tag_known_attributes(base_tag, all_valid)
                for attr in sorted(attrs):
                    items.append(
                        lsp.CompletionItem(
                            label=attr,
                            kind=lsp.CompletionItemKind.EnumMember,
                            detail=f"Attribute for '{base_tag}'",
                        )
                    )

    return lsp.CompletionList(is_incomplete=False, items=items)


@server.feature(lsp.TEXT_DOCUMENT_DEFINITION)
@_with_analysis_lock
def definition(ls: LanguageServer, params: lsp.DefinitionParams) -> lsp.Location | None:
    """Нативный переход по F12 к меткам, экранам, переменным, спрайтам и файлам ассетов."""
    if _active_analyzer is None or not _is_initialized:
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

            for rel_path, full_path in _active_analyzer.media_disk_files.items():
                clean_rel = rel_path.removeprefix("game/")
                if (
                    rel_path == norm_q
                    or clean_rel == norm_q
                    or os.path.basename(rel_path) == base_q
                ):
                    return lsp.Location(
                        uri=_path_to_uri(full_path),
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
                    if candidate in _active_analyzer.images:
                        img = _active_analyzer.images[candidate]
                        return lsp.Location(
                            uri=_path_to_uri(img.file_path),
                            range=lsp.Range(
                                start=lsp.Position(line=max(0, img.line_number - 1), character=0),
                                end=lsp.Position(
                                    line=max(0, img.line_number - 1), character=len(candidate)
                                ),
                            ),
                        )

                for candidate in (full_tag, base_tag):
                    cand_norm = candidate.lower()
                    for rel_path, full_path in _active_analyzer.media_disk_files.items():
                        clean_rel = rel_path.removeprefix("game/")
                        clean_no_ext = os.path.splitext(clean_rel)[0]
                        tokenized = (
                            clean_no_ext.removeprefix("images/").replace("/", " ").replace("_", " ")
                        )
                        if tokenized == cand_norm or os.path.basename(clean_no_ext) == cand_norm:
                            return lsp.Location(
                                uri=_path_to_uri(full_path),
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
    if word in _active_analyzer.labels:
        lbl = _active_analyzer.labels[word]
        return lsp.Location(
            uri=_path_to_uri(lbl.file_path),
            range=lsp.Range(
                start=lsp.Position(line=max(0, lbl.line_number - 1), character=0),
                end=lsp.Position(line=max(0, lbl.line_number - 1), character=len(word)),
            ),
        )

    # 3.2. Экран (screen)
    if word in _active_analyzer.screens:
        scr = _active_analyzer.screens[word]
        return lsp.Location(
            uri=_path_to_uri(scr.file_path),
            range=lsp.Range(
                start=lsp.Position(line=max(0, scr.line_number - 1), character=0),
                end=lsp.Position(line=max(0, scr.line_number - 1), character=len(word)),
            ),
        )

    # 3.3. Переменная или константа
    target_var = word if word in _active_analyzer.variables else word.split(".")[-1]
    if target_var in _active_analyzer.variables:
        var = _active_analyzer.variables[target_var]
        return lsp.Location(
            uri=_path_to_uri(var.file_path),
            range=lsp.Range(
                start=lsp.Position(line=max(0, var.line_number - 1), character=0),
                end=lsp.Position(line=max(0, var.line_number - 1), character=len(target_var)),
            ),
        )

    # 3.4. Имя изображения (image) вне строк show/scene
    if word in _active_analyzer.images:
        img = _active_analyzer.images[word]
        return lsp.Location(
            uri=_path_to_uri(img.file_path),
            range=lsp.Range(
                start=lsp.Position(line=max(0, img.line_number - 1), character=0),
                end=lsp.Position(line=max(0, img.line_number - 1), character=len(word)),
            ),
        )

    # 3.5. ATL трансформация (transform)
    if word in _active_analyzer.transforms:
        trans = _active_analyzer.transforms[word]
        return lsp.Location(
            uri=_path_to_uri(trans.file_path),
            range=lsp.Range(
                start=lsp.Position(line=max(0, trans.line_number - 1), character=0),
                end=lsp.Position(line=max(0, trans.line_number - 1), character=len(word)),
            ),
        )

    return None


@server.feature(lsp.TEXT_DOCUMENT_REFERENCES)
@_with_analysis_lock
def references(ls: LanguageServer, params: lsp.ReferenceParams) -> list[lsp.Location] | None:
    """Find References: все статические jump/call-ссылки на метку под курсором."""
    if _active_analyzer is None or not _is_initialized:
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
    if word in _active_analyzer.labels:
        if params.context.include_declaration:
            lbl = _active_analyzer.labels[word]
            locations.append(
                lsp.Location(
                    uri=_path_to_uri(lbl.file_path),
                    range=lsp.Range(
                        start=lsp.Position(line=max(0, lbl.line_number - 1), character=0),
                        end=lsp.Position(line=max(0, lbl.line_number - 1), character=len(word)),
                    ),
                )
            )
        for ref_path, ref_line in _active_analyzer.jump_sources.get(word, []):
            locations.append(
                lsp.Location(
                    uri=_path_to_uri(ref_path),
                    range=lsp.Range(
                        start=lsp.Position(line=max(0, ref_line - 1), character=0),
                        end=lsp.Position(line=max(0, ref_line - 1), character=len(word)),
                    ),
                )
            )
        return locations

    # экраны, переменные, спрайты, трансформы — следующая итерация:
    # для них ещё нет обратного индекса с координатами.
    return None


@server.feature(lsp.TEXT_DOCUMENT_HOVER)
@_with_analysis_lock
def hover(ls: LanguageServer, params: lsp.HoverParams) -> lsp.Hover | None:
    """Семантические подсказки при наведении курсора мыши на переменные, метки и экраны."""
    if _active_analyzer is None or not _is_initialized:
        return None

    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc or not doc.lines:
        return None

    # P0-5: guard от IndexError при out-of-range line. Аналогичный guard есть
    # в definition() (server.py:394) и references() (server.py:539), но в hover
    # его не было. Это приводило к падению сервера при hover в первые миллисекунды
    # после did_change, когда doc.lines ещё не обновился, либо при невалидном
    # position от клиента.
    line_idx = params.position.line
    if line_idx >= len(doc.lines):
        return None

    line = doc.lines[line_idx]
    col = params.position.character

    word = None
    for m in re.finditer(r"[^\W\d][\w\.]*", line):
        if m.start() <= col <= m.end():
            word = m.group(0)
            break

    if not word:
        return None

    api_content = get_renpy_api_hover(word)
    if api_content:
        return lsp.Hover(
            contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=api_content)
        )

    target_var = word if word in _active_analyzer.variables else word.split(".")[-1]
    if target_var in _active_analyzer.variables:
        var = _active_analyzer.variables[target_var]
        fname = os.path.basename(var.file_path)
        kind = "Constant (`define`)" if var.is_constant else "Variable (`default`)"

        content = (
            f"**Ren'Py {kind}** — `{target_var}`\n\n"
            f"*Declared at `{fname}:{var.line_number}`*\n"
            f"```renpy\n{var.code_line}\n```"
        )
        return lsp.Hover(contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=content))

    if word in _active_analyzer.labels:
        lbl = _active_analyzer.labels[word]
        fname = os.path.basename(lbl.file_path)

        info_lines = [f"**Ren'Py Label** — `{word}`\n\n*Declared at `{fname}:{lbl.line_number}`*"]
        info_lines.append(f"```renpy\n{lbl.code_line}\n```")

        status = []
        if lbl.has_return:
            status.append("✔ Has return")
        if lbl.outgoing_jumps:
            status.append(
                f"➔ Jumps to: {', '.join(f'`{j}`' for j in sorted(lbl.outgoing_jumps)[:4])}"
            )
        if status:
            info_lines.append("\n" + " • ".join(status))

        return lsp.Hover(
            contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value="\n".join(info_lines))
        )

    if word in _active_analyzer.screens:
        scr = _active_analyzer.screens[word]
        fname = os.path.basename(scr.file_path)
        content = f"**Ren'Py Screen** — `{word}`\n\n*Declared at `{fname}:{scr.line_number}`*"
        return lsp.Hover(contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=content))

    return None


@server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
@_with_analysis_lock
def document_symbols(
    ls: LanguageServer, params: lsp.DocumentSymbolParams
) -> list[lsp.DocumentSymbol]:
    """Генерирует нативное дерево символов для Outline (Структура), Breadcrumbs и Ctrl+Shift+O."""
    symbols: list[lsp.DocumentSymbol] = []
    if _active_analyzer is None:
        return symbols

    uri = params.text_document.uri
    file_path = _uri_to_path(uri)
    norm_path = _normalize_path(file_path)  # P0-6: единая нормализация

    scope = _active_analyzer.file_scopes.get(norm_path)
    if not scope:
        _active_analyzer._collect_symbols(file_path)
        scope = _active_analyzer.file_scopes.get(norm_path)

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


def start_lsp():
    server.start_io()
