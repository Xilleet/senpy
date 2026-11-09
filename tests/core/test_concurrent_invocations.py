"""Characterization tests for concurrent Senpy invocations on the same project.

When two Senpy processes run on the same project at the same time (e.g. two
CI jobs, two terminal windows, or an IDE plus a CLI), both may write to the
shared ``.senpy_cache/cache.pkl`` and ``~/.senpy/trusted_plugins.json``.

Historically both writers used a fixed temp filename (``cache.pkl.tmp`` /
``trusted_plugins.json.tmp``). ``os.replace`` is atomic, but the
``open(tmp_path, "wb")`` + ``pickle.dump`` phase was NOT — two writers
sharing the same temp inode could interleave bytes, producing a corrupt
pickle that the next ``load_manifest`` would have to discard (self-healing,
but at the cost of a one-time cold-cache run).

The current implementation uses ``tempfile.mkstemp`` for a unique temp
filename per call, so concurrent writers cannot clobber each other's temp
file. These tests characterize three properties:

  1. **Self-healing contract**: a corrupt cache manifest or trust store
     must not crash the analyzer / plugin loader; the next run rebuilds
     from scratch.

  2. **Unique temp filename**: each save call uses its own temp file, so
     the old shared-tmp-path race is structurally impossible.

  3. **Cleanup on failure**: if ``os.replace`` fails (e.g. permission
     denied, disk full), the temp file is removed — no garbage accumulates
     in ``.senpy_cache``.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from senpy.__version__ import __version__ as SENPY_VERSION
from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.cache import CacheManifest, SafeCacheUnpickler

# =============================================================================
# Helpers
# =============================================================================


def _setup_project(tmp_path: Path, rpy_content: str) -> Path:
    """Create a minimal Ren'Py project with a single .rpy file."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "scenario.rpy").write_text(rpy_content, encoding="utf-8")
    return tmp_path


_SAMPLE_RPY = """label start:
    return
"""


def _corrupt_bytes(path: Path) -> None:
    """Overwrite file content with garbage that no parser will accept."""
    path.write_bytes(b"\x00\x01\x02 not a valid pickle \xff\xfe\xfd")


def _truncate_to_half(path: Path) -> None:
    """Simulate a write that was interrupted before ``os.replace`` — first
    half of the file survives, second half is missing."""
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])


# =============================================================================
# Self-healing contract: corrupt cache manifest
# =============================================================================


class TestCacheManifestSelfHealing:
    """If the cache manifest is corrupt, the analyzer must rebuild without
    crashing and produce the same diagnostics as a cold run."""

    def test_corrupt_manifest_triggers_cold_rebuild(self, tmp_path: Path) -> None:
        project = _setup_project(tmp_path, _SAMPLE_RPY)
        cache_dir = project / ".senpy_cache"
        manifest_path = cache_dir / "cache.pkl"

        cold = SenpyAnalyzer(str(project))
        cold_r = cold.run(quiet=True)
        assert manifest_path.exists()
        cold_codes = sorted(d.code for d in cold_r.diagnostics)

        _corrupt_bytes(manifest_path)

        warm = SenpyAnalyzer(str(project))
        warm_r = warm.run(quiet=True)

        warm_codes = sorted(d.code for d in warm_r.diagnostics)
        assert warm_codes == cold_codes, (
            "Corrupt manifest should trigger a cold rebuild that produces "
            f"the same diagnostics. Cold={cold_codes}, warm={warm_codes}."
        )

        # Manifest must be re-written as a valid CacheManifest.
        with open(manifest_path, "rb") as f:
            rebuilt = SafeCacheUnpickler(f).load()
        assert isinstance(rebuilt, CacheManifest)
        assert rebuilt.version == SENPY_VERSION

    def test_truncated_manifest_triggers_cold_rebuild(self, tmp_path: Path) -> None:
        project = _setup_project(tmp_path, _SAMPLE_RPY)
        cache_dir = project / ".senpy_cache"
        manifest_path = cache_dir / "cache.pkl"

        cold = SenpyAnalyzer(str(project))
        cold.run(quiet=True)

        _truncate_to_half(manifest_path)

        warm = SenpyAnalyzer(str(project))
        # Must not raise — EOFError on truncated pickle is caught internally.
        warm.run(quiet=True)

    def test_empty_manifest_triggers_cold_rebuild(self, tmp_path: Path) -> None:
        project = _setup_project(tmp_path, _SAMPLE_RPY)
        cache_dir = project / ".senpy_cache"
        manifest_path = cache_dir / "cache.pkl"

        cold = SenpyAnalyzer(str(project))
        cold.run(quiet=True)

        manifest_path.write_bytes(b"")

        warm = SenpyAnalyzer(str(project))
        warm.run(quiet=True)


# =============================================================================
# Self-healing contract: corrupt trust store
# =============================================================================


class TestTrustStoreSelfHealing:
    """If the trust store JSON is corrupt, the plugin loader must treat it
    as empty and continue. The next ``trust_plugin`` call overwrites the
    corrupt file with valid JSON."""

    def test_corrupt_trust_store_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        from senpy.plugins import security

        store_path = Path(security.get_trust_store_path())
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text("{not valid json", encoding="utf-8")

        data = security._read_trust_store()
        assert data["plugins"] == []
        assert data["trusted_at"] == {}
        assert data["version"] == security._TRUST_STORE_VERSION

    def test_corrupt_trust_store_overwritten_on_next_trust(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        from senpy.plugins import security

        store_path = Path(security.get_trust_store_path())
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text("{ corrupt", encoding="utf-8")

        security.trust_plugin("some-plugin")

        with open(store_path, encoding="utf-8") as f:
            data = json.load(f)
        assert "some-plugin" in data["plugins"]


# =============================================================================
# Unique temp filename: each save call uses its own temp file
# =============================================================================


class TestUniqueTempFilename:
    """``CacheManager.save_manifest`` and ``_write_trust_store`` must use a
    unique temp filename per call (via ``tempfile.mkstemp``), so concurrent
    writers cannot share a temp inode."""

    def test_save_manifest_uses_unique_temp_filename(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = _setup_project(tmp_path, _SAMPLE_RPY)
        cache_dir = project / ".senpy_cache"

        real_mkstemp = tempfile.mkstemp
        seen_paths: list[str] = []

        def _tracking_mkstemp(*args, **kwargs):
            fd, path = real_mkstemp(*args, **kwargs)
            seen_paths.append(path)
            return fd, path

        monkeypatch.setattr("tempfile.mkstemp", _tracking_mkstemp)

        a = SenpyAnalyzer(str(project))
        a.run(quiet=True)

        # At least one mkstemp call (for save_manifest) — possibly more
        # if other code paths use tempfile, but at least one and all unique.
        assert len(seen_paths) >= 1, "save_manifest did not call tempfile.mkstemp"
        assert len(seen_paths) == len(
            set(seen_paths)
        ), f"save_manifest reused a temp filename: {seen_paths}"

        # No leftover .tmp files after a successful run.
        leftovers = [p for p in cache_dir.iterdir() if p.suffix == ".tmp"]
        assert leftovers == [], f"save_manifest left .tmp files in cache dir: {leftovers}"

    def test_save_manifest_cleanup_on_replace_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = _setup_project(tmp_path, _SAMPLE_RPY)
        cache_dir = project / ".senpy_cache"
        manifest_path = cache_dir / "cache.pkl"

        # First, do a successful cold run so a valid manifest exists.
        cold = SenpyAnalyzer(str(project))
        cold.run(quiet=True)
        assert manifest_path.exists()

        real_replace = os.replace

        def _failing_replace(src: str, dst: str) -> None:
            if os.path.abspath(dst) == os.path.abspath(str(manifest_path)):
                raise OSError("simulated rename failure")
            return real_replace(src, dst)

        monkeypatch.setattr("os.replace", _failing_replace)

        # Second run — save_manifest catches OSError silently (debug log).
        warm = SenpyAnalyzer(str(project))
        warm.run(quiet=True)

        # Critical: no leftover .tmp files even though os.replace failed.
        leftovers = [p for p in cache_dir.iterdir() if p.suffix == ".tmp"]
        assert leftovers == [], f"save_manifest leaked .tmp files on rename failure: {leftovers}"

        # Original manifest is intact (the failure happened before os.replace,
        # so the previous content at manifest_path was never touched).
        with open(manifest_path, "rb") as f:
            rebuilt = SafeCacheUnpickler(f).load()
        assert isinstance(rebuilt, CacheManifest)

    def test_trust_store_uses_unique_temp_filename(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        from senpy.plugins import security

        real_mkstemp = tempfile.mkstemp
        seen_paths: list[str] = []

        def _tracking_mkstemp(*args, **kwargs):
            fd, path = real_mkstemp(*args, **kwargs)
            seen_paths.append(path)
            return fd, path

        monkeypatch.setattr("tempfile.mkstemp", _tracking_mkstemp)

        security.trust_plugin("plugin-a")
        security.trust_plugin("plugin-b")

        # Two trust writes → two mkstemp calls → two unique paths.
        assert (
            len(seen_paths) >= 2
        ), f"Expected >=2 mkstemp calls for 2 trust writes, got {len(seen_paths)}"
        assert len(seen_paths) == len(
            set(seen_paths)
        ), f"_write_trust_store reused a temp filename: {seen_paths}"

        store_dir = Path(security.get_trust_store_path()).parent
        leftovers = [p for p in store_dir.iterdir() if p.suffix == ".tmp"]
        assert leftovers == [], f"_write_trust_store leaked .tmp files: {leftovers}"
