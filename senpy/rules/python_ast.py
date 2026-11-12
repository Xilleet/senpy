from __future__ import annotations

import ast
import difflib
from typing import TYPE_CHECKING

from senpy.core.constants import BUILTIN_SYMBOLS, SCREEN_LOCAL_IGNORE
from senpy.core.logging import get_logger
from senpy.core.models import Diagnostic
from senpy.core.type_inference import (
    KNOWN_TYPE_METHODS,
    METHOD_SUGGESTIONS,
    MUTATING_METHODS,
    SYSTEM_MUTABLE_NAMESPACES,
    _check_binop_incompatible,
    infer_ast_type,
    infer_default_value,
    infer_expr_type,  # noqa: F401
)
from senpy.domain.text_tags import get_utf16_range, suggest_similar_symbol
from senpy.text_utils import dedent_python

if TYPE_CHECKING:
    from senpy.core.protocols import FullAnalyzer

_logger = get_logger("rules.python_ast")


def _get_root_name(node: ast.AST | None) -> str | None:
    """Recursively unwraps subscripts and attributes down to the base variable name (e.g., a[0]['k'] -> a)."""
    curr = node
    while isinstance(curr, (ast.Subscript, ast.Attribute)):
        curr = curr.value
    if isinstance(curr, ast.Name):
        return curr.id
    return None


def _extract_assign_target_name(node: ast.Assign | ast.AugAssign) -> tuple[str, bool]:
    """Extract the target name from an Assign/AugAssign node.

    Returns `(name, is_attr)`:
        - `name` is the variable name (for `Name`) or the dotted attribute
          (e.g. `obj.prop`, for `Attribute`).
        - `is_attr` is True when the target is an attribute access (not a
          plain variable). The caller uses this to skip `style.*` mutations.
    """
    target_node = (
        node.target
        if isinstance(node, ast.AugAssign)
        else (node.targets[0] if node.targets else None)
    )
    if isinstance(target_node, ast.Name):
        return target_node.id, False
    if isinstance(target_node, ast.Attribute):
        return ast.unparse(target_node), True
    return "variable", False


def extract_assigned_names(py_code: str) -> set[str]:
    """Extracts the variable names that are assigned a value in a Python line.

    Handles all Python assignment forms:
      - Plain: ``x = 5``
      - Chained: ``a = b = 5``
      - Tuple unpacking: ``a, b = 1, 2`` (and nested ``a, (b, c) = ...``)
      - List unpacking: ``[a, b] = 1, 2``
      - Starred: ``a, *b = [1, 2, 3]``
      - Walrus: ``(x := 5)`` (and nested ``(x := (y := 5))``)
      - AnnAssign: ``x: int = 5`` (and ``x: int`` without value)
      - AugAssign: ``x += 1`` (and ``-=``, ``*=``, etc.)

    Only top-level assignments are returned — assignments inside
    ``if``/``for``/``while``/``try``/``with``/function bodies are
    conditional (they may not execute) and must NOT be reported as
    guaranteed. The previous implementation used ``ast.walk`` which
    recursed into all nested bodies; this is incorrect for
    guaranteed-assignment tracking because it treated conditional
    assignments as if they were unconditional.

    Walrus inside an ``if`` condition expression (e.g.
    ``if (y := compute()):``) IS returned — the walrus evaluates when
    the ``if`` statement evaluates, which is unconditional at the top
    level.
    """
    assigned: set[str] = set()
    try:
        tree = ast.parse(py_code)
        # Iterate top-level statements only. ``ast.walk`` would recurse
        # into If/For/While/Try/With/FunctionDef/ClassDef bodies and
        # collect conditional assignments as if they were guaranteed.
        # This matches the contract of ``clear_safe_cfg_vars`` which
        # already iterates ``tree.body`` for the same reason.
        for node in tree.body:
            # Plain and chained assignment: a = b = 5
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    _collect_target_names(target, assigned)
                # Walrus inside the RHS value: `result = (x := 5) + 10`.
                # The walrus evaluates when the RHS evaluates, which is
                # unconditional at the top level — so `x` IS guaranteed.
                for child in ast.walk(node.value):
                    if isinstance(child, ast.NamedExpr):
                        _collect_target_names(child.target, assigned)
            # Annotated, augmented, and walrus: all have a single .target
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
                _collect_target_names(node.target, assigned)
                # For AnnAssign/AugAssign, the value may also contain walrus.
                value = getattr(node, "value", None)
                if value is not None:
                    for child in ast.walk(value):
                        if isinstance(child, ast.NamedExpr):
                            _collect_target_names(child.target, assigned)
            elif isinstance(node, ast.Expr):
                # Walrus inside an expression statement: `(x := 5)` or
                # `if (y := compute()):` (the latter as a standalone
                # expression). Walk only the expression node (not into
                # nested If/For bodies) to find NamedExpr.
                for child in ast.walk(node):
                    if isinstance(child, ast.NamedExpr):
                        _collect_target_names(child.target, assigned)
            elif isinstance(node, ast.If):
                # The `if` statement itself runs unconditionally. The
                # walrus inside its CONDITION expression evaluates when
                # the condition evaluates — that's guaranteed. Walk
                # only the test (condition), not the body/orelse.
                for child in ast.walk(node.test):
                    if isinstance(child, ast.NamedExpr):
                        _collect_target_names(child.target, assigned)
                # Bodies (node.body, node.orelse) are conditional — skip.
            elif isinstance(node, (ast.While,)):
                # Same as If: walrus in the condition is guaranteed;
                # body/orelse are conditional.
                for child in ast.walk(node.test):
                    if isinstance(child, ast.NamedExpr):
                        _collect_target_names(child.target, assigned)
            elif isinstance(node, ast.For):
                # Loop target binding is top-level (the loop variable
                # is assigned when the for-statement evaluates, even
                # if the iterable is empty the binding still happens
                # via StopIteration cleanup — but in practice an
                # empty iterable means the loop body never runs, so
                # the loop variable may be unbound. We treat the
                # loop target as guaranteed (matches Ren'Py's typical
                # `$ for i in [1,2,3]:` usage where the iterable is
                # known at lint time) but skip the body assignments.
                _collect_target_names(node.target, assigned)
                # Body and orelse are conditional — skip.
            # With/Try/FunctionDef/ClassDef: their bodies are
            # conditional (with-exit may not run cleanup, try may
            # not reach the body, function may not be called). Skip
            # entirely.
    except SyntaxError as e:
        _logger.debug("extract_assigned_names: ast.parse failed: %s", e)
    return assigned


def _collect_target_names(target: ast.expr, names: set[str]) -> None:
    """Recursively extract variable names from an assignment target.

    Handles:
      - ``ast.Name``: ``x`` → add ``x``.
      - ``ast.Tuple`` / ``ast.List``: ``a, b`` → add each element.
      - ``ast.Starred``: ``*b`` → add ``b`` (the inner name).
      - Other (``ast.Attribute``, ``ast.Subscript``): ignored (not a
        simple variable name).
    """
    if isinstance(target, ast.Name):
        names.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            _collect_target_names(elt, names)
    elif isinstance(target, ast.Starred):
        _collect_target_names(target.value, names)
    # ast.Attribute, ast.Subscript, etc. — not a simple variable name.


def _collect_target_names_into_dict(target: ast.expr, d: dict) -> None:
    """Recursively extract variable names from an assignment target and
    remove them from ``d`` (a dict, typically ``branch_uninitialized``).

    Same recursion as ``_collect_target_names``, but pops from a dict
    instead of adding to a set.
    """
    if isinstance(target, ast.Name):
        d.pop(target.id, None)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            _collect_target_names_into_dict(elt, d)
    elif isinstance(target, ast.Starred):
        _collect_target_names_into_dict(target.value, d)


class PythonAstChecker:
    """Checks embedded Python code via AST for compliance with Ren'Py rules.

    TODO (post-1.0 architecture redesign): this class is 1540 lines / 41
    methods implementing 8 rule groups (RPY102/105/106/108/110/201/208/
    403/103/202). extracted type inference functions to
    ``senpy/core/type_inference.py`` (454 lines), but the class itself
    was NOT split via mixins because:

      1. 47 cross-method calls — methods constantly call each other
         (``_walk_python_nodes`` → ``_visit_augassign`` →
         ``_check_augassign_name`` → ``_check_augassign_type_conflict``).
         This is one cohesive AST visitor, not 5 independent modules.
      2. Mixin pattern in Python shares ``self`` — mypy cannot verify
         cross-mixin method calls, and import-chain fragility multiplies
         (one missing re-export broke CI in Phase 4.3).
      3. Only 7 of 41 methods are external entry points; the other 34
         are internal implementation details.

    The practical floor without a fundamental redesign is ~1580 lines
    (after extracting the 5 module-level assignment helpers). Further
    reduction requires a **rule-as-plugin architecture**: each rule
    (RPY102, RPY105, etc.) becomes a separate class with a registration
    pattern, sharing a common ``ASTVisitor`` base. This is post-1.0
    work — not a Phase 4 file split, but an architectural change that
    affects how rules are registered, discovered, and tested.

    For now, this file is accepted as oversized but stable. The 8 rule
    groups are documented inline via section comments for navigability.
    """

    def __init__(self, analyzer: FullAnalyzer):
        self.analyzer = analyzer

    def collect_from_python_block(self, code_lines: list[str]) -> tuple[dict[str, int], set[str]]:
        """Collects functions, classes, and variables from init python blocks along with line numbers.

        Only top-level declarations are returned — assignments inside
        ``if``/``for``/``while``/``try``/``with`` bodies are conditional
        (they may not execute) and must NOT be registered as top-level
        symbols. The previous implementation used ``ast.walk`` which
        recursed into all nested bodies; this is incorrect because it
        registered conditional assignments as if they were top-level
        declarations, polluting ``user_symbols`` and ``missing_defaults``
        with variables that may never exist at runtime.
        """
        names: dict[str, int] = {}
        refs: set[str] = set()
        code = dedent_python("".join(code_lines))
        try:
            tree = ast.parse(code)
            # Iterate top-level statements only. ``ast.walk`` would recurse
            # into If/For/While/Try/With/FunctionDef/ClassDef bodies and
            # register conditional assignments as top-level declarations.
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names[node.name] = getattr(node, "lineno", 1)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            names[target.id] = getattr(node, "lineno", 1)
                elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                    if isinstance(node.target, ast.Name):
                        names[node.target.id] = getattr(node, "lineno", 1)
                elif (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value.isidentifier()
                ):
                    refs.add(node.value)
                # If/For/While/Try/With bodies are conditional — skip.
                # Their inner assignments are not top-level declarations.
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
        init_priority: int = 0,
    ) -> None:
        """RPY109: Checks function calls in init python for alphabetical file order.

        ``init_priority`` is the Ren'Py init priority of the current block
        (default 0). Ren'Py runs init blocks in priority order — lower
        number first; same priority falls back to alphabetical filename
        order. RPY109 uses this to avoid firing when the current block
        runs AFTER the defining block (higher priority number) even if
        the current file is alphabetically before the defining file.

        We do not track per-variable init priorities — a variable defined
        in another file could be at any priority. Conservative heuristic:
        - If ``init_priority > 0``: the current block runs after the
          default ``init python:`` (priority 0). Assume any variable
          from another file was defined at priority 0 — no violation.
          (May miss real violations where both blocks have positive
          priorities in wrong order; users can ``# noqa`` if hit.)
        - If ``init_priority <= 0``: apply the existing alphabetical
          check (it correctly catches same-priority violations, and
          is conservative for the negative-priority case where the
          current block runs before any default-priority block).
        """
        if init_priority > 0:
            # Current block runs after default-priority init blocks —
            # references to variables defined elsewhere are safe.
            return

        try:
            tree = ast.parse(py_code)
        except SyntaxError as e:
            _logger.debug("check_init_dependency: ast.parse failed: %s", e)
            return

        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # For functions only decorators are evaluated immediately at startup
                for dec in stmt.decorator_list:
                    self._check_init_node_order(dec, file_path, start_line, lines, noqa_map)
            elif isinstance(stmt, ast.ClassDef):
                # For classes, decorators and base classes are evaluated
                for dec in stmt.decorator_list:
                    self._check_init_node_order(dec, file_path, start_line, lines, noqa_map)
                for base in stmt.bases:
                    self._check_init_node_order(base, file_path, start_line, lines, noqa_map)
            else:
                # Other statements (calls, assignments) execute immediately
                self._check_init_node_order(stmt, file_path, start_line, lines, noqa_map)

    def _check_init_node_order(
        self,
        root_node: ast.AST,
        file_path: str,
        start_line: int,
        lines: list[str] | None,
        noqa_map: dict,
    ) -> None:
        """Walk one init-phase node and emit RPY109 for any name loaded before its file's turn in alphabetical order."""
        import os

        for child in ast.walk(root_node):
            # Ignore bodies of functions and classes (they execute lazily)
            if (
                isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and child is not root_node
            ):
                continue

            if not (isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)):
                continue

            name = child.id
            if name in BUILTIN_SYMBOLS:
                continue
            if name not in self.analyzer.variables:
                continue

            def_file = self.analyzer.variables[name].file_path
            if def_file == file_path:
                continue

            curr_rel = (
                os.path.relpath(file_path, self.analyzer.project_path).replace("\\", "/").lower()
            )
            def_rel = (
                os.path.relpath(def_file, self.analyzer.project_path).replace("\\", "/").lower()
            )

            # If the current file loads earlier than the file with the definition
            if curr_rel < def_rel:
                self._emit_rpy109(
                    name=name,
                    child=child,
                    file_path=file_path,
                    def_file=def_file,
                    start_line=start_line,
                    lines=lines,
                    noqa_map=noqa_map,
                )

    def _emit_rpy109(
        self,
        *,
        name: str,
        child: ast.AST,
        file_path: str,
        def_file: str,
        start_line: int,
        lines: list[str] | None,
        noqa_map: dict,
    ) -> None:
        """Build and submit the RPY109 diagnostic for an init-order violation."""
        import os

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
        """RPY201, RPY205, RPY208: Check imperative loops and mutations inside a screen."""
        try:
            tree = ast.parse(py_code)
        except SyntaxError as e:
            _logger.debug("check_screen_mutation: ast.parse failed: %s", e)
            return

        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.While)):
                self._check_loop_in_screen(
                    node=node,
                    file_path=file_path,
                    line_idx=line_idx,
                    screen_name=screen_name,
                    lines=lines,
                    noqa_map=noqa_map,
                )
                return  # only one diagnostic per walk (matches original behavior)

            if isinstance(node, (ast.Assign, ast.AugAssign)):
                self._check_mutation_in_screen(
                    node=node,
                    file_path=file_path,
                    line_idx=line_idx,
                    screen_name=screen_name,
                    screen_local_symbols=screen_local_symbols,
                    line_content=line_content,
                    lines=lines,
                    noqa_map=noqa_map,
                )
                return

    def _check_loop_in_screen(
        self,
        *,
        node: ast.For | ast.While,
        file_path: str,
        line_idx: int,
        screen_name: str,
        lines: list[str] | None,
        noqa_map: dict,
    ) -> None:
        """RPY205: Imperative for/while loop inside a screen definition.

        Python loops inside screens hurt UI prediction performance.
        Ren'Py screen language should use declarative `for` instead.
        """
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

    def _check_mutation_in_screen(
        self,
        *,
        node: ast.Assign | ast.AugAssign,
        file_path: str,
        line_idx: int,
        screen_name: str,
        screen_local_symbols: set[str],
        line_content: str,
        lines: list[str] | None,
        noqa_map: dict,
    ) -> None:
        """RPY208 (screen-local var mutation) and RPY201 (global state mutation)."""
        target_name, is_attr = _extract_assign_target_name(node)
        if is_attr and target_name.startswith("style."):
            return
        if target_name in SCREEN_LOCAL_IGNORE:
            return

        raw_l = lines[line_idx - 1] if lines and 0 <= line_idx - 1 < len(lines) else line_content
        start_c, end_c = get_utf16_range(raw_l, target_name)

        if target_name in screen_local_symbols:
            self._emit_rpy208(
                target_name=target_name,
                screen_name=screen_name,
                file_path=file_path,
                line_idx=line_idx,
                raw_l=raw_l,
                start_c=start_c,
                end_c=end_c,
                noqa_map=noqa_map,
            )
            return

        self._emit_rpy201(
            target_name=target_name,
            screen_name=screen_name,
            file_path=file_path,
            line_idx=line_idx,
            raw_l=raw_l,
            start_c=start_c,
            end_c=end_c,
            noqa_map=noqa_map,
        )

    def _emit_rpy208(
        self,
        *,
        target_name: str,
        screen_name: str,
        file_path: str,
        line_idx: int,
        raw_l: str,
        start_c: int,
        end_c: int,
        noqa_map: dict,
    ) -> None:
        """RPY208: Direct mutation of screen-local variable via Python ($ var = ...)."""
        self.analyzer._add_diagnostic(
            Diagnostic(
                file_path=file_path,
                line_number=line_idx,
                line_content=raw_l.strip(),
                code="RPY208",
                message=(
                    f"Direct state mutation of screen-local variable '{target_name}' "
                    f"inside screen '{screen_name}'. "
                    "Python statements in screens execute in the global store and "
                    "cannot modify screen-local variables! "
                    f"Use screen action SetScreenVariable('{target_name}', ...) instead."
                ),
                severity="ERROR",
                col=start_c,
                end_col=end_c,
            ),
            noqa_map,
        )

    def _emit_rpy201(
        self,
        *,
        target_name: str,
        screen_name: str,
        file_path: str,
        line_idx: int,
        raw_l: str,
        start_c: int,
        end_c: int,
        noqa_map: dict,
    ) -> None:
        """RPY201: Direct mutation of global state inside screen."""
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

    def check_python_ast(
        self,
        py_code: str,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None = None,
    ) -> None:
        """Parses Python code and runs a recursive AST traversal."""
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

            # RPY108 (improvement 0.7.6): Check for incompatible BinOp
            # in the entire tree. This catches `$ result = "text" + 5`
            # or `$ x = [1,2] - 3` where the type conflict is inside an
            # expression, not at the assignment level.
            for node in ast.walk(tree):
                if isinstance(node, ast.BinOp):
                    result = _check_binop_incompatible(node, self.analyzer.variables)
                    if result is not None:
                        lt, rt, op_name = result
                        real_line = start_line + getattr(node, "lineno", 1) - 1
                        raw_l = (
                            lines[real_line - 1]
                            if lines and 0 <= real_line - 1 < len(lines)
                            else ""
                        )
                        self.analyzer._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=real_line,
                                line_content=raw_l.strip(),
                                code="RPY108",
                                message=(
                                    f"Incompatible binary operation: '{lt}' {op_name} '{rt}'. "
                                    f"This will raise TypeError at runtime."
                                ),
                                severity="ERROR",
                            ),
                            noqa_map,
                        )

        except SyntaxError as e:
            _logger.debug("check_python_ast: ast.parse failed: %s", e)
            # Emit RPY110: report Python syntax errors in $-statements and
            # init python blocks instead of silently swallowing them.
            # Ren'Py would crash with a traceback at this line — Senpy
            # should catch it before runtime.
            error_line = start_line + (e.lineno - 1) if e.lineno else start_line
            error_col = e.offset or 0
            line_content = ""
            if lines and error_line >= 1 and error_line <= len(lines):
                line_content = lines[error_line - 1].rstrip("\r\n")
            self.analyzer._add_diagnostic(
                Diagnostic(
                    file_path=file_path,
                    line_number=error_line,
                    line_content=line_content,
                    code="RPY110",
                    message=f"Python syntax error: {e.msg}",
                    severity="ERROR",
                    col=error_col,
                ),
                noqa_map,
            )

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
            self._check_augassign_name(node, file_path, start_line, noqa_map, lines, local_scope)
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
        raw_l = lines[real_line - 1] if lines and 0 <= real_line - 1 < len(lines) else ""
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
            expected_t == "str"
            and op_t != "str"
            or expected_t in ("int", "float")
            and op_t not in ("int", "float")
            or expected_t == "list"
            and op_t not in ("list",)
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
        if not root_name or root_name in local_scope or root_name in SYSTEM_MUTABLE_NAMESPACES:
            return

        real_line = start_line + getattr(node, "lineno", 1) - 1
        raw_l = lines[real_line - 1] if lines and 0 <= real_line - 1 < len(lines) else ""
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
                # Record the assignment in the current branch's scope so
                # subsequent statements in the SAME body see the variable
                # (intra-branch sequencing). Without this, a pattern like
                #   if cond:
                #       args = []
                #       args.extend(...)
                # would fire RPY102 on the .extend() call because `args`
                # was treated as undeclared. The scope copy made in
                # _visit_if_while / _visit_for / _visit_try ensures this
                # does not leak to the parent scope.
                local_scope.add(target.id)
            elif isinstance(target, ast.Subscript):
                self._check_assign_subscript_target(
                    target, file_path, real_line, raw_l, noqa_map, local_scope
                )
            elif isinstance(target, (ast.Tuple, ast.List)):
                self._check_assign_tuple_target(
                    target, node.value, file_path, real_line, raw_l, noqa_map, local_scope
                )
                # Tuple/list unpacking also introduces new names into
                # the current branch's scope (e.g. `a, b = 1, 2`).
                _collect_target_names(target, local_scope)

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
        self,
        target: ast.Name,
        value_node: ast.AST,
        file_path: str,
        real_line: int,
        raw_l: str,
        noqa_map: dict,
        local_scope: set[str],
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
        self,
        target: ast.Subscript,
        file_path: str,
        real_line: int,
        raw_l: str,
        noqa_map: dict,
        local_scope: set[str],
    ) -> None:
        """RPY105/RPY102: Check subscript assignment ($ CONST["key"] = "value")."""
        root_name = _get_root_name(target.value)
        if not root_name or root_name in local_scope or root_name in SYSTEM_MUTABLE_NAMESPACES:
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
        self,
        target: ast.Tuple | ast.List,
        value_node: ast.AST,
        file_path: str,
        real_line: int,
        raw_l: str,
        noqa_map: dict,
        local_scope: set[str],
    ) -> None:
        """RPY104: Check tuple/list unpacking assignment ($ a, b = 1, 2)."""
        for elt in target.elts:
            if isinstance(elt, ast.Name) and elt.id not in local_scope:
                self._verify_assign_target(
                    elt.id,
                    file_path,
                    real_line,
                    noqa_map,
                    raw_line=raw_l,
                    val_node=value_node,
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

        Runs for non-function, non-control-flow nodes (Import, Assign,
        Expr, etc.). Control-flow nodes (If/While/For/Try) are skipped
        here — their bodies are visited separately by ``_visit_if_while``
        / ``_visit_for`` / ``_visit_try``, which create the correct
        branch-local scope before recursing. Walking a control-flow node
        here would check Call nodes inside its body against the OUTER
        scope, missing variables assigned earlier in the same branch
        (false RPY102 on patterns like::

            if cond:
                args = []
                args.extend(...)   # walker saw this with outer scope → false positive

        ). The dispatcher in ``_walk_python_nodes`` calls this on every
        node, then recurses into control-flow bodies separately — so
        skipping control-flow nodes here avoids both double-checking
        and the scope-mismatch false positive.
        """
        if isinstance(node, (ast.If, ast.While, ast.For, ast.Try)):
            return
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                self._check_mutating_method_call(
                    sub, file_path, start_line, noqa_map, lines, local_scope
                )
                self._check_invalid_method_call(
                    sub, file_path, start_line, noqa_map, lines, local_scope
                )

    def _check_mutating_method_call(
        self,
        sub: ast.Call,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None,
        local_scope: set[str],
    ) -> None:
        """RPY105/RPY102: Check mutating methods (.append, .update, etc.) on
        constants and undeclared variables."""
        method_name = sub.func.attr
        if method_name not in MUTATING_METHODS:
            return

        root_name = _get_root_name(sub.func.value)
        if not root_name or root_name in local_scope or root_name in SYSTEM_MUTABLE_NAMESPACES:
            return

        real_line = start_line + getattr(sub, "lineno", 1) - 1
        raw_l = lines[real_line - 1] if lines and 0 <= real_line - 1 < len(lines) else ""
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
        self,
        sub: ast.Call,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None,
        local_scope: set[str],
    ) -> None:
        """RPY108: Check for invalid method calls on known built-in types
        (list.add → .append, dict.append, str.pop, etc.)."""
        method_name = sub.func.attr
        if not isinstance(sub.func.value, ast.Name) or method_name.startswith("_"):
            return

        var_id = sub.func.value.id
        var_sym = self.analyzer.variables.get(var_id)
        if not var_sym or var_sym.type_name not in KNOWN_TYPE_METHODS or var_id in local_scope:
            return

        t_name = var_sym.type_name
        valid_methods = KNOWN_TYPE_METHODS[t_name]
        if method_name in valid_methods:
            return

        real_line = start_line + getattr(sub, "lineno", 1) - 1
        raw_l = lines[real_line - 1] if lines and 0 <= real_line - 1 < len(lines) else ""
        target_str = f"{var_id}.{method_name}"
        sub_str = target_str if target_str in raw_l else method_name
        start_c, end_c = get_utf16_range(raw_l, sub_str)

        if (t_name, method_name) in METHOD_SUGGESTIONS:
            hint = f" (did you mean '{METHOD_SUGGESTIONS[(t_name, method_name)]}' ?)"
        else:
            matches = difflib.get_close_matches(method_name, list(valid_methods), n=1, cutoff=0.6)
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
        """Recursive traversal of body and orelse for if/while.

        Each branch gets its own copy of ``local_scope`` so that
        variables assigned inside the body are visible to subsequent
        statements in the SAME body (intra-branch sequencing) but do
        not leak to the parent scope (correct conditional scoping).
        Without this copy, an assignment like ``args = []`` inside an
        ``if`` body would either be invisible to a later ``args.extend()``
        in the same body (false RPY102) — if we never added it — or
        leak outside the if (incorrect scoping) — if we added it to the
        parent's local_scope. The copy gives us the right semantics.
        """
        body_scope = set(local_scope)
        self._walk_python_nodes(node.body, file_path, start_line, noqa_map, lines, body_scope)
        orelse_scope = set(local_scope)
        self._walk_python_nodes(node.orelse, file_path, start_line, noqa_map, lines, orelse_scope)

    def _visit_for(
        self,
        node: ast.For,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None,
        local_scope: set[str],
    ) -> None:
        """Recursive traversal of body and orelse for for, with the loop variable in scope."""
        loop_scope = set(local_scope)
        if isinstance(node.target, ast.Name):
            loop_scope.add(node.target.id)
        elif isinstance(node.target, (ast.Tuple, ast.List)):
            for elt in node.target.elts:
                if isinstance(elt, ast.Name):
                    loop_scope.add(elt.id)
        self._walk_python_nodes(node.body, file_path, start_line, noqa_map, lines, loop_scope)
        self._walk_python_nodes(node.orelse, file_path, start_line, noqa_map, lines, loop_scope)

    def _visit_try(
        self,
        node: ast.Try,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None,
        local_scope: set[str],
    ) -> None:
        """Recursive traversal of body, orelse, finalbody, and handlers for try."""
        self._walk_python_nodes(node.body, file_path, start_line, noqa_map, lines, local_scope)
        self._walk_python_nodes(node.orelse, file_path, start_line, noqa_map, lines, local_scope)
        self._walk_python_nodes(node.finalbody, file_path, start_line, noqa_map, lines, local_scope)
        for handler in node.handlers:
            h_scope = set(local_scope)
            if handler.name:
                h_scope.add(handler.name)
            self._walk_python_nodes(handler.body, file_path, start_line, noqa_map, lines, h_scope)

    def _walk_python_nodes(
        self,
        nodes: list[ast.stmt],
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None,
        local_scope: set[str],
    ) -> None:
        """Dispatcher: processes top-level statements via _visit_* methods.

        Phase 3 Step 4 (0.5.6): split from 479 lines into 8 methods + dispatcher.
        Each _visit_* method handles one type of AST node.
        """
        for node in nodes:
            # Ignore nested functions and classes, they create their own local scope
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

            # 4. Mutating methods — run for ALL non-function nodes.
            # (FunctionDef/ClassDef already filtered by `continue` above.)
            self._visit_mutating_methods(node, file_path, start_line, noqa_map, lines, local_scope)

            # 5. Recurse into control flow bodies.
            # Previously dead code: the original if/elif chain had
            # `if not isinstance(FunctionDef)` which was always True,
            # making the elif branches unreachable. Fixed: separate if.
            if isinstance(node, (ast.If, ast.While)):
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
        """RPY403, RPY202, RPY103: Checks if/elif conditions via AST.

        Thin dispatcher: delegates to 2 helpers.
        """
        try:
            cond_tree = ast.parse(expr, mode="eval")
            self._check_rpy403_condition(
                cond_tree, expr, file_path, line_idx, line_content, noqa_map
            )
            self._check_undeclared_vars_in_condition(
                cond_tree,
                file_path,
                line_idx,
                line_content,
                screen_name,
                screen_local_symbols,
                noqa_map,
            )
        except SyntaxError as e:
            _logger.debug("check_condition: ast.parse failed: %s", e)

    def _check_rpy403_condition(
        self,
        cond_tree: ast.Expression,
        expr: str,
        file_path: str,
        line_idx: int,
        line_content: str,
        noqa_map: dict,
    ) -> None:
        """RPY403: Always-false, always-true, contradiction, tautology checks.

        Dispatches to one of four sub-checks based on the AST node type
        of the condition body. Each sub-check emits at most one RPY403
        diagnostic. The dispatcher itself does no diagnostic emission —
        it only routes to the appropriate handler.
        """
        body = cond_tree.body

        if isinstance(body, ast.Constant):
            self._check_rpy403_constant(body, expr, file_path, line_idx, line_content, noqa_map)
        elif isinstance(body, ast.BoolOp):
            self._check_rpy403_boolop(body, expr, file_path, line_idx, line_content, noqa_map)

    def _check_rpy403_constant(
        self,
        body: ast.Constant,
        expr: str,
        file_path: str,
        line_idx: int,
        line_content: str,
        noqa_map: dict,
    ) -> None:
        """RPY403 for Constant conditions: always-False (False/0/""/None)
        and always-True (True/1/"non-empty" — with the bare True/1 skip).
        """
        value = bool(body.value)
        is_none = isinstance(body.value, type(None))

        if not value:
            # Always-False: `if False:`, `if 0:`, `if "":`, `if None:`
            self._emit_rpy403(
                file_path,
                line_idx,
                line_content,
                noqa_map,
                f"Condition '{expr}' is always False. This block will never execute.",
            )
        elif value and not is_none and expr.strip() not in ("True", "1"):
            # Always-True: skip bare `True` and `1` (treated as intentional).
            self._emit_rpy403(
                file_path,
                line_idx,
                line_content,
                noqa_map,
                f"Condition '{expr}' is always True. The condition is redundant — remove it or simplify the logic.",
            )

    def _check_rpy403_boolop(
        self,
        body: ast.BoolOp,
        expr: str,
        file_path: str,
        line_idx: int,
        line_content: str,
        noqa_map: dict,
    ) -> None:
        """RPY403 for BoolOp conditions: contradiction in AND (`x and not x`),
        tautology in OR (`x or not x`).
        """
        if isinstance(body.op, ast.And):
            self._check_rpy403_contradiction(body, file_path, line_idx, line_content, noqa_map)
        elif isinstance(body.op, ast.Or):
            self._check_rpy403_tautology(body, file_path, line_idx, line_content, noqa_map)

    def _check_rpy403_contradiction(
        self,
        body: ast.BoolOp,
        file_path: str,
        line_idx: int,
        line_content: str,
        noqa_map: dict,
    ) -> None:
        """Contradiction in AND: `if x and not x:` (always False).

        Collects plain ``Name`` nodes and ``UnaryOp(Not, Name)`` nodes from
        the AND operands, then finds the intersection — any name that
        appears both directly and negated is a contradiction.
        """
        names, not_names = self._collect_boolop_names(body)
        contradictions = names.intersection(not_names)
        if contradictions:
            var_c = next(iter(contradictions))
            self._emit_rpy403(
                file_path,
                line_idx,
                line_content,
                noqa_map,
                f"Condition contains mutually exclusive contradiction: '{var_c} and not {var_c}'. Always evaluates to False.",
            )

    def _check_rpy403_tautology(
        self,
        body: ast.BoolOp,
        file_path: str,
        line_idx: int,
        line_content: str,
        noqa_map: dict,
    ) -> None:
        """Tautology in OR: `if x or not x:` (always True).

        Same name/negated-name intersection as contradiction, but the
        OR of a variable and its negation is always True.
        """
        names, not_names = self._collect_boolop_names(body)
        tautologies = names.intersection(not_names)
        if tautologies:
            var_t = next(iter(tautologies))
            self._emit_rpy403(
                file_path,
                line_idx,
                line_content,
                noqa_map,
                f"Condition contains tautology: '{var_t} or not {var_t}'. Always evaluates to True.",
            )

    def _collect_boolop_names(self, body: ast.BoolOp) -> tuple[set[str], set[str]]:
        """Extract plain names and negated names from a BoolOp's operands.

        Returns ``(names, not_names)`` where ``names`` is the set of
        ``Name`` ids that appear directly, and ``not_names`` is the set
        of ``Name`` ids that appear as ``UnaryOp(Not, Name)``.
        """
        names = {n.id for n in body.values if isinstance(n, ast.Name)}
        not_names = {
            n.operand.id
            for n in body.values
            if isinstance(n, ast.UnaryOp)
            and isinstance(n.op, ast.Not)
            and isinstance(n.operand, ast.Name)
        }
        return names, not_names

    def _emit_rpy403(
        self,
        file_path: str,
        line_idx: int,
        line_content: str,
        noqa_map: dict,
        message: str,
    ) -> None:
        """Emit a single RPY403 diagnostic. Centralised so all four
        sub-checks share the same Diagnostic construction logic.
        """
        self.analyzer._add_diagnostic(
            Diagnostic(
                file_path=file_path,
                line_number=line_idx,
                line_content=line_content,
                code="RPY403",
                message=message,
            ),
            noqa_map,
        )

    def _check_undeclared_vars_in_condition(
        self,
        cond_tree: ast.Expression,
        file_path: str,
        line_idx: int,
        line_content: str,
        screen_name: str | None,
        screen_local_symbols: set[str],
        noqa_map: dict,
    ) -> None:
        """RPY202/RPY103: Undeclared variables in if/elif conditions.

        Deduplication: if the same variable appears multiple times in the
        same condition (e.g. ``if not fn.endswith(".png") and not
        fn.endswith(".jpg") and not fn.endswith(".webp"):`` references
        ``fn`` three times), only ONE diagnostic is emitted per variable
        per line. Without this, three stacked RPY103 diagnostics appear
        on the same line, all pointing at the first occurrence of ``fn``
        (because ``get_utf16_range`` returns the first match) — visually
        that looks like a single squiggly line on the wrong column, not
        three separate underlines. A ``seen`` set per call enforces the
        deduplication; different undeclared variables on the same line
        still each get their own diagnostic.
        """
        seen: set[str] = set()
        for node in ast.walk(cond_tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                var_name = node.id
                if var_name.startswith("_") or var_name in SCREEN_LOCAL_IGNORE:
                    continue
                if var_name in seen:
                    # Already emitted RPY202/RPY103 for this var on this
                    # line — skip duplicates so we don't get N stacked
                    # diagnostics pointing at the same first-occurrence
                    # column via get_utf16_range.
                    continue
                if (
                    var_name not in self.analyzer.declared_symbols
                    and var_name not in screen_local_symbols
                ):
                    seen.add(var_name)
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
        """RPY404: Checks an if/elif condition for a variable in MAYBE_SET status."""
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
        """Removes variables from uninitialized if they have been assigned a value.

        Handles all Python assignment forms (plain, tuple unpacking,
        walrus, AnnAssign, AugAssign) via ``_collect_target_names``.
        """
        try:
            tree = ast.parse(py_code)
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        _collect_target_names_into_dict(target, branch_uninitialized)
                elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
                    _collect_target_names_into_dict(node.target, branch_uninitialized)
                elif isinstance(node, ast.Expr):
                    # Walrus inside an expression statement: `(x := 5)`.
                    # ast.walk finds all NamedExpr nodes recursively.
                    for child in ast.walk(node):
                        if isinstance(child, ast.NamedExpr):
                            _collect_target_names_into_dict(child.target, branch_uninitialized)

        except SyntaxError as e:
            _logger.debug("clear_safe_cfg_vars: ast.parse failed: %s", e)
