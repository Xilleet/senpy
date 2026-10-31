"""QUA-12: contextlib.suppress → try/except + logger.debug.

Контракт:
  - После миграции suppress(...), когда подавленное исключение срабатывает,
    в лог пишется DEBUG-сообщение с типом исключения и сообщением.
  - Сам suppress остаётся (caller не видит исключение) — это backward compat.
  - Логирование через модульный logger (senpy.cache, senpy.cli.unrpyc, etc).

Тесты проверяют ключевые сценарии:
  1. core/cache.py — corrupt pickle → CacheError не поднимается, пишется debug.
  2. core/signature.py — SyntaxError в $-выражении → debug логируется.
  3. rules/python_ast.py — SyntaxError в infer_ast_type → debug логируется.
"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from senpy.core.logging import setup_logging


@pytest.fixture(autouse=True)
def reset_logging():
    # Включаем DEBUG уровень на корневом senpy логгере — иначе caplog не поймает
    # debug-сообщения (setup_logging по умолчанию ставит INFO).
    setup_logging(level=logging.DEBUG)
    yield


# =============================================================================
# 1. core/cache.py — corrupt cache file
# =============================================================================

def test_cache_corrupt_pickle_logs_debug(tmp_path: Path, caplog):
    """CacheManager.load_manifest() при corrupt pickle пишет DEBUG, не падает."""
    from senpy.core.cache import CacheManager

    # CacheManager хранит manifest в <project>/.senpy_cache/cache.pkl
    cache_dir = tmp_path / ".senpy_cache"
    cache_dir.mkdir()
    manifest_file = cache_dir / "cache.pkl"  # именно cache.pkl, не manifest.pkl
    manifest_file.write_bytes(b"not a valid pickle stream")

    cm = CacheManager(project_path=str(tmp_path))

    with caplog.at_level(logging.DEBUG, logger="senpy.cache"):
        # Должно вернуть None — fallback, не падать
        result = cm.load_manifest()

    # Не упало — уже хорошо. Проверим что лог есть.
    assert result is None or result is False

    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any(
        "manifest" in r.message.lower() or "pickle" in r.message.lower()
        or "cache" in r.message.lower()
        for r in debug_records
    ), f"no debug log for cache corruption: {debug_records}"


# =============================================================================
# 2. core/signature.py — SyntaxError в Python AST
# =============================================================================

def test_signature_syntax_error_logs_debug(caplog):
    """parse_signature при SyntaxError пишет DEBUG, возвращает empty SignatureInfo."""
    from senpy.core.signature import parse_signature

    # Передаём Python-код с синтаксической ошибкой
    bad_code = "def f(:"  # syntax error

    with caplog.at_level(logging.DEBUG, logger="senpy.signature"):
        result = parse_signature(bad_code)

    # Должен вернуть fallback SignatureInfo (с has_params=True но
    # max_args=inf, has_varargs=True —宽松ный fallback).
    # Главное — debug лог должен быть.
    assert result is not None  # fallback SignatureInfo возвращается

    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any(
        "syntax" in r.message.lower() or "signature" in r.message.lower()
        or "parse" in r.message.lower()
        for r in debug_records
    ), f"no debug log for signature SyntaxError: {debug_records}"


# =============================================================================
# 3. rules/python_ast.py — SyntaxError в infer_ast_type
# =============================================================================

def test_python_ast_syntax_error_logs_debug(caplog):
    """extract_assigned_names при SyntaxError пишет DEBUG, возвращает empty set."""
    from senpy.rules.python_ast import extract_assigned_names

    # Python-код с синтаксической ошибкой
    bad_code = "x = :"

    with caplog.at_level(logging.DEBUG, logger="senpy.rules.python_ast"):
        result = extract_assigned_names(bad_code)

    # Должно вернуть пустое множество (fallback)
    assert result == set()

    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any(
        "syntax" in r.message.lower() or "ast" in r.message.lower()
        or "parse" in r.message.lower()
        for r in debug_records
    ), f"no debug log for python_ast SyntaxError: {debug_records}"


# =============================================================================
# 4. formats/traceback.py — OSError при чтении traceback.txt
# =============================================================================

def test_traceback_read_oserror_logs_debug(tmp_path: Path, caplog, monkeypatch):
    """parse_traceback_file при OSError (файл это директория) пишет DEBUG."""
    from senpy.formats import traceback as traceback_mod

    # Передаём директорию вместо файла — os.path.isfile вернёт False,
    # но если передать существующий путь который является директорией,
    # open() поднимет IsADirectoryError (subclass of OSError).
    # Лучше: передаём путь который isfile() = True но read упадёт.
    # Альтернатива: передаём несуществующий файл, получаем early return None.
    # Для теста QUA-12 нужен случай когда open() падает — используем mock.
    fake_path = tmp_path / "fake_traceback.txt"

    # Делаем вид что файл существует (isfile=True), но open() падает
    with patch("os.path.isfile", return_value=True):
        with patch("builtins.open", side_effect=OSError("mocked: permission denied")):
            with caplog.at_level(logging.DEBUG, logger="senpy.traceback"):
                result = traceback_mod.parse_traceback_file(str(fake_path))

    assert result is None

    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any(
        "traceback" in r.message.lower() or "read" in r.message.lower()
        or "file" in r.message.lower()
        for r in debug_records
    ), f"no debug log for traceback OSError: {debug_records}"


# =============================================================================
# 5. Sanity check — suppress не должен остаться в ключевых модулях
# =============================================================================

def test_no_contextlib_suppress_in_core_cache():
    """После миграции в core/cache.py не должно остаться contextlib.suppress."""
    import senpy.core.cache as cache_mod
    import inspect
    source = inspect.getsource(cache_mod)
    # Допускаем suppress только в комментариях/docstring, не в коде.
    # Простая проверка: считаем строки с `with contextlib.suppress(` (код, не текст).
    code_lines = [
        line for line in source.splitlines()
        if "contextlib.suppress(" in line and not line.strip().startswith("#")
        and not line.strip().startswith('"') and not line.strip().startswith("'")
    ]
    assert code_lines == [], f"contextlib.suppress still in core/cache.py: {code_lines}"


def test_no_contextlib_suppress_in_core_signature():
    """После миграции в core/signature.py не должно остаться contextlib.suppress."""
    import senpy.core.signature as sig_mod
    import inspect
    source = inspect.getsource(sig_mod)
    code_lines = [
        line for line in source.splitlines()
        if "contextlib.suppress(" in line and not line.strip().startswith("#")
        and not line.strip().startswith('"') and not line.strip().startswith("'")
    ]
    assert code_lines == [], f"contextlib.suppress still in core/signature.py: {code_lines}"
