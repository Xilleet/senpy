"""CLI command handlers — обработчики команд senpy.

Вынесено из cli.py
Каждая функция принимает args (+ контекст) и возвращает:
  - None: команда не активна (args.xxx = False)
  - int: exit code (0 = успех, 1 = ошибка)
"""

from __future__ import annotations

import json
import os
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from senpy.traceback import find_latest_traceback, parse_traceback_file
from senpy.tsundere import TSUNDERE_UI


def handle_traceback(args, console: Console, is_tsundere: bool) -> int | None:
    """--traceback: анализ краш-лога."""
    if not args.traceback:
        return None

    traceback_arg = args.traceback
    if not os.path.isfile(traceback_arg):
        relative_to_project = os.path.join(args.path, traceback_arg)
        if os.path.isfile(relative_to_project):
            traceback_arg = relative_to_project
        elif traceback_arg == "traceback.txt":
            auto_found = find_latest_traceback(args.path)
            if auto_found:
                traceback_arg = auto_found

    crash = parse_traceback_file(traceback_arg)
    if not crash:
        console.print(
            f"[yellow]Could not find or parse crash log at '[bold]{traceback_arg}[/bold]'.[/yellow]\n"
        )
        if traceback_arg == "traceback.txt" or traceback_arg == args.traceback:
            console.print(
                "[dim]Hint: senpy looks for traceback.txt or errors.txt in project root or game/ subfolder.[/dim]"
            )
        return 0

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
    return 0


def handle_init_ci(args, console: Console, is_tsundere: bool) -> int | None:
    """--init-ci: создание GitHub Actions workflow."""
    if not args.init_ci:
        return None

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
    return 0


def handle_coverage(args, console: Console, is_tsundere: bool) -> int | None:
    """--coverage: метрики локализации."""
    if not args.coverage:
        return None

    from senpy.coverage import calculate_translation_coverage

    coverage_data = calculate_translation_coverage(args.path)

    if not coverage_data:
        console.print("[yellow]No translations found in game/tl/ directory.[/yellow]\n")
        return 0

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
            f"[{pct_style}]{pct}%[/{pct_style}]",
        )

    console.print(table)
    if is_tsundere:
        console.print(f"\n[bold magenta]{TSUNDERE_UI['coverage']}[/bold magenta]\n")
    return 0


def handle_clear_cache(args, console: Console) -> int | None:
    """--clear-cache: очистка кэша."""
    if not args.clear_cache:
        return None

    from senpy.cache import CacheManager

    cm = CacheManager(args.path)
    if cm.clear():
        console.print("[bold green]✔ Cache cleared successfully![/bold green]")
    else:
        console.print("[yellow]No cache directory found.[/yellow]")
    return 0


def handle_stats(args, analyzer, console: Console, is_tsundere: bool) -> int | None:
    """--stats: статистика по диалогам и персонажам."""
    if not args.stats:
        return None

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
        return 0

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
    return 0


def handle_export_wiki(args, analyzer, console: Console, is_tsundere: bool) -> int | None:
    """--export-wiki: генерация документации проекта."""
    if not args.export_wiki:
        return None

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
    return 0


def handle_export_html(
    args, result, analyzer, console: Console, is_tsundere: bool, ignored_codes: set
    ) -> int | None:
    """--export-html: автономный HTML отчёт."""
    if not args.export_html:
        return None

    from senpy.html_report import generate_html_report

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
        elapsed=0.0,
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
    return 0


def handle_graph(args, analyzer, console: Console, is_tsundere: bool) -> int | None:
    """--graph / --graph-file: граф сюжета в Mermaid."""
    if not (args.graph or args.graph_file):
        return None

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
        sys.stdout.write(graph_content + "\n")
    return 0


def handle_defaults(args, analyzer, console: Console, is_tsundere: bool) -> int | None:
    """--defaults: генерация senpy_defaults.rpy."""
    if not args.defaults:
        return None

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
    return 0


def handle_stubs(args, analyzer, console: Console, is_tsundere: bool) -> int | None:
    """--stubs: генерация Python type stubs."""
    if not args.stubs:
        return None

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
    return 0
