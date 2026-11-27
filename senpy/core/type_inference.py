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
import logging
from typing import TYPE_CHECKING, Any

from senpy.core.constants import TYPE_INFERENCE_MAX_DEPTH
from senpy.text_utils import parse_python_silent

if TYPE_CHECKING:
    pass  # no type-only imports needed yet

_logger = logging.getLogger(__name__)


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
    if val_node is None or depth > TYPE_INFERENCE_MAX_DEPTH:
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
    """Infer type from a variable name reference.

    In Python 3, ``True`` / ``False`` / ``None`` are keywords, not
    identifiers — ``ast.parse("True")`` returns ``ast.Constant``, not
    ``ast.Name``. The previous special-case branches for ``node.id in
    ("True", "False")`` and ``node.id == "None"`` were therefore dead
    code (unreachable since the Python 2 → 3 migration) and have been
    removed. Boolean/None literals are handled by ``_infer_constant``.
    """
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

    # Numeric arithmetic: int + int → int, int + float → float.
    # Note: ``bool`` is a subtype of ``int`` in Python (True == 1, False == 0),
    # so ``True + 1 == 2``, ``True * 3 == 3`` and ``True - 1 == 0`` are
    # legitimate. Treat ``bool`` the same as ``int`` for numeric arithmetic
    # — fixes false-positive RPY108 on ``$ total = True + 1`` and
    # ``$ count = enabled * 3``. Result of any bool+numeric op is ``int``
    # (or ``float`` if either operand is float), matching Python semantics
    # (``True + True == 2``, not ``True``).
    _NUMERIC_TYPES = ("int", "float", "bool")
    if lt in _NUMERIC_TYPES and rt in _NUMERIC_TYPES:
        if "float" in (lt, rt):
            return "float"
        # Both operands are int/bool — result is int (bool arithmetic
        # promotes to int in Python).
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

    if {lt, rt} <= {"int", "float", "bool"}:
        return None

    op = node.op
    if isinstance(op, ast.Add):
        return _check_add_compat(lt, rt)
    if isinstance(op, ast.Sub):
        return _check_sub_compat(lt, rt)
    if isinstance(op, ast.Mult):
        return _check_mult_compat(lt, rt)
    if isinstance(op, ast.Mod):
        # ``%`` has two distinct semantics in Python:
        #   1. String formatting: ``"%d" % 5``, ``"%s" % (a, b)``, ``"%(x)s" % {"x": 1}``
        #      — left operand is a format string, right operand can be anything.
        #   2. Numeric modulo: ``7 % 3`` — both operands numeric.
        # Numeric ``%`` is already handled by the ``{lt, rt} <= {"int", "float", "bool"}``
        # guard above (returns None = compatible). If we reach this branch, at least
        # one operand is non-numeric. ``str % any`` is valid (formatting); any other
        # non-numeric combination (``list % int``, ``dict % str``, ``set % int``,
        # ``int % str``) is a TypeError at runtime — flag as incompatible so RPY108
        # can surface it.
        #
        # Previously this branch unconditionally returned ``None`` (silent pass),
        # which meant RPY108 never fired on ``$ x = [1,2] % 3`` or similar clearly
        # invalid code. Restricting the pass to ``lt == "str"`` matches
        # ``_check_mult_compat``'s pattern (only specific type pairs are OK).
        if lt == "str":
            return None
        return (lt, rt, "%")
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
    # ``bool`` is a subtype of ``int`` in Python — ``True - False == 1`` and
    # ``True - 1 == 0`` are legitimate. ``_check_binop_incompatible`` already
    # handled pure ``int`` / ``float`` (they return None before reaching here),
    # but ``bool`` was excluded from the numeric set (now fixed), so callers
    # used to land here and get an unconditional "incompatible" verdict.
    # After the bool fix in ``_infer_binop``, we treat ``bool`` as numeric —
    # this stub stays correct because it is only reached for non-numeric
    # operand pairs (``str - str``, ``list - int``, etc.), which ARE
    # incompatible in Python.
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
    # dict.keys() / dict.values() / dict.items() return view objects in
    # Python 3 (dict_keys / dict_values / dict_items), NOT lists. Returning
    # "list" here would make RPY108 consider ``$ ks = d.keys(); $ ks.append(x)``
    # valid (it's not — AttributeError at runtime). Return None (unknown
    # type) so the type-inference caller treats it conservatively.
    #
    # If we ever introduce proper view types (``dict_keys`` / ``dict_values``
    # / ``dict_items``), this is the place to return them.
    if method in ("keys", "values", "items"):
        return None
    return None


def infer_expr_type(
    expr_str: str | None,
    known_vars: dict[str, Any] | None = None,
) -> str | None:
    """Infers the type of an expression from an assignment string considering known symbols."""
    if not expr_str or not expr_str.strip():
        return None
    try:
        tree = parse_python_silent(expr_str.strip(), mode="eval")
        return infer_ast_type(tree.body, known_vars=known_vars)
    except (SyntaxError, ValueError, TypeError) as e:
        # Match the logging discipline of ``signature.parse_signature`` —
        # silent ``return None`` on parse failure hides bugs in the
        # inference pipeline (a regression in ``parse_python_silent`` or
        # a new unhandled node type would manifest as a silent type-None
        # and produce RPY108 false negatives). DEBUG-level so it does
        # not spam normal runs; visible with ``--verbose`` / ``--log-level
        # senpy.core.type_inference=DEBUG``.
        _logger.debug("type inference failed for %r: %s", expr_str, e)
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
        # Was ``return "[]"`` — silently changed the type to list,
        # after which ``.add()`` calls on the variable tripped RPY108 (list
        # has no ``.add()`` method). The chain was: RPY106 warns about set
        # → ``--defaults`` generator writes ``default x = []`` → user's
        # existing ``$ x.add(...)`` code triggers RPY108. The proper default
        # is ``renpy.revertable_set()`` — Ren'Py's rollback-compatible set
        # type (has ``.add()``, ``.discard()``, ``.remove()`` like the
        # built-in set, and reverts correctly during rollback). This is
        # exactly what RPY106 suggests as the safe alternative.
        return "renpy.revertable_set()"
    if t == "None":
        return "None"
    return "False"


# Ren'Py system namespaces whose mutation is allowed during the game.
# Assigning to ``persistent.foo``, ``config.bar``, ``store.baz``,
# ``gui.qux``, ``style.quux`` is normal Ren'Py initialization — these
# namespaces are designed to be mutated at runtime (config flags,
# persistent save data, gui/theme overrides, style properties).
#
# ``audio`` is intentionally NOT in this set, even though it is a Ren'Py
# system namespace (see ``BUILTIN_SYMBOLS`` in ``senpy/core/renpy_builtins.py``).
# Mutations of ``audio`` itself (``$ audio.foo = bar``) are rare and
# almost always indicate a bug — the intended pattern is to register
# channels via ``renpy.music.register_channel()`` and reference them by
# name, or use ``define audio.bgm = "track.ogg"`` for aliases (which
# goes through the ``define`` machinery, not runtime assignment). If a
# project does need to mutate ``audio`` at runtime, the resulting
# RPY105 is a useful prompt to add an explicit ``default audio.foo``
# declaration. Re-evaluate if a real-world project surfaces this as a
# false positive.
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
    # Tuples expose only two non-mutating methods (``count`` and ``index``) —
    # the same two that ``list`` inherits from ``Sequence``. Without this
    # entry, ``$ x = (1, 2).count(1)`` would route to the "unknown method"
    # path and could produce a false RPY108 (type taint) on valid tuple
    # introspection. Tuples are immutable, so no mutating methods are listed.
    "tuple": {
        "count",
        "index",
    },
}

# Hints for common cross-type mistakes (e.g., .add() instead of .append() on a list).
# Keys are ``(type_name, method_name)`` pairs where the method exists on a *different*
# built-in type and the user likely confused the two. The value is the correct method
# (or operation) on the actual type — surfaced as ``" (did you mean '...' ?)"`` in the
# RPY108 diagnostic. When a pair is NOT in this map, the caller falls back to
# ``difflib.get_close_matches`` against the type's actual method list.
METHOD_SUGGESTIONS: dict[tuple[str, str], str] = {
    # Existing entries — list/dict/set confusion on add/append.
    ("list", "add"): ".append()",
    ("dict", "append"): ".update()",
    ("set", "append"): ".add()",
    # ``discard`` is a set method (no-op if key absent); on list the
    # equivalent is ``.remove()`` (raises if absent) — flag the typo.
    ("list", "discard"): ".remove()",
    # ``discard`` on dict has no direct equivalent — ``.pop(key, None)``
    # is the closest (returns the value, no-op if absent).
    ("dict", "discard"): ".pop(key, None)",
    # Tuples are immutable — any mutating method is a typo for a list operation.
    # Suggest conversion rather than a phantom method.
    ("tuple", "append"): "(convert to list first)",
    ("tuple", "remove"): "(convert to list first)",
}
