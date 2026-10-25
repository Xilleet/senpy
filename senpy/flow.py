from __future__ import annotations

import json
import re
from collections import deque
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
        lbl = self.analyzer.labels.get(label_name)
        if lbl and lbl.has_return:
            return True
        if visited is None:
            visited = set()
        if label_name in visited:
            return False
        visited.add(label_name)

        outgoing = lbl.outgoing_jumps if lbl else set()
        for target in outgoing:
            if self.can_reach_return(target, visited):
                return True
        return False

    def check_unreachable_labels(self) -> list[Diagnostic]:
        """RPY303: Выявляет метки, на которые нет статических ссылок (возможный dead code)."""
        diagnostics: list[Diagnostic] = []
        for label_name, lbl in self.analyzer.labels.items():
            clean_name = label_name.strip().lower()
            if clean_name.startswith("_") or clean_name in SYSTEM_LABELS:
                continue
            if label_name not in self.analyzer.referenced_labels:
                msg = f"No static references found to label '{label_name}'."
                if self.analyzer.has_dynamic_jumps:
                    msg += " Project uses dynamic routing, verify target reaches."
                else:
                    msg += " Verify if it is dead code or invoked dynamically."

                start_c, end_c = get_utf16_range(lbl.code_line, label_name)
                diagnostics.append(
                    Diagnostic(
                        file_path=lbl.file_path,
                        line_number=lbl.line_number,
                        line_content=lbl.code_line,
                        code="RPY303",
                        message=msg,
                        severity="INFO",
                        col=start_c,
                        end_col=end_c,
                    )
                )
        return diagnostics

    def check_story_islands(self) -> list[Diagnostic]:
        """RPY309: Находит изолированные подграфы (острова) и циклы, недостижимые из системных точек входа."""
        labels = self.analyzer.labels

        root_labels = {
            lbl for lbl in labels
            if lbl.lower() in SYSTEM_LABELS or lbl.startswith("_")
        }

        if not root_labels:
            return []

        reachable: set[str] = set()
        queue = deque(root_labels)
        reachable.update(root_labels)

        while queue:
            curr = queue.popleft()
            lbl_sym = labels.get(curr)
            outgoing = lbl_sym.outgoing_jumps if lbl_sym else set()
            for target in outgoing:
                if target in labels and target not in reachable:
                    reachable.add(target)
                    queue.append(target)

        diagnostics: list[Diagnostic] = []
        for label_name, lbl in labels.items():
            if label_name in reachable:
                continue
            if label_name.startswith("_") or label_name.lower() in SYSTEM_LABELS:
                continue

            has_incoming_jump = any(label_name in l.outgoing_jumps for l in labels.values())
            has_reference = label_name in self.analyzer.referenced_labels

            if has_incoming_jump or has_reference:
                msg = f"Story island detected: label '{label_name}' forms an isolated subgraph unreachable from 'start'."
                if self.analyzer.has_dynamic_jumps:
                    msg += " Project uses dynamic routing, verify reachability."
                start_c, end_c = get_utf16_range(lbl.code_line, label_name)
                diagnostics.append(
                    Diagnostic(
                        file_path=lbl.file_path,
                        line_number=lbl.line_number,
                        line_content=lbl.code_line,
                        code="RPY309",
                        message=msg,
                        severity="WARNING",
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
        branch_uninitialized: dict[str, tuple[str, ...]],
        noqa_map: dict,
    ) -> None:
        """RPY404: Проверяет [var] в тексте после меню с переменными в статусе MAYBE_SET."""
        from senpy.constants import RE_INTERPOLATION

        for match in RE_STRING_MATCH.finditer(line_content):
            s = match.group(0)
            for var in RE_INTERPOLATION.findall(s):
                if var in branch_uninitialized:
                    info = branch_uninitialized[var]
                    missing_choice = info[0]
                    menu_line = info[2] if len(info) > 2 else "earlier"
                    reason = missing_choice if ("branch" in missing_choice or "condition" in missing_choice) else f"player took choice '{missing_choice}'"
                    self.analyzer._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=line_idx,
                            line_content=line_content,
                            code="RPY404",
                            message=(
                                f"Variable '[{var}]' may be uninitialized (MAYBE_SET) if "
                                f"{reason} on line {menu_line}. Will cause KeyError or save crash."
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
    ) -> tuple[int, dict[str, tuple[str, ...]], set[str]]:
        from senpy.analyzer import _strip_comment
        from senpy.constants import RE_MENU_START

        idx = start_idx
        choices: list[dict] = []
        current_choice = None
        choice_indent: int | None = None
        uninitialized_vars: dict[str, tuple[str, ...]] = {}
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
            is_direct_choice = bool(
                m_choice
                and line_indent > menu_indent
                and (choice_indent is None or line_indent == choice_indent)
            )

            if is_direct_choice:
                if choice_indent is None:
                    choice_indent = line_indent

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

                if RE_MENU_START.match(raw_line):
                    consumed_idx, sub_uninit, sub_guaranteed = self.analyze_menu_flow(
                        lines,
                        idx + 1,
                        line_indent,
                        file_path=file_path,
                        noqa_map=noqa_map,
                    )
                    current_choice["defined"].update(sub_guaranteed)
                    uninitialized_vars.update(sub_uninit)
                    idx = consumed_idx
                    continue

                if stripped.startswith("$"):
                    py = stripped[1:].strip()
                    current_choice["defined"].update(extract_assigned_names(py))

                if re.match(r"^\s*(?:jump\b|return\b|\$?\s*renpy\.(?:quit|full_restart|utter_restart|jump|jump_out_of_context)\b)", stripped):
                    current_choice["terminates"] = True

            idx += 1

        if current_choice:
            check_empty_choice(current_choice)
            choices.append(current_choice)

        merging_choices = [c for c in choices if not c["terminates"]]

        if len(merging_choices) > 1:
            all_defined = set().union(*(c["defined"] for c in merging_choices))
            for var in all_defined:
                if var in self.analyzer.user_symbols:
                    continue

                missing_choice_dict = next(
                    (c for c in merging_choices if var not in c["defined"]),
                    None,
                )
                defined_choice_dict = next(
                    (c for c in merging_choices if var in c["defined"]),
                    None,
                )

                if missing_choice_dict and defined_choice_dict:
                    if file_path:
                        start_c, end_c = get_utf16_range(missing_choice_dict["raw"], missing_choice_dict["title"])
                        self.analyzer._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=missing_choice_dict["line"],
                                line_content=missing_choice_dict["raw"],
                                code="RPY401",
                                message=(
                                    f"Menu branch asymmetry: variable '{var}' is assigned in choice "
                                    f"'{defined_choice_dict['title']}' (line {defined_choice_dict['line']}), "
                                    f"but missing in '{missing_choice_dict['title']}'."
                                ),
                                col=start_c,
                                end_col=end_c,
                            ),
                            noqa_map,
                        )

                    uninitialized_vars[var] = (
                        missing_choice_dict["title"],
                        defined_choice_dict["title"],
                        str(missing_choice_dict["line"]),
                    )

        guaranteed_vars = (
            set.intersection(*(c["defined"] for c in merging_choices))
            if merging_choices
            else set()
        )

        return idx, uninitialized_vars, guaranteed_vars

    def generate_mermaid_graph(self) -> str:
        """Генерирует чистую Mermaid.js диаграмму графа сюжета новеллы."""
        lines = [
            "```mermaid",
            "graph TD",
            "    %% Generated by Senpy Linter (Story Flow Graph)",
        ]

        labels = self.analyzer.labels

        for label, lbl_sym in sorted(labels.items()):
            if label.startswith("_"):
                continue
            
            has_return = lbl_sym.has_return
            has_jumps = len(lbl_sym.outgoing_jumps) > 0
            
            if has_return:
                shape_start, shape_end = ("([", "])")
            elif not has_jumps:
                shape_start, shape_end = ("[[", "]]:::fallthrough")
            else:
                shape_start, shape_end = ('["', '"]')
                
            lines.append(f"    {label}{shape_start}{label}{shape_end}")

        lines.append("")

        edges_added = False
        for src, lbl_sym in sorted(labels.items()):
            if src.startswith("_"):
                continue
            for tgt in sorted(lbl_sym.outgoing_jumps):
                tgt_sym = labels.get(tgt)
                is_call = tgt_sym.has_return if tgt_sym else False
                arrow = "-- call -->" if is_call else "-->"

                if tgt in labels:
                    lines.append(f"    {src} {arrow} {tgt}")
                    edges_added = True
                else:
                    lines.append(f"    {src} -. jump .-> {tgt}:::missing")
                    edges_added = True

        if not edges_added:
            lines.append("    %% No static jumps detected")

        lines.append("\n    classDef missing fill:#ff4d4f,stroke:#333,stroke-width:1px,color:#fff;")
        lines.append("    classDef fallthrough fill:#faad14,stroke:#333,stroke-width:1px,color:#fff;")
        lines.append("```")

        meta = {"locations": {}}
        for lbl_name, lbl_sym in labels.items():
            meta["locations"][lbl_name] = {"file": lbl_sym.file_path.replace("\\", "/"), "line": lbl_sym.line_number, "type": "label"}

        for src, lbl_sym in labels.items():
            for tgt in lbl_sym.outgoing_jumps:
                if tgt not in labels and tgt in self.analyzer.jump_sources:
                    sources = self.analyzer.jump_sources[tgt]
                    if sources:
                        meta["locations"][tgt] = {
                            "file": sources[0][0].replace("\\", "/"),
                            "line": sources[0][1],
                            "type": "missing_jump",
                        }

        lines.append("\n```senpy-meta")
        lines.append(json.dumps(meta, ensure_ascii=False))
        lines.append("```")

        return "\n".join(lines)