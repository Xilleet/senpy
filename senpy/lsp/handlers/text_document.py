"""LSP handlers: textDocument/* lifecycle events.

Extracted from senpy/lsp/server.py in 0.6.0 (Phase 5).

Contains:
  - did_open              ← TEXT_DOCUMENT_DID_OPEN
  - did_save              ← TEXT_DOCUMENT_DID_SAVE
  - did_change            ← TEXT_DOCUMENT_DID_CHANGE
  - did_close             ← TEXT_DOCUMENT_DID_CLOSE
  - did_change_watched_files ← WORKSPACE_DID_CHANGE_WATCHED_FILES

The debounce logic (schedule_full_diagnostics / schedule_change_diagnostics)
remains in server.py — it operates on the module-level _full_timer / _change_timer,
which in 0.6.0-11 will be replaced with a per-URI dict.
"""

from __future__ import annotations

from lsprotocol import types as lsp

# server_mod is imported lazily inside the functions to avoid a circular import
# (senpy.lsp.server is not fully initialized yet when this module is loaded).
# The alternative would be to pass server_state via parameters, but that would
# break back-compat with existing tests that call handlers directly.


def did_open(ls, params: lsp.DidOpenTextDocumentParams) -> None:
    """TEXT_DOCUMENT_DID_OPEN: starts a full project scan for .rpy files."""
    if params.text_document.uri.endswith(".rpy"):
        from senpy.lsp import server as server_mod

        server_mod.schedule_full_diagnostics(ls, params.text_document.uri)


def did_save(ls, params: lsp.DidSaveTextDocumentParams) -> None:
    """TEXT_DOCUMENT_DID_SAVE: restarts the full project scan for .rpy files."""
    if params.text_document.uri.endswith(".rpy"):
        from senpy.lsp import server as server_mod

        server_mod.schedule_full_diagnostics(ls, params.text_document.uri)


def did_change(ls, params: lsp.DidChangeTextDocumentParams) -> None:
    """TEXT_DOCUMENT_DID_CHANGE: incremental single-file analysis for .rpy."""
    if params.text_document.uri.endswith(".rpy"):
        from senpy.lsp import server as server_mod

        server_mod.schedule_change_diagnostics(ls, params.text_document.uri)


def did_close(ls, params: lsp.DidCloseTextDocumentParams) -> None:
    """TEXT_DOCUMENT_DID_CLOSE: removes the file from the analyzer's in-memory buffer."""
    from senpy.lsp import server as server_mod

    uri = params.text_document.uri
    if server_mod._active_analyzer is not None:
        norm_file = server_mod._normalize_path(server_mod._uri_to_path(uri))
        server_mod._active_analyzer.in_memory_files.pop(norm_file, None)


def did_change_watched_files(ls, params: lsp.DidChangeWatchedFilesParams) -> None:
    """WORKSPACE_DID_CHANGE_WATCHED_FILES: stub to prevent spam in the Output log.

    VS Code sends these events on any .rpy file change on disk. If we don't
    stub them out — the LSP server's Output log grows to megabytes over a
    session. Real analysis is triggered via did_save / did_change.
    """
