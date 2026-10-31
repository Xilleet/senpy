"""Translation file analysis: RPY601/602/603.

Extracted from core/analyzer.py in 0.6.6 to reduce analyzer god-class.
Handles .rpy translation files (game/tl/) — validates variable interpolation,
formatting tags, and empty translations.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from typing import TYPE_CHECKING

from senpy.core.constants import NON_DIALOGUE_STATEMENTS
from senpy.core.models import Diagnostic

if TYPE_CHECKING:
    from senpy.core.analyzer import SenpyAnalyzer


def analyze_tl_file(analyzer: SenpyAnalyzer, file_path: str) -> None:
    """Analyze a translation (.rpy) file for RPY601/602/603 issues.

    Reads the file (or in-memory content), parses old/new translation pairs,
    and validates them. Appends diagnostics to analyzer.diagnostics.
    """
    try:
        norm_path = os.path.normcase(os.path.abspath(file_path))
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
    validate_tl_pairs(analyzer, pairs, file_path)


def parse_tl_pairs(lines: list[str]) -> list[tuple[str, int, str, int]]:
    """State machine that collects safe pairs:
    (source_text, old_line, translation_text, new_line)

    Robust to comments, blank lines, voice/with, and missing new.
    """
    re_old = re.compile(
        r'^\s*old\s+("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')'
    )
    re_new = re.compile(
        r'^\s*new\s+("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')'
    )
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
) -> None:
    """Validate translation pairs for RPY601/602/603."""
    re_var = re.compile(r"\[([^\W\d]\w*)(?:![a-zA-Z]+)?\]")
    re_tag = re.compile(r"\{(/?[a-zA-Z_]+)(?:=[^}]*)?\}")

    for old_txt, old_line, new_txt, new_line in pairs:
        # Mask escaped brackets \[ and \{
        old_masked = re.sub(r"\\.|(\{\{|\}\}|\[\[|\]\])", "  ", old_txt)
        new_masked = re.sub(r"\\.|(\{\{|\}\}|\[\[|\]\])", "  ", new_txt)

        # RPY603: Empty translation
        if old_txt.strip() and not new_txt.strip():
            start_c, end_c = analyzer._get_utf16_range(f'new "{new_txt}"', new_txt)
            analyzer.diagnostics.append(
                Diagnostic(
                    file_path=file_path,
                    line_number=new_line,
                    line_content=f'new "{new_txt}"',
                    code="RPY603",
                    message="Translation string is empty ('new \"\"'). Players will see blank text.",
                    severity="WARNING",
                    col=start_c,
                    end_col=end_c,
                )
            )
            continue

        # RPY601: Variable interpolation mismatch [var]
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

            start_c, end_c = analyzer._get_utf16_range(
                new_txt, next(iter(extra)) if extra else None
            )
            analyzer.diagnostics.append(
                Diagnostic(
                    file_path=file_path,
                    line_number=new_line,
                    line_content=new_txt,
                    code="RPY601",
                    message=f"Variable mismatch in translation ({'; '.join(diffs)}). Will crash with KeyError at runtime!",
                    severity="ERROR",
                    col=start_c,
                    end_col=end_c,
                )
            )

        # RPY602: Formatting tag mismatch {b}, {color}, etc.
        old_tags = Counter(re_tag.findall(old_masked))
        new_tags = Counter(re_tag.findall(new_masked))
        if old_tags != new_tags:
            analyzer.diagnostics.append(
                Diagnostic(
                    file_path=file_path,
                    line_number=new_line,
                    line_content=new_txt,
                    code="RPY602",
                    message="Formatting tags count or names do not match the original string. Text styles may break.",
                    severity="WARNING",
                )
            )
