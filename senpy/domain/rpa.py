from __future__ import annotations

import io
import pickle
import pickletools
import zlib
from dataclasses import dataclass
from typing import BinaryIO

__all__ = [
    "SAFE_OPCODES",
    "SafeRPAUnpickler",
    "safe_load_rpa_index",
    "RpaSegment",
    "RpaEntry",
    "RpaArchiveIndex",
    "parse_rpa_archive",
    "read_rpa_segment",
]

# Opcode allowlist: only primitive data types are allowed
SAFE_OPCODES = {
    # Protocols, markers, and stack
    "PROTO",
    "FRAME",
    "STOP",
    "MARK",
    "POP",
    "POP_MARK",
    "DUP",
    # Memoization (references in the object graph)
    "PUT",
    "BINPUT",
    "LONG_BINPUT",
    "MEMOIZE",
    "GET",
    "BINGET",
    "LONG_BINGET",
    # Numbers
    "INT",
    "BININT",
    "BININT1",
    "BININT2",
    "LONG",
    "LONG1",
    "LONG4",
    "FLOAT",
    "BINFLOAT",
    # Strings and bytes
    "STRING",
    "BINSTRING",
    "SHORT_BINSTRING",
    "UNICODE",
    "BINUNICODE",
    "SHORT_BINUNICODE",
    "BINUNICODE8",
    "BINBYTES",
    "SHORT_BINBYTES",
    "BINBYTES8",
    "BYTEARRAY8",
    # Constants
    "NONE",
    "NEWTRUE",
    "NEWFALSE",
    # Collections
    "EMPTY_TUPLE",
    "TUPLE",
    "TUPLE1",
    "TUPLE2",
    "TUPLE3",
    "EMPTY_LIST",
    "LIST",
    "APPEND",
    "APPENDS",
    "EMPTY_DICT",
    "DICT",
    "SETITEM",
    "SETITEMS",
}


class SafeRPAUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        # Second line of defense: forbid importing any classes, functions, and modules
        raise pickle.UnpicklingError(
            f"Security Error: Forbidden import '{module}.{name}' in untrusted RPA archive"
        )


def safe_load_rpa_index(raw_data: bytes, max_uncompressed_bytes: int = 50 * 1024 * 1024) -> dict:
    """
    Safely unpacks and validates an RPA archive index.
    Protects against RCE (Remote Code Execution), opcode injection, and zip bombs.
    """
    # 1. Decompression bomb protection (limit the uncompressed index size to 50 MB)
    decompressor = zlib.decompressobj()
    decompressed = decompressor.decompress(raw_data, max_length=max_uncompressed_bytes)
    if decompressor.unconsumed_tail:
        raise ValueError("RPA index exceeds safe limit (decompression bomb protection)")

    # 2. First line of defense: static bytecode analysis to ensure no dangerous opcodes
    for opcode, _, _ in pickletools.genops(decompressed):
        if opcode.name not in SAFE_OPCODES:
            raise pickle.UnpicklingError(
                f"Security Error: Malicious pickle opcode '{opcode.name}' detected in RPA archive"
            )

    # 3. Second line of defense: deserialize via an isolated Unpickler
    unpickler = SafeRPAUnpickler(
        io.BytesIO(decompressed), encoding="utf-8", errors="surrogateescape"
    )
    index = unpickler.load()

    if not isinstance(index, dict):
        raise TypeError("Malformed RPA archive: root structure is not a dictionary")

    return index


# =============================================================================
# RPA archive data model + unified parser/reader
#
# Before 0.9.4 the RPA code had two parallel readers with divergent header
# parsing: ``assets.py:_read_rpa_index`` used a fixed-width ``header[8:24]``
# slice (which silently mis-parses archives whose offset field is not exactly
# 16 hex chars wide, e.g. the ``_make_rpa_archive`` test fixture) and
# discarded the segment tuples entirely; ``unrpyc.py:extract_scripts_from_rpa``
# used a whitespace-split, key-aware parse and did read segments. RPA-1 + RPA-3
# collapse both into a single ``parse_rpa_archive`` (header + index) and a
# single ``read_rpa_segment`` (segment I/O), so there is one source of truth
# for the RPA byte format. ``safe_load_rpa_index`` above is unchanged — it
# remains the security primitive (opcode allowlist + isolated unpickler).
# =============================================================================

# Recognized RPA magic tokens (the exact first whitespace-delimited token of
# the header line). Real archives use ``b"RPA-3.0 "`` / ``b"RPA-2.0 "`` with a
# trailing space separating the magic from the offset; matching on the exact
# token (rather than ``startswith``) avoids mis-classifying a hypothetical
# ``b"RPA-3.0X"`` prefix as an archive.
_RPA_MAGIC_TOKENS: frozenset[bytes] = frozenset({b"RPA-3.0", b"RPA-2.0"})

# Bytes to read for the header line. The longest real header variant is
# ``"RPA-3.0 <16-hex-offset> <8-hex-key> \n"`` (35 bytes); 64 leaves margin
# and covers any future width change without re-tuning.
_RPA_HEADER_READ_BYTES = 64


@dataclass(frozen=True, slots=True)
class RpaSegment:
    """One segment of a file stored inside an RPA archive.

    Fields are DECODED: the archive's XOR obfuscation key (RPA-3.0 only;
    RPA-2.0 has ``key == 0`` so XOR is a no-op) has already been applied to
    ``offset`` and ``length`` at parse time, so a consumer can
    ``f.seek(offset); f.read(length)`` directly without knowing the key.
    ``prefix`` is stored verbatim (it is never obfuscated in the format).

    Semantics: ``length`` counts only the in-archive DATA bytes;
    ``prefix`` is PREPENDED to the read data and is NOT part of ``length``.
    The pre-0.9.4 reader subtracted ``len(prefix)`` from ``length`` and
    truncated the data — see ``test_rpa_prefix_bug.py``.
    """

    offset: int
    length: int
    prefix: bytes


@dataclass(frozen=True, slots=True)
class RpaEntry:
    """One file inside an RPA archive, with enough metadata to read its
    contents lazily without re-parsing the archive header.

    ``filename`` is normalized to forward slashes and kept in its ORIGINAL
    CASE — case-insensitive lookup is a caller concern. This mirrors how
    ``AssetManager`` stores disk assets: ``known_assets`` lowercases for
    matching, but the RPA cache keeps original case so extraction / sandbox
    paths (RPA-9) stay faithful to what the archive actually contains.
    ``segments`` are decoded (see :class:`RpaSegment`). ``archive_path`` is
    the path of the containing ``.rpa`` file, stored as handed to
    :func:`parse_rpa_archive` (callers pass absolute paths in practice).
    """

    filename: str
    segments: tuple[RpaSegment, ...]
    archive_path: str


@dataclass(frozen=True, slots=True)
class RpaArchiveIndex:
    """Parsed RPA archive: XOR key + entries keyed by normalized filename.

    ``entries`` maps the LOWERCASED, forward-slashed filename to its
    :class:`RpaEntry` (the entry itself keeps the original-case ``filename``).
    ``key`` is retained per-archive (not per-entry) for future RPA-1.0 legacy
    support and integrity / CRC checks that may need to
    re-interpret raw index bytes. ``version`` is the magic token string
    (``"RPA-3.0"`` / ``"RPA-2.0"``).
    """

    archive_path: str
    key: int
    version: str
    entries: dict[str, RpaEntry]


def parse_rpa_archive(rpa_path: str) -> RpaArchiveIndex | None:
    """Open and parse an RPA archive into a decoded :class:`RpaArchiveIndex`.

    Reads the archive header (whitespace-split, key-aware — handles both
    RPA-2.0 and RPA-3.0 regardless of hex-field width, which the previous
    fixed-width ``header[8:24]`` parser in ``assets.py`` could not), locates
    the zlib-compressed pickle index via :func:`safe_load_rpa_index`, and
    builds decoded :class:`RpaEntry` objects.

    Returns ``None`` if *rpa_path* is not a recognized RPA archive (no
    ``RPA-2.0``/``RPA-3.0`` magic token, or the header is too short to carry
    an offset). Raises ``ValueError`` / ``TypeError`` / ``zlib.error`` /
    ``pickle.PickleError`` on corrupt or malicious content — callers are
    expected to catch and log (see ``AssetManager._read_rpa_index`` and
    ``extract_scripts_from_rpa``).

    Segment decoding is defensive: a single malformed segment (non-int
    offset/length, non-bytes prefix, wrong tuple arity) is skipped rather
    than aborting the whole archive, and an entry with zero usable segments
    is dropped. This means a partially-corrupt archive still yields its
    valid entries — strictly better than the previous all-or-nothing
    behaviour, and it keeps ``known_assets`` registration (RPA-1's
    non-breaking contract) intact even when one segment is garbage.
    """
    with open(rpa_path, "rb") as f:
        header = f.read(_RPA_HEADER_READ_BYTES)
        first_line = header.split(b"\n", 1)[0]
        parts = first_line.split()
        if len(parts) < 2 or parts[0] not in _RPA_MAGIC_TOKENS:
            return None
        version = parts[0].decode("ascii", errors="replace")
        offset = int(parts[1], 16)
        key = int(parts[2], 16) if version.startswith("RPA-3.0") and len(parts) > 2 else 0
        f.seek(offset)
        raw_index = safe_load_rpa_index(f.read())

    entries: dict[str, RpaEntry] = {}
    for filename, segments in raw_index.items():
        if not isinstance(filename, str):
            # Non-str keys are malformed (the index maps filename -> segs).
            # Skip rather than crash on ``filename.replace`` — the previous
            # ``assets.py`` reader caught the AttributeError only at the
            # outer try/except, losing the whole archive.
            continue
        clean_fn = filename.replace("\\", "/")
        decoded_segs: list[RpaSegment] = []
        for seg in segments or ():
            try:
                if not isinstance(seg, (tuple, list)) or len(seg) < 2:
                    continue
                seg_offset = int(seg[0]) ^ key
                seg_len = int(seg[1]) ^ key
                raw_prefix = seg[2] if len(seg) > 2 else b""
                prefix = bytes(raw_prefix) if raw_prefix is not None else b""
            except (TypeError, ValueError, IndexError, AttributeError):
                # Malformed segment value (non-int offset/length, non-bytes
                # prefix that ``bytes()`` rejects). Skip this segment; the
                # entry is still usable if it has at least one good segment.
                continue
            decoded_segs.append(RpaSegment(seg_offset, seg_len, prefix))
        if not decoded_segs:
            continue
        entries[clean_fn.lower()] = RpaEntry(clean_fn, tuple(decoded_segs), rpa_path)

    return RpaArchiveIndex(rpa_path, key, version, entries)


def read_rpa_segment(f: BinaryIO, segment: RpaSegment) -> bytes:
    """Read one segment's bytes from an open RPA archive file handle.

    Seeks to ``segment.offset``, reads exactly ``segment.length`` data bytes,
    and prepends ``segment.prefix``. The prefix is SEPARATE from ``length``
    (RPA-4): ``length`` counts only in-archive data; prefix is prepended
    after the read.

    This is the single DRY'ed segment reader — used by code
    extraction (``extract_scripts_from_rpa``) and, in later 0.9.4 tasks, by
    asset extraction and hover preview.
    Length-integrity validation (compare ``len(read_data)`` to
    ``segment.length`` and warn + skip on mismatch) is deliberately NOT
    performed here, a separate task with its own WARNING-and-
    skip semantics; folding it in now would change ``extract_scripts_from_rpa``
    behaviour for archives that currently extract short data silently.
    """
    f.seek(segment.offset)
    return segment.prefix + f.read(segment.length)
