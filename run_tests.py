"""
Senpy test runner with an interactive menu and progress display.
Usage:
    python run_tests.py                     # Menu or auto-run
    python run_tests.py --update-snapshots  # Direct run with a flag (for CI)
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
    """Run pytest with the given arguments and time the execution."""
    console.print(f"\n[bold cyan]⚡ Running pytest with args: {args}[/bold cyan]\n")

    start_time = time.perf_counter()
    exit_code = pytest.main(args)
    elapsed = time.perf_counter() - start_time

    # Exit code 5 means "No tests were collected" (empty -k filter result).
    if exit_code == 0:
        console.print(
            f"\n[bold green]✔ Everything was successfully completed in {elapsed:.2f}с![/bold green]\n"
        )
    elif exit_code == 5:
        console.print(
            "\n[bold yellow]⚠ No tests found for this filter (it is possible that a fixture for this rule has not yet been created).[/bold yellow]\n"
        )
        exit_code = 0
    else:
        console.print(
            f"\n[bold red]✖ Errors / test failures detected ({elapsed:.2f}с).[/bold red]\n"
        )

    return exit_code


def interactive_menu() -> list[str]:
    """Interactive console menu for choosing the test mode."""
    console.print("[bold magenta]========================================[/bold magenta]")
    console.print("[bold white]          SENPY TEST RUNNER MENU          [/bold white]")
    console.print("[bold magenta]========================================[/bold magenta]")
    console.print("  [1] Run with snapshot updates (--update-snapshots)")
    console.print("  [2] A standard run of all tests (быстрый)")
    console.print("  [3] Running tests for a specific rule (using the -k filter)")
    console.print("  [q] Exit")
    console.print("[bold magenta]----------------------------------------[/bold magenta]")

    choice = Prompt.ask("[?] Select an option", choices=["1", "2", "3", "q", "quit"], default="2")
    choice = choice.strip().lower()

    if choice in ("q", "quit"):
        console.print("[yellow][*] Exiting tests.[/yellow]")
        sys.exit(0)
    elif choice == "1":
        return ["tests", "--update-snapshots"]
    elif choice == "2":
        return ["tests"]
    elif choice == "3":
        rule_input = (
            Prompt.ask("[?] Enter the rule number (for example, 108 or rpy108)").strip().lower()
        )
        if not rule_input:
            return ["tests"]
        # Normalize input: if the user typed "108", convert it to "rpy108".
        rule_filter = rule_input if rule_input.startswith("rpy") else f"rpy{rule_input}"
        console.print(f"[dim][*] Test filter pattern: -k {rule_filter}[/dim]")
        return ["tests", "-k", rule_filter]

    return ["tests"]


def main():
    # If arguments were passed via CLI/CI (e.g. run_tests.py --update-snapshots),
    # skip the menu and run them directly.
    if len(sys.argv) > 1:
        pytest_args = sys.argv[1:]
    else:
        # Otherwise launch the interactive menu.
        pytest_args = interactive_menu()

    return run_pytest_with_timer(pytest_args)


if __name__ == "__main__":
    exit_code = 1
    try:
        exit_code = main()
    except KeyboardInterrupt:
        console.print("\n[yellow][*] Testing interrupted by the user (Ctrl+C).[/yellow]")
        exit_code = 130
    except SystemExit as se:
        exit_code = se.code if isinstance(se.code, int) else 1
    except BaseException:
        console.print("\n[bold red][!] Critical script error:[/bold red]")
        traceback.print_exc()
        exit_code = 1
    finally:
        console.print()
        input("Press Enter to close the window...")
        sys.exit(exit_code)
