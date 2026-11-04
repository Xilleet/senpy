"""FileCollector — file discovery and I/O utilities extracted from SenpyAnalyzer.

Manages:
  - .rpy file discovery (os.walk, IGNORED_DIRS, tl/ detection)
  - File reading (in-memory, stage1 cache, disk)
  - noqa comment parsing (# noqa: RPY001, RPY002)
  - noqa map building (line→codes)
  - Encoding error emission (RPY100)
  - Logical line joining (multi-line via backslash or unclosed brackets)

These are pure utility functions that don't touch symbol registries.
The symbol collection logic (_collect_symbols, _collect_default, etc.)
stays in SenpyAnalyzer for now — it will be extracted in Step 2c.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from senpy.core.constants import IGNORED_DIRS, RE_NOQA
from senpy.core.models import Diagnostic
from senpy.core.paths import normalize_path

if TYPE_CHECKING:
    pass


def discover_rpy_files(project_path: str) -> tuple[list[str], list[str]]:
    """Walk the project directory and return (main_rpy_files, tl_rpy_files).

    Separates files in game/tl/ directories (translation files) from
    main script files. Files are sorted for deterministic traversal order.
    """
    main_files: list[str] = []
    tl_files: list[str] = []
    for root, dirs, filenames in os.walk(project_path, followlinks=False):
        dirs[:] = sorted([d for d in dirs if d not in IGNORED_DIRS])
        rel_parts = os.path.relpath(root, project_path).replace("\\", "/").split("/")
        is_tl_dir = "tl" in rel_parts

        for f in sorted(filenames):
            if f.endswith((".rpy", "_ren.py")):
                full_p = os.path.join(root, f)
                if is_tl_dir:
                    tl_files.append(full_p)
                else:
                    main_files.append(full_p)
    return sorted(main_files), sorted(tl_files)


def parse_noqa(line: str) -> tuple[bool, set[str] | None]:
    """Parse a `# noqa` comment from a line.

    Returns (has_noqa, codes_or_None):
      - (False, None) if no noqa comment
      - (True, None) if bare `# noqa` (suppress all)
      - (True, {"RPY001", "RPY002"}) if `# noqa: RPY001, RPY002`
    """
    m = RE_NOQA.search(line)
    if not m:
        return False, None
    codes_str = m.group(1) or m.group(2)
    if codes_str:
        codes = {c.strip().upper() for c in codes_str.split(",") if c.strip()}
        return True, codes
    return True, None


def build_noqa_map(lines: list[str]) -> dict[int, set[str] | None]:
    """Pre-parse all `# noqa` comments in the file into a line→codes map."""
    noqa_map: dict[int, set[str] | None] = {}
    for line_no, raw_line in enumerate(lines, start=1):
        has_noqa, codes = parse_noqa(raw_line)
        if has_noqa:
            noqa_map[line_no] = codes
    return noqa_map


def emit_encoding_error(
    file_path: str, err: UnicodeDecodeError, diagnostics: list[Diagnostic]
) -> None:
    """Emit RPY100 diagnostic for a file that is not valid UTF-8.

    Previously the decode error was swallowed by `except: pass` — the linter
    silently skipped the file and reported "clean", although Ren'Py will crash
    when loading such a script.
    """
    diagnostics.append(
        Diagnostic(
            file_path=file_path,
            line_number=1,
            line_content="",
            code="RPY100",
            severity="ERROR",
            message=(
                f"File is not valid UTF-8 ({err.reason} at byte offset {err.start}). "
                "Ren'Py requires UTF-8 script files: the game will fail to load it. "
                "Re-save the file with UTF-8 encoding."
            ),
        )
    )


def read_file_lines(
    file_path: str,
    in_memory_files: dict[str, str],
    stage1_lines: dict[str, list[str]],
) -> list[str] | None:
    """Read file lines: in-memory first, then stage1 cache, then disk.

    Returns None if the file can't be read (encoding error, OS error).
    Pops from stage1_lines cache if found (single-use).
    """
    try:
        norm_path = normalize_path(file_path)
        if norm_path in in_memory_files:
            return in_memory_files[norm_path].splitlines(keepends=True)
        elif norm_path in stage1_lines:
            return stage1_lines.pop(norm_path)
        else:
            with open(file_path, encoding="utf-8", newline="") as f:
                return f.readlines()
    except (UnicodeDecodeError, OSError):
        return None
