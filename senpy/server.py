from __future__ import annotations

import os
import threading
from urllib.parse import unquote, urlparse

from lsprotocol import types as lsp

try:
    from pygls.lsp.server import LanguageServer
except ImportError:
    from pygls.server import LanguageServer

from senpy.analyzer import Diagnostic, SenpyAnalyzer

server = LanguageServer("senpy-lsp", "v0.1.2")


def _uri_to_path(uri: str) -> str:
    parsed = urlparse(uri)
    path = unquote(parsed.path)
    if os.name == "nt" and path.startswith("/"):
        path = path[1:]
    return os.path.normpath(path)


def _path_to_uri(path: str) -> str:
    from pathlib import Path
    return Path(os.path.abspath(path)).as_uri()


def _get_workspace_root(ls: LanguageServer, fallback_file_path: str) -> str:
    if ls.workspace.root_path:
        return ls.workspace.root_path
    return os.path.dirname(fallback_file_path)


_previously_diagnosed_uris: set[str] = set()
_latest_diagnostics_by_path: dict[str, list[tuple[Diagnostic, lsp.Diagnostic]]] = {}
_debounce_timer: threading.Timer | None = None
_active_analyzer: SenpyAnalyzer | None = None
_current_workspace_root: str | None = None


def run_diagnostics(ls: LanguageServer, trigger_uri: str, in_memory: dict[str, str] | None = None):
    global _previously_diagnosed_uris, _latest_diagnostics_by_path, _active_analyzer, _current_workspace_root
    file_path = _uri_to_path(trigger_uri)
    project_root = _get_workspace_root(ls, file_path)

    # Переиспользуем закэшированный экземпляр анализатора для одного workspace
    if _active_analyzer is None or _current_workspace_root != project_root:
        _current_workspace_root = project_root
        _active_analyzer = SenpyAnalyzer(project_root, in_memory_files=in_memory)
    else:
        _active_analyzer.in_memory_files = {
            os.path.normcase(os.path.abspath(k)): v
            for k, v in (in_memory or {}).items()
        }

    result = _active_analyzer.run()

    files_diags: dict[str, list[lsp.Diagnostic]] = {}
    _latest_diagnostics_by_path.clear()

    severity_map = {
        "ERROR": lsp.DiagnosticSeverity.Error,
        "WARNING": lsp.DiagnosticSeverity.Warning,
        "INFO": lsp.DiagnosticSeverity.Information,
    }

    for diag in result.diagnostics:
        diag_uri = _path_to_uri(diag.file_path)
        line_idx = max(0, diag.line_number - 1)

        if diag.end_col > diag.col:
            start_char = diag.col
            end_char = diag.end_col
        else:
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
            code_description=lsp.CodeDescription(
                href=f"https://github.com/Xilleet/senpy/blob/main/RULES.md#{diag.code.lower()}"
            ),
        )

        files_diags.setdefault(diag_uri, []).append(lsp_diag)
        norm_file = os.path.normcase(os.path.abspath(diag.file_path))
        _latest_diagnostics_by_path.setdefault(norm_file, []).append((diag, lsp_diag))

    current_uris = set(files_diags.keys())
    for uri, diags in files_diags.items():
        ls.text_document_publish_diagnostics(
            lsp.PublishDiagnosticsParams(uri=uri, diagnostics=diags)
        )

    cleared_uris = _previously_diagnosed_uris - current_uris
    for uri in cleared_uris:
        ls.text_document_publish_diagnostics(
            lsp.PublishDiagnosticsParams(uri=uri, diagnostics=[])
        )

    _previously_diagnosed_uris = current_uris


def _trigger_delayed_diagnostics(ls: LanguageServer, uri: str):
    global _debounce_timer
    if _debounce_timer is not None:
        _debounce_timer.cancel()

    doc = ls.workspace.get_text_document(uri)
    file_path = _uri_to_path(uri)
    in_memory = {file_path: doc.source} if doc else None

    _debounce_timer = threading.Timer(0.25, run_diagnostics, args=[ls, uri, in_memory])
    _debounce_timer.daemon = True
    _debounce_timer.start()


@server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: LanguageServer, params: lsp.DidOpenTextDocumentParams):
    if params.text_document.uri.endswith(".rpy"):
        run_diagnostics(ls, params.text_document.uri)


@server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
def did_save(ls: LanguageServer, params: lsp.DidSaveTextDocumentParams):
    if params.text_document.uri.endswith(".rpy"):
        run_diagnostics(ls, params.text_document.uri)


@server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: LanguageServer, params: lsp.DidChangeTextDocumentParams):
    if params.text_document.uri.endswith(".rpy"):
        _trigger_delayed_diagnostics(ls, params.text_document.uri)


@server.feature(lsp.TEXT_DOCUMENT_CODE_ACTION)
def code_action(ls: LanguageServer, params: lsp.CodeActionParams) -> list[lsp.CodeAction]:
    actions: list[lsp.CodeAction] = []
    uri = params.text_document.uri
    norm_path = os.path.normcase(_uri_to_path(uri))

    if norm_path not in _latest_diagnostics_by_path:
        return actions

    user_line = params.range.start.line

    for diag, lsp_diag in _latest_diagnostics_by_path[norm_path]:
        line_idx = max(0, diag.line_number - 1)
        if line_idx == user_line and diag.fix_title and diag.fix_replacement:
            if diag.fix_start_col is not None and diag.fix_end_col is not None:
                edit_range = lsp.Range(
                    start=lsp.Position(line=line_idx, character=diag.fix_start_col),
                    end=lsp.Position(line=line_idx, character=diag.fix_end_col),
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

    return actions


def start_lsp():
    server.start_io()