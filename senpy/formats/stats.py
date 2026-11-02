from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from senpy.core.analyzer import _get_logical_line
from senpy.core.constants import NON_DIALOGUE_STATEMENTS
from senpy.core.paths import normalize_path

if TYPE_CHECKING:
    from senpy.core.analyzer import SenpyAnalyzer


@dataclass(slots=True)
class CharacterStats:
    tag: str
    display_name: str
    lines_count: int = 0
    words_count: int = 0
    chars_count: int = 0
    percentage_words: float = 0.0


@dataclass(slots=True)
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
RE_TEXT_TAGS = re.compile(r"\{[^}]*\}")
RE_WORDS = re.compile(r"[\w\'-]+", re.UNICODE)
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
    """Collect story statistics: dialogue lines, word counts, character stats.

    Only counts dialogue inside `label` blocks (not screens, styles, etc.).
    """
    char_names = extract_character_names(analyzer)
    char_stats: dict[str, CharacterStats] = {}
    counters = _StatCounters()

    main_rpy, _ = analyzer._get_rpy_files()
    for file_path in main_rpy + analyzer.extra_files:
        lines = _read_stats_lines(file_path, analyzer)
        if lines is None:
            continue
        _process_stats_for_file(
            lines=lines, char_names=char_names, char_stats=char_stats, counters=counters
        )

    return _build_story_stats(char_stats, counters.lines, counters.words, counters.chars)


@dataclass(slots=True)
class _StatCounters:
    """Mutable counters shared across the file/line processing helpers."""

    lines: int = 0
    words: int = 0
    chars: int = 0


@dataclass(slots=True)
class _LineContext:
    """Per-line state for the dialogue-line loop (label scope + last speaker)."""

    in_label: bool = False
    last_speaker: str = "narrator"


def _read_stats_lines(file_path: str, analyzer: SenpyAnalyzer) -> list[str] | None:
    """Return the file's lines (from in-memory cache or disk).

    Returns None if the file is not readable (e.g. missing, UTF-8 decode
    error) — caller should skip the file silently.
    """
    norm_path = normalize_path(file_path)
    if norm_path in analyzer.in_memory_files:
        return analyzer.in_memory_files[norm_path].splitlines(keepends=True)
    try:
        with open(file_path, encoding="utf-8", newline="") as f:
            return f.readlines()
    except (OSError, UnicodeDecodeError):
        return None


def _process_stats_for_file(
    *,
    lines: list[str],
    char_names: dict[str, str],
    char_stats: dict[str, CharacterStats],
    counters: _StatCounters,
) -> None:
    """Walk every logical line in `lines`, accumulating dialogue stats into
    `char_stats` (per-character) and `counters` (totals).
    """
    ctx = _LineContext()
    idx = 0
    while idx < len(lines):
        next_idx, raw_line, clean = _get_logical_line(lines, idx)
        idx = _process_stats_line(
            next_idx=next_idx,
            raw_line=raw_line,
            clean=clean,
            ctx=ctx,
            char_names=char_names,
            char_stats=char_stats,
            counters=counters,
        )


def _process_stats_line(
    *,
    next_idx: int,
    raw_line: str,
    clean: str,
    ctx: _LineContext,
    char_names: dict[str, str],
    char_stats: dict[str, CharacterStats],
    counters: _StatCounters,
) -> int:
    """Process one logical line, return the next line index to resume from.

    Mutates `ctx` (label scope + last speaker), `char_stats` (per-character
    dialogue counts), and `counters` (totals).
    """
    stripped = clean.strip()
    if not stripped:
        return next_idx

    line_indent = len(raw_line) - len(raw_line.lstrip(" "))
    _update_label_scope(line_indent=line_indent, stripped=stripped, ctx=ctx)
    if not ctx.in_label:
        return next_idx

    # extend "..." continuation: attribute words to the previous speaker
    if stripped.startswith(("extend ", "extend\t")):
        w_count, c_count = _count_extend_words(stripped)
        if w_count > 0 and ctx.last_speaker in char_stats:
            char_stats[ctx.last_speaker].words_count += w_count
            char_stats[ctx.last_speaker].chars_count += c_count
            counters.words += w_count
            counters.chars += c_count
        return next_idx

    first_word = stripped.split()[0] if stripped.split() else ""
    if first_word in NON_DIALOGUE_STATEMENTS:
        return next_idx

    m = RE_DIALOGUE_LINE.match(stripped)
    if m:
        speaker_tag, word_count, char_count = _parse_dialogue_line(m, char_names, char_stats)
        if word_count > 0:
            ctx.last_speaker = speaker_tag
            counters.lines += 1
            counters.words += word_count
            counters.chars += char_count

    return next_idx


def _update_label_scope(*, line_indent: int, stripped: str, ctx: _LineContext) -> None:
    """Toggle `ctx.in_label` based on top-level block headers.

    A `label X:` at indent 0 → enter label scope. A `screen`/`style`/`init`/
    `transform`/`image`/`layeredimage` at indent 0 → leave label scope.
    Lines inside label blocks (indent > 0) don't change the scope.
    """
    if line_indent != 0:
        return
    if stripped.startswith("label ") and stripped.endswith(":"):
        ctx.in_label = True
        return
    if stripped.startswith(("screen ", "style ", "init ", "transform ", "image ", "layeredimage ")):
        ctx.in_label = False


def _count_extend_words(stripped: str) -> tuple[int, int]:
    """Count words in an extend "..." continuation line."""
    m_ext = re.search(r'("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')', stripped)
    if not m_ext:
        return 0, 0
    text_content = m_ext.group(2) or m_ext.group(3) or ""
    clean_text = RE_TEXT_TAGS.sub("", text_content).replace('\\"', '"').replace("\\'", "'")
    words = RE_WORDS.findall(clean_text)
    return len(words), sum(len(w) for w in words)


def _parse_dialogue_line(
    m: re.Match,
    char_names: dict[str, str],
    char_stats: dict[str, CharacterStats],
) -> tuple[str, int, int]:
    """Parse a dialogue line match, update char_stats, return (speaker_tag, word_count, char_count)."""
    raw_speaker = m.group(1)
    text_content = m.group(3) or m.group(4) or ""

    clean_text = RE_TEXT_TAGS.sub("", text_content).replace('\\"', '"').replace("\\'", "'")
    words = RE_WORDS.findall(clean_text)
    word_count = len(words)
    char_count = sum(len(w) for w in words)

    if word_count == 0:
        return "narrator", 0, 0

    speaker_tag = raw_speaker.strip("\"'") if raw_speaker else "narrator"
    disp_name = char_names.get(
        speaker_tag,
        "Narrator (Рассказчик)" if speaker_tag == "narrator" else speaker_tag,
    )

    if speaker_tag not in char_stats:
        char_stats[speaker_tag] = CharacterStats(tag=speaker_tag, display_name=disp_name)

    char_stats[speaker_tag].lines_count += 1
    char_stats[speaker_tag].words_count += word_count
    char_stats[speaker_tag].chars_count += char_count

    return speaker_tag, word_count, char_count


def _build_story_stats(
    char_stats: dict[str, CharacterStats],
    total_lines: int,
    total_words: int,
    total_chars: int,
) -> StoryStats:
    """Calculate percentages and build final StoryStats result."""
    for stat in char_stats.values():
        if total_words > 0:
            stat.percentage_words = round((stat.words_count / total_words) * 100, 1)

    reading_time = round(total_words / 180.0, 1)
    sorted_chars = dict(
        sorted(char_stats.items(), key=lambda item: item[1].words_count, reverse=True)
    )

    return StoryStats(
        total_dialogue_lines=total_lines,
        total_words=total_words,
        total_chars=total_chars,
        reading_time_minutes=reading_time,
        characters=sorted_chars,
    )
