from __future__ import annotations

import io
import pickle
import pickletools
import zlib

# Opcode allowlist: only primitive data types are allowed
SAFE_OPCODES = {
    # Protocols, markers, and stack
    "PROTO",
    "FRAME",
    "STOP",
    "MARK",
    "POP",
    "POP_MARK",
    "DUP",
    # Memoization (references in the object graph)
    "PUT",
    "BINPUT",
    "LONG_BINPUT",
    "MEMOIZE",
    "GET",
    "BINGET",
    "LONG_BINGET",
    # Numbers
    "INT",
    "BININT",
    "BININT1",
    "BININT2",
    "LONG",
    "LONG1",
    "LONG4",
    "FLOAT",
    "BINFLOAT",
    # Strings and bytes
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
    # Constants
    "NONE",
    "NEWTRUE",
    "NEWFALSE",
    # Collections
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
        # Second line of defense: forbid importing any classes, functions, and modules
        raise pickle.UnpicklingError(
            f"Security Error: Forbidden import '{module}.{name}' in untrusted RPA archive"
        )


def safe_load_rpa_index(raw_data: bytes, max_uncompressed_bytes: int = 50 * 1024 * 1024) -> dict:
    """
    Safely unpacks and validates an RPA archive index.
    Protects against RCE (Remote Code Execution), opcode injection, and zip bombs.
    """
    # 1. Decompression bomb protection (limit the uncompressed index size to 50 MB)
    decompressor = zlib.decompressobj()
    decompressed = decompressor.decompress(raw_data, max_length=max_uncompressed_bytes)
    if decompressor.unconsumed_tail:
        raise ValueError("RPA index exceeds safe limit (decompression bomb protection)")

    # 2. First line of defense: static bytecode analysis to ensure no dangerous opcodes
    for opcode, _, _ in pickletools.genops(decompressed):
        if opcode.name not in SAFE_OPCODES:
            raise pickle.UnpicklingError(
                f"Security Error: Malicious pickle opcode '{opcode.name}' detected in RPA archive"
            )

    # 3. Second line of defense: deserialize via an isolated Unpickler
    unpickler = SafeRPAUnpickler(
        io.BytesIO(decompressed), encoding="utf-8", errors="surrogateescape"
    )
    index = unpickler.load()

    if not isinstance(index, dict):
        raise TypeError("Malformed RPA archive: root structure is not a dictionary")

    return index
