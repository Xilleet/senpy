"""Regression tests for RPA archive handling.

The bug has two parts:

    * Part A — `safe_load_rpa_index` raises `TypeError` when the pickle
      root is not a dict (e.g. a list), but `_read_rpa_index` only
      catches `(OSError, zlib.error, pickle.UnpicklingError, ValueError)`,
      so the `TypeError` propagates and crashes the analyzer.
    * Part B — `_read_rpa_index` is currently dead code: `.rpa` is in
      `NON_ASSET_EXTENSIONS`, so the `continue` on line 185 fires before
      the `if f.lower().endswith(".rpa")` check on line 217 can run.

The hardening fix (Part A) is in scope for 0.8.1 — adding `TypeError` and
`AttributeError` to the except clause. Without it, anyone who later
activates `_read_rpa_index` (Part B, tracked separately as A18 for 0.8.2)
would inherit a latent crash on every malformed `.rpa` file.

Activation of `_read_rpa_index` (Part B) is NOT in scope for 0.8.1: it
requires a separate decision about whether Senpy should index RPA
archives at all (and a regression test on real-world archives). Tracked
as A18 in `download/senpy_roadmap.md`.
"""

from __future__ import annotations

import io
import os
import pickle
import struct
import zlib
from pathlib import Path

import pytest

from senpy.domain.rpa import safe_load_rpa_index


def _make_rpa_with_pickle_root(root_obj: object, tmp_path: Path) -> Path:
    """Build a minimal .rpa archive whose pickle root is `root_obj`.

    The RPA-3.0 header format (parsed by `_read_rpa_index`):
        b"RPA-3.0 " + hex(offset)[16 chars] + b" " + hex(key)[8 chars] + b"\\n"
    Total header length = 8 + 16 + 1 + 8 + 1 = 34 chars.
    `header[8:24]` extracts the 16-char hex offset.
    """
    pickled = pickle.dumps(root_obj)
    key = 0  # RPA-3.0 uses an obfuscation key; 0 = no obfuscation
    offset = 34  # data starts right after the header
    header = f"RPA-3.0 {offset:016x} {key:08x}\n".encode("ascii")
    assert len(header) == 34
    body = zlib.compress(pickled)
    rpa_path = tmp_path / "evil.rpa"
    with open(rpa_path, "wb") as f:
        f.write(header)
        f.write(body)
    return rpa_path


def test_safe_load_rpa_index_rejects_non_dict_root() -> None:
    """safe_load_rpa_index must raise on a non-dict pickle root.

    A pickle that deserializes to a list (or any non-dict) is malformed
    for an RPA archive — the index must be a dict mapping filenames to
    metadata. The function already raises `TypeError` for this case; the
    bug is that `_read_rpa_index` does not catch it.
    """
    raw = zlib.compress(pickle.dumps(["not", "a", "dict"]))
    with pytest.raises(TypeError, match="root structure is not a dictionary"):
        safe_load_rpa_index(raw)


def test_read_rpa_index_does_not_crash_on_malformed_archive(
    tmp_path: Path,
) -> None:
    """Reproducer: a `.rpa` file whose pickle root is a list (not a dict)
    must be logged and skipped, NOT crash the analyzer with an uncaught
    `TypeError`. The except clause must include `TypeError` and
    `AttributeError` so that any future activation of `_read_rpa_index`
    inherits safe handling of malformed archives.

    We test `_read_rpa_index` directly because `.rpa` is currently in
    `NON_ASSET_EXTENSIONS` (the activation of `_read_rpa_index` from the
    production path is tracked separately as A18 for 0.8.2). The
    hardening of the except clause is in scope for 0.8.1: anyone who
    later activates the method must inherit safe handling.
    """
    from senpy.domain.assets import AssetManager

    rpa_path = _make_rpa_with_pickle_root(["not", "a", "dict"], tmp_path)
    project_path = tmp_path / "game"
    project_path.mkdir(parents=True, exist_ok=True)

    am = AssetManager(str(project_path))
    # Directly invoke _read_rpa_index — must not raise.
    am._read_rpa_index(str(rpa_path))


def test_read_rpa_index_does_not_crash_on_int_keys(tmp_path: Path) -> None:
    """Reproducer (variant): pickle root is a dict but keys are not str.
    `for filename in index:` with non-str keys would crash with
    `AttributeError: 'int' object has no attribute 'replace'`. The
    except clause must include `AttributeError`.
    """
    from senpy.domain.assets import AssetManager

    rpa_path = _make_rpa_with_pickle_root({1: "value", 2: "other"}, tmp_path)
    project_path = tmp_path / "game"
    project_path.mkdir(parents=True, exist_ok=True)

    am = AssetManager(str(project_path))
    am._read_rpa_index(str(rpa_path))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
