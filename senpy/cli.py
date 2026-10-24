from __future__ import annotations

import argparse
import contextlib
import json
import os
import pickle
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from collections import Counter

import tomllib
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from senpy.analyzer import SenpyAnalyzer
from senpy.constants import IGNORED_DIRS
from senpy.rpa import safe_load_rpa_index
from senpy.traceback import find_latest_traceback
from senpy.tsundere import IS_RU, TSUNDERE_FLAVORS, TSUNDERE_UI

console = Console()

SENPY_CACHE_DIR = os.path.expanduser("~/.senpy/tools/unrpyc")
UNRPYC_GITHUB_ZIP = "https://github.com/CensoredUsername/unrpyc/archive/refs/heads/master.zip"

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

    with contextlib.suppress(OSError, ValueError, TypeError, zlib.error, pickle.PickleError), open(rpa_path, "rb") as f:
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
        if os.path.exists(f) and os.path.normcase(os.path.abspath(f)) != os.path.normcase(os.path.abspath(dest)):
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
        if IS_RU else
        f"✔ Successfully decompiled {len(decompiled_rpy)} file(s) into sandbox!"
    )
    console.print(f"[bold green]{success_msg}[/bold green]\n")
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
        help="List all 40 available Senpy rules and their descriptions"
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
        "--coverage",
        action="store_true",
        help="Display translation coverage metrics and completion percentages for game/tl/"
    )
    g_lint.add_argument(
        "--defaults",
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
        "--export-wiki",
        nargs="?",
        const="PROJECT_WIKI.md",
        metavar="FILE",
        help="Generate project documentation (characters, variables, endings) in Markdown (default: PROJECT_WIKI.md)"
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
        "--init-ci",
        action="store_true",
        help="Generate a GitHub Actions workflow (.github/workflows/senpy.yml) with automated SARIF scanning"
    )
    g_tools.add_argument(
        "--traceback",
        nargs="?",
        const="traceback.txt",
        metavar="FILE",
        help="Inspect runtime crash log (traceback.txt or errors.txt) and explain the crash using Senpy rules"
    )
    g_tools.add_argument(
        "--stubs",
        nargs="?",
        const="typings",
        metavar="DIR",
        help="Generate Python type stubs (.pyi) for Pylance / MyPy in VS Code (default: typings/)"
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
    is_tsundere = args.tsundere or config.get("tsundere", False)

    if args.traceback:
        from senpy.traceback import parse_traceback_file
        crash = parse_traceback_file(args.traceback)
        if not crash:
            console.print(f"[yellow]Could not find or parse crash log at '[bold]{args.traceback}[/bold]'.[/yellow]\n")
            sys.exit(0)

        t_text = Text()
        t_text.append("Runtime Crash Report (Post-Mortem Analysis)\n\n", style="bold red")
        t_text.append(f"Location:  {crash.file_path}:{crash.line_number}\n", style="bold cyan")
        if crash.code_line:
            t_text.append(f"Code:      {crash.code_line}\n", style="bright_white")
        t_text.append(f"Exception: {crash.exception_type}: {crash.exception_message}\n\n", style="bold yellow")
        t_text.append(f"Rule [{crash.rule_code}]: ", style="bold red")
        t_text.append(f"{crash.explanation}\n", style="bright_white")

        console.print(Panel(t_text, title="Traceback Inspector", border_style="red"))
        sys.exit(0)

    if args.init_ci:
        from senpy.ci import init_ci_workflow
        out_path, _created = init_ci_workflow(args.path)
        rel_out = os.path.relpath(out_path, os.getcwd())
        if is_tsundere:
            console.print(f"[bold magenta]{TSUNDERE_UI['init_ci'].format(path=rel_out)}[/bold magenta]\n")
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
            pct_style = "bold green" if pct >= 95.0 else "bold yellow" if pct >= 70.0 else "bold red"
            table.add_row(
                lang,
                f"{stats.total_strings:,}",
                f"{stats.translated_strings:,}",
                f"{stats.empty_strings:,}",
                f"[{pct_style}]{pct}%[/{pct_style}]"
            )

        console.print(table)
        if is_tsundere:
            console.print(f"\n[bold magenta]{TSUNDERE_UI['coverage']}[/bold magenta]\n")
        sys.exit(0)

    if args.clear_cache:
        from senpy.cache import CacheManager
        cm = CacheManager(args.path)
        if cm.clear():
            console.print(f"[bold green]✔ Successfully cleared cache directory: {cm.cache_dir}[/bold green]")
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
    existing_rpy_files = set()
    for root, dirs, files in os.walk(args.path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for f in files:
            if f.endswith(".rpy"):
                existing_rpy_files.add(f)

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
                base_name = os.path.basename(item)
                rpy_name = base_name[:-1] if base_name.endswith(".rpyc") else base_name
                # Если такой .rpy уже есть в game/, пропускаем архивную копию
                if rpy_name not in existing_rpy_files:
                    if item.endswith(".rpy"):
                        extra_rpy_files.append(item)
                    elif item.endswith(".rpyc"):
                        raw_orphans.append(item)

    # 3. Синхронизируем исходники для дедупликации (не декомпилируем .rpyc, если уже найден .rpy)
    for f in extra_rpy_files:
        existing_rpy_files.add(os.path.basename(f))

    # 4. Проверяем кэш декомпиляции для всех .rpyc (с диска и из .rpa)
    for rpyc in raw_orphans:
        rpy_name = os.path.basename(rpyc)[:-1]
        
        # Если .rpy исходник уже найден в папке или вытащен из архива — игнорируем его .rpyc
        if rpy_name in existing_rpy_files:
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

        recent_tb = find_latest_traceback(args.path)
        if recent_tb:
            auto_crash = parse_traceback_file(recent_tb)
            if auto_crash:
                tb_name = os.path.basename(recent_tb)
                tb_text = Text()
                tb_text.append(f"Recent crash log detected ({tb_name})!\n", style="bold red")
                tb_text.append(f"Crashed at: {auto_crash.file_path}:{auto_crash.line_number} — {auto_crash.exception_type}\n", style="yellow")
                tb_text.append(f"[{auto_crash.rule_code}] {auto_crash.explanation}", style="bright_white")
                console.print(Panel(tb_text, border_style="red dim", expand=False))
                console.print()

    start_time = time.perf_counter()
    analyzer = SenpyAnalyzer(args.path, extra_files=extra_rpy_files, fix=args.fix, no_cache=args.no_cache)
    result = analyzer.run(quiet=is_quiet_mode)
    elapsed = time.perf_counter() - start_time
    if args.export_wiki:
        from senpy.wiki import generate_project_wiki
        wiki_md = generate_project_wiki(analyzer)
        target_wiki = args.export_wiki
        with open(target_wiki, "w", encoding="utf-8", newline="\n") as f:
            f.write(wiki_md)
        if is_tsundere:
            console.print(f"\n[bold magenta]{TSUNDERE_UI['export_wiki'].format(path=target_wiki)}[/bold magenta]\n")
        else:
            console.print(f"\n[bold green]✔ Project documentation exported to [bold]{target_wiki}[/bold]![/bold green]\n")
        sys.exit(0)
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
    if args.defaults:
        out_file, gen_count = analyzer.generate_defaults_file()
        if gen_count > 0:
            if is_tsundere:
                console.print(f"\n[bold magenta](//∇//) «{TSUNDERE_UI['defaults_generated'].format(path=out_file, count=gen_count)}»[/bold magenta]\n")
            else:
                console.print(f"\n[bold green]✔ Successfully generated [bold]{out_file}[/bold] with [bold]{gen_count}[/bold] default declaration(s)![/bold green]\n")
        else:
            console.print("\n[bold green]✔ All variables are already properly declared via 'default'![/bold green]\n")
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