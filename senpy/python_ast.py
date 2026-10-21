from __future__ import annotations

import ast
import contextlib
import textwrap
from typing import TYPE_CHECKING

from senpy.constants import SCREEN_LOCAL_IGNORE
from senpy.models import Diagnostic
from senpy.text_tags import get_utf16_range, suggest_similar_symbol

if TYPE_CHECKING:
    from senpy.analyzer import SenpyAnalyzer


def infer_default_value(val_node: ast.AST | None) -> str:
    """Выводит безопасное дефолтное значение по AST-узлу."""
    if val_node is None:
        return "False"
    if isinstance(val_node, ast.Constant):
        if isinstance(val_node.value, bool):
            return "False"
        elif isinstance(val_node.value, (int, float)):
            return "0"
        elif isinstance(val_node.value, str):
            return '""'
        elif val_node.value is None:
            return "None"
    elif isinstance(val_node, (ast.List, ast.ListComp)):
        return "[]"
    elif isinstance(val_node, (ast.Dict, ast.DictComp)):
        return "{}"
    elif isinstance(val_node, (ast.Set, ast.SetComp)):
        return "[]"
    elif isinstance(val_node, ast.Call) and isinstance(val_node.func, ast.Name):
        if val_node.func.id in ("list", "set"):
            return "[]"
        elif val_node.func.id == "dict":
            return "{}"
    return "False"


def extract_assigned_names(py_code: str) -> set[str]:
    """Извлекает имена переменных, которым присваивается значение в строке Python."""
    assigned = set()
    with contextlib.suppress(SyntaxError):
        tree = ast.parse(py_code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned.add(target.id)
    return assigned


class PythonAstChecker:
    """Проверяет встроенный Python-код через AST на соблюдение правил Ren'Py."""

    def __init__(self, analyzer: SenpyAnalyzer):
        self.analyzer = analyzer

    def collect_from_python_block(self, code_lines: list[str]) -> tuple[set[str], set[str]]:
        """Собирает функции, классы и переменные из init python блоков."""
        names: set[str] = set()
        refs: set[str] = set()
        code = textwrap.dedent("".join(code_lines))
        with contextlib.suppress(SyntaxError):
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(node.name)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            names.add(target.id)
                elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.isidentifier():
                    refs.add(node.value)
        return names, refs

    def check_screen_mutation(
        self,
        py_code: str,
        file_path: str,
        line_idx: int,
        line_content: str,
        screen_name: str,
        screen_local_symbols: set[str],
        noqa_map: dict,
        lines: list[str] | None = None,
    ) -> None:
        """RPY201, RPY205: Проверка императивных циклов и мутаций внутри screen."""
        with contextlib.suppress(SyntaxError):
            tree = ast.parse(py_code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.For, ast.While)):
                    loop_type = type(node).__name__.lower()
                    real_line = line_idx + getattr(node, "lineno", 1) - 1
                    target_line = (
                        lines[real_line - 1]
                        if lines and 0 <= real_line - 1 < len(lines)
                        else f"{loop_type} ..."
                    )
                    start_c, end_c = get_utf16_range(target_line, loop_type)
                    self.analyzer._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=real_line,
                            line_content=(
                                lines[real_line - 1].strip()
                                if lines and 0 <= real_line - 1 < len(lines)
                                else f"{loop_type} ...:"
                            ),
                            code="RPY205",
                            message=(
                                f"Imperative '{loop_type}' loop inside screen '{screen_name}'. "
                                "Python loops inside screens hurt UI prediction performance. "
                                "Use screen-level declarative 'for' loops instead."
                            ),
                            col=start_c,
                            end_col=end_c,
                        ),
                        noqa_map,
                    )
                    break

                if isinstance(node, (ast.Assign, ast.AugAssign)):
                    target_name = "variable"
                    target_node = (
                        node.target
                        if isinstance(node, ast.AugAssign)
                        else (node.targets[0] if node.targets else None)
                    )
                    is_attr = False
                    if isinstance(target_node, ast.Name):
                        target_name = target_node.id
                    elif isinstance(target_node, ast.Attribute):
                        target_name = ast.unparse(target_node)
                        is_attr = True

                    if is_attr and target_name.startswith("style."):
                        continue
                    if target_name in SCREEN_LOCAL_IGNORE or target_name in screen_local_symbols:
                        continue

                    raw_l = (
                        lines[line_idx - 1]
                        if lines and 0 <= line_idx - 1 < len(lines)
                        else line_content
                    )
                    start_c, end_c = get_utf16_range(raw_l, target_name)

                    self.analyzer._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=line_idx,
                            line_content=raw_l.strip(),
                            code="RPY201",
                            message=(
                                f"Direct state mutation '{target_name}' inside screen '{screen_name}'. "
                                "Screens are evaluated predictively. Use screen Actions instead."
                            ),
                            col=start_c,
                            end_col=end_c,
                        ),
                        noqa_map,
                    )
                    break

    def check_python_ast(
        self,
        py_code: str,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None = None,
    ) -> None:
        """Парсит Python-код и запускает рекурсивный обход AST."""
        with contextlib.suppress(SyntaxError):
            tree = ast.parse(py_code)
            self._walk_python_nodes(
                tree.body,
                file_path,
                start_line,
                noqa_map,
                lines,
                local_scope=set(),
            )

    def _walk_python_nodes(
        self,
        nodes: list[ast.stmt],
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None,
        local_scope: set[str],
    ) -> None:
        for node in nodes:
            # Игнорируем вложенные функции и классы, они создают свой локальный скоуп
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue

            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "random":
                        real_line = start_line + getattr(node, "lineno", 1) - 1
                        raw_l = (
                            lines[real_line - 1]
                            if lines and 0 <= real_line - 1 < len(lines)
                            else "import random"
                        )
                        start_c, end_c = get_utf16_range(raw_l, "import random")
                        self.analyzer._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=real_line,
                                line_content=raw_l.strip(),
                                code="RPY106",
                                message="Standard 'random' used during gameplay. Rollback and saves may become non-deterministic; prefer 'renpy.random'.",
                                col=start_c,
                                end_col=end_c,
                                fix_title="Replace with 'from renpy import random'",
                                fix_replacement="from renpy import random",
                            ),
                            noqa_map,
                        )
            elif isinstance(node, ast.ImportFrom) and node.module == "random":
                real_line = start_line + getattr(node, "lineno", 1) - 1
                raw_l = (
                    lines[real_line - 1]
                    if lines and 0 <= real_line - 1 < len(lines)
                    else "from random import ..."
                )
                start_c, end_c = get_utf16_range(raw_l, "random")
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=real_line,
                        line_content=raw_l.strip(),
                        code="RPY106",
                        message="Standard 'random' used during gameplay. Rollback and saves may become non-deterministic; prefer 'renpy.random'.",
                        col=start_c,
                        end_col=end_c,
                    ),
                    noqa_map,
                )

            elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                var_name = node.target.id
                if var_name not in local_scope:
                    real_line = start_line + getattr(node, "lineno", 1) - 1
                    raw_l = (
                        lines[real_line - 1]
                        if lines and 0 <= real_line - 1 < len(lines)
                        else ""
                    )
                    if (not raw_l or var_name not in raw_l) and lines and 0 <= start_line - 1 < len(lines):
                        raw_l = lines[start_line - 1]
                    start_c, end_c = get_utf16_range(raw_l, var_name)

                    if var_name in self.analyzer.defined_constants:
                        if var_name not in self.analyzer.declared_characters:
                            self.analyzer._add_diagnostic(
                                Diagnostic(
                                    file_path=file_path,
                                    line_number=real_line,
                                    line_content=raw_l.strip(),
                                    code="RPY105",
                                    message=f"Constant '{var_name}' was declared with 'define', but modified via '+='. Use 'default' for mutable variables.",
                                    col=start_c,
                                    end_col=end_c,
                                ),
                                noqa_map,
                            )
                    elif var_name not in self.analyzer.declared_symbols:
                        hint = suggest_similar_symbol(var_name, self.analyzer.user_symbols)
                        self.analyzer._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=real_line,
                                line_content=raw_l.strip(),
                                code="RPY102",
                                message=f"Augmented assignment to '{var_name}' before declaration via 'default'{hint}. Causes runtime NameError.",
                                col=start_c,
                                end_col=end_c,
                            ),
                            noqa_map,
                        )

            elif isinstance(node, ast.Assign):
                real_line = start_line + getattr(node, "lineno", 1) - 1
                raw_l = (
                    lines[real_line - 1]
                    if lines and 0 <= real_line - 1 < len(lines)
                    else ""
                )
                if not raw_l.strip() and lines and 0 <= start_line - 1 < len(lines):
                    raw_l = lines[start_line - 1]

                is_set = (
                    isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "set"
                ) or isinstance(node.value, (ast.Set, ast.SetComp))

                if is_set:
                    sub_str = "set" if "set" in raw_l else "{"
                    start_c, end_c = get_utf16_range(raw_l, sub_str)
                    self.analyzer._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=real_line,
                            line_content=raw_l.strip(),
                            code="RPY106",
                            message="Mutable 'set' used in story flow. Ren'Py rollback does not track standard sets. Prefer list '[]' or 'renpy.revertable_set()'.",
                            col=start_c,
                            end_col=end_c,
                        ),
                        noqa_map,
                    )

                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if target.id not in local_scope:
                            self._verify_assign_target(
                                target.id,
                                file_path,
                                real_line,
                                noqa_map,
                                raw_line=raw_l,
                                val_node=node.value,
                            )
                    elif isinstance(target, (ast.Tuple, ast.List)):
                        for elt in target.elts:
                            if isinstance(elt, ast.Name) and elt.id not in local_scope:
                                self._verify_assign_target(
                                    elt.id,
                                    file_path,
                                    real_line,
                                    noqa_map,
                                    raw_line=raw_l,
                                    val_node=node.value,
                                )

            elif isinstance(node, (ast.If, ast.While)):
                self._walk_python_nodes(node.body, file_path, start_line, noqa_map, lines, local_scope)
                self._walk_python_nodes(node.orelse, file_path, start_line, noqa_map, lines, local_scope)

            elif isinstance(node, ast.For):
                loop_scope = set(local_scope)
                if isinstance(node.target, ast.Name):
                    loop_scope.add(node.target.id)
                elif isinstance(node.target, (ast.Tuple, ast.List)):
                    for elt in node.target.elts:
                        if isinstance(elt, ast.Name):
                            loop_scope.add(elt.id)
                self._walk_python_nodes(node.body, file_path, start_line, noqa_map, lines, loop_scope)
                self._walk_python_nodes(node.orelse, file_path, start_line, noqa_map, lines, loop_scope)

            elif isinstance(node, ast.Try):
                self._walk_python_nodes(node.body, file_path, start_line, noqa_map, lines, local_scope)
                self._walk_python_nodes(node.orelse, file_path, start_line, noqa_map, lines, local_scope)
                self._walk_python_nodes(node.finalbody, file_path, start_line, noqa_map, lines, local_scope)
                for handler in node.handlers:
                    h_scope = set(local_scope)
                    if handler.name:
                        h_scope.add(handler.name)
                    self._walk_python_nodes(handler.body, file_path, start_line, noqa_map, lines, h_scope)

    def _verify_assign_target(
        self,
        var_name: str,
        file_path: str,
        line_idx: int,
        noqa_map: dict,
        raw_line: str = "",
        val_node: ast.AST | None = None,
    ) -> None:
        if var_name.startswith("_") or var_name in self.analyzer.declared_characters:
            return

        start_c, end_c = get_utf16_range(raw_line, var_name) if raw_line else (0, 0)

        if var_name in self.analyzer.defined_constants:
            self.analyzer._add_diagnostic(
                Diagnostic(
                    file_path=file_path,
                    line_number=line_idx,
                    line_content=f"{var_name} = ...",
                    code="RPY105",
                    message=(
                        f"Variable '{var_name}' was declared with 'define' (constant), but is reassigned dynamically. "
                        "Ren'Py expects 'default' for variables that change, otherwise rollback and saves will corrupt."
                    ),
                    col=start_c,
                    end_col=end_c,
                ),
                noqa_map,
            )
            return

        if var_name not in self.analyzer.declared_symbols:
            hint = suggest_similar_symbol(var_name, self.analyzer.user_symbols)
            self.analyzer._add_diagnostic(
                Diagnostic(
                    file_path=file_path,
                    line_number=line_idx,
                    line_content=f"{var_name} = ...",
                    code="RPY104",
                    message=(
                        f"Variable '{var_name}' is assigned dynamically without a top-level 'default'{hint}. "
                        "This will break save games and cause NameError on other story branches."
                    ),
                    col=start_c,
                    end_col=end_c,
                ),
                noqa_map,
            )
            self.analyzer.declared_symbols.add(var_name)
        if var_name not in self.analyzer.missing_defaults:
            self.analyzer.missing_defaults[var_name] = infer_default_value(val_node)

    def check_condition(
        self,
        file_path: str,
        line_idx: int,
        line_content: str,
        expr: str,
        screen_name: str | None,
        screen_local_symbols: set[str],
        noqa_map: dict,
    ) -> None:
        """RPY403, RPY202, RPY103: Проверяет условия if/elif через AST."""
        with contextlib.suppress(SyntaxError):
            cond_tree = ast.parse(expr, mode="eval")
            if isinstance(cond_tree.body, ast.Constant) and not bool(cond_tree.body.value):
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=line_idx,
                        line_content=line_content,
                        code="RPY403",
                        message=f"Condition '{expr}' is always False. This block will never execute.",
                    ),
                    noqa_map,
                )
            elif isinstance(cond_tree.body, ast.BoolOp) and isinstance(cond_tree.body.op, ast.And):
                names = {n.id for n in cond_tree.body.values if isinstance(n, ast.Name)}
                not_names = {
                    n.operand.id
                    for n in cond_tree.body.values
                    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not) and isinstance(n.operand, ast.Name)
                }
                contradictions = names.intersection(not_names)
                if contradictions:
                    var_c = next(iter(contradictions))
                    self.analyzer._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=line_idx,
                            line_content=line_content,
                            code="RPY403",
                            message=f"Condition contains mutually exclusive contradiction: '{var_c} and not {var_c}'. Always evaluates to False.",
                        ),
                        noqa_map,
                    )
            for node in ast.walk(cond_tree):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    var_name = node.id
                    if var_name.startswith("_") or var_name in SCREEN_LOCAL_IGNORE:
                        continue
                    if var_name not in self.analyzer.declared_symbols and var_name not in screen_local_symbols:
                        hint = suggest_similar_symbol(var_name, self.analyzer.user_symbols)
                        start_c, end_c = get_utf16_range(line_content, var_name)
                        if screen_name:
                            self.analyzer._add_diagnostic(
                                Diagnostic(
                                    file_path=file_path,
                                    line_number=line_idx,
                                    line_content=line_content,
                                    code="RPY202",
                                    message=(
                                        f"Screen '{screen_name}' accesses undeclared variable '{var_name}'{hint}. "
                                        "Screens can be evaluated in the main menu or before game start, causing a crash."
                                    ),
                                    col=start_c,
                                    end_col=end_c,
                                ),
                                noqa_map,
                            )
                        else:
                            self.analyzer._add_diagnostic(
                                Diagnostic(
                                    file_path=file_path,
                                    line_number=line_idx,
                                    line_content=line_content,
                                    code="RPY103",
                                    message=f"Undeclared variable '{var_name}' in condition{hint}. Evaluating this condition will crash with NameError.",
                                    col=start_c,
                                    end_col=end_c,
                                ),
                                noqa_map,
                            )

    def check_cfg_condition(
        self,
        file_path: str,
        line_idx: int,
        line_content: str,
        expr: str,
        branch_uninitialized: dict,
        noqa_map: dict,
    ) -> None:
        """RPY401: Проверяет условие на использование переменной, объявленной не во всех ветках menu."""
        with contextlib.suppress(SyntaxError):
            tree = ast.parse(expr, mode="eval")
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Load)
                    and node.id in branch_uninitialized
                ):
                    missing_choice, defined_choice = branch_uninitialized[node.id]
                    self.analyzer._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=line_idx,
                            line_content=line_content,
                            code="RPY401",
                            message=(
                                f"Variable '{node.id}' is only defined in menu choice '{defined_choice}', "
                                f"but missing in '{missing_choice}'. When choosing '{missing_choice}', "
                                "this condition will crash with NameError."
                            ),
                        ),
                        noqa_map,
                    )

    def clear_safe_cfg_vars(self, py_code: str, branch_uninitialized: dict) -> None:
        """Удаляет переменные из неинициализированных, если им присвоено значение."""
        with contextlib.suppress(SyntaxError):
            tree = ast.parse(py_code)
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            branch_uninitialized.pop(target.id, None)


# Псевдоним для краткости, если захочешь использовать AstChecker
AstChecker = PythonAstChecker