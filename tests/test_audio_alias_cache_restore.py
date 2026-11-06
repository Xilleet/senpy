"""TDD tests for audio alias hover restoration after Tier 1 cache hit.

``AssetManager.index()`` calls ``_reset_asset_state()`` which clears
``audio_name_to_path``. Registration of ``define audio.NAME = "..."``
aliases happens in ``FileCollector._collect_define_audio()`` via
``AssetManager.register_audio_alias()`` — but this is only called
inside ``_collect_symbols()``, which is **skipped** on Tier 1 cache
hit (the cached ``FileScope`` is restored directly).

``SymbolTable.rebuild_from_scopes()`` restores the alias *names*
(``defined_audio_map``), but does NOT restore
``AssetManager.audio_name_to_path`` (the disk-path index).

Result: after a warm run with Tier 1 cache hit, an audio alias is
still resolvable for semantic checks (via ``defined_audio_map``), but
``build_audio_hover()`` cannot resolve the alias to a disk path → the
hover card for ``play music custom_alias`` does not show file
size/preview.

Fix: after ``rebuild_from_scopes()``, re-register audio aliases into
``AssetManager.audio_name_to_path`` from the aggregated
``defined_audio_map`` (a simple loop calling
``register_audio_alias()`` for each alias→target pair).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer


def _make_project_with_audio_alias(tmp_path: Path) -> Path:
    """Build a project with a ``define audio.alias = "file.ogg"`` and
    the actual audio file on disk.
    """
    game = tmp_path / "game"
    game.mkdir(parents=True, exist_ok=True)
    (game / "script.rpy").write_text(
        'define audio.calm = "audio/bgm_calm.ogg"\n'
        "label start:\n"
        "    play music calm\n"
        "    return\n",
        encoding="utf-8",
    )
    audio_dir = game / "audio"
    audio_dir.mkdir(exist_ok=True)
    (audio_dir / "bgm_calm.ogg").write_bytes(b"OggS\x00\x00\x00\x00")
    return tmp_path


class TestAudioAliasHoverAfterTier1CacheHit:
    """After a warm run (Tier 1 cache hit), audio alias hover must
    still resolve the alias to a disk path.
    """

    def test_audio_name_to_path_restored_after_warm_run(self, tmp_path: Path):
        """Cold run → warm run → ``audio_name_to_path`` must contain
        the alias after the warm run.

        Before the fix: the warm run skipped ``_collect_symbols()`` →
        ``register_audio_alias()`` was never called →
        ``audio_name_to_path`` was empty → ``resolve_audio_path()``
        returned ``None``.
        """
        project = _make_project_with_audio_alias(tmp_path)

        # Cold run (with cache enabled — the default).
        analyzer1 = SenpyAnalyzer(str(project))
        analyzer1.run(quiet=True)

        # Verify cold run registered the alias.
        assert "calm" in analyzer1.assets.audio_name_to_path, (
            "Cold run did not register audio alias 'calm' in "
            "audio_name_to_path. Test setup is wrong."
        )
        cold_path = analyzer1.assets.audio_name_to_path["calm"]
        assert os.path.exists(
            cold_path
        ), f"Cold run resolved alias to a non-existent path: {cold_path}"

        # Warm run (cache enabled — Tier 1 cache hit expected).
        analyzer2 = SenpyAnalyzer(str(project))
        analyzer2.run(quiet=True)

        # The alias must still be in audio_name_to_path after the warm run.
        assert "calm" in analyzer2.assets.audio_name_to_path, (
            "Warm run (Tier 1 cache hit) did not restore audio alias "
            "'calm' in audio_name_to_path. register_audio_alias() is only "
            "called inside _collect_symbols() (cache miss path), so Tier 1 "
            "cache hit skips it. The fix must re-register aliases from "
            "defined_audio_map after rebuild_from_scopes()."
        )
        warm_path = analyzer2.assets.audio_name_to_path["calm"]
        assert warm_path == cold_path, (
            f"Warm run resolved alias to a different path: {warm_path} != {cold_path}. "
            "The alias must resolve to the same disk path on cold and warm runs."
        )

    def test_resolve_audio_path_works_after_warm_run(self, tmp_path: Path):
        """``resolve_audio_path('calm')`` must return a valid path
        after a warm run.
        """
        project = _make_project_with_audio_alias(tmp_path)

        # Cold run.
        analyzer1 = SenpyAnalyzer(str(project))
        analyzer1.run(quiet=True)
        cold_resolve = analyzer1.assets.resolve_audio_path("calm")
        assert cold_resolve is not None, "Cold run should resolve 'calm'."

        # Warm run.
        analyzer2 = SenpyAnalyzer(str(project))
        analyzer2.run(quiet=True)
        warm_resolve = analyzer2.assets.resolve_audio_path("calm")

        assert warm_resolve is not None, (
            "Warm run (Tier 1 cache hit) could not resolve audio alias "
            "'calm' to a disk path. resolve_audio_path() uses "
            "audio_name_to_path, which is cleared by _reset_asset_state() "
            "and not re-populated on Tier 1 cache hit. The fix must "
            "re-register aliases after rebuild_from_scopes()."
        )
        assert (
            warm_resolve == cold_resolve
        ), f"Warm run resolved to a different path: {warm_resolve} != {cold_resolve}."

    def test_defined_audio_map_populated_after_warm_run(self, tmp_path: Path):
        """``defined_audio_map`` (SymbolTable) must be populated after
        a warm run — this is the existing behaviour that works (it's
        restored by ``rebuild_from_scopes()``).

        This is a characterization test (not RED) — it verifies the
        part that already works, so we know the fix only needs to
        bridge the gap between ``defined_audio_map`` (which is restored)
        and ``audio_name_to_path`` (which is not).
        """
        project = _make_project_with_audio_alias(tmp_path)

        # Cold run.
        analyzer1 = SenpyAnalyzer(str(project))
        analyzer1.run(quiet=True)
        assert "calm" in analyzer1.defined_audio_map, (
            "Cold run did not register audio alias in defined_audio_map. " "Test setup is wrong."
        )

        # Warm run.
        analyzer2 = SenpyAnalyzer(str(project))
        analyzer2.run(quiet=True)
        assert "calm" in analyzer2.defined_audio_map, (
            "Warm run did not restore 'calm' in defined_audio_map. "
            "rebuild_from_scopes() should restore it from FileScope."
        )
        assert (
            analyzer2.defined_audio_map["calm"] == "audio/bgm_calm.ogg"
        ), f"Unexpected target path: {analyzer2.defined_audio_map['calm']}"
