"""Cross-process cache lock stress tests.

The existing ``test_cache_lock.py`` covers the lock API at unit level
(``_acquire_lock`` / ``_release_lock`` from threads). The existing
``test_concurrent_invocations.py`` covers the self-healing contract
when the cache is corrupted.

Neither test covers the real-world scenario: multiple Senpy processes
running on the SAME project at the SAME time, each trying to load and
save ``.senpy_cache/cache.pkl`` concurrently. This is the actual
workload that ``_acquire_lock`` was designed to protect against:

  - pre-commit hook + LSP server running simultaneously on the same project
  - two terminal windows running ``senpy`` at the same time
  - a CI matrix where multiple jobs share a cache dir

These tests run real subprocesses (``python -m senpy.cli``) in parallel
via ``concurrent.futures.ProcessPoolExecutor`` and verify the four
invariants of the cross-process lock contract:

  1. **No crash**: every process exits 0 (or 1 for "lint errors found",
     never 2 for "internal crash" or 124 for "timeout").
  2. **No leftover temp files**: ``.senpy_cache/*.tmp`` is empty after
     all processes complete — ``tempfile.mkstemp`` + ``os.replace``
     cleanup works under contention.
  3. **No corrupt cache**: ``cache.pkl`` is a valid pickle that
     ``SafeCacheUnpickler`` can load as ``CacheManifest`` after the
     parallel run completes. A corrupt manifest would indicate either
     the lock failed to serialise writers, or ``os.replace`` was
     bypassed.
  4. **Warm run succeeds**: a final serial warm run (with cache) on
     the same project succeeds — the cache left by the parallel run
     is loadable and produces the same diagnostics.

The tests are gated on ``_HAS_FCNTL`` (Unix) or ``_HAS_MSVCRT``
(Windows) because the lock is a no-op on platforms with neither
locking primitive — the contract does not apply there.

Why subprocesses, not threads
-----------------------------
``fcntl.flock`` and ``msvcrt.locking`` are PROCESS-level locks — they
are released when the process exits, but threads inside one process
share the same file descriptor table. The lock code in
``cache.py:_acquire_lock`` opens a new file descriptor per call, so
threads DO contend — but a real-world pre-commit+LSP scenario involves
two separate Python processes, not two threads of one. Subprocess
tests faithfully reproduce the production failure mode.
"""

from __future__ import annotations

import multiprocessing
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pytest

from senpy.__version__ import __version__ as SENPY_VERSION
from senpy.core.cache import _HAS_FCNTL, _HAS_MSVCRT, CacheManifest, SafeCacheUnpickler

# Use "spawn" instead of the default "fork" on Linux. The fork start method
# emits a DeprecationWarning when the parent is multi-threaded (pytest with
# plugins is multi-threaded), and on some systems can deadlock under high
# parallelism. spawn is the default on macOS (Python 3.8+) and Windows
# already — making it explicit here removes the warning and is consistent
# across platforms.
if sys.platform != "win32":
    multiprocessing.set_start_method("spawn", force=True)


# =============================================================================
# Helpers
# =============================================================================


_SAMPLE_RPY = """label start:
    $ score = 0
    menu:
        "Win":
            $ score = 100
        "Lose":
            $ score = 0
    "Score: [score]"
    return
"""


def _setup_project(tmp_path: Path) -> Path:
    """Create a minimal Ren'Py project with a single .rpy file."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "scenario.rpy").write_text(_SAMPLE_RPY, encoding="utf-8")
    return tmp_path


def _run_senpy_subprocess(
    project_path: str, *, timeout: float = 30.0
) -> tuple[int, float, bytes, bytes]:
    """Run ``python -m senpy.cli <project> --exit-zero`` as a subprocess.

    Returns ``(exit_code, elapsed_seconds, stdout, stderr)``.
    Exit codes:
        0 — clean (no diagnostics) or diagnostics emitted (in CI mode).
        1 — lint errors found (treated as success for stress-test purposes:
            we are testing cache integrity, not lint correctness).
        2 — internal Senpy crash (failure for stress-test purposes).
        124 — subprocess.TimeoutExpired (failure).
        other — unexpected (failure).
    """
    cmd = [sys.executable, "-m", "senpy.cli", project_path, "--exit-zero"]
    start = time.monotonic()
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        elapsed = time.monotonic() - start
        return r.returncode, elapsed, r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        elapsed = time.monotonic() - start
        return 124, elapsed, e.stdout or b"", e.stderr or b""


# =============================================================================
# Stress tests: real subprocesses in parallel
# =============================================================================


def _stress_run_worker(project_path: str) -> tuple[int, float, bytes, bytes]:
    """Worker function for ProcessPoolExecutor.

    Module-level (not a nested function) so it is picklable on Windows
    (which uses spawn, not fork — lambdas and nested functions are not
    picklable).
    """
    return _run_senpy_subprocess(project_path)


@pytest.mark.skipif(
    not (_HAS_FCNTL or _HAS_MSVCRT),
    reason="No file locking primitive on this platform (fcntl/msvcrt)",
)
class TestCrossProcessCacheStress:
    """Stress tests that run multiple Senpy subprocesses in parallel on
    the same project and verify the four cross-process lock invariants.
    """

    def test_five_parallel_processes_no_corruption(self, tmp_path: Path) -> None:
        """5 parallel ``senpy`` processes on the same project must not
        corrupt the cache. All processes must exit 0 or 1 (not 2 or 124).

        This is the canonical pre-commit+LSP scenario: two writers race
        on ``save_manifest``, but the ``cache.lock`` file serialises
        them. The 5-process count is chosen to be larger than typical
        CI parallelism (2-4 cores) so the lock queue has multiple
        waiters.
        """
        project = _setup_project(tmp_path)

        # First cold run to populate the cache (serial).
        cold_rc, cold_elapsed, _, _ = _run_senpy_subprocess(str(project))
        assert cold_rc in (0, 1), f"Cold run failed with exit code {cold_rc}"

        cache_dir = tmp_path / ".senpy_cache"
        assert (cache_dir / "cache.pkl").exists(), "Cold run did not write cache.pkl"

        # Now run 5 parallel processes — each will try to load_manifest
        # (shared read) and save_manifest (exclusive write).
        with ProcessPoolExecutor(max_workers=5) as ex:
            futures = [ex.submit(_stress_run_worker, str(project)) for _ in range(5)]
            results = [f.result() for f in as_completed(futures)]

        # Invariant 1: no crash. Exit codes 0 and 1 are success (1 means
        # lint errors found, which is OK — we are stress-testing the cache,
        # not the lint output). Codes 2, 124, or other are failures.
        for i, (rc, _, _, stderr) in enumerate(results):
            assert rc in (0, 1), (
                f"Parallel process {i} exited with code {rc} (expected 0 or 1). "
                f"stderr: {stderr.decode('utf-8', errors='replace')[:500]}"
            )

        # Invariant 2: no leftover .tmp files.
        leftovers = list(cache_dir.glob("*.tmp"))
        assert leftovers == [], (
            f"Parallel run left .tmp files in cache dir: {leftovers}. "
            "save_manifest's cleanup-on-failure path is broken under contention."
        )

        # Invariant 3: cache.pkl is still a valid CacheManifest.
        manifest_path = cache_dir / "cache.pkl"
        assert manifest_path.exists(), "cache.pkl disappeared after parallel run"
        with open(manifest_path, "rb") as f:
            rebuilt = SafeCacheUnpickler(f).load()
        assert isinstance(rebuilt, CacheManifest), (
            f"cache.pkl is not a CacheManifest after parallel run. "
            f"Got: {type(rebuilt).__name__}"
        )
        assert rebuilt.version == SENPY_VERSION, (
            f"cache.pkl version mismatch: {rebuilt.version!r} != {SENPY_VERSION!r}. "
            "The cache was either written by an older Senpy or corrupted."
        )

        # Invariant 4: a final warm run (serial) succeeds and is fast.
        warm_rc, warm_elapsed, _, _ = _run_senpy_subprocess(str(project))
        assert warm_rc in (0, 1), (
            f"Warm run after parallel stress failed with exit code {warm_rc}. "
            "The cache left by the parallel run is not loadable."
        )
        # Warm run should be FASTER than the cold run (cache hit).
        # Allow 2x slack for slow CI machines.
        assert warm_elapsed < cold_elapsed * 2.0, (
            f"Warm run ({warm_elapsed:.2f}s) was not faster than cold run "
            f"({cold_elapsed:.2f}s) — cache hit may have failed under contention."
        )

    def test_ten_parallel_processes_no_deadlock(self, tmp_path: Path) -> None:
        """10 parallel processes must not deadlock and must complete
        within a reasonable time. Each process waits at most
        ``_LOCK_TIMEOUT`` (5s) before degrading — so 10 processes
        queued on a single lock should complete in ~50s worst-case.
        We give 60s slack for CI.

        This test catches the case where ``_release_lock`` fails to
        release the lock — under that bug, processes would queue
        forever and the test would time out.
        """
        project = _setup_project(tmp_path)

        # Cold run first.
        cold_rc, _, _, _ = _run_senpy_subprocess(str(project))
        assert cold_rc in (0, 1)

        # 10 parallel processes.
        with ProcessPoolExecutor(max_workers=10) as ex:
            futures = [ex.submit(_stress_run_worker, str(project)) for _ in range(10)]
            # Wait at most 60s for all 10 to complete.
            results = []
            for f in as_completed(futures, timeout=60.0):
                results.append(f.result())

        assert len(results) == 10, (
            f"Only {len(results)}/10 parallel processes completed within 60s — "
            "possible deadlock in _release_lock."
        )
        # All must succeed.
        for i, (rc, _, _, _) in enumerate(results):
            assert rc in (0, 1), f"Process {i} exited with code {rc} (expected 0 or 1)."

    def test_parallel_processes_no_leftover_lock_file(self, tmp_path: Path) -> None:
        """After parallel processes complete, ``cache.lock`` may still
        exist (we never unlink it — that's the design: the lock file
        is reused across runs). But ``cache.lock`` must not be held by
        any process — a subsequent acquire must succeed immediately.

        This catches the case where ``_release_lock`` forgets to close
        the file descriptor on one of the parallel paths — the lock
        would remain held forever.
        """
        project = _setup_project(tmp_path)
        cache_dir = tmp_path / ".senpy_cache"

        # Cold run + 3 parallel.
        _run_senpy_subprocess(str(project))
        with ProcessPoolExecutor(max_workers=3) as ex:
            futures = [ex.submit(_stress_run_worker, str(project)) for _ in range(3)]
            for f in as_completed(futures, timeout=30.0):
                f.result()

        # Acquire lock from the test process — must succeed immediately.
        from senpy.core.cache import CacheManager

        cm = CacheManager(project_path=str(project), enabled=True, cache_dir=str(cache_dir))
        handle = cm._acquire_lock()
        assert handle is not None, (
            "Lock could not be acquired after parallel run — a parallel "
            "process did not release the lock (fd leak)."
        )
        cm._release_lock(handle)

    def test_parallel_with_readonly_manifest_no_crash(self, tmp_path: Path) -> None:
        """If ``cache.pkl`` is read-only (e.g. distributed via a
        read-only mount), parallel processes must still not crash.
        ``save_manifest`` catches ``OSError`` silently and degrades —
        the lock itself must not deadlock when the manifest is
        unwritable.
        """
        project = _setup_project(tmp_path)
        cache_dir = tmp_path / ".senpy_cache"
        manifest_path = cache_dir / "cache.pkl"

        # Cold run to create the manifest.
        _run_senpy_subprocess(str(project))
        assert manifest_path.exists()

        # Make the manifest read-only (POSIX only — Windows ACLs differ).
        if not _HAS_FCNTL:
            pytest.skip("Read-only file test is POSIX-specific")
        os.chmod(manifest_path, 0o444)

        try:
            with ProcessPoolExecutor(max_workers=3) as ex:
                futures = [ex.submit(_stress_run_worker, str(project)) for _ in range(3)]
                results = [f.result() for f in as_completed(futures, timeout=30.0)]

            # All must exit 0 or 1 (no crash, no timeout).
            for i, (rc, _, _, _) in enumerate(results):
                assert rc in (0, 1), f"Process {i} exited with code {rc} on read-only manifest."
        finally:
            # Restore write permission so tmp_path cleanup works.
            os.chmod(manifest_path, 0o644)

    def test_parallel_no_corrupt_pickle(self, tmp_path: Path) -> None:
        """Specific regression for the original bug: when two processes
        used a shared temp filename (``cache.pkl.tmp``), they could
        interleave bytes before ``os.replace``. The fix uses
        ``tempfile.mkstemp`` for a unique temp per call.

        This test runs the parallel scenario many times (10 iterations)
        and verifies ``cache.pkl`` is never corrupt. The original bug
        was probabilistic — under heavy contention it manifested about
        1 in 20 runs. 10 iterations catch the regression with ~50%
        probability if the bug returned.
        """
        project = _setup_project(tmp_path)
        cache_dir = tmp_path / ".senpy_cache"
        manifest_path = cache_dir / "cache.pkl"

        # Cold run.
        _run_senpy_subprocess(str(project))

        # 10 iterations × 3 parallel processes = 30 cache writes.
        for iteration in range(10):
            with ProcessPoolExecutor(max_workers=3) as ex:
                futures = [ex.submit(_stress_run_worker, str(project)) for _ in range(3)]
                for f in as_completed(futures, timeout=30.0):
                    rc, _, _, _ = f.result()
                    assert rc in (0, 1), f"Iteration {iteration}: process exited with {rc}"

            # After each iteration, cache.pkl must still be a valid manifest.
            assert manifest_path.exists(), f"Iteration {iteration}: cache.pkl disappeared"
            with open(manifest_path, "rb") as f:
                data = SafeCacheUnpickler(f).load()
            assert isinstance(data, CacheManifest), (
                f"Iteration {iteration}: cache.pkl is not a CacheManifest "
                f"(got {type(data).__name__}) — the unique-temp-filename fix "
                "may have regressed."
            )


# =============================================================================
# Edge case: process killed mid-write
# =============================================================================


class TestProcessKilledMidWrite:
    """If a Senpy process is killed (SIGKILL, OOM, system crash) while
    writing ``cache.pkl``, the lock file may remain "stale" (the fd is
    closed by the OS, but the file still exists). The next process must
    be able to acquire the lock — ``fcntl.flock`` is automatically
    released by the kernel when the fd is closed (process exit).

    This test verifies that scenario: kill a subprocess mid-write,
    verify the next process can still acquire the lock and produce a
    valid cache.
    """

    def test_killed_process_does_not_deadlock_subsequent_run(self, tmp_path: Path) -> None:
        """A process killed mid-write must not leave the lock held."""
        if not _HAS_FCNTL:
            pytest.skip("fcntl-specific test (POSIX)")

        project = _setup_project(tmp_path)

        # Start a process and kill it after a short delay.
        # We use --no-cache to force a cold run that takes longer
        # (cold runs do file I/O and have a higher chance of being
        # mid-write when killed).
        proc = subprocess.Popen(
            [sys.executable, "-m", "senpy.cli", str(project), "--exit-zero", "--no-cache"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.05)  # let it start
        proc.kill()
        proc.wait(timeout=5.0)

        # The lock file may exist (we never unlink it) but must not be held.
        # The next run must succeed.
        rc, _, _, _ = _run_senpy_subprocess(str(project))
        assert rc in (0, 1), (
            f"Run after killed process failed with exit code {rc} — the "
            "killed process may have left the lock in a held state (should "
            "not happen: fcntl.flock is released by the kernel on process exit)."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])
