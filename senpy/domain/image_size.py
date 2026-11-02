"""Lightweight image header parser for hover preview sizing.

Reads only the file header (first few KB) to extract pixel dimensions for
PNG, JPEG, WEBP, GIF, BMP. Avoids pulling in Pillow as a runtime dependency
just to size a hover thumbnail.

Algorithm adapted from renpy-magic (MIT, Copyright (c) 2026 Allure Diffusion),
which uses the npm `image-size` package; the byte layouts these parsers walk
are dictated by the format specifications, not by renpy-magic's code.

Returned dimensions are clamped to a 400x200 bounding box (preserving aspect
ratio) so hover thumbnails do not dominate the editor. The clamping is the
same policy renpy-magic uses.
"""

from __future__ import annotations

import struct
from pathlib import Path

MAX_HOVER_WIDTH = 400
MAX_HOVER_HEIGHT = 200

_HEADER_READ_BYTES = 64 * 1024  # mirror renpy-magic: 64 KB header buffer


def _read_header(path: str | Path, n: int = _HEADER_READ_BYTES) -> bytes:
    """Read up to n bytes from the start of the file. Never raises; on I/O
    error returns whatever was readable (possibly b'')."""
    try:
        with open(path, "rb") as f:
            return f.read(n)
    except OSError:
        return b""


def _png_size(buf: bytes) -> tuple[int, int] | None:
    # PNG: 8-byte signature, then IHDR chunk: 4-byte length, "IHDR", 4-byte
    # width, 4-byte height (big-endian). The IHDR is always the first chunk,
    # so its width/height live at bytes 16..24.
    if len(buf) < 24 or buf[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    if buf[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", buf[16:24])
    return (width, height) if width and height else None


def _gif_size(buf: bytes) -> tuple[int, int] | None:
    # GIF87a/89a: 6-byte signature, then 2-byte logical screen width and
    # 2-byte height (little-endian).
    if len(buf) < 10 or buf[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    width, height = struct.unpack("<HH", buf[6:10])
    return (width, height) if width and height else None


def _bmp_size(buf: bytes) -> tuple[int, int] | None:
    # BMP: "BM", then DIB header. BITMAPINFOHEADER (40 bytes) puts width and
    # height at offset 18 and 22 as little-endian signed 32-bit ints. For
    # BMP we read these directly; height may be negative (top-down bitmap),
    # take abs.
    if len(buf) < 26 or buf[:2] != b"BM":
        return None
    width = struct.unpack("<i", buf[18:22])[0]
    height = abs(struct.unpack("<i", buf[22:26])[0])
    if width <= 0 or height <= 0:
        return None
    return (width, height)


def _webp_size(buf: bytes) -> tuple[int, int] | None:
    # WEBP: "RIFF"...."WEBP", then a 4-byte chunk type. VP8 (lossy) places
    # 16-bit width/height at offset 26..30; VP8L (lossless) at 21..25 with
    # 14-bit packed fields; VP8X (extended) at 24..30 with 24-bit packed.
    # Minimum header: 12 (RIFF/WEBP) + 4 (chunk id) + 4 (chunk size) = 20
    # bytes before the per-variant payload.
    if len(buf) < 20 or buf[:4] != b"RIFF" or buf[8:12] != b"WEBP":
        return None
    chunk = buf[12:16]
    if chunk == b"VP8 ":
        if len(buf) < 30:
            return None
        # VP8 stores width-1 and height-1 as 14-bit little-endian values
        # (top 2 bits of each uint16 are reserved).
        width = (struct.unpack("<H", buf[26:28])[0] & 0x3FFF) + 1
        height = (struct.unpack("<H", buf[28:30])[0] & 0x3FFF) + 1
    elif chunk == b"VP8L":
        if len(buf) < 25:
            return None
        # 1 byte signature (0x2F), then 14 bits width-1, 14 bits height-1.
        b0, b1, b2, b3 = struct.unpack("<BBBB", buf[21:25])
        width = 1 + ((b1 & 0x3F) << 8 | b0)
        height = 1 + ((b3 & 0x0F) << 10 | b2 << 2 | (b1 & 0xC0) >> 6)
    elif chunk == b"VP8X":
        if len(buf) < 30:
            return None
        # 1 byte flags, 3 bytes reserved, then 24-bit width-1, 24-bit height-1
        w0, w1, w2, h0, h1, h2 = struct.unpack("<BBBBBB", buf[24:30])
        width = 1 + (w0 | w1 << 8 | w2 << 16)
        height = 1 + (h0 | h1 << 8 | h2 << 16)
    else:
        return None
    return (width, height) if width and height else None


def _jpeg_size(buf: bytes) -> tuple[int, int] | None:
    # JPEG: walk the marker segments. SOF0..SOF15 (excluding SOF4, SOF8,
    # SOF12 — restart markers — which we treat as SOF for sizing since the
    # width/height fields are at the same offset) carry width and height as
    # 16-bit big-endian at offset +5 of the marker segment payload.
    if not buf.startswith(b"\xff\xd8"):
        return None
    i = 2
    n = len(buf)
    while i + 1 < n:
        if buf[i] != 0xFF:
            i += 1
            continue
        marker = buf[i + 1]
        # Standalone markers (no payload): RSTn, SOI, EOI, TEM.
        if marker == 0xD8 or marker == 0xD9 or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if i + 4 > n:
            return None
        seg_len = struct.unpack(">H", buf[i + 2 : i + 4])[0]
        # SOFn markers: 0xC0..0xCF (excl. 0xC4=DHT, 0xC8=JPG, 0xCC=DAC).
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if i + 9 > n:
                return None
            height = struct.unpack(">H", buf[i + 5 : i + 7])[0]
            width = struct.unpack(">H", buf[i + 7 : i + 9])[0]
            return (width, height) if width and height else None
        # Skip past this marker segment: 2-byte length includes its own bytes.
        i += 2 + seg_len
    return None


_PARSERS = {
    ".png": _png_size,
    ".jpg": _jpeg_size,
    ".jpeg": _jpeg_size,
    ".webp": _webp_size,
    ".gif": _gif_size,
    ".bmp": _bmp_size,
}


def get_image_size(path: str | Path) -> tuple[int, int] | None:
    """Return (width, height) in pixels for the image at *path*.

    Returns None if the format is unsupported or the header could not be
    parsed. Never raises on I/O errors.
    """
    suffix = Path(path).suffix.lower()
    parser = _PARSERS.get(suffix)
    if parser is None:
        return None
    return parser(_read_header(path))


def clamp_to_hover_box(width: int, height: int) -> tuple[int, int]:
    """Scale (width, height) down to fit inside MAX_HOVER_WIDTH x
    MAX_HOVER_HEIGHT, preserving aspect ratio. Returns (w, h) suitable for
    VS Code markdown image-size syntax (`![alt](uri|width=W)`).
    """
    if width <= 0 or height <= 0:
        return (MAX_HOVER_WIDTH, MAX_HOVER_HEIGHT)
    w_ratio = MAX_HOVER_WIDTH / width
    h_ratio = MAX_HOVER_HEIGHT / height
    ratio = min(w_ratio, h_ratio, 1.0)  # never upscale
    return (max(1, int(width * ratio)), max(1, int(height * ratio)))


def markdown_size_param(path: str | Path) -> str:
    """Build the `|width=W` or `|height=H` suffix for VS Code markdown images.

    VS Code's markdown-image-size extension accepts either `|width=N` or
    `|height=N` (not both). We emit whichever dimension is the binding
    constraint after clamping to the hover box.
    """
    size = get_image_size(path)
    if size is None:
        return ""  # let VS Code render at natural size
    w, h = clamp_to_hover_box(*size)
    # If width is the binding constraint (i.e. width was scaled to MAX but
    # height still has headroom), emit width=. Otherwise emit height=.
    if w <= h:
        return f"|width={w}"
    return f"|height={h}"
