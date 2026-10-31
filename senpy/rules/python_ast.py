from __future__ import annotations

import ast
import difflib
import textwrap
from typing import Any

from senpy.core.constants import BUILTIN_SYMBOLS, SCREEN_LOCAL_IGNORE
from senpy.core.logging import get_logger
from senpy.core.models import Diagnostic
from senpy.core.sink import DiagnosticSink  # Фаза 1.4: Protocol вместо SenpyAnalyzer
from senpy.domain.text_tags import get_utf16_range, suggest_similar_symbol

_logger = get_logger("rules.python_ast")


def infer_ast_type(
    val_node: ast.AST | None,
    known_vars: dict[str, Any] | None = None,
    depth: int = 0,
) -> str | None:
    """Infer the Python type of an AST expression node.

    Dispatches to specialized helpers based on node type:
      1. _infer_constant — literals (int, float, str, bool, None)
      2. _infer_name — variable references
      3. _infer_collection — list/dict/set/tuple
      4. _infer_joinedstr — f-strings
      5. _infer_compare — comparison operations
      6. _infer_unaryop — unary operations (not, -x)
      7. _infer_binop — binary operations (+, -, *, /)
      8. _infer_ifexp — ternary expressions
      9. _infer_call — function/method calls

    TODO(future): Replace with Type Lattice (TypeHint.join()) for
    automatic union types after if/else. Currently returns str|None.
    """
    if val_node is None or depth > 8:
        return None

    if isinstance(val_node, ast.Constant):
        return _infer_constant(val_node)
    elif isinstance(val_node, ast.Name):
        return _infer_name(val_node, known_vars)
    elif isinstance(val_node, (ast.List, ast.ListComp, ast.Dict, ast.DictComp,
                                ast.Set, ast.SetComp, ast.Tuple)):
        return _infer_collection(val_node)
    elif isinstance(val_node, ast.JoinedStr):
        return "str"
    elif isinstance(val_node, ast.Compare):
        return "bool"
    elif isinstance(val_node, ast.UnaryOp):
        return _infer_unaryop(val_node, known_vars, depth)
    elif isinstance(val_node, ast.BinOp):
        return _infer_binop(val_node, known_vars, depth)
    elif isinstance(val_node, ast.IfExp):
        return _infer_ifexp(val_node, known_vars, depth)
    elif isinstance(val_node, ast.Call):
        return _infer_call(val_node)
    return None


def _infer_constant(node: ast.Constant) -> str | None:
    """Infer type from a literal constant."""
    if isinstance(node.value, bool):
        return "bool"
    if isinstance(node.value, int):
        return "int"
    if isinstance(node.value, float):
        return "float"
    if isinstance(node.value, str):
        return "str"
    if node.value is None:
        return "None"
    return None


def _infer_name(node: ast.Name, known_vars: dict | None) -> str | None:
    """Infer type from a variable name reference."""
    if node.id in ("True", "False"):
        return "bool"
    if node.id == "None":
        return "None"
    if known_vars and node.id in known_vars:
        var_sym = known_vars[node.id]
        return getattr(var_sym, "type_name", None) or (
            var_sym if isinstance(var_sym, str) else None
        )
    return None


def _infer_collection(node: ast.AST) -> str | None:
    """Infer type from collection literals (list, dict, set, tuple)."""
    if isinstance(node, (ast.List, ast.ListComp)):
        return "list"
    if isinstance(node, (ast.Dict, ast.DictComp)):
        return "dict"
    if isinstance(node, (ast.Set, ast.SetComp)):
        return "set"
    if isinstance(node, ast.Tuple):
        return "tuple"
    return None


def _infer_unaryop(
    node: ast.UnaryOp, known_vars: dict | None, depth: int
) -> str | None:
    """Infer type from unary operations (not x → bool, -x → int/float)."""
    if isinstance(node.op, ast.Not):
        return "bool"
    if isinstance(node.op, (ast.USub, ast.UAdd)):
        operand_t = infer_ast_type(node.operand, known_vars, depth + 1)
        if operand_t in ("int", "float"):
            return operand_t
    return None


def _infer_binop(
    node: ast.BinOp, known_vars: dict | None, depth: int
) -> str | None:
    """Infer type from binary operations (+, -, *, /, //, %)."""
    lt = infer_ast_type(node.left, known_vars, depth + 1)
    rt = infer_ast_type(node.right, known_vars, depth + 1)

    # Division always returns float in Python 3
    if isinstance(node.op, ast.Div):
        return "float"

    # String/list concatenation
    if isinstance(node.op, ast.Add):
        if lt == "str" and rt == "str":
            return "str"
        if lt == "list" and rt == "list":
            return "list"

    # Repetition: str * int → str, list * int → list
    if isinstance(node.op, ast.Mult):
        if (lt == "str" and rt == "int") or (lt == "int" and rt == "str"):
            return "str"
        if (lt == "list" and rt == "int") or (lt == "int" and rt == "list"):
            return "list"

    # Numeric arithmetic: int + int → int, int + float → float
    if lt in ("int", "float") and rt in ("int", "float"):
        if "float" in (lt, rt):
            return "float"
        return "int"

    return None


def _infer_ifexp(
    node: ast.IfExp, known_vars: dict | None, depth: int
) -> str | None:
    """Infer type from ternary expression (a if cond else b)."""
    t_body = infer_ast_type(node.body, known_vars, depth + 1)
    t_else = infer_ast_type(node.orelse, known_vars, depth + 1)
    if t_body == t_else and t_body is not None:
        return t_body
    return None


def _infer_call(node: ast.Call) -> str | None:
    """Infer type from function/method calls (int(), str(), .upper(), etc.)."""
    if isinstance(node.func, ast.Name):
        return _infer_builtin_function(node.func.id)
    elif isinstance(node.func, ast.Attribute):
        return _infer_method_call(node.func.attr)
    return None


def _infer_builtin_function(func_id: str) -> str | None:
    """Infer return type from builtin function calls."""
    if func_id in ("int", "len", "round"):
        return "int"
    if func_id == "float":
        return "float"
    if func_id == "str":
        return "str"
    if func_id == "bool":
        return "bool"
    if func_id in ("list", "revertable_list"):
        return "list"
    if func_id in ("dict", "revertable_dict"):
        return "dict"
    if func_id in ("set", "revertable_set"):
        return "set"
    return None


def _infer_method_call(method: str) -> str | None:
    """Infer return type from method calls on known types."""
    # String methods
    if method in (
        "upper", "lower", "strip", "lstrip", "rstrip",
        "replace", "format", "capitalize", "title",
    ):
        return "str"
    if method in ("split", "splitlines"):
        return "list"
    if method in ("startswith", "endswith", "isdigit", "isalpha", "isalnum"):
        return "bool"
    if method in ("count", "index", "find", "rfind"):
        return "int"
    if method in ("keys", "values"):
        return "list"
    return None


def infer_expr_type(
    expr_str: str | None,
    known_vars: dict[str, Any] | None = None,
) -> str | None:
    """Выводит тип выражения из строки присваивания с учетом известных символов."""
    if not expr_str or not expr_str.strip():
        return None
    try:
        tree = ast.parse(expr_str.strip(), mode="eval")
        return infer_ast_type(tree.body, known_vars=known_vars)
    except (SyntaxError, ValueError, TypeError):
        return None


def infer_default_value(
    val_node: ast.AST | None,
    known_vars: dict[str, Any] | None = None,
) -> str:
    """Выводит безопасное дефолтное значение на основе вычисленного типа узла."""
    t = infer_ast_type(val_node, known_vars=known_vars)
    if t == "int":
        return "0"
    if t == "float":
        return "0.0"
    if t == "str":
        return '""'
    if t == "bool":
        return "False"
    if t == "list":
        return "[]"
    if t == "dict":
        return "{}"
    if t == "set":
        return "[]"
    if t == "None":
        return "None"
    return "False"


# Системные пространства имён Ren'Py, мутация которых допустима во время игры
SYSTEM_MUTABLE_NAMESPACES = {"persistent", "config", "store", "gui", "style"}

MUTATING_METHODS = {
    # Списки (list / deque)
    "append",
    "extend",
    "insert",
    "remove",
    "pop",
    "clear",
    "reverse",
    "sort",
    # Множества (set)
    "add",
    "discard",
    "difference_update",
    "intersection_update",
    "symmetric_difference_update",
    # Словари (dict)
    "update",
    "popitem",
    "setdefault",
}

# Допустимые стандартные методы встроенных типов данных
KNOWN_TYPE_METHODS: dict[str, set[str]] = {
    "list": {
        "append",
        "extend",
        "insert",
        "remove",
        "pop",
        "clear",
        "index",
        "count",
        "sort",
        "reverse",
        "copy",
    },
    "dict": {
        "clear",
        "copy",
        "fromkeys",
        "get",
        "items",
        "keys",
        "pop",
        "popitem",
        "setdefault",
        "update",
        "values",
    },
    "set": {
        "add",
        "clear",
        "copy",
        "difference",
        "difference_update",
        "discard",
        "intersection",
        "intersection_update",
        "isdisjoint",
        "issubset",
        "issuperset",
        "pop",
        "remove",
        "symmetric_difference",
        "symmetric_difference_update",
        "union",
        "update",
    },
    "str": {
        "capitalize",
        "casefold",
        "center",
        "count",
        "encode",
        "endswith",
        "expandtabs",
        "find",
        "format",
        "format_map",
        "index",
        "isalnum",
        "isalpha",
        "isascii",
        "isdecimal",
        "isdigit",
        "isidentifier",
        "islower",
        "isnumeric",
        "isprintable",
        "isspace",
        "istitle",
        "isupper",
        "join",
        "ljust",
        "lower",
        "lstrip",
        "partition",
        "removeprefix",
        "removesuffix",
        "replace",
        "rfind",
        "rindex",
        "rjust",
        "rpartition",
        "rsplit",
        "rstrip",
        "split",
        "splitlines",
        "startswith",
        "strip",
        "swapcase",
        "title",
        "translate",
        "upper",
        "zfill",
    },
}

# Подсказки частых межтиповых ошибок (например, .add() вместо .append() у списка)
METHOD_SUGGESTIONS: dict[tuple[str, str], str] = {
    ("list", "add"): ".append()",
    ("dict", "append"): ".update()",
    ("set", "append"): ".add()",
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
    try:
        tree = ast.parse(py_code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned.add(target.id)
    except SyntaxError as e:
        # log debug instead of silent suppress.
        _logger.debug("extract_assigned_names: ast.parse failed: %s", e)
    return assigned


class PythonAstChecker:
    """Проверяет встроенный Python-код через AST на соблюдение правил Ren'Py."""

    def __init__(self, analyzer: DiagnosticSink):
        self.analyzer = analyzer

    def collect_from_python_block(self, code_lines: list[str]) -> tuple[dict[str, int], set[str]]:
        """Собирает функции, классы и переменные из init python блоков вместе с номерами строк."""
        names: dict[str, int] = {}
        refs: set[str] = set()
        code = textwrap.dedent("".join(code_lines))
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names[node.name] = getattr(node, "lineno", 1)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            names[target.id] = getattr(node, "lineno", 1)
                elif (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value.isidentifier()
                ):
                    refs.add(node.value)
        except SyntaxError as e:
            # log debug instead of silent suppress.
            _logger.debug("collect_from_python_block: ast.parse failed: %s", e)
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

        try:
            tree = ast.parse(py_code)

            def walk_and_check(root_node: ast.AST):
                for child in ast.walk(root_node):
                    # Игнорируем тела функций и классов (они исполняются отложенно)
                    if (
                        isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                        and child is not root_node
                    ):
                        continue

                    if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                        name = child.id
                        if name in BUILTIN_SYMBOLS:
                            continue
                        if name in self.analyzer.variables:
                            def_file = self.analyzer.variables[name].file_path
                            if def_file != file_path:
                                curr_rel = (
                                    os.path.relpath(file_path, self.analyzer.project_path)
                                    .replace("\\", "/")
                                    .lower()
                                )
                                def_rel = (
                                    os.path.relpath(def_file, self.analyzer.project_path)
                                    .replace("\\", "/")
                                    .lower()
                                )

                                # Если текущий файл загружается раньше файла с определением
                                if curr_rel < def_rel:
                                    real_line = start_line + getattr(child, "lineno", 1) - 1
                                    raw_l = (
                                        lines[real_line - 1]
                                        if lines and 0 <= real_line - 1 < len(lines)
                                        else ""
                                    )
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
        except SyntaxError as e:
            # log debug instead of silent suppress.
            _logger.debug("check_init_dependency: ast.parse failed: %s", e)

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
        try:
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
                    if target_name in SCREEN_LOCAL_IGNORE:
                        continue

                    raw_l = (
                        lines[line_idx - 1]
                        if lines and 0 <= line_idx - 1 < len(lines)
                        else line_content
                    )
                    start_c, end_c = get_utf16_range(raw_l, target_name)

                    # RPY208: Прямая мутация локальной переменной экрана через Python ($ var = ...)
                    if target_name in screen_local_symbols:
                        self.analyzer._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=line_idx,
                                line_content=raw_l.strip(),
                                code="RPY208",
                                message=(
                                    f"Direct state mutation of screen-local variable '{target_name}' inside screen '{screen_name}'. "
                                    "Python statements in screens execute in the global store and cannot modify screen-local variables! "
                                    f"Use screen action SetScreenVariable('{target_name}', ...) instead."
                                ),
                                severity="ERROR",
                                col=start_c,
                                end_col=end_c,
                            ),
                            noqa_map,
                        )
                        break

                    # RPY201: Прямая мутация глобального состояния
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

        except SyntaxError as e:
            # log debug instead of silent suppress.
            _logger.debug("check_screen_mutation: ast.parse failed: %s", e)
    def check_python_ast(
        self,
        py_code: str,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None = None,
    ) -> None:
        """Парсит Python-код и запускает рекурсивный обход AST."""
        try:
            tree = ast.parse(py_code)
            self._walk_python_nodes(
                tree.body,
                file_path,
                start_line,
                noqa_map,
                lines,
                local_scope=set(),
            )

        except SyntaxError as e:
            # log debug instead of silent suppress.
            _logger.debug("check_python_ast: ast.parse failed: %s", e)
    def _visit_import(
        self,
        node: ast.Import,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None,
    ) -> None:
        """RPY106: import random → renpy.random."""
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

    def _visit_import_from(
        self,
        node: ast.ImportFrom,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None,
    ) -> None:
        """RPY106: from random import ... → renpy.random."""
        if node.module == "random":
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

    def _visit_augassign(
        self,
        node: ast.AugAssign,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None,
        local_scope: set[str],
    ) -> None:
        """RPY105/RPY102/RPY108: augmented assignment (+=, -=) checks."""
        if isinstance(node.target, ast.Name):
            self._check_augassign_name(
                node, file_path, start_line, noqa_map, lines, local_scope
            )
        elif isinstance(node.target, ast.Subscript):
            self._check_augassign_subscript(
                node, file_path, start_line, noqa_map, lines, local_scope
            )

    def _check_augassign_name(
        self,
        node: ast.AugAssign,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None,
        local_scope: set[str],
    ) -> None:
        """RPY105/RPY102/RPY108: augmented assignment to Name target ($ CONST += 1)."""
        var_name = node.target.id
        if var_name in local_scope:
            return

        real_line = start_line + getattr(node, "lineno", 1) - 1
        raw_l = (
            lines[real_line - 1]
            if lines and 0 <= real_line - 1 < len(lines)
            else ""
        )
        if (
            (not raw_l or var_name not in raw_l)
            and lines
            and 0 <= start_line - 1 < len(lines)
        ):
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
            self._check_augassign_type_conflict(
                var_name, var_sym, node.value, file_path, real_line, raw_l, start_c, end_c, noqa_map
            )

    def _check_augassign_type_conflict(
        self,
        var_name: str,
        var_sym,
        value_node: ast.AST,
        file_path: str,
        real_line: int,
        raw_l: str,
        start_c: int,
        end_c: int,
        noqa_map: dict,
    ) -> None:
        """RPY108: Check incompatible type in augmented assignment (+=, -=)."""
        expected_t = var_sym.type_name if var_sym else None
        op_t = infer_ast_type(value_node, known_vars=self.analyzer.variables)
        if not expected_t or not op_t:
            return

        is_incompatible = (
            expected_t == "str" and op_t != "str"
            or expected_t in ("int", "float") and op_t not in ("int", "float")
            or expected_t == "list" and op_t not in ("list",)
            or expected_t in ("dict", "bool")
        )

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

    def _check_augassign_subscript(
        self,
        node: ast.AugAssign,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None,
        local_scope: set[str],
    ) -> None:
        """RPY105/RPY102: augmented assignment to Subscript target ($ CONST[x] += 1)."""
        root_name = _get_root_name(node.target.value)
        if (
            not root_name
            or root_name in local_scope
            or root_name in SYSTEM_MUTABLE_NAMESPACES
        ):
            return

        real_line = start_line + getattr(node, "lineno", 1) - 1
        raw_l = (
            lines[real_line - 1]
            if lines and 0 <= real_line - 1 < len(lines)
            else ""
        )
        start_c, end_c = get_utf16_range(raw_l, root_name)

        root_var = self.analyzer.variables.get(root_name)
        if root_var and root_var.is_constant and not root_var.is_character:
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
        elif root_name not in self.analyzer.declared_symbols:
            hint = suggest_similar_symbol(root_name, self.analyzer.user_symbols)
            self.analyzer._add_diagnostic(
                Diagnostic(
                    file_path=file_path,
                    line_number=real_line,
                    line_content=raw_l.strip(),
                    code="RPY102",
                    message=f"Augmented assignment to subscript of undeclared variable '{root_name}' before declaration{hint}. Causes runtime NameError.",
                    col=start_c,
                    end_col=end_c,
                ),
                noqa_map,
            )

    def _visit_assign(
        self,
        node: ast.Assign,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None,
        local_scope: set[str],
    ) -> None:
        """RPY104/RPY105/RPY106/RPY108: assignment checks."""
        real_line = start_line + getattr(node, "lineno", 1) - 1
        raw_l = lines[real_line - 1] if lines and 0 <= real_line - 1 < len(lines) else ""
        if not raw_l.strip() and lines and 0 <= start_line - 1 < len(lines):
            raw_l = lines[start_line - 1]

        self._check_assign_set_usage(node, file_path, real_line, raw_l, noqa_map)

        for target in node.targets:
            if isinstance(target, ast.Name):
                self._check_assign_name_target(
                    target, node.value, file_path, real_line, raw_l, noqa_map, local_scope
                )
            elif isinstance(target, ast.Subscript):
                self._check_assign_subscript_target(
                    target, file_path, real_line, raw_l, noqa_map, local_scope
                )
            elif isinstance(target, (ast.Tuple, ast.List)):
                self._check_assign_tuple_target(
                    target, node.value, file_path, real_line, raw_l, noqa_map, local_scope
                )

    def _check_assign_set_usage(
        self, node: ast.Assign, file_path: str, real_line: int, raw_l: str, noqa_map: dict
    ) -> None:
        """RPY106: Check for mutable set() usage in story flow."""
        is_set = (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "set"
        ) or isinstance(node.value, (ast.Set, ast.SetComp))

        if not is_set:
            return

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

    def _check_assign_name_target(
        self, target: ast.Name, value_node: ast.AST, file_path: str,
        real_line: int, raw_l: str, noqa_map: dict, local_scope: set[str]
    ) -> None:
        """RPY104/RPY108: Check assignment to Name target ($ var = value)."""
        if target.id in local_scope:
            return

        self._verify_assign_target(
            target.id, file_path, real_line, noqa_map, raw_line=raw_l, val_node=value_node
        )

        # RPY108: Type conflict check ($ var = "High" when var was int)
        expected_t = (
            self.analyzer.variables[target.id].type_name
            if target.id in self.analyzer.variables
            else None
        )
        new_t = infer_ast_type(value_node, known_vars=self.analyzer.variables)
        if (
            expected_t
            and new_t
            and expected_t != new_t
            and expected_t != "None"  # None -> any type allowed (initial init)
            and new_t != "None"  # any type -> None allowed (reset to sentinel)
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

    def _check_assign_subscript_target(
        self, target: ast.Subscript, file_path: str, real_line: int,
        raw_l: str, noqa_map: dict, local_scope: set[str]
    ) -> None:
        """RPY105/RPY102: Check subscript assignment ($ CONST["key"] = "value")."""
        root_name = _get_root_name(target.value)
        if (
            not root_name
            or root_name in local_scope
            or root_name in SYSTEM_MUTABLE_NAMESPACES
        ):
            return

        root_var = self.analyzer.variables.get(root_name)
        if root_var and root_var.is_constant and not root_var.is_character:
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
        elif root_name not in self.analyzer.declared_symbols:
            start_c, end_c = get_utf16_range(raw_l, root_name)
            hint = suggest_similar_symbol(root_name, self.analyzer.user_symbols)
            self.analyzer._add_diagnostic(
                Diagnostic(
                    file_path=file_path,
                    line_number=real_line,
                    line_content=raw_l.strip(),
                    code="RPY102",
                    message=f"Subscript assignment to undeclared variable '{root_name}' before declaration{hint}. Causes runtime NameError.",
                    col=start_c,
                    end_col=end_c,
                ),
                noqa_map,
            )

    def _check_assign_tuple_target(
        self, target: ast.Tuple | ast.List, value_node: ast.AST, file_path: str,
        real_line: int, raw_l: str, noqa_map: dict, local_scope: set[str]
    ) -> None:
        """RPY104: Check tuple/list unpacking assignment ($ a, b = 1, 2)."""
        for elt in target.elts:
            if isinstance(elt, ast.Name) and elt.id not in local_scope:
                self._verify_assign_target(
                    elt.id, file_path, real_line, noqa_map,
                    raw_line=raw_l, val_node=value_node,
                )

    def _visit_mutating_methods(
        self,
        node: ast.stmt,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None,
        local_scope: set[str],
    ) -> None:
        """RPY105/RPY102/RPY108: mutation of constants via methods (list.append, etc.).

        Runs for ALL non-function nodes (Import, Assign, If, etc.).
        Uses ast.walk to find Call nodes within statement.
        """
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                self._check_mutating_method_call(
                    sub, file_path, start_line, noqa_map, lines, local_scope
                )
                self._check_invalid_method_call(
                    sub, file_path, start_line, noqa_map, lines, local_scope
                )

    def _check_mutating_method_call(
        self, sub: ast.Call, file_path: str, start_line: int,
        noqa_map: dict, lines: list[str] | None, local_scope: set[str]
    ) -> None:
        """RPY105/RPY102: Check mutating methods (.append, .update, etc.) on
        constants and undeclared variables."""
        method_name = sub.func.attr
        if method_name not in MUTATING_METHODS:
            return

        root_name = _get_root_name(sub.func.value)
        if (
            not root_name
            or root_name in local_scope
            or root_name in SYSTEM_MUTABLE_NAMESPACES
        ):
            return

        real_line = start_line + getattr(sub, "lineno", 1) - 1
        raw_l = (
            lines[real_line - 1]
            if lines and 0 <= real_line - 1 < len(lines)
            else ""
        )
        target_str = f"{root_name}.{method_name}"
        sub_str = target_str if target_str in raw_l else root_name
        start_c, end_c = get_utf16_range(raw_l, sub_str)

        root_var = self.analyzer.variables.get(root_name)
        if root_var and root_var.is_constant and not root_var.is_character:
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
        elif root_name not in self.analyzer.declared_symbols:
            hint = suggest_similar_symbol(root_name, self.analyzer.user_symbols)
            self.analyzer._add_diagnostic(
                Diagnostic(
                    file_path=file_path,
                    line_number=real_line,
                    line_content=raw_l.strip(),
                    code="RPY102",
                    message=f"Method call '.{method_name}()' on undeclared variable '{root_name}' before declaration{hint}. Causes runtime NameError.",
                    col=start_c,
                    end_col=end_c,
                ),
                noqa_map,
            )

    def _check_invalid_method_call(
        self, sub: ast.Call, file_path: str, start_line: int,
        noqa_map: dict, lines: list[str] | None, local_scope: set[str]
    ) -> None:
        """RPY108: Check for invalid method calls on known built-in types
        (list.add → .append, dict.append, str.pop, etc.)."""
        method_name = sub.func.attr
        if not isinstance(sub.func.value, ast.Name) or method_name.startswith("_"):
            return

        var_id = sub.func.value.id
        var_sym = self.analyzer.variables.get(var_id)
        if (
            not var_sym
            or var_sym.type_name not in KNOWN_TYPE_METHODS
            or var_id in local_scope
        ):
            return

        t_name = var_sym.type_name
        valid_methods = KNOWN_TYPE_METHODS[t_name]
        if method_name in valid_methods:
            return

        real_line = start_line + getattr(sub, "lineno", 1) - 1
        raw_l = (
            lines[real_line - 1]
            if lines and 0 <= real_line - 1 < len(lines)
            else ""
        )
        target_str = f"{var_id}.{method_name}"
        sub_str = target_str if target_str in raw_l else method_name
        start_c, end_c = get_utf16_range(raw_l, sub_str)

        if (t_name, method_name) in METHOD_SUGGESTIONS:
            hint = f" (did you mean '{METHOD_SUGGESTIONS[(t_name, method_name)]}' ?)"
        else:
            matches = difflib.get_close_matches(
                method_name, list(valid_methods), n=1, cutoff=0.6
            )
            hint = f" (did you mean '.{matches[0]}()' ?)" if matches else ""

        self.analyzer._add_diagnostic(
            Diagnostic(
                file_path=file_path,
                line_number=real_line,
                line_content=raw_l.strip(),
                code="RPY108",
                message=(
                    f"Invalid method call: variable '{var_id}' has type '{t_name}', "
                    f"which does not have a method '.{method_name}()'{hint}. Causes runtime AttributeError."
                ),
                severity="ERROR",
                col=start_c,
                end_col=end_c,
            ),
            noqa_map,
        )

    def _visit_if_while(
        self,
        node: ast.If | ast.While,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None,
        local_scope: set[str],
    ) -> None:
        """Рекурсивный обход body и orelse для if/while."""
        self._walk_python_nodes(
            node.body, file_path, start_line, noqa_map, lines, local_scope
        )
        self._walk_python_nodes(
            node.orelse, file_path, start_line, noqa_map, lines, local_scope
        )

    def _visit_for(
        self,
        node: ast.For,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None,
        local_scope: set[str],
    ) -> None:
        """Рекурсивный обход body и orelse для for, с loop variable в scope."""
        loop_scope = set(local_scope)
        if isinstance(node.target, ast.Name):
            loop_scope.add(node.target.id)
        elif isinstance(node.target, (ast.Tuple, ast.List)):
            for elt in node.target.elts:
                if isinstance(elt, ast.Name):
                    loop_scope.add(elt.id)
        self._walk_python_nodes(
            node.body, file_path, start_line, noqa_map, lines, loop_scope
        )
        self._walk_python_nodes(
            node.orelse, file_path, start_line, noqa_map, lines, loop_scope
        )

    def _visit_try(
        self,
        node: ast.Try,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None,
        local_scope: set[str],
    ) -> None:
        """Рекурсивный обход body, orelse, finalbody и handlers для try."""
        self._walk_python_nodes(
            node.body, file_path, start_line, noqa_map, lines, local_scope
        )
        self._walk_python_nodes(
            node.orelse, file_path, start_line, noqa_map, lines, local_scope
        )
        self._walk_python_nodes(
            node.finalbody, file_path, start_line, noqa_map, lines, local_scope
        )
        for handler in node.handlers:
            h_scope = set(local_scope)
            if handler.name:
                h_scope.add(handler.name)
            self._walk_python_nodes(
                handler.body, file_path, start_line, noqa_map, lines, h_scope
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
        """Dispatcher: обрабатывает top-level statements через _visit_* методы.

        Phase 3 Step 4 (0.5.6): разбит с 479 строк на 8 методов + dispatcher.
        Каждый _visit_* метод обрабатывает один тип AST-узла.
        """
        for node in nodes:
            # Игнорируем вложенные функции и классы, они создают свой локальный скоуп
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue

            if isinstance(node, ast.Import):
                self._visit_import(node, file_path, start_line, noqa_map, lines)
            elif isinstance(node, ast.ImportFrom):
                self._visit_import_from(node, file_path, start_line, noqa_map, lines)
            elif isinstance(node, ast.AugAssign):
                self._visit_augassign(node, file_path, start_line, noqa_map, lines, local_scope)
            elif isinstance(node, ast.Assign):
                self._visit_assign(node, file_path, start_line, noqa_map, lines, local_scope)

            # 4. Мутирующие методы Python и валидация методов встроенных типов
            # Запускается для ВСЕХ non-function узлов (отдельный if, не elif).
            # Note: оригинальный код имел if-elif цепочку здесь, где if был
            # всегда True (not isinstance FunctionDef), что делало elif
            # (If/While/For/Try) dead code. Поведение сохранено для совместимости.
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self._visit_mutating_methods(node, file_path, start_line, noqa_map, lines, local_scope)
            elif isinstance(node, (ast.If, ast.While)):
                self._visit_if_while(node, file_path, start_line, noqa_map, lines, local_scope)
            elif isinstance(node, ast.For):
                self._visit_for(node, file_path, start_line, noqa_map, lines, local_scope)
            elif isinstance(node, ast.Try):
                self._visit_try(node, file_path, start_line, noqa_map, lines, local_scope)


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
        if (
            var_name.startswith("_")
            or (var_sym and var_sym.is_character)
            or var_name in SYSTEM_MUTABLE_NAMESPACES
        ):
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
        try:
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
                    if isinstance(n, ast.UnaryOp)
                    and isinstance(n.op, ast.Not)
                    and isinstance(n.operand, ast.Name)
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
                    if (
                        var_name not in self.analyzer.declared_symbols
                        and var_name not in screen_local_symbols
                    ):
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

        except SyntaxError as e:
            # log debug instead of silent suppress.
            _logger.debug("check_condition: ast.parse failed: %s", e)
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
        try:
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
                                f"Variable '{node.id}' may be uninitialized (MAYBE_SET) if "
                                f"{reason} on line {menu_line}. Condition will crash with NameError."
                            ),
                            col=start_c,
                            end_col=end_c,
                        ),
                        noqa_map,
                    )

        except SyntaxError as e:
            # log debug instead of silent suppress.
            _logger.debug("check_cfg_condition: ast.parse failed: %s", e)
    def clear_safe_cfg_vars(self, py_code: str, branch_uninitialized: dict) -> None:
        """Удаляет переменные из неинициализированных, если им присвоено значение."""
        try:
            tree = ast.parse(py_code)
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            branch_uninitialized.pop(target.id, None)


        except SyntaxError as e:
            # log debug instead of silent suppress.
            _logger.debug("clear_safe_cfg_vars: ast.parse failed: %s", e)

