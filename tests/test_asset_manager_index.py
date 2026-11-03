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

import pytest

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


class TestNonAssetExtensionsExcluded:
    """Files with non-asset extensions (.exe, .sh, .md, .txt, .zip, .psd,
    .rpa, .rpyc, .spec) must NOT appear in `unused_assets`.

    These are not game assets — they are build artifacts, documentation,
    archives, or Photoshop source files. Including them in
    `unused_assets` produces hundreds of false positives on real mods
    (e.g. DDLC: Blue Skies had ~500 "unused assets", of which ~90%
    were .rpyc/.rpa/.md/.txt/.psd files).
    """

    @pytest.fixture
    def project_with_non_asset_files(self, tmp_path: Path) -> Path:
        """Project with one real asset + several non-asset files."""
        project = tmp_path / "proj"
        project.mkdir()
        game = project / "game"
        game.mkdir()

        # One real unused asset (should appear in unused_assets).
        (game / "images").mkdir()
        (game / "images" / "bg_real.png").write_bytes(b"\x89PNG\r\n\x1a\n fake")

        # Non-asset files that should be auto-excluded.
        (game / "script.rpyc").write_bytes(b"\x00\x01\x02 rpyc bytecode")
        (game / "audio.rpa").write_bytes(b"RPA-3.0 archive")
        (project / "README.md").write_text("# My Mod\n", encoding="utf-8")
        (project / "notes.txt").write_text("todo\n", encoding="utf-8")
        (project / "sprites.zip").write_bytes(b"PK zip archive")
        (project / "art.psd").write_bytes(b"8BPS photoshop")
        (project / "build.sh").write_text("#!/bin/sh\necho build\n", encoding="utf-8")
        (project / "launcher.exe").write_bytes(b"MZ exe header")
        return project

    def test_rpyc_excluded(self, project_with_non_asset_files):
        am = AssetManager(str(project_with_non_asset_files))
        am.index()
        unused = set(am.known_assets)
        assert "script.rpyc" not in unused
        assert "game/script.rpyc" not in unused

    def test_rpa_excluded(self, project_with_non_asset_files):
        am = AssetManager(str(project_with_non_asset_files))
        am.index()
        unused = set(am.known_assets)
        assert "audio.rpa" not in unused
        assert "game/audio.rpa" not in unused

    def test_md_excluded(self, project_with_non_asset_files):
        am = AssetManager(str(project_with_non_asset_files))
        am.index()
        unused = set(am.known_assets)
        assert "readme.md" not in unused

    def test_txt_excluded(self, project_with_non_asset_files):
        am = AssetManager(str(project_with_non_asset_files))
        am.index()
        unused = set(am.known_assets)
        assert "notes.txt" not in unused

    def test_zip_excluded(self, project_with_non_asset_files):
        am = AssetManager(str(project_with_non_asset_files))
        am.index()
        unused = set(am.known_assets)
        assert "sprites.zip" not in unused

    def test_psd_excluded(self, project_with_non_asset_files):
        am = AssetManager(str(project_with_non_asset_files))
        am.index()
        unused = set(am.known_assets)
        assert "art.psd" not in unused

    def test_sh_excluded(self, project_with_non_asset_files):
        am = AssetManager(str(project_with_non_asset_files))
        am.index()
        unused = set(am.known_assets)
        assert "build.sh" not in unused

    def test_exe_excluded(self, project_with_non_asset_files):
        am = AssetManager(str(project_with_non_asset_files))
        am.index()
        unused = set(am.known_assets)
        assert "launcher.exe" not in unused

    def test_real_asset_still_listed(self, project_with_non_asset_files):
        """Sanity: real game assets (PNG) are still in the list."""
        am = AssetManager(str(project_with_non_asset_files))
        am.index()
        unused = set(am.known_assets)
        assert "images/bg_real.png" in unused or "game/images/bg_real.png" in unused
