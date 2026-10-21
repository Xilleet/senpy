from __future__ import annotations

import difflib
import os
import re

from senpy.constants import (
    MEDIA_EXTENSIONS,
    NAMED_COLORS,
    PAIR_TAGS,
    RE_INTERPOLATION,
    RE_STRING_MATCH,
    RE_TAG,
    SELF_CLOSING_TAGS,
)
from senpy.models import Diagnostic


def get_utf16_range(line: str, sub: str | None = None) -> tuple[int, int]:
    """Возвращает UTF-16 смещения (start, end) для LSP и подсветки в редакторе."""
    line_clean = line.rstrip("\r\n")
    if not sub:
        indent = len(line_clean) - len(line_clean.lstrip())
        start = len(line_clean[:indent].encode("utf-16-le")) // 2
        end = len(line_clean.encode("utf-16-le")) // 2
        return start, max(start + 1, end)

    idx = line_clean.find(sub)
    if idx == -1:
        indent = len(line_clean) - len(line_clean.lstrip())
        start = len(line_clean[:indent].encode("utf-16-le")) // 2
        end = len(line_clean.encode("utf-16-le")) // 2
        return start, max(start + 1, end)

    start = len(line_clean[:idx].encode("utf-16-le")) // 2
    end = len(line_clean[: idx + len(sub)].encode("utf-16-le")) // 2
    return start, end


def suggest_similar_symbol(unknown_var: str, user_symbols: set[str]) -> str:
    """Предлагает близкое по написанию имя переменной."""
    matches = difflib.get_close_matches(
        unknown_var, list(user_symbols), n=1, cutoff=0.6
    )
    if matches:
        return f" (did you mean '{matches[0]}' ?)"
    return ""


def process_quoted_strings(
    raw_line: str,
    line_idx: int,
    file_path: str,
    declared_symbols: set[str],
    extra_symbols: set[str],
    user_symbols: set[str],
    fix: bool = False,
) -> tuple[str, bool, list[Diagnostic], int, int, list[str]]:
    """
    Разбирает все строковые литералы в строке:
    - Выявляет и автофиксирует незакрытые теги (RPY301).
    - Проверяет hex-цвета в {color} (RPY304).
    - Проверяет необъявленные переменные в [var] (RPY101).
    - Регистрирует упомянутые ассеты (для RPY503).
    """
    modified = False
    reconstructed_line = raw_line
    non_nestable_tags = {"b", "i", "u", "s", "plain"}
    diagnostics: list[Diagnostic] = []
    fixed_count = 0
    fixable_count = 0
    used_assets: list[str] = []

    matches = list(RE_STRING_MATCH.finditer(raw_line))
    for match in reversed(matches):
        full_str = match.group(0)
        quote_char = full_str[0]
        inner_content = full_str[1:-1]

        # Регистрация ассета, если в кавычках указан путь к медиафайлу
        val_clean = inner_content.replace("\\", "/").lower().strip()
        if any(val_clean.endswith(ext) for ext in MEDIA_EXTENSIONS):
            used_assets.append(val_clean)
            used_assets.append(os.path.basename(val_clean))

        # Маскируем экранированные {{, }}, [[, ]], сохраняя смещения символов
        masked_content = re.sub(r"\{\{|\}\}|\[\[|\]\]", "  ", inner_content)

        # RPY101: Переменные в интерполяции диалога [var]
        for var in RE_INTERPOLATION.findall(masked_content):
            if var not in declared_symbols and var not in extra_symbols:
                hint = suggest_similar_symbol(var, user_symbols)
                start_c, end_c = get_utf16_range(raw_line, f"[{var}]")
                diagnostics.append(
                    Diagnostic(
                        file_path=file_path,
                        line_number=line_idx,
                        line_content=raw_line.strip(),
                        code="RPY101",
                        message=f"Variable '[{var}]' is not declared via 'default' or 'define'{hint}.",
                        col=start_c,
                        end_col=end_c,
                    )
                )

        stack: list[str] = []
        in_place_replacements: list[tuple[int, int, str]] = []

        for t_match in RE_TAG.finditer(masked_content):
            is_closing = t_match.group(1) == "/"
            tag_name = t_match.group(2).lower()
            tag_param = t_match.group(3)
            t_start, t_end = t_match.span()

            # RPY304: Проверка валидности hex-цвета
            if tag_name == "color" and not is_closing and tag_param:
                color_val = tag_param.strip("\"'").lower()
                if color_val.startswith("#"):
                    hex_str = color_val[1:]
                    if len(hex_str) not in (3, 4, 6, 8) or not all(c in "0123456789abcdef" for c in hex_str):
                        start_c, end_c = get_utf16_range(raw_line, tag_param)
                        diagnostics.append(
                            Diagnostic(
                                file_path=file_path,
                                line_number=line_idx,
                                line_content=raw_line.strip(),
                                code="RPY304",
                                message=f"Malformed hex color '{color_val}' in {{color}} tag.",
                                col=start_c,
                                end_col=end_c,
                            )
                        )
                elif color_val not in NAMED_COLORS:
                    diagnostics.append(
                        Diagnostic(
                            file_path=file_path,
                            line_number=line_idx,
                            line_content=raw_line.strip(),
                            code="RPY304",
                            message=f"Unknown color name '{color_val}' in {{color}} tag.",
                        )
                    )

            if tag_name in SELF_CLOSING_TAGS:
                continue

            if tag_name in PAIR_TAGS:
                if is_closing:
                    if not stack:
                        diagnostics.append(
                            Diagnostic(
                                file_path=file_path,
                                line_number=line_idx,
                                line_content=raw_line.strip(),
                                code="RPY301",
                                message=f"Found closing tag '{{/{tag_name}}}' without matching opening tag.",
                            )
                        )
                    else:
                        last_tag = stack.pop()
                        if last_tag != tag_name:
                            diagnostics.append(
                                Diagnostic(
                                    file_path=file_path,
                                    line_number=line_idx,
                                    line_content=raw_line.strip(),
                                    code="RPY301",
                                    message=f"Mismatched tag: expected '{{/{last_tag}}}', found '{{/{tag_name}}}'.",
                                )
                            )
                else:
                    # Умная проверка: дубликат открывающего тега вместо закрывающего
                    if tag_name in non_nestable_tags and tag_name in stack:
                        stack.remove(tag_name)
                        replacement_tag = f"{{/{tag_name}}}"
                        in_place_replacements.append((t_start, t_end, replacement_tag))

                        raw_tag_start = match.start() + 1 + t_start
                        raw_tag_end = match.start() + 1 + t_end
                        start_c = len(raw_line[:raw_tag_start].encode("utf-16-le")) // 2
                        end_c = len(raw_line[:raw_tag_end].encode("utf-16-le")) // 2

                        diagnostics.append(
                            Diagnostic(
                                file_path=file_path,
                                line_number=line_idx,
                                line_content=raw_line.strip(),
                                code="RPY301",
                                message=f"Duplicate opening tag '{{{tag_name}}}' while already inside '{{{tag_name}}}'. Did you mean '{{/{tag_name}}}'?",
                                col=start_c,
                                end_col=end_c,
                                fix_title=f"Change '{{{tag_name}}}' to '{{/{tag_name}}}'",
                                fix_replacement=replacement_tag,
                                fix_start_col=start_c,
                                fix_end_col=end_c,
                            )
                        )
                    else:
                        stack.append(tag_name)

        # 1. Применяем замены опечаток внутри строки ({i} -> {/i})
        if in_place_replacements:
            fixable_count += len(in_place_replacements)
            if fix:
                for s, e, repl in sorted(in_place_replacements, key=lambda x: x[0], reverse=True):
                    inner_content = inner_content[:s] + repl + inner_content[e:]
                modified = True
                fixed_count += len(in_place_replacements)

        # 2. Если остались реально незакрытые теги в конце строки
        if stack:
            closing_tags = "".join(f"{{/{t}}}" for t in reversed(stack))
            if fix:
                inner_content = inner_content + closing_tags
                modified = True
                fixed_count += len(stack)
            else:
                fixable_count += 1
                unclosed = ", ".join(f"'{{{t}}}'" for t in stack)
                first_unclosed_tag = f"{{{stack[0]}}}"
                start_c, end_c = get_utf16_range(raw_line, first_unclosed_tag)

                insert_idx = match.end() - 1
                ins_char = len(raw_line[:insert_idx].encode("utf-16-le")) // 2

                diagnostics.append(
                    Diagnostic(
                        file_path=file_path,
                        line_number=line_idx,
                        line_content=raw_line.strip(),
                        code="RPY301",
                        message=f"Unclosed text tag(s) in dialogue: {unclosed}.",
                        col=start_c,
                        end_col=end_c,
                        fix_title=f"Auto-close tag(s) with '{closing_tags}'",
                        fix_replacement=closing_tags,
                        fix_start_col=ins_char,
                        fix_end_col=ins_char,
                    )
                )

        if modified and fix:
            start, end = match.span()
            reconstructed_line = (
                reconstructed_line[:start]
                + f"{quote_char}{inner_content}{quote_char}"
                + reconstructed_line[end:]
            )

    return reconstructed_line, modified, diagnostics, fixed_count, fixable_count, used_assets