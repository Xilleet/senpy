"""Workspace containment check в `_uri_to_path`.

Security-тесты для валидации `file:` scheme и workspace containment.

Уязвимость до:
  `_uri_to_path("file:///etc/passwd")` возвращал путь `/etc/passwd` без
  какой-либо проверки. Злонамеренный LSP-клиент (или манипулирующий workspace
  root) мог заставить Senpy читать произвольные файлы вне проекта.

после:
  1. Только `file:` scheme принимается. Остальные (`http:`, `https:`, `ftp:`,
     `git+ssh:` и т.д.) — `ValueError`.
  2. Если передан `workspace_root`, путь обязан находиться внутри него
     (после нормализации через `os.path.realpath`). Иначе — `ValueError`.
  3. Защита от path traversal: `..` сегменты не должны позволять выйти за
     пределы workspace.
  4. На Windows UNC-пути (двойные backslash-пути к сетевым ресурсам) поведение
     не меняется — `file:` scheme нормализуется через `Path.as_uri()`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import senpy.lsp.server as server_mod

# =============================================================================
# Scheme validation
# =============================================================================

def test_uri_to_path_accepts_file_scheme(tmp_path: Path):
    """`file:` URI обязан парситься (backward compat)."""
    f = tmp_path / "script.rpy"
    f.write_text("label start:\n    pass\n", encoding="utf-8")
    uri = f.as_uri()
    result = server_mod._uri_to_path(uri)
    assert os.path.normcase(result) == os.path.normcase(str(f))


def test_uri_to_path_rejects_http_scheme():
    """`http:` URI должен быть отклонён."""
    with pytest.raises(ValueError, match="(?i)scheme"):
        server_mod._uri_to_path("http://evil.example.com/script.rpy")


def test_uri_to_path_rejects_https_scheme():
    """`https:` URI должен быть отклонён."""
    with pytest.raises(ValueError, match="(?i)scheme"):
        server_mod._uri_to_path("https://evil.example.com/script.rpy")


def test_uri_to_path_rejects_ftp_scheme():
    """`ftp:` URI должен быть отклонён."""
    with pytest.raises(ValueError, match="(?i)scheme"):
        server_mod._uri_to_path("ftp://evil.example.com/script.rpy")


def test_uri_to_path_rejects_empty_scheme():
    """URI без scheme (относительный путь) должен быть отклонён."""
    with pytest.raises(ValueError, match="(?i)scheme"):
        server_mod._uri_to_path("just/a/path.rpy")


# =============================================================================
# Workspace containment check
# =============================================================================

def test_uri_to_path_inside_workspace_ok(tmp_path: Path):
    """URI внутри workspace_root — ОК."""
    workspace = tmp_path / "project"
    workspace.mkdir()
    script = workspace / "game" / "script.rpy"
    script.parent.mkdir(parents=True)
    script.write_text("label start:\n    pass\n", encoding="utf-8")
    uri = script.as_uri()
    result = server_mod._uri_to_path(uri, workspace_root=str(workspace))
    assert os.path.normcase(result) == os.path.normcase(str(script))


def test_uri_to_path_outside_workspace_rejected(tmp_path: Path):
    """URI вне workspace_root должен быть отклонён."""
    workspace = tmp_path / "project"
    workspace.mkdir()
    outside = tmp_path / "secret" / "passwd"
    outside.parent.mkdir(parents=True)
    outside.write_text("root:x:0:0\n", encoding="utf-8")
    uri = outside.as_uri()
    with pytest.raises(ValueError, match="(?i)outside.*workspace|containment"):
        server_mod._uri_to_path(uri, workspace_root=str(workspace))


def test_uri_to_path_path_traversal_rejected(tmp_path: Path):
    """Path traversal через `..` не должен позволять выйти за workspace."""
    workspace = tmp_path / "project"
    workspace.mkdir()
    # Создаём поддиректорию и пытаемся через .. выйти наружу
    sub = workspace / "sub"
    sub.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("secret\n", encoding="utf-8")
    # URI с .. сегментами
    malicious_uri = f"file://{workspace}/sub/../../outside.txt"
    with pytest.raises(ValueError, match="(?i)outside.*workspace|containment"):
        server_mod._uri_to_path(malicious_uri, workspace_root=str(workspace))


def test_uri_to_path_no_workspace_root_skips_containment(tmp_path: Path):
    """Без workspace_root containment-проверка не делается (backward compat).

    Обоснование: ряд handlers вызывает `_uri_to_path` до того, как workspace
    root известен (ранняя инициализация). В этом случае проверка scheme
    всё равно работает, containment — нет.
    """
    f = tmp_path / "script.rpy"
    f.write_text("label start:\n    pass\n", encoding="utf-8")
    uri = f.as_uri()
    result = server_mod._uri_to_path(uri)  # без workspace_root
    assert os.path.normcase(result) == os.path.normcase(str(f))


# =============================================================================
# Backward compat — без scheme check сломал бы существующие тесты
# =============================================================================

def test_uri_to_path_preserves_backward_compat(tmp_path: Path):
    """Старые вызовы без workspace_root должны работать как раньше
    (за исключением scheme validation, которая теперь строгая)."""
    f = tmp_path / "script.rpy"
    f.write_text("label start:\n    pass\n", encoding="utf-8")
    uri = f.as_uri()
    result = server_mod._uri_to_path(uri)
    # Должен вернуть путь, который можно открыть
    with open(result, "r", encoding="utf-8") as fh:
        content = fh.read()
    assert "label start" in content


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only path test")
def test_uri_to_path_unix_absolute(tmp_path: Path):
    """Unix-абсолютный путь через file: scheme."""
    f = tmp_path / "game" / "script.rpy"
    f.parent.mkdir(parents=True)
    f.write_text("label start:\n    pass\n", encoding="utf-8")
    # Явная конструкция URI
    uri = f"file://{f}"
    result = server_mod._uri_to_path(uri, workspace_root=str(tmp_path))
    assert os.path.normcase(result) == os.path.normcase(str(f))
