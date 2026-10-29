from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from senpy.cli.unrpyc import (
    decompile_to_sandbox,
    extract_scripts_from_rpa,
    find_unrpyc_executable,
)
from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.config import load_config
from senpy.core.constants import IGNORED_DIRS
from senpy.domain.tsundere import TSUNDERE_FLAVORS, TSUNDERE_UI
from senpy.formats.traceback import find_latest_traceback, parse_traceback_file
from senpy.formatter import FormatConfig, Formatter

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

SEVERITY_STYLES = {
    "ERROR": ("bold red", "red dim"),
    "WARNING": ("bold yellow", "yellow dim"),
    "HINT": ("bold cyan", "cyan dim"),
    "INFO": ("bold blue", "blue dim"),
}

# P1-1: unrpyc/rpa функции вынесены в senpy/_unrpyc_bootstrap.py
# (Вариант B — умеренный рефакторинг cli.py)
from senpy.cli.commands import (  # noqa: E402
    handle_clear_cache,
    handle_coverage,
    handle_defaults,
    handle_export_html,
    handle_export_wiki,
    handle_graph,
    handle_init_ci,
    handle_stats,
    handle_stubs,
    handle_traceback,
)


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


def _dispatch_format(argv: list[str]) -> int:
    """Обработчик подкоманды `senpy format`.

    Использование:
        senpy format [PATHS...] [OPTIONS]

    Опции:
        --check              Не записывать файлы, exit 1 если требуются изменения
        --diff               Показать diff без записи
        --stdin-filename NAME  Читать из stdin, считать что это NAME
        --help, -h           Показать справку
    """

    fmt_parser = argparse.ArgumentParser(
        prog="senpy format",
        description="Format .rpy files (Black-style). Idempotent, low-risk, Ren'Py-specific.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    fmt_parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to format (default: current dir)",
    )
    fmt_parser.add_argument(
        "--check",
        action="store_true",
        help="Don't write files, exit 1 if any file would be modified (CI-friendly)",
    )
    fmt_parser.add_argument(
        "--diff",
        action="store_true",
        help="Print diff of what would be changed, don't write files",
    )
    fmt_parser.add_argument(
        "--stdin-filename",
        metavar="NAME",
        help="Read from stdin, format, print to stdout. NAME is used for scope detection.",
    )

    fmt_args = fmt_parser.parse_args(argv)
    formatter = Formatter(FormatConfig())

    # Режим stdin
    if fmt_args.stdin_filename:
        code = sys.stdin.read()
        formatted = formatter.format_code(code, filename=fmt_args.stdin_filename)
        sys.stdout.write(formatted)
        return 0

    # Сбор .rpy файлов
    rpy_files: list[Path] = []
    for p_str in fmt_args.paths:
        p = Path(p_str)
        if p.is_file() and p.suffix == ".rpy":
            rpy_files.append(p)
        elif p.is_dir():
            rpy_files.extend(p.rglob("*.rpy"))
        else:
            print(f"[yellow]Skipping (not a .rpy file/dir): {p}[/yellow]")

    if not rpy_files:
        print("[yellow]No .rpy files found.[/yellow]")
        return 0

    changed_count = 0
    would_change_count = 0

    for f in rpy_files:
        try:
            original = f.read_text(encoding="utf-8")
        except OSError as e:
            print(f"[red]Error reading {f}: {e}[/red]")
            continue

        formatted = formatter.format_code(original, filename=str(f))

        if original == formatted:
            continue  # already formatted

        if fmt_args.check:
            would_change_count += 1
            print(f"[yellow]Would reformat:[/yellow] {f}")
        elif fmt_args.diff:
            import difflib

            diff = difflib.unified_diff(
                original.splitlines(keepends=True),
                formatted.splitlines(keepends=True),
                fromfile=str(f),
                tofile=str(f),
            )
            sys.stdout.writelines(diff)
            would_change_count += 1
        else:
            try:
                f.write_text(formatted, encoding="utf-8")
                changed_count += 1
                print(f"[green]Formatted:[/green] {f}")
            except OSError as e:
                print(f"[red]Error writing {f}: {e}[/red]")

    # Итоговый вывод
    if fmt_args.check or fmt_args.diff:
        if would_change_count > 0:
            print(
                f"\n[bold yellow]{would_change_count} file(s) would be reformatted.[/bold yellow]"
            )
            return 1
        print("\n[bold green]All files are already formatted![/bold green]")
        return 0

    if changed_count > 0:
        print(f"\n[bold green]{changed_count} file(s) formatted.[/bold green]")
    else:
        print("\n[bold green]All files are already formatted![/bold green]")
    return 0

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Создаёт argparse parser и парсит аргументы CLI.

    Вынесено из main() в Phase 3 Step 1 (0.5.6) для:
    - Тестируемости (можно вызывать с произвольным argv)
    - Уменьшения main() с 719 до ~530 строк
    - Подготовки к dispatch_subcommand() pattern

    Args:
        argv: Аргументы командной строки. None = использовать sys.argv.

    Returns:
        argparse.Namespace с распарсенными аргументами.
    """
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

    return parser.parse_args(argv)

def filter_diagnostics(
    result,
    args,
    ignored_codes: set[str],
) -> tuple[list, int]:
    """Фильтрует diagnostics по --ignore, --errors-only, --info.

    Вынесено из main() в Phase 3 Step 2a (0.5.6) для:
    - Тестируемости (чистая функция, без side effects)
    - Уменьшения main()
    - Подготовки к render_output()

    Args:
        result: AnalysisResult с .diagnostics list.
        args: Namespace с .ignore, .errors_only, .info.
        ignored_codes: Set кодов правил для игнорирования.

    Returns:
        Кортеж (active_diagnostics, hidden_info_count):
        - active_diagnostics: отфильтрованный список для вывода
        - hidden_info_count: сколько INFO скрыто (для сообщения "use --info")
    """
    hidden_info_count = sum(
        1
        for e in result.diagnostics
        if e.severity == "INFO"
        and e.code not in ignored_codes
        and not args.info
    )
    active_diagnostics = [
        e
        for e in result.diagnostics
        if e.code not in ignored_codes
        and (not args.errors_only or e.severity == "ERROR")
        and (args.info or e.severity != "INFO")
    ]
    return active_diagnostics, hidden_info_count

def render_sarif(active_diagnostics, args, console) -> int:
    """Рендерит diagnostics в SARIF формат. Возвращает exit code (не вызывает sys.exit).

    Вынесено из main() в Phase 3 Step 2b (0.5.6).
    """
    from senpy.formats.sarif import generate_sarif
    sarif_str = generate_sarif(active_diagnostics, args.path)
    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(sarif_str)
        console.print(f"[bold green]✔ SARIF report saved to {args.output_file}[/bold green]")
    else:
        print(sarif_str)
    error_count = sum(1 for e in active_diagnostics if e.severity == "ERROR")
    return 1 if error_count > 0 else 0


def render_json(active_diagnostics, result, elapsed, args, console) -> int:
    """Рендерит diagnostics в JSON формат. Возвращает exit code (не вызывает sys.exit).

    Вынесено из main() в Phase 3 Step 2b (0.5.6).
    """
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
    return 1 if error_count > 0 else 0

def render_text(
    active_diagnostics,
    hidden_info_count: int,
    result,
    args,
    console: Console,
    is_tsundere: bool,
    elapsed: float,
    max_errors: int,
) -> int:
    """Рендерит diagnostics в text-формате (карточки + таблица + summary).

    Возвращает exit code (не вызывает sys.exit).
    Вынесено из main() в Phase 3 Step 2c (0.5.6).
    """
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
        return 0

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
    return 0 if args.exit_zero else (1 if error_count > 0 else 0)

def discover_files(args, config: dict, project_path: str) -> list[str]:
    """Находит .rpy файлы, .rpyc orphans, извлекает RPA, декомпилирует .rpyc.

    Вынесено из main() в Phase 3 Step 3 (0.5.6).
    Возвращает список extra_rpy_files — путей к .rpy файлам из RPA/декомпиляции.
    """
    decomp_sandbox = os.path.join(os.path.abspath(args.path), ".senpy_cache", "decompiled")
    rpa_sandbox = os.path.join(os.path.abspath(args.path), ".senpy_cache", "rpa_extracted")
    os.makedirs(decomp_sandbox, exist_ok=True)
    os.makedirs(rpa_sandbox, exist_ok=True)

    raw_orphans = SenpyAnalyzer.find_orphaned_rpyc(args.path)
    orphaned_rpyc = []
    extra_rpy_files = []

    # P0-4: ДВА множества для дедупликации
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
                    rel = f
                existing_rpy_files.add(rel)
                existing_rpy_basenames.add(f)

    # 2. RPA
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
                if rpy_name not in existing_rpy_basenames:
                    if item.endswith(".rpy"):
                        extra_rpy_files.append(item)
                    elif item.endswith(".rpyc"):
                        raw_orphans.append(item)

    # 3. Синхронизация
    for f in extra_rpy_files:
        existing_rpy_basenames.add(os.path.basename(f))

    # 4. Кэш декомпиляции
    for rpyc in raw_orphans:
        rpy_name = os.path.basename(rpyc)[:-1]
        if rpy_name in existing_rpy_basenames:
            continue
        cached_rpy = os.path.join(decomp_sandbox, rpy_name)
        if os.path.exists(cached_rpy) and os.path.getmtime(cached_rpy) >= os.path.getmtime(rpyc):
            if cached_rpy not in extra_rpy_files:
                extra_rpy_files.append(cached_rpy)
        else:
            if rpyc not in orphaned_rpyc:
                orphaned_rpyc.append(rpyc)

    # 5. Декомпиляция
    if orphaned_rpyc:
        should_decompile = config.get("decompile", False) or args.decompile
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

    return extra_rpy_files

def main():

    # P1-1: Subcommand dispatch (senpy format ...)
    if len(sys.argv) > 1 and sys.argv[1] == "format":
        return _dispatch_format(sys.argv[2:])

    # Phase 3 Step 1: argparse вынесен в parse_args()
    args = parse_args()

    # UX-15: --version — печатает и выходит.
    if args.version:
        from senpy.__version__ import __version__

        print(f"senpy {__version__}")
        sys.exit(0)

    if args.lsp:
        from senpy.lsp.server import start_lsp

        start_lsp()
        sys.exit(0)

    if args.rules or args.rule:
        from senpy.rules.rules_info import show_rule_detail, show_rules_table

        if args.rule:
            show_rule_detail(args.rule.upper())
        else:
            show_rules_table()
        sys.exit(0)

    config = load_config(args.path)
    is_tsundere = args.tsundere or config.get("tsundere", False)

    _ec = handle_traceback(args, console, is_tsundere)
    if _ec is not None:
        sys.exit(_ec)

    _ec = handle_init_ci(args, console, is_tsundere)
    if _ec is not None:
        sys.exit(_ec)

    _ec = handle_coverage(args, console, is_tsundere)
    if _ec is not None:
        sys.exit(_ec)

    _ec = handle_clear_cache(args, console)
    if _ec is not None:
        sys.exit(_ec)

    cfg_ignore = set(config.get("ignore", []))
    cli_ignore = set(args.ignore) if args.ignore is not None else set()
    ignored_codes = {c.strip().upper() for c in (cli_ignore or cfg_ignore)}

    max_errors = args.max_errors or config.get("max_errors", 50)

    # Phase 3 Step 3: file discovery вынесено в discover_files()
    extra_rpy_files = discover_files(args, config, args.path)

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
    _ec = handle_stats(args, analyzer, console, is_tsundere)
    if _ec is not None:
        sys.exit(_ec)
    _ec = handle_export_wiki(args, analyzer, console, is_tsundere)
    if _ec is not None:
        sys.exit(_ec)
    _ec = handle_export_html(args, result, analyzer, console, is_tsundere, ignored_codes)
    if _ec is not None:
        sys.exit(_ec)
    _ec = handle_graph(args, analyzer, console, is_tsundere)
    if _ec is not None:
        sys.exit(_ec)
    _ec = handle_defaults(args, analyzer, console, is_tsundere)
    if _ec is not None:
        sys.exit(_ec)
    _ec = handle_stubs(args, analyzer, console, is_tsundere)
    if _ec is not None:
        sys.exit(_ec)
    # Phase 3 Step 2a: фильтрация вынесена в filter_diagnostics()
    active_diagnostics, hidden_info_count = filter_diagnostics(result, args, ignored_codes)

    # --- ВЫВОД В ФОРМАТЕ SARIF ДЛЯ GITHUB ACTIONS ---
    if args.output_format == "sarif":
        sys.exit(render_sarif(active_diagnostics, args, console))

    # --- ВЫВОД В ФОРМАТЕ JSON ДЛЯ VS CODE ---
    elif args.output_format == "json":
        sys.exit(render_json(active_diagnostics, result, elapsed, args, console))

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
        _exit_with_output_redirect(
            args,
            render_text(active_diagnostics, hidden_info_count, result, args, console, is_tsundere, elapsed, max_errors)
        )


if __name__ == "__main__":
    main()
