from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
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

console = Console()

SENPY_CACHE_DIR = os.path.expanduser("~/.senpy/tools/unrpyc")
UNRPYC_GITHUB_ZIP = "https://github.com/CensoredUsername/unrpyc/archive/refs/heads/master.zip"

def _is_russian_os() -> bool:
    """Определяет, русский ли интерфейс у ОС пользователя."""
    if "ru" in os.environ.get("LANG", "").lower():
        return True
    if os.name == "nt":
        # Ловим конкретные ошибки доступа к системным библиотекам
        with contextlib.suppress(AttributeError, OSError):
            # 1049 (0x0419) — это код русского языка в Windows
            return ctypes.windll.kernel32.GetUserDefaultUILanguage() == 1049
    return False

IS_RU = _is_russian_os()

TSUNDERE_FLAVORS = {
    "RPY101": "(¬_¬ ) «Бака! Ты используешь переменную в диалоге, но даже не объявил её! О чем ты вообще думал?!»" if IS_RU else "(¬_¬ ) «B-Baka! You used a variable in dialogue without declaring it! What were you thinking?!»",
    "RPY102": "(╬ Ò﹏Ó) «Ты делаешь += к переменной, которой НЕТ! Это же чистый NameError при запуске, идиот!»" if IS_RU else "(╬ Ò﹏Ó) «You're doing += to a variable that DOESN'T EXIST! That's a guaranteed NameError, idiot!»",
    "RPY103": "( ﾟдﾟ) «Ты вставил в условие if переменную из воздуха! Игра вылетит, бестолочь!»" if IS_RU else "( ﾟдﾟ) «You put a phantom variable in an if-condition! The game will crash, dummy!»",
    "RPY104": "(>_< ) «Создал переменную на лету без default?! Сохранения у игроков сломаются после патча, дурак!»" if IS_RU else "(>_< ) «Created a variable on the fly without a default?! You'll break player save files on the next patch, fool!»",
    "RPY105": "(╬ Ò﹏Ó) «Ты меняешь переменную из define?! define — это КОНСТАНТА! Для меняющихся переменных есть default, идиот!»" if IS_RU else "(╬ Ò﹏Ó) «You mutated a variable from define?! define is for CONSTANTS! Use default for mutable state, idiot!»",
    "RPY106": "(╬ Ò﹏Ó) «Ты импортировал стандартный random?! Откат назад и сохранения развалятся на куски, бестолочь! Используй renpy.random!»" if IS_RU else "(╬ Ò﹏Ó) «You imported standard random?! Rollback and save files will fall apart, dummy! Use renpy.random!»",
    "RPY306": "(；￣Д￣) «Ты сделал call на метку, но забыл поставить return! Сюжет провалится дальше в чужие сцены!»" if IS_RU else "(；￣Д￣) «You called a label without a return statement! The story will bleed into unrelated scenes!»",
    "RPY504": "(눈_눈) «Ты объявил одну и ту же картинку дважды! Одна молча сотрет другую, гений!»" if IS_RU else "(눈_눈) «You declared the exact same image twice! One will silently overwrite the other, genius!»",
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
    "RPY303": "(￣︿￣) «Написал метку и ни разу на нее не сослался... Забыл про нее, да? Мертвый код!»" if IS_RU else "(￣︿￣) «Wrote a label and never referenced it... You just forgot about it, didn't you? Dead code!»",
    "RPY304": "(｀ε´ ) «Что это за цвет такой?! Ты даже в hex-кодах умудрился опечататься!»" if IS_RU else "(｀ε´ ) «What kind of color is that?! You even managed to make a typo in hex codes!»",
    "RPY401": "(눈_눈) «В одном пункте меню ты переменную дал, а во втором забыл?! Выберут второй — и игра крашнется!»" if IS_RU else "(눈_눈) «You defined a variable in one menu choice but forgot it in another?! They pick the second one and it crashes!»",
    "RPY501": "(￣︿￣) «Музыка не найдена! В этой сцене будет гробовая тишина, глупый!»" if IS_RU else "(￣︿￣) «Music file not found! There will be dead silence in this scene, stupid!»",
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
}

SEVERITY_STYLES = {
    "ERROR": ("bold red", "red dim"),
    "WARNING": ("bold yellow", "yellow dim"),
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

    if auto_download:
        console.print("[bold yellow]unrpyc was not found on your system.[/bold yellow]")
        try:
            ans = input("Would you like Senpy to automatically download unrpyc from GitHub? [Y/n]: ").strip().lower()
            if ans in ("", "y", "yes"):
                return download_unrpyc()
        except (EOFError, KeyboardInterrupt):
            pass

    return None


def decompile_to_sandbox(orphans: list[str], unrpyc_cmd: list[str], temp_dir: str) -> list[str]:
    console.print(f"[bold cyan]Decompiling {len(orphans)} file(s) into temporary sandbox...[/bold cyan]")

    temp_rpyc_files = []
    for f in orphans:
        base_name = os.path.basename(f)
        dest = os.path.join(temp_dir, base_name)
        shutil.copy2(f, dest)
        temp_rpyc_files.append(dest)

    cmd = unrpyc_cmd + ["-c"] + temp_rpyc_files
    try:
        subprocess.run(cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
        console.print(f"[bold red]Decompilation warning:[/bold red] {e}")

    decompiled_rpy = []
    for root, _, files in os.walk(temp_dir):
        for file in files:
            if file.endswith(".rpy"):
                decompiled_rpy.append(os.path.join(root, file))

    console.print(f"[bold green]✔ Successfully decompiled {len(decompiled_rpy)} file(s) to sandbox![/bold green]\n")
    return decompiled_rpy


def main():
    parser = argparse.ArgumentParser(
        prog="senpy",
        description="Notice me, Senpy! Fast semantic linter for Ren'Py."
    )
    parser.add_argument(
        "--rule",
        metavar="CODE",
        help="Show detailed explanation and code examples for a specific rule (e.g. --rule RPY104)"
    )
    parser.add_argument(
        "--rules",
        action="store_true",
        help="List all available Senpy rules and their descriptions"
    )
    parser.add_argument("path", nargs="?", default=".", help="Path to the Ren'Py project (game directory)")
    parser.add_argument(
        "--tsundere",
        action="store_true",
        help="Enable Tsundere mode. (B-Baka! It's not like I want to check your visual novel!)"
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Automatically fix safe errors (e.g. unclosed text tags RPY301)"
    )
    parser.add_argument(
        "--generate-defaults",
        action="store_true",
        help="Automatically generate 'senpy_defaults.rpy' containing 'default' declarations for all RPY104 variables."
    )
    parser.add_argument(
        "--errors-only",
        action="store_true",
        help="Show only critical ERRORs, hiding WARNINGs and INFO notices"
    )
    parser.add_argument(
        "--output-format",
        "--format",
        dest="output_format",
        choices=["text", "json"],
        default="text",
        help="Output format: 'text' (default) or 'json' for CI/LSP"
    )
    parser.add_argument(
        "--output-file",
        help="Save report to a specific file (e.g. report.json or report.txt)"
    )
    parser.add_argument(
        "--ignore",
        nargs="+",
        default=None,
        help="Ignore specific error codes (e.g. --ignore RPY104 RPY101)"
    )
    parser.add_argument(
        "--max-errors",
        type=int,
        default=None,
        help="Maximum errors to display in terminal (default: 50)"
    )
    parser.add_argument(
        "--decompile",
        action="store_true",
        help="Automatically decompile orphaned .rpyc files into a temporary sandbox"
    )
    parser.add_argument(
        "--unrpyc",
        help="Custom path to unrpyc.py or unrpyc executable"
    )
    parser.add_argument(
        "--lsp",
        action="store_true",
        help="Run Senpy as a Language Server (LSP) for editors like VS Code/Neovim"
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

    is_tsundere = args.tsundere or config.get("tsundere", False)

    cfg_ignore = set(config.get("ignore", []))
    cli_ignore = set(args.ignore) if args.ignore is not None else set()
    ignored_codes = {c.strip().upper() for c in (cli_ignore or cfg_ignore)}

    max_errors = args.max_errors or config.get("max_errors", 50)
    auto_decompile = args.decompile or config.get("decompile", False)

    orphaned_rpyc = SenpyAnalyzer.find_orphaned_rpyc(args.path)
    extra_rpy_files = []

    with tempfile.TemporaryDirectory() as temp_sandbox:
        if orphaned_rpyc:
            should_decompile = auto_decompile

            if not should_decompile:
                console.print(
                    f"[bold yellow]Found {len(orphaned_rpyc)} compiled .rpyc file(s) without source code.[/bold yellow]"
                )
                try:
                    answer = input("Decompile them into a temporary sandbox for analysis? [y/N]: ").strip().lower()
                    should_decompile = answer in ("y", "yes")
                except (EOFError, KeyboardInterrupt):
                    should_decompile = False

            if should_decompile:
                custom_unrpyc = args.unrpyc or config.get("unrpyc_path")
                unrpyc_cmd = find_unrpyc_executable(custom_unrpyc, args.path, auto_download=True)
                if not unrpyc_cmd:
                    console.print(
                        "[bold red]Decompilation skipped:[/bold red] unrpyc could not be found or downloaded.\n"
                    )
                else:
                    extra_rpy_files = decompile_to_sandbox(orphaned_rpyc, unrpyc_cmd, temp_sandbox)

        if args.output_format != "json":
            if is_tsundere:
                console.print(
                    f"[bold magenta](¬_¬ ) «{TSUNDERE_UI['intro'].format(path=args.path)}»[/bold magenta]\n"
                )
            else:
                console.print(f"[bold cyan]Scanning directory:[/bold cyan] {args.path}...\n")

        start_time = time.perf_counter()
        analyzer = SenpyAnalyzer(args.path, extra_files=extra_rpy_files, fix=args.fix)
        result = analyzer.run()
        elapsed = time.perf_counter() - start_time
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
        active_diagnostics = [
            e for e in result.diagnostics
            if e.code not in ignored_codes and (not args.errors_only or e.severity == "ERROR")
        ]
        # --- ВЫВОД В ФОРМАТЕ JSON ДЛЯ VS CODE ---
        if args.output_format == "json":
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
        # ----------------------------------------
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

            # В цундере рамка под цвет настроения, иначе по severity
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

        # Подсчет по категориям
        error_count = sum(1 for e in active_diagnostics if e.severity == "ERROR")
        warn_count = sum(1 for e in active_diagnostics if e.severity == "WARNING")
        info_count = sum(1 for e in active_diagnostics if e.severity == "INFO")

        summary_parts = []
        if error_count:
            summary_parts.append(f"[bold red]{error_count} error(s)[/bold red]")
        if warn_count:
            summary_parts.append(f"[bold yellow]{warn_count} warning(s)[/bold yellow]")
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

        # Выходим с кодом 1 ТОЛЬКО если есть критические ERROR!
        sys.exit(1 if error_count > 0 else 0)


if __name__ == "__main__":
    main()