#!/usr/bin/env python3
"""bump_version.py — апдейт версии Senpy.

ECO-9: версия хранится в единственном месте — senpy/__version__.py.
Все остальные файлы (constants.py, server.py, pyproject.toml) импортируют
или читают её динамически. Только package.json (для VS Code marketplace)
по-прежнему требует явную версию — её мы обновляем здесь.

Использование:
    python bump_version.py             # интерактивное меню
    python bump_version.py patch       # 0.4.7 -> 0.4.8
    python bump_version.py minor       # 0.4.7 -> 0.5.0
    python bump_version.py major       # 0.4.7 -> 1.0.0
    python bump_version.py 1.2.3       # явная версия
"""
from __future__ import annotations

import json
import os
import re
import sys

VERSION_PY_PATH = os.path.join("senpy", "__version__.py")
PACKAGE_JSON_PATH = os.path.join("senpy-vscode", "package.json")


def select_target_version(major: int, minor: int, patch: int) -> str | None:
    patch_ver = f"{major}.{minor}.{patch + 1}"
    minor_ver = f"{major}.{minor + 1}.0"
    major_ver = f"{major + 1}.0.0"

    # Если передан аргумент командной строки (python bump_version.py minor)
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip().lower()
        if arg in ("patch", "p", "1"):
            return patch_ver
        if arg in ("minor", "m", "2"):
            return minor_ver
        if arg in ("major", "3"):
            return major_ver
        if re.match(r"^\d+\.\d+\.\d+$", arg):
            return arg
        print(f"[!] Неизвестный аргумент: '{arg}'. Используйте: patch, minor, major или версию X.Y.Z")
        return None

    # Интерактивное меню
    print("=" * 50)
    print(f"[*] Текущая версия: {major}.{minor}.{patch}")
    print("=" * 50)
    print(f"  [1] Patch: {patch_ver}  (предназначается для багфиксов, хотфиксов и мелких правок регулярок без изменения архитектуры и без добавления крупных фич)")
    print(f"  [2] Minor: {minor_ver}  (выпускается, когда проект получает новые крупные возможности, расширение семантики или переход на новый уровень качества)")
    print(f"  [3] Major: {major_ver}  (статус первого стабильного релизного билда (Production Ready), когда API стабилизирован и протестирован на десятках реальных новелл)")
    print(f"  [c] Ввести свою версию вручную")
    print(f"  [q] Отмена")
    print("=" * 50)

    choice = input("[?] Выберите вариант [1/2/3/c/q] (по умолчанию 2): ").strip().lower()

    if choice in ("q", "quit", "exit"):
        return None
    if choice in ("1", "patch"):
        return patch_ver
    if choice in ("", "2", "minor"):
        return minor_ver
    if choice in ("3", "major"):
        return major_ver
    if choice in ("c", "custom"):
        custom = input("[?] Введите версию (например, 0.3.0): ").strip()
        if re.match(r"^\d+\.\d+\.\d+$", custom):
            return custom
        print("[!] Некорректный формат версии.")
        return None

    return minor_ver


def read_current_version() -> tuple[int, int, int]:
    """Читает текущую версию из senpy/__version__.py."""
    if not os.path.exists(VERSION_PY_PATH):
        print(f"[ERROR] {VERSION_PY_PATH} не найден!")
        sys.exit(1)

    with open(VERSION_PY_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Ищем __version__ = "X.Y.Z"
    match = re.search(r'__version__\s*=\s*["\'](\d+)\.(\d+)\.(\d+)["\']', content)
    if not match:
        print("[!] Строка __version__ не найдена в senpy/__version__.py.")
        sys.exit(1)

    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def write_version_to_pyfile(next_ver: str) -> None:
    """Обновляет senpy/__version__.py с новой версией + MAJOR/MINOR/PATCH."""
    major, minor, patch = (int(x) for x in next_ver.split("."))
    new_content = f'''"""Single source of truth для версии Senpy.

Все остальные места (pyproject.toml, constants.SENPY_VERSION, server.py,
senpy-vscode/package.json) должны синхронизироваться с этим файлом через
`python bump_version.py`.

Изменять версию только здесь (или через `bump_version.py`, который сам
проставит её сюда и во все остальные места).
"""
from __future__ import annotations

__version__ = "{next_ver}"

# Удобные алиасы для использования в разных местах кода
# (например, в LSP-сервере часто нужен "v0.4.7" с префиксом).
VERSION_WITH_PREFIX = f"v{{__version__}}"

# Semver-разбор для сложных проверок (например, cache invalidation по major.minor)
MAJOR: int = {major}
MINOR: int = {minor}
PATCH: int = {patch}

__all__ = ["__version__", "VERSION_WITH_PREFIX", "MAJOR", "MINOR", "PATCH"]
'''
    with open(VERSION_PY_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"[✔] senpy/__version__.py: -> {next_ver}")


def write_version_to_package_json(next_ver: str) -> None:
    """Обновляет senpy-vscode/package.json — VS Code marketplace требует явную версию."""
    if not os.path.exists(PACKAGE_JSON_PATH):
        print(f"[!] Warning: {PACKAGE_JSON_PATH} не найден, пропуск.")
        return
    try:
        with open(PACKAGE_JSON_PATH, "r", encoding="utf-8") as f:
            pkg_data = json.load(f)
        old_ver = pkg_data.get("version", "?")
        pkg_data["version"] = next_ver
        with open(PACKAGE_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(pkg_data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"[✔] senpy-vscode/package.json: {old_ver} -> {next_ver}")
    except (OSError, json.JSONDecodeError, KeyError) as e:
        print(f"[!] Warning: не удалось синхронизировать package.json: {e}")


def bump_version():
    maj_n, min_n, pat_n = read_current_version()
    current_ver = f"{maj_n}.{min_n}.{pat_n}"

    next_ver = select_target_version(maj_n, min_n, pat_n)
    if not next_ver:
        print(f"[*] Версия {current_ver} остаётся без изменений.\n")
        return

    print(f"\n[+] Обновление версии: {current_ver} -> {next_ver}\n")

    # 1. Обновляем senpy/__version__.py — единственный источник правды
    write_version_to_pyfile(next_ver)

    # 2. Обновляем senpy-vscode/package.json (marketplace требует явную версию)
    write_version_to_package_json(next_ver)

    # 3. Готово. constants.py, server.py, pyproject.toml подхватят версию
    # автоматически через import / dynamic = ["version"].
    print(f"\n[★] Успешно! Проект обновлён до версии {next_ver}.")
    print(f"    constants.py / server.py / pyproject.toml подхватят автоматически.\n")


if __name__ == "__main__":
    bump_version()
