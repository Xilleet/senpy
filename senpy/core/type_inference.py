"""Type inference for Python AST expressions.

Extracted from senpy/rules/python_ast.py.

Provides:
  - infer_ast_type(node, known_vars, depth) → str | None
      Main dispatcher: infers the Python type of an AST expression node.
  - infer_expr_type(expr_str, known_vars) → str | None
      Parse + infer: convenience wrapper that parses a string expression.
  - infer_default_value(expr_str) → str
      Infers a safe default value for a variable from its initializer.
  - _infer_* helpers (constant, name, collection, unaryop, binop, ifexp, call,
      builtin_function, method_call) — dispatched to by infer_ast_type.
  - _check_binop_incompatible / _check_*_compat — type compatibility checks
      for binary operations (used by RPY108 type taint detection).

Used by:
  - senpy/rules/python_ast.py (PythonAstChecker._check_augassign_type_conflict)
  - senpy/core/file_collector.py (FileCollector._collect_define — infers
    VariableSymbol.type_name from the initializer expression)
  - senpy/rules/checkers/state.py (imported transitively)
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass  # no type-only imports needed yet


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
    elif isinstance(
        val_node, (ast.List, ast.ListComp, ast.Dict, ast.DictComp, ast.Set, ast.SetComp, ast.Tuple)
    ):
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


def _infer_unaryop(node: ast.UnaryOp, known_vars: dict | None, depth: int) -> str | None:
    """Infer type from unary operations (not x → bool, -x → int/float)."""
    if isinstance(node.op, ast.Not):
        return "bool"
    if isinstance(node.op, (ast.USub, ast.UAdd)):
        operand_t = infer_ast_type(node.operand, known_vars, depth + 1)
        if operand_t in ("int", "float"):
            return operand_t
    return None


def _infer_binop(node: ast.BinOp, known_vars: dict | None, depth: int) -> str | None:
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


def _check_binop_incompatible(
    node: ast.BinOp,
    known_vars: dict[str, Any] | None = None,
) -> tuple[str, str, str] | None:
    """Check if a BinOp has incompatible operand types.

    Returns (left_type, right_type, op_name) if incompatible, None if OK or unknown.

    Thin dispatcher: delegates to per-op helpers.
    """
    lt = infer_ast_type(node.left, known_vars)
    rt = infer_ast_type(node.right, known_vars)
    if not lt or not rt:
        return None

    if {lt, rt} <= {"int", "float"}:
        return None

    op = node.op
    if isinstance(op, ast.Add):
        return _check_add_compat(lt, rt)
    if isinstance(op, ast.Sub):
        return _check_sub_compat(lt, rt)
    if isinstance(op, ast.Mult):
        return _check_mult_compat(lt, rt)
    if isinstance(op, ast.Mod):
        return None  # str % any OK (formatting), numeric handled above
    if isinstance(op, (ast.FloorDiv, ast.Pow)):
        return (lt, rt, "//" if isinstance(op, ast.FloorDiv) else "**")
    return None


def _check_add_compat(lt: str, rt: str) -> tuple[str, str, str] | None:
    """Add (+): str+str OK, list+list OK. All else incompatible."""
    if (lt == "str" and rt == "str") or (lt == "list" and rt == "list"):
        return None
    return (lt, rt, "+")


def _check_sub_compat(lt: str, rt: str) -> tuple[str, str, str] | None:
    """Sub (-): only numeric types (int/float already handled by caller)."""
    return (lt, rt, "-")


def _check_mult_compat(lt: str, rt: str) -> tuple[str, str, str] | None:
    """Mult (*): str*int OK, int*str OK, list*int OK, int*list OK. All else incompatible."""
    compatible = (
        (lt == "str" and rt == "int")
        or (lt == "int" and rt == "str")
        or (lt == "list" and rt == "int")
        or (lt == "int" and rt == "list")
    )
    if compatible:
        return None
    return (lt, rt, "*")


def _infer_ifexp(node: ast.IfExp, known_vars: dict | None, depth: int) -> str | None:
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
        "upper",
        "lower",
        "strip",
        "lstrip",
        "rstrip",
        "replace",
        "format",
        "capitalize",
        "title",
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
    """Infers the type of an expression from an assignment string considering known symbols."""
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
    """Infers a safe default value based on the computed node type."""
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


# Ren'Py system namespaces whose mutation is allowed during the game
SYSTEM_MUTABLE_NAMESPACES = {"persistent", "config", "store", "gui", "style"}

MUTATING_METHODS = {
    # Lists (list / deque)
    "append",
    "extend",
    "insert",
    "remove",
    "pop",
    "clear",
    "reverse",
    "sort",
    # Sets (set)
    "add",
    "discard",
    "difference_update",
    "intersection_update",
    "symmetric_difference_update",
    # Dictionaries (dict)
    "update",
    "popitem",
    "setdefault",
}

# Allowed standard methods of built-in data types
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

# Hints for common cross-type mistakes (e.g., .add() instead of .append() on a list)
METHOD_SUGGESTIONS: dict[tuple[str, str], str] = {
    ("list", "add"): ".append()",
    ("dict", "append"): ".update()",
    ("set", "append"): ".add()",
}
