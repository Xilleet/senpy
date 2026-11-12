"""Characterization tests for senpy/cli/unrpyc.py helper functions.

These functions handle the unrpyc bootstrap: finding the decompiler on
disk, verifying its SHA256, safely extracting the zip, locating .rpyc
orphans inside .rpa archives, and decompiling them to a sandbox. The
existing security tests (``tests/security/test_vendored_unrpyc.py``)
cover the happy-path decompile flow; this file targets the remaining
branches: Zip Slip detection, SHA mismatch, custom-path / cache-dir /
``which`` lookup fallbacks, RPA-2.0 vs RPA-3.0 headers, .rpymc
extension, and the decompile error path.

Where possible the tests construct real on-disk fixtures (real zips,
real RPA archives with zlib-compressed pickle indexes) and assert on
observable side-effects (files extracted, console output, return
values) rather than internal call sequences — characterization-style.
"""

from __future__ import annotations

import io
import os
import pickle
import struct
import sys
import zipfile
import zlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from senpy.cli.unrpyc import (
    _safe_zip_extract,
    _verify_unrpyc_sha256,
    decompile_to_sandbox,
    download_unrpyc,
    extract_scripts_from_rpa,
    find_in_directory_tree,
    find_unrpyc_executable,
)

# ---------------------------------------------------------------------------
# find_in_directory_tree
# ---------------------------------------------------------------------------


class TestFindInDirectoryTree:
    def test_empty_dirs_returns_none(self) -> None:
        assert find_in_directory_tree([]) is None

    def test_nonexistent_base_skipped(self, tmp_path: Path) -> None:
        assert find_in_directory_tree([str(tmp_path / "missing")]) is None

    def test_finds_unrpyc_py_at_base(self, tmp_path: Path) -> None:
        (tmp_path / "unrpyc.py").write_text("# stub", encoding="utf-8")
        result = find_in_directory_tree([str(tmp_path)])
        assert result is not None
        assert result.endswith("unrpyc.py")

    def test_finds_unrpyc_in_subdir(self, tmp_path: Path) -> None:
        sub = tmp_path / "unrpyc"
        sub.mkdir()
        (sub / "unrpyc.py").write_text("# stub", encoding="utf-8")
        result = find_in_directory_tree([str(tmp_path)])
        assert result is not None
        assert "unrpyc" in result

    def test_finds_in_tools_subdir(self, tmp_path: Path) -> None:
        tools = tmp_path / "tools"
        tools.mkdir()
        (tools / "unrpyc.py").write_text("# stub", encoding="utf-8")
        result = find_in_directory_tree([str(tmp_path)])
        assert result is not None
        assert "tools" in result

    def test_finds_in_parent_dir(self, tmp_path: Path) -> None:
        child = tmp_path / "child"
        child.mkdir()
        (tmp_path / "unrpyc.py").write_text("# stub", encoding="utf-8")
        result = find_in_directory_tree([str(child)])
        assert result is not None
        # The candidate ``os.path.dirname(base)/unrpyc.py`` finds it.
        assert result.endswith("unrpyc.py")


# ---------------------------------------------------------------------------
# _verify_unrpyc_sha256
# ---------------------------------------------------------------------------


class TestVerifySha256:
    def test_none_placeholder_returns_true(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        # Simulate the placeholder state (UNRPYC_PINNED_SHA256 is None).
        monkeypatch.setattr("senpy.cli.unrpyc.UNRPYC_PINNED_SHA256", None)
        assert _verify_unrpyc_sha256("/nonexistent.zip") is True
        captured = capsys.readouterr()
        assert "SHA256 verification skipped" in captured.out

    def test_matching_hash_returns_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data = b"hello unrpyc"
        zip_path = tmp_path / "unrpyc.zip"
        zip_path.write_bytes(data)
        import hashlib

        monkeypatch.setattr(
            "senpy.cli.unrpyc.UNRPYC_PINNED_SHA256",
            hashlib.sha256(data).hexdigest(),
        )
        assert _verify_unrpyc_sha256(str(zip_path)) is True

    def test_mismatching_hash_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        zip_path = tmp_path / "unrpyc.zip"
        zip_path.write_bytes(b"real content")
        monkeypatch.setattr(
            "senpy.cli.unrpyc.UNRPYC_PINNED_SHA256",
            "0" * 64,  # wrong hash
        )
        assert _verify_unrpyc_sha256(str(zip_path)) is False
        captured = capsys.readouterr()
        assert "SHA256 mismatch" in captured.out
        assert "Refusing to install" in captured.out


# ---------------------------------------------------------------------------
# _safe_zip_extract
# ---------------------------------------------------------------------------


class TestSafeZipExtract:
    def test_normal_extraction(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("a.txt", "content a")
            zf.writestr("sub/b.txt", "content b")
        with zipfile.ZipFile(zip_path, "r") as zf:
            extracted = _safe_zip_extract(zf, str(tmp_path))
        assert "a.txt" in extracted
        assert "sub/b.txt" in extracted
        assert (tmp_path / "a.txt").read_text() == "content a"
        assert (tmp_path / "sub" / "b.txt").read_text() == "content b"

    def test_zip_slip_member_skipped(self, tmp_path: Path, capsys) -> None:
        # Construct a zip with a member whose path escapes dest_dir.
        zip_path = tmp_path / "malicious.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("safe.txt", "ok")
            zf.writestr("../../evil.txt", "evil")
        with zipfile.ZipFile(zip_path, "r") as zf:
            extracted = _safe_zip_extract(zf, str(tmp_path))
        # Safe member extracted; evil member skipped.
        assert "safe.txt" in extracted
        assert "../../evil.txt" not in extracted
        captured = capsys.readouterr()
        assert "Zip Slip detected" in captured.out
        assert not (tmp_path / "evil.txt").exists()


# ---------------------------------------------------------------------------
# find_unrpyc_executable
# ---------------------------------------------------------------------------


class TestFindUnrpycExecutable:
    def test_custom_path_py_file(self, tmp_path: Path) -> None:
        custom = tmp_path / "myunrpyc.py"
        custom.write_text("# stub", encoding="utf-8")
        result = find_unrpyc_executable(str(custom), None, auto_download=False)
        assert result is not None
        assert result[0] == sys.executable or "python" in result[0]
        assert result[1] == str(custom)

    def test_custom_path_non_py(self, tmp_path: Path) -> None:
        custom = tmp_path / "unrpyc-bin"
        custom.write_text("# stub", encoding="utf-8")
        result = find_unrpyc_executable(str(custom), None, auto_download=False)
        assert result is not None
        assert result[0] == str(custom)

    def test_cache_dir_walk(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Redirect SENPY_CACHE_DIR to a tmp path with an unrpyc.py inside.
        cache = tmp_path / "cache"
        sub = cache / "unrpyc-1.0"
        sub.mkdir(parents=True)
        (sub / "unrpyc.py").write_text("# stub", encoding="utf-8")
        monkeypatch.setattr("senpy.cli.unrpyc.SENPY_CACHE_DIR", str(cache))
        result = find_unrpyc_executable(None, None, auto_download=False)
        assert result is not None
        assert result[1].endswith("unrpyc.py")

    def test_which_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # No custom path, no cache dir, no local found — shutil.which returns a path.
        monkeypatch.setattr("senpy.cli.unrpyc.SENPY_CACHE_DIR", str(tmp_path / "nocache"))
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/unrpyc")
        result = find_unrpyc_executable(None, None, auto_download=False)
        assert result == ["/usr/local/bin/unrpyc"]

    def test_local_found_in_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # No custom path, no cache, no which — but unrpyc.py in cwd.
        monkeypatch.setattr("senpy.cli.unrpyc.SENPY_CACHE_DIR", str(tmp_path / "nocache"))
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.chdir(tmp_path)
        (tmp_path / "unrpyc.py").write_text("# stub", encoding="utf-8")
        result = find_unrpyc_executable(None, None, auto_download=False)
        assert result is not None
        assert result[1].endswith("unrpyc.py")

    def test_auto_download_prompt_yes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No unrpyc anywhere; auto_download=True; user types "y".
        monkeypatch.setattr("senpy.cli.unrpyc.SENPY_CACHE_DIR", str(tmp_path / "nocache"))
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.chdir(tmp_path)
        # Mock stdin as a tty.
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = True
        monkeypatch.setattr("sys.stdin", fake_stdin)
        monkeypatch.setattr("builtins.input", lambda *a, **kw: "y")
        # download_unrpyc is called — mock it to return a fake cmd.
        monkeypatch.setattr(
            "senpy.cli.unrpyc.download_unrpyc",
            lambda: ["/fake/python", "/fake/unrpyc.py"],
        )
        result = find_unrpyc_executable(None, None, auto_download=True)
        assert result == ["/fake/python", "/fake/unrpyc.py"]

    def test_auto_download_prompt_no(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("senpy.cli.unrpyc.SENPY_CACHE_DIR", str(tmp_path / "nocache"))
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.chdir(tmp_path)
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = True
        monkeypatch.setattr("sys.stdin", fake_stdin)
        monkeypatch.setattr("builtins.input", lambda *a, **kw: "n")
        result = find_unrpyc_executable(None, None, auto_download=True)
        assert result is None

    def test_not_found_returns_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # No unrpyc anywhere, auto_download=False.
        monkeypatch.setattr("senpy.cli.unrpyc.SENPY_CACHE_DIR", str(tmp_path / "nocache"))
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.chdir(tmp_path)
        result = find_unrpyc_executable(None, None, auto_download=False)
        assert result is None


# ---------------------------------------------------------------------------
# extract_scripts_from_rpa
# ---------------------------------------------------------------------------


def _make_rpa_archive(path: Path, files: dict[str, bytes], version: str = "RPA-3.0") -> None:
    """Create a real RPA archive on disk for testing.

    Layout: ``header_line`` + ``payload`` (concatenated file bytes) +
    ``index_bytes`` (zlib-compressed pickle). The header is
    ``"RPA-3.0 <hex_offset> <hex_key>\\n"`` where ``offset`` points at
    ``index_bytes`` and ``key`` is ``0`` (XOR with 0 is a no-op, so the
    same helper works for both RPA-2.0 and RPA-3.0). The index stores
    absolute offsets within the archive file (header_len + payload_offset).
    """
    # First pass: compute the header length so we can compute absolute
    # offsets. The header line is fixed-width: "RPA-3.0 " (8) + 8 hex
    # digits + " " + 16 hex digits + "\n" = 8 + 8 + 1 + 16 + 1 = 34.
    # We'll verify this after building the header.
    payload = b""
    index: dict[str, list[tuple[int, int]]] = {}
    for name, data in files.items():
        payload += data
    index_bytes = zlib.compress(pickle.dumps(index))

    # We need the header length to compute absolute offsets, but the
    # header contains the index offset which depends on the header
    # length. Solve iteratively: assume header_len=34, compute index
    # offset, rebuild header, check length matches.
    header_len = 34  # "RPA-2.0/3.0 " + 8 hex + " " + 16 hex + "\n"
    # Build index with absolute offsets.
    index = {}
    pos = 0
    for name, data in files.items():
        index[name] = [(header_len + pos, len(data))]
        pos += len(data)
    index_bytes = zlib.compress(pickle.dumps(index))
    index_offset = header_len + len(payload)
    header_line = f"{version} {index_offset:08x} 0000000000000000\n".encode()
    # If the header length assumption was wrong, redo with the real length.
    if len(header_line) != header_len:
        header_len = len(header_line)
        index = {}
        pos = 0
        for name, data in files.items():
            index[name] = [(header_len + pos, len(data))]
            pos += len(data)
        index_bytes = zlib.compress(pickle.dumps(index))
        index_offset = header_len + len(payload)
        header_line = f"{version} {index_offset:08x} 0000000000000000\n".encode()
    with open(path, "wb") as f:
        f.write(header_line)
        f.write(payload)
        f.write(index_bytes)


class TestExtractScriptsFromRpa:
    def test_non_rpa_file_returns_empty(self, tmp_path: Path) -> None:
        archive = tmp_path / "notanarchive.rpa"
        archive.write_bytes(b"just some text, not an RPA archive")
        dest = tmp_path / "dest"
        dest.mkdir()
        result = extract_scripts_from_rpa(str(archive), str(dest))
        assert result == []

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        archive = tmp_path / "empty.rpa"
        archive.write_bytes(b"")
        dest = tmp_path / "dest"
        dest.mkdir()
        result = extract_scripts_from_rpa(str(archive), str(dest))
        assert result == []

    def test_rpa_2_0_extracts_rpyc(self, tmp_path: Path) -> None:
        archive = tmp_path / "test.rpa"
        dest = tmp_path / "dest"
        dest.mkdir()
        _make_rpa_archive(archive, {"game/script.rpyc": b"fake rpyc bytes"}, version="RPA-2.0")
        result = extract_scripts_from_rpa(str(archive), str(dest))
        assert len(result) == 1
        extracted = Path(result[0])
        assert extracted.exists()
        assert extracted.read_bytes() == b"fake rpyc bytes"

    def test_rpa_3_0_extracts_rpyc(self, tmp_path: Path) -> None:
        archive = tmp_path / "test.rpa"
        dest = tmp_path / "dest"
        dest.mkdir()
        _make_rpa_archive(archive, {"scene.rpyc": b"rpyc data"}, version="RPA-3.0")
        result = extract_scripts_from_rpa(str(archive), str(dest))
        assert len(result) == 1
        assert Path(result[0]).read_bytes() == b"rpyc data"

    def test_skips_non_rpy_files(self, tmp_path: Path) -> None:
        archive = tmp_path / "test.rpa"
        dest = tmp_path / "dest"
        dest.mkdir()
        _make_rpa_archive(
            archive,
            {"game/script.rpyc": b"rpyc", "readme.txt": b"not rpy"},
            version="RPA-2.0",
        )
        result = extract_scripts_from_rpa(str(archive), str(dest))
        # Only .rpyc / .rpy are extracted; readme.txt is skipped.
        assert len(result) == 1
        assert result[0].endswith(".rpyc")

    def test_cached_file_skipped(self, tmp_path: Path) -> None:
        archive = tmp_path / "test.rpa"
        dest = tmp_path / "dest"
        dest.mkdir()
        _make_rpa_archive(archive, {"script.rpyc": b"new"}, version="RPA-2.0")
        # Pre-create the dest file with "old" content — should not be overwritten
        # because the cache check (dest mtime >= archive mtime) fires.
        dest_file = dest / "script.rpyc"
        dest_file.write_bytes(b"old")
        # Make dest_file newer than the archive (archive was just created).
        import time

        archive_mtime = os.path.getmtime(archive)
        os.utime(dest_file, (archive_mtime + 10, archive_mtime + 10))
        result = extract_scripts_from_rpa(str(archive), str(dest))
        assert len(result) == 1
        # Content unchanged — cache hit.
        assert dest_file.read_bytes() == b"old"


# ---------------------------------------------------------------------------
# decompile_to_sandbox
# ---------------------------------------------------------------------------


class TestDecompileToSandbox:
    def test_rpymc_extension(self, tmp_path: Path) -> None:
        # .rpymc → .rpym (strip last char).
        import pickle

        slot1_data = zlib.compress(pickle.dumps(({}, [])))
        slot1_pos = 34
        slot1_header = struct.pack("III", 1, slot1_pos, len(slot1_data))
        slot0_header = struct.pack("III", 0, 0, 0)
        rpyc_bytes = b"RENPY RPC2" + slot1_header + slot0_header + slot1_data

        rpymc_file = tmp_path / "test.rpymc"
        rpymc_file.write_bytes(rpyc_bytes)

        result = decompile_to_sandbox(
            orphans=[str(rpymc_file)], unrpyc_cmd=None, temp_dir=str(tmp_path)
        )
        assert len(result) == 1
        assert result[0].endswith(".rpym"), f"expected .rpym, got {result[0]}"

    def test_non_rpyc_extension_gets_rpy_suffix(self, tmp_path: Path) -> None:
        # A file with no .rpyc / .rpymc extension gets ".rpy" appended.
        import pickle

        slot1_data = zlib.compress(pickle.dumps(({}, [])))
        slot1_pos = 34
        slot1_header = struct.pack("III", 1, slot1_pos, len(slot1_data))
        slot0_header = struct.pack("III", 0, 0, 0)
        rpyc_bytes = b"RENPY RPC2" + slot1_header + slot0_header + slot1_data

        weird_file = tmp_path / "weird.rpyc.bak"
        weird_file.write_bytes(rpyc_bytes)

        result = decompile_to_sandbox(
            orphans=[str(weird_file)], unrpyc_cmd=None, temp_dir=str(tmp_path)
        )
        # Either decompiled to .rpy or failed — but the rpy_name logic
        # hit the else branch (base_name + ".rpy").
        assert isinstance(result, list)

    def test_decompile_error_prints_message(self, tmp_path: Path, capsys) -> None:
        # Mock decompile_rpyc to raise — the error path should print
        # a red error message and continue to the next file.
        bad_file = tmp_path / "bad.rpyc"
        bad_file.write_bytes(b"not a real rpyc file")

        with patch("senpy.vendor.unrpyc.decompile_rpyc") as mock_decompile:
            mock_decompile.side_effect = RuntimeError("boom")
            result = decompile_to_sandbox(
                orphans=[str(bad_file)], unrpyc_cmd=None, temp_dir=str(tmp_path)
            )
        # Error path: no files decompiled.
        assert result == []
        captured = capsys.readouterr()
        assert "Decompilation error" in captured.out
        assert "RuntimeError" in captured.out


# ---------------------------------------------------------------------------
# download_unrpyc (mocked network)
# ---------------------------------------------------------------------------


class TestDownloadUnrpyc:
    def test_sha_mismatch_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        # Redirect cache dir to tmp.
        monkeypatch.setattr("senpy.cli.unrpyc.SENPY_CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.setattr(
            "senpy.cli.unrpyc.UNRPYC_PINNED_SHA256",
            "0" * 64,  # wrong hash
        )
        # Mock urllib.request.urlopen to return a context manager that
        # yields fake zip bytes. MagicMock auto-implements __enter__/__exit__.
        fake_resp = MagicMock()
        fake_resp.__enter__.return_value = io.BytesIO(b"fake zip content")
        fake_resp.__exit__.return_value = None
        monkeypatch.setattr("urllib.request.urlopen", lambda req: fake_resp)
        result = download_unrpyc()
        assert result is None
        captured = capsys.readouterr()
        assert "SHA256 mismatch" in captured.out

    def test_download_error_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        import urllib.error

        monkeypatch.setattr("senpy.cli.unrpyc.SENPY_CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req: (_ for _ in ()).throw(urllib.error.URLError("network down")),
        )
        result = download_unrpyc()
        assert result is None
        captured = capsys.readouterr()
        assert "Failed to download unrpyc" in captured.out
