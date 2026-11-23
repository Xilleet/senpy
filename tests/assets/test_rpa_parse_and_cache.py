"""Tests for the unified RPA data model, parser and segment reader.

These cover the 0.9.4 refactor that collapsed the two parallel RPA readers
(``assets.py:_read_rpa_index`` with its fixed-width ``header[8:24]`` slice and
``unrpyc.py:extract_scripts_from_rpa`` with its whitespace-split parse) into a
single ``parse_rpa_archive`` + ``read_rpa_segment`` pair living in
``senpy/domain/rpa.py``.

Scope:
  * ``RpaSegment`` / ``RpaEntry`` / ``RpaArchiveIndex`` construction.
  * ``parse_rpa_archive``: header parsing for RPA-2.0 / RPA-3.0, XOR key
    decoding, prefix preservation, defensive handling of malformed
    segments / non-str keys, and the latent fixed-width-parser bug (archives
    whose offset field is not exactly 16 hex chars wide).
  * ``read_rpa_segment``: offset/length read + prefix prepend (RPA-4
    semantics preserved by the DRY reader).
  * ``AssetManager.rpa_index_cache`` (RPA-1): populated on ``index()``,
    ``known_assets`` registration unchanged, cleared on re-index.
"""

from __future__ import annotations

import io
import os
import pickle
import zlib
from pathlib import Path

import pytest

from senpy.domain.assets import AssetManager
from senpy.domain.rpa import (
    RpaArchiveIndex,
    RpaEntry,
    RpaSegment,
    parse_rpa_archive,
    read_rpa_segment,
)

# ---------------------------------------------------------------------------
# Archive fixture builder — reproduces BOTH real-world header widths:
#   * 16-hex offset + 8-hex key + trailing space  (test_rpa_prefix_bug format)
#   *  8-hex offset + 16-hex key, no trailing space (test_unrpyc_helpers format)
# The previous fixed-width ``header[8:24]`` parser in assets.py could only
# handle the first; the unified whitespace-split parser handles both.
# ---------------------------------------------------------------------------


def _make_rpa(
    path: Path,
    files: dict[str, tuple[bytes, bytes] | bytes],
    *,
    version: str = "RPA-3.0",
    key: int = 0,
    hex_offset_width: int = 16,
    hex_key_width: int = 8,
    trailing_space: bool = True,
) -> None:
    """Write a real RPA archive to *path*.

    Each entry is ``filename -> (data, prefix)`` or ``filename -> data``
    (prefix defaults to ``b""``). The data section holds only the file DATA;
    prefix is stored in the index and prepended at read time (RPA-4
    semantics). Segments are stored XOR'd with *key*:
    ``(data_offset ^ key, len(data) ^ key, prefix)``.
    """
    norm: dict[str, tuple[bytes, bytes]] = {}
    for name, val in files.items():
        if isinstance(val, tuple):
            data, prefix = val
        else:
            data, prefix = val, b""
        norm[name] = (data, prefix)

    trailing = " " if trailing_space else ""
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
    assert len(header_line) == header_len, (len(header_line), header_len)
    with open(path, "wb") as f:
        f.write(header_line)
        f.write(payload)
        f.write(index_bytes)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


class TestRpaDataclasses:
    def test_rpa_segment_is_frozen(self) -> None:
        seg = RpaSegment(offset=10, length=20, prefix=b"ab")
        assert seg.offset == 10
        assert seg.length == 20
        assert seg.prefix == b"ab"
        with pytest.raises((AttributeError, TypeError)):
            seg.offset = 99  # type: ignore[misc]

    def test_rpa_entry_is_frozen_and_keeps_original_case(self) -> None:
        seg = RpaSegment(0, 5, b"")
        entry = RpaEntry(filename="Game/Img.PNG", segments=(seg,), archive_path="/x/a.rpa")
        assert entry.filename == "Game/Img.PNG"  # original case preserved
        assert entry.archive_path == "/x/a.rpa"
        assert entry.segments == (seg,)

    def test_rpa_archive_index_holds_key_and_entries(self) -> None:
        seg = RpaSegment(0, 5, b"")
        entry = RpaEntry("a.rpy", (seg,), "/x/a.rpa")
        idx = RpaArchiveIndex(
            "/x/a.rpa", key=0xCAFEBABE, version="RPA-3.0", entries={"a.rpy": entry}
        )
        assert idx.key == 0xCAFEBABE
        assert idx.version == "RPA-3.0"
        assert idx.entries["a.rpy"] is entry


# ---------------------------------------------------------------------------
# parse_rpa_archive
# ---------------------------------------------------------------------------


class TestParseRpaArchive:
    def test_non_rpa_file_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "not.rpa"
        p.write_bytes(b"just some text, not an RPA archive")
        assert parse_rpa_archive(str(p)) is None

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.rpa"
        p.write_bytes(b"")
        assert parse_rpa_archive(str(p)) is None

    def test_wrong_magic_returns_none(self, tmp_path: Path) -> None:
        # Magic token "RPA-3.0X" must NOT be accepted (exact-token match).
        p = tmp_path / "bad.rpa"
        p.write_bytes(b"RPA-3.0X 0000000000000022 00000000 \n")
        assert parse_rpa_archive(str(p)) is None

    def test_rpa_3_0_key_zero_decodes_segments(self, tmp_path: Path) -> None:
        p = tmp_path / "a.rpa"
        _make_rpa(p, {"game/script.rpyc": b"hello rpyc"})
        idx = parse_rpa_archive(str(p))
        assert idx is not None
        assert idx.version == "RPA-3.0"
        assert idx.key == 0
        entry = idx.entries["game/script.rpyc"]
        assert entry.filename == "game/script.rpyc"
        assert entry.archive_path == str(p)
        assert len(entry.segments) == 1
        seg = entry.segments[0]
        # Reading the segment yields the original data.
        with open(p, "rb") as f:
            assert read_rpa_segment(f, seg) == b"hello rpyc"

    def test_rpa_3_0_nonzero_key_xor_decoded(self, tmp_path: Path) -> None:
        """Segments stored XOR'd with a non-zero key must be decoded on parse."""
        p = tmp_path / "a.rpa"
        key = 0xCAFEBABE
        _make_rpa(p, {"game/s.rpy": b"label start:\n    return\n"}, key=key)
        idx = parse_rpa_archive(str(p))
        assert idx is not None
        assert idx.key == key
        seg = idx.entries["game/s.rpy"].segments[0]
        with open(p, "rb") as f:
            assert read_rpa_segment(f, seg) == b"label start:\n    return\n"

    def test_rpa_2_0_has_key_zero(self, tmp_path: Path) -> None:
        p = tmp_path / "a.rpa"
        _make_rpa(p, {"scene.rpyc": b"rpyc data"}, version="RPA-2.0")
        idx = parse_rpa_archive(str(p))
        assert idx is not None
        assert idx.version == "RPA-2.0"
        # RPA-2.0 has no key field — parser defaults to 0.
        assert idx.key == 0
        with open(p, "rb") as f:
            assert read_rpa_segment(f, idx.entries["scene.rpyc"].segments[0]) == b"rpyc data"

    def test_prefix_preserved_in_segment(self, tmp_path: Path) -> None:
        p = tmp_path / "a.rpa"
        _make_rpa(p, {"game/s.rpy": (b"label start:\n    return\n", b"# from archive\n")})
        idx = parse_rpa_archive(str(p))
        assert idx is not None
        seg = idx.entries["game/s.rpy"].segments[0]
        assert seg.prefix == b"# from archive\n"
        with open(p, "rb") as f:
            assert read_rpa_segment(f, seg) == b"# from archive\nlabel start:\n    return\n"

    def test_8_hex_offset_parses_correctly(self, tmp_path: Path) -> None:
        """Latent-bug guard: the OLD fixed-width ``header[8:24]`` parser in
        assets.py silently mis-parsed archives whose offset field was 8 hex
        chars (the ``_make_rpa_archive`` fixture format) — it grabbed a
        space + key digits and raised ValueError. The unified split parser
        must read this format correctly."""
        p = tmp_path / "a.rpa"
        _make_rpa(
            p,
            {"game/script.rpyc": b"fake rpyc bytes"},
            version="RPA-2.0",
            hex_offset_width=8,
            hex_key_width=16,
            trailing_space=False,
        )
        idx = parse_rpa_archive(str(p))
        assert idx is not None
        with open(p, "rb") as f:
            assert (
                read_rpa_segment(f, idx.entries["game/script.rpyc"].segments[0])
                == b"fake rpyc bytes"
            )

    def test_non_str_filename_skipped(self, tmp_path: Path) -> None:
        """A non-str key in the index (malformed) must be skipped, not crash."""
        p = tmp_path / "a.rpa"
        # Hand-craft: valid header, but the pickle root has an int key.
        key = 0
        bad_index = {1: [("v",)]}  # int filename, garbage segment
        header_len = 35  # standard RPA-3.0 16/8 + trailing space
        index_bytes = zlib.compress(pickle.dumps(bad_index))
        header = f"RPA-3.0 {header_len:016x} {key:08x} \n".encode("ascii")
        assert len(header) == header_len
        with open(p, "wb") as f:
            f.write(header)
            f.write(index_bytes)
        idx = parse_rpa_archive(str(p))
        assert idx is not None
        assert idx.entries == {}  # the int-keyed entry was dropped

    def test_malformed_segment_skipped_entry_kept_if_has_good_one(self, tmp_path: Path) -> None:
        """An entry with one bad segment and one good segment must keep the
        good one (defensive decoding) rather than aborting the archive."""
        p = tmp_path / "a.rpa"
        # Build a valid archive shell, then rewrite the index with a mixed
        # segment list for one file: [(bad), (good)].
        data = b"good-data-bytes"
        key = 0
        header_len = 35
        data_offset = header_len
        good_seg = (data_offset ^ key, len(data) ^ key, b"")
        bad_seg = ("not-an-int", len(data) ^ key, b"")  # non-int offset
        index = {"game/s.rpy": [bad_seg, good_seg]}
        index_bytes = zlib.compress(pickle.dumps(index))
        header = f"RPA-3.0 {(header_len + len(data)):016x} {key:08x} \n".encode("ascii")
        assert len(header) == header_len
        with open(p, "wb") as f:
            f.write(header)
            f.write(data)
            f.write(index_bytes)
        idx = parse_rpa_archive(str(p))
        assert idx is not None
        entry = idx.entries["game/s.rpy"]
        # Only the good segment survived.
        assert len(entry.segments) == 1
        with open(p, "rb") as f:
            assert read_rpa_segment(f, entry.segments[0]) == data

    def test_missing_file_raises_oserror(self, tmp_path: Path) -> None:
        with pytest.raises(OSError):
            parse_rpa_archive(str(tmp_path / "nope.rpa"))


# ---------------------------------------------------------------------------
# read_rpa_segment
# ---------------------------------------------------------------------------


class TestReadRpaSegment:
    def test_reads_data_at_offset(self, tmp_path: Path) -> None:
        p = tmp_path / "a.rpa"
        _make_rpa(p, {"f.bin": b"0123456789"})
        idx = parse_rpa_archive(str(p))
        assert idx is not None
        seg = idx.entries["f.bin"].segments[0]
        with open(p, "rb") as f:
            assert read_rpa_segment(f, seg) == b"0123456789"

    def test_empty_prefix_returns_just_data(self) -> None:
        seg = RpaSegment(offset=0, length=4, prefix=b"")
        buf = io.BytesIO(b"ABCDXXXX")
        assert read_rpa_segment(buf, seg) == b"ABCD"

    def test_prefix_prepended_not_subtracted_from_length(self) -> None:
        """RPA-4 semantics: prefix is prepended AFTER reading length bytes;
        length is NOT reduced by len(prefix)."""
        seg = RpaSegment(offset=0, length=4, prefix=b"PQ")
        buf = io.BytesIO(b"ABCDXXXX")
        # Must be PQ + 4 data bytes = "PQABCD", not "PQAB" (truncated).
        assert read_rpa_segment(buf, seg) == b"PQABCD"

    def test_multiple_segments_concatenated(self, tmp_path: Path) -> None:
        p = tmp_path / "a.rpa"
        _make_rpa(
            p,
            {"f.bin": b"AAAA", "g.bin": b"BBBB"},
        )
        idx = parse_rpa_archive(str(p))
        assert idx is not None
        with open(p, "rb") as f:
            out = b"".join(
                read_rpa_segment(f, seg)
                for seg in idx.entries["f.bin"].segments + idx.entries["g.bin"].segments
            )
        assert out == b"AAAABBBB"


# ---------------------------------------------------------------------------
# AssetManager.rpa_index_cache
# ---------------------------------------------------------------------------


class TestAssetManagerRpaIndexCache:
    def test_cache_populated_after_index(self, tmp_path: Path) -> None:
        game = tmp_path / "game"
        game.mkdir()
        rpa = game / "archive.rpa"
        _make_rpa(
            rpa,
            {
                "game/images/bg.png": b"\x89PNG fake",
                "game/script.rpyc": b"rpyc-bytes",
            },
        )
        am = AssetManager(str(tmp_path))
        am.index()

        # RPA-1: cache holds the parsed archive.
        assert str(rpa) in am.rpa_index_cache
        idx = am.rpa_index_cache[str(rpa)]
        assert isinstance(idx, RpaArchiveIndex)
        # Both entries indexed by lowercased filename.
        assert "game/images/bg.png" in idx.entries
        assert "game/script.rpyc" in idx.entries
        # Segments preserved (not discarded like pre-0.9.4).
        assert idx.entries["game/images/bg.png"].segments[0].length == len(b"\x89PNG fake")

    def test_known_assets_registration_unchanged(self, tmp_path: Path) -> None:
        """non-breaking contract: known_assets still gets the names."""
        game = tmp_path / "game"
        game.mkdir()
        rpa = game / "archive.rpa"
        _make_rpa(rpa, {"game/images/bg.png": b"\x89PNG fake"})
        am = AssetManager(str(tmp_path))
        am.index()
        # The .rpa file itself is NOT a known asset (build artifact)...
        assert "game/archive.rpa" not in am.known_assets
        # ...but its CONTENTS are registered (with and without game/ prefix).
        assert "game/images/bg.png" in am.known_assets
        assert "images/bg.png" in am.known_assets
        assert "bg.png" in am.known_assets

    def test_cache_cleared_on_reindex(self, tmp_path: Path) -> None:
        """A deleted archive must not linger in rpa_index_cache after re-index
        (mirrors the known_assets stale-cache regression test)."""
        game = tmp_path / "game"
        game.mkdir()
        rpa = game / "archive.rpa"
        _make_rpa(rpa, {"game/images/bg.png": b"\x89PNG fake"})
        am1 = AssetManager(str(tmp_path))
        am1.index()
        assert str(rpa) in am1.rpa_index_cache

        rpa.unlink()  # delete the archive

        am2 = AssetManager(str(tmp_path))
        am2.index()
        assert str(rpa) not in am2.rpa_index_cache
        assert "game/images/bg.png" not in am2.known_assets

    def test_malformed_archive_does_not_crash_or_populate_cache(self, tmp_path: Path) -> None:
        """A corrupt archive (pickle root is a list) must be logged+skipped:
        no cache entry, no crash, known_assets unaffected."""
        game = tmp_path / "game"
        game.mkdir()
        rpa = game / "evil.rpa"
        # pickle root = list, not dict — safe_load_rpa_index raises TypeError.
        bad = zlib.compress(pickle.dumps(["not", "a", "dict"]))
        header = f"RPA-3.0 0000000000000022 {0:08x} \n".encode("ascii")
        with open(rpa, "wb") as f:
            f.write(header)
            f.write(bad)
        am = AssetManager(str(tmp_path))
        am.index()  # must not raise
        assert str(rpa) not in am.rpa_index_cache

    def test_original_case_preserved_in_entry_filename(self, tmp_path: Path) -> None:
        """The cache keeps original-case filenames (extraction-faithful),
        while known_assets lowercases for matching."""
        game = tmp_path / "game"
        game.mkdir()
        rpa = game / "archive.rpa"
        _make_rpa(rpa, {"game/Images/BG.PNG": b"\x89PNG fake"})
        am = AssetManager(str(tmp_path))
        am.index()
        idx = am.rpa_index_cache[str(rpa)]
        # Entry keeps original case...
        assert idx.entries["game/images/bg.png"].filename == "game/Images/BG.PNG"
        # ...while known_assets matched on the lowercased form.
        assert "game/images/bg.png" in am.known_assets
