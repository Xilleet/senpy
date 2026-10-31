"""Dead code detection: RPY701/702/703 (unused define/transform/screen).

Extracted from core/analyzer.py in 0.6.6 to reduce analyzer god-class.
The function takes an analyzer instance and appends diagnostics directly.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from typing import TYPE_CHECKING

from senpy.core.constants import BUILTIN_SCREENS, BUILTIN_SYMBOLS
from senpy.core.models import Diagnostic

if TYPE_CHECKING:
    from senpy.core.analyzer import SenpyAnalyzer

# Pre-compiled regex for word tokenization.
_WORD_RE = re.compile(r"\w+")


def check_unused_declarations(analyzer: SenpyAnalyzer) -> None:
    """RPY701-703: Find unused define/transform/screen declarations (dead code).

    Disabled if the project has dynamic jumps (can't track references reliably).
    Uses a pre-built word → {(file, line_idx)} index in a single pass
    over all files — O(total_words + symbols) instead of O(symbols × total_lines).

    PERF-2: the initial implementation on DDLC (50 files, 77k lines, ~200 symbols)
    was hanging for minutes.
    """
    if analyzer.has_dynamic_jumps:
        return

    # Step 1: Build word → set of (norm_path, line_idx_0based) index in one pass.
    word_locations: dict[str, set[tuple[str, int]]] = defaultdict(set)
    for norm_path in analyzer.file_scopes:
        lines = analyzer._stage1_lines.get(norm_path)
        if lines is None:
            try:
                with open(norm_path, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except OSError:
                continue
            analyzer._stage1_lines[norm_path] = lines
        for i, line in enumerate(lines):
            for word in _WORD_RE.findall(line):
                word_locations[word].add((norm_path, i))

    def _is_used(name: str, decl_file: str, decl_line: int) -> bool:
        """O(1) lookup: name is used if it appears outside its declaration line."""
        decl_norm = os.path.normcase(os.path.abspath(decl_file))
        decl_loc = (decl_norm, decl_line - 1)
        locations = word_locations.get(name)
        if not locations:
            return False
        if len(locations) > 1:
            return True
        return decl_loc not in locations

    # RPY701: Unused define constants
    for name, var_sym in analyzer.variables.items():
        if not var_sym.is_constant:
            continue
        if var_sym.is_character:
            continue
        if not _is_used(name, var_sym.file_path, var_sym.line_number):
            analyzer.diagnostics.append(
                Diagnostic(
                    file_path=var_sym.file_path,
                    line_number=var_sym.line_number,
                    line_content=var_sym.code_line,
                    code="RPY701",
                    message=f"Constant '{name}' is declared with 'define' but never used. Consider removing this dead code.",
                    severity="HINT",
                )
            )

    # RPY702: Unused transforms
    for name, trn_sym in analyzer.transforms.items():
        if name in BUILTIN_SYMBOLS:
            continue
        if not _is_used(name, trn_sym.file_path, trn_sym.line_number):
            analyzer.diagnostics.append(
                Diagnostic(
                    file_path=trn_sym.file_path,
                    line_number=trn_sym.line_number,
                    line_content=trn_sym.code_line,
                    code="RPY702",
                    message=f"Transform '{name}' is defined but never used in 'show/scene at'. Consider removing this dead code.",
                    severity="HINT",
                )
            )

    # RPY703: Unused screens
    for name, scr_sym in analyzer.screens.items():
        if name in BUILTIN_SCREENS:
            continue
        if not _is_used(name, scr_sym.file_path, scr_sym.line_number):
            analyzer.diagnostics.append(
                Diagnostic(
                    file_path=scr_sym.file_path,
                    line_number=scr_sym.line_number,
                    line_content=f"screen {name}():",
                    code="RPY703",
                    message=f"Screen '{name}' is defined but never called or shown. Consider removing this dead code.",
                    severity="HINT",
                )
            )
