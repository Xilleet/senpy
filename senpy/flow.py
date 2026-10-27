from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from senpy.constants import (
    BUILTIN_SCREENS,
    RE_MENU_CHOICE,
    RE_STRING_MATCH,
    SYSTEM_LABELS,
)
from senpy.models import Diagnostic
from senpy.python_ast import extract_assigned_names
from senpy.text_tags import get_utf16_range

if TYPE_CHECKING:
    from senpy.analyzer import SenpyAnalyzer

_MERMAID_RESERVED_IDS = {"end"}


def _mermaid_safe_id(name: str) -> str:
    """Имя метки/экрана -> валидный id узла Mermaid.

    \\W юникодный: кириллица сохраняется, точки саб-меток -> "_".
    Зарезервированное слово end получает суффикс, иначе Mermaid
    трактует его как закрытие subgraph и ломает парсинг.
    Ограничение: санитизация может коллидировать (chapter.start и
    chapter_start дадут один узел) — принято осознанно.
    """
    safe = re.sub(r"\W", "_", name)
    if safe in _MERMAID_RESERVED_IDS:
        safe += "_"
    return safe

def _mermaid_node_ref(name: str) -> str:
    """Ссылка на узел в ребре: голый id, если санитизация имя не меняла
    (байт-совместимость со старым выводом), иначе id + кавычканный
    текст с сырым именем."""
    sid = _mermaid_safe_id(name)
    return sid if sid == name else f'{sid}["{name}"]'

@dataclass
class FlowBranch:
    """Представляет одну ветку развилки (choice в menu: или if/elif/else)."""
    kind: str                      # "choice", "if", "elif", "else"
    name: str                      # Название выбора или описание ветки
    line: int                      # Номер строки
    defined_vars: set[str] = field(default_factory=set)
    terminates: bool = False
    raw: str = ""


def merge_flow_branches(
    branches: list[FlowBranch],
    block_kind: str,
    block_line: int,
    has_else: bool,
    known_symbols: set[str],
    already_guaranteed: set[str],
) -> tuple[set[str], dict[str, tuple[str, ...]], bool]:
    """
    Унифицированное слияние параллельных веток (if/elif/else или menu:).
    Возвращает:
      - guaranteed_vars: переменные, гарантированно заданные во всех нетерминирующих путях
      - uninitialized_vars: словарь переменных MAYBE_SET с метаданными о пропущенной ветке
      - all_terminating: True, если абсолютно все ветки выходят через jump/return
    """
    non_terminating = [b for b in branches if not b.terminates]
    if not non_terminating:
        return set(), {}, True

    if block_kind == "menu":
        guaranteed = set.intersection(*(b.defined_vars for b in non_terminating)) if non_terminating else set()
    else:  # "if"
        if has_else and len(branches) > 1:
            guaranteed = set.intersection(*(b.defined_vars for b in non_terminating))
        else:
            guaranteed = set()

    all_defined = set().union(*(b.defined_vars for b in branches))
    maybe_set = all_defined - guaranteed
    uninitialized: dict[str, tuple[str, ...]] = {}

    for var in sorted(maybe_set):
        if var in known_symbols or var in already_guaranteed:
            continue

        missing_b = next((b for b in branches if var not in b.defined_vars), None)
        defined_b = next((b for b in branches if var in b.defined_vars), None)

        if block_kind == "if":
            if not has_else:
                missing_desc = "condition is False (no else branch)"
                missing_line = block_line
            elif missing_b:
                missing_desc = f"{missing_b.kind} branch was taken"
                missing_line = missing_b.line
            else:
                missing_desc = "alternate branch was taken"
                missing_line = block_line
            defined_desc = f"{defined_b.kind} branch" if defined_b else "if branch"
        else:
            missing_desc = missing_b.name if missing_b else "alternate choice"
            defined_desc = defined_b.name if defined_b else "menu choice"
            missing_line = missing_b.line if missing_b else block_line

        uninitialized[var] = (missing_desc, defined_desc, str(missing_line))

    return guaranteed, uninitialized, False

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
        return any(self.can_reach_return(target, visited) for target in outgoing)

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

        # экраны как мосты графа. Корневые экраны — встроенные (движок
        # показывает их сам) плюс все экраны со статическими ссылками
        # (show screen / call screen / use / Show / ShowMenu).
        root_screens = BUILTIN_SCREENS | self.analyzer.used_screens
        screen_targets: set[str] = set()
        for scr_name in root_screens:
            screen_targets.update(self.analyzer.screen_action_jumps.get(scr_name, ()))

        reachable: set[str] = set()
        queue = deque(root_labels)
        reachable.update(root_labels)

        # Экшены Jump/Call из доступных экранов открывают новые метки
        for target in screen_targets:
            if target in labels and target not in reachable:
                reachable.add(target)
                queue.append(target)

        while queue:
            curr = queue.popleft()
            lbl_sym = labels.get(curr)
            outgoing = lbl_sym.outgoing_jumps if lbl_sym else set()
            for target in outgoing:
                if target in labels and target not in reachable:
                    reachable.add(target)
                    queue.append(target)

        incoming_jumps: dict[str, set[str]] = {}
        for src_name, src_lbl in labels.items():
            for tgt in src_lbl.outgoing_jumps:
                incoming_jumps.setdefault(tgt, set()).add(src_name)

        diagnostics: list[Diagnostic] = []
        for label_name, lbl in labels.items():
            if label_name in reachable:
                continue
            if label_name.startswith("_") or label_name.lower() in SYSTEM_LABELS:
                continue

            has_incoming_jump = label_name in incoming_jumps
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
    ) -> tuple[int, dict[str, tuple[str, ...]], set[str], bool]:
        from senpy.analyzer import _strip_comment
        from senpy.constants import RE_MENU_START

        idx = start_idx
        choices: list[FlowBranch] = []
        current_choice: FlowBranch | None = None
        choice_indent: int | None = None
        statement_counts: dict[int, int] = {}
        uninitialized_vars: dict[str, tuple[str, ...]] = {}
        noqa_map = noqa_map or {}

        def check_empty_choice(branch: FlowBranch | None):
            if branch and statement_counts.get(id(branch), 0) == 0 and file_path:
                start_c, end_c = get_utf16_range(branch.raw, branch.name)
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=branch.line,
                        line_content=branch.raw,
                        code="RPY402",
                        message=f"Menu choice '{branch.name}' has no statements inside and will immediately fall through.",
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

                current_choice = FlowBranch(
                    kind="choice",
                    name=m_choice.group(2).strip("\"'"),
                    line=idx + 1,
                    raw=stripped,
                )
                statement_counts[id(current_choice)] = 0
                idx += 1
                continue

            if current_choice and line_indent > choice_indent:
                statement_counts[id(current_choice)] = statement_counts.get(id(current_choice), 0) + 1

                if RE_MENU_START.match(raw_line):
                    consumed_idx, sub_uninit, sub_guaranteed, sub_term = self.analyze_menu_flow(
                        lines,
                        idx + 1,
                        line_indent,
                        file_path=file_path,
                        noqa_map=noqa_map,
                    )
                    current_choice.defined_vars.update(sub_guaranteed)
                    uninitialized_vars.update(sub_uninit)
                    if sub_term:
                        current_choice.terminates = True
                    idx = consumed_idx
                    continue

                if stripped.startswith("$"):
                    py = stripped[1:].strip()
                    current_choice.defined_vars.update(extract_assigned_names(py))

                if re.match(r"^\s*(?:jump\b|return\b|\$?\s*renpy\.(?:quit|full_restart|utter_restart|jump|jump_out_of_context)\b)", stripped):
                    current_choice.terminates = True

            idx += 1

        if current_choice:
            check_empty_choice(current_choice)
            choices.append(current_choice)

        merging_choices = [c for c in choices if not c.terminates]

        # RPY401: Диагностика асимметрии между нетерминирующими ветками меню
        if len(merging_choices) > 1:
            all_defined = set().union(*(c.defined_vars for c in merging_choices))
            for var in all_defined:
                if var in self.analyzer.user_symbols or var in self.analyzer.declared_symbols:
                    continue

                missing_b = next((c for c in merging_choices if var not in c.defined_vars), None)
                defined_b = next((c for c in merging_choices if var in c.defined_vars), None)

                if missing_b and defined_b and file_path:
                    start_c, end_c = get_utf16_range(missing_b.raw, missing_b.name)
                    self.analyzer._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=missing_b.line,
                            line_content=missing_b.raw,
                            code="RPY401",
                            message=(
                                f"Menu branch asymmetry: variable '{var}' is assigned in choice "
                                f"'{defined_b.name}' (line {defined_b.line}), "
                                f"but missing in '{missing_b.name}'."
                            ),
                            col=start_c,
                            end_col=end_c,
                        ),
                        noqa_map,
                    )

        # Унифицированное слияние состояния
        guaranteed_vars, merged_uninit, all_terminates = merge_flow_branches(
            branches=choices,
            block_kind="menu",
            block_line=start_idx,
            has_else=True,
            known_symbols=self.analyzer.user_symbols,
            already_guaranteed=set(),
        )
        uninitialized_vars.update(merged_uninit)

        return idx, uninitialized_vars, guaranteed_vars, all_terminates

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
                shape_start, shape_end = ('(["', '"])')
            elif not has_jumps:
                shape_start, shape_end = ('[["', '"]]:::fallthrough')
            else:
                shape_start, shape_end = ('["', '"]')
            lines.append(f"    {_mermaid_safe_id(label)}{shape_start}{label}{shape_end}")

        # --- Экраны: узлы (follow-up; префикс screen_ разводит
        # id-пространства label/screen в Mermaid) ---
        screens_registry = self.analyzer.screens
        screen_action_jumps = getattr(self.analyzer, "screen_action_jumps", {}) or {}
        used_screens = getattr(self.analyzer, "used_screens", set()) or set()
        # источники screen_uses (лейблы с call/show screen и экраны
        # с use) — тоже участники графа, их узлы должны существовать
        screen_uses = getattr(self.analyzer, "screen_uses", {}) or {}
        graph_screens = sorted(
            (set(screen_action_jumps) | set(used_screens) | set(screen_uses))
            & set(screens_registry)
        )
        for scr in graph_screens:
            lines.append(f'    screen_{_mermaid_safe_id(scr)}{{"screen: {scr}"}}:::screen')

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
                    lines.append(f"    {_mermaid_safe_id(src)} {arrow} {_mermaid_safe_id(tgt)}")
                    edges_added = True
                else:
                    lines.append(f'    {_mermaid_safe_id(src)} -. jump .-> {_mermaid_node_ref(tgt)}:::missing')
                    edges_added = True

        # --- Экраны: рёбра Jump-экшенов (существующая метка = сплошное,
        # отсутствующая = пунктир с классом missing) ---
        for scr in graph_screens:
            for tgt in sorted(screen_action_jumps.get(scr, ())):
                if tgt in labels:
                    lines.append(f"    screen_{_mermaid_safe_id(scr)} -- action --> {_mermaid_safe_id(tgt)}")
                else:
                    lines.append(f"    screen_{_mermaid_safe_id(scr)} -. action .-> {_mermaid_node_ref(tgt)}:::missing")
                edges_added = True

        # --- рёбра label -- call screen --> screen и screen -- use --> screen ---
        for src_name in sorted(screen_uses):
            if src_name.startswith("_"):
                continue
            for tgt in sorted(screen_uses[src_name]):
                if tgt not in screens_registry:
                    continue  # несуществующие экраны — территория RPY204
                if src_name in labels:
                    lines.append(f"    {src_name} -- call screen --> screen_{tgt}")
                    edges_added = True
                elif src_name in screens_registry:
                    lines.append(f"    screen_{src_name} -- use --> screen_{tgt}")
                    edges_added = True


        if not edges_added:
            lines.append("    %% No static jumps detected")

        lines.append("\n    classDef missing fill:#ff4d4f,stroke:#333,stroke-width:1px,color:#fff;")
        lines.append("    classDef fallthrough fill:#faad14,stroke:#333,stroke-width:1px,color:#fff;")
        lines.append("    classDef screen fill:#1890ff,stroke:#333,stroke-width:1px,color:#fff;")
        lines.append("```")

        meta = {"locations": {}}
        for lbl_name, lbl_sym in labels.items():
            meta["locations"][lbl_name] = {"file": lbl_sym.file_path.replace("\\", "/"), "line": lbl_sym.line_number, "type": "label"}

        # Координаты экранов для навигации из senpy-meta
        for scr in graph_screens:
            scr_sym = screens_registry.get(scr)
            if scr_sym is not None:
                meta["locations"][f"screen_{scr}"] = {
                    "file": scr_sym.file_path.replace("\\", "/"),
                    "line": scr_sym.line_number,
                    "type": "screen",
                }

        for src, lbl_sym in labels.items():  # noqa: B007
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
