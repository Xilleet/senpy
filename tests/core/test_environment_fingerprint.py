"""TDD tests for ``compute_environment_fingerprint`` (environment fingerprint).

The environment fingerprint covers filesystem-dependent state that the
symbol hash does not include:
  - ``AssetManager.valid_images`` — built from ``os.walk`` over ``images/``.
  - ``AssetManager.known_assets`` — built from ``os.walk`` over the project.
  - ``AssetManager.audio_dir_files`` — built from ``os.walk`` over ``audio/``.
  - ``defined_audio_map`` target paths — parsed from ``.rpy`` but reference
    on-disk audio files (the *target* path, not just the alias name).

Without these in the cache fingerprint, a warm run after adding/removing
a ``.png`` or ``.ogg`` file would serve stale ``RPY501``/``RPY502``/``RPY503``
diagnostics from the Tier-2 cache — the analyzer thinks nothing changed
because the ``.rpy`` files are byte-identical.

The fingerprint is combined with the symbol hash:
``combined = blake2b(symbol_hash + env_fingerprint)``. Old manifests that
store only ``global_symbol_hash`` (without env fingerprint) are treated
as a cache miss → rebuild.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.cache import CacheManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(tmp_path: Path, script_content: str) -> Path:
    """Build a minimal Ren'Py project with one .rpy file."""
    game = tmp_path / "game"
    game.mkdir(parents=True, exist_ok=True)
    (game / "script.rpy").write_text(script_content, encoding="utf-8")
    return tmp_path


def _make_image_file(project: Path, rel_path: str, content: bytes = b"\x89PNG\r\n\x1a\n") -> Path:
    """Create an image file inside the project's game/images/ dir."""
    full = project / "game" / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(content)
    return full


def _make_audio_file(project: Path, rel_path: str, content: bytes = b"OggS") -> Path:
    """Create an audio file inside the project's game/ dir."""
    full = project / "game" / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(content)
    return full


# ---------------------------------------------------------------------------
# compute_environment_fingerprint — existence + determinism
# ---------------------------------------------------------------------------


class TestEnvironmentFingerprintExists:
    """``compute_environment_fingerprint`` must exist and return a hex string."""

    def test_method_exists(self):
        """The method must exist on CacheManager."""
        assert hasattr(CacheManager, "compute_environment_fingerprint"), (
            "CacheManager.compute_environment_fingerprint does not exist. "
            "Without it, FS-dependent state (valid_images, known_assets, "
            "audio_dir_files, defined_audio_map targets) is not part of the "
            "cache fingerprint → stale RPY501/502/503 on warm runs."
        )

    def test_returns_hex_string(self, tmp_path: Path):
        """The fingerprint must be a non-empty hex string."""
        project = _make_project(tmp_path, "label start:\n    return\n")
        analyzer = SenpyAnalyzer(str(project), no_cache=True)
        analyzer.run(quiet=True)

        fp = CacheManager.compute_environment_fingerprint(analyzer)
        assert isinstance(fp, str)
        assert len(fp) > 0
        # Hex string (BLAKE2b output)
        assert all(
            c in "0123456789abcdef" for c in fp
        ), f"Environment fingerprint is not a hex string: {fp!r}"

    def test_deterministic_same_project(self, tmp_path: Path):
        """Two runs of the same project → identical fingerprint."""
        project = _make_project(tmp_path, "label start:\n    return\n")
        _make_image_file(project, "images/bg_town.png")

        analyzer1 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer1.run(quiet=True)
        fp1 = CacheManager.compute_environment_fingerprint(analyzer1)

        analyzer2 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer2.run(quiet=True)
        fp2 = CacheManager.compute_environment_fingerprint(analyzer2)

        assert fp1 == fp2, (
            "Same project state produced different environment fingerprints. "
            "The fingerprint must be deterministic — otherwise the cache would "
            "never hit and every warm run would be as slow as a cold run."
        )


# ---------------------------------------------------------------------------
# Asset add/delete → fingerprint changes
# ---------------------------------------------------------------------------


class TestAssetAddDeleteChangesFingerprint:
    """Adding/removing a ``.png`` or ``.ogg`` file must change the fingerprint."""

    def test_add_image_changes_fingerprint(self, tmp_path: Path):
        """Adding a ``.png`` to ``images/`` → fingerprint must change."""
        project = _make_project(tmp_path, "label start:\n    return\n")

        analyzer1 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer1.run(quiet=True)
        fp1 = CacheManager.compute_environment_fingerprint(analyzer1)

        # Add an image file.
        _make_image_file(project, "images/bg_town.png")

        analyzer2 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer2.run(quiet=True)
        fp2 = CacheManager.compute_environment_fingerprint(analyzer2)

        assert fp1 != fp2, (
            "Adding a .png file did not change the environment fingerprint. "
            "valid_images / known_assets must be part of the fingerprint — "
            "RPY502 (missing image) and RPY503 (unused asset) depend on "
            "the set of on-disk image files. Without this, a warm run after "
            "adding an image would serve stale RPY502 from the cache."
        )

    def test_delete_image_changes_fingerprint(self, tmp_path: Path):
        """Removing a ``.png`` from ``images/`` → fingerprint must change."""
        project = _make_project(tmp_path, "label start:\n    return\n")
        img = _make_image_file(project, "images/bg_town.png")

        analyzer1 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer1.run(quiet=True)
        fp1 = CacheManager.compute_environment_fingerprint(analyzer1)

        # Delete the image file.
        img.unlink()

        analyzer2 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer2.run(quiet=True)
        fp2 = CacheManager.compute_environment_fingerprint(analyzer2)

        assert fp1 != fp2, (
            "Deleting a .png file did not change the environment fingerprint. "
            "known_assets must be part of the fingerprint — RPY503 (unused "
            "asset) depends on the set of on-disk files. Without this, a "
            "warm run after deleting an image would serve stale RPY503 from "
            "the cache."
        )

    def test_add_audio_changes_fingerprint(self, tmp_path: Path):
        """Adding an ``.ogg`` to ``audio/`` → fingerprint must change."""
        project = _make_project(tmp_path, "label start:\n    return\n")

        analyzer1 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer1.run(quiet=True)
        fp1 = CacheManager.compute_environment_fingerprint(analyzer1)

        _make_audio_file(project, "audio/bgm_calm.ogg")

        analyzer2 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer2.run(quiet=True)
        fp2 = CacheManager.compute_environment_fingerprint(analyzer2)

        assert fp1 != fp2, (
            "Adding an .ogg file did not change the environment fingerprint. "
            "audio_dir_files must be part of the fingerprint — RPY501 (missing "
            "audio) depends on the set of on-disk audio files. Without this, "
            "a warm run after adding audio would serve stale RPY501 from the cache."
        )

    def test_delete_audio_changes_fingerprint(self, tmp_path: Path):
        """Removing an ``.ogg`` from ``audio/`` → fingerprint must change."""
        project = _make_project(tmp_path, "label start:\n    return\n")
        audio = _make_audio_file(project, "audio/bgm_calm.ogg")

        analyzer1 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer1.run(quiet=True)
        fp1 = CacheManager.compute_environment_fingerprint(analyzer1)

        audio.unlink()

        analyzer2 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer2.run(quiet=True)
        fp2 = CacheManager.compute_environment_fingerprint(analyzer2)

        assert fp1 != fp2, (
            "Deleting an .ogg file did not change the environment fingerprint. "
            "audio_dir_files must be part of the fingerprint — RPY501 (missing "
            "audio) depends on the set of on-disk audio files. Without this, "
            "a warm run after deleting audio would serve stale RPY501 from the cache."
        )


# ---------------------------------------------------------------------------
# Audio alias target path change → fingerprint changes
# ---------------------------------------------------------------------------


class TestAudioAliasTargetChangesFingerprint:
    """Changing ``define audio.X = "path"`` target path → fingerprint must change.

    The alias name (``X``) is part of the symbol hash, but the *target*
    path (``"path"``) is not — it's a filesystem-dependent value. Without
    it in the fingerprint, renaming an audio file and updating the alias
    target would not invalidate the cache (the symbol hash is unchanged
    because the alias name is the same).
    """

    def test_alias_target_change_changes_fingerprint(self, tmp_path: Path):
        """Changing ``define audio.calm = "a.ogg"`` → ``"b.ogg"`` →
        fingerprint must change.
        """
        project = _make_project(
            tmp_path,
            'define audio.calm = "audio/bgm_calm.ogg"\n'
            "label start:\n"
            "    play music calm\n"
            "    return\n",
        )
        _make_audio_file(project, "audio/bgm_calm.ogg")
        _make_audio_file(project, "audio/bgm_happy.ogg")

        analyzer1 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer1.run(quiet=True)
        fp1 = CacheManager.compute_environment_fingerprint(analyzer1)

        # Change the alias target (same alias name, different file).
        (project / "game" / "script.rpy").write_text(
            'define audio.calm = "audio/bgm_happy.ogg"\n'
            "label start:\n"
            "    play music calm\n"
            "    return\n",
            encoding="utf-8",
        )

        analyzer2 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer2.run(quiet=True)
        fp2 = CacheManager.compute_environment_fingerprint(analyzer2)

        assert fp1 != fp2, (
            "Changing an audio alias target path did not change the "
            "environment fingerprint. defined_audio_map values (target "
            "paths) must be part of the fingerprint — audio hover and "
            "RPY501 depend on the target file existing. Without this, "
            "renaming an audio file + updating the alias would not "
            "invalidate the cache."
        )


# ---------------------------------------------------------------------------
# Combined hash: symbol_hash + env_fingerprint
# ---------------------------------------------------------------------------


class TestCombinedGlobalHash:
    """The combined hash (symbol + environment) must change when either
    the symbol table OR the filesystem state changes.
    """

    def test_combined_hash_changes_on_fs_change(self, tmp_path: Path):
        """A .png add (no .rpy change) → combined hash must change."""
        project = _make_project(
            tmp_path,
            'image bg_town = "images/bg_town.png"\nlabel start:\n    scene bg_town\n    return\n',
        )

        analyzer1 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer1.run(quiet=True)
        symbol_hash1 = CacheManager.compute_global_hash(analyzer1)
        env_fp1 = CacheManager.compute_environment_fingerprint(analyzer1)
        combined1 = CacheManager.compute_combined_hash(analyzer1)

        # Add the image file (no .rpy change → symbol hash unchanged).
        _make_image_file(project, "images/bg_town.png")

        analyzer2 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer2.run(quiet=True)
        symbol_hash2 = CacheManager.compute_global_hash(analyzer2)
        env_fp2 = CacheManager.compute_environment_fingerprint(analyzer2)
        combined2 = CacheManager.compute_combined_hash(analyzer2)

        # Symbol hash unchanged (no .rpy edit).
        assert (
            symbol_hash1 == symbol_hash2
        ), "Symbol hash changed despite no .rpy edit — B.1 regression?"
        # Env fingerprint changed (image added).
        assert env_fp1 != env_fp2, "Env fingerprint should change on image add."
        # Combined hash changed (env component changed).
        assert combined1 != combined2, (
            "Combined hash did not change after adding a .png file. "
            "The combined hash must reflect both symbol and environment "
            "state — otherwise Tier-2 cache hits serve stale RPY502."
        )

    def test_combined_hash_changes_on_symbol_change(self, tmp_path: Path):
        """A .rpy edit (no FS change) → combined hash must change."""
        project = _make_project(
            tmp_path,
            "label foo:\n    jump bar\nlabel bar:\n    return\n",
        )

        analyzer1 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer1.run(quiet=True)
        combined1 = CacheManager.compute_combined_hash(analyzer1)

        # Edit .rpy (add return to foo — symbol change, no FS change).
        (project / "game" / "script.rpy").write_text(
            "label foo:\n    jump bar\n    return\nlabel bar:\n    return\n",
            encoding="utf-8",
        )

        analyzer2 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer2.run(quiet=True)
        combined2 = CacheManager.compute_combined_hash(analyzer2)

        assert combined1 != combined2, (
            "Combined hash did not change after a .rpy edit (symbol change). "
            "The combined hash must reflect symbol-table changes too — "
            "otherwise B.1 is broken."
        )

    def test_combined_hash_stable_on_unrelated_change(self, tmp_path: Path):
        """A comment-only .rpy edit (no symbol change) + no FS change →
        combined hash must NOT change (cache must hit).
        """
        project = _make_project(
            tmp_path,
            "label start:\n    return\n",
        )

        analyzer1 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer1.run(quiet=True)
        combined1 = CacheManager.compute_combined_hash(analyzer1)

        # Add a comment — no symbol change, no FS change.
        (project / "game" / "script.rpy").write_text(
            "# comment\nlabel start:\n    return\n",
            encoding="utf-8",
        )

        analyzer2 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer2.run(quiet=True)
        combined2 = CacheManager.compute_combined_hash(analyzer2)

        assert combined1 == combined2, (
            "Combined hash changed after a comment-only edit. The hash must "
            "only respond to symbol-table or FS changes, not to whitespace/"
            "comments. Otherwise every save in the editor would invalidate "
            "the cache."
        )


# ---------------------------------------------------------------------------
# End-to-end: stale RPY502 no longer served from warm cache
# ---------------------------------------------------------------------------


class TestStaleRPY502NoLongerServedFromWarmCache:
    """End-to-end: ``senpy --no-cache=False`` warm run after adding a
    ``.png`` file must NOT serve a stale ``RPY502`` (missing image).

    Before B.2: warm run hit Tier-2 cache (symbol hash unchanged) and
    served the stale RPY502 even though the image now exists on disk.
    After B.2: the environment fingerprint changes (image added) →
    combined hash changes → Tier-2 cache miss → re-analyze → no RPY502.
    """

    def test_warm_run_after_image_add_drops_rpy502(self, tmp_path: Path):
        """Cold run: RPY502 (missing image). Add image. Warm run: no RPY502."""
        # Use auto-discovery (no explicit `image` declaration) so RPY502
        # fires when the .png is absent. With an explicit `image bg = "path"`
        # declaration, the image is always "valid" (it's in analyzer.images),
        # so RPY502 never fires regardless of the filesystem.
        project = _make_project(
            tmp_path,
            "label start:\n    scene bg_town\n    return\n",
        )
        # No image file on disk → RPY502 fires.

        # Cold run (with cache enabled — the default).
        analyzer1 = SenpyAnalyzer(str(project))  # cache enabled
        result1 = analyzer1.run(quiet=True)
        rpy502_cold = [d for d in result1.diagnostics if d.code == "RPY502"]
        assert len(rpy502_cold) >= 1, (
            "Cold run should fire RPY502 (image missing on disk). "
            "Test setup is wrong if it does not."
        )

        # Add the image file.
        _make_image_file(project, "images/bg_town.png")

        # Warm run (cache enabled — should hit Tier 1, but Tier 2 must
        # miss because the env fingerprint changed).
        analyzer2 = SenpyAnalyzer(str(project))  # cache enabled
        result2 = analyzer2.run(quiet=True)
        rpy502_warm = [d for d in result2.diagnostics if d.code == "RPY502"]
        assert rpy502_warm == [], (
            f"Warm run after adding the image still serves {len(rpy502_warm)} "
            f"stale RPY502 diagnostic(s). The environment fingerprint must "
            "invalidate the Tier-2 cache when a .png file is added — "
            "otherwise users see stale 'missing image' errors."
        )
