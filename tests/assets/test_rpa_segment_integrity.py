"""Length-integrity validation for ``read_rpa_segment``.

``read_rpa_segment`` now compares ``len(read_data)`` to ``segment.length``
and raises ``ValueError`` on a short read (truncated archive, segment offset
beyond EOF, or an index claiming more bytes than the data region holds),
instead of silently returning a partial segment. Callers that catch
``ValueError`` skip the affected entry: ``extract_scripts_from_rpa`` skips
one bad entry and continues with the rest (warn); ``extract_asset_to_cache``
returns ``None`` so the hover falls back to the hint.
"""

from __future__ import annotations

import os
import pickle
import zlib
from pathlib import Path

import pytest

from senpy.cli.unrpyc import extract_scripts_from_rpa
from senpy.domain.archive_asset_cache import extract_asset_to_cache
from senpy.domain.rpa import parse_rpa_archive, read_rpa_segment

# RPA-3.0 header: "RPA-3.0 " + 16-hex offset + " " + 8-hex key + " \n" = 35 bytes.
_VERSION = "RPA-3.0"
_HEADER_LEN = len(_VERSION) + 1 + 16 + 1 + 8 + 1 + 1


def _make_rpa(
    path: Path,
    entries: dict[str, list[tuple[int, int, bytes]]],
    *,
    payload: bytes = b"",
    key: int = 0,
) -> None:
    """Write a minimal RPA-3.0 archive whose index stores the EXACT segment
    tuples given (offset, length, prefix) XOR'd with *key*.

    Unlike a normal archive builder, the offsets need NOT point at real data:
    a tuple like ``(999_999, 100, b"")`` crafts a segment that reads past EOF,
    exercising the RPA-5 short-read check. *payload* is written verbatim
    between the header and the index; valid segments point into it.
    """
    index: dict[str, list[tuple[int, int, bytes]]] = {}
    for fn, segs in entries.items():
        index[fn] = [(off ^ key, length ^ key, prefix) for (off, length, prefix) in segs]
    index_bytes = zlib.compress(pickle.dumps(index))
    index_offset = _HEADER_LEN + len(payload)
    header = f"{_VERSION} {index_offset:016x} {key:08x} \n".encode("ascii")
    assert len(header) == _HEADER_LEN
    with open(path, "wb") as f:
        f.write(header)
        f.write(payload)
        f.write(index_bytes)


def _entry(rpa_path: Path, filename: str):
    idx = parse_rpa_archive(str(rpa_path))
    assert idx is not None, "archive failed to parse"
    key = filename.replace("\\", "/").lower()
    assert key in idx.entries, f"{filename!r} not in {list(idx.entries)}"
    return idx.entries[key]


# =============================================================================
# read_rpa_segment: valid reads + the integrity check
# =============================================================================


class TestReadRpaSegmentIntegrity:
    def test_valid_single_segment_no_raise(self, tmp_path: Path) -> None:
        data = b"valid rpy body"
        rpa = tmp_path / "a.rpa"
        _make_rpa(
            rpa,
            {"good.rpy": [(_HEADER_LEN, len(data), b"")]},
            payload=data,
        )
        entry = _entry(rpa, "good.rpy")
        with open(rpa, "rb") as f:
            assert read_rpa_segment(f, entry.segments[0]) == data

    def test_zero_length_segment_ok(self, tmp_path: Path) -> None:
        """A zero-length segment (prefix-only) reads zero bytes and is valid
        — the check must not fire on ``len(b"") == 0``."""
        rpa = tmp_path / "a.rpa"
        _make_rpa(rpa, {"pfx.bin": [(_HEADER_LEN, 0, b"PFX")]}, payload=b"")
        entry = _entry(rpa, "pfx.bin")
        with open(rpa, "rb") as f:
            assert read_rpa_segment(f, entry.segments[0]) == b"PFX"

    def test_offset_beyond_eof_raises(self, tmp_path: Path) -> None:
        """Offset way past the file → read returns b"" → ValueError."""
        rpa = tmp_path / "a.rpa"
        _make_rpa(rpa, {"bad.rpy": [(999_999, 100, b"")]}, payload=b"")
        entry = _entry(rpa, "bad.rpy")
        with open(rpa, "rb") as f:
            with pytest.raises(ValueError, match="truncat"):
                read_rpa_segment(f, entry.segments[0])

    def test_extends_past_eof_raises(self, tmp_path: Path) -> None:
        """Offset inside the file but length runs past EOF → short read."""
        rpa = tmp_path / "a.rpa"
        _make_rpa(
            rpa,
            {"bad.rpy": [(_HEADER_LEN, 999_999, b"")]},
            payload=b"XY",  # 2 bytes of real data, then the index, then EOF
        )
        entry = _entry(rpa, "bad.rpy")
        with open(rpa, "rb") as f:
            with pytest.raises(ValueError) as exc:
                read_rpa_segment(f, entry.segments[0])
        # Got some bytes (the payload + maybe index) but fewer than 999999.
        assert "expected 999999" in str(exc.value)

    def test_error_message_includes_details(self, tmp_path: Path) -> None:
        rpa = tmp_path / "a.rpa"
        _make_rpa(rpa, {"bad.rpy": [(999_999, 100, b"")]}, payload=b"")
        entry = _entry(rpa, "bad.rpy")
        with open(rpa, "rb") as f:
            with pytest.raises(ValueError) as exc:
                read_rpa_segment(f, entry.segments[0])
        msg = str(exc.value)
        assert "999999" in msg  # offset
        assert "expected 100" in msg
        assert "read 0" in msg

    def test_nonzero_key_short_read_raises(self, tmp_path: Path) -> None:
        """The key is applied at parse time, so the integrity check is
        key-agnostic — a liar segment still raises under a non-zero key."""
        rpa = tmp_path / "a.rpa"
        _make_rpa(
            rpa,
            {"bad.rpy": [(999_999, 100, b"")]},
            payload=b"",
            key=0xDEADBEEF,
        )
        entry = _entry(rpa, "bad.rpy")
        with open(rpa, "rb") as f:
            with pytest.raises(ValueError):
                read_rpa_segment(f, entry.segments[0])


# =============================================================================
# extract_scripts_from_rpa: skip bad entry, continue the rest
# =============================================================================


class TestExtractScriptsSkipOnTruncation:
    def test_skips_bad_entry_continues_good(self, tmp_path: Path, caplog) -> None:
        """A truncated entry is skipped (warn) but the good entry in the same
        archive still extracts — one corrupt segment no longer loses the
        whole archive."""
        good_data = b"# good script\n"
        rpa = tmp_path / "game" / "archive.rpa"
        rpa.parent.mkdir(parents=True)
        _make_rpa(
            rpa,
            {
                # Valid: offset into the real payload, length matches.
                "good.rpy": [(_HEADER_LEN, len(good_data), b"")],
                # Liar: offset way past EOF → short read → ValueError.
                "bad.rpy": [(999_999, 100, b"")],
            },
            payload=good_data,
        )
        dest = tmp_path / "out"
        dest.mkdir()
        import logging

        with caplog.at_level(logging.WARNING, logger="senpy.cli.unrpyc"):
            extracted = extract_scripts_from_rpa(str(rpa), str(dest))

        good_dest = str(dest / "good.rpy")
        bad_dest = str(dest / "bad.rpy")
        assert good_dest in extracted
        assert bad_dest not in extracted
        # The good file has the right bytes.
        assert Path(good_dest).read_bytes() == good_data
        # And no bad file was written.
        assert not os.path.exists(bad_dest)
        # A warning was logged for the skipped entry.
        assert any("bad.rpy" in r.message and "truncat" in r.message for r in caplog.records)

    def test_all_bad_entries_returns_empty(self, tmp_path: Path) -> None:
        """Every entry truncated → empty result, no crash, no files written."""
        rpa = tmp_path / "a.rpa"
        _make_rpa(
            rpa,
            {
                "bad1.rpy": [(999_999, 100, b"")],
                "bad2.rpy": [(888_888, 50, b"")],
            },
            payload=b"",
        )
        dest = tmp_path / "out"
        dest.mkdir()
        extracted = extract_scripts_from_rpa(str(rpa), str(dest))
        assert extracted == []
        assert not list(dest.rglob("*.rpy"))

    def test_valid_archive_no_warning(self, tmp_path: Path, caplog) -> None:
        """A clean archive extracts with no truncation warning."""
        data = b"# clean\n"
        rpa = tmp_path / "a.rpa"
        _make_rpa(rpa, {"ok.rpy": [(_HEADER_LEN, len(data), b"")]}, payload=data)
        dest = tmp_path / "out"
        dest.mkdir()
        import logging

        with caplog.at_level(logging.WARNING, logger="senpy.cli.unrpyc"):
            extracted = extract_scripts_from_rpa(str(rpa), str(dest))
        assert extracted == [str(dest / "ok.rpy")]
        assert not any("truncat" in r.message for r in caplog.records)


# =============================================================================
# extract_asset_to_cache: truncated segment → None (hint fallback)
# =============================================================================


class TestExtractAssetCacheOnTruncation:
    def test_truncated_multisegment_returns_none(self, tmp_path: Path) -> None:
        """A multi-segment entry whose second segment is truncated →
        extract_asset_to_cache returns None (hover falls back to the hint)."""
        seg0_data = b"part0"
        rpa = tmp_path / "game" / "archive.rpa"
        rpa.parent.mkdir(parents=True)
        _make_rpa(
            rpa,
            {
                "game/bg.png": [
                    (_HEADER_LEN, len(seg0_data), b""),  # valid
                    (999_999, 50, b""),  # liar → short read
                ]
            },
            payload=seg0_data,
        )
        entry = _entry(rpa, "game/bg.png")
        path = extract_asset_to_cache(entry, cache_root=str(tmp_path / "cache"))
        assert path is None
        # And nothing was written to the cache.
        assert not list((tmp_path / "cache").rglob("bg.png"))

    def test_valid_multisegment_still_extracts(self, tmp_path: Path) -> None:
        """Regression: a valid multi-segment entry still extracts correctly
        — the integrity check must not fire on full reads."""
        seg0 = b"BODY-A"
        seg1 = b"BODY-B"
        rpa = tmp_path / "game" / "archive.rpa"
        rpa.parent.mkdir(parents=True)
        _make_rpa(
            rpa,
            {
                "game/song.ogg": [
                    (_HEADER_LEN, len(seg0), b""),
                    (_HEADER_LEN + len(seg0), len(seg1), b""),
                ]
            },
            payload=seg0 + seg1,
        )
        entry = _entry(rpa, "game/song.ogg")
        path = extract_asset_to_cache(entry, cache_root=str(tmp_path / "cache"))
        assert path is not None
        assert Path(path).read_bytes() == seg0 + seg1
