"""Cross-process cache lock tests (R-P0-8).

Validates that CacheManager acquires and releases a file-based lock
(``cache.lock``) around ``load_manifest`` and ``save_manifest`` to
prevent concurrent writes from different processes (pre-commit hook +
LSP server running simultaneously).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from senpy.core.cache import _HAS_FCNTL, _HAS_MSVCRT, CacheManager, CacheManifest
from senpy.core.constants import SENPY_VERSION


@pytest.fixture
def cache_dir(tmp_path: Path) -> str:
    """Create a temp cache directory."""
    d = str(tmp_path / ".senpy_cache")
    os.makedirs(d, exist_ok=True)
    return d


@pytest.fixture
def cache_manager(cache_dir: str) -> CacheManager:
    """Create a CacheManager with a temp cache dir."""
    return CacheManager(project_path=cache_dir, enabled=True, cache_dir=cache_dir)


class TestCacheLock:
    """R-P0-8: cross-process cache lock."""

    def test_lock_file_created_after_save(self, cache_manager: CacheManager, cache_dir: str):
        """save_manifest() must create a cache.lock file."""
        manifest = CacheManifest(version="test", global_symbol_hash="abc")
        cache_manager.save_manifest(manifest)
        assert os.path.exists(
            os.path.join(cache_dir, "cache.lock")
        ), "cache.lock should exist after save_manifest"

    def test_acquire_and_release_lock(self, cache_manager: CacheManager):
        """_acquire_lock() returns a non-None handle, _release_lock() cleans up."""
        handle = cache_manager._acquire_lock()
        assert handle is not None, "Lock should be acquired when no contention"
        cache_manager._release_lock(handle)
        # After release, a new acquire should succeed
        handle2 = cache_manager._acquire_lock()
        assert handle2 is not None
        cache_manager._release_lock(handle2)

    def test_second_acquire_blocks_then_succeeds(self, cache_manager: CacheManager):
        """When lock is held, a second acquire from a different thread
        should either block and then succeed (after release) or return
        None (if timeout is very short). We test the blocking path by
        holding the lock briefly in one thread and acquiring in another."""
        if not (_HAS_FCNTL or _HAS_MSVCRT):
            pytest.skip("No file locking primitive on this platform")

        handle = cache_manager._acquire_lock()
        assert handle is not None

        # Spawn a thread that tries to acquire the lock.
        # It should block until we release.
        acquired_in_thread = threading.Event()

        def _try_acquire():
            h = cache_manager._acquire_lock()
            if h is not None:
                acquired_in_thread.set()
                cache_manager._release_lock(h)

        t = threading.Thread(target=_try_acquire)
        t.start()

        # Give the thread a moment to attempt (it should be blocked).
        acquired_in_thread.wait(timeout=0.3)
        assert not acquired_in_thread.is_set(), "Second acquire should block while lock is held"

        # Release the lock — thread should now acquire it.
        cache_manager._release_lock(handle)
        acquired_in_thread.wait(timeout=2.0)
        assert acquired_in_thread.is_set(), "Second acquire should succeed after release"
        t.join(timeout=2.0)

    def test_save_then_load_with_lock(self, cache_manager: CacheManager):
        """save_manifest + load_manifest should work end-to-end with locking."""
        manifest = CacheManifest(version=SENPY_VERSION, global_symbol_hash="deadbeef")
        cache_manager.save_manifest(manifest)

        # Load should return the same manifest (version matches).
        loaded = cache_manager.load_manifest()
        assert loaded is not None
        assert loaded.global_symbol_hash == "deadbeef"

    def test_lock_released_after_save(self, cache_manager: CacheManager):
        """After save_manifest() completes, the lock should be released
        (a subsequent acquire should succeed immediately)."""
        manifest = CacheManifest(version="test", global_symbol_hash="xyz")
        cache_manager.save_manifest(manifest)

        # Should acquire immediately — no contention.
        handle = cache_manager._acquire_lock()
        assert handle is not None, "Lock should be free after save_manifest"
        cache_manager._release_lock(handle)

    def test_lock_released_after_load(self, cache_manager: CacheManager):
        """After load_manifest() completes, the lock should be released."""
        manifest = CacheManifest(version="test", global_symbol_hash="loadtest")
        cache_manager.save_manifest(manifest)
        cache_manager.load_manifest()

        handle = cache_manager._acquire_lock()
        assert handle is not None, "Lock should be free after load_manifest"
        cache_manager._release_lock(handle)

    def test_lock_released_on_save_error(self, cache_manager: CacheManager, tmp_path: Path):
        """If save_manifest() raises an exception, the lock should still
        be released (no deadlock)."""
        # Corrupt the cache dir so save fails (make it read-only after
        # ensure_cache_dir already ran for lock creation).
        # Actually, save_manifest catches OSError silently. Let's test
        # by making the manifest_path point to an invalid location.
        cache_manager.manifest_path = "/nonexistent/path/cache.pkl"

        manifest = CacheManifest(version="test", global_symbol_hash="err")
        # Should not raise — save_manifest catches OSError.
        cache_manager.save_manifest(manifest)

        # Lock should be released despite the error.
        handle = cache_manager._acquire_lock()
        assert handle is not None, "Lock should be released even after save error"
        cache_manager._release_lock(handle)

    def test_disabled_cache_skips_lock(self, tmp_path: Path):
        """When cache is disabled, no lock should be acquired."""
        cm = CacheManager(
            project_path=str(tmp_path),
            enabled=False,
            cache_dir=str(tmp_path / ".senpy_cache"),
        )
        handle = cm._acquire_lock()
        assert handle is None, "Disabled cache should not acquire a lock"

    def test_lock_file_path(self, cache_manager: CacheManager, cache_dir: str):
        """_lock_path should be cache_dir/cache.lock."""
        expected = os.path.join(cache_dir, "cache.lock")
        assert cache_manager._lock_path == expected
