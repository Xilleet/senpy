from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Diagnostic:
    file_path: str
    line_number: int
    line_content: str
    code: str
    message: str
    severity: str = "ERROR"  # "ERROR", "WARNING", "INFO"
    col: int = 0
    end_col: int = 0
    fix_title: str | None = None
    fix_replacement: str | None = None
    fix_start_col: int | None = None
    fix_end_col: int | None = None


@dataclass
class AnalysisResult:
    diagnostics: list[Diagnostic]
    file_count: int
    total_lines: int
    fixed_count: int = 0
    fixable_count: int = 0


RULE_SEVERITY: dict[str, str] = {
    "RPY001": "ERROR",    # Табуляция в отступах
    "RPY002": "ERROR",    # Фигурные/типографские кавычки в коде
    "RPY101": "ERROR",    # Опечатка в [var] -> KeyError
    "RPY102": "ERROR",    # += до default -> NameError
    "RPY103": "ERROR",    # if var: без объявления -> NameError
    "RPY104": "WARNING",  # $ var = 1 без default -> риск для сохранений
    "RPY105": "ERROR",    # Мутация define-константы -> ломает откат и сейвы
    "RPY106": "WARNING",  # Использование random/set в игровом процессе
    "RPY201": "WARNING",  # Глобальная мутация внутри screen -> ломает откат
    "RPY202": "WARNING",  # Переменная в screen без default
    "RPY203": "WARNING",  # Кнопка без action
    "RPY204": "ERROR",    # Несуществующий экран -> ScriptError
    "RPY205": "WARNING",  # Циклы for/while внутри экрана
    "RPY206": "ERROR",    # Прямой вызов функции в action
    "RPY301": "ERROR",    # Незакрытый тег диалога
    "RPY302": "ERROR",    # Прыжок на несуществующую метку
    "RPY303": "INFO",     # Метка без статических ссылок
    "RPY304": "ERROR",    # Невалидный hex-цвет
    "RPY305": "ERROR",    # Неэкранированные кавычки в диалоге
    "RPY306": "WARNING",  # Поток call не гарантирует return
    "RPY307": "ERROR",    # Дубликат объявления label
    "RPY308": "WARNING",  # Label fallthrough без return/jump
    "RPY401": "WARNING",  # Развилка menu: переменная объявлена не везде
    "RPY402": "WARNING",  # Пустой выбор в menu
    "RPY403": "WARNING",  # Заведомо ложное условие
    "RPY501": "ERROR",    # Отсутствует аудиофайл
    "RPY502": "WARNING",  # Спрайт не найден в ассетах
    "RPY503": "WARNING",  # Неиспользуемый ассет на диске
    "RPY504": "WARNING",  # Повторное объявление/переопределение image
}