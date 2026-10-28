from __future__ import annotations

import re

from senpy.core.models import Diagnostic
from senpy.domain.text_tags import get_utf16_range

# Словарь устаревших API:
# Имя функции -> (Совет/пояснение, 1-к-1 замена для автофикса или None)
DEPRECATED_APIS: dict[str, tuple[str, str | None]] = {
    # Устаревшие Displayables
    "LiveComposite": (
        "This function is obsolete or outdated. Use 'Composite' instead.",
        "Composite",
    ),
    "LiveCrop": ("This function is obsolete or outdated. Use 'Crop' instead.", "Crop"),
    "LiveTile": ("This function is obsolete or outdated. Use 'Tile' instead.", "Tile"),
    "DynamicCharacter": (
        "Deprecated in modern Ren'Py. Use 'Character' with '[var]' interpolation instead.",
        "Character",
    ),
    # Устаревшие анимации (заменены на ATL)
    "anim.Filmstrip": (
        "Legacy animation helper. Prefer modern ATL (transform / pause) instead.",
        None,
    ),
    "anim.Blink": ("Legacy animation helper. Prefer modern ATL instead.", None),
    "anim.SMAnimation": ("Legacy animation helper. Prefer modern ATL instead.", None),
    # Устаревшие вызовы ui.* (заменены на Screen Language)
    "ui.text": (
        "Legacy 'ui' screen function is obsolete. Use Screen Language 'text' statement.",
        None,
    ),
    "ui.button": (
        "Legacy 'ui' screen function is obsolete. Use Screen Language 'button' statement.",
        None,
    ),
    "ui.imagebutton": (
        "Legacy 'ui' screen function is obsolete. Use Screen Language 'imagebutton' statement.",
        None,
    ),
    "ui.textbutton": (
        "Legacy 'ui' screen function is obsolete. Use Screen Language 'textbutton' statement.",
        None,
    ),
    "ui.vbox": (
        "Legacy 'ui' screen function is obsolete. Use Screen Language 'vbox' statement.",
        None,
    ),
    "ui.hbox": (
        "Legacy 'ui' screen function is obsolete. Use Screen Language 'hbox' statement.",
        None,
    ),
    "ui.grid": (
        "Legacy 'ui' screen function is obsolete. Use Screen Language 'grid' statement.",
        None,
    ),
    "ui.close": (
        "Legacy 'ui' screen construction is obsolete. Use declarative Screen Language.",
        None,
    ),
}

# Предкомпилированное регулярное выражение для быстрого поиска
RE_DEPRECATED = re.compile(r"\b(" + "|".join(re.escape(k) for k in DEPRECATED_APIS) + r")\b")

# Быстрый фильтр подстрок, чтобы не гонять regex по обычным строкам
FAST_TERMS = ("Live", "anim.", "ui.", "DynamicCharacter")


class DeprecationChecker:
    """Проверяет строки кода сценария на использование устаревшего API Ren'Py."""

    @staticmethod
    def _is_in_quotes(s: str, pos: int) -> bool:
        """Проверяет, находится ли позиция pos внутри строкового литерала."""
        in_quote = None
        i = 0
        while i < pos:
            ch = s[i]
            if ch == "\\":
                i += 2
                continue
            if in_quote:
                if ch == in_quote:
                    in_quote = None
            elif ch in ('"', "'"):
                in_quote = ch
            i += 1
        return in_quote is not None

    @classmethod
    def check_line(cls, line: str, line_no: int, file_path: str) -> list[Diagnostic]:
        # 1. Быстрый фильтр: если ни одной подстроки нет, выходим за 5 наносекунд
        if not any(term in line for term in FAST_TERMS):
            return []

        # 2. Пропускаем комментарии
        stripped = line.strip()
        if stripped.startswith("#"):
            return []

        diagnostics: list[Diagnostic] = []
        for match in RE_DEPRECATED.finditer(line):
            # Если токен внутри кавычек диалога — игнорируем
            if cls._is_in_quotes(line, match.start()):
                continue

            token = match.group(1)
            advice, replacement = DEPRECATED_APIS[token]
            start_c, end_c = get_utf16_range(line, token)

            diagnostics.append(
                Diagnostic(
                    file_path=file_path,
                    line_number=line_no,
                    line_content=line.strip(),
                    code="RPY107",
                    message=f"Deprecated Ren'Py API '{token}'. {advice}",
                    severity="WARNING",
                    col=start_c,
                    end_col=end_c,
                    fix_title=f"Replace '{token}' with '{replacement}'" if replacement else None,
                    fix_replacement=replacement if replacement else None,
                    fix_start_col=start_c if replacement else None,
                    fix_end_col=end_c if replacement else None,
                )
            )
        return diagnostics
