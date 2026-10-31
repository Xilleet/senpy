from __future__ import annotations

import os
import re
from dataclasses import dataclass

from senpy.core.logging import get_logger

_logger = get_logger("traceback")


@dataclass
class CrashReport:
    file_path: str
    line_number: int
    code_line: str
    exception_type: str
    exception_message: str
    rule_code: str
    explanation: str


# Карта частых рантайм-падений Ren'Py в правила Senpy
CRASH_RULES = [
    (
        r"NameError:\s+name\s+'([^']+)'\s+is not defined",
        "RPY104",
        "Variable '{0}' was accessed or modified before being declared. Declare it via 'default {0} = ...' at top level.",
    ),
    (
        r"KeyError:\s+'([^']+)'",
        "RPY101",
        "Variable '[{0}]' inside dialogue interpolation does not exist in store, crashing text renderer.",
    ),
    (
        r"ScriptError:\s+could not find label\s+'([^']+)'",
        "RPY302",
        "Jump or Call executed to non-existent label '{0}'. Check for typos.",
    ),
    (
        r"Exception:\s+Screen\s+(\w+)\s+is not known",
        "RPY204",
        "Call or Show screen target '{0}' does not exist in project declarations.",
    ),
    (
        r"TypeError:\s+can only concatenate str.*to str",
        "RPY108",
        "Incompatible types: attempted to concatenate a string with a non-string variable (Type Taint).",
    ),
    (
        r"TypeError:\s+unsupported operand type\(s\) for \+=:\s+'([^']+)' and '([^']+)'",
        "RPY108",
        "Incompatible augmented assignment: operation between '{0}' and '{1}' is forbidden in Python.",
    ),
    (
        r"Exception:\s+Audio channel '([^']+)' is not registered",
        "RPY505",
        "Audio channel '{0}' is not registered via renpy.music.register_channel().",
    ),
]


def parse_traceback_file(file_path: str) -> CrashReport | None:
    """Парсит traceback.txt / errors.txt и сопоставляет его с семантикой Senpy."""
    if not os.path.isfile(file_path):
        return None

    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            content = f.read()

        # 1. Ищем место сбоя в коде игры (File "game/script.rpy", line 42, in ...)
        loc_match = re.search(
            r'File\s+["\']([^"\']+\.rpy)["\'],\s+line\s+(\d+)(?:,\s+in\s+([^\n]+))?\s*\n(?:\s+([^\n]+))?',
            content,
        )
        if not loc_match:
            return None

        rel_file = loc_match.group(1)
        line_num = int(loc_match.group(2))
        code_line = (loc_match.group(4) or "").strip()

        # 2. Ищем текст самого исключения
        exc_match = re.search(
            r"([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception)):\s*([^\n]+)",
            content,
        )
        exc_type = exc_match.group(1) if exc_match else "Exception"
        exc_msg = exc_match.group(2) if exc_match else "Unknown runtime error"

        # 3. Сопоставляем с правилами Senpy
        rule_code = "RUNTIME"
        explanation = "Game crashed at runtime. Inspect the indicated file and line."

        for pattern, r_code, expl_tmpl in CRASH_RULES:
            m = re.search(pattern, content)
            if m:
                rule_code = r_code
                groups = m.groups()
                explanation = expl_tmpl.format(*groups) if groups else expl_tmpl
                break

        return CrashReport(
            file_path=rel_file,
            line_number=line_num,
            code_line=code_line,
            exception_type=exc_type,
            exception_message=exc_msg,
            rule_code=rule_code,
            explanation=explanation,
        )
    except (OSError, UnicodeDecodeError) as e:
        # log debug instead of silent suppress.
        _logger.debug(
            "failed to read traceback file %s: %s", file_path, e
        )
        return None


def find_latest_traceback(project_path: str) -> str | None:
    """Ищет свежий traceback.txt или errors.txt в проекте."""
    candidates = [
        os.path.join(project_path, "traceback.txt"),
        os.path.join(project_path, "errors.txt"),
        os.path.join(os.path.dirname(project_path), "traceback.txt"),
        os.path.join(os.path.dirname(project_path), "errors.txt"),
        os.path.join(project_path, "game", "traceback.txt"),
        os.path.join(project_path, "game", "errors.txt"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None
