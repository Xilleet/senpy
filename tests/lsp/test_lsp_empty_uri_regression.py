"""Regression test: empty trigger_uri must not crash run_full_project_diagnostics.

Bug: when the `initialized` handler (workspace.py) called
``schedule_full_diagnostics(ls, "")`` with an empty trigger_uri,
``run_full_project_diagnostics`` immediately called ``_uri_to_path("")``
which raised ``SecurityError("unsupported URI scheme ''; only 'file:' is
allowed")``. The exception propagated up the daemon thread, crashing
Thread-1 and leaving the LSP server without full-project diagnostics.

Symptom in the VS Code Output panel:

    Exception in thread Thread-1:
    ...
      File "senpy/lsp/server.py", line 345, in run_full_project_diagnostics
        file_path = _uri_to_path(trigger_uri)
      File "senpy/lsp/server.py", line 56, in _uri_to_path
        raise SecurityError(
    senpy.core.exceptions.SecurityError: _uri_to_path: unsupported URI
    scheme ''; only 'file:' is allowed (uri='')

Fix: in ``run_full_project_diagnostics``, when ``trigger_uri`` is empty,
fall back to the workspace root path (``ls.workspace.root_path``). If
that's also missing, log a debug message and return silently — there is
nothing to scan.

This test verifies both the empty-URI-with-workspace case and the
empty-URI-without-workspace case (defensive: should not crash either way).
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

import senpy.lsp.server as server_mod
from tests._helpers.lsp import setup_test_workspace


class TestEmptyTriggerUriNoCrash:
    """run_full_project_diagnostics must not crash on empty trigger_uri."""

    def test_empty_uri_with_workspace_root_scans_silently(self, tmp_path: Path):
        """Empty trigger_uri + valid workspace root → scan runs without exception.

        This is the `initialized` handler case: it calls
        ``schedule_full_diagnostics(ls, "")`` to trigger a workspace-wide
        scan with no specific file. The fix uses ``ls.workspace.root_path``
        as the project root in this case.
        """
        setup_test_workspace(tmp_path)
        mock_ls = MagicMock()
        mock_ls.workspace.root_path = str(tmp_path)

        # Reset analyzer state so the scan actually runs.
        server_mod._active_analyzer = None
        server_mod._current_workspace_root = None
        server_mod._is_initialized = False

        # Must not raise. The scan runs synchronously in this thread.
        server_mod.run_full_project_diagnostics(mock_ls, "")

        # The scan should have initialized the analyzer.
        assert server_mod._active_analyzer is not None
        assert server_mod._is_initialized is True

    def test_empty_uri_without_workspace_root_returns_silently(self, tmp_path: Path):
        """Empty trigger_uri + missing workspace root → log debug + return, no crash.

        Defensive case: workspace.root_path raises AttributeError or returns
        None. We must not propagate SecurityError — just log and bail.
        """
        setup_test_workspace(tmp_path)
        mock_ls = MagicMock()
        # Force AttributeError on .root_path access.
        del mock_ls.workspace.root_path

        server_mod._active_analyzer = None
        server_mod._is_initialized = False

        # Must not raise.
        server_mod.run_full_project_diagnostics(mock_ls, "")

        # Analyzer should NOT be initialized (we bailed early).
        assert server_mod._active_analyzer is None
        assert server_mod._is_initialized is False

    def test_initialized_handler_with_empty_uri_does_not_crash_thread(self, tmp_path: Path):
        """End-to-end: the `initialized` handler schedules a debounced scan
        with empty URI; the scan runs in a daemon thread; the thread must
        not crash with SecurityError.

        This is the regression test for the actual user-visible symptom
        (Thread-1 crash in VS Code Output).
        """
        from lsprotocol import types as lsp

        from senpy.lsp.handlers.workspace import initialized

        setup_test_workspace(tmp_path)
        mock_ls = MagicMock()
        mock_ls.workspace.root_path = str(tmp_path)

        # Reset state.
        server_mod._active_analyzer = None
        server_mod._current_workspace_root = None
        server_mod._is_initialized = False
        server_mod._full_timer = None

        # Trigger the initialized handler — schedules a debounced scan
        # with empty URI (this is the bug repro).
        initialized(mock_ls, lsp.InitializedParams())

        # Wait for the debounce timer to fire (0.3s) plus a margin.
        # The daemon thread should complete without crashing.
        if server_mod._full_timer is not None:
            # Replace the timer's target with a synchronous call so we
            # can observe exceptions directly. The original bug was that
            # the exception went uncaught in the daemon thread.
            timer = server_mod._full_timer
            timer.cancel()  # don't let the original timer fire

            # Run the target function directly in this thread — if the
            # bug is present, this raises SecurityError.
            try:
                timer.function(*timer.args, **timer.kwargs)
            except Exception as exc:
                # Cleanup before failing.
                server_mod._full_timer = None
                raise AssertionError(
                    f"run_full_project_diagnostics crashed on empty trigger_uri: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc

        # Cleanup.
        if server_mod._full_timer is not None:
            server_mod._full_timer.cancel()
            server_mod._full_timer = None
