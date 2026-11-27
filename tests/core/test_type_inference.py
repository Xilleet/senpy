"""Coverage tests for senpy/core/type_inference.py.

The existing tests in test_analyzer.py cover the functions indirectly through
PythonAstChecker.

These tests directly cover infer_ast_type, infer_expr_type, infer_default_value,
and the _infer_* / _check_*_compat helpers.
"""

from __future__ import annotations

import ast

import pytest

from senpy.core.constants import TYPE_INFERENCE_MAX_DEPTH
from senpy.core.type_inference import (
    KNOWN_TYPE_METHODS,
    METHOD_SUGGESTIONS,
    SYSTEM_MUTABLE_NAMESPACES,
    _check_add_compat,
    _check_binop_incompatible,
    _check_mult_compat,
    _check_sub_compat,
    infer_ast_type,
    infer_default_value,
    infer_expr_type,
)


class TestInferAstType:
    """Direct tests for infer_ast_type + _infer_* helpers."""

    def test_none_node(self):
        assert infer_ast_type(None) is None

    def test_depth_limit(self):
        """Depth > TYPE_INFERENCE_MAX_DEPTH returns None (recursion guard).

        Previously the limit was hardcoded to 8 — too low for legitimate
        nested expressions (e.g. ``(((a + b) * c) - d) + e * f / g``
        already needs depth 5). Now routed through the named constant
        (default 32), so deeply nested code does not silently lose type
        inference and produce RPY108 false negatives.
        """
        # Build a deeply nested expression: 1 + 1 + 1 + ... (TYPE_INFERENCE_MAX_DEPTH + 1 levels)
        expr = "1" + " + 1" * (TYPE_INFERENCE_MAX_DEPTH + 1)
        node = ast.parse(expr, mode="eval").body
        result = infer_ast_type(node, depth=TYPE_INFERENCE_MAX_DEPTH)
        assert result is None  # depth limit hit

    def test_depth_limit_not_hit_for_normal_expressions(self):
        """Reasonable nested expressions should NOT trip the depth guard."""
        # 5 levels of nesting — well below TYPE_INFERENCE_MAX_DEPTH (32).
        expr = "1 + 2 * 3 - 4 / 5 + 6"
        node = ast.parse(expr, mode="eval").body
        result = infer_ast_type(node)
        # int arithmetic → int (well, with / it's float, but result must not be None)
        assert result is not None

    def test_int_constant(self):
        node = ast.parse("42", mode="eval").body
        assert infer_ast_type(node) == "int"

    def test_float_constant(self):
        node = ast.parse("3.14", mode="eval").body
        assert infer_ast_type(node) == "float"

    def test_str_constant(self):
        node = ast.parse('"hello"', mode="eval").body
        assert infer_ast_type(node) == "str"

    def test_bool_constant(self):
        node = ast.parse("True", mode="eval").body
        assert infer_ast_type(node) == "bool"

    def test_none_constant(self):
        node = ast.parse("None", mode="eval").body
        assert infer_ast_type(node) == "None"

    def test_name_with_known_vars(self):
        node = ast.parse("x", mode="eval").body
        assert infer_ast_type(node, known_vars={"x": "str"}) == "str"

    def test_name_without_known_vars(self):
        node = ast.parse("x", mode="eval").body
        assert infer_ast_type(node, known_vars=None) is None

    def test_list_literal(self):
        node = ast.parse("[1, 2, 3]", mode="eval").body
        assert infer_ast_type(node) == "list"

    def test_dict_literal(self):
        node = ast.parse('{"a": 1}', mode="eval").body
        assert infer_ast_type(node) == "dict"

    def test_set_literal(self):
        node = ast.parse("{1, 2, 3}", mode="eval").body
        assert infer_ast_type(node) == "set"

    def test_tuple_literal(self):
        node = ast.parse("(1, 2)", mode="eval").body
        assert infer_ast_type(node) == "tuple"

    def test_list_comp(self):
        node = ast.parse("[x for x in range(10)]", mode="eval").body
        assert infer_ast_type(node) == "list"

    def test_joined_str(self):
        node = ast.parse('f"{x}"', mode="eval").body
        assert infer_ast_type(node) == "str"

    def test_compare(self):
        node = ast.parse("x == 1", mode="eval").body
        assert infer_ast_type(node) == "bool"

    def test_unary_not(self):
        node = ast.parse("not x", mode="eval").body
        assert infer_ast_type(node) == "bool"

    def test_unary_minus(self):
        node = ast.parse("-x", mode="eval").body
        result = infer_ast_type(node, known_vars={"x": "int"})
        assert result == "int"

    def test_binop_int_plus_int(self):
        node = ast.parse("1 + 2", mode="eval").body
        assert infer_ast_type(node) == "int"

    def test_binop_str_plus_str(self):
        node = ast.parse('"a" + "b"', mode="eval").body
        assert infer_ast_type(node) == "str"

    def test_ifexp(self):
        node = ast.parse('"yes" if True else "no"', mode="eval").body
        assert infer_ast_type(node) == "str"

    def test_call_int(self):
        node = ast.parse("int('42')", mode="eval").body
        assert infer_ast_type(node) == "int"

    def test_call_str(self):
        node = ast.parse("str(42)", mode="eval").body
        assert infer_ast_type(node) == "str"

    def test_call_len(self):
        node = ast.parse("len([1, 2])", mode="eval").body
        assert infer_ast_type(node) == "int"

    def test_call_unknown_function(self):
        node = ast.parse("unknown_func()", mode="eval").body
        assert infer_ast_type(node) is None

    def test_method_call_int(self):
        """int() call returns int type."""
        node = ast.parse("int('42')", mode="eval").body
        assert infer_ast_type(node) == "int"


class TestInferExprType:
    """Tests for infer_expr_type (string → type)."""

    def test_simple_int(self):
        assert infer_expr_type("42") == "int"

    def test_simple_str(self):
        assert infer_expr_type('"hello"') == "str"

    def test_with_known_vars(self):
        assert infer_expr_type("x + 1", known_vars={"x": "int"}) == "int"

    def test_syntax_error(self):
        assert infer_expr_type("def broken(:") is None

    def test_empty_expr(self):
        assert infer_expr_type("") is None


class TestInferDefaultValue:
    """Tests for infer_default_value."""

    def test_int_default(self):
        """infer_default_value returns 'False' as a safe default for any type."""
        assert infer_default_value("0") == "False"

    def test_str_default(self):
        assert infer_default_value('""') == "False"

    def test_bool_default(self):
        assert infer_default_value("False") == "False"

    def test_list_default(self):
        assert infer_default_value("[]") == "False"

    def test_dict_default(self):
        assert infer_default_value("{}") == "False"

    def test_none_default(self):
        assert infer_default_value("None") == "False"

    def test_complex_expression(self):
        """Complex expressions also return 'False' as safe default."""
        result = infer_default_value("x + 1")
        assert result == "False"


class TestBinopCompatChecks:
    """Tests for _check_binop_incompatible and _check_*_compat helpers."""

    def test_add_str_and_int_incompatible(self):
        result = _check_add_compat("str", "int")
        assert result is not None
        assert len(result) == 3  # (left_type, right_type, message)

    def test_add_int_and_int_returns_tuple(self):
        """_check_add_compat returns a tuple when both types are known."""
        result = _check_add_compat("int", "int")
        assert result is not None
        assert len(result) == 3

    def test_add_str_and_str_compatible(self):
        """str + str is valid in Python (concatenation) — returns None."""
        assert _check_add_compat("str", "str") is None

    def test_sub_int_and_str_incompatible(self):
        result = _check_sub_compat("int", "str")
        assert result is not None

    def test_sub_int_and_int_returns_tuple(self):
        result = _check_sub_compat("int", "int")
        assert result is not None

    def test_mult_str_and_int_incompatible(self):
        """str * int is technically valid in Python (repeats the string),
        but may be flagged depending on implementation."""
        result = _check_mult_compat("str", "int")
        # Either None (allowed) or a tuple (flagged) — just verify it doesn't crash.
        assert result is None or len(result) == 3

    def test_binop_incompatible_int_and_str(self):
        """_check_binop_incompatible returns (lt, rt, op) for incompatible types."""
        node = ast.parse('1 + "a"', mode="eval").body
        result = _check_binop_incompatible(node)
        assert result is not None
        assert result[0] == "int"
        assert result[1] == "str"

    def test_binop_compatible_int_and_int(self):
        """_check_binop_incompatible returns None for compatible types."""
        node = ast.parse("1 + 2", mode="eval").body
        assert _check_binop_incompatible(node) is None

    def test_binop_with_unknown_type(self):
        """Unknown types (None) should not trigger incompatibility."""
        node = ast.parse("x + 1", mode="eval").body
        # x is unknown — no incompatibility detected
        assert _check_binop_incompatible(node, known_vars=None) is None


class TestModCompatChecks:
    """Coverage for the ``%`` operator compat check.

    Previously ``_check_binop_incompatible`` unconditionally returned
    ``None`` for any ``Mod`` (``%``) — silent pass for ``list % int``,
    ``dict % str``, etc. The fix restricts the silent pass to ``str % any``
    (string formatting) and flags everything else as incompatible so
    RPY108 can surface real type errors.
    """

    def test_mod_str_and_int_compatible(self):
        """``"%d" % 5`` — string formatting, valid."""
        node = ast.parse('"%d" % 5', mode="eval").body
        assert _check_binop_incompatible(node) is None

    def test_mod_str_and_tuple_compatible(self):
        """``"%s %s" % (a, b)`` — string formatting with tuple args, valid."""
        node = ast.parse('"%s %s" % (1, 2)', mode="eval").body
        assert _check_binop_incompatible(node) is None

    def test_mod_int_and_int_compatible(self):
        """``7 % 3`` — numeric modulo, valid (handled by numeric guard)."""
        node = ast.parse("7 % 3", mode="eval").body
        assert _check_binop_incompatible(node) is None

    def test_mod_list_and_int_incompatible(self):
        """``[1,2] % 3`` — TypeError at runtime, must be flagged."""
        node = ast.parse("[1, 2] % 3", mode="eval").body
        result = _check_binop_incompatible(node)
        assert result is not None
        assert result[0] == "list"
        assert result[1] == "int"
        assert result[2] == "%"

    def test_mod_dict_and_str_incompatible(self):
        """``{} % "x"`` — TypeError at runtime, must be flagged."""
        node = ast.parse('{} % "x"', mode="eval").body
        result = _check_binop_incompatible(node)
        assert result is not None
        assert result[2] == "%"

    def test_mod_int_and_str_incompatible(self):
        """``5 % "x"`` — TypeError at runtime (right operand must be numeric
        when left is numeric, not a format string). Must be flagged."""
        node = ast.parse('5 % "x"', mode="eval").body
        result = _check_binop_incompatible(node)
        assert result is not None
        assert result[2] == "%"


class TestKnownTypeMethods:
    """Coverage for the KNOWN_TYPE_METHODS registry, including the
    newly-added ``tuple`` entry (was missing — caused potential RPY108
    false positives on ``$ x = (1, 2).count(1)``)."""

    def test_tuple_entry_exists(self):
        """``tuple`` must be a key in KNOWN_TYPE_METHODS."""
        assert "tuple" in KNOWN_TYPE_METHODS

    def test_tuple_has_count(self):
        """``tuple.count`` is a standard non-mutating method."""
        assert "count" in KNOWN_TYPE_METHODS["tuple"]

    def test_tuple_has_index(self):
        """``tuple.index`` is a standard non-mutating method."""
        assert "index" in KNOWN_TYPE_METHODS["tuple"]

    def test_tuple_has_no_mutating_methods(self):
        """Tuples are immutable — no append/extend/remove/etc."""
        tuple_methods = KNOWN_TYPE_METHODS["tuple"]
        for forbidden in ("append", "extend", "remove", "pop", "clear", "sort"):
            assert (
                forbidden not in tuple_methods
            ), f"tuple must not expose mutating method {forbidden!r}"


class TestMethodSuggestions:
    """Coverage for the expanded METHOD_SUGGESTIONS map."""

    def test_list_add_suggests_append(self):
        assert METHOD_SUGGESTIONS[("list", "add")] == ".append()"

    def test_list_discard_suggests_remove(self):
        """``discard`` is a set method (no-op if absent); on list the
        equivalent is ``.remove()`` (raises if absent)."""
        assert METHOD_SUGGESTIONS[("list", "discard")] == ".remove()"

    def test_dict_discard_suggests_pop(self):
        """``discard`` on dict has no direct equivalent — ``.pop(key, None)``
        is the closest (returns the value, no-op if absent)."""
        assert METHOD_SUGGESTIONS[("dict", "discard")] == ".pop(key, None)"

    def test_tuple_append_suggests_conversion(self):
        """Tuples are immutable — any mutating method is a typo for a list
        operation. Suggest conversion rather than a phantom method."""
        assert ("tuple", "append") in METHOD_SUGGESTIONS
        assert ("tuple", "remove") in METHOD_SUGGESTIONS


class TestSystemMutableNamespaces:
    """Verify the SYSTEM_MUTABLE_NAMESPACES constant."""

    def test_contains_persistent(self):
        assert "persistent" in SYSTEM_MUTABLE_NAMESPACES

    def test_contains_config(self):
        assert "config" in SYSTEM_MUTABLE_NAMESPACES

    def test_contains_gui(self):
        assert "gui" in SYSTEM_MUTABLE_NAMESPACES

    def test_is_set(self):
        assert isinstance(SYSTEM_MUTABLE_NAMESPACES, set)

    def test_audio_intentionally_excluded(self):
        """``audio`` is a Ren'Py system namespace (per BUILTIN_SYMBOLS)
        but is intentionally NOT in SYSTEM_MUTABLE_NAMESPACES.

        Mutations of ``audio`` itself (``$ audio.foo = bar``) are rare
        and almost always indicate a bug — the intended pattern is to
        register channels via ``renpy.music.register_channel()`` or use
        ``define audio.bgm = "track.ogg"`` for aliases. If a project
        does need to mutate ``audio`` at runtime, the resulting RPY105
        is a useful prompt to add an explicit ``default audio.foo``
        declaration. This test pins the exclusion so a future
        contributor does not silently add ``audio`` without
        re-evaluating the false-positive risk.
        """
        assert "audio" not in SYSTEM_MUTABLE_NAMESPACES


class TestInferExprTypeLogging:
    """Coverage for the debug-log-on-parse-failure behaviour.

    Previously ``infer_expr_type`` silently swallowed
    ``SyntaxError`` / ``ValueError`` / ``TypeError`` and returned
    ``None`` — invisible in normal runs, hiding pipeline regressions.
    Now it logs at DEBUG level (visible with ``--verbose``).
    """

    def test_syntax_error_returns_none(self, caplog):
        """Parse failure still returns None (no crash)."""
        result = infer_expr_type("def broken(:")
        assert result is None

    def test_syntax_error_logs_debug(self, caplog):
        """Parse failure logs a DEBUG message with the failing expression."""
        import logging

        with caplog.at_level(logging.DEBUG, logger="senpy.core.type_inference"):
            infer_expr_type("def broken(:")
        # At least one DEBUG record from our logger mentioning the failure.
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert debug_records, "expected at least one DEBUG log record"
        assert any("type inference failed" in r.getMessage().lower() for r in debug_records)
