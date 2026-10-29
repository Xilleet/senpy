from __future__ import annotations

import functools
import os
import threading
import warnings
from urllib.parse import unquote, urlparse

from lsprotocol import types as lsp

from senpy.__version__ import VERSION_WITH_PREFIX as _SENPY_VERSION
from senpy.core.analyzer import Diagnostic, SenpyAnalyzer

warnings.filterwarnings("ignore", category=SyntaxWarning)

try:
    from pygls.lsp.server import LanguageServer
except ImportError:
    from pygls.server import LanguageServer

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


class _RWLock:
    """Reader-writer lock с preference писателям.

    Введено в 0.6.0-12 (P1'-9). Раньше все handler'ы брали эксклюзивный
    threading.Lock — из-за этого параллельные read-only вызовы (definition,
    hover, completions) сериализовались. RWLock позволяет нескольким
    reader'ам работать параллельно, write-lock эксклюзивен.

    Preference писателям: если есть ожидающий writer, новые reader'ы ждут.
    Это предотвращает starvation writer'ов при постоянном потоке reader'ов
    (что типично для LSP — клиент шлёт hover/completions постоянно).

    Реализация через Condition + 2 счётчика. Без внешних зависимостей.
    """

    def __init__(self):
        self._cond = threading.Condition()
        self._readers = 0
        self._writers_waiting = 0
        self._writer_active = False

    def acquire_read(self) -> None:
        with self._cond:
            # Ждём, пока активен writer ИЛИ есть ожидающий writer (preference)
            while self._writer_active or self._writers_waiting > 0:
                self._cond.wait()
            self._readers += 1

    def release_read(self) -> None:
        with self._cond:
            self._readers -= 1
            if self._readers == 0:
                self._cond.notify_all()

    def acquire_write(self) -> None:
        with self._cond:
            self._writers_waiting += 1
            try:
                while self._writer_active or self._readers > 0:
                    self._cond.wait()
                self._writer_active = True
            finally:
                self._writers_waiting -= 1

    def release_write(self) -> None:
        with self._cond:
            self._writer_active = False
            self._cond.notify_all()

    # Context managers для удобства
    def read_lock(self):
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            self.acquire_read()
            try:
                yield
            finally:
                self.release_read()

        return _ctx()

    def write_lock(self):
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            self.acquire_write()
            try:
                yield
            finally:
                self.release_write()

        return _ctx()


class SenpyLSPServer:
    """Контейнер для LSP-серверного state.

    Введено в 0.6.0-9 (Фаза 5). Пока что содержит только stateful методы —
    module-level globals (_active_analyzer, _is_initialized, ...) остаются
    для back-compat с тестами и handlers. В 0.7.0 module-level state будет
    убран, и все handler'ы будут обращаться к singleton _lsp_server.

    P1'-7: 9 module globals → class fields (постепенный перенос)
    P1'-8: per-URI debounce dict[str, Timer] (в 0.6.0-11) ✅
    P1'-9: reader-writer lock для analysis_lock (в 0.6.0-12) ✅
    """

    def __init__(self):
        # P1'-8: per-URI debounce timers.
        self.change_timers: dict[str, threading.Timer] = {}
        # P1'-9: reader-writer lock для analysis state.
        # Заменяет module-level _analysis_lock в новой архитектуре.
        # Module-level _analysis_lock остаётся для back-compat (см. ниже).
        self.rw_lock = _RWLock()


# Singleton-инстанс для будущего использования.
_lsp_server = SenpyLSPServer()


_analysis_lock = threading.Lock()
_previously_diagnosed_uris: set[str] = set()
_latest_diagnostics_by_path: dict[str, list[tuple[Diagnostic, lsp.Diagnostic]]] = {}
_change_timer: threading.Timer | None = None
_full_timer: threading.Timer | None = None
_active_analyzer: SenpyAnalyzer | None = None
_current_workspace_root: str | None = None
_is_initialized: bool = False

# UX-EXT-5: snapshot labels/screens/transforms/images для autocomplete/rename/hover.
# После run() делаем shallow copy этих dict'ов, чтобы analyze_file_only (вызывается
# при did_change) не выкидывал labels из других файлов из _active_analyzer.labels.
# Без snapshot'а autocomplete показывает только labels текущего файла —
# баг "jump в day1a.rpy не предлагает labels из day10a.rpy".
_symbol_snapshot: dict[str, dict] = {
    "labels": {},
    "screens": {},
    "transforms": {},
    "variables": {},
    "images": set(),
    "jump_sources": {},
}


def _refresh_symbol_snapshot() -> None:
    """Обновляет snapshot labels/screens/transforms/... из _active_analyzer.

    Вызывается после каждого run() (full project scan). Snapshot используется
    autocomplete/rename/prepare_rename/hover, чтобы они видели ВСЕ символы
    проекта, даже если analyze_file_only очистил _active_analyzer.labels.
    """
    if _active_analyzer is None:
        return
    _symbol_snapshot["labels"] = dict(_active_analyzer.labels)
    _symbol_snapshot["screens"] = dict(_active_analyzer.screens)
    _symbol_snapshot["transforms"] = dict(_active_analyzer.transforms)
    _symbol_snapshot["variables"] = dict(_active_analyzer.variables)
    _symbol_snapshot["images"] = set(_active_analyzer.images)
    _symbol_snapshot["jump_sources"] = {
        k: list(v) for k, v in _active_analyzer.jump_sources.items()
    }

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

    P1'-9 (0.6.0-12): используем reader-writer lock. Handler'ы — это
    read-only операции (они читают _active_analyzer.labels, _symbol_snapshot,
    и т.д.). Поэтому берём read lock — несколько handler'ов могут работать
    параллельно. Писатели (run_full_project_diagnostics) берут write lock
    эксклюзивно.

    Module-level _analysis_lock остаётся как запасной — берём его тоже,
    для back-compat со старыми тестами, которые могут проверять состояние
    lock'а напрямую. В 0.7.0 будет убран.
    """

    @functools.wraps(func)
    def wrapper(ls, params):
        # P1'-9: берём read lock + старый эксклюзивный lock для back-compat
        _lsp_server.rw_lock.acquire_read()
        try:
            with _analysis_lock:
                return func(ls, params)
        finally:
            _lsp_server.rw_lock.release_read()

    return wrapper


def run_full_project_diagnostics(ls: LanguageServer, trigger_uri: str):
    """Полное сканирование проекта в одном потоке с блокировкой от параллельных запусков.

    P1'-9 (0.6.0-12): берёт write lock — эксклюзивный доступ к state.
    Пока работает writer, ни один reader (handler) не запустится.
    """
    global \
        _previously_diagnosed_uris, \
        _latest_diagnostics_by_path, \
        _active_analyzer, \
        _current_workspace_root, \
        _is_initialized

    _lsp_server.rw_lock.acquire_write()
    try:
        with _analysis_lock:
            file_path = _uri_to_path(trigger_uri)
            project_root = _get_workspace_root(ls, file_path)

            if _active_analyzer is None or _current_workspace_root != project_root:
                _current_workspace_root = project_root
                _active_analyzer = SenpyAnalyzer(project_root)

            result = _active_analyzer.run(quiet=True)
            _is_initialized = True
            # UX-EXT-5: snapshot символов для autocomplete/rename/hover.
            # Должен быть ПОСЛЕ run(), но ДО проверки diagnostics.
            _refresh_symbol_snapshot()

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
    finally:
        _lsp_server.rw_lock.release_write()


def run_single_file_diagnostics(ls: LanguageServer, uri: str, content: str):
    """Сверхбыстрый анализ одного файла на лету (15 мс).

    P1'-9 (0.6.0-12): берёт write lock — мутирует _active_analyzer.in_memory_files
    и _latest_diagnostics_by_path.
    """
    if _active_analyzer is None or not _is_initialized:
        schedule_full_diagnostics(ls, uri)
        return

    file_path = _uri_to_path(uri)

    # Guard: orphan Timer из ранних LSP-тестов может срабатывать уже после
    # завершения теста, с устаревшим _active_analyzer (project_path на другом
    # диске, чем file_path). В этом случае os.path.relpath падает с
    # ValueError. Перенаправляем на full scan — он пересоздаст analyzer.
    try:
        os.path.relpath(file_path, _active_analyzer.project_path)
    except ValueError:
        schedule_full_diagnostics(ls, uri)
        return

    _lsp_server.rw_lock.acquire_write()
    try:
        with _analysis_lock:
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
    finally:
        _lsp_server.rw_lock.release_write()


def schedule_full_diagnostics(ls: LanguageServer, uri: str):
    """Дебаунс для полного сканирования (гасит пачку одновременных didOpen)."""
    global _full_timer
    if _full_timer is not None:
        _full_timer.cancel()
    _full_timer = threading.Timer(0.3, run_full_project_diagnostics, args=[ls, uri])
    _full_timer.daemon = True
    _full_timer.start()


def schedule_change_diagnostics(ls: LanguageServer, uri: str):
    """Дебаунс при наборе текста.

    P1'-8 (0.6.0-11): per-URI debounce. Раньше был один общий _change_timer
    на все URI — при редактировании 2+ файлов одновременно таймеры
    конфликтовали (последний редактируемый файл отменял pending analysis
    других файлов). Теперь каждый URI имеет свой timer в _lsp_server.change_timers.

    _change_timer (module-level) оставлен для back-compat с тестами, которые
    проверяют cancel-логику. В 0.7.0 будет убран.
    """
    global _change_timer

    # P1'-8: cancel existing timer for THIS uri only
    existing = _lsp_server.change_timers.get(uri)
    if existing is not None:
        existing.cancel()

    doc = ls.workspace.get_text_document(uri)
    if not doc:
        # Если документ не найден — убираем pending timer для этого URI
        _lsp_server.change_timers.pop(uri, None)
        # Back-compat: сбрасываем и module-level _change_timer (если он был для этого URI)
        if _change_timer is not None:
            _change_timer.cancel()
            _change_timer = None
        return

    new_timer = threading.Timer(0.15, run_single_file_diagnostics, args=[ls, uri, doc.source])
    new_timer.daemon = True
    _lsp_server.change_timers[uri] = new_timer
    # Back-compat: дублируем в module-level _change_timer для тестов, проверяющих cancel
    _change_timer = new_timer
    new_timer.start()


@server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: LanguageServer, params: lsp.DidOpenTextDocumentParams):
    """0.6.0-3: делегирует в handlers.text_document."""
    from senpy.lsp.handlers.text_document import did_open as _impl
    _impl(ls, params)


@server.feature(lsp.WORKSPACE_DID_CHANGE_WATCHED_FILES)
def did_change_watched_files(ls: LanguageServer, params: lsp.DidChangeWatchedFilesParams):
    """0.6.0-3: делегирует в handlers.text_document."""
    from senpy.lsp.handlers.text_document import did_change_watched_files as _impl
    _impl(ls, params)


@server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
def did_save(ls: LanguageServer, params: lsp.DidSaveTextDocumentParams):
    """0.6.0-3: делегирует в handlers.text_document."""
    from senpy.lsp.handlers.text_document import did_save as _impl
    _impl(ls, params)


@server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)
def did_close(ls: LanguageServer, params: lsp.DidCloseTextDocumentParams):
    """0.6.0-3: делегирует в handlers.text_document."""
    from senpy.lsp.handlers.text_document import did_close as _impl
    _impl(ls, params)


@server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: LanguageServer, params: lsp.DidChangeTextDocumentParams):
    """0.6.0-3: делегирует в handlers.text_document."""
    from senpy.lsp.handlers.text_document import did_change as _impl
    _impl(ls, params)


@server.feature(
    lsp.TEXT_DOCUMENT_CODE_ACTION,
    lsp.CodeActionOptions(code_action_kinds=[lsp.CodeActionKind.QuickFix]),
)
@_with_analysis_lock
def code_action(ls: LanguageServer, params: lsp.CodeActionParams) -> list[lsp.CodeAction]:
    """0.6.0: делегирует в handlers.diagnostics."""
    from senpy.lsp.handlers.diagnostics import code_action as _impl
    return _impl(ls, params)


@server.feature(lsp.TEXT_DOCUMENT_COMPLETION)
@_with_analysis_lock
def completions(ls: LanguageServer, params: lsp.CompletionParams) -> lsp.CompletionList:
    """0.6.0: делегирует в handlers.completion."""
    from senpy.lsp.handlers.completion import completions as _impl
    return _impl(ls, params)


@server.feature(lsp.TEXT_DOCUMENT_DEFINITION)
@_with_analysis_lock
def definition(ls: LanguageServer, params: lsp.DefinitionParams) -> lsp.Location | None:
    """0.6.0-4: делегирует в handlers.navigation."""
    from senpy.lsp.handlers.navigation import definition as _impl
    return _impl(ls, params)


@server.feature(lsp.TEXT_DOCUMENT_REFERENCES)
@_with_analysis_lock
def references(ls: LanguageServer, params: lsp.ReferenceParams) -> list[lsp.Location] | None:
    """0.6.0-4: делегирует в handlers.navigation."""
    from senpy.lsp.handlers.navigation import references as _impl
    return _impl(ls, params)


@server.feature(lsp.TEXT_DOCUMENT_HOVER)
@_with_analysis_lock
def hover(ls: LanguageServer, params: lsp.HoverParams) -> lsp.Hover | None:
    """0.6.0: делегирует в handlers.hover."""
    from senpy.lsp.handlers.hover import hover as _impl
    return _impl(ls, params)


@server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
@_with_analysis_lock
def document_symbols(
    ls: LanguageServer, params: lsp.DocumentSymbolParams
) -> list[lsp.DocumentSymbol]:
    """0.6.0-4: делегирует в handlers.navigation."""
    from senpy.lsp.handlers.navigation import document_symbols as _impl
    return _impl(ls, params)


# =============================================================================
# UX-1: textDocument/foldingRange — сворачивание label/screen/menu/init блоков
# =============================================================================
# Позволяет в VS Code сворачивать (fold) блоки кода:
# - label X: ... (до следующего label или конца файла)
# - screen X(): ...
# - menu: ...
# - init python: ...
# - transform X: ...
# - python: ...
#
# Алгоритм: проходим по строкам, отслеживаем отступы. При встрече scope-opening
# ключевого слова — открываем folding range. Закрываем при уменьшении отступа
# до того же уровня или ниже.
@server.feature(lsp.TEXT_DOCUMENT_FOLDING_RANGE)
@_with_analysis_lock
def folding_range(ls: LanguageServer, params: lsp.FoldingRangeParams) -> list[lsp.FoldingRange]:
    """0.6.0: делегирует в handlers.workspace."""
    from senpy.lsp.handlers.workspace import folding_range as _impl
    return _impl(ls, params)


# =============================================================================
# UX-EXT-3: textDocument/prepareRename — preview перед F2 rename
# =============================================================================
# VS Code вызывает prepareRename перед самим rename, чтобы:
# 1. Проверить, что под курсором валидный символ для переименования
# 2. Показать пользователю Range слова, которое будет переименовано
# 3. Разрешить отмену до применения изменений (preview mode)
#
# Если вернуть None — VS Code покажет "The element can't be renamed" и
# не даст нажать F2.
#
# Алгоритм: находим слово под курсором. Если это label (есть в
# _active_analyzer.labels) — возвращаем его Range. Иначе None.
@server.feature(lsp.TEXT_DOCUMENT_PREPARE_RENAME)
@_with_analysis_lock
def prepare_rename(
    ls: LanguageServer, params: lsp.PrepareRenameParams
) -> lsp.Range | lsp.PrepareRenameResult | None:
    """0.6.0-4: делегирует в handlers.navigation."""
    from senpy.lsp.handlers.navigation import prepare_rename as _impl
    return _impl(ls, params)


# =============================================================================
# UX-2: textDocument/rename — переименование меток
# =============================================================================
# Переименовывает label во всех местах:
# - Объявление (label X:)
# - Все jump X
# - Все call X
#
# Использует jump_sources обратный индекс из analyzer.
# Возвращает WorkspaceEdit с изменениями для всех файлов проекта.
#
# UX-EXT-3: prepare_provider=True — VS Code вызывает prepareRename перед F2,
# чтобы показать preview и разрешить отмену до применения.
@server.feature(
    lsp.TEXT_DOCUMENT_RENAME,
    lsp.RenameOptions(prepare_provider=True),
)
@_with_analysis_lock
def rename(ls: LanguageServer, params: lsp.RenameParams) -> lsp.WorkspaceEdit | None:
    """0.6.0-4: делегирует в handlers.navigation."""
    from senpy.lsp.handlers.navigation import rename as _impl
    return _impl(ls, params)


# =============================================================================
# UX-3: workspace/symbol — глобальный поиск символов (Ctrl+T)
# =============================================================================
# Возвращает все label'ы, screen'ы, transform'ы в проекте.
# VS Code: Ctrl+T → вводишь имя → переход к определению.
#
# Поддерживает фильтрацию по query (case-insensitive substring match).
# Если query пустой — возвращает все символы.
@server.feature(lsp.WORKSPACE_SYMBOL)
@_with_analysis_lock
def workspace_symbol(
    ls: LanguageServer, params: lsp.WorkspaceSymbolParams
) -> list[lsp.WorkspaceSymbol]:
    """0.6.0: делегирует в handlers.workspace."""
    from senpy.lsp.handlers.workspace import workspace_symbol as _impl
    return _impl(ls, params)


# =============================================================================
# UX-12: initialized — запуск full project scan сразу после инициализации
# =============================================================================
# Без этого handler'а hover/completion не работают первые 300ms после открытия
# файла (до первого did_save). initialized запускает scan немедленно.
@server.feature(lsp.INITIALIZED)
def initialized(ls: LanguageServer, params: lsp.InitializedParams) -> None:
    """0.6.0: делегирует в handlers.workspace."""
    from senpy.lsp.handlers.workspace import initialized as _impl
    return _impl(ls, params)


# =============================================================================
# UX-5: documentHighlight — подсветка всех упоминаний слова в файле
# =============================================================================
# VS Code: курсор на переменной/метке → все её упоминания в файле подсвечиваются.
# Ищет слово в: labels, screens, transforms, variables (declared_symbols).
# Возвращает DocumentHighlight с kind: Write (объявление) / Read (использование).
@server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT)
@_with_analysis_lock
def document_highlight(
    ls: LanguageServer, params: lsp.DocumentHighlightParams
) -> list[lsp.DocumentHighlight]:
    """0.6.0: делегирует в handlers.workspace."""
    from senpy.lsp.handlers.workspace import document_highlight as _impl
    return _impl(ls, params)


def start_lsp():
    server.start_io()
