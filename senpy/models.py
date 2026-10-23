from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
@dataclass
class Diagnostic:
    file_path: str
    line_number: int
    line_content: str
    code: str
    message: str
    severity: str | None = None
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


@dataclass
class FileScope:
    user_symbols: set[str] = field(default_factory=set)
    declared_symbols: set[str] = field(default_factory=set)
    defined_constants: set[str] = field(default_factory=set)
    declared_characters: set[str] = field(default_factory=set)
    declared_labels: dict[str, tuple[str, int, str]] = field(default_factory=dict)
    declared_screens: dict[str, tuple[str, int]] = field(default_factory=dict)
    declared_images: dict[str, tuple[str, int, str]] = field(default_factory=dict)
    declared_layeredimages: dict[str, set[str]] = field(default_factory=dict)
    defined_audio_map: dict[str, str] = field(default_factory=dict)
    registered_audio_channels: set[str] = field(default_factory=set)
    referenced_labels: set[str] = field(default_factory=set)
    labels_with_return: set[str] = field(default_factory=set)
    label_outgoing_jumps: dict[str, set[str]] = field(default_factory=dict)
    jump_sources: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    label_signatures: dict = field(default_factory=dict)
    screen_signatures: dict = field(default_factory=dict)
    symbol_declarations: dict[str, tuple[str, int, str]] = field(default_factory=dict)
    symbol_types: dict[str, str] = field(default_factory=dict)

RULE_SEVERITY: dict[str, str] = {
    # 0xx: Синтаксис и форматирование (Критично для парсера)
    "RPY001": "ERROR",    # Табуляция в отступах -> SyntaxError
    "RPY002": "ERROR",    # Фигурные/типографские кавычки в коде -> SyntaxError

    # 1xx: Переменные, состояние и питон
    "RPY101": "ERROR",    # Опечатка в [var] -> KeyError в диалоге
    "RPY102": "ERROR",    # += до default -> NameError при входе в сцену
    "RPY103": "ERROR",    # if var: без объявления -> NameError
    "RPY104": "WARNING",  # $ var = 1 без default -> поломка сейвов после патча
    "RPY105": "ERROR",    # Мутация define-константы -> ломает откат назад
    "RPY106": "WARNING",  # Использование random/set в игровом процессе
    "RPY107": "HINT",     # Устаревший API Ren'Py (LiveComposite и др. работают, но устарели)
    "RPY108": "ERROR",    # Конфликт типов или несовместимый += -> TypeError
    "RPY109": "ERROR",    # Нарушение порядка загрузки init python (вызов до объявления)

    # 2xx: Экраны и UI
    "RPY201": "WARNING",  # Глобальная мутация внутри screen -> ломает предсказание UI
    "RPY202": "WARNING",  # Переменная в screen без default
    "RPY203": "WARNING",  # Кнопка без action (мертвый элемент интерфейса)
    "RPY204": "ERROR",    # Несуществующий экран -> ScriptError
    "RPY205": "WARNING",  # Циклы for/while внутри экрана (просадки FPS)
    "RPY206": "ERROR",    # Прямой вызов функции в action со скобками
    "RPY207": "ERROR",    # Несовпадение параметров при вызове экрана (use / call screen)

    # 3xx: Диалоги и граф сюжета
    "RPY301": "ERROR",    # Незакрытый тег диалога {b}
    "RPY302": "ERROR",    # Прыжок на несуществующую метку -> ScriptError
    "RPY303": "HINT",     # Метка-одиночка без ссылок (может вызываться динамически)
    "RPY304": "ERROR",    # Невалидный hex-цвет
    "RPY305": "ERROR",    # Неэкранированные кавычки в диалоге
    "RPY306": "WARNING",  # Поток call не гарантирует return
    "RPY307": "ERROR",    # Дубликат объявления label -> ScriptError
    "RPY308": "WARNING",  # Label fallthrough без return/jump
    "RPY309": "WARNING",  # Сюжетный остров / изолированный цикл сцен
    "RPY310": "ERROR",    # Несовпадение аргументов вызова метки call (TypeError)

    # 4xx: Развилки сюжета и условия
    "RPY401": "WARNING",  # Развилка menu: переменная объявлена не везде
    "RPY402": "WARNING",  # Пустой выбор в menu
    "RPY403": "WARNING",  # Заведомо ложное условие (мертвый блок кода)
    "RPY404": "WARNING",  # Чтение переменной со статусом MAYBE_SET после развилки menu

    # 5xx: Ассеты и медиа
    "RPY501": "ERROR",    # Отсутствует аудиофайл на диске
    "RPY502": "WARNING",  # Спрайт или поза не найдена в ассетах
    "RPY503": "HINT",     # Неиспользуемый ассет на диске (лишний вес билда)
    "RPY504": "HINT",     # Повторное объявление/переопределение image (часто намеренно в модах)
    "RPY505": "WARNING",  # Несуществующий аудиоканал или невалидный модификатор (loop на voice)

    # 6xx: Локализация (tl/)
    "RPY601": "ERROR",    # Рассинхрон переменных [var] в переводе -> KeyError
    "RPY602": "WARNING",  # Рассинхрон тегов {тег} в переводе
    "RPY603": "WARNING",  # Пустая строка перевода new ""
}