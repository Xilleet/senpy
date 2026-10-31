"""CLI-15: .senpy-ignore файл — bulk rule exclusions.

Контракт:
  - При запуске Senpy ищет `.senpy-ignore` в корне проекта (args.path).
  - Файл содержит один rule code per line.
  - Строки начинающиеся с `#` — комментарии, игнорируются.
  - Inline comments после `#` тоже поддерживаются: `RPY101 # typo in dialogue`.
  - Пустые строки игнорируются.
  - Rule codes нормализуются (uppercase, strip).
  - Если файл не существует — никаких exclusions (молча, без warning).
  - Exclusions из .senpy-ignore добавляются к ignored_codes
    (объединяются с --ignore / --extend-ignore / config.ignore).

Формат:
    # .senpy-ignore
    RPY101  # typo in dialogue variable
    RPY104
    # RPY105  # commented out — rule will fire
    RPY301

Семантика: как если бы пользователь передал --ignore для каждого кода.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import senpy.cli.main as cli_main
from senpy.cli.main import load_senpy_ignore


def _make_args(**kwargs) -> MagicMock:
    """Создаёт args Namespace с дефолтами."""
    args = MagicMock()
    args.path = kwargs.get("path", ".")
    return args


def _write_senpy_ignore(project_path: Path, content: str) -> Path:
    """Создаёт .senpy-ignore файл в проекте."""
    ignore_file = project_path / ".senpy-ignore"
    ignore_file.write_text(content, encoding="utf-8")
    return ignore_file


# =============================================================================
# 1. Базовое чтение файла
# =============================================================================

def test_load_senpy_ignore_returns_empty_set_if_no_file(tmp_path: Path):
    """Если .senpy-ignore не существует — возвращается пустое множество."""
    result = load_senpy_ignore(str(tmp_path))
    assert result == set()


def test_load_senpy_ignore_reads_simple_codes(tmp_path: Path):
    """Читает простые rule codes по одному на строку."""
    _write_senpy_ignore(tmp_path, "RPY101\nRPY104\nRPY301\n")
    result = load_senpy_ignore(str(tmp_path))
    assert result == {"RPY101", "RPY104", "RPY301"}


# =============================================================================
# 2. Комментарии
# =============================================================================

def test_load_senpy_ignore_skips_comments(tmp_path: Path):
    """Строки начинающиеся с # — комментарии, игнорируются."""
    _write_senpy_ignore(tmp_path, "# This is a comment\nRPY101\n# Another comment\nRPY104\n")
    result = load_senpy_ignore(str(tmp_path))
    assert result == {"RPY101", "RPY104"}


def test_load_senpy_ignore_handles_inline_comments(tmp_path: Path):
    """Inline comments после # поддерживаются: `RPY101 # typo`."""
    _write_senpy_ignore(tmp_path, "RPY101  # typo in dialogue\nRPY104 # missing default\n")
    result = load_senpy_ignore(str(tmp_path))
    assert result == {"RPY101", "RPY104"}


def test_load_senpy_ignore_skips_empty_lines(tmp_path: Path):
    """Пустые строки игнорируются."""
    _write_senpy_ignore(tmp_path, "RPY101\n\n\nRPY104\n\n")
    result = load_senpy_ignore(str(tmp_path))
    assert result == {"RPY101", "RPY104"}


def test_load_senpy_ignore_commented_rule_not_included(tmp_path: Path):
    """Строка `# RPY105` — это комментарий, RPY105 НЕ добавляется."""
    _write_senpy_ignore(tmp_path, "RPY101\n# RPY105\nRPY104\n")
    result = load_senpy_ignore(str(tmp_path))
    assert "RPY105" not in result
    assert result == {"RPY101", "RPY104"}


# =============================================================================
# 3. Нормализация
# =============================================================================

def test_load_senpy_ignore_normalizes_to_uppercase(tmp_path: Path):
    """Rule codes нормализуются к uppercase."""
    _write_senpy_ignore(tmp_path, "rpy101\nRpy104\nRPY301\n")
    result = load_senpy_ignore(str(tmp_path))
    assert result == {"RPY101", "RPY104", "RPY301"}


def test_load_senpy_ignore_strips_whitespace(tmp_path: Path):
    """Пробелы и табы вокруг code обрезаются."""
    _write_senpy_ignore(tmp_path, "  RPY101  \n\tRPY104\t\n  RPY301  \n")
    result = load_senpy_ignore(str(tmp_path))
    assert result == {"RPY101", "RPY104", "RPY301"}


# =============================================================================
# 4. Edge cases
# =============================================================================

def test_load_senpy_ignore_empty_file(tmp_path: Path):
    """Пустой файл — пустое множество."""
    _write_senpy_ignore(tmp_path, "")
    result = load_senpy_ignore(str(tmp_path))
    assert result == set()


def test_load_senpy_ignore_only_comments(tmp_path: Path):
    """Файл только с комментариями — пустое множество."""
    _write_senpy_ignore(tmp_path, "# Just a comment\n# Another\n")
    result = load_senpy_ignore(str(tmp_path))
    assert result == set()


def test_load_senpy_ignore_invalid_codes_included(tmp_path: Path):
    """Невалидные codes тоже добавляются — валидация не наша забота.

    Если юзер написал `RPY999` (которого не существует) — он просто попадёт
    в ignored set, но ничего не сломает (нет такого правила = ничего не
    игнорируется).
    """
    _write_senpy_ignore(tmp_path, "RPY101\nRPY999\n")
    result = load_senpy_ignore(str(tmp_path))
    assert result == {"RPY101", "RPY999"}


# =============================================================================
# 5. Ищет файл в правильном месте
# =============================================================================

def test_load_senpy_ignore_finds_file_in_project_root(tmp_path: Path):
    """Файл ищется в корне project_path, не в CWD."""
    project = tmp_path / "my_project"
    project.mkdir()
    game_dir = project / "game"
    game_dir.mkdir()
    _write_senpy_ignore(project, "RPY101\n")

    result = load_senpy_ignore(str(project))
    assert result == {"RPY101"}


def test_load_senpy_ignore_no_file_in_subdir(tmp_path: Path):
    """Если .senpy-ignore в поддиректории — он НЕ применяется."""
    project = tmp_path / "my_project"
    project.mkdir()
    subdir = project / "game"
    subdir.mkdir()
    # Файл в поддиректории, не в корне
    ignore_in_subdir = subdir / ".senpy-ignore"
    ignore_in_subdir.write_text("RPY101\n", encoding="utf-8")

    result = load_senpy_ignore(str(project))
    assert result == set()  # Файл в поддиректории не найден
