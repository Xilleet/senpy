"""Centralized logging setup for Senpy.

Library-style logging:
  - Default: `NullHandler` only (no output). Caller decides where to write.
  - `verbose=True`: `StreamHandler` to stderr with formatter.
  - `log_file=<path>`: `FileHandler` with same formatter.
  - Idempotent: re-calling `setup_logging()` does not duplicate handlers.

Why NullHandler by default?
  Senpy runs in three modes: CLI (stdout/stderr for humans), LSP server
  (stderr is reserved for LSP protocol — extra output breaks the client),
  and library (`senpy.api`). Default silence is the only safe choice;
  callers opt-in to output via `verbose=True` or `log_file`.

Public API:
  - `setup_logging(verbose=False, log_file=None) -> logging.Logger`
  - `get_logger(name: str) -> logging.Logger` — for submodules,
    returns child logger `"senpy.<name>"` with `propagate=True`.

Usage in cli/main.py:
  from senpy.core.logging import setup_logging
  setup_logging(verbose=args.verbose)
  logger = get_logger("cli")
  logger.info("analyzing %d files", n)

Usage in plugins/loader.py:
  from senpy.core.logging import get_logger
  logger = get_logger("plugins")
  logger.warning("Plugin %s failed: %s", name, e)
"""
from __future__ import annotations

import logging
import sys

__all__ = ["setup_logging", "get_logger", "LOGGER_NAME"]

LOGGER_NAME = "senpy"
_DEFAULT_FORMAT = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _clear_handlers(logger: logging.Logger) -> None:
    """Удалить все существующие handlers (для идемпотентности)."""
    for h in list(logger.handlers):
        logger.removeHandler(h)
        try:  # noqa: SIM105
            h.close()
        except Exception:  # noqa: BLE001 — close() не должен падать cleanup
            pass


def setup_logging(
    verbose: bool = False,
    log_file: str | None = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """Инициализация главного Senpy-логгера.

    Идемпотентна: повторные вызовы заменяют конфигурацию (не дублируют
    handlers). Это позволяет cli/main.py и lsp/server.py независимо
    вызывать setup_logging — последний вызов выигрывает.

    Args:
        verbose: Если True — добавляет StreamHandler на stderr.
            False (по умолчанию) — тишина (NullHandler). LSP-режим
            ОБЯЗАН использовать verbose=False.
        log_file: Если передан — добавляет FileHandler с этим путём.
            Файл открывается в append-режиме (не перезаписывается).
        level: Уровень логирования. По умолчанию INFO. DEBUG включает
            расширенную диагностику.

    Returns:
        Главный logger проекта (имя "senpy").
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    # propagate=True (по умолчанию): позволяет pytest caplog перехватывать
    # логи, и позволяет caller'у добавить свой handler на root logger
    # (например через logging.basicConfig()). Дублирования не возникает,
    # потому что у root по умолчанию нет handlers (lastResort = WARNING
    # на stderr срабатывает только если ни у кого нет handlers).
    logger.propagate = True

    # Идемпотентность: очищаем старые handlers перед установкой новых.
    _clear_handlers(logger)

    # NullHandler всегда добавляется — это гарантирует что даже без
    # verbose/log_file вызовы logger.* не падают с "No handlers could be found".
    logger.addHandler(logging.NullHandler())

    formatter = logging.Formatter(_DEFAULT_FORMAT, datefmt=_DEFAULT_DATEFMT)

    if verbose:
        sh = logging.StreamHandler(stream=sys.stderr)
        sh.setFormatter(formatter)
        sh.setLevel(level)
        logger.addHandler(sh)

    if log_file:
        # append mode, UTF-8 — для кросс-платформенности (Windows cp1251
        # по умолчанию ломает русские сообщения).
        fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        fh.setFormatter(formatter)
        fh.setLevel(level)
        logger.addHandler(fh)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Возвращает child logger с именем "senpy.<name>".

    Для подмодулей (cli, lsp, plugins, core, ...). Child-логгер:
      - Не имеет своих handlers (всё через корень "senpy").
      - propagate=True (по умолчанию для child loggers в Python).
      - Уровень наследуется от родителя.

    Args:
        name: Имя подмодуля (без префикса "senpy."). Например: "cli",
            "plugins", "lsp.server".

    Returns:
        logging.Logger с именем "senpy.<name>".

    Example:
        >>> logger = get_logger("plugins")
        >>> logger.warning("Plugin %s failed", name)
    """
    if not name:
        return logging.getLogger(LOGGER_NAME)
    if name.startswith(LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
