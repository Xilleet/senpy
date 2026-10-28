#!/usr/bin/env python3
"""restructure_senpy.py — автоматическая реструктуризация senpy/ по папкам.

перемещение файлов из плоской структуры senpy/*.py
в иерархическую senpy/{core,rules,lsp,cli,formats,domain}/*.py.

БЕЗОПАСНОСТЬ:
    Скрипт делает только механические операции:
    1. Создаёт папки с __init__.py
    2. Перемещает файлы (git mv если в git, иначе shutil.move)
    3. Split checkers.py на 5 файлов в rules/checkers/
    4. Обновляет все импорты 'from senpy.X import' → 'from senpy.<folder>.X import'
    5. Создаёт senpy/__init__.py с re-exports для backward compat

    Скрипт НЕ меняет логику кода — только пути импортов.

ПРОВЕРКИ ПОСЛЕ ЗАПУСКА:
    1. python scripts/check_cycles.py → 0 циклов
    2. pytest tests/test_imports.py → 81 passed
    3. pytest tests/ → 425 passed (или сколько есть)

ИСПОЛЬЗОВАНИЕ:
    python scripts/restructure_senpy.py            # применить
    python scripts/restructure_senpy.py --dry-run  # показать что будет сделано
    python scripts/restructure_senpy.py --check    # только проверить текущее состояние

ВАЖНО:
    Перед запуском — ОБЯЗАТЕЛЬНО закоммитьте все изменения!
    Скрипт меняет много файлов, откатить через git reset --hard будет проще.
"""
from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

# =============================================================================
# Карта перемещений: старый путь → новый путь
# =============================================================================

# Файлы, которые ОСТАЮТСЯ в корне senpy/ (не переезжают)
STAYS_IN_ROOT = {
    "__init__.py",
    "__version__.py",
    "text_utils.py",  # используется всеми — оставляем в корне как утилиту
}

# Карта: имя файла → имя папки назначения
FILE_TO_FOLDER = {
    # === core/ — ядро (orchestrator + модели + кэш + константы) ===
    "analyzer.py": "core",
    "cache.py": "core",
    "cache_manifest.py": "core",
    "config.py": "core",
    "constants.py": "core",
    "coverage.py": "core",
    "models.py": "core",
    "scope.py": "core",
    "signature.py": "core",
    "sink.py": "core",
    "symbols.py": "core",

    # === rules/ — lint-правила ===
    "python_ast.py": "rules",
    "flow.py": "rules",
    "deprecated.py": "rules",
    "rules_info.py": "rules",
    # checkers.py — особый случай, split на 5 файлов в rules/checkers/

    # === lsp/ — LSP-сервер ===
    "server.py": "lsp",

    # === cli/ — CLI ===
    "cli.py": "cli",  # → cli/main.py
    "_cli_commands.py": "cli",  # → cli/commands.py
    "_unrpyc_bootstrap.py": "cli",  # → cli/unrpyc.py

    # === formats/ — I/O форматы ===
    "sarif.py": "formats",
    "html_report.py": "formats",
    "wiki.py": "formats",
    "stubs.py": "formats",
    "ci.py": "formats",
    "traceback.py": "formats",
    "stats.py": "formats",

    # === domain/ — Ren'Py domain knowledge ===
    "renpy_api.py": "domain",
    "text_tags.py": "domain",
    "assets.py": "domain",
    "rpa.py": "domain",
    "tsundere.py": "domain",
}

# Переименования при перемещении (старое_имя → новое_имя)
FILE_RENAME = {
    "cli.py": "main.py",  # senpy/cli.py → senpy/cli/main.py
    "_cli_commands.py": "commands.py",  # senpy/_cli_commands.py → senpy/cli/commands.py
    "_unrpyc_bootstrap.py": "unrpyc.py",  # senpy/_unrpyc_bootstrap.py → senpy/cli/unrpyc.py
}

# Классы из checkers.py и их целевые файлы
CHECKER_SPLIT = {
    "BaseChecker": ("rules/base.py", None),  # (файл, родительский класс если есть)
    "IfBlockContext": ("rules/base.py", None),  # dataclass в начале checkers.py
    "FormattingChecker": ("rules/checkers/formatting.py", "BaseChecker"),
    "ScreenChecker": ("rules/checkers/screen.py", "BaseChecker"),
    "AssetChecker": ("rules/checkers/asset.py", "BaseChecker"),
    "DialogueChecker": ("rules/checkers/dialogue.py", "BaseChecker"),
    "StateChecker": ("rules/checkers/state.py", "BaseChecker"),
}


# =============================================================================
# 1. Создание структуры папок
# =============================================================================

def create_folder_structure(senpy_root: Path, dry_run: bool = False) -> None:
    """Создаёт 7 папок с __init__.py."""
    folders = ["core", "rules", "rules/checkers", "lsp", "cli", "formats", "domain"]

    for folder in folders:
        folder_path = senpy_root / folder
        init_path = folder_path / "__init__.py"

        if dry_run:
            print(f"  [DRY-RUN] mkdir {folder_path}")
            print(f"  [DRY-RUN] create {init_path}")
            continue

        folder_path.mkdir(parents=True, exist_ok=True)
        if not init_path.exists():
            init_path.write_text(
                f'"""Senpy {folder} subpackage."""\n',
                encoding="utf-8",
            )
            print(f"  ✓ created {init_path}")


# =============================================================================
# 2. Перемещение файлов
# =============================================================================

def move_file(
    src: Path,
    dst: Path,
    dry_run: bool = False,
    use_git: bool = True,
) -> None:
    """Перемещает файл. Использует git mv если в git, иначе shutil.move."""
    if dry_run:
        print(f"  [DRY-RUN] move {src} → {dst}")
        return

    dst.parent.mkdir(parents=True, exist_ok=True)

    if use_git:
        # Проверим, в git ли файл
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(src)],
            capture_output=True,
            cwd=src.parent,
        )
        if result.returncode == 0:
            # Файл в git — используем git mv
            subprocess.run(
                ["git", "mv", str(src), str(dst)],
                check=True,
                cwd=src.parent,
            )
            print(f"  ✓ git mv {src.name} → {dst}")
            return

    # Не в git — обычное перемещение
    shutil.move(str(src), str(dst))
    print(f"  ✓ move {src.name} → {dst}")


def move_all_files(senpy_root: Path, dry_run: bool = False) -> None:
    """Перемещает все файлы по карте FILE_TO_FOLDER."""
    print("\n=== Перемещение файлов ===")

    for filename, folder in FILE_TO_FOLDER.items():
        src = senpy_root / filename
        if not src.exists():
            print(f"  ⚠ {src} не найден, пропускаю")
            continue

        new_name = FILE_RENAME.get(filename, filename)
        dst = senpy_root / folder / new_name

        move_file(src, dst, dry_run=dry_run)


# =============================================================================
# 3. Split checkers.py на 5 файлов
# =============================================================================

def split_checkers_py(senpy_root: Path, dry_run: bool = False) -> None:
    """Разделяет checkers.py на 5 файлов в rules/checkers/ + base.py в rules/.

    Внимание: вызывается ПОСЛЕ move_all_files (checkers.py уже не существует).
    Но мы ожидаем что checkers.py остался в корне — он не в FILE_TO_FOLDER.
    """
    print("\n=== Split checkers.py ===")

    checkers_py = senpy_root / "checkers.py"
    if not checkers_py.exists():
        print(f"  ⚠ {checkers_py} не найден — возможно уже split")
        return

    content = checkers_py.read_text(encoding="utf-8")
    tree = ast.parse(content)

    # Соберём top-level элементы: imports, classes, функции, присваивания
    # и сгруппируем по целевым файлам
    groups: dict[str, list[str]] = {
        "rules/base.py": [],
        "rules/checkers/formatting.py": [],
        "rules/checkers/screen.py": [],
        "rules/checkers/asset.py": [],
        "rules/checkers/dialogue.py": [],
        "rules/checkers/state.py": [],
    }

    lines = content.splitlines(keepends=True)

    # Соберём все импорты (они пойдут в каждый файл)
    imports_lines = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            start = node.lineno - 1
            end = node.end_lineno
            imports_lines.extend(lines[start:end])

    # Распределение классов по файлам
    # Отслеживаем какие имена нужны каждому классу (наследники, типы в сигнатурах)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name in CHECKER_SPLIT:
            target_file_key, parent_class = CHECKER_SPLIT[node.name]
            # Нормализуем ключ: "rules/base.py" или "rules/checkers/formatting.py"
            if "/" in target_file_key:
                # "rules/checkers/formatting.py" → key
                key = target_file_file = target_file_key
            else:
                key = target_file_key
            start = node.lineno - 1
            end = node.end_lineno
            class_lines = lines[start:end]
            groups[key].extend(class_lines)
        elif isinstance(node, ast.ClassDef) and node.name == "IfBlockContext":
            # IfBlockContext — dataclass в начале, идёт в base.py
            start = node.lineno - 1
            end = node.end_lineno
            groups["rules/base.py"].extend(lines[start:end])

    # Записываем файлы
    for rel_path, body_lines in groups.items():
        dst = senpy_root / rel_path
        if dry_run:
            print(f"  [DRY-RUN] create {dst} ({len(body_lines)} lines)")
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        # Собираем файл: заголовок + импорты + доп. импорты + тело
        header = f'"""{dst.stem} — extracted from checkers.py (Фаза 2, 0.5.4)."""\n\n'
        content_parts = [header]
        if imports_lines:
            content_parts.extend(imports_lines)
            content_parts.append("\n\n")

        # Для файлов-наследников (formatting.py, screen.py, asset.py, dialogue.py, state.py)
        # добавляем импорт BaseChecker из senpy.rules.base
        if rel_path.startswith("rules/checkers/"):
            content_parts.append("from senpy.rules.base import BaseChecker\n\n")

        content_parts.extend(body_lines)
        dst.write_text("".join(content_parts), encoding="utf-8")
        print(f"  ✓ created {dst} ({len(body_lines)} lines)")

    # Создаём rules/checkers/__init__.py с re-exports
    if not dry_run:
        checkers_init = senpy_root / "rules" / "checkers" / "__init__.py"
        checkers_init.write_text(
            '"""Senpy rules/checkers subpackage — 5 чекеров, split из checkers.py."""\n\n'
            'from senpy.rules.checkers.formatting import FormattingChecker\n'
            'from senpy.rules.checkers.screen import ScreenChecker\n'
            'from senpy.rules.checkers.asset import AssetChecker\n'
            'from senpy.rules.checkers.dialogue import DialogueChecker\n'
            'from senpy.rules.checkers.state import StateChecker\n\n'
            '__all__ = ["FormattingChecker", "ScreenChecker", "AssetChecker",\n'
            '           "DialogueChecker", "StateChecker"]\n',
            encoding="utf-8",
        )
        print(f"  ✓ created {checkers_init}")

    # Удаляем старый checkers.py
    if not dry_run:
        checkers_py.unlink()
        print(f"  ✓ deleted {checkers_py}")


# =============================================================================
# 4. Обновление импортов во всех .py файлах
# =============================================================================

# Карта обратного разрешения: имя модуля → полный путь после реструктуризации
MODULE_NEW_PATH = {
    "analyzer": "senpy.core.analyzer",
    "cache": "senpy.core.cache",
    "cache_manifest": "senpy.core.cache_manifest",
    "config": "senpy.core.config",
    "constants": "senpy.core.constants",
    "coverage": "senpy.core.coverage",
    "models": "senpy.core.models",
    "scope": "senpy.core.scope",
    "signature": "senpy.core.signature",
    "sink": "senpy.core.sink",
    "symbols": "senpy.core.symbols",
    "python_ast": "senpy.rules.python_ast",
    "flow": "senpy.rules.flow",
    "deprecated": "senpy.rules.deprecated",
    "rules_info": "senpy.rules.rules_info",
    "server": "senpy.lsp.server",
    "cli": "senpy.cli.main",  # cli.py → cli/main.py
    "_cli_commands": "senpy.cli.commands",
    "_unrpyc_bootstrap": "senpy.cli.unrpyc",
    "sarif": "senpy.formats.sarif",
    "html_report": "senpy.formats.html_report",
    "wiki": "senpy.formats.wiki",
    "stubs": "senpy.formats.stubs",
    "ci": "senpy.formats.ci",
    "traceback": "senpy.formats.traceback",
    "stats": "senpy.formats.stats",
    "renpy_api": "senpy.domain.renpy_api",
    "text_tags": "senpy.domain.text_tags",
    "assets": "senpy.domain.assets",
    "rpa": "senpy.domain.rpa",
    "tsundere": "senpy.domain.tsundere",
    # checkers — особый: стал пакетом
    "checkers": "senpy.rules.checkers",
    # text_utils остаётся в корне
    "text_utils": "senpy.text_utils",
    # __version__ остаётся в корне
    "__version__": "senpy.__version__",
}


def update_imports_in_file(file_path: Path, dry_run: bool = False) -> bool:
    """Обновляет импорты в одном .py файле. Возвращает True если были изменения."""
    content = file_path.read_text(encoding="utf-8")
    original = content

    # Паттерн: from senpy.X import ...  или  from senpy.X.Y import ...
    # Заменяем senpy.X на senpy.<folder>.X (если X в карте)
    for old_module, new_module in MODULE_NEW_PATH.items():
        # from senpy.<old> import ... → from <new> import ...
        # Внимание: не трогаем senpy.<old>.<sub> (это подпакеты)
        content = re.sub(
            rf'\bfrom senpy\.{old_module}\b(?!\.)',
            f'from {new_module}',
            content,
        )
        # import senpy.<old> → import <new>
        content = re.sub(
            rf'\bimport senpy\.{old_module}\b(?!\.)',
            f'import {new_module}',
            content,
        )

    if content != original:
        if not dry_run:
            file_path.write_text(content, encoding="utf-8")
        return True
    return False


def update_all_imports(project_root: Path, dry_run: bool = False) -> None:
    """Обновляет импорты во всех .py файлах проекта."""
    print("\n=== Обновление импортов ===")

    # Все .py файлы в senpy/ (включая новые подпапки) и tests/
    py_files = []
    for pattern in ["senpy/**/*.py", "tests/**/*.py", "scripts/**/*.py"]:
        py_files.extend(project_root.glob(pattern))

    # Исключаем __pycache__, vendor, .ruff_cache
    py_files = [
        f for f in py_files
        if "__pycache__" not in str(f)
        and "vendor" not in str(f)
        and ".ruff_cache" not in str(f)
    ]

    updated = 0
    for py_file in sorted(py_files):
        if update_imports_in_file(py_file, dry_run=dry_run):
            updated += 1
            if dry_run:
                print(f"  [DRY-RUN] would update {py_file}")
            else:
                print(f"  ✓ updated {py_file}")

    print(f"\n  Total: {updated} files updated")


# =============================================================================
# 5. Re-exports в senpy/__init__.py
# =============================================================================

def create_senpy_init(senpy_root: Path, dry_run: bool = False) -> None:
    """Создаёт senpy/__init__.py с re-exports для backward compat."""
    print("\n=== Создание senpy/__init__.py с re-exports ===")

    init_content = '''"""Senpy — semantic linter & LSP for Ren'Py.

Re-exports для backward compat: после реструктуризации 0.5.4 (файлы
переехали в core/, rules/, lsp/, cli/, formats/, domain/) старые импорты
продолжают работать:
    from senpy import SenpyAnalyzer           # → senpy.core.analyzer
    from senpy import Diagnostic, RULE_SEVERITY  # → senpy.core.models
    from senpy import main                    # → senpy.cli.main
"""
from __future__ import annotations

# Core
from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.cache import CacheManager, CacheManifest, CachedFileEntry, SafeCacheUnpickler
from senpy.core.config import load_config
from senpy.core.constants import SENPY_VERSION
from senpy.core.models import Diagnostic, RULE_SEVERITY, AnalysisResult, FileScope
from senpy.core.sink import DiagnosticSink
from senpy.core.symbols import (
    VariableSymbol, LabelSymbol, ScreenSymbol, ImageSymbol, TransformSymbol,
)

# CLI
from senpy.cli.main import main

# Version
from senpy.__version__ import __version__, VERSION_WITH_PREFIX

__all__ = [
    # Core
    "SenpyAnalyzer",
    "CacheManager", "CacheManifest", "CachedFileEntry", "SafeCacheUnpickler",
    "load_config",
    "SENPY_VERSION",
    "Diagnostic", "RULE_SEVERITY", "AnalysisResult", "FileScope",
    "DiagnosticSink",
    "VariableSymbol", "LabelSymbol", "ScreenSymbol", "ImageSymbol", "TransformSymbol",
    # CLI
    "main",
    # Version
    "__version__", "VERSION_WITH_PREFIX",
]
'''

    init_path = senpy_root / "__init__.py"
    if dry_run:
        print(f"  [DRY-RUN] would write {init_path}")
        return

    init_path.write_text(init_content, encoding="utf-8")
    print(f"  ✓ created {init_path}")


# =============================================================================
# 6. Проверки
# =============================================================================

def verify_no_cycles(project_root: Path) -> bool:
    """Запускает check_cycles.py, возвращает True если 0 циклов."""
    print("\n=== Проверка: циклы ===")
    check_script = project_root / "scripts" / "check_cycles.py"
    if not check_script.exists():
        print(f"  ⚠ {check_script} не найден, пропускаю")
        return True

    result = subprocess.run(
        [sys.executable, str(check_script)],
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    print(result.stdout)
    if result.returncode == 0:
        print("  ✓ No cycles")
        return True
    print(f"  ✗ Cycles found:\n{result.stderr}")
    return False


def verify_imports(project_root: Path) -> bool:
    """Пробует импортировать ключевые модули."""
    print("\n=== Проверка: ключевые импорты ===")
    imports_to_test = [
        "from senpy.core.analyzer import SenpyAnalyzer",
        "from senpy.core.models import Diagnostic, RULE_SEVERITY",
        "from senpy.cli.main import main",
        "from senpy.rules.checkers import FormattingChecker, ScreenChecker, AssetChecker, DialogueChecker, StateChecker",
        "from senpy.rules.base import BaseChecker",
        "from senpy import SenpyAnalyzer, Diagnostic, main, __version__",
    ]

    all_ok = True
    for imp in imports_to_test:
        result = subprocess.run(
            [sys.executable, "-c", imp],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        if result.returncode == 0:
            print(f"  ✓ {imp}")
        else:
            print(f"  ✗ {imp}")
            print(f"    {result.stderr.strip()}")
            all_ok = False

    return all_ok


# =============================================================================
# Главная функция
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Реструктуризация senpy/ по папкам (Фаза 2, 0.5.4)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать что будет сделано, без реальных изменений",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Только проверить текущее состояние (без изменений)",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Корень проекта (по умолчанию: родитель scripts/)",
    )
    args = parser.parse_args()

    # Находим корень проекта
    script_dir = Path(__file__).resolve().parent
    project_root = Path(args.project_root) if args.project_root else script_dir.parent
    senpy_root = project_root / "senpy"

    if not senpy_root.is_dir():
        print(f"Error: senpy/ not found at {senpy_root}", file=sys.stderr)
        return 2

    print(f"Project root: {project_root}")
    print(f"Senpy root:   {senpy_root}")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'CHECK' if args.check else 'APPLY'}")

    if args.check:
        # Только проверки
        ok = verify_no_cycles(project_root)
        ok = verify_imports(project_root) and ok
        return 0 if ok else 1

    # === Применение ===

    # 1. Создать папки
    print("\n--- Шаг 1: Создание структуры папок ---")
    create_folder_structure(senpy_root, dry_run=args.dry_run)

    # 2. Переместить файлы (кроме checkers.py — его split отдельно)
    print("\n--- Шаг 2: Перемещение файлов ---")
    # ВНИМАНИЕ: checkers.py НЕ в FILE_TO_FOLDER — он обрабатывается отдельно
    move_all_files(senpy_root, dry_run=args.dry_run)

    # 3. Split checkers.py
    print("\n--- Шаг 3: Split checkers.py ---")
    split_checkers_py(senpy_root, dry_run=args.dry_run)

    # 4. Обновить импорты
    print("\n--- Шаг 4: Обновление импортов ---")
    update_all_imports(project_root, dry_run=args.dry_run)

    # 5. Создать senpy/__init__.py
    print("\n--- Шаг 5: Re-exports в __init__.py ---")
    create_senpy_init(senpy_root, dry_run=args.dry_run)

    # 6. Проверки
    if not args.dry_run:
        print("\n--- Шаг 6: Проверки ---")
        cycles_ok = verify_no_cycles(project_root)
        imports_ok = verify_imports(project_root)

        if cycles_ok and imports_ok:
            print("\n✓ Реструктуризация завершена успешно!")
            print("\nДальнейшие шаги:")
            print("  1. pytest tests/test_imports.py -v  → 81 passed")
            print("  2. pytest tests/ -v                → 425 passed")
            print("  3. git add -A && git commit -m 'refactor(0.5.4): restructure senpy/ into subpackages'")
            return 0
        print("\n✗ Проверки не прошли. Откатите изменения: git reset --hard")
        return 1

    print("\n[DRY-RUN] Завершено. Никаких реальных изменений не сделано.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
