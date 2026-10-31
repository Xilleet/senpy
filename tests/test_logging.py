"""QUA-9: senpy/core/logging.py — centralized logging setup.

TDD-контракт для `setup_logging()`:

  1. Возвращает `logging.Logger` с именем `"senpy"` (главный logger проекта).
  2. По умолчанию НЕ выводит в stderr — использует `logging.NullHandler()`
     (library best practice: caller решает, куда писать).
  3. `verbose=True` добавляет `StreamHandler` с formatter'ом
     `[%(asctime)s] %(levelname)s %(name)s: %(message)s` на stderr.
  4. `log_file=<path>` добавляет `FileHandler` с тем же formatter'ом.
  5. `setup_logging()` идемпотентен: повторный вызов не дублирует handlers.
  6. Sub-loggers (`senpy.plugins`, `senpy.lsp`, `senpy.cli`) наследуют
     propagate=True от корня, не имеют своих handlers.
  7. `get_logger(name)` — public API для подмодулей; возвращает child
     logger с именем `"senpy.<name>"`.

Обоснование дизайна:
  - Library-стиль (NullHandler по умолчанию) — Senpy используется и как CLI,
    и как LSP-сервер, и как библиотека (senpy.api). В LSP-режиме stderr
    занят LSP-протоколом; лишний вывод ломает клиент. Поэтому по умолчанию
    тишина.
  - Caller (cli/main.py, lsp/server.py) явно вызывает `setup_logging(verbose=...)`
    когда хочет вывод.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from senpy.core.logging import get_logger, setup_logging

# =============================================================================
# 1. Defaults — library best practice
# =============================================================================

def test_setup_logging_returns_senpy_logger():
    """setup_logging() возвращает logger с именем 'senpy'."""
    logger = setup_logging()
    assert logger.name == "senpy"


def test_setup_logging_default_has_null_handler():
    """По умолчанию — только NullHandler (library best practice).

    Никаких StreamHandler, FileHandler — caller решает, куда писать.
    """
    logger = setup_logging()
    # NullHandler должен быть в списке (он не пишет никуда).
    handler_types = [type(h).__name__ for h in logger.handlers]
    assert "NullHandler" in handler_types


def test_setup_logging_no_stream_handler_by_default():
    """Без verbose=True не должно быть StreamHandler (защита LSP stderr)."""
    logger = setup_logging()
    handler_types = [type(h).__name__ for h in logger.handlers]
    assert "StreamHandler" not in handler_types


# =============================================================================
# 2. Verbose mode
# =============================================================================

def test_setup_logging_verbose_adds_stream_handler():
    """verbose=True добавляет StreamHandler."""
    logger = setup_logging(verbose=True)
    handler_types = [type(h).__name__ for h in logger.handlers]
    assert "StreamHandler" in handler_types


def test_setup_logging_verbose_emits_messages(caplog):
    """verbose=True позволяет писать логи на уровне INFO и выше."""
    logger = setup_logging(verbose=True)
    # caplog перехватывает через propagate
    with caplog.at_level(logging.INFO, logger="senpy"):
        logger.info("test message")
    assert "test message" in caplog.text


# =============================================================================
# 3. Idempotency
# =============================================================================

def test_setup_logging_is_idempotent():
    """Повторный вызов setup_logging не дублирует handlers."""
    logger1 = setup_logging(verbose=True)
    count1 = len(logger1.handlers)
    logger2 = setup_logging(verbose=True)
    count2 = len(logger2.handlers)
    assert logger1 is logger2  # тот же объект
    assert count1 == count2, f"handler count changed: {count1} → {count2}"


def test_setup_logging_can_switch_modes():
    """Смена verbose → default убирает StreamHandler."""
    logger_verbose = setup_logging(verbose=True)
    assert any(type(h).__name__ == "StreamHandler" for h in logger_verbose.handlers)

    logger_default = setup_logging()  # verbose=False
    assert not any(
        type(h).__name__ == "StreamHandler" for h in logger_default.handlers
    )


# =============================================================================
# 4. File handler
# =============================================================================

def test_setup_logging_with_log_file(tmp_path: Path):
    """log_file добавляет FileHandler."""
    log_path = tmp_path / "senpy.log"
    logger = setup_logging(log_file=str(log_path))
    handler_types = [type(h).__name__ for h in logger.handlers]
    assert "FileHandler" in handler_types


def test_setup_logging_log_file_writes_messages(tmp_path: Path):
    """Логи реально пишутся в файл."""
    log_path = tmp_path / "senpy.log"
    logger = setup_logging(log_file=str(log_path), verbose=False)
    logger.warning("test warning message")
    # flush all handlers
    for h in logger.handlers:
        h.flush()
    content = log_path.read_text(encoding="utf-8")
    assert "test warning message" in content
    assert "WARNING" in content


# =============================================================================
# 5. get_logger — public API for submodules
# =============================================================================

def test_get_logger_returns_child():
    """get_logger('plugins') возвращает logger с именем 'senpy.plugins'."""
    sub = get_logger("plugins")
    assert sub.name == "senpy.plugins"


def test_get_logger_propagates_to_root():
    """Child logger propagate=True — пишет через родителя."""
    sub = get_logger("test_module")
    assert sub.propagate is True


def test_get_logger_has_no_own_handlers():
    """Child logger не имеет своих handlers (всё через корень)."""
    setup_logging()  # гарантируем корень инициализирован
    sub = get_logger("submodule_xyz")
    # Sub-loggers не должны добавлять своих handlers
    assert len(sub.handlers) == 0


# =============================================================================
# 6. Formatter — стандартный формат
# =============================================================================

def test_setup_logging_formatter_format(tmp_path: Path):
    """Formatter включает timestamp, level, name, message."""
    log_path = tmp_path / "fmt.log"
    logger = setup_logging(log_file=str(log_path))
    logger.warning("hello world")
    for h in logger.handlers:
        h.flush()
    content = log_path.read_text(encoding="utf-8")
    # Должны быть: timestamp (год), WARNING, senpy, hello world
    assert "WARNING" in content
    assert "senpy" in content
    assert "hello world" in content


# =============================================================================
# 7. Integration — log levels work correctly
# =============================================================================

def test_log_levels_respected(tmp_path: Path):
    """DEBUG не пишется по умолчанию (level=INFO)."""
    log_path = tmp_path / "levels.log"
    logger = setup_logging(log_file=str(log_path))
    logger.debug("debug msg")
    logger.info("info msg")
    logger.warning("warn msg")
    for h in logger.handlers:
        h.flush()
    content = log_path.read_text(encoding="utf-8")
    assert "info msg" in content
    assert "warn msg" in content
    # DEBUG не должен попасть
    assert "debug msg" not in content
