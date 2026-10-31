"""pydantic валидация схемы конфига.

  - Создаётся pydantic-модель SenpyConfig с типами полей.
  - load_config() возвращает dict, который проходит pydantic валидацию.
  - Если конфиг невалиден (например, max_errors = "много") — логируется
    WARNING с понятным сообщением, и возвращается пустой config (fallback).
  - Неизвестные поля в [tool.senpy] игнорируются (forward-compat).
  - Опциональные поля имеют дефолты.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from senpy.core.config import load_config, validate_config
from senpy.core.logging import setup_logging


@pytest.fixture(autouse=True)
def reset_logging():
    setup_logging(level=logging.DEBUG)
    yield


# =============================================================================
# 1. validate_config — базовая валидация
# =============================================================================

def test_validate_config_accepts_valid_config():
    """Валидный конфиг проходит без ошибок."""
    valid_config = {
        "decompile": True,
        "max_errors": 50,
        "info": False,
        "errors_only": False,
        "tsundere": False,
        "ignore": ["RPY101", "RPY104"],
        "select": ["RPY102"],
        "extend_select": ["RPY103"],
        "extend_ignore": ["RPY105"],
    }
    validated = validate_config(valid_config)
    assert validated["decompile"] is True
    assert validated["max_errors"] == 50
    assert validated["ignore"] == ["RPY101", "RPY104"]


def test_validate_config_accepts_empty_config():
    """Пустой конфиг проходит, всё по дефолтам."""
    validated = validate_config({})
    # Дефолты
    assert validated["decompile"] is False
    assert validated["max_errors"] == 50
    assert validated["info"] is False
    assert validated["errors_only"] is False
    assert validated["tsundere"] is False
    assert validated["ignore"] == []


def test_validate_config_unknown_keys_ignored():
    """Неизвестные ключи игнорируются (forward-compat)."""
    config_with_unknown = {
        "decompile": True,
        "future_feature": "not yet implemented",
        "experimental": {"nested": True},
    }
    validated = validate_config(config_with_unknown)
    assert validated["decompile"] is True
    # Неизвестные ключи не попадают в результат
    assert "future_feature" not in validated
    assert "experimental" not in validated


# =============================================================================
# 2. Type validation
# =============================================================================

def test_validate_config_rejects_max_errors_as_string(caplog):
    """max_errors = "много" — невалидный тип, логируется warning."""
    bad_config = {"max_errors": "много"}
    with caplog.at_level(logging.WARNING, logger="senpy.config"):
        validated = validate_config(bad_config)

    # Fallback: возвращается пустой конфиг
    assert validated == {} or validated.get("max_errors") == 50
    # Warning логирован
    assert any(
        "max_errors" in r.message.lower() or "validation" in r.message.lower()
        for r in caplog.records
    ), f"no warning logged: {caplog.records}"


def test_validate_config_rejects_decompile_as_string(caplog):
    """decompile = "yes" — невалидный тип (ожидается bool)."""
    bad_config = {"decompile": "yes"}
    with caplog.at_level(logging.WARNING, logger="senpy.config"):
        validated = validate_config(bad_config)

    # Fallback
    assert validated == {} or validated.get("decompile") is False
    assert any(
        "decompile" in r.message.lower() or "validation" in r.message.lower()
        for r in caplog.records
    )


def test_validate_config_rejects_ignore_as_string(caplog):
    """ignore = "RPY101" — невалидный тип (ожидается list)."""
    bad_config = {"ignore": "RPY101"}  # string вместо list
    with caplog.at_level(logging.WARNING, logger="senpy.config"):
        validated = validate_config(bad_config)

    assert validated == {} or validated.get("ignore") == []
    assert any(
        "ignore" in r.message.lower() or "validation" in r.message.lower()
        for r in caplog.records
    )


# =============================================================================
# 3. Опциональные поля и дефолты
# =============================================================================

def test_validate_config_partial_config_uses_defaults():
    """Частичный конфиг — недостающие поля берутся из дефолтов."""
    partial = {"decompile": True}
    validated = validate_config(partial)
    assert validated["decompile"] is True
    # Остальное по дефолту
    assert validated["max_errors"] == 50
    assert validated["ignore"] == []


def test_validate_config_unrpyc_path_optional():
    """unrpyc_path — опциональное, может быть None или строкой."""
    validated = validate_config({"unrpyc_path": "tools/unrpyc.py"})
    assert validated["unrpyc_path"] == "tools/unrpyc.py"

    validated = validate_config({})
    assert validated.get("unrpyc_path") is None


def test_validate_config_severity_dict():
    """severity — dict rule_code → severity string."""
    config = {
        "severity": {
            "RPY104": "ERROR",
            "RPY308": "INFO",
        }
    }
    validated = validate_config(config)
    assert validated["severity"]["RPY104"] == "ERROR"
    assert validated["severity"]["RPY308"] == "INFO"


# =============================================================================
# 4. Integration с load_config
# =============================================================================

def test_load_config_validates_via_pydantic(tmp_path: Path, monkeypatch, caplog):
    """load_config использует validate_config и логирует ошибки."""
    # Изолируемся от CWD репо
    empty_cwd = tmp_path / "empty_cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)

    project = tmp_path / "my_project"
    project.mkdir()
    config_file = project / "senpy.toml"
    config_file.write_text(
        '[senpy]\nmax_errors = "много"\n',  # невалидный тип
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="senpy.config"):
        result = load_config(str(project))

    # Fallback: пустой конфиг
    assert result == {}
    # WARNING логирован
    assert any(
        "max_errors" in r.message.lower() or "validation" in r.message.lower()
        for r in caplog.records
    )


def test_load_config_valid_config_passes(tmp_path: Path, monkeypatch):
    """Валидный TOML проходит pydantic валидацию без warnings."""
    empty_cwd = tmp_path / "empty_cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)

    project = tmp_path / "my_project"
    project.mkdir()
    config_file = project / "senpy.toml"
    config_file.write_text(
        '[senpy]\nmax_errors = 50\ndecompile = true\nignore = ["RPY101"]\n',
        encoding="utf-8",
    )

    result = load_config(str(project))
    assert result["max_errors"] == 50
    assert result["decompile"] is True
    assert result["ignore"] == ["RPY101"]
