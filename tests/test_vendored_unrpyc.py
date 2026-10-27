"""Тесты для ECO-5: vendored unrpyc — встроенный декомпилятор.

Проверяет, что:
1. Импорт decompile_rpyc работает
2. decompile_rpyc_bytes работает на простых данных
3. decompile_to_sandbox интегрирована с vendored unrpyc
"""
from __future__ import annotations

import zlib
from pathlib import Path
from unittest.mock import MagicMock

from senpy._unrpyc_bootstrap import decompile_to_sandbox


def test_vendored_unrpyc_import():
    """Импорт decompile_rpyc из vendored unrpyc работает."""
    from senpy.vendor.unrpyc import decompile_rpyc

    assert callable(decompile_rpyc), "decompile_rpyc должна быть callable"


def test_vendored_unrpyc_decompile_rpyc_bytes():
    """decompile_rpyc_bytes принимает bytes и возвращает str."""
    from senpy.vendor.unrpyc import decompile_rpyc_bytes

    # Создадим минимальный правильный .rpyc v2 файл
    # Формат: b"RENPY RPC2" + slot 1 (slot=1, start, length) + slot 0 (terminator)
    # slot 1 = zlib pickle пустого AST []
    import pickle
    import struct

    slot1_data = zlib.compress(pickle.dumps(({}, [])))
    # Позиция slot 1 данных: 10 (header) + 12 (slot 1 header) + 12 (slot 0 terminator) = 34
    slot1_pos = 34
    slot1_header = struct.pack("III", 1, slot1_pos, len(slot1_data))  # slot=1, start, length
    slot0_header = struct.pack("III", 0, 0, 0)  # terminator (slot=0)
    rpyc_bytes = b"RENPY RPC2" + slot1_header + slot0_header + slot1_data

    # Должна вернуть строку (даже пустую для пустого AST)
    result = decompile_rpyc_bytes(rpyc_bytes)
    assert isinstance(result, str), f"Ожидалась str, получено {type(result)}"


def test_decompile_to_sandbox_uses_vendored(tmp_path: Path):
    """decompile_to_sandbox использует vendored unrpyc (без subprocess)."""
    # Создадим минимальный правильный .rpyc v2 файл
    import pickle
    import struct

    slot1_data = zlib.compress(pickle.dumps(({}, [])))
    slot1_pos = 34
    slot1_header = struct.pack("III", 1, slot1_pos, len(slot1_data))
    slot0_header = struct.pack("III", 0, 0, 0)
    rpyc_bytes = b"RENPY RPC2" + slot1_header + slot0_header + slot1_data

    rpyc_file = tmp_path / "test.rpyc"
    rpyc_file.write_bytes(rpyc_bytes)

    # Вызываем decompile_to_sandbox
    result = decompile_to_sandbox(
        orphans=[str(rpyc_file)],
        unrpyc_cmd=None,  # ECO-5: параметр игнорируется
        temp_dir=str(tmp_path),
    )

    # Должен создать .rpy файл
    assert len(result) >= 1, f"Ожидался хотя бы 1 файл, получено {result}"
    rpy_path = result[0]
    assert rpy_path.endswith(".rpy"), f"Ожидался .rpy, получено {rpy_path}"

    # Файл должен существовать
    rpy_file = Path(rpy_path)
    assert rpy_file.exists(), f"Файл {rpy_path} не создан"

    # Содержимое должно быть строкой (возможно пустой для пустого AST)
    content = rpy_file.read_text(encoding="utf-8")
    assert isinstance(content, str)


def test_decompile_to_sandbox_no_subprocess(tmp_path: Path):
    """decompile_to_sandbox НЕ использует subprocess (ECO-5)."""
    import pickle
    from unittest.mock import patch

    fake_ast = []
    fake_data = pickle.dumps(fake_ast)
    compressed = zlib.compress(fake_data)

    rpyc_file = tmp_path / "test.rpyc"
    rpyc_file.write_bytes(compressed)

    # Перехватываем subprocess.Popen — не должен вызываться
    with patch("subprocess.Popen") as mock_popen:
        decompile_to_sandbox(
            orphans=[str(rpyc_file)],
            unrpyc_cmd=None,
            temp_dir=str(tmp_path),
        )
        assert not mock_popen.called, "subprocess.Popen не должен вызываться (ECO-5 vendored)"
