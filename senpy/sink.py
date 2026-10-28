"""DiagnosticSink — Protocol для объектов, способных принимать diagnostics.

Вынесено в отдельный модуль в Фазе 1.3 (0.5.3) для разрыва циклической
зависимости analyzer ↔ checkers.

Раньше BaseChecker.__init__ принимал analyzer: SenpyAnalyzer — это
заставляло checkers.py импортировать senpy.analyzer, что создавало цикл:
    analyzer.py → checkers.py → analyzer.py

Теперь BaseChecker.__init__ принимает analyzer: DiagnosticSink (Protocol).
SenpyAnalyzer реализует этот Protocol, но чекеры зависят только от Protocol,
не от конкретного класса. Это разрывает импортный цикл.

В Фазе 1.3 DiagnosticSink содержит только методы, связанные с диагностикой:
    - _add_diagnostic(diag, noqa_map)
    - _get_utf16_range(raw_line, name)
    - fixable_count, fixed_count, fix (атрибуты)

Доступ к символам (screens, labels, variables, ...) пока остаётся через
self.analyzer — это будет разорвано в 0.5.5 (когда _collect_symbols
будет разбит на отдельные SymbolRegistry).

Public API:
    DiagnosticSink  — Protocol (typing only, не инстанцируется)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from senpy.models import Diagnostic


@runtime_checkable
class DiagnosticSink(Protocol):
    """Protocol для объектов, способных принимать diagnostics и применять QuickFix.

    SenpyAnalyzer реализует этот Protocol. Чекеры (BaseChecker и наследники)
    зависят только от Protocol, не от конкретного класса SenpyAnalyzer.

    Это позволяет:
    1. Разорвать циклический импорт analyzer ↔ checkers.
    2. Тестировать чекеры с mock-объектами (в будущем).
    3. Создавать альтернативные реализации DiagnosticSink (например, для
      批量 обработки без full SenpyAnalyzer).

    Минимальный контракт (Фаза 1.3):
        - _add_diagnostic(diag, noqa_map) — добавить diagnostic
        - _get_utf16_range(raw_line, name) — посчитать UTF-16 диапазон для QuickFix
        - fixable_count: int — счётчик исправимых ошибок
        - fixed_count: int — счётчик исправленных ошибок
        - fix: bool — флаг режима автофикса

    В 0.5.5 (когда _collect_symbols будет разбит) будет добавлен
    SymbolProvider Protocol для доступа к символам (screens, labels, ...).
    """

    # Атрибуты (instance variables)
    fixable_count: int
    fixed_count: int
    fix: bool

    def _add_diagnostic(self, diag: "Diagnostic", noqa_map: dict[int, set[str] | None]) -> None:
        """Добавить diagnostic в список найденных ошибок.

        Args:
            diag: Diagnostic объект с информацией об ошибке.
            noqa_map: Map номер строки → set подавленных правил (для # noqa).
        """
        ...

    def _get_utf16_range(self, raw_line: str, name: str) -> tuple[int, int]:
        """Возвращает (start, end) UTF-16 позиции имени в строке.

        Используется для расчёта QuickFix диапазонов в LSP/CLI.

        Args:
            raw_line: Исходная строка из файла.
            name: Имя (переменной/метки/экрана/...) для поиска позиции.

        Returns:
            Кортеж (start_char, end_char) — позиции в UTF-16 code units.
        """
        ...
