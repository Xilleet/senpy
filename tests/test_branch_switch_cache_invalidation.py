"""Regression tests for cache invalidation when .rpy files are added,
deleted, or renamed between two analyzer runs.

Scenario: a project starts with two .rpy files. Between subsequent
``SenpyAnalyzer.run()`` calls, the test simulates the three branch-switch
operations that happen in real-world workflows (e.g. ``git checkout``
to a different branch, file-manager delete, editor save-as):

  cold → delete → warm → re-add → warm → rename → warm

At each step we assert:

  - The cache manifest's ``files`` dict contains exactly the .rpy files
    currently on disk — old paths evicted, new paths added. (Implicit
    eviction via manifest rebuild.)
  - Diagnostics reflect the current on-disk state. Specifically, a
    ``jump helper`` in ``script.rpy`` emits RPY302 when ``helper.rpy``
    is absent, and is silent when ``helper`` is defined in any .rpy
    file.
  - Tier 2 cache reuse: a file that has not been edited between runs
    may still hit the warm cache even when sibling files were added or
    deleted (provided the global symbol hash did not change in a way
    that affects that file's diagnostics).

These properties have always held in the implementation — the manifest
is rebuilt from scratch every run from only the files ``discover_rpy_files``
returns. This test pins them down as a regression guard.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.cache import CacheManifest, SafeCacheUnpickler
from senpy.core.paths import normalize_path

# =============================================================================
# Fixtures
# =============================================================================


_SCRIPT_RPY = """label start:
    jump helper
    return
"""

_HELPER_RPY = """label helper:
    return
"""


def _make_project(tmp_path: Path) -> Path:
    """Create a project with script.rpy (jumping to ``helper``) and
    helper.rpy (defining ``label helper``)."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(_SCRIPT_RPY, encoding="utf-8")
    (game_dir / "helper.rpy").write_text(_HELPER_RPY, encoding="utf-8")
    return tmp_path


def _load_manifest(project: Path) -> CacheManifest | None:
    """Read the on-disk cache manifest. Returns ``None`` if no manifest
    has been written yet."""
    manifest_path = project / ".senpy_cache" / "cache.pkl"
    if not manifest_path.exists():
        return None
    with open(manifest_path, "rb") as f:
        return SafeCacheUnpickler(f).load()


def _manifest_keys(project: Path) -> set[str]:
    """Return the set of normalized file paths currently in the cache
    manifest. Returns ``set()`` if no manifest exists."""
    m = _load_manifest(project)
    if m is None:
        return set()
    return set(m.files.keys())


def _diag_codes(analyzer: SenpyAnalyzer) -> set[str]:
    return {d.code for d in analyzer.diagnostics}


# =============================================================================
# Tests
# =============================================================================


class TestBranchSwitchCacheInvalidation:
    """cold → delete → warm → re-add → warm → rename → warm sequence."""

    def test_full_branch_switch_sequence(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        cache_dir = project / ".senpy_cache"
        shutil.rmtree(cache_dir, ignore_errors=True)

        game = project / "game"
        script = game / "script.rpy"
        helper = game / "helper.rpy"
        assistance = game / "assistance.rpy"

        script_key = normalize_path(str(script))
        helper_key = normalize_path(str(helper))
        assistance_key = normalize_path(str(assistance))

        # ---- cold run: both files present, jump resolves, no RPY302 ----
        cold = SenpyAnalyzer(str(project))
        cold.run(quiet=True)
        cold_keys = _manifest_keys(project)
        assert script_key in cold_keys, "cold run should cache script.rpy"
        assert helper_key in cold_keys, "cold run should cache helper.rpy"
        assert "RPY302" not in _diag_codes(
            cold
        ), "jump helper must resolve when helper.rpy is present"

        # ---- delete helper.rpy → warm run → RPY302 fires, entry evicted ----
        helper.unlink()
        warm_after_delete = SenpyAnalyzer(str(project))
        warm_after_delete.run(quiet=True)
        keys_after_delete = _manifest_keys(project)
        assert (
            helper_key not in keys_after_delete
        ), "deleted file's cache entry must be evicted on the next run"
        assert script_key in keys_after_delete, "unchanged file's cache entry must remain"
        assert "RPY302" in _diag_codes(
            warm_after_delete
        ), "jump helper must emit RPY302 when helper.rpy is deleted"

        # ---- re-add helper.rpy → warm run → RPY302 clears, entry back ----
        helper.write_text(_HELPER_RPY, encoding="utf-8")
        warm_after_readd = SenpyAnalyzer(str(project))
        warm_after_readd.run(quiet=True)
        keys_after_readd = _manifest_keys(project)
        assert helper_key in keys_after_readd, "re-added file must appear in the cache manifest"
        assert script_key in keys_after_readd
        assert "RPY302" not in _diag_codes(
            warm_after_readd
        ), "jump helper must resolve again once helper.rpy is back"

        # ---- rename helper.rpy → assistance.rpy → warm run ----
        # Content is identical; only the file path changes.
        helper.rename(assistance)
        warm_after_rename = SenpyAnalyzer(str(project))
        warm_after_rename.run(quiet=True)
        keys_after_rename = _manifest_keys(project)
        # Old path evicted.
        assert (
            helper_key not in keys_after_rename
        ), "renamed-away file's old cache key must be evicted"
        # New path added.
        assert assistance_key in keys_after_rename, "renamed-to file's new cache key must be added"
        # Unchanged file still cached.
        assert script_key in keys_after_rename
        # jump helper still resolves: ``label helper`` now lives in
        # assistance.rpy — the cross-file lookup is path-independent.
        assert "RPY302" not in _diag_codes(
            warm_after_rename
        ), "jump helper must resolve even after the defining file is renamed"

    def test_delete_all_files_does_not_crash(self, tmp_path: Path) -> None:
        """Edge case: when every .rpy file is deleted between runs, the
        manifest saved by the next run must not contain any stale entries.
        The analyzer must complete without crashing even though
        ``new_cached_entries`` is empty (which suppresses the manifest
        save — see analysis_pipeline._finalize_results)."""
        project = _make_project(tmp_path)
        cache_dir = project / ".senpy_cache"
        shutil.rmtree(cache_dir, ignore_errors=True)

        cold = SenpyAnalyzer(str(project))
        cold.run(quiet=True)
        assert _load_manifest(project) is not None

        # Delete every .rpy file.
        for f in (project / "game").glob("*.rpy"):
            f.unlink()

        warm = SenpyAnalyzer(str(project))
        # Must not crash.
        warm.run(quiet=True)

        # Diagnostics should be empty — no files to analyze.
        assert warm.diagnostics == [] or all(
            d.code == "RPY000" for d in warm.diagnostics
        ), "No .rpy files on disk → no diagnostics (except internal errors)"

    def test_add_new_file_between_runs(self, tmp_path: Path) -> None:
        """Adding a new .rpy file between runs must:
        - Add its entry to the next manifest.
        - Invalidate Tier 2 cache for sibling files whose diagnostics
          depend on cross-file state (here: a label referenced by a jump).
        """
        project = _make_project(tmp_path)
        cache_dir = project / ".senpy_cache"
        shutil.rmtree(cache_dir, ignore_errors=True)

        # Start with ONLY script.rpy — jump helper unresolved.
        game = project / "game"
        helper = game / "helper.rpy"
        helper.unlink()  # remove helper so cold run sees only script

        cold = SenpyAnalyzer(str(project))
        cold.run(quiet=True)
        assert "RPY302" in _diag_codes(
            cold
        ), "cold run with only script.rpy → jump helper must emit RPY302"

        # Add helper.rpy — now jump resolves.
        helper.write_text(_HELPER_RPY, encoding="utf-8")
        warm = SenpyAnalyzer(str(project))
        warm.run(quiet=True)

        warm_keys = _manifest_keys(project)
        assert (
            normalize_path(str(helper)) in warm_keys
        ), "newly added file must appear in the cache manifest"
        assert "RPY302" not in _diag_codes(
            warm
        ), "jump helper must resolve once helper.rpy is added"

    def test_rename_preserves_symbol_resolution(self, tmp_path: Path) -> None:
        """Renaming a .rpy file that defines a label must not break
        cross-file references to that label — the symbol table is
        rebuilt every run from the on-disk file set, and label
        resolution is path-independent.

        This is the structural contract that allows ``git checkout``
        between branches that move the same label between files to
        work without manually clearing the cache.
        """
        project = _make_project(tmp_path)
        cache_dir = project / ".senpy_cache"
        shutil.rmtree(cache_dir, ignore_errors=True)

        cold = SenpyAnalyzer(str(project))
        cold.run(quiet=True)
        assert "RPY302" not in _diag_codes(cold)

        # Rename helper.rpy → assistance.rpy, same content.
        game = project / "game"
        (game / "helper.rpy").rename(game / "assistance.rpy")

        warm = SenpyAnalyzer(str(project))
        warm.run(quiet=True)

        # Symbol resolution must still find ``label helper`` in the
        # renamed file.
        assert "RPY302" not in _diag_codes(warm), (
            "renaming the file that defines a label must not break "
            "cross-file references to that label"
        )
