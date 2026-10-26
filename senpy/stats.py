from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from senpy.analyzer import _get_logical_line
from senpy.constants import NON_DIALOGUE_STATEMENTS

if TYPE_CHECKING:
    from senpy.analyzer import SenpyAnalyzer


@dataclass
class CharacterStats:
    tag: str
    display_name: str
    lines_count: int = 0
    words_count: int = 0
    chars_count: int = 0
    percentage_words: float = 0.0


@dataclass
class StoryStats:
    total_dialogue_lines: int = 0
    total_words: int = 0
    total_chars: int = 0
    reading_time_minutes: float = 0.0
    characters: dict[str, CharacterStats] = field(default_factory=dict)

    @property
    def reading_time_formatted(self) -> str:
        hours = int(self.reading_time_minutes // 60)
        mins = int(self.reading_time_minutes % 60)
        if hours > 0:
            return f"~{hours} ч. {mins} мин."
        return f"~{mins} мин."


RE_CHARACTER_DEF = re.compile(
    r'(?:Dynamic)?Character\s*\(\s*(?:_\s*\(\s*)?["\']?([^"\'\),]+)["\']?'
)
RE_VAR_VALUE = re.compile(r'=\s*["\']([^"\']+)["\']')
RE_TEXT_TAGS = re.compile(r'\{[^}]*\}')
RE_WORDS = re.compile(r'[\w\'-]+', re.UNICODE)
RE_DIALOGUE_LINE = re.compile(
    r'^(?:([^\W\d]\w*|"[^"]*"|\'[^\']*\')(?:\s+[\w-]+)*\s+)?("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')(.*)$'
)


def extract_character_names(analyzer: SenpyAnalyzer) -> dict[str, str]:
    """Извлекает отображаемые имена персонажей с разворачиванием динамических переменных (DynamicCharacter)."""
    names: dict[str, str] = {}
    for var_name, sym in analyzer.variables.items():
        if sym.is_character:
            m = RE_CHARACTER_DEF.search(sym.code_line)
            if m:
                raw_target = m.group(1).strip()
                # Снимаем интерполяцию [var] если имя задано как Character("[p_name]")
                clean_target = raw_target.strip("[]\"'")
                
                # Если имя персонажа ссылается на переменную (как в DDLC: s_name -> Сайори)
                if clean_target in analyzer.variables:
                    val_match = RE_VAR_VALUE.search(analyzer.variables[clean_target].code_line)
                    if val_match:
                        names[var_name] = val_match.group(1)
                        continue
                
                names[var_name] = raw_target if raw_target.isidentifier() is False else clean_target
            else:
                names[var_name] = var_name
    return names


def collect_story_stats(analyzer: SenpyAnalyzer) -> StoryStats:
    """Собирает сценарную статистику реплик строго внутри меток сюжета (label)."""
    char_names = extract_character_names(analyzer)
    char_stats: dict[str, CharacterStats] = {}

    total_lines = 0
    total_words = 0
    total_chars = 0

    main_rpy, _ = analyzer._get_rpy_files()
    all_files = main_rpy + analyzer.extra_files

    for file_path in all_files:
        norm_path = os.path.normcase(os.path.abspath(file_path))
        if norm_path in analyzer.in_memory_files:
            lines = analyzer.in_memory_files[norm_path].splitlines(keepends=True)
        else:
            try:
                with open(file_path, "r", encoding="utf-8", newline="") as f:
                    lines = f.readlines()
            except (OSError, UnicodeDecodeError):
                continue

        idx = 0
        in_label = False
        last_speaker = "narrator"

        while idx < len(lines):
            next_idx, raw_line, clean = _get_logical_line(lines, idx)
            stripped = clean.strip()
            line_indent = len(raw_line) - len(raw_line.lstrip(" "))

            if not stripped:
                idx = next_idx
                continue

            # Диалог в Ren'Py существует СТРОГО внутри меток сюжета (label).
            # Всё, что на отступе 0 вне label (screens, styles, init, transforms), игнорируется!
            if line_indent == 0:
                if stripped.startswith("label ") and stripped.endswith(":"):
                    in_label = True
                elif stripped.startswith(("screen ", "style ", "init ", "transform ", "image ", "layeredimage ")):
                    in_label = False

            if not in_label:
                idx = next_idx
                continue

            # Обработка специальной конструкции Ren'Py: extend "..."
            if stripped.startswith(("extend ", "extend\t")):
                m_ext = re.search(r'("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')', stripped)
                if m_ext:
                    text_content = m_ext.group(2) or m_ext.group(3) or ""
                    clean_text = RE_TEXT_TAGS.sub("", text_content).replace('\\"', '"').replace("\\'", "'")
                    words = RE_WORDS.findall(clean_text)
                    w_count = len(words)
                    c_count = sum(len(w) for w in words)

                    if w_count > 0 and last_speaker in char_stats:
                        char_stats[last_speaker].words_count += w_count
                        char_stats[last_speaker].chars_count += c_count
                        total_words += w_count
                        total_chars += c_count

                idx = next_idx
                continue

            first_word = stripped.split()[0] if stripped.split() else ""
            if first_word in NON_DIALOGUE_STATEMENTS:
                idx = next_idx
                continue

            m = RE_DIALOGUE_LINE.match(stripped)
            if m:
                raw_speaker = m.group(1)
                text_content = m.group(3) or m.group(4) or ""

                # Очистка текста от тегов {b}, {color=...} и экранированных символов
                clean_text = RE_TEXT_TAGS.sub("", text_content).replace('\\"', '"').replace("\\'", "'")
                words = RE_WORDS.findall(clean_text)
                word_count = len(words)
                char_count = sum(len(w) for w in words)

                if word_count > 0:
                    speaker_tag = raw_speaker.strip("\"'") if raw_speaker else "narrator"
                    disp_name = char_names.get(speaker_tag, "Narrator (Рассказчик)" if speaker_tag == "narrator" else speaker_tag)

                    if speaker_tag not in char_stats:
                        char_stats[speaker_tag] = CharacterStats(tag=speaker_tag, display_name=disp_name)

                    char_stats[speaker_tag].lines_count += 1
                    char_stats[speaker_tag].words_count += word_count
                    char_stats[speaker_tag].chars_count += char_count

                    last_speaker = speaker_tag
                    total_lines += 1
                    total_words += word_count
                    total_chars += char_count

            idx = next_idx

    # Расчёт долей диалогов
    for stat in char_stats.values():
        if total_words > 0:
            stat.percentage_words = round((stat.words_count / total_words) * 100, 1)

    reading_time = round(total_words / 180.0, 1)
    sorted_chars = dict(sorted(char_stats.items(), key=lambda item: item[1].words_count, reverse=True))

    return StoryStats(
        total_dialogue_lines=total_lines,
        total_words=total_words,
        total_chars=total_chars,
        reading_time_minutes=reading_time,
        characters=sorted_chars,
    )