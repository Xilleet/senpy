from __future__ import annotations

import io
import pickle
import pickletools
import zlib

# Белый список опкодов: разрешены только примитивные типы данных
SAFE_OPCODES = {
    # Протоколы, маркеры и стек
    "PROTO",
    "FRAME",
    "STOP",
    "MARK",
    "POP",
    "POP_MARK",
    "DUP",
    # Мемоизация (ссылки в графе объектов)
    "PUT",
    "BINPUT",
    "LONG_BINPUT",
    "MEMOIZE",
    "GET",
    "BINGET",
    "LONG_BINGET",
    # Числа
    "INT",
    "BININT",
    "BININT1",
    "BININT2",
    "LONG",
    "LONG1",
    "LONG4",
    "FLOAT",
    "BINFLOAT",
    # Строки и байты
    "STRING",
    "BINSTRING",
    "SHORT_BINSTRING",
    "UNICODE",
    "BINUNICODE",
    "SHORT_BINUNICODE",
    "BINUNICODE8",
    "BINBYTES",
    "SHORT_BINBYTES",
    "BINBYTES8",
    "BYTEARRAY8",
    # Константы
    "NONE",
    "NEWTRUE",
    "NEWFALSE",
    # Коллекции
    "EMPTY_TUPLE",
    "TUPLE",
    "TUPLE1",
    "TUPLE2",
    "TUPLE3",
    "EMPTY_LIST",
    "LIST",
    "APPEND",
    "APPENDS",
    "EMPTY_DICT",
    "DICT",
    "SETITEM",
    "SETITEMS",
}


class SafeRPAUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        # Второй рубеж обороны: запрещаем импорт любых классов, функций и модулей
        raise pickle.UnpicklingError(
            f"Security Error: Forbidden import '{module}.{name}' in untrusted RPA archive"
        )


def safe_load_rpa_index(raw_data: bytes, max_uncompressed_bytes: int = 50 * 1024 * 1024) -> dict:
    """
    Безопасно распаковывает и валидирует индекс RPA-архива.
    Защищает от RCE (Remote Code Execution), инъекций опкодов и Zip-бомб.
    """
    # 1. Защита от Decompression Bomb (ограничение размера распакованного индекса до 50 МБ)
    decompressor = zlib.decompressobj()
    decompressed = decompressor.decompress(raw_data, max_length=max_uncompressed_bytes)
    if decompressor.unconsumed_tail:
        raise ValueError("RPA index exceeds safe limit (decompression bomb protection)")

    # 2. Первый рубеж: статический анализ байткода на отсутствие опасных опкодов
    for opcode, _, _ in pickletools.genops(decompressed):
        if opcode.name not in SAFE_OPCODES:
            raise pickle.UnpicklingError(
                f"Security Error: Malicious pickle opcode '{opcode.name}' detected in RPA archive"
            )

    # 3. Второй рубеж: десериализация через изолированный Unpickler
    unpickler = SafeRPAUnpickler(
        io.BytesIO(decompressed), encoding="utf-8", errors="surrogateescape"
    )
    index = unpickler.load()

    if not isinstance(index, dict):
        raise TypeError("Malformed RPA archive: root structure is not a dictionary")

    return index
