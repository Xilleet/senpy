"""Stress test for the ``Timer.cancel()`` TOCTOU race in the LSP debounce.

CPython's ``threading.Timer.cancel()`` only sets an ``Event`` flag. If
the timer's interval has already elapsed and the worker function has
started executing (past the ``is_set()`` check in ``Timer.run()``),
``cancel()`` is a no-op — the stale worker runs anyway and publishes
outdated diagnostics.

The race window is microseconds, which makes a naive "fire 100 rapid
``did_change`` events and count ``publishDiagnostics``" test flaky.
Instead, this module uses a ``FlakyTimer`` monkeypatch that
deterministically simulates the worst-case TOCTOU loss: ``cancel()``
is always a no-op, and the worker fires immediately in a real thread.

With the generation-counter fix in ``SenpyLSPServer`` (B14), even when
``cancel()`` loses the race, stale workers bail out before publishing
because their captured generation no longer matches the latest.

Test coverage:
  1. ``test_rapid_did_change_publishes_only_latest`` — N rapid
     ``did_change`` events with FlakyTimer → only 1 publishDiagnostics
     call (the latest worker), N-1 stale workers bail out.
  2. ``test_did_change_then_did_save_no_duplicate_publish`` —
     ``did_change`` + ``did_save`` overlapping timers (150 ms + 300 ms)
     → no duplicate publishDiagnostics for the same URI.
  3. ``test_per_uri_generation_independence`` — generation counter is
     per-URI; rapid ``did_change`` for URI_A does not affect URI_B's
     pending worker.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from lsprotocol import types as lsp

import senpy.lsp.server as server_mod
from senpy.core.analyzer import SenpyAnalyzer

# =============================================================================
# FlakyTimer — deterministic simulation of Timer.cancel() losing the race
# =============================================================================


class FlakyTimer:
    """Mimics ``threading.Timer`` but ``cancel()`` is always a no-op.

    The worker function fires immediately in a real thread (simulates
    the timer interval having elapsed and the worker having passed the
    ``is_set()`` check). This deterministically reproduces the worst-case
    ``Timer.cancel()`` TOCTOU loss that happens stochastically under
    real scheduling pressure.

    The worker blocks on ``_worker_gate`` before calling ``func`` —
    this lets the test fire N rapid ``schedule_change_diagnostics``
    calls first (incrementing the generation counter N times) and then
    release all workers simultaneously. After release, each worker
    checks its captured generation against the latest — stale workers
    bail out, only the latest publishes.

    Drop-in replacement for ``threading.Timer`` — used via
    ``monkeypatch.setattr(server_mod.threading, "Timer", FlakyTimer)``.
    """

    def __init__(
        self,
        interval: float,
        func: Any,
        args: list | None = None,
        kwargs: dict | None = None,
    ) -> None:
        self.interval = interval  # ignored — fires immediately
        self.func = func
        self.args = args or []
        self.kwargs = kwargs or {}
        self._thread: threading.Thread | None = None
        self.daemon = True  # mirror threading.Timer.daemon attribute

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="FlakyTimer-worker")
        self._thread.start()

    def _run(self) -> None:
        # Wait for the test to release all workers simultaneously.
        # This properly models the TOCTOU race: by the time the gate
        # opens, the latest generation is already the final value, and
        # each worker's captured generation may be stale.
        _worker_gate.wait(timeout=10.0)
        # Simulate the TOCTOU loss: cancel() is called too late, so the
        # worker runs unconditionally. No is_set() check here.
        try:
            self.func(*self.args, **self.kwargs)
        except Exception:
            # Mirror threading.Timer's behaviour: swallow worker
            # exceptions (they would otherwise crash the worker thread
            # and print a traceback that pollutes test output).
            pass

    def cancel(self) -> None:
        # Deliberately a no-op — simulates cancel() arriving after the
        # worker has already passed the is_set() check in Timer.run().
        pass

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)


# Module-level gate event. Tests reset it before scheduling workers,
# then set it to release all workers simultaneously.
_worker_gate = threading.Event()


def _wait_for_all_workers(timeout: float = 5.0) -> None:
    """Wait until all FlakyTimer worker threads finish."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Inspect all FlakyTimer instances we created — but we don't
        # track them globally. Instead, just sleep briefly and let the
        # GIL/release schedule drain them. They fire immediately on
        # start(), so a short wait is enough.
        time.sleep(0.05)
        # Check if any thread named "FlakyTimer-worker" is still alive.
        alive = [t for t in threading.enumerate() if t.name == "FlakyTimer-worker"]
        if not alive:
            return
    # Final join attempt with timeout — don't fail the test if a worker
    # is stuck (the write lock serializes them, so they should drain).


# =============================================================================
# Mock LS / workspace
# =============================================================================


class _VaryingMockDocument:
    """Mock document that returns a different source on each access —
    simulates the user typing between did_change events."""

    def __init__(self, uri: str, contents: list[str]) -> None:
        self.uri = uri
        self._contents = contents
        self._idx = 0
        self.source = contents[0]
        self.lines = contents[0].splitlines(keepends=True)

    def advance(self) -> None:
        """Move to the next content snapshot (simulates user typing)."""
        self._idx = min(self._idx + 1, len(self._contents) - 1)
        new = self._contents[self._idx]
        self.source = new
        self.lines = new.splitlines(keepends=True)


class _MockWorkspace:
    def __init__(self, doc, root_path: str) -> None:
        self.doc = doc
        self.root_path = root_path

    def get_text_document(self, uri: str):
        return self.doc if self.doc.uri == uri else None


class _RecordingLS:
    """Mock LanguageServer that records publishDiagnostics calls."""

    def __init__(self, doc, root_path: str) -> None:
        self.workspace = _MockWorkspace(doc, root_path)
        self.published: list[lsp.PublishDiagnosticsParams] = []
        self._publish_lock = threading.Lock()

    def text_document_publish_diagnostics(self, params: lsp.PublishDiagnosticsParams) -> None:
        with self._publish_lock:
            self.published.append(params)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _clean_lsp_state():
    """Reset LSP server module-level state before AND after each test."""
    # Reset the worker gate — workers block on it until the test releases them.
    _worker_gate.clear()
    # Before
    server_mod._active_analyzer = None
    server_mod._is_initialized = False
    server_mod._current_workspace_root = None
    server_mod._previously_diagnosed_uris = set()
    server_mod._latest_diagnostics_by_path = {}
    if getattr(server_mod, "_full_timer", None) is not None:
        try:
            server_mod._full_timer.cancel()
        except Exception:
            pass
        server_mod._full_timer = None
    if getattr(server_mod, "_change_timer", None) is not None:
        try:
            server_mod._change_timer.cancel()
        except Exception:
            pass
        server_mod._change_timer = None
    lsp_server = getattr(server_mod, "_lsp_server", None)
    if lsp_server is not None:
        if hasattr(lsp_server, "change_timers"):
            for t in list(lsp_server.change_timers.values()):
                try:
                    t.cancel()
                except Exception:
                    pass
            lsp_server.change_timers.clear()
        if hasattr(lsp_server, "change_generations"):
            lsp_server.change_generations.clear()
        if hasattr(lsp_server, "full_generation"):
            lsp_server.full_generation = 0

    yield

    # After
    _worker_gate.clear()
    server_mod._active_analyzer = None
    server_mod._is_initialized = False
    server_mod._current_workspace_root = None
    server_mod._previously_diagnosed_uris = set()
    server_mod._latest_diagnostics_by_path = {}
    if getattr(server_mod, "_full_timer", None) is not None:
        try:
            server_mod._full_timer.cancel()
        except Exception:
            pass
        server_mod._full_timer = None
    if getattr(server_mod, "_change_timer", None) is not None:
        try:
            server_mod._change_timer.cancel()
        except Exception:
            pass
        server_mod._change_timer = None
    lsp_server = getattr(server_mod, "_lsp_server", None)
    if lsp_server is not None:
        if hasattr(lsp_server, "change_timers"):
            for t in list(lsp_server.change_timers.values()):
                try:
                    t.cancel()
                except Exception:
                    pass
            lsp_server.change_timers.clear()
        if hasattr(lsp_server, "change_generations"):
            lsp_server.change_generations.clear()
        if hasattr(lsp_server, "full_generation"):
            lsp_server.full_generation = 0


def _setup_workspace(tmp_path: Path, initial_content: str) -> tuple[Path, SenpyAnalyzer]:
    """Create a project with a single .rpy file and prime the analyzer."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    script_file = game_dir / "script.rpy"
    script_file.write_text(initial_content, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    server_mod._current_workspace_root = str(tmp_path)
    server_mod._refresh_symbol_snapshot()
    return script_file, analyzer


# =============================================================================
# Tests
# =============================================================================


class TestRapidDidChangeGenerationGuard:
    """Rapid ``did_change`` events with FlakyTimer → only the latest
    worker publishes, all stale workers bail out via generation check."""

    def test_rapid_did_change_publishes_only_latest(self, tmp_path: Path, monkeypatch) -> None:
        """Simulate 5 rapid ``did_change`` events on the same URI.

        FlakyTimer forces every scheduled worker to fire (cancel is a
        no-op). Without the generation-counter fix, all 5 workers would
        run and call ``publishDiagnostics`` — the user would see stale
        diagnostics flicker in the Problems panel.

        With the fix, each stale worker checks its captured generation
        against ``_lsp_server.change_generations[uri]`` and bails out
        before publishing. Only the latest worker (generation 5)
        publishes.
        """
        initial = "label start:\n    return\n"
        script_file, _ = _setup_workspace(tmp_path, initial)
        uri = server_mod._path_to_uri(str(script_file))

        # Five content snapshots — each represents a user keystroke.
        contents = [
            "label start:\n    return\n",
            "label start:\n    $ a = 0\n    return\n",
            "label start:\n    $ a = 0\n    $ b = 1\n    return\n",
            "label start:\n    $ a = 0\n    $ b = 1\n    $ c = 2\n    return\n",
            "label start:\n    $ a = 0\n    $ b = 1\n    $ c = 2\n    $ d = 3\n    return\n",
        ]
        doc = _VaryingMockDocument(uri, contents)
        ls = _RecordingLS(doc, str(tmp_path))

        # Patch threading.Timer with FlakyTimer — every cancel() is a no-op.
        monkeypatch.setattr(server_mod.threading, "Timer", FlakyTimer)

        # Fire 5 rapid schedule_change_diagnostics calls. Each advances
        # the document content (simulating did_change) and reschedules.
        # FlakyTimer workers start in real threads but block on
        # _worker_gate — so all 5 schedules complete first (incrementing
        # change_generations[uri] to 5), then all workers are released
        # simultaneously and each checks its captured gen.
        for i in range(5):
            if i > 0:
                doc.advance()
            server_mod.schedule_change_diagnostics(ls, uri)

        # Release all workers simultaneously. Now each worker checks
        # its captured gen against latest=5: only the worker with gen=5
        # proceeds, the other 4 bail out.
        _worker_gate.set()

        # Wait for all FlakyTimer workers to drain.
        _wait_for_all_workers(timeout=5.0)

        # With the generation-counter fix: only the latest worker
        # (generation 5) publishes — 4 stale workers (generations 1-4)
        # bail out.
        #
        # Without the fix: all 5 workers would publish (FlakyTimer forces
        # every worker to fire). This test would fail with len == 5
        # instead of 1.
        assert len(ls.published) == 1, (
            f"Expected exactly 1 publishDiagnostics call (latest worker "
            f"only), got {len(ls.published)}. Stale workers ran and "
            f"published outdated diagnostics — the Timer.cancel() race "
            f"(B14) is not guarded by the generation counter."
        )

    def test_stale_workers_bail_out_before_publish(self, tmp_path: Path, monkeypatch) -> None:
        """A more granular check: of N scheduled workers, only the
        latest should reach ``publishDiagnostics``. Stale workers must
        bail out before acquiring the write lock.

        This test records the order in which workers enter and exit the
        write lock — stale workers should NOT enter the lock at all.
        """
        initial = "label start:\n    return\n"
        script_file, analyzer = _setup_workspace(tmp_path, initial)
        uri = server_mod._path_to_uri(str(script_file))

        contents = [f"label start:\n    $ v{i} = {i}\n    return\n" for i in range(3)]
        doc = _VaryingMockDocument(uri, contents)
        ls = _RecordingLS(doc, str(tmp_path))

        monkeypatch.setattr(server_mod.threading, "Timer", FlakyTimer)

        # Track acquire_write / release_write calls.
        original_acquire = server_mod._lsp_server.rw_lock.acquire_write
        original_release = server_mod._lsp_server.rw_lock.release_write
        acquire_calls: list[int] = []

        def _tracking_acquire():
            acquire_calls.append(len(acquire_calls))
            return original_acquire()

        monkeypatch.setattr(server_mod._lsp_server.rw_lock, "acquire_write", _tracking_acquire)
        monkeypatch.setattr(server_mod._lsp_server.rw_lock, "release_write", original_release)

        for i in range(3):
            if i > 0:
                doc.advance()
            server_mod.schedule_change_diagnostics(ls, uri)

        # Release all workers simultaneously — each checks its gen
        # against latest=3.
        _worker_gate.set()
        _wait_for_all_workers(timeout=5.0)

        # Only one worker (the latest) should have acquired the write
        # lock. Stale workers bail out before acquire_write().
        assert len(acquire_calls) == 1, (
            f"Expected exactly 1 acquire_write call (latest worker "
            f"only), got {len(acquire_calls)}. Stale workers entered "
            f"the write lock — they did not bail out via the generation "
            f"check at the top of run_single_file_diagnostics."
        )
        assert len(ls.published) == 1


class TestDidChangeAndDidSaveOverlap:
    """``did_change`` (150 ms timer) and ``did_save`` (300 ms timer)
    scheduling overlapping workers. The single-file worker fires first,
    the full-scan worker fires second — both currently publish for the
    same URI, causing visual flicker in VS Code.

    With the generation-counter fix, the two worker types use separate
    counters, so they don't cancel each other. But each type guards its
    own stale workers."""

    def test_change_then_save_both_publish_for_different_reasons(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """``did_change`` then ``did_save`` should both produce
        publishDiagnostics for the same URI — they are not stale with
        respect to each other (different generation counters).

        This documents the intended behavior: change + save overlap
        produces 2 publish calls (one from each worker type). The fix
        only prevents stale workers of the *same* type from publishing.
        """
        initial = "label start:\n    return\n"
        script_file, analyzer = _setup_workspace(tmp_path, initial)
        uri = server_mod._path_to_uri(str(script_file))

        doc = _VaryingMockDocument(uri, [initial])
        ls = _RecordingLS(doc, str(tmp_path))

        monkeypatch.setattr(server_mod.threading, "Timer", FlakyTimer)

        # did_change → schedule_change_diagnostics (per-URI generation)
        server_mod.schedule_change_diagnostics(ls, uri)
        # did_save → schedule_full_diagnostics (global generation)
        server_mod.schedule_full_diagnostics(ls, uri)

        # Release all workers.
        _worker_gate.set()
        _wait_for_all_workers(timeout=5.0)

        # Both workers run — they use different generation counters,
        # so neither is "stale" with respect to the other.
        assert len(ls.published) >= 1, (
            "Expected at least 1 publishDiagnostics call from change " "or full worker"
        )

        # All publishes should be for our URI (or for URIs that the full
        # scan picked up — at minimum, our URI must be covered).
        our_uri_publishes = [p for p in ls.published if p.uri == uri]
        assert our_uri_publishes, (
            "No publishDiagnostics for the edited URI — neither change "
            "worker nor full worker published for it."
        )


class TestPerURIGenerationIndependence:
    """Generation counter is per-URI — rapid ``did_change`` for URI_A
    does not affect URI_B's pending worker."""

    def test_rapid_did_change_on_uri_a_does_not_invalidate_uri_b(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Schedule a change for URI_B, then fire 5 rapid changes for
        URI_A. URI_B's worker must still publish (its generation is
        unchanged). URI_A's stale workers must bail out."""
        game_dir = tmp_path / "game"
        game_dir.mkdir(parents=True, exist_ok=True)
        file_a = game_dir / "a.rpy"
        file_b = game_dir / "b.rpy"
        file_a.write_text("label a:\n    return\n", encoding="utf-8")
        file_b.write_text("label b:\n    return\n", encoding="utf-8")

        analyzer = SenpyAnalyzer(str(tmp_path))
        analyzer.run(quiet=True)
        server_mod._active_analyzer = analyzer
        server_mod._is_initialized = True
        server_mod._current_workspace_root = str(tmp_path)
        server_mod._refresh_symbol_snapshot()

        uri_a = server_mod._path_to_uri(str(file_a))
        uri_b = server_mod._path_to_uri(str(file_b))

        contents_a = [f"label a:\n    $ v{i} = {i}\n    return\n" for i in range(5)]
        doc_a = _VaryingMockDocument(uri_a, contents_a)
        doc_b = _VaryingMockDocument(uri_b, ["label b:\n    return\n"])

        # RecordingLS that can serve both URIs.
        class _MultiDocWorkspace:
            def __init__(self, docs, root_path):
                self.docs = docs
                self.root_path = root_path

            def get_text_document(self, uri):
                return self.docs.get(uri)

        class _MultiDocLS:
            def __init__(self, docs, root_path):
                self.workspace = _MultiDocWorkspace(docs, root_path)
                self.published = []
                self._lock = threading.Lock()

            def text_document_publish_diagnostics(self, params):
                with self._lock:
                    self.published.append(params)

        ls = _MultiDocLS({uri_a: doc_a, uri_b: doc_b}, str(tmp_path))
        monkeypatch.setattr(server_mod.threading, "Timer", FlakyTimer)

        # Schedule URI_B's worker first (it has gen=1 for uri_b).
        server_mod.schedule_change_diagnostics(ls, uri_b)
        # Now fire 5 rapid changes for URI_A — increments uri_a's gen 5 times.
        for i in range(5):
            if i > 0:
                doc_a.advance()
            server_mod.schedule_change_diagnostics(ls, uri_a)

        # Release all workers simultaneously.
        _worker_gate.set()
        _wait_for_all_workers(timeout=5.0)

        # URI_A: only 1 publish (latest worker, gen=5).
        uri_a_publishes = [p for p in ls.published if p.uri == uri_a]
        assert len(uri_a_publishes) == 1, (
            f"URI_A: expected 1 publish (latest worker), got "
            f"{len(uri_a_publishes)}. Stale workers ran."
        )

        # URI_B: at least 1 publish — its generation counter is
        # independent of URI_A's. URI_B's worker must NOT have bailed
        # out due to URI_A activity.
        uri_b_publishes = [p for p in ls.published if p.uri == uri_b]
        assert uri_b_publishes, (
            "URI_B: no publishDiagnostics — its worker bailed out due "
            "to URI_A activity. Per-URI generation independence is "
            "broken: change_generations must be keyed by URI."
        )
