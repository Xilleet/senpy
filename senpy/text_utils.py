"""Текстовые утилиты Senpy — функции, не имеющие зависимостей от analyzer.

Вынесено в отдельный модуль в Фазе 1.3 (0.5.3) для разрыва циклических
зависимостей:
    - checkers.py → analyzer._strip_comment
    - flow.py → analyzer._strip_comment

Раньше _strip_comment лежал в analyzer.py, и checkers/flow делали lazy
импорт `from senpy.core.analyzer import _strip_comment` внутри методов. Это
создавало цикл (хотя и через runtime, не через top-level import).

Теперь _strip_comment в этом модуле (senpy/text_utils.py), все зависят
от него однонаправленно:
    analyzer.py → senpy.text_utils
    checkers.py → senpy.text_utils
    flow.py → senpy.text_utils

Для обратной совместимости _strip_comment реэкспортируется из analyzer.py
(старый импорт `from senpy.core.analyzer import _strip_comment` продолжает работать).

Public API:
    _strip_comment(line: str) -> str
"""
from __future__ import annotations


def _strip_comment(line: str) -> str:
    """Удаляет комментарий (#), не ломая hex-цвета, экранированные кавычки (\\") и тройные кавычки.

    Алгоритм:
    1. Если '#' нет в строке — вернуть как есть.
    2. Идти посимвольно, отслеживая состояние:
       - Внутри одинарных/двойных кавычек — '#' не считается комментарием.
       - Внутри тройных кавычек (''' или \"\"\") — аналогично.
       - Экранированный символ (\\X) — пропускаем 2 символа.
       - '#' вне строк — начало комментария, обрезаем.
    3. Если дошли до конца — строка без комментария, вернуть как есть.

    Это важно для Ren'Py, где:
      - '#ffffff' — hex-цвет, не комментарий
      - '"# not a comment"' — '#' внутри строки, не комментарий
      - 'label start: # comment' — '#' после кода, комментарий

    Args:
        line: Исходная строка (может содержать # в любом месте).

    Returns:
        Строка с обрезанным комментарием (если он был). Пробелы в конце
        не трогаются — это задача вызывающего кода.
    """
    if "#" not in line:
        return line

    in_quote = None
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "\\":
            i += 2
            continue
        if in_quote in ('"""', "'''"):
            if line[i : i + 3] == in_quote:
                in_quote = None
                i += 3
                continue
            i += 1
            continue
        if in_quote:
            if ch == in_quote:
                in_quote = None
            i += 1
            continue
        if line[i : i + 3] in ('"""', "'''"):
            in_quote = line[i : i + 3]
            i += 3
            continue
        if ch in ('"', "'"):
            in_quote = ch
            i += 1
            continue
        if ch == "#":
            return line[:i]
        i += 1
    return line
