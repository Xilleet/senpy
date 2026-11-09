"""Regression tests for JPEG header parsing when APP markers consume more
than the 64 KB header buffer.

Real-world JPEG files (camera output, stock photos, images with embedded
XMP / ICC profiles / large EXIF thumbnails) can carry APP segments
totalling more than 64 KB before the SOF0 (Start-Of-Frame) marker. The
header parser reads only the first ``_HEADER_READ_BYTES = 64 * 1024``
bytes of the file (mirroring renpy-magic), so a SOF0 located past that
boundary is never seen.

The current implementation handles this gracefully: when the marker-scan
loop exhausts the buffer without encountering a SOFn marker,
``_jpeg_size`` returns ``None``, ``get_image_size`` returns ``None``,
and ``markdown_size_param`` returns ``""`` — the LSP hover then renders
the image at natural VS Code size, without ``|width=`` / ``|height=``
sizing hints.

These tests pin that contract down as a regression guard:
  - long APP marker pushing SOF0 past the buffer → graceful ``None``
  - APP marker at the buffer boundary (just inside / just outside)
  - sanity check: a normal JPEG with a small APP marker still parses
  - direct ``_jpeg_size`` unit tests with byte slices (no disk I/O)
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from senpy.domain.image_size import (
    _HEADER_READ_BYTES,
    _jpeg_size,
    get_image_size,
    markdown_size_param,
)

# =============================================================================
# Helpers — JPEG byte constructors
# =============================================================================


def _sof0_segment(width: int, height: int) -> bytes:
    """Build a SOF0 marker segment carrying the given dimensions.

    Layout: 0xFFC0 + 2-byte length (incl. its own 2 bytes) + 1-byte
    precision + 2-byte height + 2-byte width + 1-byte component count
    + 3 bytes per component (id, sampling, quant-table).
    """
    payload = struct.pack(">BHH", 8, height, width) + b"\x03\x11\x00\x11\x00\x11\x00"
    return b"\xff\xc0" + struct.pack(">H", len(payload) + 2) + payload


def _app_segment(marker: int, payload_len: int) -> bytes:
    """Build an APPn marker segment with a payload of ``payload_len``
    zero bytes. ``marker`` is the APPn marker number (0xE0..0xEF).
    The 2-byte length field includes itself, so the segment's total
    size is ``2 (marker) + 2 (length) + payload_len - 0`` bytes when
    ``payload_len >= 2`` (the length field counts its own 2 bytes).

    For a max-length segment, ``payload_len = 0xFFFF - 2 = 65533``.
    """
    if payload_len < 0:
        raise ValueError("payload_len must be >= 0")
    total_length = payload_len + 2  # length field counts its own 2 bytes
    if total_length > 0xFFFF:
        raise ValueError(f"segment too large: {total_length} > 65535")
    return bytes([0xFF, marker]) + struct.pack(">H", total_length) + b"\x00" * payload_len


def _minimal_jpeg(width: int, height: int) -> bytes:
    """SOI + SOF0 only — no APP markers at all."""
    return b"\xff\xd8" + _sof0_segment(width, height)


def _jpeg_with_long_app1(width: int, height: int, app1_payload_len: int) -> bytes:
    """SOI + APP1 (EXIF) with the given payload length + SOF0.

    With ``app1_payload_len = 65533`` (max), the SOF0 starts at byte
    offset ``2 + 4 + 65533 = 65539``, which is 3 bytes past the 64 KB
    header buffer (65536 bytes). The parser must return ``None``.
    """
    return b"\xff\xd8" + _app_segment(0xE1, app1_payload_len) + _sof0_segment(width, height)


# =============================================================================
# Direct _jpeg_size unit tests — no disk I/O
# =============================================================================


class TestJpegSizeDirect:
    """Call ``_jpeg_size`` directly with in-memory bytes — fast, no disk."""

    def test_minimal_jpeg_returns_dimensions(self) -> None:
        buf = _minimal_jpeg(100, 200)
        assert _jpeg_size(buf) == (100, 200)

    def test_long_app1_pushes_sof0_past_buffer_returns_none(self) -> None:
        """A max-length APP1 (65535 bytes including length field) pushes
        SOF0 to byte offset 65539 — 3 bytes past the 64 KB buffer.
        ``_jpeg_size`` must return ``None`` gracefully."""
        # The full file would be 65555 bytes, but the parser only sees
        # the first 65536 (the header buffer). Construct exactly that
        # slice to exercise the boundary directly.
        full = _jpeg_with_long_app1(100, 200, app1_payload_len=65533)
        assert len(full) == 65555
        buf = full[:_HEADER_READ_BYTES]
        assert len(buf) == 65536
        # SOF0 is past the buffer → None.
        assert _jpeg_size(buf) is None

    def test_app1_with_sof0_fully_inside_buffer_returns_dimensions(self) -> None:
        """APP1 payload of 65514 bytes puts SOF0 at byte 65520 — and the
        full 16-byte SOF0 segment fits within the 64 KB buffer (ends at
        byte 65536). Parser must find it and return dims."""
        full = _jpeg_with_long_app1(100, 200, app1_payload_len=65514)
        # SOI(2) + marker(2) + length(2) + payload(65514) + SOF0(16) = 65536
        assert len(full) == 65536
        buf = full[:_HEADER_READ_BYTES]
        assert _jpeg_size(buf) == (100, 200)

    def test_app1_with_sof0_straddling_buffer_returns_none(self) -> None:
        """APP1 payload of 65528 puts SOF0 at byte 65534 — the marker
        prefix (2 bytes) fits inside the 64 KB buffer, but the length
        field extends past it. This is the truncated-segment guard
        (``i + 9 > n`` in ``_jpeg_size``)."""
        full = _jpeg_with_long_app1(100, 200, app1_payload_len=65528)
        # SOI(2) + marker(2) + length(2) + payload(65528) + SOF0(16) = 65550
        assert len(full) == 65550
        buf = full[:_HEADER_READ_BYTES]
        # SOF0 marker prefix at byte 65534 is inside, but length field
        # at 65536-65537 is outside the buffer → truncated → None.
        assert _jpeg_size(buf) is None

    def test_corrupt_jpeg_no_sof_returns_none(self) -> None:
        """A JPEG that starts with SOI but never contains a SOFn marker
        must return ``None``, not crash or hang."""
        buf = b"\xff\xd8" + _app_segment(0xE1, 100) + b"\x00" * 200
        assert _jpeg_size(buf) is None

    def test_non_jpeg_returns_none(self) -> None:
        assert _jpeg_size(b"not a jpeg at all") is None

    def test_empty_buffer_returns_none(self) -> None:
        assert _jpeg_size(b"") is None

    def test_truncated_marker_returns_none(self) -> None:
        """A marker prefix at the very end of the buffer, with no length
        field, must not crash."""
        buf = b"\xff\xd8\xff"  # SOI + lone marker prefix
        assert _jpeg_size(buf) is None

    def test_truncated_sof_returns_none(self) -> None:
        """A SOFn marker whose declared segment length extends past the
        buffer must return ``None``, not raise ``IndexError``."""
        # SOF0 marker + length field declaring 17 bytes, but only 3 bytes
        # of payload follow (truncated mid-segment).
        buf = b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x64"
        assert _jpeg_size(buf) is None

    def test_multiple_app_markers_then_sof(self) -> None:
        """Several small APP markers in a row, then SOF0 — must parse."""
        buf = (
            b"\xff\xd8"
            + _app_segment(0xE0, 14)  # APP0 JFIF
            + _app_segment(0xE1, 30)  # APP1 EXIF
            + _app_segment(0xE2, 10)  # APP2 ICC
            + _sof0_segment(320, 240)
        )
        assert _jpeg_size(buf) == (320, 240)


# =============================================================================
# End-to-end: get_image_size + markdown_size_param on disk
# =============================================================================


class TestJpegLongAppMarkersEndToEnd:
    """Exercise the public API via real files on ``tmp_path``."""

    def test_long_app_marker_get_image_size_returns_none(self, tmp_path: Path) -> None:
        jpeg_bytes = _jpeg_with_long_app1(100, 200, app1_payload_len=65533)
        path = tmp_path / "long_app.jpg"
        path.write_bytes(jpeg_bytes)

        assert get_image_size(path) is None

    def test_long_app_marker_markdown_size_param_returns_empty(self, tmp_path: Path) -> None:
        jpeg_bytes = _jpeg_with_long_app1(100, 200, app1_payload_len=65533)
        path = tmp_path / "long_app.jpg"
        path.write_bytes(jpeg_bytes)

        assert markdown_size_param(path) == ""

    def test_normal_jpeg_returns_dimensions(self, tmp_path: Path) -> None:
        """Sanity check: a normal JPEG with a small APP marker still
        parses — no regression in the happy path."""
        jpeg_bytes = (
            b"\xff\xd8"
            + _app_segment(0xE1, 14)  # small APP1 EXIF
            + _sof0_segment(1024, 768)
        )
        path = tmp_path / "normal.jpg"
        path.write_bytes(jpeg_bytes)

        assert get_image_size(path) == (1024, 768)
        # markdown_size_param clamps to MAX_HOVER_WIDTH=400 / MAX_HOVER_HEIGHT=200
        # preserving aspect ratio. For 1024x768 the binding ratio is
        # 200/768 ~= 0.2604 → 266x200 → w > h → emits |height=200.
        assert markdown_size_param(path) == "|height=200"

    def test_wide_image_emits_height_after_clamp(self, tmp_path: Path) -> None:
        """A wide image (1024x256) clamps to 400x100 (width-bound), then
        markdown emits ``|height=100`` because w > h after clamp."""
        jpeg_bytes = _minimal_jpeg(1024, 256)
        path = tmp_path / "wide.jpg"
        path.write_bytes(jpeg_bytes)

        assert get_image_size(path) == (1024, 256)
        # w_ratio=400/1024=0.39, h_ratio=200/256=0.78, ratio=0.39
        # new_w=int(1024*0.39)=400, new_h=int(256*0.39)=100
        # w=400 > h=100 → emit |height=100
        assert markdown_size_param(path) == "|height=100"

    def test_tall_image_emits_width_after_clamp(self, tmp_path: Path) -> None:
        """A tall image (256x1024) clamps to 100x400 (height-bound), then
        markdown emits ``|width=100`` because w < h after clamp."""
        jpeg_bytes = _minimal_jpeg(256, 1024)
        path = tmp_path / "tall.jpg"
        path.write_bytes(jpeg_bytes)

        assert get_image_size(path) == (256, 1024)
        # w_ratio=400/256=1.56, h_ratio=200/1024=0.195, ratio=0.195
        # new_w=int(256*0.195)=50, new_h=int(1024*0.195)=200
        # w=50 < h=200 → emit |width=50
        assert markdown_size_param(path) == "|width=50"

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "does_not_exist.jpg"
        assert get_image_size(path) is None
        assert markdown_size_param(path) == ""

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.jpg"
        path.write_bytes(b"")
        assert get_image_size(path) is None
        assert markdown_size_param(path) == ""

    def test_truncated_jpeg_returns_none(self, tmp_path: Path) -> None:
        """A file that starts with SOI but is truncated mid-segment must
        not crash."""
        path = tmp_path / "truncated.jpg"
        path.write_bytes(b"\xff\xd8\xff\xe1\x00\x10\x00\x00")  # SOI + start of APP1
        assert get_image_size(path) is None
        assert markdown_size_param(path) == ""
