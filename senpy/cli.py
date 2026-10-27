from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import pickle
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
import zipfile
import zlib
from collections import Counter

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from senpy.analyzer import SenpyAnalyzer
from senpy.constants import IGNORED_DIRS
from senpy.rpa import safe_load_rpa_index
from senpy.traceback import find_latest_traceback, parse_traceback_file
from senpy.tsundere import IS_RU, TSUNDERE_FLAVORS, TSUNDERE_UI

# Пайпы (VS Code-расширение, >file, CI) всегда получают utf-8: дефолтная
# кодировка пайпа Windows = locale (cp1251) -> UnicodeEncodeError на ✔/(//∇//)
# и mojibake для кириллицы (Node декодирует пайп как utf8). Интерактивную
# консоль не трогаем: там rich пишет через WriteConsoleW (Unicode-safe).
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and not _stream.isatty() and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

# legacy-рендерер Windows у rich падает на stdout-пайпе (WriteConsoleW на
# невалидном хэндле): отключаем его, когда вывод не интерактивный терминал.
# В живой консоли (isatty=True) поведение прежнее.
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
# Default: v2.0.4 — последний стабильный релиз unrpyc (24 февраля 2026).
# Поддержка: Ren'Py 6.18.0+ / 6.99 / 7.x / 8.x.
# Обновить: `python scripts/update_unrpyc_pin.py` (подставит реальный commit SHA + SHA256).
# Список профилей: `python scripts/update_unrpyc_pin.py --list`.
UNRPYC_PINNED_COMMIT = "v2.0.4"
UNRPYC_PINNED_SHA256 = None  # placeholder — будет вычислен при update
UNRPYC_GITHUB_ZIP_TEMPLATE = "https://github.com/CensoredUsername/unrpyc/archive/{commit}.zip"


def _unrpyc_zip_url() -> str:
    """URL для скачивания pinned версии unrpyc."""
    return UNRPYC_GITHUB_ZIP_TEMPLATE.format(commit=UNRPYC_PINNED_COMMIT)


SEVERITY_STYLES = {
    "ERROR": ("bold red", "red dim"),
    "WARNING": ("bold yellow", "yellow dim"),
    "HINT": ("bold cyan", "cyan dim"),
    "INFO": ("bold blue", "blue dim"),
}


def load_config(project_path: str) -> dict:
    candidates = [
        os.path.join(project_path, "senpy.toml"),
        os.path.join(project_path, "pyproject.toml"),
        os.path.join(os.path.dirname(project_path), "senpy.toml"),
        os.path.join(os.path.dirname(project_path), "pyproject.toml"),
        os.path.join(os.getcwd(), "senpy.toml"),
        os.path.join(os.getcwd(), "pyproject.toml"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            with (
                contextlib.suppress(tomllib.TOMLDecodeError, OSError),
                open(c, "rb") as f,
            ):
                data = tomllib.load(f)
                return data.get("tool", {}).get("senpy", data.get("senpy", {}))
    return {}


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

        # ECO-4: SHA256 verification
        if not _verify_unrpyc_sha256(zip_path):
            with contextlib.suppress(OSError):
                os.remove(zip_path)
            return None

        # ECO-4: безопасная распаковка
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            _safe_zip_extract(zip_ref, SENPY_CACHE_DIR)

        with contextlib.suppress(OSError):
            os.remove(zip_path)

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
        for root, _, files in os.walk(SENPY_CACHE_DIR):
            if "unrpyc.py" in files:
                return [sys.executable, os.path.join(root, "unrpyc.py")]

    which_unrpyc = shutil.which("unrpyc")
    if which_unrpyc:
        return [which_unrpyc]

    with contextlib.suppress(subprocess.SubprocessError, OSError):
        res = subprocess.run(
            [sys.executable, "-m", "unrpyc", "--help"], capture_output=True, check=False
        )
        if res.returncode == 0:
            return [sys.executable, "-m", "unrpyc"]

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

    with (
        contextlib.suppress(OSError, ValueError, TypeError, zlib.error, pickle.PickleError),
        open(rpa_path, "rb") as f,
    ):
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

    return extracted


def decompile_to_sandbox(orphans: list[str], unrpyc_cmd: list[str], temp_dir: str) -> list[str]:
    total = len(orphans)
    prep_label = "[Подготовка]" if IS_RU else "[Preparing]"
    decomp_label = "[Декомпиляция]" if IS_RU else "[Decompiling]"
    done_word = "готово" if IS_RU else "done"

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

    cmd = unrpyc_cmd + ["-c"] + temp_rpyc_files

    done = 0
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if process.stdout:
            for line in process.stdout:
                if "decompil" in line.lower():
                    done = min(total, done + 1)
                    curr_file = ""
                    for part in line.split():
                        clean_part = part.strip("\"'()[],:;.")
                        if clean_part.endswith((".rpyc", ".rpy")):
                            curr_file = os.path.basename(clean_part)
                            break
                    if not curr_file:
                        curr_file = done_word if done == total else "..."
                    msg = f"\r{decomp_label} {done}/{total} ({curr_file[:25]})"
                    print(msg.ljust(75), end="", flush=True)
        process.wait()
        print()
    except (subprocess.SubprocessError, OSError) as e:
        err_msg = "Ошибка декомпиляции" if IS_RU else "Decompilation error"
        console.print(f"[bold red]{err_msg}:[/bold red] {e}")

    decompiled_rpy = []
    for root, _, files in os.walk(temp_dir):
        for file in files:
            if file.endswith(".rpy"):
                decompiled_rpy.append(os.path.join(root, file))

    success_msg = (
        f"✔ Успешно декомпилировано {len(decompiled_rpy)} файл(ов) в песочницу!"
        if IS_RU
        else f"✔ Successfully decompiled {len(decompiled_rpy)} file(s) into sandbox!"
    )
    console.print(f"[bold green]{success_msg}[/bold green]\n")
    return decompiled_rpy


# --- P0-1 helpers: file redirect for text-format output ---
class _ReplaceConsole:
    """Context manager: временно подменяет модульную `console` на `file_console`,
    корректно закрывая файл при выходе (даже при sys.exit внутри блока)."""

    def __init__(self, file_console: Console):
        self._file_console = file_console
        self._original_console: Console | None = None

    def __enter__(self):
        global console
        self._original_console = console
        console = self._file_console
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        global console
        # Возвращаем оригинальную console
        if self._original_console is not None:
            console = self._original_console
        # Закрываем файловый поток (rich Console хранит его в .file)
        try:
            if hasattr(self._file_console.file, "close"):
                self._file_console.file.close()
        except Exception:
            pass
        # Не подавляем исключения
        return False


def _replace_console(file_console: Console) -> _ReplaceConsole:
    """Фабрика для with-блока: with _replace_console(file_console): ..."""
    return _ReplaceConsole(file_console)


def _exit_with_output_redirect(args, exit_code: int) -> None:
    """Закрывает файл (если был открыт) и выходит с exit_code.
    Используется вместо sys.exit() внутри with-блока text-вывода."""
    # sys.exit() поднимает SystemExit, который корректно обрабатывается
    # __exit__ context manager'а — файл закроется автоматически.
    sys.exit(exit_code)


def _make_file_console(args) -> Console:
    """Создаёт файловую Console для text-формата с --output-file.
    Force_terminal=False чтобы rich не применял ANSI-цвета в файл."""
    out_dir = os.path.dirname(os.path.abspath(args.output_file))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    # type: ignore[arg-type] — file ожидает IO[str], file-объект подходит
    return Console(
        file=open(args.output_file, "w", encoding="utf-8"),
        force_terminal=False,
        legacy_windows=False,
    )


class _NullRedirect:
    """No-op context manager для случая без --output-file."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def _null_redirect() -> _NullRedirect:
    return _NullRedirect()


def main():

    parser = argparse.ArgumentParser(
        prog="senpy",
        description="Notice me, Senpy! Fast semantic linter & LSP for Ren'Py.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # UX-15: --version — печатает версию и выходит (как у ruff/black).
    # Использует senpy.__version__ (single source of truth после ECO-9).
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show Senpy version and exit",
    )

    # 1. Позиционный аргумент: путь к проекту
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the Ren'Py project or 'game' directory (default: current dir)",
    )

    # 2. Справка и документация по правилам
    g_rules = parser.add_argument_group("Rules & Documentation")
    g_rules.add_argument(
        "--rules",
        action="store_true",
        help="List all 40 available Senpy rules and their descriptions",
    )
    g_rules.add_argument(
        "--rule",
        metavar="CODE",
        help="Show detailed explanation and code examples for a specific rule (e.g. --rule RPY104)",
    )

    # 3. Настройки анализа и автофикса
    g_lint = parser.add_argument_group("Analysis & Autofix")
    g_lint.add_argument(
        "--fix",
        action="store_true",
        help="Automatically fix safe errors (unclosed tags RPY301, smart quotes RPY002, tabs RPY001)",
    )
    g_lint.add_argument(
        "--coverage",
        action="store_true",
        help="Display translation coverage metrics and completion percentages for game/tl/",
    )
    g_lint.add_argument(
        "--stats",
        action="store_true",
        help="Calculate story & character dialogue statistics, word count and reading time",
    )
    g_lint.add_argument(
        "--defaults",
        action="store_true",
        help="Generate 'senpy_defaults.rpy' containing 'default' declarations for all RPY104 variables",
    )
    g_lint.add_argument(
        "--errors-only",
        action="store_true",
        help="Show only critical ERRORs, hiding WARNINGs and INFO notices",
    )
    g_lint.add_argument(
        "--info",
        action="store_true",
        help="Display informational notices (e.g. unreferenced labels RPY303)",
    )
    g_lint.add_argument(
        "--ignore",
        nargs="+",
        metavar="CODE",
        default=None,
        help="Ignore specific error codes (e.g. --ignore RPY104 RPY101)",
    )
    g_lint.add_argument(
        "--max-errors",
        type=int,
        metavar="NUM",
        default=None,
        help="Maximum errors to display in terminal (default: 50)",
    )
    g_lint.add_argument(
        "--no-cache", action="store_true", help="Disable disk caching (.senpy_cache)"
    )
    g_lint.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear project cache directory (.senpy_cache) and exit",
    )
    # UX-15: dry-run и CI-friendly опции для --fix.
    g_lint.add_argument(
        "--check",
        action="store_true",
        help="Dry-run for --fix: report what would be fixed, but don't write. "
        "Exit 1 if any fixable issues found (CI-friendly).",
    )
    g_lint.add_argument(
        "--diff",
        action="store_true",
        help="Show unified diff of what --fix would change, but don't write files. "
        "Useful for reviewing auto-fixes before applying.",
    )
    g_lint.add_argument(
        "--exit-zero",
        action="store_true",
        help="Always exit 0, even if errors found. Useful for non-blocking CI runs "
        "(e.g. nightly reports). Still prints diagnostics to stdout.",
    )

    # 4. Визуализация и форматы отчётов
    g_export = parser.add_argument_group("Visualization & Reports")
    g_export.add_argument(
        "--export-html",
        metavar="FILE",
        help="Generate a standalone HTML report with an interactive story map and diagnostics",
    )
    g_export.add_argument(
        "--export-wiki",
        nargs="?",
        const="PROJECT_WIKI.md",
        metavar="FILE",
        help="Generate project documentation (characters, variables, endings) in Markdown (default: PROJECT_WIKI.md)",
    )
    g_export.add_argument(
        "--graph",
        action="store_true",
        help="Generate a Mermaid.js diagram of the story flow and label transitions",
    )
    g_export.add_argument(
        "--graph-file",
        metavar="FILE",
        help="Save the Mermaid.js story diagram directly to a file (e.g. story.md)",
    )
    g_export.add_argument(
        "--output-format",
        "--format",
        dest="output_format",
        choices=["text", "json", "sarif"],
        default="text",
        help="Output format: 'text' (default), 'json' for VS Code, or 'sarif' for GitHub Actions",
    )
    g_export.add_argument(
        "--output-file",
        metavar="FILE",
        help="Save report to a specific file (e.g. report.json or report.txt)",
    )

    # 5. Декомпиляция и интеграции
    g_tools = parser.add_argument_group("Tools & Integrations")
    g_tools.add_argument(
        "--lsp",
        action="store_true",
        help="Run Senpy as a Language Server (LSP) for editors like VS Code / Neovim",
    )
    g_tools.add_argument(
        "--init-ci",
        action="store_true",
        help="Generate a GitHub Actions workflow (.github/workflows/senpy.yml) with automated SARIF scanning",
    )
    g_tools.add_argument(
        "--traceback",
        nargs="?",
        const="traceback.txt",
        metavar="FILE",
        help="Inspect runtime crash log (traceback.txt or errors.txt) and explain the crash using Senpy rules",
    )
    g_tools.add_argument(
        "--stubs",
        nargs="?",
        const="typings",
        metavar="DIR",
        help="Generate Python type stubs (.pyi) for Pylance / MyPy in VS Code (default: typings/)",
    )
    g_tools.add_argument(
        "--decompile",
        action="store_true",
        help="Automatically decompile orphaned .rpyc files into a temporary sandbox",
    )
    g_tools.add_argument(
        "--unrpyc", metavar="PATH", help="Custom path to unrpyc.py or unrpyc executable"
    )
    g_tools.add_argument(
        "--tsundere",
        action="store_true",
        help="B-Baka! It's not like I want to check your visual novel!",
    )

    args = parser.parse_args()

    # UX-15: --version — печатает и выходит.
    if args.version:
        from senpy.__version__ import __version__

        print(f"senpy {__version__}")
        sys.exit(0)

    if args.lsp:
        from senpy.server import start_lsp

        start_lsp()
        sys.exit(0)

    if args.rules or args.rule:
        from senpy.rules_info import show_rule_detail, show_rules_table

        if args.rule:
            show_rule_detail(args.rule.upper())
        else:
            show_rules_table()
        sys.exit(0)

    config = load_config(args.path)
    is_tsundere = args.tsundere or config.get("tsundere", False)

    if args.traceback:
        # P0-3: ранее `--traceback` имел const="traceback.txt", что ломало авто-поиск
        # errors.txt. Если пользователь не указал имя файла явно (использовал
        # дефолтный const), и указанного файла нет — пытаемся найти через
        # find_latest_traceback(args.path), который проверяет и traceback.txt,
        # и errors.txt, и game/traceback.txt, и game/errors.txt.
        traceback_arg = args.traceback
        if not os.path.isfile(traceback_arg):
            # Не absolute path и не существует в CWD — попробуем относительно args.path
            relative_to_project = os.path.join(args.path, traceback_arg)
            if os.path.isfile(relative_to_project):
                traceback_arg = relative_to_project
            elif traceback_arg == "traceback.txt":
                # Дефолтный const, файл не найден нигде — пробуем авто-поиск
                auto_found = find_latest_traceback(args.path)
                if auto_found:
                    traceback_arg = auto_found

        crash = parse_traceback_file(traceback_arg)
        if not crash:
            console.print(
                f"[yellow]Could not find or parse crash log at '[bold]{traceback_arg}[/bold]'.[/yellow]\n"
            )
            # Если ни один файл не нашёлся — подсказываем пользователю
            if traceback_arg == "traceback.txt" or traceback_arg == args.traceback:
                console.print(
                    "[dim]Hint: senpy looks for traceback.txt or errors.txt in project root or game/ subfolder.[/dim]"
                )
            sys.exit(0)

        t_text = Text()
        t_text.append("Runtime Crash Report (Post-Mortem Analysis)\n\n", style="bold red")
        t_text.append(f"Location:  {crash.file_path}:{crash.line_number}\n", style="bold cyan")
        if crash.code_line:
            t_text.append(f"Code:      {crash.code_line}\n", style="bright_white")
        t_text.append(
            f"Exception: {crash.exception_type}: {crash.exception_message}\n\n", style="bold yellow"
        )
        t_text.append(f"Rule [{crash.rule_code}]: ", style="bold red")
        t_text.append(f"{crash.explanation}\n", style="bright_white")

        console.print(Panel(t_text, title="Traceback Inspector", border_style="red"))
        sys.exit(0)

    if args.init_ci:
        from senpy.ci import init_ci_workflow

        out_path, _created = init_ci_workflow(args.path)
        rel_out = os.path.relpath(out_path, os.getcwd())
        if is_tsundere:
            console.print(
                f"[bold magenta]{TSUNDERE_UI['init_ci'].format(path=rel_out)}[/bold magenta]\n"
            )
        else:
            console.print(
                f"[bold green]✔ Successfully created GitHub Actions workflow:[/bold green] [bold cyan]{rel_out}[/bold cyan]\n"
                "[dim]Commit and push this file to enable automatic GitHub Code Scanning on every Pull Request![/dim]\n"
            )
        sys.exit(0)

    if args.coverage:
        from senpy.coverage import calculate_translation_coverage

        coverage_data = calculate_translation_coverage(args.path)

        if not coverage_data:
            console.print("[yellow]No translations found in game/tl/ directory.[/yellow]\n")
            sys.exit(0)

        table = Table(title="Localization Coverage (game/tl/)", border_style="dim")
        table.add_column("Language", style="bold cyan")
        table.add_column("Total Strings", justify="right", style="bold white")
        table.add_column("Translated", justify="right", style="bold green")
        table.add_column("Missing / Empty", justify="right", style="bold red")
        table.add_column("Completion", justify="right")

        for lang, stats in sorted(coverage_data.items()):
            pct = stats.coverage_percent
            pct_style = (
                "bold green" if pct >= 95.0 else "bold yellow" if pct >= 70.0 else "bold red"
            )
            table.add_row(
                lang,
                f"{stats.total_strings:,}",
                f"{stats.translated_strings:,}",
                f"{stats.empty_strings:,}",
                f"[{pct_style}]{pct}%[/{pct_style}]",
            )

        console.print(table)
        if is_tsundere:
            console.print(f"\n[bold magenta]{TSUNDERE_UI['coverage']}[/bold magenta]\n")
        sys.exit(0)

    if args.clear_cache:
        from senpy.cache import CacheManager

        cm = CacheManager(args.path)
        if cm.clear():
            console.print(
                f"[bold green]✔ Successfully cleared cache directory: {cm.cache_dir}[/bold green]"
            )
        else:
            console.print("[dim]Cache directory does not exist, nothing to clear.[/dim]")
        sys.exit(0)

    cfg_ignore = set(config.get("ignore", []))
    cli_ignore = set(args.ignore) if args.ignore is not None else set()
    ignored_codes = {c.strip().upper() for c in (cli_ignore or cfg_ignore)}

    max_errors = args.max_errors or config.get("max_errors", 50)
    auto_decompile = args.decompile or config.get("decompile", False)

    # 1. Песочницы внутри кэша
    decomp_sandbox = os.path.join(os.path.abspath(args.path), ".senpy_cache", "decompiled")
    rpa_sandbox = os.path.join(os.path.abspath(args.path), ".senpy_cache", "rpa_extracted")
    os.makedirs(decomp_sandbox, exist_ok=True)
    os.makedirs(rpa_sandbox, exist_ok=True)

    raw_orphans = SenpyAnalyzer.find_orphaned_rpyc(args.path)
    orphaned_rpyc = []
    extra_rpy_files = []

    # Предварительно собираем список существующих .rpy строго без учета .senpy_cache
    # P0-4: ранее existing_rpy_files хранил basenames, что ломало multi-module
    # проекты (game/script.rpy и mods/script.rpy коллайдили, второй .rpyc
    # пропускался как «уже есть»). Теперь храним ДВА множества:
    #   existing_rpy_files    — relpath относительно args.path (уникальные пути)
    #   existing_rpy_basenames — basenames для совместимости со старой логикой
    #                            дедупликации .rpyc (один .rpyc → один .rpy по basename)
    existing_rpy_files = set()
    existing_rpy_basenames = set()
    for root, dirs, files in os.walk(args.path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for f in files:
            if f.endswith(".rpy"):
                full_path = os.path.join(root, f)
                try:
                    rel = os.path.relpath(full_path, args.path)
                except ValueError:
                    # Cross-drive на Windows — fallback на basename
                    rel = f
                existing_rpy_files.add(rel)
                existing_rpy_basenames.add(f)

    # 2. Умная работа с RPA: ищем скрипты в архивах (для релизных сборок и модов)
    rpa_files = []
    for root, dirs, files in os.walk(args.path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for f in files:
            if f.lower().endswith(".rpa"):
                rpa_files.append(os.path.join(root, f))

    for rpa in rpa_files:
        rpa_base = os.path.splitext(os.path.basename(rpa))[0].lower()
        if (
            any(term in rpa_base for term in ("script", "archive", "data", "game", "code"))
            or not raw_orphans
        ):
            extracted = extract_scripts_from_rpa(rpa, rpa_sandbox)
            for item in extracted:
                base_name = os.path.basename(item)
                rpy_name = base_name[:-1] if base_name.endswith(".rpyc") else base_name
                # Если такой .rpy уже есть в game/, пропускаем архивную копию
                # P0-4: сравнение по basename (как раньше) — это правильно для
                # дедупликации .rpyc vs .rpy (один .rpyc → один .rpy с тем же именем).
                if rpy_name not in existing_rpy_basenames:
                    if item.endswith(".rpy"):
                        extra_rpy_files.append(item)
                    elif item.endswith(".rpyc"):
                        raw_orphans.append(item)

    # 3. Синхронизируем исходники для дедупликации (не декомпилируем .rpyc, если уже найден .rpy)
    for f in extra_rpy_files:
        existing_rpy_basenames.add(os.path.basename(f))

    # 4. Проверяем кэш декомпиляции для всех .rpyc (с диска и из .rpa)
    for rpyc in raw_orphans:
        rpy_name = os.path.basename(rpyc)[:-1]

        # Если .rpy исходник уже найден в папке или вытащен из архива — игнорируем его .rpyc
        # P0-4: сравнение по basename (как раньше) — .rpyc-дедупликация корректна по basename.
        if rpy_name in existing_rpy_basenames:
            continue

        cached_rpy = os.path.join(decomp_sandbox, rpy_name)
        if os.path.exists(cached_rpy) and os.path.getmtime(cached_rpy) >= os.path.getmtime(rpyc):
            if cached_rpy not in extra_rpy_files:
                extra_rpy_files.append(cached_rpy)
        else:
            if rpyc not in orphaned_rpyc:
                orphaned_rpyc.append(rpyc)

    # 5. Если появились новые/изменённые .rpyc — декомпилируем в песочницу
    if orphaned_rpyc:
        should_decompile = auto_decompile
        is_interactive = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
        if (
            not should_decompile
            and is_interactive
            and not (args.graph or args.graph_file or args.stats)
        ):
            console.print(
                f"[bold yellow]Found {len(orphaned_rpyc)} compiled .rpyc file(s) without source code.[/bold yellow]"
            )
            try:
                answer = (
                    input("Decompile them into a sandbox for analysis? [y/N]: ").strip().lower()
                )
                should_decompile = answer in ("y", "yes")
            except (EOFError, KeyboardInterrupt):
                should_decompile = False

        if should_decompile:
            custom_unrpyc = args.unrpyc or config.get("unrpyc_path")
            unrpyc_cmd = find_unrpyc_executable(
                custom_unrpyc, args.path, auto_download=is_interactive
            )
            if unrpyc_cmd:
                new_decompiled = decompile_to_sandbox(orphaned_rpyc, unrpyc_cmd, decomp_sandbox)
                for f_rpy in new_decompiled:
                    if f_rpy not in extra_rpy_files:
                        extra_rpy_files.append(f_rpy)

    is_quiet_mode = bool(
        args.graph or args.graph_file or args.stats or args.output_format in ("json", "sarif")
    )

    if not is_quiet_mode:
        if is_tsundere:
            console.print(
                f"[bold magenta](¬_¬ ) «{TSUNDERE_UI['intro'].format(path=args.path)}»[/bold magenta]\n"
            )
        else:
            console.print(f"[bold cyan]Scanning directory:[/bold cyan] {args.path}...\n")

        recent_tb = find_latest_traceback(args.path)
        if recent_tb:
            auto_crash = parse_traceback_file(recent_tb)
            if auto_crash:
                tb_name = os.path.basename(recent_tb)
                tb_text = Text()
                tb_text.append(f"Recent crash log detected ({tb_name})!\n", style="bold red")
                tb_text.append(
                    f"Crashed at: {auto_crash.file_path}:{auto_crash.line_number} — {auto_crash.exception_type}\n",
                    style="yellow",
                )
                tb_text.append(
                    f"[{auto_crash.rule_code}] {auto_crash.explanation}", style="bright_white"
                )
                console.print(Panel(tb_text, border_style="red dim", expand=False))
                console.print()

    # UX-15: --check и --diff — dry-run режимы для --fix.
    # --check: анализируем с fix=False (НЕ применяем фиксы), смотрим на fixable_count.
    #          Exit 1 если fixable > 0. Это правильно: analyzer.run() с fix=False
    #          уже считает fixable_count (количество потенциальных фиксов).
    # --diff: анализируем с fix=True, но monkey-patch open() чтобы перехватить
    #         запись и собрать diff, не трогая диск.
    diff_collector: dict[str, str] = {}
    _real_open = open
    if args.diff:
        import builtins

        _real_open = builtins.open

        def _intercept_open(file, mode="r", *a, **kw):
            if "w" in mode and isinstance(file, str) and file.endswith(".rpy"):

                class _DiffCapture:
                    def __init__(self):
                        self._buf = []

                    def write(self, s):
                        self._buf.append(s)

                    def writelines(self, lines):
                        self._buf.extend(lines)

                    def close(self):
                        pass

                    def flush(self):
                        pass

                    def __enter__(self):
                        return self

                    def __exit__(self, *a):
                        diff_collector[file] = "".join(self._buf)

                return _DiffCapture()
            return _real_open(file, mode, *a, **kw)

        builtins.open = _intercept_open

    # --check: fix=False (ничего не меняем, только считаем fixable_count).
    # --diff: fix=True (analyzer готовит изменения, но open() перехвачен).
    # обычный --fix: fix=True.
    # без опций: fix=False.
    should_apply_fix = args.fix or args.diff  # --check НЕ применяет

    # UX-15: --check и --diff форсируют --no-cache. Tier 2 cache хранит diagnostics,
    # но НЕ fixable_count (он инкрементируется только в _analyze_file).
    # Если использовать кэш, fixable_count=0 и --check ложно говорит "No fixable".
    no_cache = args.no_cache or args.check or args.diff

    start_time = time.perf_counter()
    analyzer = SenpyAnalyzer(
        args.path, extra_files=extra_rpy_files, fix=should_apply_fix, no_cache=no_cache
    )
    result = analyzer.run(quiet=is_quiet_mode)
    elapsed = time.perf_counter() - start_time

    # Восстанавливаем open()
    if args.diff:
        builtins.open = _real_open
    if args.stats:
        # P0-2: ранее здесь создавался НОВЫЙ SenpyAnalyzer(args.path) без extra_files
        # и без fix=args.fix — это теряло все декомпилированные из .rpyc/.rpa файлы
        # и заставляло повторно сканировать проект. Теперь переиспользуем уже
        # готовый analyzer с полным набором файлов.
        from senpy.stats import collect_story_stats

        stats = collect_story_stats(analyzer)

        if args.output_format == "json":
            out_data = {
                "total_dialogue_lines": stats.total_dialogue_lines,
                "total_words": stats.total_words,
                "total_chars": stats.total_chars,
                "reading_time_minutes": stats.reading_time_minutes,
                "reading_time_formatted": stats.reading_time_formatted,
                "characters": [
                    {
                        "tag": c.tag,
                        "display_name": c.display_name,
                        "lines": c.lines_count,
                        "words": c.words_count,
                        "chars": c.chars_count,
                        "percentage": c.percentage_words,
                    }
                    for c in stats.characters.values()
                ],
            }
            json_str = json.dumps(out_data, indent=2, ensure_ascii=False)
            if args.output_file:
                with open(args.output_file, "w", encoding="utf-8") as f:
                    f.write(json_str)
                console.print(f"[bold green]✔ Stats saved to {args.output_file}[/bold green]")
            else:
                print(json_str)
            sys.exit(0)

        # Вывод дашборда в терминал
        summary_panel = Panel(
            Text.from_markup(
                f"[bold cyan]Total Dialogue Lines:[/bold cyan] [bold white]{stats.total_dialogue_lines:,}[/bold white]   "
                f"[bold cyan]Total Words:[/bold cyan] [bold green]{stats.total_words:,}[/bold green]   "
                f"[bold cyan]Characters:[/bold cyan] [bold yellow]{stats.total_chars:,}[/bold yellow]\n"
                f"[bold cyan]Estimated Reading Time:[/bold cyan] [bold magenta]{stats.reading_time_formatted}[/bold magenta] (at 180 wpm)   "
                f"[bold cyan]Cast Size:[/bold cyan] [bold white]{len(stats.characters)} speakers[/bold white]"
            ),
            title="[bold magenta]Story & Script Analytics[/bold magenta]",
            border_style="cyan",
        )
        console.print(summary_panel)

        table = Table(title="Dialogue Speech Share", border_style="dim")
        table.add_column("Speaker", style="bold cyan")
        table.add_column("Identifier", style="dim")
        table.add_column("Lines", justify="right", style="bold white")
        table.add_column("Words", justify="right", style="bold green")
        table.add_column("Share", justify="right", style="bold yellow")
        table.add_column("Distribution Bar", style="bright_magenta")

        for c in stats.characters.values():
            bar_len = int(c.percentage_words // 5)
            if bar_len > 0:
                bar = f"[bright_magenta]{'█' * bar_len}[/][dim]{'░' * (20 - bar_len)}[/dim]"
            else:
                bar = f"[dim]{'░' * 20}[/dim]"

            table.add_row(
                c.display_name,
                f"`{c.tag}`",
                f"{c.lines_count:,}",
                f"{c.words_count:,}",
                f"{c.percentage_words}%",
                bar,
            )

        console.print(table)
        if is_tsundere and "stats" in TSUNDERE_UI:
            console.print(
                f"\n[bold magenta]{TSUNDERE_UI['stats'].format(words=stats.total_words, hours=stats.reading_time_minutes / 60)}[/bold magenta]\n"
            )
        sys.exit(0)
    if args.export_wiki:
        from senpy.wiki import generate_project_wiki

        wiki_md = generate_project_wiki(analyzer)
        target_wiki = args.export_wiki
        with open(target_wiki, "w", encoding="utf-8", newline="\n") as f:
            f.write(wiki_md)
        if is_tsundere:
            console.print(
                f"\n[bold magenta]{TSUNDERE_UI['export_wiki'].format(path=target_wiki)}[/bold magenta]\n"
            )
        else:
            console.print(
                f"\n[bold green]✔ Project documentation exported to [bold]{target_wiki}[/bold]![/bold green]\n"
            )
        sys.exit(0)
    if args.export_html:
        from senpy.html_report import generate_html_report

        # Отфильтруем предварительно диагностики как для терминала
        active_diagnostics = [
            e
            for e in result.diagnostics
            if e.code not in ignored_codes
            and (not args.errors_only or e.severity == "ERROR")
            and (args.info or e.severity != "INFO")
        ]
        generate_html_report(
            diagnostics=active_diagnostics,
            graph_mermaid=analyzer.export_graph(),
            file_count=result.file_count,
            total_lines=result.total_lines,
            elapsed=elapsed,
            out_path=args.export_html,
        )
        if is_tsundere:
            console.print(
                f"[bold magenta](//∇//) «Я... я сгенерировала HTML отчёт в [bold]{args.export_html}[/bold]! Изучай свои сюжетные дыры, бака!»[/bold magenta]\n"
            )
        else:
            console.print(
                f"[bold green]✔ Autonomous HTML report saved to [bold]{args.export_html}[/bold][/bold green]\n"
            )
    if args.graph or args.graph_file:
        graph_content = analyzer.export_graph()
        if args.graph_file:
            with open(args.graph_file, "w", encoding="utf-8") as f:
                f.write(graph_content)
            if is_tsundere:
                console.print(
                    f"\n[bold magenta](//∇//) «Я... я нарисовала карту твоих переходов в [bold]{args.graph_file}[/bold]! Н-но не думай, что мне интересно, куда пойдёт твой герой, бака!»[/bold magenta]\n"
                )
            else:
                console.print(
                    f"\n[bold green]✔ Story flow graph saved to [bold]{args.graph_file}[/bold]![/bold green]\n"
                )
        else:
            # Сырой вывод в stdout: расширение парсит блоки ```mermaid``` /
            # ```senpy-meta``` регулярками. console.print здесь вреден:
            # soft-wrap ломает однострочный JSON, markup — опасен.
            # utf-8 обязателен: Node декодирует пайп как utf8.
            sys.stdout.write(graph_content + "\n")
        sys.exit(0)

    # Генерация файла senpy_defaults.rpy
    if args.defaults:
        out_file, gen_count = analyzer.generate_defaults_file()
        if gen_count > 0:
            if is_tsundere:
                console.print(
                    f"\n[bold magenta](//∇//) «{TSUNDERE_UI['defaults_generated'].format(path=out_file, count=gen_count)}»[/bold magenta]\n"
                )
            else:
                console.print(
                    f"\n[bold green]✔ Successfully generated [bold]{out_file}[/bold] with [bold]{gen_count}[/bold] default declaration(s)![/bold green]\n"
                )
        else:
            console.print(
                "\n[bold green]✔ All variables are already properly declared via 'default'![/bold green]\n"
            )
        sys.exit(0)

    if args.stubs:
        from senpy.stubs import generate_stubs

        out_dir, count = generate_stubs(analyzer, out_dir=args.stubs)
        rel_out = os.path.relpath(out_dir, os.getcwd())
        if is_tsundere:
            console.print(
                f"\n[bold magenta](//∇//) «{TSUNDERE_UI['generate_stubs'].format(path=rel_out, count=count)}»[/bold magenta]\n"
            )
        else:
            console.print(
                f"\n[bold green]✔ Successfully generated Python type stubs in [bold]{rel_out}/[/bold] ({count} symbols exported)![/bold green]\n"
                "[dim]Pylance and MyPy in VS Code will now natively autocomplete and type-check your Ren'Py store.[/dim]\n"
            )
        sys.exit(0)

    # Фильтруем ошибки по кодам из --ignore и --errors-only
    hidden_info_count = sum(
        1
        for e in result.diagnostics
        if e.severity == "INFO" and e.code not in ignored_codes and not args.info
    )
    active_diagnostics = [
        e
        for e in result.diagnostics
        if e.code not in ignored_codes
        and (not args.errors_only or e.severity == "ERROR")
        and (args.info or e.severity != "INFO")
    ]

    # --- ВЫВОД В ФОРМАТЕ SARIF ДЛЯ GITHUB ACTIONS ---
    if args.output_format == "sarif":
        from senpy.sarif import generate_sarif

        sarif_str = generate_sarif(active_diagnostics, args.path)

        if args.output_file:
            with open(args.output_file, "w", encoding="utf-8") as f:
                f.write(sarif_str)
            console.print(f"[bold green]✔ SARIF report saved to {args.output_file}[/bold green]")
        else:
            print(sarif_str)

        error_count = sum(1 for e in active_diagnostics if e.severity == "ERROR")
        sys.exit(1 if error_count > 0 else 0)

    # --- ВЫВОД В ФОРМАТЕ JSON ДЛЯ VS CODE ---
    elif args.output_format == "json":
        json_output = []
        for err in active_diagnostics:
            json_output.append(
                {
                    "file": err.file_path,
                    "line": err.line_number,
                    "col": err.col,
                    "end_col": err.end_col,
                    "code": err.code,
                    "severity": err.severity.lower(),
                    "message": err.message,
                }
            )

        output_data = {
            "diagnostics": json_output,
            "summary": {
                "total_lines": result.total_lines,
                "fixed": result.fixed_count,
                "time_sec": round(elapsed, 3),
            },
        }
        json_str = json.dumps(output_data, indent=2, ensure_ascii=False)
        if args.output_file:
            with open(args.output_file, "w", encoding="utf-8") as f:
                f.write(json_str)
            console.print(f"[bold green]✔ Report saved to {args.output_file}[/bold green]")
        else:
            print(json_str)
        error_count = sum(1 for e in active_diagnostics if e.severity == "ERROR")
        sys.exit(1 if error_count > 0 else 0)

    # P0-1: --output-file для text-формата.
    # Раньше --output-file молча игнорировался: rich Console пишет в sys.stdout,
    # а файловый перехват был только для JSON/SARIF веток. Решение — временно
    # подменить глобальную `console` на файловую через context manager, чтобы
    # весь text-вывод (карточки, таблицы, tsundere-баннеры, итоговая строка)
    # пошёл в файл. Используем _exit_with_output_redirect вместо sys.exit,
    # чтобы SystemExit корректно отработал через __exit__ и закрыл файл.
    output_redirect = (
        _replace_console(_make_file_console(args))
        if (args.output_file and args.output_format == "text")
        else _null_redirect()
    )

    # UX-15: --check и --diff обработка после analyzer.run.
    # Выводим результат dry-run и выходим ДО обычного вывода diagnostics.
    if args.check:
        if result.fixable_count > 0:
            console.print(
                f"[bold yellow]Would fix {result.fixable_count} issue(s) in {result.file_count} file(s).[/bold yellow]"
            )
            console.print("[dim]Run with --fix to apply these changes.[/dim]")
            sys.exit(1)
        else:
            console.print("[bold green]No fixable issues found.[/bold green]")
            sys.exit(0)

    if args.diff:
        import difflib

        if not diff_collector:
            console.print("[bold green]No changes would be applied by --fix.[/bold green]")
            sys.exit(0)

        console.print(f"[bold cyan]--fix would change {len(diff_collector)} file(s):[/bold cyan]\n")
        has_changes = False
        for file_path, new_content in diff_collector.items():
            try:
                with _real_open(file_path, "r", encoding="utf-8") as f:
                    original = f.read()
            except OSError:
                continue
            if original == new_content:
                continue
            has_changes = True
            diff = difflib.unified_diff(
                original.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=file_path,
                tofile=file_path + " (after --fix)",
            )
            sys.stdout.writelines(diff)
            sys.stdout.write("\n")

        if has_changes:
            console.print(
                f"[bold yellow]\n{result.fixable_count} fixable issue(s) across {len(diff_collector)} file(s).[/bold yellow]"
            )
            console.print("[dim]Run with --fix to apply these changes.[/dim]")
            sys.exit(1)
        else:
            console.print("[bold green]No changes would be applied by --fix.[/bold green]")
            sys.exit(0)

    with output_redirect:
        # 0 ПРОБЛЕМ
        if not active_diagnostics:
            if is_tsundere:
                console.print(
                    f"[bold magenta](⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄) «{TSUNDERE_UI['clean_title']}»[/bold magenta]\n"
                    f"[dim]{TSUNDERE_UI['clean_sub'].format(lines=result.total_lines, elapsed=elapsed)}[/dim]"
                )
            else:
                msg = f"[bold green]✔ All clean![/bold green] Scanned [bold]{result.total_lines:,}[/bold] lines across [bold]{result.file_count}[/bold] file(s) in [cyan]{elapsed:.3f}s[/cyan]."
                if result.fixed_count > 0:
                    msg += f" [bold cyan]({result.fixed_count} fix(es) applied!)[/bold cyan]"
                console.print(msg)
            _exit_with_output_redirect(args, 0)

        # ВЫВОД КАРТОЧЕК С УЧЕТОМ SEVERITY
        displayed = active_diagnostics[:max_errors]
        for err in displayed:
            text = Text()
            text.append(f"{err.file_path}:{err.line_number}\n", style="bold cyan")
            text.append(f"  {err.line_number} │ ", style="dim")
            text.append(f"{err.line_content}\n\n", style="bright_white")

            if is_tsundere and err.code in TSUNDERE_FLAVORS:
                text.append(f"  {TSUNDERE_FLAVORS[err.code]}\n", style="bold italic #ff79c6")

            badge_style, border_style = SEVERITY_STYLES.get(err.severity, ("bold red", "red dim"))
            text.append(f"  [{err.severity}] {err.code}: ", style=badge_style)
            text.append(f"{err.message}", style="bright_white")

            panel_border = "magenta dim" if is_tsundere else border_style
            console.print(Panel(text, border_style=panel_border, expand=False))

        if len(active_diagnostics) > max_errors:
            hidden = len(active_diagnostics) - max_errors
            console.print(
                f"\n[dim]... and {hidden} more diagnostic(s) omitted (use --max-errors to show more).[/dim]\n"
            )

        # СВОДНАЯ ТАБЛИЦА С УРОВНЯМИ СТРОГОСТИ
        counts = Counter((e.code, e.severity) for e in active_diagnostics)
        table = Table(
            title="Diagnostics Summary" if not is_tsundere else TSUNDERE_UI["summary"],
            border_style="dim",
        )
        table.add_column("Rule", style="bold cyan")
        table.add_column("Severity", justify="center")
        table.add_column("Count", justify="right", style="bold white")

        for (code, severity), count in sorted(counts.items()):
            sev_badge = Text(severity, style=SEVERITY_STYLES.get(severity, ("white", ""))[0])
            table.add_row(code, sev_badge, str(count))

        console.print(table)

        if result.fixed_count > 0:
            if is_tsundere:
                console.print(
                    f"\n[bold magenta](//∇//) «{TSUNDERE_UI['fixed'].format(count=result.fixed_count)}»[/bold magenta]"
                )
            else:
                console.print(
                    f"\n[bold green]✔ Automatically fixed {result.fixed_count} error(s)![/bold green]"
                )
        elif result.fixable_count > 0 and not args.fix:
            if is_tsundere:
                console.print(
                    f"\n[dim magenta][*] {TSUNDERE_UI['fixable'].format(count=result.fixable_count)}[/dim magenta]"
                )
            else:
                console.print(
                    f"\n[dim][*] {result.fixable_count} fixable with the --fix option[/dim]"
                )

        if hidden_info_count > 0:
            if is_tsundere:
                console.print(
                    f"\n[dim magenta](¬_¬ ) «{TSUNDERE_UI['info_omitted'].format(count=hidden_info_count)}»[/dim magenta]"
                )
            else:
                console.print(
                    f"\n[dim]ℹ {hidden_info_count} info notice(s) omitted (use --info to view them).[/dim]"
                )

        # Подсчет по категориям
        error_count = sum(1 for e in active_diagnostics if e.severity == "ERROR")
        warn_count = sum(1 for e in active_diagnostics if e.severity == "WARNING")
        hint_count = sum(1 for e in active_diagnostics if e.severity == "HINT")
        info_count = sum(1 for e in active_diagnostics if e.severity == "INFO")

        summary_parts = []
        if error_count:
            summary_parts.append(f"[bold red]{error_count} error(s)[/bold red]")
        if warn_count:
            summary_parts.append(f"[bold yellow]{warn_count} warning(s)[/bold yellow]")
        if hint_count:
            summary_parts.append(f"[bold cyan]{hint_count} hint(s)[/bold cyan]")
        if info_count:
            summary_parts.append(f"[bold blue]{info_count} info notice(s)[/bold blue]")

        summary_str = ", ".join(summary_parts)

        if is_tsundere:
            if error_count > 0:
                console.print(
                    f"\n[bold magenta](╬ Ò﹏Ó) {TSUNDERE_UI['errors'].format(summary_str=summary_str, elapsed=elapsed)}[/bold magenta]"
                )
            else:
                console.print(
                    f"\n[bold magenta](¬_¬ ) {TSUNDERE_UI['warnings'].format(summary_str=summary_str, elapsed=elapsed)}[/bold magenta]"
                )
        else:
            status_icon = (
                "[bold red]✖[/bold red]" if error_count > 0 else "[bold yellow]⚠[/bold yellow]"
            )
            console.print(
                f"\n{status_icon} Found {summary_str} "
                f"across [bold]{result.file_count}[/bold] file(s) ({result.total_lines:,} lines) "
                f"in [cyan]{elapsed:.3f}s[/cyan]."
            )

        # UX-15: --exit-zero форсирует exit 0 даже при ошибках (для non-blocking CI).
        _exit_with_output_redirect(args, 0 if args.exit_zero else (1 if error_count > 0 else 0))


if __name__ == "__main__":
    main()
