#!/usr/bin/env python3
"""Демо-скрипт для проверки Senpy formatter на живых примерах.

Запуск:
    python test_formatter_demo.py

Скрипт прогоняет 5 тестов и показывает результаты.
Никаких файлов не меняет — только печатает в консоль.
"""
from __future__ import annotations

from senpy.formatter import Formatter


def test(name: str, code: str, expect_changed: bool = True) -> None:
    """Прогнать форматтер и показать результат."""
    f = Formatter()
    formatted = f.format_code(code)

    print(f"\n{'='*70}")
    print(f"ТЕСТ: {name}")
    print(f"{'='*70}")
    print("ВХОД (raw):")
    print(repr(code))
    print()
    print("ВЫХОД (formatted):")
    print(repr(formatted))
    print()
    print("ВЫХОД (как текст):")
    print(formatted)
    print()

    changed = code != formatted
    if changed == expect_changed:
        print(f"✓ ОК (изменён: {changed})")
    else:
        print(f"✗ НЕ ОЖИДАЛИ (изменён: {changed}, ожидали: {expect_changed})")

    # Idempotency check
    twice = f.format_code(formatted)
    if twice == formatted:
        print("✓ Idempotent: format(format(x)) == format(x)")
    else:
        print("✗ НЕ IDEMPOTENT!")
        print(f"  twice: {twice!r}")


def main() -> None:
    print("=" * 70)
    print("Senpy Formatter — демо")
    print("=" * 70)

    f = Formatter()
    print(f"Зарегистрированные правила: {[n for n, _ in f.rules]}")
    print(f"Конфиг: indent_size={f.config.indent_size}, max_blank_lines={f.config.max_blank_lines}")

    # Тест 1: табуляция → 4 пробела
    test(
        "Табуляция → 4 пробела",
        'label start:\n\t"Hello"\n\treturn\n',
        expect_changed=True,
    )

    # Тест 2: trailing whitespace + нет EOF newline
    test(
        "Trailing whitespace + нет EOF newline",
        'label start:   \n    "Hello"   ',
        expect_changed=True,
    )

    # Тест 3: слишком много пустых строк
    test(
        "3+ пустых строк → max 2",
        'label a:\n    "x"\n\n\n\n\nlabel b:\n    "y"\n',
        expect_changed=True,
    )

    # Тест 4: skip block НЕ трогается
    test(
        "Skip block (# senpy: format off) НЕ трогается",
        '# senpy: format off\n$ x =\t1   \n# senpy: format on\n',
        expect_changed=False,
    )

    # Тест 5: уже отформатированный файл — no-op
    test(
        "Уже отформатированный — no-op",
        'label start:\n    "Hello"\n    return\n',
        expect_changed=False,
    )

    # Тест 6: смешанные tab + spaces
    test(
        "Смешанные tab + spaces → нормализация",
        'label start:\n  \t"Mixed indent"\n',
        expect_changed=True,
    )

    # Тест 7: реальный .rpy с несколькими блоками
    test(
        "Реальный .rpy (label + screen + menu)",
        'label start:\n\t"Hello"\n\tjump chapter2\n\n\n\n\n'
        'label chapter2:\n\t"World"\n\treturn\n\n'
        'screen main_menu():\n\ttextbutton "Start" action Start()\n',
        expect_changed=True,
    )

    # Тест 8: пустой файл
    test(
        "Пустой файл",
        '',
        expect_changed=False,
    )

    # Тест 9: только комментарии
    test(
        "Только комментарии",
        '# comment 1\n# comment 2\n',
        expect_changed=False,
    )

    # Тест 10: CRLF → LF
    test(
        "CRLF line endings → LF",
        'label start:\r\n\t"Hello"\r\n\treturn\r\n',
        expect_changed=True,
    )

    print(f"\n{'='*70}")
    print("ВСЕ ТЕСТЫ ПРОЙДЕНЫ")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
