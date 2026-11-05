"""Translation file analysis: RPY601/602/603.

Extracted from core/analyzer.py in 0.6.6 to reduce analyzer god-class.
Handles .rpy translation files (game/tl/) — validates variable interpolation,
formatting tags, and empty translations.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from senpy.core.constants import NON_DIALOGUE_STATEMENTS
from senpy.core.file_collector import build_noqa_map
from senpy.core.models import Diagnostic
from senpy.core.paths import normalize_path

if TYPE_CHECKING:
    from senpy.core.analyzer import SenpyAnalyzer


def analyze_tl_file(analyzer: SenpyAnalyzer, file_path: str) -> None:
    """Analyze a translation (.rpy) file for RPY601/602/603 issues.

    Reads the file (or in-memory content), parses old/new translation pairs,
    and validates them. Appends diagnostics to analyzer.diagnostics.
    """
    try:
        norm_path = normalize_path(file_path)
        if norm_path in analyzer.in_memory_files:
            lines = analyzer.in_memory_files[norm_path].splitlines(keepends=True)
        else:
            with open(file_path, encoding="utf-8", newline="") as f:
                lines = f.readlines()
    except UnicodeDecodeError as e:
        analyzer._emit_encoding_error(file_path, e)
        return
    except OSError:
        return

    analyzer.total_lines += len(lines)
    pairs = parse_tl_pairs(lines)
    noqa_map = build_noqa_map(lines)
    # Persist for the later cross-file RPY802 check; the per-file rules
    # below consume this map directly via _add_diagnostic.
    analyzer._noqa_maps[normalize_path(file_path)] = noqa_map
    validate_tl_pairs(analyzer, pairs, file_path, noqa_map)


def parse_tl_pairs(lines: list[str]) -> list[tuple[str, int, str, int]]:
    """State machine that collects safe pairs:
    (source_text, old_line, translation_text, new_line)

    Robust to comments, blank lines, voice/with, and missing new.
    """
    re_old = re.compile(r'^\s*old\s+("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')')
    re_new = re.compile(r'^\s*new\s+("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')')
    re_dialogue_old = re.compile(
        r'^\s*#\s*(?:(?:\w+|"[^"]*"|\'[^\']*\')(?:\s+\w+)*\s+)?("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')'
    )
    re_dialogue_new = re.compile(
        r'^\s*(?:(?:\w+|"[^"]*"|\'[^\']*\')(?:\s+\w+)*\s+)?("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')'
    )

    pairs = []
    pending_old = None
    pending_old_line = 0

    for line_no, raw_line in enumerate(lines, start=1):
        clean = raw_line.strip()
        if not clean:
            continue

        # 1. translate strings: (old / new)
        m_old = re_old.match(clean)
        if m_old:
            s = m_old.group(1)
            pending_old = s[1:-1]
            pending_old_line = line_no
            continue

        m_new = re_new.match(clean)
        if m_new:
            if pending_old is not None:
                s = m_new.group(1)
                pairs.append((pending_old, pending_old_line, s[1:-1], line_no))
                pending_old = None
                pending_old_line = 0
            continue

        # 2. dialogue blocks: (# "original" / "translation")
        if clean.startswith("#"):
            m_d_old = re_dialogue_old.match(clean)
            if m_d_old:
                s = m_d_old.group(1)
                pending_old = s[1:-1]
                pending_old_line = line_no
            continue
        else:
            first_word = clean.split()[0] if clean.split() else ""
            if first_word in NON_DIALOGUE_STATEMENTS or clean.startswith("translate "):
                if clean.startswith("translate "):
                    pending_old = None
                continue

            if pending_old is not None:
                m_d_new = re_dialogue_new.match(clean)
                if m_d_new:
                    s = m_d_new.group(1)
                    pairs.append((pending_old, pending_old_line, s[1:-1], line_no))
                pending_old = None
                pending_old_line = 0

    return pairs


def validate_tl_pairs(
    analyzer: SenpyAnalyzer,
    pairs: list[tuple[str, int, str, int]],
    file_path: str,
    noqa_map: dict[int, set[str] | None],
) -> None:
    """Validate translation pairs for RPY601/602/603/801.

    Thin dispatcher (REF-008): delegates to per-rule helpers.
    Was CC=~15, 111 lines → CC=2, ~15 lines.
    """
    re_var = re.compile(r"\[([^\W\d]\w*)(?:![a-zA-Z]+)?\]")
    re_tag = re.compile(r"\{(/?[a-zA-Z_]+)(?:=[^}]*)?\}")

    seen_old: dict[str, int] = {}
    duplicate_reported: set[str] = set()

    for old_txt, old_line, new_txt, new_line in pairs:
        old_masked = re.sub(r"\\.|(\{\{|\}\}|\[\[|\]\])", "  ", old_txt)
        new_masked = re.sub(r"\\.|(\{\{|\}\}|\[\[|\]\])", "  ", new_txt)

        if _check_rpy603(analyzer, old_txt, new_txt, new_line, file_path, noqa_map):
            continue

        _check_rpy601(
            analyzer, old_masked, new_masked, new_txt, new_line, file_path, re_var, noqa_map
        )
        _check_rpy602(
            analyzer, old_masked, new_masked, new_txt, new_line, file_path, re_tag, noqa_map
        )
        _check_rpy801(
            analyzer, old_txt, old_line, seen_old, duplicate_reported, file_path, noqa_map
        )


def _check_rpy603(
    analyzer: SenpyAnalyzer,
    old_txt: str,
    new_txt: str,
    new_line: int,
    file_path: str,
    noqa_map: dict[int, set[str] | None],
) -> bool:
    """RPY603: Empty translation string. Returns True if diagnostic was emitted (caller should `continue`)."""
    if old_txt.strip() and not new_txt.strip():
        start_c, end_c = analyzer._get_utf16_range(f'new "{new_txt}"', new_txt)
        analyzer._add_diagnostic(
            Diagnostic(
                file_path=file_path,
                line_number=new_line,
                line_content=f'new "{new_txt}"',
                code="RPY603",
                message="Translation string is empty ('new \"\"'). Players will see blank text.",
                severity="WARNING",
                col=start_c,
                end_col=end_c,
            ),
            noqa_map,
        )
        return True
    return False


def _check_rpy601(
    analyzer: SenpyAnalyzer,
    old_masked: str,
    new_masked: str,
    new_txt: str,
    new_line: int,
    file_path: str,
    re_var: re.Pattern,
    noqa_map: dict[int, set[str] | None],
) -> None:
    """RPY601: Variable interpolation mismatch [var]."""
    old_vars = Counter(re_var.findall(old_masked))
    new_vars = Counter(re_var.findall(new_masked))
    missing = old_vars - new_vars
    extra = new_vars - old_vars

    if missing or extra:
        diffs = []
        if missing:
            diffs.append(f"lost: {', '.join(f'[{v}]' for v in missing)}")
        if extra:
            diffs.append(f"typo/extra: {', '.join(f'[{v}]' for v in extra)}")

        start_c, end_c = analyzer._get_utf16_range(new_txt, next(iter(extra)) if extra else None)
        analyzer._add_diagnostic(
            Diagnostic(
                file_path=file_path,
                line_number=new_line,
                line_content=new_txt,
                code="RPY601",
                message=f"Variable mismatch in translation ({'; '.join(diffs)}). Will crash with KeyError at runtime!",
                severity="ERROR",
                col=start_c,
                end_col=end_c,
            ),
            noqa_map,
        )


def _check_rpy602(
    analyzer: SenpyAnalyzer,
    old_masked: str,
    new_masked: str,
    new_txt: str,
    new_line: int,
    file_path: str,
    re_tag: re.Pattern,
    noqa_map: dict[int, set[str] | None],
) -> None:
    """RPY602: Formatting tag mismatch {b}, {color}, etc."""
    old_tags = Counter(re_tag.findall(old_masked))
    new_tags = Counter(re_tag.findall(new_masked))
    if old_tags != new_tags:
        analyzer._add_diagnostic(
            Diagnostic(
                file_path=file_path,
                line_number=new_line,
                line_content=new_txt,
                code="RPY602",
                message="Formatting tags count or names do not match the original string. Text styles may break.",
                severity="WARNING",
            ),
            noqa_map,
        )


def _check_rpy801(
    analyzer: SenpyAnalyzer,
    old_txt: str,
    old_line: int,
    seen_old: dict[str, int],
    duplicate_reported: set[str],
    file_path: str,
    noqa_map: dict[int, set[str] | None],
) -> None:
    """RPY801: Duplicate translation string in the same file."""
    if old_txt in seen_old and old_txt not in duplicate_reported:
        first_line = seen_old[old_txt]
        start_c, end_c = analyzer._get_utf16_range(f'old "{old_txt}"', old_txt)
        analyzer._add_diagnostic(
            Diagnostic(
                file_path=file_path,
                line_number=old_line,
                line_content=f'old "{old_txt}"',
                code="RPY801",
                message=(
                    f"Duplicate translation source: 'old \"{old_txt}\"' was already "
                    f"defined on line {first_line}. The second definition silently "
                    f"overrides the first — the first translation is dead code. "
                    f"Consolidate or remove the duplicate."
                ),
                severity="WARNING",
                col=start_c,
                end_col=end_c,
            ),
            noqa_map,
        )
        duplicate_reported.add(old_txt)
    elif old_txt not in seen_old:
        seen_old[old_txt] = old_line


def check_cross_language_consistency(analyzer: SenpyAnalyzer, tl_files: list[str]) -> None:
    """RPY802: Check cross-language translation consistency.

    Thin dispatcher (REF-009): delegates to _build_lang_map + _find_inconsistencies.
    Was CC=18, 104 lines → CC=2, ~10 lines.
    """
    lang_translations = _build_lang_map(tl_files)
    _find_and_emit_inconsistencies(analyzer, lang_translations, tl_files)


def _build_lang_map(tl_files: list[str]) -> dict[str, dict[str, set[str]]]:
    """Build language → {old_txt → set of new_txt translations} from all TL files."""
    lang_translations: dict[str, dict[str, set[str]]] = {}

    for tl_file in tl_files:
        lang = _extract_lang_from_path(tl_file)
        try:
            with open(tl_file, encoding="utf-8", newline="") as f:
                lines = f.readlines()
        except (OSError, UnicodeDecodeError):
            continue

        pairs = parse_tl_pairs(lines)
        if lang not in lang_translations:
            lang_translations[lang] = {}

        for old_txt, _old_line, new_txt, _new_line in pairs:
            if old_txt not in lang_translations[lang]:
                lang_translations[lang][old_txt] = set()
            lang_translations[lang][old_txt].add(new_txt)

    return lang_translations


def _extract_lang_from_path(tl_file: str) -> str:
    """Extract language code from path: .../tl/<lang>/file.rpy → <lang>."""
    norm = normalize_path(tl_file).replace("\\", "/")
    parts = norm.split("/")
    try:
        tl_idx = parts.index("tl")
        return parts[tl_idx + 1] if tl_idx + 1 < len(parts) else "unknown"
    except (ValueError, IndexError):
        return "unknown"


def _find_and_emit_inconsistencies(
    analyzer: SenpyAnalyzer,
    lang_translations: dict[str, dict[str, set[str]]],
    tl_files: list[str],
) -> None:
    """Flag old_txt with multiple DIFFERENT translations within the same language."""
    for lang, translations in lang_translations.items():
        for old_txt, new_variants in translations.items():
            non_empty = {t for t in new_variants if t.strip()}
            if len(non_empty) > 1:
                diag_file, diag_line = _find_first_occurrence(old_txt, lang, tl_files)
                variants_str = " | ".join(f'"{v}"' for v in sorted(non_empty))
                analyzer._add_diagnostic_by_file(
                    Diagnostic(
                        file_path=diag_file,
                        line_number=diag_line,
                        line_content=f'old "{old_txt}"',
                        code="RPY802",
                        message=(
                            f"Inconsistent translation in language '{lang}': "
                            f"source '{old_txt}' is translated as: {variants_str}. "
                            f"Pick one translation and use it consistently across all files "
                            f"in this language directory."
                        ),
                        severity="WARNING",
                    )
                )


def _find_first_occurrence(old_txt: str, lang: str, tl_files: list[str]) -> tuple[str, int]:
    """Find the first file/line where old_txt appears in the given language."""
    for tl_file in tl_files:
        file_lang = _extract_lang_from_path(tl_file)
        if file_lang != lang:
            continue
        try:
            with open(tl_file, encoding="utf-8", newline="") as f:
                file_lines = f.readlines()
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(file_lines, start=1):
            if f'old "{old_txt}"' in line or f"old '{old_txt}'" in line:
                return tl_file, i
    return "<unknown>", 0
