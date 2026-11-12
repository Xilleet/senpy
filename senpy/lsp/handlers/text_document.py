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
    """TEXT_DOCUMENT_DID_CLOSE: removes the file from the analyzer's in-memory buffer.

    Mutates ``_active_analyzer.in_memory_files`` — same shared dict that
    ``run_single_file_diagnostics`` writes to under the RWLock write
    lock. Without that lock a ``did_close`` fired mid-write lets the
    reader see a half-mutated dict (or, on CPython, only the GIL saves
    us from a torn struct). The contract is: any mutation of
    ``in_memory_files`` goes through the write lock, so ``did_close``
    must too.

    Also cancels any pending per-URI change-diagnostics timer for this
    URI. Without this cancel, a stale timer that was scheduled before
    ``did_close`` would fire 150 ms later and re-add the (now-closed)
    document to ``in_memory_files`` via ``run_single_file_diagnostics``,
    resurrecting the closed file and influencing the next full-project
    analysis.
    """
    from senpy.lsp import server as server_mod

    uri = params.text_document.uri
    # Cancel the pending per-URI change timer BEFORE acquiring the write
    # lock — the timer's callback also acquires the write lock, so
    # cancelling it first avoids a guaranteed wait. After cancel, pop
    # the URI from the dict so future did_change events start clean.
    existing = _lsp_server_change_timers().get(uri)
    if existing is not None:
        existing.cancel()
        _lsp_server_change_timers().pop(uri, None)

    # state access via _lsp_server.<attr> accessors.
    # Both lsp_server.active_analyzer and the module global _active_analyzer
    # are the same object (property delegates). Function calls
    # (_normalize_path, _uri_to_path) stay on server_mod — they are module
    # functions, not state.
    lsp_server = server_mod._lsp_server
    if lsp_server.active_analyzer is not None:
        norm_file = server_mod._normalize_path(server_mod._uri_to_path(uri))
        with lsp_server.rw_lock.write_lock():
            # Re-check inside the lock: active_analyzer could have been
            # swapped out by run_full_project_diagnostics between the
            # outer None-check and acquire_write(). The mutation must
            # target the analyzer that is current at mutation time, not
            # the one that was current at check time.
            current = lsp_server.active_analyzer
            if current is not None:
                current.in_memory_files.pop(norm_file, None)


def _lsp_server_change_timers() -> dict:
    """Lazy access to ``_lsp_server.change_timers``.

    Encapsulated as a helper so ``did_close`` can cancel the per-URI
    timer without reaching into ``server_mod._lsp_server`` (which can
    be ``None`` during early LSP init, before any document is opened).
    Returns an empty dict-like object when the server is not yet up —
    in that case there is nothing to cancel anyway.
    """
    from senpy.lsp import server as server_mod

    lsp_server = getattr(server_mod, "_lsp_server", None)
    if lsp_server is None:
        return {}
    return getattr(lsp_server, "change_timers", {}) or {}


def did_change_watched_files(ls, params: lsp.DidChangeWatchedFilesParams) -> None:
    """WORKSPACE_DID_CHANGE_WATCHED_FILES: refresh asset index on external file changes.

    VS Code sends these events when files change on disk outside the
    editor (file manager, git pull, asset pipeline). Without this handler
    the LSP server (long-lived) keeps stale asset data: hover cards
    show non-existent files, RPY501-503 fire on assets that were added
    since the server started.

    Filter events by media extensions (images, audio, video). For other
    files (text, source) we ignore the event — those go through
    ``did_save`` / ``did_change`` which already trigger per-file
    re-analysis.

    A 300ms debounce avoids spamming ``AssetManager.index()`` on bulk
    operations like ``git checkout`` (which can produce dozens of
    file-change events in a few ms).
    """
    from senpy.core.constants import MEDIA_EXTENSIONS
    from senpy.lsp import server as server_mod

    # Quick exit: if there are no media events, do nothing.
    has_media_event = False
    for change in params.changes:
        uri = change.uri
        # URI is typically `file:///path/to/file.png`. Use os.path.splitext
        # to extract the extension; ignore query/fragment.
        path = uri
        for prefix in ("file://", "file:"):
            if path.startswith(prefix):
                path = path[len(prefix) :]
                break
        # Strip query string if present.
        if "?" in path:
            path = path.split("?", 1)[0]
        ext = ""
        if "." in path:
            ext = "." + path.rsplit(".", 1)[1].lower()
        if ext in MEDIA_EXTENSIONS:
            has_media_event = True
            break

    if not has_media_event:
        return

    # Debounce: cancel any pending asset-refresh timer, schedule a new one.
    # We piggy-back on the same timer dict as did_change (per-URI) — using
    # a synthetic URI so it does not collide with real document URIs.
    asset_refresh_uri = "__senpy_asset_refresh__"
    timers = _lsp_server_change_timers()
    existing = timers.get(asset_refresh_uri)
    if existing is not None:
        existing.cancel()

    import threading

    def _refresh_assets():
        # state access via _lsp_server.<attr>. The defensive
        # getattr-with-default was needed when accessing module globals
        # that might not exist during early LSP init — but _lsp_server is
        # a singleton created at module import time, and its @property
        # accessors always return a value (None / False by default). So
        # direct access is safe and cleaner.
        lsp_server = server_mod._lsp_server
        a = lsp_server.active_analyzer
        if a is None or not lsp_server.is_initialized:
            return
        # AssetManager.index() does a fresh disk scan; call under the
        # write lock so readers see a consistent snapshot.
        try:
            with lsp_server.rw_lock.write_lock():
                a.assets.index()
        except Exception:
            # Defensive: an asset refresh failure must not crash the LSP
            # server. Log via the server module logger if available.
            import logging

            logging.getLogger("senpy.lsp.watched_files").debug(
                "AssetManager refresh failed during did_change_watched_files",
                exc_info=True,
            )
        finally:
            timers.pop(asset_refresh_uri, None)

    new_timer = threading.Timer(0.3, _refresh_assets)
    new_timer.daemon = True
    timers[asset_refresh_uri] = new_timer
    new_timer.start()
