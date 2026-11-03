#!/usr/bin/env python3
"""check_cycles.py — static detector of circular imports in senpy/.

Phase 1.7 (0.5.3): final verification that all 5 cycles from the
v0.5.1 audit are broken, and that no new cycles appear.

Algorithm:
    1. Parse every .py file in senpy/ (excluding vendor/) via ast.
    2. Build an import graph: edge A -> B if A imports B (via
       `from senpy.B import ...` or `import senpy.B`).
    3. Find cycles via DFS with white/gray/black coloring.
    4. If a cycle is found, print it and exit with code 1.

Usage:
    python scripts/check_cycles.py            # check, exit 0/1
    python scripts/check_cycles.py --verbose  # print the full graph

CI integration:
    Add a step to .github/workflows/ci.yml:
        - name: Check for circular imports
          run: python scripts/check_cycles.py

False positives:
    The script is aware that `if TYPE_CHECKING:` blocks do NOT create
    runtime cycles (they are type hints only, not executed at import
    time). Such blocks are ignored when building the graph.

    For example, this is NOT a cycle:
        # cache.py
        if TYPE_CHECKING:
            from senpy.analyzer import SenpyAnalyzer  # type hint only

    But this IS a cycle:
        # cache.py
        from senpy.analyzer import SenpyAnalyzer  # runtime import — cycle!

History:
    The v0.5.1 audit (2026-10-28) found 5 cycles through analyzer.py:
        analyzer <-> cli
        analyzer <-> checkers
        analyzer <-> python_ast
        analyzer <-> flow
        analyzer <-> cache
    All broken in Phases 1.2-1.6 (0.5.3). This script is a safety net
    to make sure they don't come back.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections import defaultdict
from pathlib import Path

# =============================================================================
# 1. Parsing: extract imports from a .py file
# =============================================================================


class ImportVisitor(ast.NodeVisitor):
    """Collect all `from senpy.X import Y` and `import senpy.X` from a module.

    Ignores imports inside `if TYPE_CHECKING:` blocks — they don't
    create runtime cycles (type hints only).
    """

    def __init__(self, current_module: str):
        self.current_module = current_module
        self.imports: set[str] = set()
        self._in_type_checking = False  # TYPE_CHECKING nesting depth

    def _is_type_checking_test(self, test: ast.AST) -> bool:
        """Check whether the condition is `if TYPE_CHECKING`."""
        # if TYPE_CHECKING:
        if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
            return True
        # if typing.TYPE_CHECKING:
        return bool(isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")

    def visit_If(self, node: ast.If) -> None:
        """Intercept `if TYPE_CHECKING:` — ignore its body."""
        if self._is_type_checking_test(node.test):
            # Don't descend into the body — it only contains type hints.
            return
        # Regular `if` — descend into both branches.
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """from senpy.X import Y -> edge: current -> senpy.X

        We use the FULL module name (senpy.cli, not cli) so that graph
        keys match the module names produced by extract_imports.
        """
        if node.module and node.module.startswith("senpy."):
            target = node.module  # full name: senpy.cli, senpy.formatter.core, ...
            if target != self.current_module:
                self.imports.add(target)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        """import senpy.X -> edge: current -> senpy.X"""
        for alias in node.names:
            if alias.name.startswith("senpy."):
                target = alias.name  # full name
                if target != self.current_module:
                    self.imports.add(target)
        self.generic_visit(node)


def extract_imports(file_path: Path, package_root: Path) -> tuple[str, set[str]]:
    """Parse a .py file, return (module_name, set_of_imports).

    Args:
        file_path: Path to the .py file.
        package_root: Package root (where __init__.py lives).

    Returns:
        Tuple (module_name, {imported_module_names}).
    """
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        print(f"  Warning: SyntaxError in {file_path}: {e}", file=sys.stderr)
        return "", set()

    # Module name: senpy/foo/bar.py -> senpy.foo.bar
    rel = file_path.relative_to(package_root.parent)
    module_name = str(rel).replace("/", ".").replace("\\", ".").removesuffix(".py")
    # __init__.py -> package name
    if module_name.endswith(".__init__"):
        module_name = module_name[:-9]

    # For subpackages (senpy.formatter.rules) we could take only the
    # top-level (senpy.formatter) — but we keep the full name for a
    # precise graph.

    visitor = ImportVisitor(module_name)
    visitor.visit(tree)

    # We could normalize imports to the top-level package
    # (senpy.formatter.rules -> senpy.formatter) — but we keep full
    # names for precise analysis. current_module must also be full.
    return module_name, visitor.imports


# =============================================================================
# 2. Build the graph and find cycles
# =============================================================================


def build_import_graph(package_root: Path) -> dict[str, set[str]]:
    """Build the import graph: {module: {imported_modules}}."""
    graph: dict[str, set[str]] = defaultdict(set)

    # All .py files in the package (excluding __pycache__, vendor)
    py_files = sorted(
        f
        for f in package_root.rglob("*.py")
        if "__pycache__" not in str(f)
        and "vendor" not in str(f.relative_to(package_root))
        and ".ruff_cache" not in str(f)
    )

    for py_file in py_files:
        module_name, imports = extract_imports(py_file, package_root)
        if module_name:
            graph[module_name].update(imports)

    return dict(graph)


def find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Find all cycles in the graph via DFS with white/gray/black coloring.

    Returns:
        List of cycles, each cycle is a list of module names.
        Example: [['senpy.analyzer', 'senpy.cli', 'senpy.analyzer']]
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = defaultdict(lambda: WHITE)
    cycles: list[list[str]] = []
    path: list[str] = []

    def dfs(node: str) -> None:
        color[node] = GRAY
        path.append(node)

        for neighbor in graph.get(node, set()):
            if color[neighbor] == GRAY:
                # Found a cycle — extract it from the path.
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                cycles.append(cycle)
            elif color[neighbor] == WHITE:
                dfs(neighbor)

        path.pop()
        color[node] = BLACK

    # Run DFS from every node (the graph may be disconnected).
    for node in graph:
        if color[node] == WHITE:
            dfs(node)

    return cycles


# =============================================================================
# 3. Cycle filtering and deduplication
# =============================================================================


def normalize_cycle(cycle: list[str]) -> tuple[str, ...]:
    """Normalize a cycle for deduplication: start from the smallest element.

    Example: [B, C, A, B] and [C, A, B, C] both become (A, B, C).
    """
    # Drop the last element (it equals the first — this closes the cycle).
    core = cycle[:-1]
    if not core:
        return tuple(cycle)
    # Find the index of the smallest element.
    min_idx = core.index(min(core))
    # Rotate so that the smallest element is first.
    rotated = core[min_idx:] + core[:min_idx]
    return tuple(rotated)


def deduplicate_cycles(cycles: list[list[str]]) -> list[list[str]]:
    """Remove duplicate cycles (the same cycle can be found from different starts)."""
    seen: set[tuple[str, ...]] = set()
    unique: list[list[str]] = []
    for cycle in cycles:
        norm = normalize_cycle(cycle)
        if norm not in seen:
            seen.add(norm)
            unique.append(list(norm) + [norm[0]])  # close the cycle
    return unique


# =============================================================================
# 4. Main function
# =============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(description="Static detector of circular imports in senpy/.")
    parser.add_argument(
        "--package",
        default="senpy",
        help="Package name to check (default: senpy)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print the full import graph",
    )
    args = parser.parse_args()

    # Find the package root.
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    package_root = project_root / args.package

    if not package_root.is_dir():
        print(f"Error: package '{args.package}' not found at {package_root}", file=sys.stderr)
        return 2

    print(f"Analyzing {package_root}...")
    graph = build_import_graph(package_root)

    if args.verbose:
        print("\n=== Import graph ===")
        for module in sorted(graph):
            imports = sorted(graph[module])
            if imports:
                print(f"  {module} -> {', '.join(imports)}")
            else:
                print(f"  {module} (no imports)")
        print()

    cycles = find_cycles(graph)
    unique_cycles = deduplicate_cycles(cycles)

    if not unique_cycles:
        print(f"[OK] No circular imports found in '{args.package}'/")
        print(f"  Analyzed {len(graph)} modules.")
        return 0

    print(f"\n[FAIL] Found {len(unique_cycles)} circular import(s):\n", file=sys.stderr)
    for cycle in unique_cycles:
        print(f"  {' -> '.join(cycle)}", file=sys.stderr)
    print(file=sys.stderr)
    print("Circular imports can cause:", file=sys.stderr)
    print("  - ImportError on module loading", file=sys.stderr)
    print("  - Partial module initialization", file=sys.stderr)
    print("  - Unpredictable behavior depending on import order", file=sys.stderr)
    print(file=sys.stderr)
    print("To fix:", file=sys.stderr)
    print("  1. Move shared code to a third module (both depend on it)", file=sys.stderr)
    print("  2. Use Protocol instead of concrete class for type hints", file=sys.stderr)
    print("  3. Use lazy imports inside functions (last resort)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
