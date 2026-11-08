"""Domain exception hierarchy for Senpy.

All domain exceptions inherit from `SenpyError` (NOT from ValueError/TypeError).
This lets a caller write `except SenpyError:` and catch only Senpy domain errors,
not accidental ValueError from stdlib.

Hierarchy:

    SenpyError (root)
    ├── ConfigError              — broken TOML, invalid schema, unknown rule
    ├── AnalysisError            — analysis errors (parent)
    │   ├── ParseError           — .rpy/.rpyc parsing failed
    │   └── SymbolResolutionError — reference to a non-existent symbol
    ├── CacheError               — corrupt pickle, version mismatch
    ├── PluginError              — plugin crashed, API mismatch
    │   └── ApiVersionMismatchError (in plugins/security.py — backward compat)
    ├── SecurityError            — URI scheme violation, path traversal, unsafe pickle
    └── DecompilationError       — unrpyc failed to decompile .rpyc

Design principles:
  - Do not inherit from ValueError/TypeError. Goal: the caller catches Senpy
    exceptions separately from stdlib.
  - Each exception accepts (message: str, cause: Exception | None = None).
    If cause is passed — it is set as __cause__ (Python chaining).
  - No custom __str__ — Exception.__str__ is enough.

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
        # any Senpy domain error
        handle_senpy_failure()
"""

from __future__ import annotations

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

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:  # noqa: UP045
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
    catch ValueError (e.g. from before) continue to work.
    New callers should catch SecurityError explicitly.

    The ValueError inheritance is deprecated and will be removed in 1.0.
    It violates the design principle stated at the top of this file
    ("Do not inherit from ValueError/TypeError"). A grep of the codebase
    shows no production callers catch ValueError to reach SecurityError —
    the inheritance is vestigial. Kept for now to avoid breaking external
    callers, but a DeprecationWarning is emitted on instantiation.
    """

    def __init__(self, *args, **kwargs):
        import warnings

        warnings.warn(
            "SecurityError inherits from ValueError for backward compat, "
            "but this will be removed in 1.0. Catch SecurityError explicitly.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(*args, **kwargs)


class DecompilationError(SenpyError):
    """unrpyc failed to decompile a .rpyc file.

    Examples:
        - .rpyc from unsupported Ren'Py version.
        - .rpyc is encrypted or modified.
        - unrpyc crashed with TypeError on malformed bytecode.
    """
