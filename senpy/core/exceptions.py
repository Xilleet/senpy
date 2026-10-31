"""QUA-11: Domain exception hierarchy for Senpy.

Все доменные исключения наследуются от `SenpyError` (НЕ от ValueError/TypeError).
Это позволяет caller'у написать `except SenpyError:` и поймать только Senpy-
доменные ошибки, не случайные ValueError из stdlib.

Иерархия:

    SenpyError (root)
    ├── ConfigError              — битый TOML, неверная схема, unknown rule
    ├── AnalysisError            — ошибки анализа (parent)
    │   ├── ParseError           — .rpy/.rpyc парсинг упал
    │   └── SymbolResolutionError — обращение к несуществующему символу
    ├── CacheError               — corrupt pickle, version mismatch
    ├── PluginError              — плагин упал, API mismatch
    │   └── ApiVersionMismatchError (в plugins/security.py — backward compat)
    ├── SecurityError            — URI scheme violation, path traversal, unsafe pickle
    └── DecompilationError       — unrpyc не смог декомпилировать .rpyc

Дизайн-принципы:
  - Не наследоваться от ValueError/TypeError. Цель: caller ловит
    Senpy-исключения отдельно от stdlib.
  - Каждое исключение принимает (message: str, cause: Exception | None = None).
    Если cause передан — он устанавливается как __cause__ (Python chaining).
  - Никаких кастомных __str__ — Exception.__str__ достаточно.

Usage:
    from senpy.core.exceptions import SenpyError, ConfigError

    try:
        load_config(path)
    except ConfigError as e:
        logger.warning("config load failed: %s", e)
        return {}

    try:
        risky_operation()
    except SenpyError:
        # любая доменная ошибка Senpy
        handle_senpy_failure()
"""
from __future__ import annotations

from typing import Optional

__all__ = [
    "SenpyError",
    "ConfigError",
    "AnalysisError",
    "ParseError",
    "SymbolResolutionError",
    "CacheError",
    "PluginError",
    "SecurityError",
    "DecompilationError",
]


class SenpyError(Exception):
    """Base class for all Senpy domain exceptions.

    All Senpy-specific errors inherit from this. Caller can write
    `except SenpyError:` to catch any Senpy domain error without
    accidentally catching stdlib ValueError/TypeError.

    Args:
        message: Human-readable error description.
        cause: Optional original exception (for chaining via __cause__).
            Use this when wrapping a low-level exception (OSError, pickle.PickleError)
            into a domain exception — preserves traceback for debugging.
    """

    def __init__(self, message: str, *, cause: Optional[BaseException] = None) -> None:
        super().__init__(message)
        if cause is not None:
            self.__cause__ = cause


class ConfigError(SenpyError):
    """Configuration errors: invalid TOML, unknown rule code, bad schema.

    Examples:
        - senpy.toml has invalid TOML syntax.
        - config references unknown rule code (e.g. "RPY999").
        - strict = "yes" instead of strict = true.
    """


class AnalysisError(SenpyError):
    """Errors during the analysis pipeline (parsing, symbol resolution).

    Parent of ParseError and SymbolResolutionError. Catch this if you
    want to handle any analysis-stage failure uniformly.
    """


class ParseError(AnalysisError):
    """Failed to parse a .rpy or .rpyc file.

    Examples:
        - .rpy has Ren'Py syntax error that prevents AST construction.
        - .rpyc is corrupt or from unsupported Ren'Py version.
    """


class SymbolResolutionError(AnalysisError):
    """Reference to a symbol (label/screen/variable) that doesn't exist.

    Examples:
        - `jump undefined_label` — label not in symbol table.
        - `use nonexistent_screen()` — screen not defined.
    """


class CacheError(SenpyError):
    """Cache corruption or version mismatch.

    Examples:
        - .senpy_cache/ pickle file is corrupt (pickle.PickleError).
        - Cache version doesn't match current Senpy version (invalidation).
        - Cache file written by newer Senpy version (forward-incompat).
    """


class PluginError(SenpyError):
    """Plugin loading or execution failure.

    Examples:
        - Plugin's PLUGIN_API_VERSION is incompatible.
        - Plugin's Rule subclass is malformed (missing meta).
        - Plugin raised during analysis.

    ApiVersionMismatchError (in senpy/plugins/security.py) inherits from this.
    """


class SecurityError(SenpyError, ValueError):
    """Security violations: URI scheme, path traversal, unsafe unpickle.

    Examples:
        - LSP _uri_to_path rejected non-file: URI.
        - Workspace containment check failed (path outside workspace root).
        - SafeUnpickler rejected dangerous module.

    Note: inherits from ValueError for backward compat — old callers that
    catch ValueError (e.g. from LSP-19 before QUA-13) continue to work.
    New callers should catch SecurityError explicitly.
    """


class DecompilationError(SenpyError):
    """unrpyc failed to decompile a .rpyc file.

    Examples:
        - .rpyc from unsupported Ren'Py version.
        - .rpyc is encrypted or modified.
        - unrpyc crashed with TypeError on malformed bytecode.
    """
