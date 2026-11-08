from __future__ import annotations

import functools
import os
import threading
import time
from urllib.parse import unquote, urlparse

from lsprotocol import types as lsp

from senpy.__version__ import VERSION_WITH_PREFIX as _SENPY_VERSION
from senpy.core.analyzer import Diagnostic, SenpyAnalyzer
from senpy.core.exceptions import SecurityError
from senpy.core.logging import get_logger

_logger = get_logger("lsp.server")

try:
    from pygls.lsp.server import LanguageServer
except ImportError:
    from pygls.server import LanguageServer  # type: ignore[attr-defined, no-redef]

server = LanguageServer("senpy-lsp", _SENPY_VERSION)


def _uri_to_path(uri: str, workspace_root: str | None = None) -> str:
    """Converts an LSP file:// URI to a filesystem path with security checks.

    Workspace containment check.

    Two protections:
      1. **Scheme validation** — only the `file:` scheme is accepted. Any
         other (`http:`, `https:`, `ftp:`, `git+ssh:`, empty) → `ValueError`.
         Protection against a malicious client passing a URI to a remote
         resource (which `urlparse` would parse, but `open()` would then make
         a network request or read an unexpected path).
      2. **Workspace containment** (if `workspace_root` is passed) — the path
         after `realpath` must be inside `workspace_root`. Protection
         against path traversal (`../../../etc/passwd`) and URIs outside the project.
         Backward compat: if `workspace_root=None`, the check is skipped
         (contract for handlers whose workspace is not yet initialized).

    Args:
        uri: LSP URI (usually `file://...`).
        workspace_root: Optional project root. If passed — the path
            must be inside it after normalization.

    Returns:
        Normalized filesystem path.

    Raises:
        SecurityError: if the scheme is not `file:` OR the path is outside workspace_root.
            SecurityError inherits from ValueError for backward compat —
            old callers with `except ValueError:` keep working.
    """
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise SecurityError(
            f"_uri_to_path: unsupported URI scheme {parsed.scheme!r}; "
            f"only 'file:' is allowed (uri={uri!r})"
        )
    path = unquote(parsed.path)
    if os.name == "nt" and path.startswith("/"):
        path = path[1:]
    path = os.path.normpath(path)

    if workspace_root is not None:
        root_real = os.path.realpath(workspace_root)
        path_real = os.path.realpath(path)
        # os.path.commonpath returns the common prefix; if path_real is not inside
        # root_real — commonpath will be shorter than root_real.
        try:
            common = os.path.commonpath([root_real, path_real])
        except ValueError:
            # ValueError: paths on different drives (Windows) or mix of abs/rel.
            raise SecurityError(
                f"_uri_to_path: path {path_real!r} is outside workspace "
                f"root {root_real!r} (cannot compute common path)"
            ) from None
        if common != root_real:
            raise SecurityError(
                f"_uri_to_path: path {path_real!r} is outside workspace root {root_real!r}"
            )

    return path


def _path_to_uri(path: str) -> str:
    from pathlib import Path

    return Path(os.path.abspath(path)).as_uri()


def _normalize_path(path: str) -> str:
    """P0-6: unified path normalization for _latest_diagnostics_by_path keys.

    Previously different places used different normalizations:
    - os.path.normcase(os.path.abspath(...)) — in run_full_project_diagnostics (L127),
      run_single_file_diagnostics (L155), did_save (L219), document_symbols (L673)
    - os.path.normcase(_uri_to_path(uri)) without abspath — in code_action (L237)

    Because of this, lookups in _latest_diagnostics_by_path on relative paths
    did not find diagnostics, and the unsafe basename-fallback was triggered,
    which in multi-module projects could pick a QuickFix from the wrong file
    (e.g., game/script.rpy and mods/script.rpy would collide).

    Now all 4 places use _normalize_path — a single contract.
    """
    return os.path.normcase(os.path.abspath(path))


def _get_workspace_root(ls: LanguageServer, fallback_file_path: str) -> str:
    if ls.workspace.root_path:
        return ls.workspace.root_path
    return os.path.dirname(fallback_file_path)


class _RWLock:
    """Reader-writer lock with writer preference.

    Introduced in 0.6.0-12 (P1'-9). Previously all handlers took an exclusive
    threading.Lock — because of this, parallel read-only calls (definition,
    hover, completions) were serialized. RWLock allows multiple readers to
    work in parallel; the write lock is exclusive.

    Writer preference: if there is a waiting writer, new readers wait.
    This prevents writer starvation under a constant stream of readers
    (which is typical for LSP — the client sends hover/completions continuously).

    Implemented with a Condition + 2 counters. No external dependencies.

    Note (0.7.5): we considered replacing this with the `readerwriterlock`
    package, but its API (gen_rlock/gen_wlock context managers) is
    thread-local — the thread that acquires must be the one that releases.
    Our call sites use acquire/release in the same thread (LSP handlers),
    but the unit tests in test_lsp_rwlock.py exercise cross-thread
    acquire/release to verify writer preference. A full migration would
    require rewriting both call sites and tests to use context managers
    everywhere. Deferred to post-1.0 (see worklog for the readerwriterlock
    migration follow-up).
    """

    def __init__(self):
        self._cond = threading.Condition()
        self._readers = 0
        self._writers_waiting = 0
        self._writer_active = False

    def acquire_read(self, timeout: float | None = None) -> bool:
        """Acquire the read lock. Returns True if acquired, False on timeout."""
        with self._cond:
            # Wait while a writer is active OR there is a waiting writer (preference)
            deadline = None if timeout is None else time.monotonic() + timeout
            while self._writer_active or self._writers_waiting > 0:
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    self._cond.wait(timeout=remaining)
                else:
                    self._cond.wait()
            self._readers += 1
            return True

    def release_read(self) -> None:
        with self._cond:
            self._readers -= 1
            if self._readers == 0:
                self._cond.notify_all()

    def acquire_write(self, timeout: float | None = None) -> bool:
        """Acquire the write lock. Returns True if acquired, False on timeout."""
        with self._cond:
            self._writers_waiting += 1
            try:
                deadline = None if timeout is None else time.monotonic() + timeout
                while self._writer_active or self._readers > 0:
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            return False
                        self._cond.wait(timeout=remaining)
                    else:
                        self._cond.wait()
                self._writer_active = True
                return True
            finally:
                self._writers_waiting -= 1

    def release_write(self) -> None:
        with self._cond:
            self._writer_active = False
            self._cond.notify_all()

    # Context managers for convenience
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
    """Container for LSP server state.

    Introduced in 0.6.0-9 (Phase 5). For now it only contains stateful methods —
    module-level globals (_active_analyzer, _is_initialized, ...) remain
    for back-compat with tests and handlers. In 0.7.0 the module-level state will
    be removed, and all handlers will address the singleton _lsp_server.

    P1'-7: 9 module globals → class fields (gradual migration)
    P1'-8: per-URI debounce dict[str, Timer] (in 0.6.0-11) ✅
    P1'-9: reader-writer lock for analysis_lock (in 0.6.0-12) ✅
    """

    def __init__(self):
        # P1'-8: per-URI debounce timers.
        self.change_timers: dict[str, threading.Timer] = {}
        # P1'-9: reader-writer lock for analysis state.
        # Reader-writer lock: reading handlers take a read lock (parallel),
        # writers (run_full / run_single_file_diagnostics) take a write
        # lock (exclusive). The legacy module-level _analysis_lock was
        # removed in T-009 (0.8.0) — it serialised every reader,
        # defeating the RWLock.
        self.rw_lock = _RWLock()


# Singleton instance for future use.
_lsp_server = SenpyLSPServer()


_previously_diagnosed_uris: set[str] = set()
_latest_diagnostics_by_path: dict[str, list[tuple[Diagnostic, lsp.Diagnostic]]] = {}
_change_timer: threading.Timer | None = None
_full_timer: threading.Timer | None = None
_active_analyzer: SenpyAnalyzer | None = None
_current_workspace_root: str | None = None
_is_initialized: bool = False

# UX: snapshot of labels/screens/transforms/images for autocomplete/rename/hover.
# After run() we make a shallow copy of these dicts so that analyze_file_only (called
# on did_change) does not drop labels from other files out of _active_analyzer.labels.
# Without the snapshot, autocomplete only shows labels from the current file —
# the "jump in day1a.rpy doesn't suggest labels from day10a.rpy" bug.
_symbol_snapshot: dict[str, dict] = {
    "labels": {},
    "screens": {},
    "transforms": {},
    "variables": {},
    "images": set(),
    "jump_sources": {},
    # Per-file index of labels sorted by line_number — used by
    # incoming_calls for O(log N) containing-label lookup instead of
    # O(N) scan of every label in the project per jump source.
    # Structure: {file_path: [(label_name, line_number), ...]}
    "labels_by_file": {},
}


def _refresh_symbol_snapshot() -> None:
    """Refresh the snapshot of labels/screens/transforms/... from _active_analyzer.

    Called after every run() (full project scan). The snapshot is used by
    autocomplete/rename/prepare_rename/hover so they see ALL symbols of the
    project, even if analyze_file_only cleared _active_analyzer.labels.
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
    # Per-file index of labels sorted by line_number. incoming_calls uses
    # this to find the label containing a jump site in O(labels_in_file)
    # instead of O(all_labels) — for a project with 500 labels across 10
    # files, that's ~50 iterations per jump source instead of 500.
    labels_by_file: dict[str, list[tuple[str, int]]] = {}
    for name, lbl in _active_analyzer.labels.items():
        labels_by_file.setdefault(lbl.file_path, []).append((name, lbl.line_number))
    for file_labels in labels_by_file.values():
        file_labels.sort(key=lambda item: item[1])
    _symbol_snapshot["labels_by_file"] = labels_by_file


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
    """Reading handlers take the RWLock read lock.

    Writers (run_full_project_diagnostics / run_single_file_diagnostics)
    mutate the _active_analyzer registries only under the write lock;
    without it, readers catch RuntimeError: dictionary changed size
    during iteration and see half-written snapshots. The wrapper signature
    is strictly (ls, params): pygls inspects the first parameter
    (wrap_with_server) and decides whether to pass the server instance
    as the first argument.

    Reading handlers (completions / definition / hover / document_symbols
    / code_action / etc.) take a read lock — multiple handlers can work
    in parallel. Writers take a write lock exclusively.

    The legacy module-level ``_analysis_lock`` was removed in
    0.8.0: it serialised every reader, defeating the RWLock. Reader
    concurrency is now real — see
    ``tests/test_lsp_rwlock.py::test_with_analysis_lock_handlers_run_in_parallel``.
    """

    @functools.wraps(func)
    def wrapper(ls, params):
        _lsp_server.rw_lock.acquire_read()
        try:
            return func(ls, params)
        finally:
            _lsp_server.rw_lock.release_read()

    return wrapper


def run_full_project_diagnostics(ls: LanguageServer, trigger_uri: str):
    """Full project scan in a single thread with protection against parallel runs.

    P1'-9 (0.6.0-12): takes the write lock — exclusive access to state.
    While a writer runs, no reader (handler) will start.
    """
    global \
        _previously_diagnosed_uris, \
        _latest_diagnostics_by_path, \
        _active_analyzer, \
        _current_workspace_root, \
        _is_initialized

    _lsp_server.rw_lock.acquire_write()
    try:
        # trigger_uri may be empty when called from the `initialized`
        # handler (workspace-wide scan with no specific file). In that
        # case fall back to the workspace root path; if that's also
        # missing, log and return silently — there is nothing to scan.
        if trigger_uri:
            file_path = _uri_to_path(trigger_uri)
            project_root = _get_workspace_root(ls, file_path)
        else:
            try:
                workspace_root = ls.workspace.root_path
            except AttributeError:
                workspace_root = None
            if not workspace_root:
                _logger.debug(
                    "run_full_project_diagnostics: empty trigger_uri and "
                    "no workspace root; skipping scan"
                )
                return
            project_root = workspace_root

        if _active_analyzer is None or _current_workspace_root != project_root:
            _current_workspace_root = project_root
            _active_analyzer = SenpyAnalyzer(project_root)

        result = _active_analyzer.run(quiet=True)
        _is_initialized = True
        # UX: snapshot of symbols for autocomplete/rename/hover.
        # Must be AFTER run() but BEFORE the diagnostics check.
        _refresh_symbol_snapshot()

        files_diags: dict[str, list[lsp.Diagnostic]] = {}
        new_diagnostics_by_path: dict[str, list[tuple[Diagnostic, lsp.Diagnostic]]] = {}

        for diag in result.diagnostics:
            diag_uri = _path_to_uri(diag.file_path)
            lsp_diag = _create_lsp_diagnostic(diag)
            files_diags.setdefault(diag_uri, []).append(lsp_diag)
            norm_file = _normalize_path(diag.file_path)  # P0-6: unified normalization
            new_diagnostics_by_path.setdefault(norm_file, []).append((diag, lsp_diag))

        # Atomically update the shared cache (without .clear())
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
    """Ultra-fast on-the-fly analysis of a single file (15 ms).

    P1'-9 (0.6.0-12): takes the write lock — mutates _active_analyzer.in_memory_files
    and _latest_diagnostics_by_path.
    """
    if _active_analyzer is None or not _is_initialized:
        schedule_full_diagnostics(ls, uri)
        return

    _lsp_server.rw_lock.acquire_write()
    try:
        file_path = _uri_to_path(uri)
        norm_file = _normalize_path(file_path)  # P0-6: unified normalization

        _active_analyzer.in_memory_files[norm_file] = content
        diags = _active_analyzer.analyze_file_only(file_path)

        # Refresh the symbol snapshot so handlers (hover, completion,
        # rename, references) see the just-analyzed file's new symbols.
        # Without this, adding a new label/variable/screen and hovering
        # over a reference BEFORE did_save fires would return None —
        # the snapshot was only refreshed by run_full_project_diagnostics
        # and stayed stale for the entire did_change → did_save window.
        # The refresh is cheap (shallow dict copies) compared to the
        # analyze_file_only work that just ran.
        _refresh_symbol_snapshot()

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
    """Debounce for the full scan (suppresses a batch of simultaneous didOpen)."""
    global _full_timer
    if _full_timer is not None:
        _full_timer.cancel()
    _full_timer = threading.Timer(0.3, run_full_project_diagnostics, args=[ls, uri])
    _full_timer.daemon = True
    _full_timer.start()


def schedule_change_diagnostics(ls: LanguageServer, uri: str):
    """Debounce while typing.

    P1'-8 (0.6.0-11): per-URI debounce. Previously there was a single shared
    _change_timer for all URIs — when editing 2+ files at once, the timers
    conflicted (the last-edited file cancelled the pending analysis of other
    files). Now each URI has its own timer in _lsp_server.change_timers.

    _change_timer (module-level) is kept for back-compat with tests that
    verify cancel logic. It will be removed in 0.7.0.
    """
    global _change_timer

    # P1'-8: cancel existing timer for THIS uri only
    existing = _lsp_server.change_timers.get(uri)
    if existing is not None:
        existing.cancel()

    doc = ls.workspace.get_text_document(uri)
    if not doc:
        # If the document is not found — remove the pending timer for this URI
        _lsp_server.change_timers.pop(uri, None)
        # Back-compat: also reset the module-level _change_timer (if it was for this URI)
        if _change_timer is not None:
            _change_timer.cancel()
            _change_timer = None
        return

    new_timer = threading.Timer(0.15, run_single_file_diagnostics, args=[ls, uri, doc.source])
    new_timer.daemon = True
    _lsp_server.change_timers[uri] = new_timer
    # Back-compat: duplicate into the module-level _change_timer for tests checking cancel
    _change_timer = new_timer
    new_timer.start()


@server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: LanguageServer, params: lsp.DidOpenTextDocumentParams):
    """0.6.0-3: delegates to handlers.text_document."""
    from senpy.lsp.handlers.text_document import did_open as _impl

    _impl(ls, params)


@server.feature(lsp.WORKSPACE_DID_CHANGE_WATCHED_FILES)
def did_change_watched_files(ls: LanguageServer, params: lsp.DidChangeWatchedFilesParams):
    """0.6.0-3: delegates to handlers.text_document."""
    from senpy.lsp.handlers.text_document import did_change_watched_files as _impl

    _impl(ls, params)


@server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
def did_save(ls: LanguageServer, params: lsp.DidSaveTextDocumentParams):
    """0.6.0-3: delegates to handlers.text_document."""
    from senpy.lsp.handlers.text_document import did_save as _impl

    _impl(ls, params)


@server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)
def did_close(ls: LanguageServer, params: lsp.DidCloseTextDocumentParams):
    """0.6.0-3: delegates to handlers.text_document."""
    from senpy.lsp.handlers.text_document import did_close as _impl

    _impl(ls, params)


@server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: LanguageServer, params: lsp.DidChangeTextDocumentParams):
    """0.6.0-3: delegates to handlers.text_document."""
    from senpy.lsp.handlers.text_document import did_change as _impl

    _impl(ls, params)


@server.feature(
    lsp.TEXT_DOCUMENT_CODE_ACTION,
    lsp.CodeActionOptions(code_action_kinds=[lsp.CodeActionKind.QuickFix]),
)
@_with_analysis_lock
def code_action(ls: LanguageServer, params: lsp.CodeActionParams) -> list[lsp.CodeAction]:
    """0.6.0: delegates to handlers.diagnostics."""
    from senpy.lsp.handlers.diagnostics import code_action as _impl

    return _impl(ls, params)


@server.feature(lsp.TEXT_DOCUMENT_COMPLETION)
@_with_analysis_lock
def completions(ls: LanguageServer, params: lsp.CompletionParams) -> lsp.CompletionList:
    """0.6.0: delegates to handlers.completion."""
    from senpy.lsp.handlers.completion import completions as _impl

    return _impl(ls, params)


@server.feature(lsp.TEXT_DOCUMENT_DEFINITION)
@_with_analysis_lock
def definition(ls: LanguageServer, params: lsp.DefinitionParams) -> lsp.Location | None:
    """0.6.0-4: delegates to handlers.navigation."""
    from senpy.lsp.handlers.navigation import definition as _impl

    return _impl(ls, params)


@server.feature(lsp.TEXT_DOCUMENT_REFERENCES)
@_with_analysis_lock
def references(ls: LanguageServer, params: lsp.ReferenceParams) -> list[lsp.Location] | None:
    """0.6.0-4: delegates to handlers.navigation."""
    from senpy.lsp.handlers.navigation import references as _impl

    return _impl(ls, params)


@server.feature(lsp.TEXT_DOCUMENT_HOVER)
@_with_analysis_lock
def hover(ls: LanguageServer, params: lsp.HoverParams) -> lsp.Hover | None:
    """0.6.0: delegates to handlers.hover."""
    from senpy.lsp.handlers.hover import hover as _impl

    return _impl(ls, params)


@server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
@_with_analysis_lock
def document_symbols(
    ls: LanguageServer, params: lsp.DocumentSymbolParams
) -> list[lsp.DocumentSymbol]:
    """0.6.0-4: delegates to handlers.navigation."""
    from senpy.lsp.handlers.navigation import document_symbols as _impl

    return _impl(ls, params)


# =============================================================================
# UX-1: textDocument/foldingRange — fold label/screen/menu/init blocks
# =============================================================================
# Allows VS Code to fold code blocks:
# - label X: ... (until the next label or end of file)
# - screen X(): ...
# - menu: ...
# - init python: ...
# - transform X: ...
# - python: ...
#
# Algorithm: walk through lines, track indentation. On a scope-opening
# keyword — open a folding range. Close when indentation decreases
# to the same level or below.
@server.feature(lsp.TEXT_DOCUMENT_FOLDING_RANGE)
@_with_analysis_lock
def folding_range(ls: LanguageServer, params: lsp.FoldingRangeParams) -> list[lsp.FoldingRange]:
    """0.6.0: delegates to handlers.workspace."""
    from senpy.lsp.handlers.workspace import folding_range as _impl

    return _impl(ls, params)


# =============================================================================
# UX: textDocument/prepareRename — preview before F2 rename
# =============================================================================
# VS Code calls prepareRename before the actual rename, to:
# 1. Check that there is a valid symbol for renaming under the cursor
# 2. Show the user the Range of the word that will be renamed
# 3. Allow cancellation before applying changes (preview mode)
#
# If None is returned — VS Code shows "The element can't be renamed" and
# does not let the user press F2.
#
# Algorithm: find the word under the cursor. If it's a label (present in
# _active_analyzer.labels) — return its Range. Otherwise None.
@server.feature(lsp.TEXT_DOCUMENT_PREPARE_RENAME)
@_with_analysis_lock
def prepare_rename(
    ls: LanguageServer, params: lsp.PrepareRenameParams
) -> lsp.Range | lsp.PrepareRenameResult | None:
    """0.6.0-4: delegates to handlers.navigation."""
    from senpy.lsp.handlers.navigation import prepare_rename as _impl

    return _impl(ls, params)


# =============================================================================
# UX-2: textDocument/rename — rename labels
# =============================================================================
# Renames the label everywhere it appears:
# - Declaration (label X:)
# - All `jump X`
# - All `call X`
#
# Uses the jump_sources reverse index from the analyzer.
# Returns a WorkspaceEdit with changes for all project files.
#
# UX: prepare_provider=True — VS Code calls prepareRename before F2,
# to show a preview and allow cancellation before applying.
@server.feature(
    lsp.TEXT_DOCUMENT_RENAME,
    lsp.RenameOptions(prepare_provider=True),
)
@_with_analysis_lock
def rename(ls: LanguageServer, params: lsp.RenameParams) -> lsp.WorkspaceEdit | None:
    """0.6.0-4: delegates to handlers.navigation."""
    from senpy.lsp.handlers.navigation import rename as _impl

    return _impl(ls, params)


# =============================================================================
# UX-3: workspace/symbol — global symbol search (Ctrl+T)
# =============================================================================
# Returns all labels, screens, transforms in the project.
# VS Code: Ctrl+T → type a name → jump to its definition.
#
# Supports query filtering (case-insensitive substring match).
# If the query is empty — returns all symbols.
@server.feature(lsp.WORKSPACE_SYMBOL)
@_with_analysis_lock
def workspace_symbol(
    ls: LanguageServer, params: lsp.WorkspaceSymbolParams
) -> list[lsp.WorkspaceSymbol]:
    """0.6.0: delegates to handlers.workspace."""
    from senpy.lsp.handlers.workspace import workspace_symbol as _impl

    return _impl(ls, params)


# =============================================================================
# UX-12: initialized — start a full project scan right after initialization
# =============================================================================
# Without this handler, hover/completion don't work for the first 300ms after
# opening a file (until the first did_save). initialized starts the scan immediately.
@server.feature(lsp.INITIALIZED)
def initialized(ls: LanguageServer, params: lsp.InitializedParams) -> None:
    """0.6.0: delegates to handlers.workspace."""
    from senpy.lsp.handlers.workspace import initialized as _impl

    return _impl(ls, params)


# =============================================================================
# UX-5: documentHighlight — highlight all occurrences of a word in the file
# =============================================================================
# VS Code: cursor on a variable/label → all its occurrences in the file are highlighted.
# Looks up the word in: labels, screens, transforms, variables (declared_symbols).
# Returns DocumentHighlight with kind: Write (declaration) / Read (usage).
@server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT)
@_with_analysis_lock
def document_highlight(
    ls: LanguageServer, params: lsp.DocumentHighlightParams
) -> list[lsp.DocumentHighlight]:
    """0.6.0: delegates to handlers.workspace."""
    from senpy.lsp.handlers.workspace import document_highlight as _impl

    return _impl(ls, params)


# =============================================================================
# textDocument/documentColor + colorPresentation — hex color swatches
# =============================================================================
# VS Code displays color swatches next to #ffffff literals. Clicking opens
# a color picker that updates the literal.
#
# Killer feature for VN — lots of colors in {color=#...} tags, Solid("#..."),
# Color("#..."), and hex literals in init python.
@server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_COLOR)
@_with_analysis_lock
def document_color(
    ls: LanguageServer, params: lsp.DocumentColorParams
) -> list[lsp.ColorInformation]:
    """0.6.0 Sub-sprint 3: delegates to handlers.diagnostics."""
    from senpy.lsp.handlers.diagnostics import document_color as _impl

    return _impl(ls, params)


@server.feature(lsp.TEXT_DOCUMENT_COLOR_PRESENTATION)
@_with_analysis_lock
def color_presentation(
    ls: LanguageServer, params: lsp.ColorPresentationParams
) -> list[lsp.ColorPresentation]:
    """0.6.0 Sub-sprint 3: delegates to handlers.diagnostics."""
    from senpy.lsp.handlers.diagnostics import color_presentation as _impl

    return _impl(ls, params)


# =============================================================================
# textDocument/formatting — Shift+Alt+F
# =============================================================================
# Integrates senpy.formatter (from Sub-sprint 1) into VS Code.
# Shift+Alt+F → formatting() — formats whole document
#
# textDocument/rangeFormatting (Ctrl+K Ctrl+F) is intentionally NOT
# registered: range-only formatting is not implemented, and advertising
# the capability without a real implementation would mislead users into
# thinking "Format Selection" works. The placeholder handler remains
# in senpy/lsp/handlers/diagnostics.py:range_formatting (returns []) so
# a future implementation can re-register it without re-creating the
# function and its tests.
@server.feature(lsp.TEXT_DOCUMENT_FORMATTING)
def formatting(ls: LanguageServer, params: lsp.DocumentFormattingParams) -> list[lsp.TextEdit]:
    """0.6.0 Sub-sprint 3: delegates to handlers.diagnostics."""
    from senpy.lsp.handlers.diagnostics import formatting as _impl

    return _impl(ls, params)


# =============================================================================
# textDocument/signatureHelp — parameter hints for call/use
# =============================================================================
# When user types `call my_label(` and cursor is inside parens, VS Code shows
# the parameter list from the label's signature.
@server.feature(lsp.TEXT_DOCUMENT_SIGNATURE_HELP)
@_with_analysis_lock
def signature_help(ls: LanguageServer, params: lsp.SignatureHelpParams) -> lsp.SignatureHelp | None:
    """0.6.0 Sub-sprint 3b: delegates to handlers.completion."""
    from senpy.lsp.handlers.completion import signature_help as _impl

    return _impl(ls, params)


# =============================================================================
# textDocument/prepareCallHierarchy + incomingCalls + outgoingCalls
# =============================================================================
# Right-click on label → "Find Callers" (incoming) / "Find References" (outgoing).
# Killer for VN — navigation through call graph.
@server.feature(lsp.TEXT_DOCUMENT_PREPARE_CALL_HIERARCHY)
@_with_analysis_lock
def prepare_call_hierarchy(
    ls: LanguageServer, params: lsp.CallHierarchyPrepareParams
) -> list[lsp.CallHierarchyItem]:
    """0.6.0 Sub-sprint 3b: delegates to handlers.navigation."""
    from senpy.lsp.handlers.navigation import prepare_call_hierarchy as _impl

    return _impl(ls, params)


@server.feature(lsp.CALL_HIERARCHY_INCOMING_CALLS)
@_with_analysis_lock
def incoming_calls(
    ls: LanguageServer, params: lsp.CallHierarchyIncomingCallsParams
) -> list[lsp.CallHierarchyIncomingCall]:
    """0.6.0 Sub-sprint 3b: delegates to handlers.navigation."""
    from senpy.lsp.handlers.navigation import incoming_calls as _impl

    return _impl(ls, params)


@server.feature(lsp.CALL_HIERARCHY_OUTGOING_CALLS)
@_with_analysis_lock
def outgoing_calls(
    ls: LanguageServer, params: lsp.CallHierarchyOutgoingCallsParams
) -> list[lsp.CallHierarchyOutgoingCall]:
    """0.6.0 Sub-sprint 3b: delegates to handlers.navigation."""
    from senpy.lsp.handlers.navigation import outgoing_calls as _impl

    return _impl(ls, params)


def start_lsp():
    # Initialize logging before the LSP I/O loop starts. LSP uses
    # stderr as the JSON-RPC transport — any unsilenced WARNING+ log
    # record would corrupt the protocol. setup_logging(verbose=False)
    # installs a NullHandler on the 'senpy' logger so records are
    # swallowed silently. Idempotent: if main() already called it
    # (e.g. `senpy --lsp` path), this is a no-op that replaces handlers.
    # Defense-in-depth: start_lsp may be called directly by an embedded
    # host without going through main().
    from senpy.core.logging import setup_logging

    setup_logging(verbose=False)
    server.start_io()
