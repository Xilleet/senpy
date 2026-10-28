"""Senpy vendor: unrpyc — встроенный декомпилятор .rpyc.

Вместо скачивания unrpyc при первом запуске (--decompile), мы встраиваем
код напрямую. Это устраняет внешнюю зависимость и позволяет вызывать
декомпиляцию через прямой import, а не subprocess.

Лицензия: MIT (Yuri K. Schlesner, CensoredUsername, Jackmcbarn)
См. LICENSE файл в этой папке.

Public API:
    decompile_rpyc(rpyc_path) -> str  — декомпилировать .rpyc → .rpy текст
"""
from __future__ import annotations

import logging
import os
import struct
import zlib
from io import StringIO

# КРИТИЧЕСКИ ВАЖНО: renpycompat должен быть импортирован ПЕРВЫМ.
# Он создаёт фейковый `renpy` модуль через magic.fake_package("renpy"),
# который нужен для импорта остальных модулей декомпилятора.
from senpy.vendor.unrpyc.decompiler import (
    Options,
    pprint,
    renpycompat,  # noqa: F401
)
from senpy.vendor.unrpyc.decompiler.renpycompat import CLASS_FACTORY, pickle_safe_loads

logger = logging.getLogger(__name__)


class RPYCDecompilationError(Exception):
    """Ошибка декомпиляции .rpyc файла."""


def _decompile_ast(ast: object) -> str:
    """Рендерит AST в .rpy текст. Внутренняя функция."""
    out = StringIO()
    options = Options()
    pprint(out, ast, options)
    return out.getvalue()


class BadRpycException(Exception):  # noqa: N818
    """.rpyc файл имеет неизвестный или повреждённый формат."""


def _read_ast_from_file(f, filename: str = "") -> list:
    """Читает AST из .rpyc файла (формат RENPY RPC2 v2 или v1).

    v2: заголовок b"RENPY RPC2" + слоты (slot, start, length)
    v1: просто zlib-сжатый pickle (без заголовка)

    Возвращает только stmts (AST), как оригинальный unrpyc.
    (Адаптировано из unrpyc.py:read_ast_from_file)
    """
    import struct

    raw_contents = f.read()
    file_start = raw_contents[:50]

    if not raw_contents.startswith(b"RENPY RPC2"):
        # v1: просто zlib-сжатый pickle (старые .rpyc Ren'Py 6.x)
        contents = raw_contents
    else:
        # v2: парсим слоты (slot, start, length) — каждый 12 байт
        position = 10  # после "RENPY RPC2"
        chunks = {}

        for expected_slot in range(1, 0xFFFFFFFF):
            if position + 12 > len(raw_contents):
                break
            slot, start, length = struct.unpack("III", raw_contents[position: position + 12])
            if slot == 0:
                break
            position += 12
            if start + length <= len(raw_contents):
                chunks[slot] = raw_contents[start: start + length]

        if 1 not in chunks:
            raise BadRpycException(
                f"Unable to find the right slot in {filename}. "
                f"File header: {file_start}"
            )
        contents = chunks[1]

    # Распаковка zlib
    try:
        contents = zlib.decompress(contents)
    except Exception as e:
        raise BadRpycException(
            f"Did not find a zlib compressed blob in {filename}: {e}"
        ) from e

    # Десериализация pickle → (data, stmts)
    _, stmts = pickle_safe_loads(contents)
    return stmts


def decompile_rpyc(rpyc_path: str) -> str:
    """Декомпилирует .rpyc файл → .rpy текст (в памяти, без записи на диск).

    Args:
        rpyc_path: путь к .rpyc файлу

    Returns:
        .rpy текст как строка

    Raises:
        RPYCDecompilationError: если .rpyc не поддерживается или повреждён
        OSError: если файл не найден или не читается
    """
    filename = os.path.basename(rpyc_path)

    # Этап 1: Чтение файла и извлечение AST из slot 1
    try:
        with open(rpyc_path, "rb") as f:
            ast = _read_ast_from_file(f, filename)
    except BadRpycException as e:
        raise RPYCDecompilationError(f"Cannot read .rpyc {filename}: {e}") from e
    except OSError as e:
        raise OSError(f"Cannot read {filename}: {e}") from e

    # Этап 2: Рендеринг AST → .rpy текст
    try:
        return _decompile_ast(ast)
    except Exception as e:
        raise RPYCDecompilationError(
            f"Failed to render .rpy from {filename}: {e}. "
            f"This may be an unsupported AST node type or edge case."
        ) from e


def decompile_rpyc_bytes(rpyc_data: bytes) -> str:
    """Декомпилирует .rpyc из bytes (например, из .rpa архива) → .rpy текст.

    Args:
        rpyc_data: сырые байты .rpyc файла

    Returns:
        .rpy текст как строка

    Raises:
        RPYCDecompilationError: если .rpyc не поддерживается или повреждён
    """
    from io import BytesIO

    # Этап 1: Чтение AST из .rpyc bytes (парсинг слотов)
    try:
        f = BytesIO(rpyc_data)
        ast = _read_ast_from_file(f)
    except BadRpycException as e:
        raise RPYCDecompilationError(f"Cannot read .rpyc data: {e}") from e

    # Этап 2: Рендеринг AST → .rpy текст
    try:
        return _decompile_ast(ast)
    except Exception as e:
        raise RPYCDecompilationError(
            f"Failed to render .rpy: {e}. "
            f"This may be an unsupported AST node type or edge case."
        ) from e


__all__ = ["decompile_rpyc", "decompile_rpyc_bytes", "RPYCDecompilationError"]
