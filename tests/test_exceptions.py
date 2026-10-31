"""QUA-11: senpy/core/exceptions.py — domain exception hierarchy.

TDD-контракт для иерархии SenpyError:

  1. `SenpyError` — корень всех доменных исключений. Наследуется от
     `Exception` (не от ValueError/RuntimeError — это осознанный выбор,
     чтобы Senpy-исключения можно было отличить от Python builtin'ов).
  2. Прямые наследники (5 категорий):
     - `ConfigError` — битый TOML, неверная схема, неизвестный rule code.
     - `AnalysisError` — ошибки процесса анализа (родитель).
       - `ParseError` — .rpy/.rpyc парсинг упал.
       - `SymbolResolutionError` — обращение к несуществующему символу.
     - `CacheError` — corrupt pickle, version mismatch.
     - `PluginError` — плагин упал, API mismatch.
       - `ApiVersionMismatchError` — существующий (plugins/security.py),
         должен стать наследником PluginError (а не Exception).
     - `SecurityError` — URI scheme violation, path traversal, unsafe unpickle.
     - `DecompilationError` — unrpyc не смог декомпилировать .rpyc.
  3. Каждое исключение принимает `message: str` + опционально `cause: Exception`
     (для chaining через `__cause__`).
  4. `ApiVersionMismatchError` остаётся в plugins/security.py (backward compat),
     но меняет базовый класс с `Exception` на `PluginError`. Импорт из
     senpy.core.exceptions.

Дизайн-принципы:
  - Исключения НЕ наследуются от ValueError/TypeError. Цель: caller может
    написать `except SenpyError:` и поймать только Senpy-доменные ошибки,
    не случайные ValueError из stdlib.
  - Каждая категория имеет свой `prefix` для логов (например "[CACHE]",
    "[PLUGIN]", "[SEC]") — упрощает grep.
  - Никаких `__str__` кастомных — `Exception.__str__` достаточно, кастомизируем
    только через `__init__` сообщение.
"""
from __future__ import annotations

import pytest

from senpy.core.exceptions import (
    SenpyError,
    ConfigError,
    AnalysisError,
    ParseError,
    SymbolResolutionError,
    CacheError,
    PluginError,
    SecurityError,
    DecompilationError,
)


# =============================================================================
# 1. SenpyError base
# =============================================================================

def test_senpy_error_inherits_from_exception():
    """SenpyError — наследник Exception (НЕ ValueError/RuntimeError)."""
    assert issubclass(SenpyError, Exception)
    # НЕ должен наследоваться от ValueError/TypeError/RuntimeError — это
    # осознанный выбор, чтобы Senpy-исключения можно было отличить от stdlib.
    assert not issubclass(SenpyError, ValueError)
    assert not issubclass(SenpyError, TypeError)
    assert not issubclass(SenpyError, RuntimeError)


def test_senpy_error_accepts_message():
    """SenpyError принимает message как первый аргумент."""
    err = SenpyError("something went wrong")
    assert "something went wrong" in str(err)


def test_senpy_error_accepts_cause():
    """SenpyError принимает опциональный cause для chaining."""
    original = ValueError("original cause")
    err = SenpyError("wrapped", cause=original)
    assert err.__cause__ is original


def test_senpy_error_without_cause():
    """Без cause __cause__ is None (стандартное поведение)."""
    err = SenpyError("just a message")
    assert err.__cause__ is None


# =============================================================================
# 2. Категории — все наследники SenpyError
# =============================================================================

@pytest.mark.parametrize("exc_class", [
    ConfigError,
    AnalysisError,
    CacheError,
    PluginError,
    SecurityError,
    DecompilationError,
])
def test_all_categories_inherit_from_senpy_error(exc_class):
    """Все 6 категорий наследуются от SenpyError."""
    assert issubclass(exc_class, SenpyError)


# =============================================================================
# 3. Подкатегории AnalysisError
# =============================================================================

@pytest.mark.parametrize("exc_class", [
    ParseError,
    SymbolResolutionError,
])
def test_analysis_subcategories_inherit_from_analysis_error(exc_class):
    """ParseError и SymbolResolutionError — наследники AnalysisError."""
    assert issubclass(exc_class, AnalysisError)
    assert issubclass(exc_class, SenpyError)


# =============================================================================
# 4. ApiVersionMismatchError — backward compat
# =============================================================================

def test_api_version_mismatch_is_plugin_error():
    """ApiVersionMismatchError должен быть наследником PluginError.

    Backward compat: раньше наследовался от Exception. После QUA-11 должен
    наследоваться от PluginError (который наследуется от SenpyError).
    Это позволяет ловить его через `except PluginError:` или `except SenpyError:`.
    """
    from senpy.plugins.security import ApiVersionMismatchError
    assert issubclass(ApiVersionMismatchError, PluginError)
    assert issubclass(ApiVersionMismatchError, SenpyError)


def test_api_version_mismatch_still_works():
    """ApiVersionMismatchError сохраняет原有 API (plugin_version, senpy_version)."""
    from senpy.plugins.security import ApiVersionMismatchError
    err = ApiVersionMismatchError("1.5", "1.0")
    assert err.plugin_version == "1.5"
    assert err.senpy_version == "1.0"
    assert "1.5" in str(err)
    assert "1.0" in str(err)


# =============================================================================
# 5. Constructor — все категории принимают message + cause
# =============================================================================

@pytest.mark.parametrize("exc_class", [
    ConfigError,
    AnalysisError,
    ParseError,
    SymbolResolutionError,
    CacheError,
    PluginError,
    SecurityError,
    DecompilationError,
])
def test_all_exceptions_accept_message_and_cause(exc_class):
    """Все доменные исключения принимают message + cause."""
    cause = OSError("disk full")
    err = exc_class("test message", cause=cause)
    assert "test message" in str(err)
    assert err.__cause__ is cause


# =============================================================================
# 6. Catch-by-base — реальный use case
# =============================================================================

def test_can_catch_any_senpy_error_via_base():
    """Любую доменную ошибку можно поймать через `except SenpyError:`."""
    errors = [
        ConfigError("cfg"),
        ParseError("parse"),
        CacheError("cache"),
        PluginError("plugin"),
        SecurityError("sec"),
        DecompilationError("decomp"),
    ]
    for err in errors:
        try:
            raise err
        except SenpyError as caught:
            assert caught is err
        else:
            pytest.fail(f"{type(err).__name__} was not caught by except SenpyError")


def test_senpy_error_does_not_catch_value_error():
    """SenpyError НЕ ловит ValueError из stdlib.

    NB: SecurityError наследуется от ValueError для backward compat,
    но это специально. Чистый ValueError из stdlib не ловится SenpyError.
    """
    with pytest.raises(ValueError):
        try:
            raise ValueError("stdlib error")
        except SenpyError:
            pytest.fail("SenpyError caught ValueError — should not happen")


def test_security_error_is_also_value_error():
    """SecurityError наследуется от ValueError для backward compat.

    Это позволяет старым caller'ам с `except ValueError:` продолжать
    работать после миграции с ValueError на SecurityError.
    """
    assert issubclass(SecurityError, ValueError)
    assert issubclass(SecurityError, SenpyError)

    # Можно поймать через ValueError (старый код)
    with pytest.raises(ValueError):
        raise SecurityError("test")

    # Можно поймать через SenpyError (новый код)
    with pytest.raises(SenpyError):
        raise SecurityError("test")

    # Можно поймать через SecurityError (явно)
    with pytest.raises(SecurityError):
        raise SecurityError("test")


# =============================================================================
# 7. Практический use case — декомпозиция по категориям
# =============================================================================

def test_practical_use_case_plugin_loader():
    """Plugin loader может ловить PluginError отдельно от других SenpyError."""
    from senpy.plugins.security import ApiVersionMismatchError

    def load_plugin():
        raise ApiVersionMismatchError("2.0", "1.0")

    # Plugin loader хочет ловить только plugin-ошибки, остальные пробрасывать
    with pytest.raises(PluginError):
        try:
            load_plugin()
        except PluginError:
            raise  # ловим
        except SenpyError:
            pytest.fail("PluginError should not be caught by general SenpyError first")


def test_practical_use_case_config_loader():
    """Config loader может выбросить ConfigError, caller решает что делать."""
    def load_config():
        raise ConfigError("invalid TOML")

    with pytest.raises(ConfigError) as exc_info:
        load_config()
    assert "invalid TOML" in str(exc_info.value)
