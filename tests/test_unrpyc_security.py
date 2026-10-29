"""Security-тест для AUD-001: harden __import__ usage в vendored unrpyc.

Текущее состояние (после сверки с кодом):
- `decompile_rpyc` и `decompile_rpyc_bytes` используют `SafeUnpickler` через
  `pickle_safe_loads` → ✅ Безопасно: только модули из `safe_modules={"collections"}`
  проходят `__import__`, остальное → `FakeClass`.
- НО в коде осталось 5 уязвимых `__import__` вызовов в `magic.py`:
    * `FakeUnpickler.find_class` (строка 485)
    * `SafeUnpickler.find_class` для safe_modules (строка 541)
    * `FakeModule.__init__` (строка 314)
    * `FakePackage.__getattr__` (строка 394)
    * `fake_package()` функция (строка 688)

Это defense-in-depth риск: если кто-то случайно добавит опасный модуль в
`safe_modules`, или поменяет `pickle_safe_loads` на `pickle_loads` (который
использует `FakeUnpickler`) — `__import__('os')` активируется → RCE.

Контракт после hardening:
- `SafeUnpickler.find_class` для safe_modules — проверяет whitelist (никаких os/subprocess/socket)
- `FakeUnpickler.find_class` — defensive: только renpy.* + стандартные safe modules
- `FakeModule.__init__` / `FakePackage.__getattr__` — то же
- `fake_package()` — то же

Источник: AUD-001 (аудит v0.5.7), сверено с кодом 2026-10-30.
"""
from __future__ import annotations

import os
import struct
import sys
import builtins
import tempfile
import zlib
from pathlib import Path
from io import BytesIO


# Список dangerous модулей, которые Senpy НЕ должен импортировать при
# декомпиляции недоверенного .rpyc (даже если они случайно оказались в safe_modules).
DANGEROUS_MODULES = ("os", "subprocess", "socket", "shutil", "pathlib", "sys")


def _make_malicious_rpyc_bytes(module_name: str = "os", attr_name: str = "system") -> bytes:
    """Создаёт .rpyc, pickle которого ссылается на module_name.attr_name через GLOBAL opcode."""
    global_opcode = b"c" + module_name.encode() + b"\n" + attr_name.encode() + b"\n"
    malicious_pickle = b"\x80\x02" + global_opcode + b"."
    slot1_data = zlib.compress(malicious_pickle)
    slot1_pos = 34  # 10 (header) + 12 (slot1 header) + 12 (slot0 header)
    slot1_header = struct.pack("<III", 1, slot1_pos, len(slot1_data))
    slot0_header = struct.pack("<III", 0, 0, 0)
    return b"RENPY RPC2" + slot1_header + slot0_header + slot1_data


# =============================================================================
# 1. SAFE PATH (основной сценарий) — decompile_rpyc_bytes использует SafeUnpickler
# =============================================================================

def test_decompile_rpyc_bytes_does_not_import_os():
    """Декомпиляция .rpyc, ссылающегося на os.system, НЕ должна вызывать __import__('os').

    Senpy использует `SafeUnpickler` через `pickle_safe_loads` с safe_modules={"collections"}.
    Модуль 'os' не в safe_modules → SafeUnpickler возвращает FakeClass без __import__.
    """
    from senpy.vendor.unrpyc import decompile_rpyc_bytes

    rpyc_bytes = _make_malicious_rpyc_bytes("os", "system")

    real_import = builtins.__import__
    dangerous_imports_made = []

    def _tracking_import(name, *args, **kwargs):
        top_level = name.split(".")[0]
        if top_level in DANGEROUS_MODULES:
            dangerous_imports_made.append(name)
        return real_import(name, *args, **kwargs)

    builtins.__import__ = _tracking_import
    try:
        try:
            decompile_rpyc_bytes(rpyc_bytes)
        except Exception:
            pass  # malformed .rpyc может упасть — это ОК
    finally:
        builtins.__import__ = real_import

    assert dangerous_imports_made == [], (
        f"Декомпиляция вызвала __import__ для dangerous модулей: "
        f"{dangerous_imports_made}. SafeUnpickler должен возвращать FakeClass "
        f"без вызова __import__."
    )


def test_decompile_rpyc_bytes_does_not_execute_arbitrary_code(tmp_path: Path):
    """Defense-in-depth: подложенный .rpyc + подложенный evil_module.py рядом
    НЕ должны привести к выполнению кода из evil_module.py.

    Сценарий:
    1. Злоумышленник даёт жертве .rpyc, pickle которого ссылается на `evil_module.X`
    2. Злоумышленник кладёт `evil_module.py` рядом с .rpyc (или в cwd Senpy)
    3. При декомпиляции `SafeUnpickler.find_class('evil_module', 'X')` НЕ должен
       вызывать `__import__('evil_module')` (evil_module не в safe_modules) →
       возвращается FakeClass.
    """
    from senpy.vendor.unrpyc import decompile_rpyc_bytes

    # Создаём временную директорию с evil_module.py
    marker_file = tmp_path / "RCE_MARKER"
    evil_module_path = tmp_path / "evil_module.py"
    evil_module_path.write_text(
        f"import os; open({str(marker_file)!r}, 'w').write('PWNED')\n"
    )

    # Добавляем tmp_path в sys.path, чтобы __import__ нашёл evil_module
    sys.path.insert(0, str(tmp_path))
    sys.modules.pop("evil_module", None)
    assert not marker_file.exists()

    try:
        rpyc_bytes = _make_malicious_rpyc_bytes("evil_module", "hack_function")
        try:
            decompile_rpyc_bytes(rpyc_bytes)
        except Exception:
            pass  # декомпиляция может упасть — это ОК

        assert not marker_file.exists(), (
            "RCE CONFIRMED: декомпиляция .rpyc привела к выполнению evil_module.py. "
            "SafeUnpickler должен возвращать FakeClass без __import__."
        )
    finally:
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
        sys.modules.pop("evil_module", None)


# =============================================================================
# 2. DEFENSE-IN-DEPTH: SafeUnpickler.find_class с опасным safe_modules
# =============================================================================

def test_safe_unpickler_rejects_dangerous_modules_in_safe_modules():
    """Defense-in-depth: даже если кто-то случайно добавил 'os' в safe_modules,
    SafeUnpickler.find_class НЕ должен импортировать dangerous модули.

    Уязвимый путь: SafeUnpickler.find_class('os', 'system'):
        if module in self.safe_modules:
            __import__(module)  # ← БЕЗ whitelist проверки!
            ...

    После hardening: SafeUnpickler.find_class должен проверять, что модуль
    не в DANGEROUS_MODULES, даже если он оказался в safe_modules.
    """
    from senpy.vendor.unrpyc.decompiler import magic

    malicious_pickle = b"\x80\x02cos\nsystem\n."
    CLASS_FACTORY = magic.FakeClassFactory({}, magic.FakeStrict)

    # Кто-то случайно добавил 'os' в safe_modules
    unpickler = magic.SafeUnpickler(
        BytesIO(malicious_pickle),
        CLASS_FACTORY,
        safe_modules={"collections", "os"},  # ← 'os' не должно быть здесь
        use_copyreg=False,
        encoding="ASCII",
        errors="strict",
    )

    real_import = builtins.__import__
    dangerous_imports_made = []

    def _tracking_import(name, *args, **kwargs):
        top_level = name.split(".")[0]
        if top_level in DANGEROUS_MODULES:
            dangerous_imports_made.append(name)
        return real_import(name, *args, **kwargs)

    builtins.__import__ = _tracking_import
    try:
        try:
            unpickler.load()
        except Exception:
            pass
    finally:
        builtins.__import__ = real_import

    assert dangerous_imports_made == [], (
        f"SafeUnpickler с 'os' в safe_modules вызвал __import__('os') — "
        f"это RCE-вектор. Defense-in-depth: даже если 'os' оказался в "
        f"safe_modules по ошибке, hardening должен его отклонить. "
        f"Imports made: {dangerous_imports_made}"
    )


# =============================================================================
# 3. LEGITIMATE DECOMPILE — regression test
# =============================================================================

def test_legitimate_rpyc_still_decompiles():
    """Regression: после hardening, валидные .rpyc продолжают декомпилироваться.

    Ren'Py .rpyc с pickle, который ссылается на renpy.store и collections —
    это стандартный use case. Hardening НЕ должен сломать его.
    """
    from senpy.vendor.unrpyc import decompile_rpyc_bytes

    # Минимальный валидный .rpyc: пустой AST tuple ({}, [])
    import pickle
    payload = pickle.dumps(({}, []), protocol=2)
    slot1_data = zlib.compress(payload)
    slot1_pos = 34
    slot1_header = struct.pack("<III", 1, slot1_pos, len(slot1_data))
    slot0_header = struct.pack("<III", 0, 0, 0)
    rpyc_bytes = b"RENPY RPC2" + slot1_header + slot0_header + slot1_data

    result = decompile_rpyc_bytes(rpyc_bytes)
    assert isinstance(result, str), (
        f"После hardening валидный .rpyc должен декомпилироваться в str. "
        f"Получено: {type(result)}"
    )


# =============================================================================
# 4. SAFE_MODULES WHITELIST — collections и renpy.* продолжают работать
# =============================================================================

def test_safe_modules_collections_still_imports():
    """Regression: collections (легитимный safe_module) должен импортироваться
    как раньше — hardening не должен блокировать легитимные safe_modules.
    """
    from senpy.vendor.unrpyc.decompiler import magic

    # Pickle, ссылающийся на collections.OrderedDict
    import pickle
    payload = pickle.dumps(("collections", "OrderedDict"), protocol=2)
    malicious_pickle = b"\x80\x02ccollections\nOrderedDict\n."

    CLASS_FACTORY = magic.FakeClassFactory({}, magic.FakeStrict)
    unpickler = magic.SafeUnpickler(
        BytesIO(malicious_pickle),
        CLASS_FACTORY,
        safe_modules={"collections"},  # легитимный safe_module
        use_copyreg=False,
        encoding="ASCII",
        errors="strict",
    )

    # Должен вернуть collections.OrderedDict (реальный класс, не FakeClass)
    real_import = builtins.__import__
    collections_imports = []

    def _track(name, *args, **kwargs):
        if name == "collections":
            collections_imports.append(name)
        return real_import(name, *args, **kwargs)

    builtins.__import__ = _track
    try:
        result = unpickler.load()
    finally:
        builtins.__import__ = real_import

    assert "collections" in collections_imports, (
        "Hardening не должен блокировать легитимный safe_module 'collections'. "
        " collections должен импортироваться через __import__ как раньше."
    )
