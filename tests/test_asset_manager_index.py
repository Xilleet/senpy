"""Tests for `senpy/domain/assets.py:AssetManager.index()` — file discovery.

Two behaviors covered here:

1. Senpy's own files (senpy.toml, .senpyignore, report.json) must NOT
   appear in `unused_assets`. They are not game assets — they are
   Senpy's own configuration / output artifacts. Before the fix, the
   DDLC: Blue Skies dump showed `"senpy.toml"` and `"report.json"` in
   `unused_assets`, which is confusing.

2. The .senpy_cache/ directory is in IGNORED_DIRS. Files inside it
   must not be classified as game assets either (regression guard).
"""

from __future__ import annotations

from pathlib import Path

from senpy.domain.assets import AssetManager


def _make_project(tmp_path: Path) -> Path:
    """Create a minimal project with one real asset and Senpy's own files."""
    project = tmp_path / "proj"
    project.mkdir()
    game = project / "game"
    game.mkdir()

    # One real unused asset (should appear in unused_assets).
    (game / "images").mkdir()
    (game / "images" / "bg_unused.png").write_bytes(b"\x89PNG\r\n\x1a\n fake png")

    # Senpy's own files (should NOT appear in unused_assets).
    (project / "senpy.toml").write_text("[senpy]\nstrict = false\n", encoding="utf-8")
    (project / ".senpyignore").write_text("*.rpyc\n", encoding="utf-8")
    (project / "report.json").write_text('{"diagnostics": []}', encoding="utf-8")
    (project / "test_report.json").write_text('{"tests": []}', encoding="utf-8")
    (project / "test_report.txt").write_text("passed\n", encoding="utf-8")

    return project


def _collect_unused_assets(project: Path) -> set[str]:
    """Run AssetManager.index() and return the unused asset rel-paths.

    Mirrors what `senpy inspect --unresolved` does: known_assets minus
    used_asset_keys. Since we don't run the analyzer, used_asset_keys is
    empty, so this returns the full known_assets set.
    """
    am = AssetManager(str(project))
    am.index()
    return set(am.known_assets)


class TestSenpyOwnFilesExcluded:
    """Senpy's own files must not be classified as game assets."""

    def test_senpy_toml_excluded(self, tmp_path):
        project = _make_project(tmp_path)
        unused = _collect_unused_assets(project)
        # senpy.toml should NOT appear in any form (with or without prefix).
        assert "senpy.toml" not in unused
        assert "game/senpy.toml" not in unused

    def test_senpyignore_excluded(self, tmp_path):
        project = _make_project(tmp_path)
        unused = _collect_unused_assets(project)
        assert ".senpyignore" not in unused
        assert "game/.senpyignore" not in unused

    def test_report_json_excluded(self, tmp_path):
        project = _make_project(tmp_path)
        unused = _collect_unused_assets(project)
        assert "report.json" not in unused
        assert "game/report.json" not in unused

    def test_test_report_files_excluded(self, tmp_path):
        """test_report.json / test_report.txt are pytest artifacts from
        conftest.py. They should not be classified as game assets either."""
        project = _make_project(tmp_path)
        unused = _collect_unused_assets(project)
        assert "test_report.json" not in unused
        assert "test_report.txt" not in unused

    def test_real_assets_still_listed(self, tmp_path):
        """Sanity: actual unused game assets are still in the list."""
        project = _make_project(tmp_path)
        unused = _collect_unused_assets(project)
        # The fake PNG must still be there (in canonical form).
        assert "images/bg_unused.png" in unused or "game/images/bg_unused.png" in unused


class TestSenpyCacheDirExcluded:
    """The .senpy_cache/ directory is in IGNORED_DIRS. Verify it stays
    excluded — files inside it must not appear in unused_assets."""

    def test_senpy_cache_files_excluded(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "game").mkdir()
        # Create a cache file that would look like an asset if not excluded.
        cache = project / ".senpy_cache"
        cache.mkdir()
        (cache / "decompiled").mkdir()
        (cache / "decompiled" / "fake.rpy").write_text("label x:\n    return\n", encoding="utf-8")

        am = AssetManager(str(project))
        am.index()
        unused = set(am.known_assets)
        # The cached .rpy file must not be classified as a game asset.
        assert ".senpy_cache/decompiled/fake.rpy" not in unused
        assert "decompiled/fake.rpy" not in unused
