"""CLI-17: load_config должен логировать TOMLDecodeError, не молча глотать.

Контракт:
  - Если конфиг-файл содержит битый TOML — load_config возвращает {} (как и
    раньше, backward compat), НО логирует WARNING с путём и текстом ошибки.
  - caplog должен ловить это сообщение.
  - OSError (например, permission denied) — тоже логируется как WARNING.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from senpy.core.config import load_config
from senpy.core.logging import setup_logging


@pytest.fixture(autouse=True)
def reset_logging():
    setup_logging()
    yield


def test_load_config_logs_invalid_toml(tmp_path: Path, caplog, monkeypatch):
    """Битый TOML должен логироваться как WARNING."""
    # Изолируемся от CWD репо (там есть senpy.toml)
    empty_cwd = tmp_path / "empty_cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)

    # Создаём проект с битым senpy.toml
    project = tmp_path / "my_project"
    project.mkdir()
    bad_toml = project / "senpy.toml"
    bad_toml.write_text(
        'this is = "not"\nvalid = [toml at all\n',  # незакрытая скобка
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="senpy.config"):
        result = load_config(str(project))

    # backward compat: возвращает пустой dict
    assert result == {}
    # НО: логирует warning
    assert any(
        "TOMLDecodeError" in r.message or "TOML" in r.message or "invalid" in r.message.lower()
        for r in caplog.records
    ), f"warning not logged: {caplog.records}"
    # В сообщении должен быть путь к файлу
    assert any(
        str(bad_toml) in r.message or "senpy.toml" in r.message
        for r in caplog.records
    ), f"path not in log: {caplog.records}"


def test_load_config_logs_oserror(tmp_path: Path, caplog, monkeypatch):
    """OSError (например, файл недоступен для чтения) тоже логируется."""
    empty_cwd = tmp_path / "empty_cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)

    project = tmp_path / "my_project"
    project.mkdir()
    config_file = project / "senpy.toml"
    config_file.write_text("[senpy]\n", encoding="utf-8")

    # Мокаем open() чтобы он падал с PermissionError
    real_open = open

    def fake_open(path, *args, **kwargs):
        if str(path) == str(config_file):
            raise PermissionError("mocked: permission denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)

    with caplog.at_level(logging.WARNING, logger="senpy.config"):
        result = load_config(str(project))

    # backward compat: возвращает пустой dict
    assert result == {}
    # Логирует warning про ошибку чтения
    assert any(
        "permission" in r.message.lower() or "oserror" in r.message.lower()
        or "read" in r.message.lower() or "config" in r.message.lower()
        for r in caplog.records
    ), f"warning not logged: {caplog.records}"


def test_load_config_valid_toml_no_warning(tmp_path: Path, caplog, monkeypatch):
    """Валидный TOML не должен логировать warning."""
    empty_cwd = tmp_path / "empty_cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)

    project = tmp_path / "my_project"
    project.mkdir()
    config_file = project / "senpy.toml"
    config_file.write_text(
        '[senpy]\nstrict = false\nignore = ["RPY001"]\n',
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="senpy.config"):
        result = load_config(str(project))

    # CLI-16: pydantic добавляет дефолты для всех полей, поэтому проверяем
    # только ключевые поля, а не точное равенство.
    assert result.get("strict") is False
    assert result.get("ignore") == ["RPY001"]
    # Никаких warning'ов
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings == [], f"unexpected warnings: {warnings}"


def test_load_config_no_file_no_warning(tmp_path: Path, caplog, monkeypatch):
    """Если конфиг-файла нет — warning не логируется (это нормальный кейс)."""
    empty_cwd = tmp_path / "empty_cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)

    project = tmp_path / "my_project"
    project.mkdir()

    with caplog.at_level(logging.WARNING, logger="senpy.config"):
        result = load_config(str(project))

    assert result == {}
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings == [], f"unexpected warnings: {warnings}"
