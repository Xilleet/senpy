from __future__ import annotations

import os
import threading
import warnings
from urllib.parse import unquote, urlparse

warnings.filterwarnings("ignore", category=SyntaxWarning)

from lsprotocol import types as lsp

try:
    from pygls.lsp.server import LanguageServer
except ImportError:
    from pygls.server import LanguageServer

from senpy.analyzer import Diagnostic, SenpyAnalyzer

server = LanguageServer("senpy-lsp", "v0.1.3")


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


def run_full_project_diagnostics(ls: LanguageServer, trigger_uri: str):
    """Полное сканирование проекта в одном потоке с блокировкой от параллельных запусков."""
    global _previously_diagnosed_uris, _latest_diagnostics_by_path, _active_analyzer, _current_workspace_root, _is_initialized

    with _analysis_lock:
        file_path = _uri_to_path(trigger_uri)
        project_root = _get_workspace_root(ls, file_path)

        if _active_analyzer is None or _current_workspace_root != project_root:
            _current_workspace_root = project_root
            _active_analyzer = SenpyAnalyzer(project_root)

        result = _active_analyzer.run()
        _is_initialized = True

        files_diags: dict[str, list[lsp.Diagnostic]] = {}
        new_diagnostics_by_path: dict[str, list[tuple[Diagnostic, lsp.Diagnostic]]] = {}

        for diag in result.diagnostics:
            diag_uri = _path_to_uri(diag.file_path)
            lsp_diag = _create_lsp_diagnostic(diag)
            files_diags.setdefault(diag_uri, []).append(lsp_diag)
            norm_file = os.path.normcase(os.path.abspath(diag.file_path))
            new_diagnostics_by_path.setdefault(norm_file, []).append((diag, lsp_diag))

        # Атомарно обновляем общий кэш (без .clear())
        _latest_diagnostics_by_path = new_diagnostics_by_path

        current_uris = set(files_diags.keys())
        for uri, diags in files_diags.items():
            ls.text_document_publish_diagnostics(
                lsp.PublishDiagnosticsParams(uri=uri, diagnostics=diags)
            )

        for uri in (_previously_diagnosed_uris - current_uris):
            ls.text_document_publish_diagnostics(
                lsp.PublishDiagnosticsParams(uri=uri, diagnostics=[])
            )

        _previously_diagnosed_uris = current_uris


def run_single_file_diagnostics(ls: LanguageServer, uri: str, content: str):
    """Сверхбыстрый анализ одного файла на лету (15 мс)."""
    global _active_analyzer, _latest_diagnostics_by_path
    if _active_analyzer is None or not _is_initialized:
        schedule_full_diagnostics(ls, uri)
        return

    with _analysis_lock:
        file_path = _uri_to_path(uri)
        norm_file = os.path.normcase(os.path.abspath(file_path))

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


@server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
def did_save(ls: LanguageServer, params: lsp.DidSaveTextDocumentParams):
    if params.text_document.uri.endswith(".rpy"):
        schedule_full_diagnostics(ls, params.text_document.uri)


@server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: LanguageServer, params: lsp.DidChangeTextDocumentParams):
    if params.text_document.uri.endswith(".rpy"):
        schedule_change_diagnostics(ls, params.text_document.uri)


@server.feature(
    lsp.TEXT_DOCUMENT_CODE_ACTION,
    lsp.CodeActionOptions(code_action_kinds=[lsp.CodeActionKind.QuickFix]),
)
def code_action(ls: LanguageServer, params: lsp.CodeActionParams) -> list[lsp.CodeAction]:
    actions: list[lsp.CodeAction] = []
    try:
        uri = params.text_document.uri
        norm_path = os.path.normcase(_uri_to_path(uri))
        file_base = os.path.basename(norm_path)

        diags_for_file = _latest_diagnostics_by_path.get(norm_path)
        if not diags_for_file:
            for saved_path, saved_diags in _latest_diagnostics_by_path.items():
                if os.path.basename(saved_path) == file_base:
                    diags_for_file = saved_diags
                    break

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
                ins_char = len(raw[:q_pos].encode("utf-16-le")) // 2 if q_pos != -1 else lsp_diag.range.end.character
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

    except Exception as e:
        ls.show_message_log(f"Error in code_action: {e}")

    return actions


def start_lsp():
    server.start_io()