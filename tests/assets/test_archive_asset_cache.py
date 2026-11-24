"""Unit tests for ``senpy.domain.archive_asset_cache.extract_asset_to_cache`` (RPA-9).

Covers: single + multi-segment extraction, mtime cache hit (no re-read) and
invalidation, path-traversal refusal, per-archive cache discrimination,
subdir preservation, isolation under the cache root, and failure modes
(unreadable archive, empty segments).
"""

from __future__ import annotations

import os
import pickle
import zlib
from pathlib import Path

import pytest

from senpy.domain.archive_asset_cache import (
    DEFAULT_CACHE_ROOT,
    _cache_dir_for,
    extract_asset_to_cache,
)
from senpy.domain.rpa import RpaEntry, RpaSegment, parse_rpa_archive

# =============================================================================
# Helpers
# =============================================================================


def _make_rpa(
    path: Path,
    entries: dict[str, list[tuple[bytes, bytes]]],
    *,
    key: int = 0,
) -> None:
    """Write a minimal RPA-3.0 archive to *path*.

    *entries* maps filename -> list of ``(data, prefix)`` segments (a
    single-segment file passes ``[(data, b"")]``). Each segment is stored
    XOR'd with *key*: ``(offset ^ key, len(data) ^ key, prefix)``. Canonical
    16-hex offset + 8-hex key + trailing-space header.
    """
    version = "RPA-3.0"
    header_len = len(version) + 1 + 16 + 1 + 8 + 1 + 1  # space + trailing + \n

    payload = b""
    index: dict[str, list[tuple[int, int, bytes]]] = {}
    pos = 0
    for fn, segs in entries.items():
        idx_segs: list[tuple[int, int, bytes]] = []
        for data, prefix in segs:
            seg_offset = header_len + pos
            idx_segs.append((seg_offset ^ key, len(data) ^ key, prefix))
            payload += data
            pos += len(data)
        index[fn] = idx_segs

    index_bytes = zlib.compress(pickle.dumps(index))
    index_offset = header_len + len(payload)
    header = f"{version} {index_offset:016x} {key:08x} \n".encode("ascii")
    assert len(header) == header_len
    with open(path, "wb") as f:
        f.write(header)
        f.write(payload)
        f.write(index_bytes)


def _entry_for(rpa_path: Path, filename: str) -> RpaEntry:
    """Parse *rpa_path* and return the RpaEntry for *filename*."""
    idx = parse_rpa_archive(str(rpa_path))
    assert idx is not None, "archive failed to parse"
    key = filename.replace("\\", "/").lower()
    assert key in idx.entries, f"{filename!r} not in {list(idx.entries)}"
    return idx.entries[key]


# =============================================================================
# Extraction correctness
# =============================================================================


class TestExtractAssetToCache:
    def test_single_segment(self, tmp_path: Path) -> None:
        rpa = tmp_path / "game" / "archive.rpa"
        rpa.parent.mkdir(parents=True)
        data = b"\x89PNG fake body"
        _make_rpa(rpa, {"game/images/bg.png": [(data, b"")]})
        entry = _entry_for(rpa, "game/images/bg.png")

        cache_root = tmp_path / "cache"
        path = extract_asset_to_cache(entry, cache_root=str(cache_root))
        assert path is not None
        assert os.path.exists(path)
        assert Path(path).read_bytes() == data

    def test_multi_segment_with_prefix(self, tmp_path: Path) -> None:
        """Two segments, each with its own prefix — concatenated bytes must
        equal prefix0+data0+prefix1+data1 (RPA-4: prefix is prepended per
        segment, never subtracted from length)."""
        rpa = tmp_path / "game" / "archive.rpa"
        rpa.parent.mkdir(parents=True)
        seg0 = (b"BODY-A", b"HDR-A")
        seg1 = (b"BODY-B", b"")
        _make_rpa(rpa, {"game/song.ogg": [seg0, seg1]})
        entry = _entry_for(rpa, "game/song.ogg")

        path = extract_asset_to_cache(entry, cache_root=str(tmp_path / "cache"))
        assert path is not None
        assert Path(path).read_bytes() == b"HDR-A" + b"BODY-A" + b"" + b"BODY-B"

    def test_nonzero_key_decodes(self, tmp_path: Path) -> None:
        """An obfuscated archive (key != 0) extracts correctly — the key was
        applied at parse time, so extraction is key-agnostic."""
        rpa = tmp_path / "game" / "archive.rpa"
        rpa.parent.mkdir(parents=True)
        data = b"secret bytes"
        _make_rpa(rpa, {"game/bg.png": [(data, b"")]}, key=0xDEADBEEF)
        entry = _entry_for(rpa, "game/bg.png")
        path = extract_asset_to_cache(entry, cache_root=str(tmp_path / "cache"))
        assert path is not None
        assert Path(path).read_bytes() == data

    def test_preserves_subdir(self, tmp_path: Path) -> None:
        rpa = tmp_path / "game" / "archive.rpa"
        rpa.parent.mkdir(parents=True)
        _make_rpa(rpa, {"game/images/eileen/happy.png": [(b"png", b"")]})
        entry = _entry_for(rpa, "game/images/eileen/happy.png")
        path = extract_asset_to_cache(entry, cache_root=str(tmp_path / "cache"))
        assert path is not None
        # The subdir structure is preserved within the per-archive cache dir.
        assert path.endswith(os.path.join("game", "images", "eileen", "happy.png"))

    def test_per_archive_discriminator(self, tmp_path: Path) -> None:
        """Two archives (different paths) with the same entry filename land
        in different cache subdirs — no collision."""
        a1 = tmp_path / "game" / "a.rpa"
        a2 = tmp_path / "game" / "b.rpa"
        a1.parent.mkdir(parents=True)
        _make_rpa(a1, {"game/bg.png": [(b"from-a", b"")]})
        _make_rpa(a2, {"game/bg.png": [(b"from-b", b"")]})
        cache_root = tmp_path / "cache"
        p1 = extract_asset_to_cache(_entry_for(a1, "game/bg.png"), cache_root=str(cache_root))
        p2 = extract_asset_to_cache(_entry_for(a2, "game/bg.png"), cache_root=str(cache_root))
        assert p1 is not None and p2 is not None
        assert p1 != p2
        assert Path(p1).read_bytes() == b"from-a"
        assert Path(p2).read_bytes() == b"from-b"

    def test_isolation_under_cache_root(self, tmp_path: Path) -> None:
        """The extracted path is under the cache root, never under the
        project tree."""
        rpa = tmp_path / "game" / "archive.rpa"
        rpa.parent.mkdir(parents=True)
        _make_rpa(rpa, {"game/bg.png": [(b"png", b"")]})
        entry = _entry_for(rpa, "game/bg.png")
        cache_root = tmp_path / "cache"
        path = extract_asset_to_cache(entry, cache_root=str(cache_root))
        assert path is not None
        assert os.path.commonpath([os.path.abspath(path), str(cache_root)]) == str(cache_root)
        # Not under the project's game dir.
        assert os.path.commonpath([os.path.abspath(path), str(tmp_path / "game")]) != str(
            tmp_path / "game"
        )


# =============================================================================
# Cache + invalidation
# =============================================================================


class TestExtractAssetCacheInvalidation:
    def test_cache_hit_skips_reextract(self, tmp_path: Path, monkeypatch) -> None:
        """A second call reuses the cached file without re-reading the
        archive (read_rpa_segment is not called again)."""
        import senpy.domain.archive_asset_cache as aac

        rpa = tmp_path / "game" / "archive.rpa"
        rpa.parent.mkdir(parents=True)
        _make_rpa(rpa, {"game/bg.png": [(b"png-bytes", b"")]})
        entry = _entry_for(rpa, "game/bg.png")

        calls: list = []
        real = aac.read_rpa_segment

        def counting(f, seg):
            calls.append(seg)
            return real(f, seg)

        monkeypatch.setattr(aac, "read_rpa_segment", counting)

        cache_root = str(tmp_path / "cache")
        p1 = extract_asset_to_cache(entry, cache_root=cache_root)
        n_after_first = len(calls)
        assert p1 is not None
        p2 = extract_asset_to_cache(entry, cache_root=cache_root)
        assert p2 == p1
        # No segment reads on the cache hit.
        assert len(calls) == n_after_first

    def test_mtime_invalidation_reextracts(self, tmp_path: Path) -> None:
        """When the archive is newer than the cached file, extraction
        re-reads and overwrites the stale cache."""
        rpa = tmp_path / "game" / "archive.rpa"
        rpa.parent.mkdir(parents=True)
        _make_rpa(rpa, {"game/bg.png": [(b"old", b"")]})
        entry = _entry_for(rpa, "game/bg.png")
        cache_root = str(tmp_path / "cache")

        p1 = extract_asset_to_cache(entry, cache_root=cache_root)
        assert p1 is not None
        assert Path(p1).read_bytes() == b"old"

        # Rewrite the archive with new content + a future mtime so the cache
        # is definitively stale.
        _make_rpa(rpa, {"game/bg.png": [(b"new", b"")]})
        future = (os.path.getmtime(rpa) + 100,) * 2
        os.utime(rpa, future)
        # entry still points at the same archive path; reparse to refresh
        # segment offsets (they shifted if payload length changed).
        entry = _entry_for(rpa, "game/bg.png")

        p2 = extract_asset_to_cache(entry, cache_root=cache_root)
        assert p2 == p1  # same cache path, overwritten in place
        assert Path(p2).read_bytes() == b"new"


# =============================================================================
# Security + failure
# =============================================================================


class TestExtractAssetSecurityAndFailure:
    def test_path_traversal_refused(self, tmp_path: Path) -> None:
        """An entry filename like ``../../evil.png`` is refused — no file is
        written outside the cache root."""
        rpa = tmp_path / "game" / "archive.rpa"
        rpa.parent.mkdir(parents=True)
        _make_rpa(rpa, {"../../evil.png": [(b"pwned", b"")]})
        entry = _entry_for(rpa, "../../evil.png")
        cache_root = tmp_path / "cache"
        path = extract_asset_to_cache(entry, cache_root=str(cache_root))
        assert path is None
        # And nothing escaped: no evil.png anywhere under tmp_path's parent.
        assert not list(tmp_path.rglob("evil.png"))

    def test_unreadable_archive_returns_none(self, tmp_path: Path) -> None:
        """If the archive vanished (or is unreadable), extraction returns
        None — the hover falls back to the hint."""
        rpa = tmp_path / "game" / "archive.rpa"
        rpa.parent.mkdir(parents=True)
        _make_rpa(rpa, {"game/bg.png": [(b"png", b"")]})
        entry = _entry_for(rpa, "game/bg.png")
        rpa.unlink()  # archive gone
        path = extract_asset_to_cache(entry, cache_root=str(tmp_path / "cache"))
        assert path is None

    def test_empty_segments_returns_none(self, tmp_path: Path) -> None:
        """An entry with no segments yields no extraction (defensive —
        parse_rpa_archive drops zero-segment entries, but a hand-built
        RpaEntry must still be handled)."""
        entry = RpaEntry("game/bg.png", (), str(tmp_path / "archive.rpa"))
        path = extract_asset_to_cache(entry, cache_root=str(tmp_path / "cache"))
        assert path is None


def test_cache_dir_for_is_stable_and_discriminating(tmp_path: Path) -> None:
    """``_cache_dir_for`` is deterministic for a given archive path and
    differs across archives (so the shared cache root does not collide)."""
    root = str(tmp_path / "cache")
    a = str(tmp_path / "game" / "a.rpa")
    b = str(tmp_path / "game" / "b.rpa")
    assert _cache_dir_for(a, root) == _cache_dir_for(a, root)
    assert _cache_dir_for(a, root) != _cache_dir_for(b, root)
    # And lives under root.
    assert _cache_dir_for(a, root).startswith(root)


def test_default_cache_root_is_under_senpy() -> None:
    """The default cache root lives under ``~/.senpy`` (mirrors the
    ``SENPY_CACHE_DIR`` convention used by the unrpyc tool cache)."""
    assert DEFAULT_CACHE_ROOT.endswith(".senpy/archive_assets")
    assert ".senpy" in DEFAULT_CACHE_ROOT
