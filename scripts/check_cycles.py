#!/usr/bin/env python3
"""check_cycles.py — статический детектор циклических зависимостей в senpy/.
"""
from __future__ import annotations

import argparse
import ast
import sys
from collections import defaultdict
from pathlib import Path

# =============================================================================
# 1. Парсинг: извлечение импортов из .py файла
# =============================================================================

class ImportVisitor(ast.NodeVisitor):
    """Собирает все `from senpy.X import Y` и `import senpy.X` из модуля.

    Игнорирует импорты внутри `if TYPE_CHECKING:` блоков — они не создают
    runtime циклов (это только type hints).
    """

    def __init__(self, current_module: str):
        self.current_module = current_module
        self.imports: set[str] = set()
        self._in_type_checking = False  # глубина вложенности TYPE_CHECKING

    def _is_type_checking_test(self, test: ast.AST) -> bool:
        """Проверяет, является ли условие if TYPE_CHECKING."""
        if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
            return True
        return bool(isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")

    def visit_If(self, node: ast.If) -> None:
        """Перехватываем if TYPE_CHECKING: — игнорируем его содержимое."""
        if self._is_type_checking_test(node.test):
            return
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """from senpy.X import Y → edge: current → senpy.X

        Используем ПОЛНОЕ имя модуля (senpy.cli, не cli), чтобы ключи в графе
        совпадали с именами модулей из extract_imports.
        """
        if node.module and node.module.startswith("senpy."):
            target = node.module  # полное имя: senpy.cli, senpy.formatter.core, ...
            if target != self.current_module:
                self.imports.add(target)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        """import senpy.X → edge: current → senpy.X"""
        for alias in node.names:
            if alias.name.startswith("senpy."):
                target = alias.name  # полное имя
                if target != self.current_module:
                    self.imports.add(target)
        self.generic_visit(node)


def extract_imports(file_path: Path, package_root: Path) -> tuple[str, set[str]]:
    """Парсит .py файл, возвращает (имя_модуля, set_импортов).

    Args:
        file_path: Путь к .py файлу.
        package_root: Корень пакета (где __init__.py).

    Returns:
        Кортеж (module_name, {imported_module_names}).
    """
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        print(f"  ⚠ SyntaxError in {file_path}: {e}", file=sys.stderr)
        return "", set()

    # Имя модуля: senpy/foo/bar.py → senpy.foo.bar
    rel = file_path.relative_to(package_root.parent)
    module_name = str(rel).replace("/", ".").replace("\\", ".").removesuffix(".py")
    # __init__.py → имя пакета
    if module_name.endswith(".__init__"):
        module_name = module_name[:-9]

    # Для подпакетов (senpy.formatter.rules) берём только top-level: senpy.formatter
    # Нет — нам нужны все уровни для точного графа. Оставляем полное имя.

    visitor = ImportVisitor(module_name)
    visitor.visit(tree)

    # Нормализуем импорты к top-level пакету (senpy.formatter.rules → senpy.formatter)
    # Нет — оставляем полные имена для точного анализа.
    # НО: current_module тоже должен быть полным.
    return module_name, visitor.imports


# =============================================================================
# 2. Построение графа и поиск циклов
# =============================================================================

def build_import_graph(package_root: Path) -> dict[str, set[str]]:
    """Строит граф импортов: {module: {imported_modules}}."""
    graph: dict[str, set[str]] = defaultdict(set)

    # Все .py файлы в пакете (без __pycache__, vendor)
    py_files = sorted(
        f for f in package_root.rglob("*.py")
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
    """Находит все циклы в графе через DFS с цветовой маркировкой.

    Returns:
        List of cycles, каждый цикл — список имён модулей.
        Например: [['senpy.analyzer', 'senpy.cli', 'senpy.analyzer']]
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
                # Нашли цикл — извлекаем его из path
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                cycles.append(cycle)
            elif color[neighbor] == WHITE:
                dfs(neighbor)

        path.pop()
        color[node] = BLACK
    for node in graph:
        if color[node] == WHITE:
            dfs(node)

    return cycles


# =============================================================================
# 3. Фильтрация и дедупликация циклов
# =============================================================================

def normalize_cycle(cycle: list[str]) -> tuple[str, ...]:
    """Нормализует цикл для дедупликации: начинает с наименьшего элемента.

    Например: [B, C, A, B] и [C, A, B, C] → оба становятся (A, B, C).
    """
    # Убираем последний элемент (он = первому, это замыкание цикла)
    core = cycle[:-1]
    if not core:
        return tuple(cycle)
    # Находим индекс наименьшего элемента
    min_idx = core.index(min(core))
    # Ротируем так, чтобы наименьший был первым
    rotated = core[min_idx:] + core[:min_idx]
    return tuple(rotated)


def deduplicate_cycles(cycles: list[list[str]]) -> list[list[str]]:
    """Убирает дубликаты циклов (один и тот же цикл может быть найден с разных стартов)."""
    seen: set[tuple[str, ...]] = set()
    unique: list[list[str]] = []
    for cycle in cycles:
        norm = normalize_cycle(cycle)
        if norm not in seen:
            seen.add(norm)
            unique.append(list(norm) + [norm[0]])  # замыкаем цикл
    return unique


# =============================================================================
# 4. Главная функция
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Статический детектор циклических зависимостей в senpy/."
    )
    parser.add_argument(
        "--package",
        default="senpy",
        help="Имя пакета для проверки (по умолчанию: senpy)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Показать весь граф импортов",
    )
    args = parser.parse_args()

    # Находим корень пакета
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
                print(f"  {module} → {', '.join(imports)}")
            else:
                print(f"  {module} (no imports)")
        print()

    cycles = find_cycles(graph)
    unique_cycles = deduplicate_cycles(cycles)

    if not unique_cycles:
        print(f"✓ No circular imports found in '{args.package}'/")
        print(f"  Analyzed {len(graph)} modules.")
        return 0

    print(f"\n✗ Found {len(unique_cycles)} circular import(s):\n", file=sys.stderr)
    for cycle in unique_cycles:
        print(f"  {' → '.join(cycle)}", file=sys.stderr)
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
