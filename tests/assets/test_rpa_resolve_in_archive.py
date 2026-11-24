"""Tests for ``AssetManager.resolve_asset_in_archive``.

Adds the resolve primitive that locates an asset inside a parsed RPA
archive and returns a decoded ``(archive_path, offset, length, prefix)``
tuple (or ``None``). It is the bridge between the RPA-1 substrate
(``rpa_index_cache``) and the RPA-11 hover "found inside archive" consumer.

These tests do NOT exercise ``resolve_image_path`` / ``resolve_audio_path``
wiring — by design (see the method docstring) the fallback is consumed at
the hover layer, not by mutating those methods' disk-path return contract.
Here we verify the resolve primitive directly: name matching (full path,
``game/``-stripped, basename, case-insensitive, underscore↔space), the
returned tuple's correctness, prefix preservation, multi-archive lookup,
misses, and an end-to-end read proving the tuple is usable with
``read_rpa_segment``.
"""

from __future__ import annotations

import os
import pickle
import zlib
from pathlib import Path

import pytest

from senpy.domain.assets import AssetManager
from senpy.domain.rpa import RpaSegment, read_rpa_segment


def _make_rpa(
    path: Path,
    files: dict[str, tuple[bytes, bytes] | bytes],
    *,
    key: int = 0,
) -> None:
    """Write a minimal single-segment RPA-3.0 archive to *path*.

    Each entry is ``filename -> (data, prefix)`` or ``filename -> data``
    (prefix defaults to ``b""``). Segments are stored XOR'd with *key*:
    ``(data_offset ^ key, len(data) ^ key, prefix)``. The header uses the
    canonical 16-hex offset + 8-hex key + trailing-space format.
    """
    norm: dict[str, tuple[bytes, bytes]] = {}
    for name, val in files.items():
        if isinstance(val, tuple):
            data, prefix = val
        else:
            data, prefix = val, b""
        norm[name] = (data, prefix)

    version = "RPA-3.0"
    hex_offset_width, hex_key_width, trailing = 16, 8, " "
    header_len = len(version) + 1 + hex_offset_width + 1 + hex_key_width + len(trailing) + 1

    payload = b""
    index: dict[str, list[tuple[int, int, bytes]]] = {}
    pos = 0
    for name, (data, prefix) in norm.items():
        data_offset = header_len + pos
        index[name] = [(data_offset ^ key, len(data) ^ key, prefix)]
        payload += data
        pos += len(data)

    index_bytes = zlib.compress(pickle.dumps(index))
    index_offset = header_len + len(payload)
    header_line = (
        f"{version} {index_offset:0{hex_offset_width}x} {key:0{hex_key_width}x}{trailing}\n".encode(
            "ascii"
        )
    )
    assert len(header_line) == header_len
    with open(path, "wb") as f:
        f.write(header_line)
        f.write(payload)
        f.write(index_bytes)


def _index_with_archive(tmp_path: Path, files: dict, **kw) -> tuple[AssetManager, Path]:
    """Build a project with one .rpa archive under game/ and index it."""
    game = tmp_path / "game"
    game.mkdir()
    rpa = game / "archive.rpa"
    _make_rpa(rpa, files, **kw)
    am = AssetManager(str(tmp_path))
    am.index()
    return am, rpa


# ---------------------------------------------------------------------------
# Hits by name form
# ---------------------------------------------------------------------------


class TestResolveAssetInArchiveHits:
    def test_full_path_hit(self, tmp_path: Path) -> None:
        am, rpa = _index_with_archive(tmp_path, {"game/images/bg.png": b"\x89PNG fake"})
        hit = am.resolve_asset_in_archive("game/images/bg.png")
        assert hit is not None
        archive_path, offset, length, prefix = hit
        assert archive_path == str(rpa)
        assert length == len(b"\x89PNG fake")
        assert prefix == b""

    def test_game_stripped_hit(self, tmp_path: Path) -> None:
        """`images/bg.png` must resolve to `game/images/bg.png`."""
        am, _ = _index_with_archive(tmp_path, {"game/images/bg.png": b"\x89PNG fake"})
        assert am.resolve_asset_in_archive("images/bg.png") is not None

    def test_basename_hit(self, tmp_path: Path) -> None:
        """`bg.png` matches via the basename scan fallback."""
        am, rpa = _index_with_archive(tmp_path, {"game/images/bg.png": b"\x89PNG fake"})
        hit = am.resolve_asset_in_archive("bg.png")
        assert hit is not None
        assert hit[0] == str(rpa)

    def test_case_insensitive_hit(self, tmp_path: Path) -> None:
        """Original-case references resolve against lowercased cache keys."""
        am, _ = _index_with_archive(tmp_path, {"game/images/BG.PNG": b"\x89PNG fake"})
        assert am.resolve_asset_in_archive("Game/Images/BG.PNG") is not None
        assert am.resolve_asset_in_archive("GAME/IMAGES/bg.png") is not None

    def test_underscore_space_variant_hit(self, tmp_path: Path) -> None:
        """`blue_sky.png` and `blue sky.png` both find the same entry."""
        am, _ = _index_with_archive(tmp_path, {"game/images/blue_sky.png": b"\x89PNG fake"})
        assert am.resolve_asset_in_archive("game/images/blue sky.png") is not None

    def test_prefix_preserved_in_tuple(self, tmp_path: Path) -> None:
        am, _ = _index_with_archive(
            tmp_path, {"game/s.rpy": (b"label start:\n    return\n", b"# hdr\n")}
        )
        hit = am.resolve_asset_in_archive("game/s.rpy")
        assert hit is not None
        _, _, _, prefix = hit
        assert prefix == b"# hdr\n"


# ---------------------------------------------------------------------------
# Tuple correctness + end-to-end read
# ---------------------------------------------------------------------------


class TestResolveTupleCorrectness:
    def test_tuple_matches_entry_first_segment(self, tmp_path: Path) -> None:
        am, rpa = _index_with_archive(tmp_path, {"game/images/bg.png": b"\x89PNG fake"})
        hit = am.resolve_asset_in_archive("game/images/bg.png")
        assert hit is not None
        idx = am.rpa_index_cache[str(rpa)]
        entry = idx.entries["game/images/bg.png"]
        seg = entry.segments[0]
        assert hit == (str(rpa), seg.offset, seg.length, seg.prefix)

    def test_tuple_is_end_to_end_readable(self, tmp_path: Path) -> None:
        """The returned tuple must be usable to actually read the asset bytes:
        reconstruct an RpaSegment and feed it to read_rpa_segment."""
        data = b"\x89PNG\r\n fake png bytes \n"
        am, rpa = _index_with_archive(tmp_path, {"game/images/bg.png": data})
        hit = am.resolve_asset_in_archive("bg.png")
        assert hit is not None
        archive_path, offset, length, prefix = hit
        seg = RpaSegment(offset, length, prefix)
        with open(archive_path, "rb") as f:
            assert read_rpa_segment(f, seg) == prefix + data

    def test_nonzero_key_archive_resolves_decoded(self, tmp_path: Path) -> None:
        """With a non-zero XOR key the returned offset/length are decoded."""
        am, rpa = _index_with_archive(
            tmp_path, {"game/images/bg.png": b"\x89PNG fake"}, key=0xCAFEBABE
        )
        hit = am.resolve_asset_in_archive("game/images/bg.png")
        assert hit is not None
        archive_path, offset, length, prefix = hit
        seg = RpaSegment(offset, length, prefix)
        with open(archive_path, "rb") as f:
            assert read_rpa_segment(f, seg) == b"\x89PNG fake"


# ---------------------------------------------------------------------------
# Misses + edge cases
# ---------------------------------------------------------------------------


class TestResolveAssetInArchiveMisses:
    def test_miss_returns_none(self, tmp_path: Path) -> None:
        am, _ = _index_with_archive(tmp_path, {"game/images/bg.png": b"\x89PNG fake"})
        assert am.resolve_asset_in_archive("game/images/missing.png") is None

    def test_empty_name_returns_none(self, tmp_path: Path) -> None:
        am, _ = _index_with_archive(tmp_path, {"game/images/bg.png": b"\x89PNG fake"})
        assert am.resolve_asset_in_archive("") is None

    def test_no_archives_returns_none(self, tmp_path: Path) -> None:
        """An empty rpa_index_cache must return None, not raise."""
        am = AssetManager(str(tmp_path))
        am.index()
        assert am.rpa_index_cache == {}
        assert am.resolve_asset_in_archive("anything.png") is None

    def test_basename_miss_does_not_false_match(self, tmp_path: Path) -> None:
        """`bg.jpg` must not match `bg.png` (basename scan is exact, not prefix)."""
        am, _ = _index_with_archive(tmp_path, {"game/images/bg.png": b"\x89PNG fake"})
        assert am.resolve_asset_in_archive("bg.jpg") is None


# ---------------------------------------------------------------------------
# Multi-archive
# ---------------------------------------------------------------------------


class TestResolveAssetInArchiveMultiArchive:
    def test_asset_in_multiple_archives_resolves(self, tmp_path: Path) -> None:
        """When an asset lives in two archives, resolve still finds it —
        returns one of the containing archives with a readable segment.

        Which archive is returned follows ``rpa_index_cache`` insertion
        order, which mirrors the filesystem walk (``os.walk`` / ``readdir``)
        order — that is stable for a given directory state but is NOT
        alphabetically guaranteed across environments. So we assert the
        result is one of the two archives and that its segment decodes to
        one of the two payloads, not which archive "wins"."""
        game = tmp_path / "game"
        game.mkdir()
        rpa1 = game / "a.rpa"
        rpa2 = game / "b.rpa"
        _make_rpa(rpa1, {"game/images/bg.png": b"from-archive-1"})
        _make_rpa(rpa2, {"game/images/bg.png": b"from-archive-2"})
        am = AssetManager(str(tmp_path))
        am.index()
        hit = am.resolve_asset_in_archive("game/images/bg.png")
        assert hit is not None
        archive_path, offset, length, prefix = hit
        assert archive_path in {str(rpa1), str(rpa2)}
        seg = RpaSegment(offset, length, prefix)
        with open(archive_path, "rb") as f:
            data = read_rpa_segment(f, seg)
        assert data in {b"from-archive-1", b"from-archive-2"}

    def test_asset_in_second_archive_found(self, tmp_path: Path) -> None:
        """An asset that lives only in the second archive is still resolved."""
        game = tmp_path / "game"
        game.mkdir()
        rpa1 = game / "a.rpa"
        rpa2 = game / "b.rpa"
        _make_rpa(rpa1, {"game/images/bg.png": b"bg"})
        _make_rpa(rpa2, {"game/audio/bgm.ogg": b"OggS fake"})
        am = AssetManager(str(tmp_path))
        am.index()
        hit = am.resolve_asset_in_archive("bgm.ogg")
        assert hit is not None
        assert hit[0] == str(rpa2)

    def test_different_assets_in_different_archives(self, tmp_path: Path) -> None:
        game = tmp_path / "game"
        game.mkdir()
        rpa1 = game / "a.rpa"
        rpa2 = game / "b.rpa"
        _make_rpa(rpa1, {"game/images/bg.png": b"png"})
        _make_rpa(rpa2, {"game/audio/bgm.ogg": b"ogg"})
        am = AssetManager(str(tmp_path))
        am.index()
        assert am.resolve_asset_in_archive("bg.png")[0] == str(rpa1)
        assert am.resolve_asset_in_archive("bgm.ogg")[0] == str(rpa2)


# ---------------------------------------------------------------------------
# Audio + non-image assets (resolve is generic, not image-only)
# ---------------------------------------------------------------------------


class TestResolveAssetInArchiveGeneric:
    def test_audio_asset_by_basename(self, tmp_path: Path) -> None:
        am, rpa = _index_with_archive(tmp_path, {"game/audio/bgm_calm.ogg": b"OggS fake"})
        hit = am.resolve_asset_in_archive("bgm_calm.ogg")
        assert hit is not None
        assert hit[0] == str(rpa)

    def test_rpyc_asset_resolvable(self, tmp_path: Path) -> None:
        """resolve_asset_in_archive is generic — it finds any file in an
        archive, not just images/audio (the image/audio specificity is the
        consumer's job, e.g. RPA-11 hover checks the extension)."""
        am, _ = _index_with_archive(tmp_path, {"game/script.rpyc": b"rpyc bytes"})
        assert am.resolve_asset_in_archive("game/script.rpyc") is not None
