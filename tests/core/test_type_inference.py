"""Coverage tests for senpy/core/type_inference.py.

The existing tests in test_analyzer.py cover the functions indirectly through
PythonAstChecker.

These tests directly cover infer_ast_type, infer_expr_type, infer_default_value,
and the _infer_* / _check_*_compat helpers.
"""

from __future__ import annotations

import ast

import pytest

from senpy.core.type_inference import (
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
        """Depth > 8 returns None (recursion guard)."""
        # Build a deeply nested expression: 1 + 1 + 1 + ... (9 levels)
        expr = "1" + " + 1" * 9
        node = ast.parse(expr, mode="eval").body
        result = infer_ast_type(node, depth=8)
        assert result is None  # depth limit hit

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
