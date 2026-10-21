from __future__ import annotations

import re
from typing import TYPE_CHECKING

from senpy.constants import RE_MENU_CHOICE, RE_STRING_MATCH, SYSTEM_LABELS
from senpy.models import Diagnostic
from senpy.python_ast import extract_assigned_names
from senpy.text_tags import get_utf16_range

if TYPE_CHECKING:
    from senpy.analyzer import SenpyAnalyzer


class StoryFlowAnalyzer:
    """Анализирует граф переходов, развилки меню и генерирует Mermaid-диаграммы сюжета."""

    def __init__(self, analyzer: SenpyAnalyzer):
        self.analyzer = analyzer

    def can_reach_return(self, label_name: str, visited: set[str] | None = None) -> bool:
        """RPY306: DFS-поиск пути от вызванной метки до оператора return."""
        if label_name in self.analyzer.labels_with_return:
            return True
        if visited is None:
            visited = set()
        if label_name in visited:
            return False
        visited.add(label_name)

        for target in self.analyzer.label_outgoing_jumps.get(label_name, set()):
            if self.can_reach_return(target, visited):
                return True
        return False

    def check_unreachable_labels(self) -> list[Diagnostic]:
        """RPY303: Выявляет метки, на которые нет статических ссылок (возможный dead code)."""
        diagnostics: list[Diagnostic] = []
        for label_name, (file_path, line_idx, content) in self.analyzer.declared_labels.items():
            clean_name = label_name.strip().lower()
            if clean_name.startswith("_") or clean_name in SYSTEM_LABELS:
                continue
            if label_name not in self.analyzer.referenced_labels:
                msg = f"No static references found to label '{label_name}'."
                if self.analyzer.has_dynamic_jumps:
                    msg += " Project uses dynamic routing, verify target reaches."
                else:
                    msg += " Verify if it is dead code or invoked dynamically."

                start_c, end_c = get_utf16_range(content, label_name)
                diagnostics.append(
                    Diagnostic(
                        file_path=file_path,
                        line_number=line_idx,
                        line_content=content,
                        code="RPY303",
                        message=msg,
                        severity="INFO",
                        col=start_c,
                        end_col=end_c,
                    )
                )
        return diagnostics

    def check_cfg_interpolations(
        self,
        file_path: str,
        line_idx: int,
        line_content: str,
        branch_uninitialized: dict[str, tuple[str, str]],
        noqa_map: dict,
    ) -> None:
        """RPY401: Проверяет [var] в тексте после меню с несбалансированными переменными."""
        from senpy.constants import RE_INTERPOLATION

        matches = RE_STRING_MATCH.findall(line_content)
        for double_q, _, single_q, _ in matches:
            s = double_q if double_q else single_q
            for var in RE_INTERPOLATION.findall(s):
                if var in branch_uninitialized:
                    missing_choice, defined_choice = branch_uninitialized[var]
                    self.analyzer._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=line_idx,
                            line_content=line_content,
                            code="RPY401",
                            message=(
                                f"Variable '[{var}]' is only defined in menu choice '{defined_choice}', "
                                f"but missing in '{missing_choice}'. Taking '{missing_choice}' will cause KeyError."
                            ),
                        ),
                        noqa_map,
                    )

    def analyze_menu_flow(
        self,
        lines: list[str],
        start_idx: int,
        menu_indent: int,
        file_path: str = "",
        noqa_map: dict | None = None,
    ) -> tuple[int, dict[str, tuple[str, str]]]:
        """RPY402, RPY401: Разбирает пункты menu:, ловит пустые выборы и несбалансированные переменные."""
        from senpy.analyzer import _strip_comment

        idx = start_idx
        choices: list[dict] = []
        current_choice = None
        noqa_map = noqa_map or {}

        def check_empty_choice(choice_dict):
            if choice_dict and choice_dict["statement_count"] == 0 and file_path:
                raw_full = choice_dict.get("raw_full", choice_dict["raw"])
                start_c, end_c = get_utf16_range(raw_full, choice_dict["title"])
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=choice_dict["line"],
                        line_content=choice_dict["raw"],
                        code="RPY402",
                        message=f"Menu choice '{choice_dict['title']}' has no statements inside and will immediately fall through.",
                        col=start_c,
                        end_col=end_c,
                    ),
                    noqa_map,
                )

        while idx < len(lines):
            raw_line = lines[idx]
            stripped = _strip_comment(raw_line).strip()
            line_indent = len(raw_line) - len(raw_line.lstrip(" "))

            if not stripped:
                idx += 1
                continue

            if line_indent <= menu_indent:
                break

            m_choice = RE_MENU_CHOICE.match(raw_line)
            if m_choice and line_indent > menu_indent:
                if current_choice:
                    check_empty_choice(current_choice)
                    choices.append(current_choice)
                current_choice = {
                    "title": m_choice.group(2).strip("\"'"),
                    "indent": line_indent,
                    "defined": set(),
                    "terminates": False,
                    "statement_count": 0,
                    "line": idx + 1,
                    "raw": stripped,
                    "raw_full": raw_line,
                }
                idx += 1
                continue

            if current_choice and line_indent > current_choice["indent"]:
                current_choice["statement_count"] += 1
                if stripped.startswith("$"):
                    py = stripped[1:].strip()
                    current_choice["defined"].update(extract_assigned_names(py))
                if re.match(r"^\s*(jump\b|return\b)", stripped):
                    current_choice["terminates"] = True

            idx += 1

        if current_choice:
            check_empty_choice(current_choice)
            choices.append(current_choice)

        merging_choices = [c for c in choices if not c["terminates"]]
        uninitialized_vars: dict[str, tuple[str, str]] = {}

        if len(merging_choices) > 1:
            all_defined = set().union(*(c["defined"] for c in merging_choices))
            for var in all_defined:
                if var in self.analyzer.user_symbols:
                    continue

                defined_choice = next(
                    c["title"] for c in merging_choices if var in c["defined"]
                )
                missing_choice = next(
                    (c["title"] for c in merging_choices if var not in c["defined"]),
                    None,
                )

                if missing_choice:
                    uninitialized_vars[var] = (missing_choice, defined_choice)

        return idx, uninitialized_vars

    def generate_mermaid_graph(self) -> str:
        """Генерирует чистую Mermaid.js диаграмму графа сюжета новеллы."""
        lines = [
            "```mermaid",
            "graph TD",
            "    %% Generated by Senpy Linter (Story Flow Graph)",
        ]

        declared = self.analyzer.declared_labels
        outgoing = self.analyzer.label_outgoing_jumps

        # Объявляем узлы
        for label in sorted(declared.keys()):
            if label.startswith("_"):
                continue
            has_return = label in self.analyzer.labels_with_return
            shape_start, shape_end = ("([", "])") if has_return else ('["', '"]')
            lines.append(f"    {label}{shape_start}{label}{shape_end}")

        lines.append("")

        # Добавляем ребра (переходы)
        edges_added = False
        for src, targets in sorted(outgoing.items()):
            if src.startswith("_"):
                continue
            for tgt in sorted(targets):
                if tgt in declared:
                    lines.append(f"    {src} --> {tgt}")
                    edges_added = True
                else:
                    # Прыжок на несуществующую метку выделяем пунктиром
                    lines.append(f"    {src} -.-> {tgt}:::missing")
                    edges_added = True

        if not edges_added:
            lines.append("    %% No static jumps detected")

        # Стили для отсутствующих меток
        lines.append("\n    classDef missing fill:#ff4d4f,stroke:#333,stroke-width:1px,color:#fff;")
        lines.append("```")
        return "\n".join(lines)