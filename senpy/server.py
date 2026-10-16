from __future__ import annotations

import os
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


def run_diagnostics(ls: LanguageServer, trigger_uri: str):
    """Запускает SenpyAnalyzer и рассылает ошибки по всем файлам проекта."""
    file_path = _uri_to_path(trigger_uri)
    project_root = _get_workspace_root(ls, file_path)

    analyzer = SenpyAnalyzer(project_root)
    result = analyzer.run()

    files_diags: dict[str, list[lsp.Diagnostic]] = {}

    for diag in result.diagnostics:
        diag_uri = _path_to_uri(diag.file_path)
        
        line_str = diag.line_content.rstrip("\r\n")
        indent_len = len(line_str) - len(line_str.lstrip())
        line_idx = max(0, diag.line_number - 1)
        
        severity_map = {
            "ERROR": lsp.DiagnosticSeverity.Error,
            "WARNING": lsp.DiagnosticSeverity.Warning,
            "INFO": lsp.DiagnosticSeverity.Information,
        }

        lsp_diag = lsp.Diagnostic(
            range=lsp.Range(
                start=lsp.Position(line=line_idx, character=indent_len),
                end=lsp.Position(line=line_idx, character=len(line_str)),
            ),
            message=f"[{diag.code}] {diag.message}",
            severity=severity_map.get(diag.severity, lsp.DiagnosticSeverity.Warning),
            source="senpy",
            code=diag.code,
        )

        files_diags.setdefault(diag_uri, []).append(lsp_diag)

    # Публикация для pygls 2.x
    current_file_diags = files_diags.get(trigger_uri, [])
    ls.text_document_publish_diagnostics(
        lsp.PublishDiagnosticsParams(uri=trigger_uri, diagnostics=current_file_diags)
    )

    for uri, diags in files_diags.items():
        if uri != trigger_uri:
            ls.text_document_publish_diagnostics(
                lsp.PublishDiagnosticsParams(uri=uri, diagnostics=diags)
            )


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


def start_lsp():
    """Запуск сервера через стандартный ввод/вывод (stdio)."""
    server.start_io()