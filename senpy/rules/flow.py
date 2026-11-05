from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from senpy.core.constants import (
    BUILTIN_SCREENS,
    RE_MENU_CHOICE,
    RE_STRING_MATCH,
    SYSTEM_LABELS,
)
from senpy.core.models import Diagnostic
from senpy.domain.text_tags import get_utf16_range
from senpy.rules.python_ast import extract_assigned_names

if TYPE_CHECKING:
    from senpy.core.protocols import DiagnosticSinkAndSymbols
    from senpy.core.symbols import LabelSymbol

_MERMAID_RESERVED_IDS = {"end"}


def _mermaid_safe_id(name: str) -> str:
    """Label/screen name -> valid Mermaid node id.

    \\W is unicode-aware: Cyrillic is preserved, dots of sub-labels -> "_".
    The reserved word end receives a suffix, otherwise Mermaid
    treats it as a subgraph closing and breaks parsing.
    Limitation: sanitization may collide (chapter.start and
    chapter_start yield the same node) — accepted consciously.
    """
    safe = re.sub(r"\W", "_", name)
    if safe in _MERMAID_RESERVED_IDS:
        safe += "_"
    return safe


def _mermaid_node_ref(name: str) -> str:
    """Reference to a node in an edge: bare id if sanitization
    did not change the name (byte-comparable with old output),
    otherwise id + quoted text with the raw name."""
    sid = _mermaid_safe_id(name)
    return sid if sid == name else f'{sid}["{name}"]'


@dataclass(slots=True)
class FlowBranch:
    """Represents a single branch of a fork (choice in menu: or if/elif/else)."""

    kind: str  # "choice", "if", "elif", "else"
    name: str  # Choice name or branch description
    line: int  # Line number
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
    Unified merge of parallel branches (if/elif/else or menu:).
    Returns:
      - guaranteed_vars: variables guaranteed to be set on all non-terminating paths
      - uninitialized_vars: dict of MAYBE_SET variables with metadata about the missing branch
      - all_terminating: True if absolutely all branches exit via jump/return
    """
    non_terminating = [b for b in branches if not b.terminates]
    if not non_terminating:
        return set(), {}, True

    if block_kind == "menu":
        guaranteed = (
            set.intersection(*(b.defined_vars for b in non_terminating))
            if non_terminating
            else set()
        )
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
    """Analyzes the transition graph, menu forks, and generates Mermaid diagrams of the plot."""

    def __init__(self, analyzer: DiagnosticSinkAndSymbols):
        self.analyzer = analyzer

    def can_reach_return(self, label_name: str, visited: set[str] | None = None) -> bool:
        """RPY306: DFS search for a path from the called label to a return statement."""
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
        """RPY303: Detects labels with no static references (possible dead code)."""
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
        """RPY309: Finds isolated subgraphs (islands) and cycles unreachable from system entry points."""
        labels = self.analyzer.labels

        root_labels = {lbl for lbl in labels if lbl.lower() in SYSTEM_LABELS or lbl.startswith("_")}

        if not root_labels:
            return []

        # screens as graph bridges. Root screens — built-in (the engine
        # shows them itself) plus all screens with static references
        # (show screen / call screen / use / Show / ShowMenu).
        root_screens = BUILTIN_SCREENS | self.analyzer.used_screens
        screen_targets: set[str] = set()
        for scr_name in root_screens:
            screen_targets.update(self.analyzer.screen_action_jumps.get(scr_name, ()))

        reachable = self._find_reachable_labels(labels, root_labels, screen_targets)

        # Pre-compute incoming dict in O(N+E) (one pass over all labels and their outgoing_jumps),
        # then O(1) lookup in the loop below. Previously this was an O(N²) inline scan.
        incoming_jumps: dict[str, set[str]] = {}
        for src_name, src_lbl in labels.items():
            for tgt in src_lbl.outgoing_jumps:
                incoming_jumps.setdefault(tgt, set()).add(src_name)

        return self._collect_story_islands(labels, reachable, incoming_jumps)

    def _find_reachable_labels(
        self,
        labels: dict[str, LabelSymbol],
        root_labels: set[str],
        screen_targets: set[str],
    ) -> set[str]:
        """BFS from root labels through outgoing_jumps; screen bridges inject extra seeds."""
        reachable: set[str] = set(root_labels)
        queue: deque[str] = deque(root_labels)

        # Jump/Call actions from reachable screens open new labels
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

        return reachable

    def _collect_story_islands(
        self,
        labels: dict[str, LabelSymbol],
        reachable: set[str],
        incoming_jumps: dict[str, set[str]],
    ) -> list[Diagnostic]:
        """Emit RPY309 for every unreachable non-system label that has incoming jumps or static references."""
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
        """RPY404: Checks [var] in text after a menu with variables in MAYBE_SET status."""
        from senpy.core.constants import RE_INTERPOLATION

        for match in RE_STRING_MATCH.finditer(line_content):
            s = match.group(0)
            for var in RE_INTERPOLATION.findall(s):
                if var in branch_uninitialized:
                    info = branch_uninitialized[var]
                    missing_choice = info[0]
                    menu_line = info[2] if len(info) > 2 else "earlier"
                    reason = (
                        missing_choice
                        if ("branch" in missing_choice or "condition" in missing_choice)
                        else f"player took choice '{missing_choice}'"
                    )
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

    # =========================================================================
    # analyze_menu_flow is split into 3 methods.
    # analyze_menu_flow is now a dispatcher.
    # =========================================================================

    def _parse_menu_choices(
        self,
        lines: list[str],
        start_idx: int,
        menu_indent: int,
        file_path: str,
        noqa_map: dict,
    ) -> tuple[int, list[FlowBranch], dict[str, tuple[str, ...]]]:
        """Parses choices from a menu block. Returns (idx, choices, uninitialized_vars).

        Extracted from analyze_menu_flow in Phase 4 Step 2 (0.5.7).
        Choice-detection + empty-check helpers further split out.
        """
        from senpy.text_utils import _strip_comment

        idx = start_idx
        choices: list[FlowBranch] = []
        current_choice: FlowBranch | None = None
        choice_indent: int | None = None
        statement_counts: dict[int, int] = {}
        uninitialized_vars: dict[str, tuple[str, ...]] = {}

        while idx < len(lines):
            raw_line = lines[idx]
            stripped = _strip_comment(raw_line).strip()
            line_indent = len(raw_line) - len(raw_line.lstrip(" "))

            if not stripped:
                idx += 1
                continue

            if line_indent <= menu_indent:
                break

            if self._is_direct_choice_line(raw_line, menu_indent, choice_indent):
                if choice_indent is None:
                    choice_indent = line_indent

                if current_choice:
                    self._check_empty_choice(current_choice, statement_counts, file_path, noqa_map)
                    choices.append(current_choice)

                m_choice = RE_MENU_CHOICE.match(raw_line)
                current_choice = FlowBranch(
                    kind="choice",
                    name=m_choice.group(2).strip("\"'"),  # type: ignore[union-attr]
                    line=idx + 1,
                    raw=stripped,
                )
                statement_counts[id(current_choice)] = 0
                idx += 1
                continue

            if current_choice and line_indent > choice_indent:
                statement_counts[id(current_choice)] = (
                    statement_counts.get(id(current_choice), 0) + 1
                )

                idx, current_choice, uninitialized_vars = self._analyze_choice_body(
                    lines,
                    idx,
                    line_indent,
                    stripped,
                    raw_line,
                    current_choice,
                    uninitialized_vars,
                    file_path,
                    noqa_map,
                )
                continue

            idx += 1

        if current_choice:
            self._check_empty_choice(current_choice, statement_counts, file_path, noqa_map)
            choices.append(current_choice)

        return idx, choices, uninitialized_vars

    @staticmethod
    def _is_direct_choice_line(
        raw_line: str,
        menu_indent: int,
        choice_indent: int | None,
    ) -> bool:
        """True if `raw_line` looks like a top-level menu choice at the choice's indent."""
        m_choice = RE_MENU_CHOICE.match(raw_line)
        if not m_choice:
            return False
        line_indent = len(raw_line) - len(raw_line.lstrip(" "))
        if line_indent <= menu_indent:
            return False
        return choice_indent is None or line_indent == choice_indent

    def _check_empty_choice(
        self,
        branch: FlowBranch,
        statement_counts: dict[int, int],
        file_path: str,
        noqa_map: dict,
    ) -> None:
        """Emit RPY402 if a menu choice has zero statements inside (fall-through)."""
        if not branch or statement_counts.get(id(branch), 0) != 0 or not file_path:
            return
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

    def _analyze_choice_body(
        self,
        lines: list[str],
        idx: int,
        line_indent: int,
        stripped: str,
        raw_line: str,
        current_choice: FlowBranch,
        uninitialized_vars: dict[str, tuple[str, ...]],
        file_path: str,
        noqa_map: dict,
    ) -> tuple[int, FlowBranch, dict[str, tuple[str, ...]]]:
        """Analyzes a choice body (nested menu, jump, $). Returns (idx, choice, uninit).

        Extracted from analyze_menu_flow in Phase 4 Step 2 (0.5.7).
        """
        from senpy.core.constants import RE_MENU_START

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
            return idx, current_choice, uninitialized_vars

        if stripped.startswith("$"):
            py = stripped[1:].strip()
            current_choice.defined_vars.update(extract_assigned_names(py))

        if re.match(
            r"^\s*(?:jump\b|return\b|\$?\s*renpy\.(?:quit|full_restart|utter_restart|jump|jump_out_of_context)\b)",
            stripped,
        ):
            current_choice.terminates = True

        idx += 1
        return idx, current_choice, uninitialized_vars

    def _merge_menu_branches(
        self,
        choices: list[FlowBranch],
        start_idx: int,
        file_path: str,
        noqa_map: dict,
    ) -> tuple[set[str], dict[str, tuple[str, ...]], bool]:
        """Merge menu branches + RPY401 diagnostics. Returns (guaranteed, uninit, all_terminates).

        Extracted from analyze_menu_flow in Phase 4 Step 2 (0.5.7).
        """
        merging_choices = [c for c in choices if not c.terminates]

        # RPY401: Diagnostics of asymmetry between non-terminating menu branches
        if len(merging_choices) > 1:
            all_defined = set().union(*(c.defined_vars for c in merging_choices))
            for var in all_defined:
                if var in self.analyzer.user_symbols or var in self.analyzer.declared_symbols:
                    continue

                missing_b = next((c for c in merging_choices if var not in c.defined_vars), None)
                defined_b = next((c for c in merging_choices if var in c.defined_vars), None)

                if missing_b and defined_b and file_path:
                    start_c, end_c = get_utf16_range(missing_b.raw, missing_b.name)
                    # Improvement (0.7.6): suggest a concrete fix — add the
                    # variable assignment to the missing branch. This is
                    # more actionable than just "it's missing".
                    suggested_value = "0"  # safe default for int/bool types
                    fix_title = f"Add '{var} = {suggested_value}' to this branch"
                    self.analyzer._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=missing_b.line,
                            line_content=missing_b.raw,
                            code="RPY401",
                            message=(
                                f"Menu branch asymmetry: variable '{var}' is assigned in choice "
                                f"'{defined_b.name}' (line {defined_b.line}), "
                                f"but missing in '{missing_b.name}'. "
                                f"Add '$ {var} = {suggested_value}' to this branch or use 'default {var}' at top level."
                            ),
                            col=start_c,
                            end_col=end_c,
                            fix_title=fix_title,
                            fix_replacement=f"$ {var} = {suggested_value}",
                            fix_start_col=start_c,
                            fix_end_col=end_c,
                        ),
                        noqa_map,
                    )

        # Unified state merge
        guaranteed_vars, merged_uninit, all_terminates = merge_flow_branches(
            branches=choices,
            block_kind="menu",
            block_line=start_idx,
            has_else=True,
            known_symbols=self.analyzer.user_symbols,
            already_guaranteed=set(),
        )

        return guaranteed_vars, merged_uninit, all_terminates

    def generate_mermaid_graph(self) -> str:
        """Delegates to MermaidBuilder. Kept for backward compat."""
        return MermaidBuilder(self.analyzer).build()

    def analyze_menu_flow(
        self,
        lines: list[str],
        start_idx: int,
        menu_indent: int,
        file_path: str = "",
        noqa_map: dict | None = None,
    ) -> tuple[int, dict[str, tuple[str, ...]], set[str], bool]:
        """Analyzes a menu block: parses choices, analyzes bodies, merges branches.

        Phase 4 Step 2 (0.5.7): split from 152 lines into 3 methods + dispatcher.
        """
        noqa_map = noqa_map or {}

        idx, choices, uninitialized_vars = self._parse_menu_choices(
            lines, start_idx, menu_indent, file_path, noqa_map
        )

        guaranteed_vars, merged_uninit, all_terminates = self._merge_menu_branches(
            choices, start_idx, file_path, noqa_map
        )

        uninitialized_vars.update(merged_uninit)

        return idx, uninitialized_vars, guaranteed_vars, all_terminates

    # =========================================================================
    # generate_mermaid_graph → MermaidBuilder class.
    # =========================================================================


class MermaidBuilder:
    """Builds a Mermaid.js diagram of the visual novel plot graph.

    Extracted from StoryFlowAnalyzer.generate_mermaid_graph in Phase 4 Step 3 (0.5.7).
    """

    def __init__(self, analyzer: DiagnosticSinkAndSymbols):
        self.analyzer = analyzer

    def build(self) -> str:
        """Builds the full Mermaid graph with metadata."""
        lines = [
            "```mermaid",
            "graph TD",
            "    %% Generated by Senpy Linter (Story Flow Graph)",
        ]

        graph_ctx = _GraphContext(analyzer=self.analyzer)

        _add_nodes(lines=lines, ctx=graph_ctx)
        lines.append("")
        _add_edges(lines=lines, ctx=graph_ctx)
        _add_css_classes(lines=lines)
        lines.append("```")

        _add_metadata(lines=lines, ctx=graph_ctx)
        return "\n".join(lines)


@dataclass(slots=True)
class _GraphContext:
    """Pre-computed data shared across the build helpers."""

    analyzer: DiagnosticSinkAndSymbols
    labels: dict = field(default_factory=dict)
    screens_registry: dict = field(default_factory=dict)
    graph_screens: list = field(default_factory=list)
    screen_action_jumps: dict = field(default_factory=dict)
    screen_uses: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.labels = self.analyzer.labels
        self.screens_registry = self.analyzer.screens
        self.screen_action_jumps = getattr(self.analyzer, "screen_action_jumps", {}) or {}
        used_screens = getattr(self.analyzer, "used_screens", set()) or set()
        self.screen_uses = getattr(self.analyzer, "screen_uses", {}) or {}
        self.graph_screens = sorted(
            (set(self.screen_action_jumps) | set(used_screens) | set(self.screen_uses))
            & set(self.screens_registry)
        )


def _add_nodes(*, lines: list[str], ctx: _GraphContext) -> None:
    """Append label nodes and screen nodes to `lines`."""
    _add_label_nodes(lines=lines, ctx=ctx)
    _add_screen_nodes(lines=lines, ctx=ctx)


def _add_label_nodes(*, lines: list[str], ctx: _GraphContext) -> None:
    """Append one Mermaid node per non-private label.

    Shape depends on return/jump status:
        has_return → `(["…"])`  (stadium — terminal node)
        no jumps   → `[["…"]]:::fallthrough`  (warning — may fall through)
        otherwise  → `["…"]`  (standard rectangle)
    """
    for label, lbl_sym in sorted(ctx.labels.items()):
        if label.startswith("_"):
            continue
        has_return = lbl_sym.has_return
        has_jumps = len(lbl_sym.outgoing_jumps) > 0
        if has_return:
            shape_start, shape_end = '(["', '"])'
        elif not has_jumps:
            shape_start, shape_end = '[["', '"]]:::fallthrough'
        else:
            shape_start, shape_end = '["', '"]'
        lines.append(f"    {_mermaid_safe_id(label)}{shape_start}{label}{shape_end}")


def _add_screen_nodes(*, lines: list[str], ctx: _GraphContext) -> None:
    """Append one node per screen that appears in the graph (jump target, used, or use source)."""
    for scr in ctx.graph_screens:
        lines.append(f'    screen_{_mermaid_safe_id(scr)}{{"screen: {scr}"}}:::screen')


def _add_edges(*, lines: list[str], ctx: _GraphContext) -> None:
    """Append all edge types: label→label, screen→label, label→screen, screen→screen."""
    edges_added = False
    edges_added |= _add_label_edges(lines=lines, ctx=ctx)
    edges_added |= _add_screen_action_edges(lines=lines, ctx=ctx)
    edges_added |= _add_screen_use_edges(lines=lines, ctx=ctx)
    if not edges_added:
        lines.append("    %% No static jumps detected")


def _add_label_edges(*, lines: list[str], ctx: _GraphContext) -> bool:
    """Label→label jump/call edges. Returns True if any edge was added."""
    added = False
    for src, lbl_sym in sorted(ctx.labels.items()):
        if src.startswith("_"):
            continue
        for tgt in sorted(lbl_sym.outgoing_jumps):
            tgt_sym = ctx.labels.get(tgt)
            is_call = tgt_sym.has_return if tgt_sym else False
            arrow = "-- call -->" if is_call else "-->"
            if tgt in ctx.labels:
                lines.append(f"    {_mermaid_safe_id(src)} {arrow} {_mermaid_safe_id(tgt)}")
            else:
                lines.append(
                    f"    {_mermaid_safe_id(src)} -. jump .-> {_mermaid_node_ref(tgt)}:::missing"
                )
            added = True
    return added


def _add_screen_action_edges(*, lines: list[str], ctx: _GraphContext) -> bool:
    """Screen→label edges from screen action jumps. Returns True if any edge was added."""
    added = False
    for scr in ctx.graph_screens:
        for tgt in sorted(ctx.screen_action_jumps.get(scr, ())):
            if tgt in ctx.labels:
                lines.append(
                    f"    screen_{_mermaid_safe_id(scr)} -- action --> {_mermaid_safe_id(tgt)}"
                )
            else:
                lines.append(
                    f"    screen_{_mermaid_safe_id(scr)} -. action .-> {_mermaid_node_ref(tgt)}:::missing"
                )
            added = True
    return added


def _add_screen_use_edges(*, lines: list[str], ctx: _GraphContext) -> bool:
    """Label→screen (`call screen`) and screen→screen (`use`) edges. Returns True if any edge was added."""
    added = False
    for src_name in sorted(ctx.screen_uses):
        if src_name.startswith("_"):
            continue
        for tgt in sorted(ctx.screen_uses[src_name]):
            if tgt not in ctx.screens_registry:
                continue
            if src_name in ctx.labels:
                lines.append(f"    {src_name} -- call screen --> screen_{tgt}")
                added = True
            elif src_name in ctx.screens_registry:
                lines.append(f"    screen_{src_name} -- use --> screen_{tgt}")
                added = True
    return added


def _add_css_classes(*, lines: list[str]) -> None:
    """Append the three CSS classDef lines (missing, fallthrough, screen)."""
    lines.append("\n    classDef missing fill:#ff4d4f,stroke:#333,stroke-width:1px,color:#fff;")
    lines.append("    classDef fallthrough fill:#faad14,stroke:#333,stroke-width:1px,color:#fff;")
    lines.append("    classDef screen fill:#1890ff,stroke:#333,stroke-width:1px,color:#fff;")


def _add_metadata(*, lines: list[str], ctx: _GraphContext) -> None:
    """Append the senpy-meta JSON block with file/line locations for each node."""
    meta: dict[str, dict] = {"locations": {}}

    for lbl_name, lbl_sym in ctx.labels.items():
        meta["locations"][lbl_name] = {
            "file": lbl_sym.file_path.replace("\\", "/"),
            "line": lbl_sym.line_number,
            "type": "label",
        }

    for scr in ctx.graph_screens:
        scr_sym = ctx.screens_registry.get(scr)
        if scr_sym is not None:
            meta["locations"][f"screen_{scr}"] = {
                "file": scr_sym.file_path.replace("\\", "/"),
                "line": scr_sym.line_number,
                "type": "screen",
            }

    for _src, lbl_sym in ctx.labels.items():
        for tgt in lbl_sym.outgoing_jumps:
            if tgt not in ctx.labels and tgt in ctx.analyzer.jump_sources:
                sources = ctx.analyzer.jump_sources[tgt]
                if sources:
                    meta["locations"][tgt] = {
                        "file": sources[0][0].replace("\\", "/"),
                        "line": sources[0][1],
                        "type": "missing_jump",
                    }

    lines.append("\n```senpy-meta")
    lines.append(json.dumps(meta, ensure_ascii=False))
    lines.append("```")
