"""QUA-13: Доменные исключения вместо silent return.

Контракт:
  - `_uri_to_path` теперь кидает `SecurityError` (не `ValueError`) при
    неверной scheme или path traversal. SecurityError наследуется от
    ValueError для backward compat.
  - `download_unrpyc` при SHA mismatch логирует ERROR (не silent return).
  - Дополнительно: `ApiVersionMismatchError` теперь `PluginError`-наследник
    (проверено в test_exceptions.py).

TDD для QUA-13:
  1. test_uri_to_path_raises_security_error — scheme violation.
  2. test_security_error_is_value_error_subclass — backward compat.
  3. test_download_unrpyc_sha_mismatch_logs_error — critical log.
"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from senpy.core.exceptions import SecurityError, SenpyError
from senpy.core.logging import setup_logging


@pytest.fixture(autouse=True)
def reset_logging():
    setup_logging(level=logging.DEBUG)
    yield


# =============================================================================
# 1. _uri_to_path raises SecurityError (not ValueError)
# =============================================================================

def test_uri_to_path_raises_security_error_for_http():
    """_uri_to_path должен кидать SecurityError (не просто ValueError)."""
    import senpy.lsp.server as server_mod

    with pytest.raises(SecurityError) as exc_info:
        server_mod._uri_to_path("http://evil.com/x.rpy")

    # Сообщение содержит scheme
    assert "http" in str(exc_info.value)


def test_uri_to_path_raises_security_error_for_path_traversal(tmp_path: Path):
    """Path traversal должен кидать SecurityError."""
    import senpy.lsp.server as server_mod

    workspace = tmp_path / "project"
    workspace.mkdir()
    malicious_uri = f"file://{workspace}/sub/../../outside.txt"

    with pytest.raises(SecurityError):
        server_mod._uri_to_path(malicious_uri, workspace_root=str(workspace))


def test_uri_to_path_security_error_is_catchable_as_value_error():
    """SecurityError должен ловиться как ValueError (backward compat).

    Старый код (до QUA-13) мог делать `except ValueError:` для _uri_to_path.
    После QUA-13 этот код должен продолжать работать.
    """
    import senpy.lsp.server as server_mod

    # Симулируем старый caller
    caught_as_value_error = False
    try:
        server_mod._uri_to_path("ftp://evil.com/x.rpy")
    except ValueError:
        caught_as_value_error = True

    assert caught_as_value_error, "SecurityError should be catchable as ValueError"


def test_uri_to_path_security_error_is_catchable_as_senpy_error():
    """SecurityError должен ловиться как SenpyError (новый контракт)."""
    import senpy.lsp.server as server_mod

    caught_as_senpy_error = False
    try:
        server_mod._uri_to_path("ftp://evil.com/x.rpy")
    except SenpyError:
        caught_as_senpy_error = True

    assert caught_as_senpy_error, "SecurityError should be catchable as SenpyError"


# =============================================================================
# 2. download_unrpyc logs ERROR on SHA mismatch (not silent)
# =============================================================================

def test_download_unrpyc_sha_mismatch_logs_error(caplog, tmp_path: Path, monkeypatch):
    """При SHA mismatch download_unrpyc должен логировать ERROR.

    Раньше (до QUA-13): silent return None.
    После QUA-13: log.error(...) + return None (backward compat).
    """
    from senpy.cli import unrpyc as unrpyc_mod

    # Мокаем _verify_unrpyc_sha256 чтобы вернуть False (SHA mismatch)
    monkeypatch.setattr(unrpyc_mod, "_verify_unrpyc_sha256", lambda _: False)

    # Мокаем urllib.request.urlopen чтобы вернуть fake context manager
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, n=-1): return b"fake data"

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, **kw: FakeResponse(),
    )

    # Мокаем open() чтобы не писать файл
    import builtins

    class FakeFile:
        def __init__(self, *a, **kw):
            pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def write(self, data): pass

    monkeypatch.setattr(builtins, "open", lambda *a, **kw: FakeFile())
    # shutil.copyfileobj — no-op
    monkeypatch.setattr("shutil.copyfileobj", lambda src, dst: None)
    # os.remove — no-op
    monkeypatch.setattr("os.remove", lambda p: None)

    with caplog.at_level(logging.ERROR, logger="senpy.cli.unrpyc"):
        result = unrpyc_mod.download_unrpyc()

    # Backward compat: return None on SHA mismatch
    assert result is None

    # QUA-13: ERROR должен быть в логах
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any(
        "sha256" in r.message.lower() or "sha" in r.message.lower()
        or "supply-chain" in r.message.lower() or "verification" in r.message.lower()
        for r in error_records
    ), f"no ERROR log for SHA mismatch: {error_records}"
