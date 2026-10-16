from __future__ import annotations

import argparse
import contextlib
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

TSUNDERE_FLAVORS = {
    "RPY101": "(¬_¬ ) «Бака! Ты используешь переменную в диалоге, но даже не объявил её! О чем ты вообще думал?!»",
    "RPY102": "(╬ Ò﹏Ó) «Ты делаешь += к переменной, которой НЕТ! Это же чистый NameError при запуске, идиот!»",
    "RPY103": "( ﾟдﾟ) «Ты вставил в условие if переменную из воздуха! Игра вылетит, бестолочь!»",
    "RPY104": "(>_< ) «Создал переменную на лету без default?! Сохранения у игроков сломаются после патча, дурак!»",
    "RPY201": "(╯°□°)╯︵ ┻━┻ «Ты меняешь переменную ПРЯМО ВНУТРИ ЭКРАНА?! Экраны так не работают, тупица!»",
    "RPY202": "(눈_눈) «Экран читает переменную без default! В главном меню игра сразу рухнет, гений!»",
    "RPY301": "(；￣Д￣) «Открыл тег и забыл закрыть?! Весь дальнейший текст игры поплывет, глаза б мои не смотрели!»",
    "RPY302": "( ﾟдﾟ) «Прыжок на метку, которой ВООБЩЕ НЕТ?! Куда ты собрался прыгать, в пустоту?!»",
    "RPY303": "(￣︿￣) «Написал метку и ни разу на нее не сослался... Забыл про нее, да? Мертвый код!»",
    "RPY304": "(｀ε´ ) «Что это за цвет такой?! Ты даже в hex-кодах умудрился опечататься!»",
    "RPY401": "(눈_눈) «В одном пункте меню ты переменную дал, а во втором забыл?! Выберут второй — и игра крашнется!»",
    "RPY501": "(￣︿￣) «Музыка не найдена! В этой сцене будет гробовая тишина, глупый!»",
}

SEVERITY_STYLES = {
    "ERROR": ("bold red", "red dim"),
    "WARNING": ("bold yellow", "yellow dim"),
    "INFO": ("bold blue", "blue dim"),
}


def load_config(project_path: str) -> dict:
    candidates = [
        os.path.join(project_path, "senpy.toml"),
        os.path.join(os.path.dirname(project_path), "senpy.toml"),
        os.path.join(os.getcwd(), "senpy.toml"),
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
    parser.add_argument("path", help="Path to the Ren'Py project (game directory)")
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
        "--errors-only",
        action="store_true",
        help="Show only critical ERRORs, hiding WARNINGs and INFO notices"
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

    args = parser.parse_args()

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

        if is_tsundere:
            console.print(
                f"[bold magenta](¬_¬ ) «П-подумаешь! Сканирую твою директорию: {args.path}... "
                "Н-не то чтобы мне был интересен твой сценарий, бака!»[/bold magenta]\n"
            )
        else:
            console.print(f"[bold cyan]Scanning directory:[/bold cyan] {args.path}...\n")

        start_time = time.perf_counter()
        analyzer = SenpyAnalyzer(args.path, extra_files=extra_rpy_files, fix=args.fix)
        result = analyzer.run()
        elapsed = time.perf_counter() - start_time

        # Фильтруем ошибки по кодам из --ignore и --errors-only
        active_diagnostics = [
            e for e in result.diagnostics
            if e.code not in ignored_codes and (not args.errors_only or e.severity == "ERROR")
        ]

        # 0 ПРОБЛЕМ
        if not active_diagnostics:
            if is_tsundere:
                console.print(
                    "[bold magenta](⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄) «Н-не то чтобы мне нравился твой сценарий... "
                    "но сюжетных дыр и крашей я не нашла, бака!»[/bold magenta]\n"
                    f"[dim]Проверено {result.total_lines:,} строк за {elapsed:.3f}с. Д-доволен?![/dim]"
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
        table = Table(title="Diagnostics Summary" if not is_tsundere else "Твои позорные ошибки", border_style="dim")
        table.add_column("Rule", style="bold cyan")
        table.add_column("Severity", justify="center")
        table.add_column("Count", justify="right", style="bold white")

        for (code, severity), count in sorted(counts.items()):
            sev_badge = Text(severity, style=SEVERITY_STYLES.get(severity, ("white", ""))[0])
            table.add_row(code, sev_badge, str(count))

        console.print(table)

        if result.fixed_count > 0:
            if is_tsundere:
                console.print(f"\n[bold magenta](//∇//) «Я... я закрыла за тобой {result.fixed_count} открытых тегов! Н-но не думай, что ты мне нравишься, идиот!»[/bold magenta]")
            else:
                console.print(f"\n[bold green]✔ Automatically fixed {result.fixed_count} error(s)![/bold green]")
        elif result.fixable_count > 0 and not args.fix:
            if is_tsundere:
                console.print(f"\n[dim magenta][*] Там есть {result.fixable_count} тегов, которые я могла бы починить за тебя через --fix... если вежливо попросишь, бака![/dim magenta]")
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
                console.print(f"\n[bold magenta](╬ Ò﹏Ó) Найдено {summary_str}! Иди и исправляй, я не буду играть в такую сломанную новеллу![/bold magenta] ({elapsed:.3f}s)")
            else:
                console.print(f"\n[bold magenta](¬_¬ ) Найдено {summary_str}... Жить можно, но я за тобой слежу, бака![/bold magenta] ({elapsed:.3f}s)")
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