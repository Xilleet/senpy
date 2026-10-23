from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter

import tomllib
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from senpy.analyzer import SenpyAnalyzer
from senpy.constants import IGNORED_DIRS
from senpy.rpa import safe_load_rpa_index

console = Console()

SENPY_CACHE_DIR = os.path.expanduser("~/.senpy/tools/unrpyc")
UNRPYC_GITHUB_ZIP = "https://github.com/CensoredUsername/unrpyc/archive/refs/heads/master.zip"


def _is_russian_os() -> bool:
    """Определяет, русский ли интерфейс у ОС пользователя."""
    if "ru" in os.environ.get("LANG", "").lower():
        return True
    if os.name == "nt":
        with contextlib.suppress(AttributeError, OSError):
            return ctypes.windll.kernel32.GetUserDefaultUILanguage() == 1049
    return False


IS_RU = _is_russian_os()

TSUNDERE_FLAVORS = {
    "RPY001": "(╯°□°)╯︵ ┻━┻ «Ты посмел вставить табуляцию вместо пробелов?! Ren'Py такое не прощает, ленивый бака!»" if IS_RU else "(╯°□°)╯︵ ┻━┻ «Tabs instead of spaces in indentation?! Ren'Py does not forgive this, lazy baka!»",
    "RPY002": "(｀ε´ ) «Ты копировал текст прямо из Word?! Эти фигурные кавычки сломают весь код, бака!»" if IS_RU else "(｀ε´ ) «Did you paste from Word?! Smart quotes break Python code, baka!»",
    "RPY206": "(╬ Ò﹏Ó) «Ты вызвал функцию в action со скобками?! Она сработает ещё до клика, прямо при открытии экрана, идиот!»" if IS_RU else "(╬ Ò﹏Ó) «Calling a function directly in action?! It executes during screen render, not on click! Use Function(), dummy!»",
    "RPY307": "(╬ Ò﹏Ó) «Эта метка уже была объявлена раньше! Игра упадёт на старте из-за дубликата, слепой!»" if IS_RU else "(╬ Ò﹏Ó) «Duplicate label declaration! The game will crash on startup, blind idiot!»",
    "RPY308": "(；￣Д￣) «Сюжет в этой метке никуда не уходит и просто провалится в следующую сцену! Поставь return или jump, бестолочь!»" if IS_RU else "(；￣Д￣) «This label doesn't end with jump or return, it falls right through into the next scene, dummy!»",
    "RPY503": "(눈_눈) «Этот файл ассета нигде не используется! Зря только место на диске жрёт, бака!»" if IS_RU else "(눈_눈) «Unused media asset found! It's just wasting disk space and build size, baka!»",
    "RPY101": "(¬_¬ ) «Бака! Ты используешь переменную в диалоге, но даже не объявил её! О чем ты вообще думал?!»" if IS_RU else "(¬_¬ ) «B-Baka! You used a variable in dialogue without declaring it! What were you thinking?!»",
    "RPY102": "(╬ Ò﹏Ó) «Ты делаешь += к переменной, которой НЕТ! Это же чистый NameError при запуске, идиот!»" if IS_RU else "(╬ Ò﹏Ó) «You're doing += to a variable that DOESN'T EXIST! That's a guaranteed NameError, idiot!»",
    "RPY103": "( ﾟдﾟ) «Ты вставил в условие if переменную из воздуха! Игра вылетит, бестолочь!»" if IS_RU else "( ﾟдﾟ) «You put a phantom variable in an if-condition! The game will crash, dummy!»",
    "RPY104": "(>_< ) «Создал переменную на лету без default?! Сохранения у игроков сломаются после патча, дурак!»" if IS_RU else "(>_< ) «Created a variable on the fly without a default?! You'll break player save files on the next patch, fool!»",
    "RPY105": "(╬ Ò﹏Ó) «Ты меняешь переменную из define?! define — это КОНСТАНТА! Для меняющихся переменных есть default, идиот!»" if IS_RU else "(╬ Ò﹏Ó) «You mutated a variable from define?! define is for CONSTANTS! Use default for mutable state, idiot!»",
    "RPY106": "(╬ Ò﹏Ó) «Ты импортировал стандартный random?! Откат назад и сохранения развалятся на куски, бестолочь! Используй renpy.random!»" if IS_RU else "(╬ Ò﹏Ó) «You imported standard random?! Rollback and save files will fall apart, dummy! Use renpy.random!»",
    "RPY306": "(；￣Д￣) «Ты сделал call на метку, но пути к return не видно! Убедись, что сюжет не утечёт в чужие сцены!»" if IS_RU else "(；￣Д￣) «You called a label, but no clear return path was found! Make sure control flow doesn't bleed out!»",
    "RPY504": "(눈_눈) «Эта картинка переопределяет или дублирует ранее объявленную! Надеюсь, ты сделал это намеренно, бака!»" if IS_RU else "(눈_눈) «This image overrides or duplicates an earlier declaration! I hope that was intentional, genius!»",
    "RPY203": "(눈_눈) «Кнопка без действия action?! И на что игрок нажимать будет, на пустоту?!»" if IS_RU else "(눈_눈) «A button without an action?! What is the player supposed to click on, thin air?!»",
    "RPY204": "( ﾟдﾟ) «Экран, который ты вызываешь, вообще не существует! Куда ты собрался переключать игрока, идиот?!»" if IS_RU else "( ﾟдﾟ) «The screen you are calling does not exist! Where are you trying to switch the player to, dummy?!»",
    "RPY502": "(￣︿￣) «Спрайт или фон не найден! Персонаж растворится в воздухе прямо посреди сцены, слепой!»" if IS_RU else "(￣︿￣) «Sprite or background not found! The character will vanish into thin air, blind dummy!»",
    "RPY205": "(╯°□°)╯︵ ┻━┻ «Ты впихнул Python-цикл for/while прямо в экран?! UI будет лагать как не в себя, дурак!»" if IS_RU else "(╯°□°)╯︵ ┻━┻ «A Python for/while loop inside a screen?! The UI is going to lag horribly, fool!»",
    "RPY305": "(｀ε´ ) «Ты забыл экранировать кавычки внутри реплики! Поставь слэш \\\", иначе игра просто упадет!»" if IS_RU else "(｀ε´ ) «Unescaped quotes inside dialogue! Escape them with \\\", otherwise the game crashes!»",
    "RPY403": "(￣︿￣) «Условие всегда False! Этот кусок сюжета вообще НИКОГДА не выполнится, гений!»" if IS_RU else "(￣︿￣) «Condition is always False! This branch will NEVER execute, genius!»",
    "RPY402": "(；￣Д￣) «Ты создал пункт в меню, но внутри пусто?! Сюжет просто провалится вниз, бестолочь!»" if IS_RU else "(；￣Д￣) «You made a menu choice but left it completely empty?! The story will just fall through, dummy!»",
    "RPY201": "(╯°□°)╯︵ ┻━┻ «Ты меняешь переменную ПРЯМО ВНУТРИ ЭКРАНА?! Экраны так не работают, тупица!»" if IS_RU else "(╯°□°)╯︵ ┻━┻ «Mutating variables DIRECTLY INSIDE A SCREEN?! Screens don't work like that, dummy!»",
    "RPY202": "(눈_눈) «Экран читает переменную без default! В главном меню игра сразу рухнет, гений!»" if IS_RU else "(눈_눈) «A screen is reading a variable without a default! It's going to crash right in the main menu, genius!»",
    "RPY301": "(；￣Д￣) «Открыл тег и забыл закрыть?! Весь дальнейший текст игры поплывет, глаза б мои тебя не видели!»" if IS_RU else "(；￣Д￣) «Opened a text tag and forgot to close it?! The whole game's text is going to bleed, I can't even look at it!»",
    "RPY302": "( ﾟдﾟ) «Прыжок на метку, которой ВООБЩЕ НЕТ?! Куда ты собрался прыгать, в пустоту?!»" if IS_RU else "( ﾟдﾟ) «Jumping to a label that DOES NOT EXIST?! Where are you jumping to, the void?!»",
    "RPY303": "(￣︿￣) «Не вижу прямых переходов на метку... Надеюсь, ты вызываешь её через динамический роутер, а не просто забросил!»" if IS_RU else "(￣︿￣) «No static references to this label... I hope you're calling it dynamically, and didn't just abandon it!»",
    "RPY304": "(｀ε´ ) «Что это за цвет такой?! Ты даже в hex-кодах умудрился опечататься!»" if IS_RU else "(｀ε´ ) «What kind of color is that?! You even managed to make a typo in hex codes!»",
    "RPY401": "(눈_눈) «В одном пункте меню ты переменную дал, а во втором забыл?! Выберут второй — и игра крашнется!»" if IS_RU else "(눈_눈) «You defined a variable in one menu choice but forgot it in another?! They pick the second one and it crashes!»",
    "RPY501": "(￣︿￣) «Музыка не найдена! В этой сцене будет гробовая тишина, глупый!»" if IS_RU else "(￣︿￣) «Music file not found! There will be dead silence in this scene, stupid!»",
    "RPY601": "(╬ Ò﹏Ó) «Ты сломал переменную в переводе! Оригинал ждёт [var], а у тебя опечатка! Игра вылетит с KeyError, идиот!»" if IS_RU else "(╬ Ò﹏Ó) «Variable mismatch in translation! The original expects [var], but you made a typo! The game will crash with KeyError, dummy!»",
    "RPY602": "(；￣Д￣) «Теги форматирования в переводе не совпадают с оригиналом! Текст игры поплывёт, бестолочь!»" if IS_RU else "(；￣Д￣) «Formatting tags in translation don't match the original! Text styling will break, idiot!»",
    "RPY603": "(￣︿￣) «Ты оставил строку перевода пустой! У игроков там будет пустота вместо текста!»" if IS_RU else "(￣︿￣) «You left the translation string empty! Players will see blank air instead of text!»",
    "RPY107": "(눈_눈) «Ты используешь замшелую функцию из каменного века Ren'Py! Обнови код на современный аналог, дед!»" if IS_RU else "(눈_눈) «Using an obsolete Ren'Py function from the stone age! Update your code to modern APIs, boomer!»",
}

TSUNDERE_UI = {
    "intro": "П-подумаешь! Сканирую твою директорию: {path}... Н-не то чтобы мне был интересен твой сценарий, бака!" if IS_RU else "H-Hmph! Scanning your directory: {path}... I-It's not like I'm interested in your script, baka!",
    "clean_title": "Н-не то чтобы мне нравился твой сценарий... но сюжетных дыр и крашей я не нашла, бака!" if IS_RU else "I-It's not like I like your script... but I didn't find any plot holes or crashes, baka!",
    "clean_sub": "Проверено {lines:,} строк за {elapsed:.3f}с. Д-доволен?!" if IS_RU else "Checked {lines:,} lines in {elapsed:.3f}s. A-Are you happy now?!",
    "summary": "Твои позорные ошибки" if IS_RU else "Your shameful mistakes",
    "fixed": "Я... я закрыла за тобой {count} открытых ошибок! Н-но не думай, что ты мне нравишься, идиот!" if IS_RU else "I... I closed {count} open tags for you! B-But don't think I like you or anything, idiot!",
    "fixable": "Там есть {count} ошибок, которые я могла бы починить за тебя через --fix... если вежливо попросишь, бака!" if IS_RU else "There are {count} tags I could fix for you with --fix... if you ask nicely, baka!",
    "errors": "Найдено {summary_str}! Иди и исправляй, я не буду играть в такую сломанную новеллу! ({elapsed:.3f}s)" if IS_RU else "Found {summary_str}! Go fix them, I'm not playing such a broken novel! ({elapsed:.3f}s)",
    "warnings": "Найдено {summary_str}... Жить можно, но я за тобой слежу, бака! ({elapsed:.3f}s)" if IS_RU else "Found {summary_str}... It's playable, but I'm watching you, baka! ({elapsed:.3f}s)",
    "defaults_generated": "Я... я сгенерировала за тебя файл {path} с {count} переменными! Т-только не думай, что мне не всё равно на твои сохранения, бака!" if IS_RU else "I... I generated {path} with {count} variables for you! D-Don't think I care about your save files, baka!",
    "info_omitted": "Я заметила ещё {count} мелких нюансов, но не покажу их, пока не попросишь через --info, бака!" if IS_RU else "I noticed {count} minor things, but I won't show them unless you ask with --info, baka!",
}

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


def download_unrpyc() -> list[str] | None:
    console.print("[bold cyan]Downloading unrpyc from GitHub...[/bold cyan]")
    os.makedirs(SENPY_CACHE_DIR, exist_ok=True)
    zip_path = os.path.join(SENPY_CACHE_DIR, "unrpyc.zip")

    try:
        req = urllib.request.Request(UNRPYC_GITHUB_ZIP, headers={"User-Agent": "Senpy-Linter"})
        with urllib.request.urlopen(req) as resp, open(zip_path, "wb") as out:
            shutil.copyfileobj(resp, out)

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(SENPY_CACHE_DIR)

        with contextlib.suppress(OSError):
            os.remove(zip_path)

        console.print("[bold green]✔ Successfully downloaded and installed unrpyc to cache![/bold green]\n")
        return find_unrpyc_executable(None, None, auto_download=False)
    except (urllib.error.URLError, zipfile.BadZipFile, OSError) as e:
        console.print(f"[bold red]Failed to download unrpyc:[/bold red] {e}\n")
        return None


def find_unrpyc_executable(custom_path: str | None, project_path: str | None, auto_download: bool = True) -> list[str] | None:
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
            [sys.executable, "-m", "unrpyc", "--help"],
            capture_output=True,
            check=False
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
            ans = input("Would you like Senpy to automatically download unrpyc from GitHub? [Y/n]: ").strip().lower()
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

    with contextlib.suppress(Exception), open(rpa_path, "rb") as f:
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

    temp_rpyc_files = []
    for i, f in enumerate(orphans, 1):
        base_name = os.path.basename(f)
        dest = os.path.join(temp_dir, base_name)
        if os.path.exists(f) and os.path.normcase(os.path.abspath(f)) != os.path.normcase(os.path.abspath(dest)):
            shutil.copy2(f, dest)
        temp_rpyc_files.append(dest)
        msg = f"\r[Подготовка] {i}/{total} ({base_name[:25]})"
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
                        curr_file = "готово" if done == total else "..."
                    msg = f"\r[Декомпиляция] {done}/{total} ({curr_file[:25]})"
                    print(msg.ljust(75), end="", flush=True)
        process.wait()
        print()
    except (subprocess.SubprocessError, OSError) as e:
        console.print(f"[bold red]Ошибка декомпиляции:[/bold red] {e}")

    decompiled_rpy = []
    for root, _, files in os.walk(temp_dir):
        for file in files:
            if file.endswith(".rpy"):
                decompiled_rpy.append(os.path.join(root, file))

    console.print(f"[bold green]✔ Успешно декомпилировано {len(decompiled_rpy)} файл(ов) в песочницу![/bold green]\n")
    return decompiled_rpy


def main():

    parser = argparse.ArgumentParser(
        prog="senpy",
        description="Notice me, Senpy! Fast semantic linter & LSP for Ren'Py.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # 1. Позиционный аргумент: путь к проекту
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the Ren'Py project or 'game' directory (default: current dir)"
    )

    # 2. Справка и документация по правилам
    g_rules = parser.add_argument_group("Rules & Documentation")
    g_rules.add_argument(
        "--rules",
        action="store_true",
        help="List all 33 available Senpy rules and their descriptions"
    )
    g_rules.add_argument(
        "--rule",
        metavar="CODE",
        help="Show detailed explanation and code examples for a specific rule (e.g. --rule RPY104)"
    )

    # 3. Настройки анализа и автофикса
    g_lint = parser.add_argument_group("Analysis & Autofix")
    g_lint.add_argument(
        "--fix",
        action="store_true",
        help="Automatically fix safe errors (unclosed tags RPY301, smart quotes RPY002, tabs RPY001)"
    )
    g_lint.add_argument(
        "--generate-defaults",
        action="store_true",
        help="Generate 'senpy_defaults.rpy' containing 'default' declarations for all RPY104 variables"
    )
    g_lint.add_argument(
        "--errors-only",
        action="store_true",
        help="Show only critical ERRORs, hiding WARNINGs and INFO notices"
    )
    g_lint.add_argument(
        "--info",
        action="store_true",
        help="Display informational notices (e.g. unreferenced labels RPY303)"
    )
    g_lint.add_argument(
        "--ignore",
        nargs="+",
        metavar="CODE",
        default=None,
        help="Ignore specific error codes (e.g. --ignore RPY104 RPY101)"
    )
    g_lint.add_argument(
        "--max-errors",
        type=int,
        metavar="NUM",
        default=None,
        help="Maximum errors to display in terminal (default: 50)"
    )
    g_lint.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable disk caching (.senpy_cache)"
    )
    g_lint.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear project cache directory (.senpy_cache) and exit"
    )

    # 4. Визуализация и форматы отчётов
    g_export = parser.add_argument_group("Visualization & Reports")
    g_export.add_argument(
        "--export-html",
        metavar="FILE",
        help="Generate a standalone HTML report with an interactive story map and diagnostics"
    )
    g_export.add_argument(
        "--graph",
        action="store_true",
        help="Generate a Mermaid.js diagram of the story flow and label transitions"
    )
    g_export.add_argument(
        "--graph-file",
        metavar="FILE",
        help="Save the Mermaid.js story diagram directly to a file (e.g. story.md)"
    )
    g_export.add_argument(
        "--output-format",
        "--format",
        dest="output_format",
        choices=["text", "json", "sarif"],
        default="text",
        help="Output format: 'text' (default), 'json' for VS Code, or 'sarif' for GitHub Actions"
    )
    g_export.add_argument(
        "--output-file",
        metavar="FILE",
        help="Save report to a specific file (e.g. report.json or report.txt)"
    )

    # 5. Декомпиляция и интеграции
    g_tools = parser.add_argument_group("Tools & Integrations")
    g_tools.add_argument(
        "--lsp",
        action="store_true",
        help="Run Senpy as a Language Server (LSP) for editors like VS Code / Neovim"
    )
    g_tools.add_argument(
        "--decompile",
        action="store_true",
        help="Automatically decompile orphaned .rpyc files into a temporary sandbox"
    )
    g_tools.add_argument(
        "--unrpyc",
        metavar="PATH",
        help="Custom path to unrpyc.py or unrpyc executable"
    )
    g_tools.add_argument(
        "--tsundere",
        action="store_true",
        help="B-Baka! It's not like I want to check your visual novel!"
    )

    args = parser.parse_args() 
    
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

    if args.clear_cache:
        from senpy.cache import CacheManager
        cm = CacheManager(args.path)
        if cm.clear():
            console.print(f"[bold green]✔ Successfully cleared cache directory: {cm.cache_dir}[/bold green]")
        else:
            console.print("[dim]Cache directory does not exist, nothing to clear.[/dim]")
        sys.exit(0)

    is_tsundere = args.tsundere or config.get("tsundere", False)

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

    # 2. Умная работа с RPA: ищем скрипты в архивах (для релизных сборок и модов)
    rpa_files = []
    for root, dirs, files in os.walk(args.path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for f in files:
            if f.lower().endswith(".rpa"):
                rpa_files.append(os.path.join(root, f))
    
    for rpa in rpa_files:
        rpa_base = os.path.splitext(os.path.basename(rpa))[0].lower()
        if any(term in rpa_base for term in ("script", "archive", "data", "game", "code")) or not raw_orphans:
            extracted = extract_scripts_from_rpa(rpa, rpa_sandbox)
            for item in extracted:
                if item.endswith(".rpy"):
                    extra_rpy_files.append(item)
                elif item.endswith(".rpyc"):
                    raw_orphans.append(item)

    # 3. Проверяем кэш декомпиляции для всех .rpyc (с диска и из .rpa)
    for rpyc in raw_orphans:
        cached_rpy = os.path.join(decomp_sandbox, os.path.basename(rpyc)[:-1])
        if os.path.exists(cached_rpy) and os.path.getmtime(cached_rpy) >= os.path.getmtime(rpyc):
            if cached_rpy not in extra_rpy_files:
                extra_rpy_files.append(cached_rpy)
        else:
            if rpyc not in orphaned_rpyc:
                orphaned_rpyc.append(rpyc)

    # 4. Если появились новые/изменённые .rpyc — декомпилируем в песочницу
    if orphaned_rpyc:
        should_decompile = auto_decompile
        is_interactive = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
        if not should_decompile and is_interactive and not (args.graph or args.graph_file):
            console.print(
                f"[bold yellow]Found {len(orphaned_rpyc)} compiled .rpyc file(s) without source code.[/bold yellow]"
            )
            try:
                answer = input("Decompile them into a sandbox for analysis? [y/N]: ").strip().lower()
                should_decompile = answer in ("y", "yes")
            except (EOFError, KeyboardInterrupt):
                should_decompile = False

        if should_decompile:
            custom_unrpyc = args.unrpyc or config.get("unrpyc_path")
            unrpyc_cmd = find_unrpyc_executable(custom_unrpyc, args.path, auto_download=is_interactive)
            if unrpyc_cmd:
                new_decompiled = decompile_to_sandbox(orphaned_rpyc, unrpyc_cmd, decomp_sandbox)
                for f_rpy in new_decompiled:
                    if f_rpy not in extra_rpy_files:
                        extra_rpy_files.append(f_rpy)

    is_quiet_mode = bool(args.graph or args.graph_file or args.output_format in ("json", "sarif"))

    if not is_quiet_mode:
        if is_tsundere:
            console.print(
                f"[bold magenta](¬_¬ ) «{TSUNDERE_UI['intro'].format(path=args.path)}»[/bold magenta]\n"
            )
        else:
            console.print(f"[bold cyan]Scanning directory:[/bold cyan] {args.path}...\n")

    start_time = time.perf_counter()
    analyzer = SenpyAnalyzer(args.path, extra_files=extra_rpy_files, fix=args.fix, no_cache=args.no_cache)
    result = analyzer.run(quiet=is_quiet_mode)
    elapsed = time.perf_counter() - start_time
    if args.export_html:
        from senpy.html_report import generate_html_report
        # Отфильтруем предварительно диагностики как для терминала
        active_diagnostics = [
            e for e in result.diagnostics
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
            out_path=args.export_html
        )
        if is_tsundere:
            console.print(f"[bold magenta](//∇//) «Я... я сгенерировала HTML отчёт в [bold]{args.export_html}[/bold]! Изучай свои сюжетные дыры, бака!»[/bold magenta]\n")
        else:
            console.print(f"[bold green]✔ Autonomous HTML report saved to [bold]{args.export_html}[/bold][/bold green]\n")
    if args.graph or args.graph_file:
        graph_content = analyzer.export_graph()
        if args.graph_file:
            with open(args.graph_file, "w", encoding="utf-8") as f:
                f.write(graph_content)
        if is_tsundere:
            console.print(f"\n[bold magenta](//∇//) «Я... я нарисовала карту твоих переходов в [bold]{args.graph_file}[/bold]! Н-но не думай, что мне интересно, куда пойдёт твой герой, бака!»[/bold magenta]\n")
        else:
            console.print(f"\n[bold green]✔ Story flow graph saved to [bold]{args.graph_file}[/bold]![/bold green]\n")
        sys.exit(0)

    # Генерация файла senpy_defaults.rpy
    if args.generate_defaults:
        out_file, gen_count = analyzer.generate_defaults_file()
        if gen_count > 0:
            if is_tsundere:
                console.print(f"\n[bold magenta](//∇//) «{TSUNDERE_UI['defaults_generated'].format(path=out_file, count=gen_count)}»[/bold magenta]\n")
            else:
                console.print(f"\n[bold green]✔ Successfully generated [bold]{out_file}[/bold] with [bold]{gen_count}[/bold] default declaration(s)![/bold green]\n")
        else:
            console.print("\n[bold green]✔ All variables are already properly declared via 'default'![/bold green]\n")
        sys.exit(0)

    # Фильтруем ошибки по кодам из --ignore и --errors-only
    hidden_info_count = sum(
        1 for e in result.diagnostics
        if e.severity == "INFO" and e.code not in ignored_codes and not args.info
    )
    active_diagnostics = [
        e for e in result.diagnostics
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
            json_output.append({
                "file": err.file_path,
                "line": err.line_number,
                "col": err.col,
                "end_col": err.end_col,
                "code": err.code,
                "severity": err.severity.lower(),
                "message": err.message
            })

        output_data = {
            "diagnostics": json_output,
            "summary": {
                "total_lines": result.total_lines,
                "fixed": result.fixed_count,
                "time_sec": round(elapsed, 3)
            }
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
        sys.exit(0)

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
        console.print(f"\n[dim]... and {hidden} more diagnostic(s) omitted (use --max-errors to show more).[/dim]\n")

    # СВОДНАЯ ТАБЛИЦА С УРОВНЯМИ СТРОГОСТИ
    counts = Counter((e.code, e.severity) for e in active_diagnostics)
    table = Table(title="Diagnostics Summary" if not is_tsundere else TSUNDERE_UI['summary'], border_style="dim")
    table.add_column("Rule", style="bold cyan")
    table.add_column("Severity", justify="center")
    table.add_column("Count", justify="right", style="bold white")

    for (code, severity), count in sorted(counts.items()):
        sev_badge = Text(severity, style=SEVERITY_STYLES.get(severity, ("white", ""))[0])
        table.add_row(code, sev_badge, str(count))

    console.print(table)

    if result.fixed_count > 0:
        if is_tsundere:
            console.print(f"\n[bold magenta](//∇//) «{TSUNDERE_UI['fixed'].format(count=result.fixed_count)}»[/bold magenta]")
        else:
            console.print(f"\n[bold green]✔ Automatically fixed {result.fixed_count} error(s)![/bold green]")
    elif result.fixable_count > 0 and not args.fix:
        if is_tsundere:
            console.print(f"\n[dim magenta][*] {TSUNDERE_UI['fixable'].format(count=result.fixable_count)}[/dim magenta]")
        else:
            console.print(f"\n[dim][*] {result.fixable_count} fixable with the --fix option[/dim]")

    if hidden_info_count > 0:
        if is_tsundere:
            console.print(f"\n[dim magenta](¬_¬ ) «{TSUNDERE_UI['info_omitted'].format(count=hidden_info_count)}»[/dim magenta]")
        else:
            console.print(f"\n[dim]ℹ {hidden_info_count} info notice(s) omitted (use --info to view them).[/dim]")

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
            console.print(f"\n[bold magenta](╬ Ò﹏Ó) {TSUNDERE_UI['errors'].format(summary_str=summary_str, elapsed=elapsed)}[/bold magenta]")
        else:
            console.print(f"\n[bold magenta](¬_¬ ) {TSUNDERE_UI['warnings'].format(summary_str=summary_str, elapsed=elapsed)}[/bold magenta]")
    else:
        status_icon = "[bold red]✖[/bold red]" if error_count > 0 else "[bold yellow]⚠[/bold yellow]"
        console.print(
            f"\n{status_icon} Found {summary_str} "
            f"across [bold]{result.file_count}[/bold] file(s) ({result.total_lines:,} lines) "
            f"in [cyan]{elapsed:.3f}s[/cyan]."
        )

    sys.exit(1 if error_count > 0 else 0)


if __name__ == "__main__":
    main()