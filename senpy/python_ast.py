from __future__ import annotations

import ast
import contextlib
import textwrap
from typing import TYPE_CHECKING

from senpy.constants import BUILTIN_SYMBOLS, SCREEN_LOCAL_IGNORE
from senpy.models import Diagnostic
from senpy.text_tags import get_utf16_range, suggest_similar_symbol

if TYPE_CHECKING:
    from senpy.analyzer import SenpyAnalyzer

def infer_ast_type(val_node: ast.AST | None) -> str | None:
    """Определяет тип данных выражения по AST-узлу."""
    if val_node is None:
        return None
    if isinstance(val_node, ast.Constant):
        # bool проверяем ДО int, так как в Python isinstance(True, int) == True
        if isinstance(val_node.value, bool):
            return "bool"
        if isinstance(val_node.value, int):
            return "int"
        if isinstance(val_node.value, float):
            return "float"
        if isinstance(val_node.value, str):
            return "str"
        if val_node.value is None:
            return "None"
    elif isinstance(val_node, (ast.List, ast.ListComp)):
        return "list"
    elif isinstance(val_node, (ast.Dict, ast.DictComp)):
        return "dict"
    elif isinstance(val_node, (ast.Set, ast.SetComp)):
        return "set"
    elif isinstance(val_node, ast.Call) and isinstance(val_node.func, ast.Name):
        if val_node.func.id in ("list", "revertable_list"):
            return "list"
        if val_node.func.id in ("dict", "revertable_dict"):
            return "dict"
        if val_node.func.id in ("set", "revertable_set"):
            return "set"
    return None


def infer_expr_type(expr_str: str | None) -> str | None:
    """Выводит тип выражения из строки присваивания."""
    if not expr_str or not expr_str.strip():
        return None
    try:
        tree = ast.parse(expr_str.strip(), mode="eval")
        return infer_ast_type(tree.body)
    except (SyntaxError, ValueError, TypeError):
        return None

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

# Системные пространства имён Ren'Py, мутация которых допустима во время игры
SYSTEM_MUTABLE_NAMESPACES = {"persistent", "config", "store", "gui", "style"}

MUTATING_METHODS = {
    # Списки (list / deque)
    "append", "extend", "insert", "remove", "pop", "clear", "reverse", "sort",
    # Множества (set)
    "add", "discard", "difference_update", "intersection_update", "symmetric_difference_update",
    # Словари (dict)
    "update", "popitem", "setdefault",
}

def _get_root_name(node: ast.AST | None) -> str | None:
    """Рекурсивно разворачивает срезы и атрибуты до базового имени переменной (например, a[0]['k'] -> a)."""
    curr = node
    while isinstance(curr, (ast.Subscript, ast.Attribute)):
        curr = curr.value
    if isinstance(curr, ast.Name):
        return curr.id
    return None

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

    def collect_from_python_block(self, code_lines: list[str]) -> tuple[dict[str, int], set[str]]:
        """Собирает функции, классы и переменные из init python блоков вместе с номерами строк."""
        names: dict[str, int] = {}
        refs: set[str] = set()
        code = textwrap.dedent("".join(code_lines))
        with contextlib.suppress(SyntaxError):
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names[node.name] = getattr(node, "lineno", 1)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            names[target.id] = getattr(node, "lineno", 1)
                elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.isidentifier():
                    refs.add(node.value)
        return names, refs

    def check_init_dependency(
        self,
        py_code: str,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None = None,
    ) -> None:
        """RPY109: Проверяет вызовы функций в init python на алфавитный порядок файлов."""
        import os
        with contextlib.suppress(SyntaxError):
            tree = ast.parse(py_code)

            def walk_and_check(root_node: ast.AST):
                for child in ast.walk(root_node):
                    # Игнорируем тела функций и классов (они исполняются отложенно)
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and child is not root_node:
                        continue
                    
                    if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                        name = child.id
                        if name in BUILTIN_SYMBOLS:
                            continue
                        if name in self.analyzer.variables:
                            def_file = self.analyzer.variables[name].file_path
                            if def_file != file_path:
                                curr_rel = os.path.relpath(file_path, self.analyzer.project_path).replace("\\", "/").lower()
                                def_rel = os.path.relpath(def_file, self.analyzer.project_path).replace("\\", "/").lower()
                                
                                # Если текущий файл загружается раньше файла с определением
                                if curr_rel < def_rel:
                                    real_line = start_line + getattr(child, "lineno", 1) - 1
                                    raw_l = lines[real_line - 1] if lines and 0 <= real_line - 1 < len(lines) else ""
                                    start_c, end_c = get_utf16_range(raw_l, name)
                                    self.analyzer._add_diagnostic(
                                        Diagnostic(
                                            file_path=file_path,
                                            line_number=real_line,
                                            line_content=raw_l.strip(),
                                            code="RPY109",
                                            message=(
                                                f"Init phase dependency violation: '{name}' is evaluated here, "
                                                f"but defined later in '{os.path.basename(def_file)}'. "
                                                "Due to alphabetical load order, it will crash with NameError."
                                            ),
                                            severity="ERROR",
                                            col=start_c,
                                            end_col=end_c,
                                        ),
                                        noqa_map,
                                    )

            for stmt in tree.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # У функций сразу при старте вычисляются только декораторы
                    for dec in stmt.decorator_list:
                        walk_and_check(dec)
                elif isinstance(stmt, ast.ClassDef):
                    # У классов вычисляются декораторы и базовые классы
                    for dec in stmt.decorator_list:
                        walk_and_check(dec)
                    for base in stmt.bases:
                        walk_and_check(base)
                else:
                    # Остальные стейтменты (вызовы, присваивания) выполняются сразу
                    walk_and_check(stmt)

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

            elif isinstance(node, ast.AugAssign):
                # 1. Мутация через +=, -= переменной: $ CONST += 1
                if isinstance(node.target, ast.Name):
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

                        var_sym = self.analyzer.variables.get(var_name)
                        if var_sym and var_sym.is_constant:
                            if not var_sym.is_character:
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
                        else:
                            # RPY108: Проверка несовместимого типа при +=, -= и т.д.
                            expected_t = var_sym.type_name if var_sym else None
                            op_t = infer_ast_type(node.value)
                            if expected_t and op_t:
                                is_incompatible = False

                                if expected_t == "str" and op_t != "str" or expected_t in ("int", "float") and op_t not in ("int", "float") or expected_t == "list" and op_t not in ("list",) or expected_t in ("dict", "bool"):
                                    is_incompatible = True

                                if is_incompatible:
                                    self.analyzer._add_diagnostic(
                                        Diagnostic(
                                            file_path=file_path,
                                            line_number=real_line,
                                            line_content=raw_l.strip(),
                                            code="RPY108",
                                            message=(
                                                f"Incompatible augmented assignment: variable '{var_name}' of type '{expected_t}' "
                                                f"is modified with operand of type '{op_t}'. Will crash with TypeError at runtime!"
                                            ),
                                            severity="ERROR",
                                            col=start_c,
                                            end_col=end_c,
                                        ),
                                        noqa_map,
                                    )
                                    
                elif isinstance(node.target, ast.Subscript):
                    root_name = _get_root_name(node.target.value)
                    root_var = self.analyzer.variables.get(root_name) if root_name else None
                    if (
                        root_var
                        and root_var.is_constant
                        and not root_var.is_character
                        and root_name not in SYSTEM_MUTABLE_NAMESPACES
                        and root_name not in local_scope
                    ):
                        real_line = start_line + getattr(node, "lineno", 1) - 1
                        raw_l = lines[real_line - 1] if lines and 0 <= real_line - 1 < len(lines) else ""
                        start_c, end_c = get_utf16_range(raw_l, root_name)
                        self.analyzer._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=real_line,
                                line_content=raw_l.strip(),
                                code="RPY105",
                                message=(
                                    f"In-place augmented assignment on constant '{root_name}' declared with 'define'. "
                                    "Modifying mutable collections declared with 'define' breaks rollback and save persistence! Use 'default' instead."
                                ),
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
                            # RPY108: Проверка конфликта типов при присваивании ($ var = "High")
                            expected_t = self.analyzer.variables[target.id].type_name if target.id in self.analyzer.variables else None
                            new_t = infer_ast_type(node.value)
                            if (
                                expected_t
                                and new_t
                                and expected_t != new_t
                                and expected_t != "None"  # None -> любой_тип разрешён (первичная инициализация)
                                and new_t != "None"       # любой_тип -> None разрешён (сброс в sentinel)
                                and not ({expected_t, new_t} <= {"int", "float"})
                            ):
                                start_c, end_c = get_utf16_range(raw_l, target.id)
                                self.analyzer._add_diagnostic(
                                    Diagnostic(
                                        file_path=file_path,
                                        line_number=real_line,
                                        line_content=raw_l.strip(),
                                        code="RPY108",
                                        message=(
                                            f"Type taint: variable '{target.id}' was declared as '{expected_t}', "
                                            f"but reassigned value of incompatible type '{new_t}'. May cause runtime TypeError."
                                        ),
                                        severity="WARNING",
                                        col=start_c,
                                        end_col=end_c,
                                    ),
                                    noqa_map,
                                )
                    # 3. Мутация по ключу/индексу: $ CONST["ключ"] = "значение"
                    elif isinstance(target, ast.Subscript):
                        root_name = _get_root_name(target.value)
                        root_var = self.analyzer.variables.get(root_name) if root_name else None
                        if (
                            root_var
                            and root_var.is_constant
                            and not root_var.is_character
                            and root_name not in SYSTEM_MUTABLE_NAMESPACES
                            and root_name not in local_scope
                        ):
                            start_c, end_c = get_utf16_range(raw_l, root_name)
                            self.analyzer._add_diagnostic(
                                Diagnostic(
                                    file_path=file_path,
                                    line_number=real_line,
                                    line_content=raw_l.strip(),
                                    code="RPY105",
                                    message=(
                                        f"In-place subscript assignment on constant '{root_name}' declared with 'define'. "
                                        "Modifying mutable collections declared with 'define' breaks rollback and save persistence! Use 'default' instead."
                                    ),
                                    col=start_c,
                                    end_col=end_c,
                                ),
                                noqa_map,
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

            # 4. Мутирующие методы Python: $ CONST.append(...), CONST.clear(), CONST.pop()
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                        method_name = sub.func.attr
                        if method_name in MUTATING_METHODS:
                            root_name = _get_root_name(sub.func.value)
                            root_var = self.analyzer.variables.get(root_name) if root_name else None
                            if (
                                root_var
                                and root_var.is_constant
                                and not root_var.is_character
                                and root_name not in SYSTEM_MUTABLE_NAMESPACES
                                and root_name not in local_scope
                            ):
                                real_line = start_line + getattr(sub, "lineno", 1) - 1
                                raw_l = lines[real_line - 1] if lines and 0 <= real_line - 1 < len(lines) else ""
                                target_str = f"{root_name}.{method_name}"
                                sub_str = target_str if target_str in raw_l else root_name
                                start_c, end_c = get_utf16_range(raw_l, sub_str)
                                self.analyzer._add_diagnostic(
                                    Diagnostic(
                                        file_path=file_path,
                                        line_number=real_line,
                                        line_content=raw_l.strip(),
                                        code="RPY105",
                                        message=(
                                            f"Constant '{root_name}' was declared with 'define', but mutated via in-place method '.{method_name}()'. "
                                            "In Ren'Py, modifying mutable objects declared with 'define' breaks rollback history! Use 'default' instead."
                                        ),
                                        col=start_c,
                                        end_col=end_c,
                                    ),
                                    noqa_map,
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
        var_sym = self.analyzer.variables.get(var_name)
        if var_name.startswith("_") or (var_sym and var_sym.is_character) or var_name in SYSTEM_MUTABLE_NAMESPACES:
            return

        start_c, end_c = get_utf16_range(raw_line, var_name) if raw_line else (0, 0)

        if var_sym and var_sym.is_constant:
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
        """RPY404: Проверяет условие if/elif на переменную в статусе MAYBE_SET."""
        with contextlib.suppress(SyntaxError):
            tree = ast.parse(expr, mode="eval")
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Load)
                    and node.id in branch_uninitialized
                ):
                    info = branch_uninitialized[node.id]
                    missing_choice = info[0]
                    menu_line = info[2] if len(info) > 2 else "earlier"
                    start_c, end_c = get_utf16_range(line_content, node.id)
                    reason = missing_choice if ("branch" in missing_choice or "condition" in missing_choice) else f"player took choice '{missing_choice}'"
                    self.analyzer._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=line_idx,
                            line_content=line_content,
                            code="RPY404",
                            message=(
                                f"Variable '{node.id}' may be uninitialized (MAYBE_SET) if "
                                f"{reason} on line {menu_line}. Condition will crash with NameError."
                            ),
                            col=start_c,
                            end_col=end_c,
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