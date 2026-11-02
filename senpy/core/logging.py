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
    """Remove all existing handlers (for idempotency)."""
    for h in list(logger.handlers):
        logger.removeHandler(h)
        try:  # noqa: SIM105
            h.close()
        except Exception:  # noqa: BLE001 — close() must not fail during cleanup
            pass


def setup_logging(
    verbose: bool = False,
    log_file: str | None = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """Initialize the main Senpy logger.

    Idempotent: repeated calls replace the configuration (they do not duplicate
    handlers). This allows cli/main.py and lsp/server.py to call
    setup_logging independently — the last call wins.

    Args:
        verbose: If True — adds a StreamHandler to stderr.
            False (default) — silence (NullHandler). LSP mode MUST use
            verbose=False.
        log_file: If passed — adds a FileHandler with this path.
            The file is opened in append mode (not overwritten).
        level: Logging level. Default INFO. DEBUG enables extended
            diagnostics.

    Returns:
        The main logger of the project (name "senpy").
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    # propagate=True (default): allows pytest caplog to capture logs,
    # and allows the caller to add its own handler on the root logger
    # (for example via logging.basicConfig()). No duplication occurs
    # because the root has no handlers by default (lastResort = WARNING
    # on stderr only triggers when no one has handlers).
    logger.propagate = True

    # Idempotency: clear old handlers before installing new ones.
    _clear_handlers(logger)

    # NullHandler is always added — this guarantees that even without
    # verbose/log_file the logger.* calls do not fail with "No handlers could be found".
    logger.addHandler(logging.NullHandler())

    formatter = logging.Formatter(_DEFAULT_FORMAT, datefmt=_DEFAULT_DATEFMT)

    if verbose:
        sh = logging.StreamHandler(stream=sys.stderr)
        sh.setFormatter(formatter)
        sh.setLevel(level)
        logger.addHandler(sh)

    if log_file:
        # append mode, UTF-8 — for cross-platform support (Windows cp1251
        # by default breaks Russian messages).
        fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        fh.setFormatter(formatter)
        fh.setLevel(level)
        logger.addHandler(fh)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Returns a child logger with the name "senpy.<name>".

    For submodules (cli, lsp, plugins, core, ...). The child logger:
      - Has no handlers of its own (everything goes through the "senpy" root).
      - propagate=True (the default for child loggers in Python).
      - The level is inherited from the parent.

    Args:
        name: Name of the submodule (without the "senpy." prefix). For example:
            "cli", "plugins", "lsp.server".

    Returns:
        logging.Logger with the name "senpy.<name>".

    Example:
        >>> logger = get_logger("plugins")
        >>> logger.warning("Plugin %s failed", name)
    """
    if not name:
        return logging.getLogger(LOGGER_NAME)
    if name.startswith(LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
