"""Unrpyc bootstrap: скачивание, поиск, декомпиляция .rpyc, извлечение .rpa.

Вынесено из cli.py (P1-1: Вариант B — умеренный рефакторинг).
Этот модуль полностью независим от cli.py и использует только стандартные
библиотеки + senpy.constants + senpy.rpa + senpy.tsundere.
"""
from __future__ import annotations

import hashlib
import os
import pickle
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
import zlib

from rich.console import Console

from senpy.core.logging import get_logger
from senpy.domain.rpa import safe_load_rpa_index
from senpy.domain.tsundere import IS_RU

_logger = get_logger("cli.unrpyc")

# Console для unrpyc-блока (не зависит от глобального console из cli.py)
console = Console(legacy_windows=sys.stdout.isatty())

SENPY_CACHE_DIR = os.path.expanduser("~/.senpy/tools/unrpyc")
# ECO-4: ранее UNRPYC_GITHUB_ZIP указывал на master-ветку, что означало
# "всегда качать свежий код". Это риск: master может измениться в любой момент,
# возможны breaking changes или (hypothetically) инъекции вредоносного кода,
# если аккаунт CensoredUsername скомпрометируют.
#
# Теперь мы пинним к конкретному коммиту (UNRPYC_PINNED_COMMIT) и проверяем
# SHA256 скачанного zip (UNRPYC_PINNED_SHA256). Это defence-in-depth:
# даже если GitHub будет скомпрометирован или TLS-перехват подменит zip,
# мы отвергнем несовпадающий файл.
#
# Обновление pinned commit:
#   python scripts/update_unrpyc_pin.py
# (скрипт получит свежий SHA master-ветки, посчитает SHA256 zip'а и
# обновит обе константы).
#
# Текущий pinned commit:
UNRPYC_PINNED_COMMIT = "v2.0.4"
UNRPYC_PINNED_SHA256 = "df7446d89f68a9a94a62378248da875e9e75e983bf81de53d92b2c19f359673e"  # вычислен 2026-10-28 через update_unrpyc_pin.py
UNRPYC_GITHUB_ZIP_TEMPLATE = "https://github.com/CensoredUsername/unrpyc/archive/{commit}.zip"


def _unrpyc_zip_url() -> str:
    """URL для скачивания pinned версии unrpyc."""
    return UNRPYC_GITHUB_ZIP_TEMPLATE.format(commit=UNRPYC_PINNED_COMMIT)

# Фаза 1.2 (0.5.3): load_config вынесен в senpy/config.py для разрыва
# циклической зависимости analyzer ↔ cli. Реэкспортируем для обратной
# совместимости (старый импорт `from senpy.cli.unrpyc import load_config`
# продолжает работать).
from senpy.core.config import load_config  # noqa: E402, F401, I001

def find_in_directory_tree(start_dirs: list[str]) -> str | None:
    for base in start_dirs:
        if not base or not os.path.exists(base):
            continue
        candidates = [
            os.path.join(base, "unrpyc.py"),
            os.path.join(base, "unrpyc", "unrpyc.py"),
            os.path.join(base, "tools", "unrpyc.py"),
            os.path.join(os.path.dirname(base), "unrpyc.py"),
            os.path.join(os.path.dirname(base), "tools", "unrpyc.py"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
    return None


def _verify_unrpyc_sha256(zip_path: str) -> bool:
    """ECO-4: проверяет SHA256 скачанного zip против pinned значения.

    Возвращает True, если совпадает (или если UNRPYC_PINNED_SHA256 is None —
    для backward compat при обновлении с placeholder).
    """
    if UNRPYC_PINNED_SHA256 is None:
        # Pinned SHA не задан (placeholder) — пропускаем проверку с предупреждением.
        # Это interim-состояние, пока мейнтейнер не запустит update_unrpyc_pin.py.
        console.print(
            "[yellow]WARNING: UNRPYC_PINNED_SHA256 is None — "
            "SHA256 verification skipped. Run 'python scripts/update_unrpyc_pin.py' "
            "to enable verification.[/yellow]\n"
        )
        return True

    hasher = hashlib.sha256()
    with open(zip_path, "rb") as f:
        # Читаем чанками, чтобы не грузить весь zip в память
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    actual_sha = hasher.hexdigest()

    if actual_sha != UNRPYC_PINNED_SHA256:
        console.print(
            f"[bold red]SHA256 mismatch for unrpyc![/bold red]\n"
            f"  Expected: {UNRPYC_PINNED_SHA256}\n"
            f"  Actual:   {actual_sha}\n"
            f"Possible causes: MITM attack, compromised GitHub, or pinned commit changed.\n"
            f"Refusing to install."
        )
        return False
    return True


def _safe_zip_extract(zip_ref: zipfile.ZipFile, dest_dir: str) -> list[str]:
    """ECO-4: безопасная распаковка zip с защитой от Zip Slip.

    Python 3.6+ уже санитайзит пути в extractall, но defence-in-depth:
    явно проверяем, что все пути внутри dest_dir. Возвращает список распакованных файлов.
    """
    dest_dir_abs = os.path.abspath(dest_dir)
    extracted = []
    for member in zip_ref.namelist():
        member_path = os.path.abspath(os.path.join(dest_dir, member))
        # Проверяем, что распаковка не выходит за пределы dest_dir
        if os.path.commonpath([member_path, dest_dir_abs]) != dest_dir_abs:
            console.print(f"[red]Zip Slip detected: {member} — skipping[/red]")
            continue
        zip_ref.extract(member, dest_dir)
        extracted.append(member)
    return extracted


def download_unrpyc() -> list[str] | None:
    """ECO-4: скачивает pinned версию unrpyc с SHA256 verification.

    Изменения vs старой версии:
    - Качает конкретный commit (UNRPYC_PINNED_COMMIT), не master.
    - Проверяет SHA256 zip'а (UNRPYC_PINNED_SHA256).
    - Безопасная распаковка (_safe_zip_extract) с защитой от Zip Slip.
    """
    console.print(
        f"[bold cyan]Downloading unrpyc (commit: {UNRPYC_PINNED_COMMIT}) from GitHub...[/bold cyan]"
    )
    os.makedirs(SENPY_CACHE_DIR, exist_ok=True)
    zip_path = os.path.join(SENPY_CACHE_DIR, "unrpyc.zip")

    try:
        req = urllib.request.Request(_unrpyc_zip_url(), headers={"User-Agent": "Senpy-Linter"})
        with urllib.request.urlopen(req) as resp, open(zip_path, "wb") as out:
            shutil.copyfileobj(resp, out)

        # SHA256 verification
        if not _verify_unrpyc_sha256(zip_path):
            # log critical instead of silent return. SHA mismatch is a
            # potential supply-chain attack — user should see this loudly.
            # We still return None (backward compat) but the failure is now
            # observable in logs at ERROR level.
            _logger.error(
                "unrpyc SHA256 verification FAILED for %s — downloaded file "
                "does not match UNRPYC_PINNED_SHA256. Possible supply-chain "
                "attack or upstream changed without pin update. Removing "
                "downloaded file and falling back to no-unrpyc mode.",
                zip_path,
            )
            try:
                os.remove(zip_path)
            except OSError as e:
                # log debug instead of silent suppress.
                _logger.debug("failed to remove bad unrpyc zip %s: %s", zip_path, e)
            return None

        # безопасная распаковка
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            _safe_zip_extract(zip_ref, SENPY_CACHE_DIR)

        try:
            os.remove(zip_path)
        except OSError as e:
            # log debug instead of silent suppress. Cleanup of zip after
            # extraction; failure is non-critical (next run cleans cache_dir).
            _logger.debug("failed to remove unrpyc zip %s: %s", zip_path, e)

        console.print(
            "[bold green]✔ Successfully downloaded and installed unrpyc to cache![/bold green]\n"
        )
        return find_unrpyc_executable(None, None, auto_download=False)
    except (urllib.error.URLError, zipfile.BadZipFile, OSError) as e:
        console.print(f"[bold red]Failed to download unrpyc:[/bold red] {e}\n")
        return None


def find_unrpyc_executable(
    custom_path: str | None, project_path: str | None, auto_download: bool = True
) -> list[str] | None:
    if custom_path and os.path.exists(custom_path):
        if custom_path.endswith(".py"):
            return [sys.executable, custom_path]
        return [custom_path]

    if os.path.exists(SENPY_CACHE_DIR):
        for root, _, files in os.walk(SENPY_CACHE_DIR, followlinks=False):
            if "unrpyc.py" in files:
                return [sys.executable, os.path.join(root, "unrpyc.py")]

    which_unrpyc = shutil.which("unrpyc")
    if which_unrpyc:
        return [which_unrpyc]

    try:
        res = subprocess.run(
            [sys.executable, "-m", "unrpyc", "--help"],
            capture_output=True,
            check=False,
            timeout=30,  # CLI-18: защита от зависшего unrpyc
        )
        if res.returncode == 0:
            return [sys.executable, "-m", "unrpyc"]
    except (subprocess.SubprocessError, OSError, subprocess.TimeoutExpired) as e:
        # log debug instead of silent suppress. Probe failure means
        # unrpyc module is not installed; we fall through to find_in_directory_tree.
        _logger.debug("unrpyc --help probe failed: %s", e)

    search_dirs = [os.getcwd()]
    if project_path:
        search_dirs.append(project_path)
    local_found = find_in_directory_tree(search_dirs)
    if local_found:
        return [sys.executable, local_found]

    if auto_download and hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
        console.print("[bold yellow]unrpyc was not found on your system.[/bold yellow]")
        try:
            ans = (
                input("Would you like Senpy to automatically download unrpyc from GitHub? [Y/n]: ")
                .strip()
                .lower()
            )
            if ans in ("", "y", "yes"):
                return download_unrpyc()
        except (EOFError, KeyboardInterrupt):
            pass

    return None


def extract_scripts_from_rpa(rpa_path: str, dest_dir: str) -> list[str]:
    """Быстро и инкрементально извлекает .rpy и .rpyc из архива .rpa в изолированную песочницу с защитой от Path Traversal."""
    extracted = []
    rpa_mtime = os.path.getmtime(rpa_path) if os.path.exists(rpa_path) else 0.0
    dest_dir_abs = os.path.abspath(dest_dir)

    try:
        with open(rpa_path, "rb") as f:
            header = f.read(50)
            parts = header.split()
            if not parts or not parts[0].startswith((b"RPA-3.0", b"RPA-2.0")):
                return []

            offset = int(parts[1], 16)
            key = int(parts[2], 16) if len(parts) > 2 and parts[0].startswith(b"RPA-3.0") else 0

            f.seek(offset)
            index = safe_load_rpa_index(f.read())

            for filename, segments in index.items():
                clean_name = filename.replace("\\", "/")
                base_fn = os.path.basename(clean_name)

                if base_fn.endswith((".rpyc", ".rpy")):
                    dest = os.path.abspath(os.path.join(dest_dir, clean_name))

                    # Защита от Path Traversal: блокируем попытки записи вне dest_dir (например, ../../malicious.rpy)
                    try:
                        if os.path.commonpath([dest, dest_dir_abs]) != dest_dir_abs:
                            continue
                    except ValueError:
                        continue

                    # Кэш: если файл уже извлечён и свежее архива, пропускаем чтение байт
                    if os.path.exists(dest) and os.path.getmtime(dest) >= rpa_mtime:
                        extracted.append(dest)
                        continue

                    file_bytes = b""
                    for seg in segments:
                        seg_offset = seg[0] ^ key
                        seg_len = seg[1] ^ key
                        prefix = seg[2] if len(seg) > 2 else b""
                        f.seek(seg_offset)
                        file_bytes += prefix + f.read(seg_len - len(prefix))

                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "wb") as out:
                        out.write(file_bytes)
                    extracted.append(dest)
    except (OSError, ValueError, TypeError, zlib.error, pickle.PickleError) as e:
        # log debug instead of silent suppress. RPA extraction failure
        # is recoverable (just no .rpy from this archive); but tracking it
        # helps spot corrupt .rpa files.
        _logger.debug(
            "failed to extract scripts from RPA %s: %s", rpa_path, e
        )

    return extracted


def decompile_to_sandbox(orphans: list[str], unrpyc_cmd: list[str] | None = None, temp_dir: str = "") -> list[str]:
    """Декомпилирует .rpyc файлы в .rpy в изолированной песочнице.

    ECO-5: Теперь использует встроенный (vendored) unrpyc вместо subprocess.
    Параметр unrpyc_cmd сохранён для обратной совместимости, но игнорируется.
    """
    from senpy.vendor.unrpyc import decompile_rpyc

    total = len(orphans)
    prep_label = "[Подготовка]" if IS_RU else "[Preparing]"
    decomp_label = "[Декомпиляция]" if IS_RU else "[Decompiling]"

    temp_rpyc_files = []
    for i, f in enumerate(orphans, 1):
        base_name = os.path.basename(f)
        dest = os.path.join(temp_dir, base_name)
        if os.path.exists(f) and os.path.normcase(os.path.abspath(f)) != os.path.normcase(
            os.path.abspath(dest)
        ):
            shutil.copy2(f, dest)
        temp_rpyc_files.append(dest)
        msg = f"\r{prep_label} {i}/{total} ({base_name[:25]})"
        print(msg.ljust(75), end="", flush=True)

    print()

    decompiled_rpy = []
    done = 0
    for rpyc_file in temp_rpyc_files:
        done += 1  # noqa: SIM113
        base_name = os.path.basename(rpyc_file)
        if base_name.endswith(".rpyc"):
            rpy_name = base_name[:-1]  # .rpyc -> .rpy
        elif base_name.endswith(".rpymc"):
            rpy_name = base_name[:-1]  # .rpymc -> .rpym
        else:
            rpy_name = base_name + ".rpy"

        rpy_path = os.path.join(temp_dir, rpy_name)
        msg = f"\r{decomp_label} {done}/{total} ({rpy_name[:25]})"
        print(msg.ljust(75), end="", flush=True)

        try:
            rpy_text = decompile_rpyc(rpyc_file)
            with open(rpy_path, "w", encoding="utf-8") as f:
                f.write(rpy_text)
            decompiled_rpy.append(rpy_path)
        except Exception as e:
            err_msg = "Ошибка декомпиляции" if IS_RU else "Decompilation error"
            # ECO-5: RPYCDecompilationError даёт понятное сообщение,
            # любые другие исключения — выводим тип ошибки
            err_type = type(e).__name__
            console.print(
                f"\n[bold red]{err_msg} ({base_name}):[/bold red] "
                f"[{err_type}] {e}"
            )

    print()
    success_msg = (
        f"✔ Успешно декомпилировано {len(decompiled_rpy)} файл(ов) в песочницу!"
        if IS_RU
        else f"✔ Successfully decompiled {len(decompiled_rpy)} file(s) into sandbox!"
    )
    console.print(f"[bold green]{success_msg}[/bold green]\n")
    return decompiled_rpy
