"""Tests for `senpy/core/cache.py:compute_file_hash` — file content hashing.

Covers the BLAKE2b migration (was MD5 before 0.7.5).

Why BLAKE2b over MD5:
- Faster on modern CPUs (3-5x with SIMD)
- Not flagged by security scanners as "weak crypto" (MD5 is, even
  when used for non-security purposes like cache invalidation)
- Modern standard (RFC 7693), recommended by NIST

The hash is used for cache invalidation (detect when a .rpy file
changed). It is NOT used for security — an attacker who can plant a
collision in their own .rpy file gains nothing (the cache is per-
project, not shared across users).

Migration safety: the cache manifest carries a `version` field
(= SENPY_VERSION). When the Senpy version changes (0.7.4 -> 0.7.5),
`CacheManager.load_manifest()` rejects the old cache via
`data.version == SENPY_VERSION` check. So the BLAKE2b switch is
transparent — old MD5 hashes are simply ignored, the cache is
rebuilt from scratch on first run.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from senpy.core.cache import compute_file_hash


class TestComputeFileHash:
    """Behavioral tests for compute_file_hash()."""

    def test_returns_hex_string(self, tmp_path):
        f = tmp_path / "x.rpy"
        f.write_text("label start:\n    return\n", encoding="utf-8")
        h = compute_file_hash(str(f))
        assert isinstance(h, str)
        # Hex digest: only 0-9a-f chars.
        assert all(c in "0123456789abcdef" for c in h), f"non-hex char in {h!r}"
        assert len(h) > 0

    def test_same_content_same_hash(self, tmp_path):
        f1 = tmp_path / "a.rpy"
        f2 = tmp_path / "b.rpy"
        f1.write_text("label start:\n    return\n", encoding="utf-8")
        f2.write_text("label start:\n    return\n", encoding="utf-8")
        assert compute_file_hash(str(f1)) == compute_file_hash(str(f2))

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.rpy"
        f2 = tmp_path / "b.rpy"
        f1.write_text("label start:\n    return\n", encoding="utf-8")
        f2.write_text("label other:\n    return\n", encoding="utf-8")
        assert compute_file_hash(str(f1)) != compute_file_hash(str(f2))

    def test_missing_file_returns_empty(self, tmp_path):
        """Non-existent file → empty string (no exception)."""
        h = compute_file_hash(str(tmp_path / "nonexistent.rpy"))
        assert h == ""

    def test_empty_file_returns_nonempty_hash(self, tmp_path):
        """Empty file still has a defined hash (BLAKE2b of empty input)."""
        f = tmp_path / "empty.rpy"
        f.write_text("", encoding="utf-8")
        h = compute_file_hash(str(f))
        assert h != ""
        assert isinstance(h, str)


class TestBlake2bMigration:
    """Verify the hash algorithm is BLAKE2b, not MD5.

    This is a regression guard: if someone accidentally reverts to
    MD5 (e.g. during a refactor), these tests will fail.
    """

    def test_hash_matches_blake2b_of_content(self, tmp_path):
        """compute_file_hash(file) must equal hashlib.blake2b(content)."""
        f = tmp_path / "x.rpy"
        content = b"label start:\n    return\n"
        f.write_bytes(content)
        expected = hashlib.blake2b(content).hexdigest()
        assert compute_file_hash(str(f)) == expected

    def test_hash_does_not_match_md5_of_content(self, tmp_path):
        """Sanity: BLAKE2b output != MD5 output for the same input.

        This catches a revert where someone changes the algorithm
        back to MD5 without updating the test.
        """
        f = tmp_path / "x.rpy"
        content = b"label start:\n    return\n"
        f.write_bytes(content)
        md5_hash = hashlib.md5(content).hexdigest()
        blake2b_hash = hashlib.blake2b(content).hexdigest()
        # The two algorithms produce different outputs for the same input.
        assert md5_hash != blake2b_hash
        # compute_file_hash must produce the BLAKE2b one.
        assert compute_file_hash(str(f)) == blake2b_hash
        assert compute_file_hash(str(f)) != md5_hash

    def test_hash_length_is_blake2b_default(self, tmp_path):
        """BLAKE2b default digest size is 128 hex chars (512 bits / 64 bytes).

        MD5 is 32 hex chars (128 bits). This is another way to catch
        a revert.
        """
        f = tmp_path / "x.rpy"
        f.write_text("content", encoding="utf-8")
        h = compute_file_hash(str(f))
        assert len(h) == 128, f"expected BLAKE2b 128-hex-char digest, got {len(h)}: {h!r}"
