"""RED test for prefix handling in segment extraction.

The RPA segment format is ``(offset, length, prefix)`` where:
- ``offset``: position in the archive file where the segment data starts
- ``length``: number of bytes to read from that position (NOT including prefix)
- ``prefix``: optional bytes prepended to the extracted data (NOT part of length)

Current Senpy code: ``prefix + f.read(seg_len - len(prefix))`` —
subtracts prefix length from seg_len, TRUNCATING the data.

Correct: ``prefix + f.read(seg_len)`` — reads seg_len bytes, prepends prefix.

This test creates a minimal RPA-3.0 archive with a non-empty prefix and
verifies that the extracted file contains the full data (prefix + seg_len bytes),
not the truncated version (prefix + seg_len - len(prefix) bytes).
"""

from __future__ import annotations

import io
import os
import pickle
import struct
import zlib
from pathlib import Path

import pytest

from senpy.cli.unrpyc import extract_scripts_from_rpa


def _create_rpa3_with_prefix(
    rpa_path: str,
    filename: str,
    file_data: bytes,
    prefix: bytes,
) -> None:
    """Create a minimal RPA-3.0 archive with one file that has a non-empty prefix.

    Layout: header | data | index
    (index is at the end — offset in header points to it)
    """
    key = 0xCAFEBABE

    # Step 1: Write data section first (prefix + file_data).
    # We'll write the header as a placeholder, then data, then index.
    # Finally rewrite the header with the correct index offset.

    buf = io.BytesIO()

    # Header placeholder — 51 bytes for "RPA-3.0 " + 16 hex + " " + 8 hex + " \n"
    header_len = 8 + 16 + 1 + 8 + 2  # = 35
    buf.write(b"\x00" * header_len)  # placeholder

    # Data section: file_data ONLY (prefix is stored in the index, not in the data)
    data_offset = buf.tell()
    buf.write(file_data)

    # Index section: after data
    index_offset = buf.tell()

    # Build index: {filename: [(data_offset ^ key, len(file_data) ^ key, prefix)]}
    # Note: seg_len = len(file_data) — the DATA length, NOT including prefix.
    # Prefix is separate (prepended after reading seg_len bytes from archive).
    index = {filename: [(data_offset ^ key, len(file_data) ^ key, prefix)]}
    index_pickle = pickle.dumps(index, protocol=4)
    index_compressed = zlib.compress(index_pickle)
    buf.write(index_compressed)

    # Now rewrite the header with correct values.
    header = f"RPA-3.0 {index_offset:016x} {key:08x} \n".encode("ascii")
    assert len(header) == header_len, f"Header length mismatch: {len(header)} != {header_len}"
    buf.seek(0)
    buf.write(header)

    # Write to file.
    with open(rpa_path, "wb") as f:
        f.write(buf.getvalue())


class TestRPAPrefixHandling:
    """prefix is SEPARATE from seg_len, not part of it."""

    def test_prefix_not_subtracted_from_seg_len(self, tmp_path: Path) -> None:
        """RED: extracted file must contain prefix + full file_data,
        not prefix + truncated file_data."""
        # Create a .rpy file content.
        file_data = b"label start:\n    return\n"
        prefix = b"# extracted from archive\n"

        # Create the RPA archive.
        rpa_path = tmp_path / "test.rpa"
        dest_dir = tmp_path / "extracted"
        dest_dir.mkdir()

        _create_rpa3_with_prefix(
            str(rpa_path),
            "game/script.rpy",
            file_data,
            prefix,
        )

        # Extract using Senpy's extract_scripts_from_rpa.
        extracted = extract_scripts_from_rpa(str(rpa_path), str(dest_dir))

        assert extracted, "Expected at least one file extracted from RPA"

        # Find the extracted .rpy file.
        extracted_rpy = None
        for path in extracted:
            if path.endswith(".rpy"):
                extracted_rpy = path
                break

        assert extracted_rpy is not None, f"Expected a .rpy file in extracted: {extracted}"

        # Read the extracted content.
        with open(extracted_rpy, "rb") as f:
            extracted_bytes = f.read()

        # The correct content is prefix + file_data.
        expected = prefix + file_data
        assert extracted_bytes == expected, (
            f"Extracted file must be prefix + full file_data "
            f"({len(expected)} bytes = {len(prefix)} prefix + {len(file_data)} data). "
            f"Got {len(extracted_bytes)} bytes.\n"
            f"  Expected: {expected!r}\n"
            f"  Got:      {extracted_bytes!r}\n"
            f"  Bug: current code reads seg_len - len(prefix) = "
            f"{len(file_data) - len(prefix)} bytes instead of seg_len = {len(file_data)} bytes."
        )

    def test_no_prefix_still_works(self, tmp_path: Path) -> None:
        """Sanity: when prefix is empty, extraction must work as before."""
        file_data = b"label start:\n    return\n"
        prefix = b""

        rpa_path = tmp_path / "test.rpa"
        dest_dir = tmp_path / "extracted"
        dest_dir.mkdir()

        _create_rpa3_with_prefix(str(rpa_path), "game/script.rpy", file_data, prefix)

        extracted = extract_scripts_from_rpa(str(rpa_path), str(dest_dir))
        assert extracted, "Expected at least one file extracted"

        extracted_rpy = next(p for p in extracted if p.endswith(".rpy"))
        with open(extracted_rpy, "rb") as f:
            extracted_bytes = f.read()

        # Without prefix, expected = file_data (empty prefix + file_data).
        assert extracted_bytes == file_data, (
            f"Without prefix, extracted file must be just file_data. "
            f"Expected: {file_data!r}, Got: {extracted_bytes!r}"
        )
