"""
Скрипт быстрого запуска тестов Senpy с интерактивным меню и прогрессом.
Запуск:
    python run_tests.py                     # Меню или автозапуск
    python run_tests.py --update-snapshots  # Прямой запуск с флагом (для CI)
"""

from __future__ import annotations

import sys
import time
import traceback

import pytest
from rich.console import Console
from rich.prompt import Prompt

console = Console()


def run_pytest_with_timer(args: list[str]) -> int:
    """Запускает pytest с переданными аргументами и замеряет время."""
    console.print(f"\n[bold cyan]⚡ Запуск pytest с аргументами: {args}[/bold cyan]\n")

    start_time = time.perf_counter()
    exit_code = pytest.main(args)
    elapsed = time.perf_counter() - start_time

    # Если pytest завершился с кодом 5, это значит "No tests were collected" (пустой выбор по -k)
    if exit_code == 0:
        console.print(f"\n[bold green]✔ Всё успешно пройдено за {elapsed:.2f}с![/bold green]\n")
    elif exit_code == 5:
        console.print(
            "\n[bold yellow]⚠ Тесты по данному фильтру не найдены (возможно, фикстура для этого правила ещё не создана).[/bold yellow]\n"
        )
        exit_code = 0
    else:
        console.print(
            f"\n[bold red]✖ Обнаружены ошибки / падения тестов ({elapsed:.2f}с).[/bold red]\n"
        )

    return exit_code


def interactive_menu() -> list[str]:
    """Интерактивное консольное меню выбора режима тестирования."""
    console.print("[bold magenta]========================================[/bold magenta]")
    console.print("[bold white]          SENPY TEST RUNNER MENU          [/bold white]")
    console.print("[bold magenta]========================================[/bold magenta]")
    console.print("  [1] Прогон с обновлением снимков (--update-snapshots)")
    console.print("  [2] Обычный прогон всех тестов (быстрый)")
    console.print("  [3] Запуск тестов по конкретному правилу (фильтр -k)")
    console.print("  [q] Выход")
    console.print("[bold magenta]----------------------------------------[/bold magenta]")

    choice = Prompt.ask("[?] Выберите вариант", choices=["1", "2", "3", "q", "quit"], default="2")
    choice = choice.strip().lower()

    if choice in ("q", "quit"):
        console.print("[yellow][*] Выход из тестов.[/yellow]")
        sys.exit(0)
    elif choice == "1":
        return ["tests", "--update-snapshots"]
    elif choice == "2":
        return ["tests"]
    elif choice == "3":
        rule_input = (
            Prompt.ask("[?] Введите номер правила (например, 108 или rpy108)").strip().lower()
        )
        if not rule_input:
            return ["tests"]
        # Нормализуем ввод: если ввели "108", превращаем в "rpy108"
        rule_filter = rule_input if rule_input.startswith("rpy") else f"rpy{rule_input}"
        console.print(f"[dim][*] Фильтр тестов по шаблону: -k {rule_filter}[/dim]")
        return ["tests", "-k", rule_filter]

    return ["tests"]


def main():
    # Если аргументы переданы через консоль/CI (например, run_tests.py --update-snapshots),
    # меню пропускаем и выполняем их напрямую.
    if len(sys.argv) > 1:
        pytest_args = sys.argv[1:]
    else:
        # Иначе запускаем интерактивное меню
        pytest_args = interactive_menu()

    return run_pytest_with_timer(pytest_args)


if __name__ == "__main__":
    exit_code = 1
    try:
        exit_code = main()
    except KeyboardInterrupt:
        console.print("\n[yellow][*] Тестирование прервано пользователем (Ctrl+C).[/yellow]")
        exit_code = 130
    except SystemExit as se:
        exit_code = se.code if isinstance(se.code, int) else 1
    except BaseException:
        console.print("\n[bold red][!] Критическая ошибка скрипта:[/bold red]")
        traceback.print_exc()
        exit_code = 1
    finally:
        console.print()
        input("Нажмите Enter, чтобы закрыть окно...")
        sys.exit(exit_code)
