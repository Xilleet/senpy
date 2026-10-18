from __future__ import annotations

import os
import threading
from urllib.parse import unquote, urlparse

from lsprotocol import types as lsp

# Исправление для pygls 2.x:
try:
    from pygls.lsp.server import LanguageServer
except ImportError:
    from pygls.server import LanguageServer

from senpy.analyzer import SenpyAnalyzer

server = LanguageServer("senpy-lsp", "v0.1.0")


def _uri_to_path(uri: str) -> str:
    """Конвертирует file:// URI в нормальный путь файловой системы."""
    parsed = urlparse(uri)
    path = unquote(parsed.path)
    if os.name == "nt" and path.startswith("/"):
        path = path[1:]
    return os.path.normpath(path)


def _path_to_uri(path: str) -> str:
    """Конвертирует путь файловой системы обратно в file:// URI."""
    from pathlib import Path
    return Path(os.path.abspath(path)).as_uri()


def _get_workspace_root(ls: LanguageServer, fallback_file_path: str) -> str:
    """Определяет корень проекта (где искать game/ и остальные .rpy)."""
    if ls.workspace.root_path:
        return ls.workspace.root_path
    return os.path.dirname(fallback_file_path)

# Запоминаем файлы, для которых мы слали ошибки, чтобы очищать их при исправлении
_previously_diagnosed_uris: set[str] = set()

def run_diagnostics(ls: LanguageServer, trigger_uri: str, in_memory: dict[str, str] | None = None):
    global _previously_diagnosed_uris
    file_path = _uri_to_path(trigger_uri)
    project_root = _get_workspace_root(ls, file_path)

    # Передаем буфер памяти в анализатор
    analyzer = SenpyAnalyzer(project_root, in_memory_files=in_memory)
    result = analyzer.run()

    files_diags: dict[str, list[lsp.Diagnostic]] = {}

    severity_map = {
        "ERROR": lsp.DiagnosticSeverity.Error,
        "WARNING": lsp.DiagnosticSeverity.Warning,
        "INFO": lsp.DiagnosticSeverity.Information,
    }

    for diag in result.diagnostics:
        diag_uri = _path_to_uri(diag.file_path)
        line_idx = max(0, diag.line_number - 1)

        # Если точные координаты заданы — берем их
        if diag.end_col > diag.col:
            start_char = diag.col
            end_char = diag.end_col
        else:
            # Умный фоллбэк: отрезаем пробелы отступа, чтобы линия не висела в пустоте
            raw_text = diag.line_content
            indent = len(raw_text) - len(raw_text.lstrip())
            start_char = indent
            end_char = max(indent + 1, len(raw_text.rstrip()))

        lsp_diag = lsp.Diagnostic(
            range=lsp.Range(
                start=lsp.Position(line=line_idx, character=start_char),
                end=lsp.Position(line=line_idx, character=end_char),
            ),
            message=f"[{diag.code}] {diag.message}",
            severity=severity_map.get(diag.severity, lsp.DiagnosticSeverity.Warning),
            source="senpy",
            code=diag.code,
        )

        files_diags.setdefault(diag_uri, []).append(lsp_diag)

    # Публикуем актуальные ошибки
    current_uris = set(files_diags.keys())
    for uri, diags in files_diags.items():
        ls.text_document_publish_diagnostics(
            lsp.PublishDiagnosticsParams(uri=uri, diagnostics=diags)
        )

    # Очищаем файлы, где ошибки были исправлены (посылаем пустой массив [])
    cleared_uris = _previously_diagnosed_uris - current_uris
    for uri in cleared_uris:
        ls.text_document_publish_diagnostics(
            lsp.PublishDiagnosticsParams(uri=uri, diagnostics=[])
        )

    _previously_diagnosed_uris = current_uris


@server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: LanguageServer, params: lsp.DidOpenTextDocumentParams):
    """Срабатывает, когда файл открыли в редакторе."""
    if params.text_document.uri.endswith(".rpy"):
        run_diagnostics(ls, params.text_document.uri)


@server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
def did_save(ls: LanguageServer, params: lsp.DidSaveTextDocumentParams):
    """Срабатывает в реальном времени по Ctrl+S."""
    if params.text_document.uri.endswith(".rpy"):
        run_diagnostics(ls, params.text_document.uri)

_debounce_timer: threading.Timer | None = None


def _trigger_delayed_diagnostics(ls: LanguageServer, uri: str):
    """Запускает диагностику с задержкой 300мс (дебаунс)."""
    global _debounce_timer
    if _debounce_timer is not None:
        _debounce_timer.cancel()

    # Берем живой несохраненный текст прямо из редактора
    doc = ls.workspace.get_text_document(uri)
    file_path = _uri_to_path(uri)
    in_memory = {file_path: doc.source} if doc else None

    # Запускаем через 300 мс после последнего нажатия клавиши
    _debounce_timer = threading.Timer(0.3, run_diagnostics, args=[ls, uri, in_memory])
    _debounce_timer.daemon = True
    _debounce_timer.start()


@server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: LanguageServer, params: lsp.DidChangeTextDocumentParams):
    """Срабатывает прямо на лету при каждом ударе по клавишам!"""
    if params.text_document.uri.endswith(".rpy"):
        _trigger_delayed_diagnostics(ls, params.text_document.uri)


def start_lsp():
    """Запуск сервера через стандартный ввод/вывод (stdio)."""
    server.start_io()