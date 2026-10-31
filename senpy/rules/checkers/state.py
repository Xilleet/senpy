"""state — extracted from checkers.py (Фаза 2, 0.5.4)."""

from __future__ import annotations

import re
import textwrap

from senpy.core.constants import (
    RE_CONDITION,
    RE_MENU_START,
    RE_PYTHON_BLOCK_START,
)
from senpy.core.scope import ScopeStack
from senpy.core.sink import DiagnosticSink
from senpy.rules.base import BaseChecker, IfBlockContext
from senpy.rules.flow import FlowBranch, merge_flow_branches
from senpy.rules.python_ast import extract_assigned_names


class StateChecker(BaseChecker):
    """RPY1xx, RPY4xx — Проверка переменных, типов, условий, мутаций и развилок menu."""

    def __init__(self, analyzer: DiagnosticSink):
        super().__init__(analyzer)
        self.branch_uninitialized: dict[str, tuple[str, ...]] = {}
        self.guaranteed_vars: set[str] = set()
        self.if_stack: list[IfBlockContext] = []

    def reset(self) -> None:
        self.branch_uninitialized.clear()
        self.guaranteed_vars.clear()
        self.if_stack.clear()

    def _pop_and_merge_all_if(self) -> None:
        while self.if_stack:
            self._merge_if_context(self.if_stack.pop())

    def _merge_if_context(self, ctx: IfBlockContext) -> None:
        has_else = any(b.kind == "else" for b in ctx.branches)
        guaranteed_in_if, uninit_vars, all_terminates = merge_flow_branches(
            branches=ctx.branches,
            block_kind="if",
            block_line=ctx.line,
            has_else=has_else,
            known_symbols=self.analyzer.user_symbols,
            already_guaranteed=self.guaranteed_vars,
        )

        self.branch_uninitialized.update(uninit_vars)

        if self.if_stack:
            self.if_stack[-1].current_branch.defined_vars.update(guaranteed_in_if)
            if all_terminates:
                self.if_stack[-1].current_branch.terminates = True
        else:
            self.guaranteed_vars.update(guaranteed_in_if)

    def check_line(
        self,
        file_path: str,
        idx: int,
        next_idx: int,
        raw_line: str,
        clean_line: str,
        scope_stack: ScopeStack,
        noqa_map: dict[int, set[str] | None],
        lines: list[str],
    ) -> tuple[int, bool]:
        file_modified = False
        stripped = clean_line.strip()
        line_indent = len(raw_line) - len(raw_line.lstrip(" "))
        is_in_screen = scope_stack.current_screen_name() is not None

        # Manage if/elif/else branching stack (outside screens)
        if not is_in_screen:
            self._manage_if_elif_else_stack(stripped, line_indent, idx)

        # RPY404: Check interpolations [var] after branches
        self.analyzer._check_cfg_interpolations(
            file_path, idx + 1, stripped, self.branch_uninitialized, noqa_map
        )

        # menu: block — delegate to analyzer, may consume multiple lines
        result = self._check_menu_block(
            file_path, idx, raw_line, stripped, lines, noqa_map, is_in_screen
        )
        if result is not None:
            return result

        # $ python code (single line)
        result = self._check_python_inline(
            file_path, idx, raw_line, stripped, scope_stack, noqa_map, lines, is_in_screen
        )
        if result is not None:
            return result

        # python: block (multi-line)
        result = self._check_python_block(
            file_path, idx, raw_line, stripped, scope_stack, noqa_map, lines, is_in_screen
        )
        if result is not None:
            return result

        # if/elif/while condition
        self._check_condition(file_path, idx, stripped, scope_stack, noqa_map)

        return next_idx, file_modified

    def _manage_if_elif_else_stack(
        self, stripped: str, line_indent: int, idx: int
    ) -> None:
        """Manage if/elif/else branching stack for control flow analysis."""
        is_if = bool(re.match(r"^if\s+", stripped) and stripped.endswith(":"))
        is_elif = bool(re.match(r"^elif\s+", stripped) and stripped.endswith(":"))
        is_else = bool(stripped == "else:" or re.match(r"^else\s*:", stripped))

        # Close completed if-blocks when indentation decreases
        while self.if_stack:
            top = self.if_stack[-1]
            if line_indent < top.indent:
                self._merge_if_context(self.if_stack.pop())
            elif line_indent == top.indent:
                if is_elif or is_else:
                    break
                self._merge_if_context(self.if_stack.pop())
            else:
                break

        # Switch to elif or else branch
        if (is_elif or is_else) and self.if_stack and line_indent == self.if_stack[-1].indent:
            b_kind = "elif" if is_elif else "else"
            new_branch = FlowBranch(
                kind=b_kind,
                name=f"{b_kind} branch",
                line=idx + 1,
            )
            self.if_stack[-1].branches.append(new_branch)
            self.if_stack[-1].current_branch = new_branch

        # Open new if-block
        elif is_if:
            new_ctx = IfBlockContext(indent=line_indent, line=idx + 1)
            new_branch = FlowBranch(
                kind="if",
                name="if branch",
                line=idx + 1,
            )
            new_ctx.branches.append(new_branch)
            new_ctx.current_branch = new_branch
            self.if_stack.append(new_ctx)

        # Detect jump, return, and terminating renpy.* calls
        if self.if_stack and re.match(
            r"^\s*(?:jump\b|return\b|\$?\s*renpy\.(?:quit|full_restart|utter_restart|jump|jump_out_of_context)\b)",
            stripped,
        ):
            self.if_stack[-1].current_branch.terminates = True

    def _check_menu_block(
        self,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        lines: list[str],
        noqa_map: dict[int, set[str] | None],
        is_in_screen: bool,
    ) -> tuple[int, bool] | None:
        """Handle menu: block — delegates to analyzer._analyze_menu_flow.
        Returns (consumed_idx, file_modified) if menu was handled, None otherwise."""
        m_menu = RE_MENU_START.match(raw_line)
        if not m_menu or is_in_screen:
            return None

        menu_indent = len(m_menu.group(1))
        consumed_idx, uninit_vars, guaranteed_vars, all_terminates = (
            self.analyzer._analyze_menu_flow(
                lines,
                idx + 1,
                menu_indent,
                file_path=file_path,
                noqa_map=noqa_map,
            )
        )
        self.branch_uninitialized.update(uninit_vars)

        # Pass menu's guaranteed variables to current if-branch
        if self.if_stack:
            self.if_stack[-1].current_branch.defined_vars.update(guaranteed_vars)
            if all_terminates:
                self.if_stack[-1].current_branch.terminates = True
        else:
            self.guaranteed_vars.update(guaranteed_vars)

        return consumed_idx, False

    def _check_python_inline(
        self,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        scope_stack: ScopeStack,
        noqa_map: dict[int, set[str] | None],
        lines: list[str],
        is_in_screen: bool,
    ) -> tuple[int, bool] | None:
        """Handle $ python code (single line).
        Returns (next_idx, file_modified) if handled, None otherwise."""
        if not stripped.startswith("$"):
            return None

        self.analyzer._scan_python_assets(raw_line)
        py_code = stripped[1:].strip()
        if is_in_screen:
            self.analyzer._check_screen_mutation(
                py_code,
                file_path,
                idx + 1,
                stripped,
                scope_stack.current_screen_name(),
                scope_stack.get_local_symbols(),
                noqa_map,
                lines=lines,
            )
        else:
            self.analyzer._check_python_ast(
                py_code, file_path, start_line=idx + 1, noqa_map=noqa_map, lines=lines
            )
            self.analyzer._clear_safe_cfg_vars(py_code, self.branch_uninitialized)
            assigned_names = extract_assigned_names(py_code)
            if self.if_stack:
                self.if_stack[-1].current_branch.defined_vars.update(assigned_names)
            else:
                self.guaranteed_vars.update(assigned_names)
        return idx + 1, False

    def _check_python_block(
        self,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        scope_stack: ScopeStack,
        noqa_map: dict[int, set[str] | None],
        lines: list[str],
        is_in_screen: bool,
    ) -> tuple[int, bool] | None:
        """Handle python: block (multi-line).
        Returns (consumed_idx, file_modified) if handled, None otherwise."""
        m_py = RE_PYTHON_BLOCK_START.match(raw_line)
        if not m_py:
            return None

        indent = len(m_py.group(1))
        consumed_idx, block_lines = self.analyzer._consume_block(lines, idx + 1, indent)
        if block_lines:
            self.analyzer._scan_python_assets(block_lines)
            code = textwrap.dedent("".join(block_lines))
            if is_in_screen:
                self.analyzer._check_screen_mutation(
                    code,
                    file_path,
                    idx + 2,
                    stripped,
                    scope_stack.current_screen_name(),
                    scope_stack.get_local_symbols(),
                    noqa_map,
                    lines=lines,
                )
            else:
                self.analyzer._check_python_ast(
                    code, file_path, start_line=idx + 2, noqa_map=noqa_map, lines=lines
                )
                self.analyzer._clear_safe_cfg_vars(code, self.branch_uninitialized)
                assigned_names = extract_assigned_names(code)
                if self.if_stack:
                    self.if_stack[-1].current_branch.defined_vars.update(assigned_names)
                    if re.search(
                        r"\brenpy\.(?:quit|full_restart|utter_restart|jump|jump_out_of_context)\s*\(",
                        code,
                    ):
                        self.if_stack[-1].current_branch.terminates = True
                else:
                    self.guaranteed_vars.update(assigned_names)
        return consumed_idx, False

    def _check_condition(
        self,
        file_path: str,
        idx: int,
        stripped: str,
        scope_stack: ScopeStack,
        noqa_map: dict[int, set[str] | None],
    ) -> None:
        """Check if/elif/while condition for undeclared variables and MAYBE_SET state."""
        m_cond = (
            RE_CONDITION.match(stripped)
            if stripped.startswith(("if ", "elif ", "while "))
            else None
        )
        if not m_cond:
            return

        expr = m_cond.group(1)
        self.analyzer._check_condition(
            file_path,
            idx + 1,
            stripped,
            expr,
            scope_stack.current_screen_name(),
            scope_stack.get_local_symbols(),
            noqa_map,
        )
        self.analyzer._check_cfg_condition(
            file_path,
            idx + 1,
            stripped,
            expr,
            self.branch_uninitialized,
            noqa_map,
        )
