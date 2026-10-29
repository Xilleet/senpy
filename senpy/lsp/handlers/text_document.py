"""LSP handlers: textDocument/* lifecycle events.

Вынесено из senpy/lsp/server.py в 0.6.0 (Фаза 5).

Содержит:
  - did_open              ← TEXT_DOCUMENT_DID_OPEN
  - did_save              ← TEXT_DOCUMENT_DID_SAVE
  - did_change            ← TEXT_DOCUMENT_DID_CHANGE
  - did_close             ← TEXT_DOCUMENT_DID_CLOSE
  - did_change_watched_files ← WORKSPACE_DID_CHANGE_WATCHED_FILES

Логика debounce (schedule_full_diagnostics / schedule_change_diagnostics)
остаётся в server.py — она оперирует module-level _full_timer / _change_timer,
которые в 0.6.0-11 будут заменены на per-URI dict.
"""
from __future__ import annotations

from lsprotocol import types as lsp

# server_mod импортируется лениво внутри функций, чтобы избежать циклического
# импорта (senpy.lsp.server ещё не до конца инициализирован, когда этот модуль
# грузится). Альтернатива — передавать server_state через параметры, но это
# сломает back-compat с существующими тестами, которые зовут handler'ы напрямую.


def did_open(ls, params: lsp.DidOpenTextDocumentParams) -> None:
    """TEXT_DOCUMENT_DID_OPEN: запускает full project scan для .rpy файлов."""
    if params.text_document.uri.endswith(".rpy"):
        from senpy.lsp import server as server_mod
        server_mod.schedule_full_diagnostics(ls, params.text_document.uri)


def did_save(ls, params: lsp.DidSaveTextDocumentParams) -> None:
    """TEXT_DOCUMENT_DID_SAVE: перезапускает full project scan для .rpy файлов."""
    if params.text_document.uri.endswith(".rpy"):
        from senpy.lsp import server as server_mod
        server_mod.schedule_full_diagnostics(ls, params.text_document.uri)


def did_change(ls, params: lsp.DidChangeTextDocumentParams) -> None:
    """TEXT_DOCUMENT_DID_CHANGE: incremental single-file analysis для .rpy."""
    if params.text_document.uri.endswith(".rpy"):
        from senpy.lsp import server as server_mod
        server_mod.schedule_change_diagnostics(ls, params.text_document.uri)


def did_close(ls, params: lsp.DidCloseTextDocumentParams) -> None:
    """TEXT_DOCUMENT_DID_CLOSE: убирает файл из in-memory буфера анализатора."""
    from senpy.lsp import server as server_mod
    uri = params.text_document.uri
    if server_mod._active_analyzer is not None:
        norm_file = server_mod._normalize_path(server_mod._uri_to_path(uri))
        server_mod._active_analyzer.in_memory_files.pop(norm_file, None)


def did_change_watched_files(ls, params: lsp.DidChangeWatchedFilesParams) -> None:
    """WORKSPACE_DID_CHANGE_WATCHED_FILES: заглушка против спама в Output логе.

    VS Code шлёт эти события на любое изменение .rpy файла на диске. Если мы
    их не заглушим — Output лог LSP-сервера разрастается до мегабайтов за
    сессию. Реальный анализ запускается через did_save / did_change.
    """
