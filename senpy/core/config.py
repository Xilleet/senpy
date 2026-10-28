"""Конфигурация Senpy — чтение senpy.toml / pyproject.toml.

Вынесено из senpy/_unrpyc_bootstrap.py в Фазе 1.2 (0.5.3) для разрыва
циклической зависимости analyzer ↔ cli.

Раньше load_config лежала в _unrpyc_bootstrap.py, и analyzer.py делал
`from senpy.cli.main import load_config` (cli просто реэкспортировал её из
_unrpyc_bootstrap). Это создавало цикл:
    analyzer.py → cli.py → analyzer.py

Теперь load_config в этом модуле (senpy/config.py), и все зависят от него
однонаправленно:
    analyzer.py → senpy.config
    cli.py → senpy.config
    _unrpyc_bootstrap.py → senpy.config (возможно?)

Public API:
    load_config(project_path: str) -> dict
"""
from __future__ import annotations

import contextlib
import os
import tomllib


def load_config(project_path: str) -> dict:
    """Найти и прочитать конфигурацию Senpy.

    Ищет senpy.toml или pyproject.toml в порядке:
        1. В project_path/
        2. В родительской директории project_path/
        3. В текущей рабочей директории

    Возвращает содержимое секции [tool.senpy] (или [senpy] для senpy.toml).
    Если ни один файл не найден или TOML невалиден — возвращает пустой dict.

    Args:
        project_path: Путь к Ren'Py-проекту или папке с конфигом.

    Returns:
        Dict с конфигурацией. Пустой dict если конфиг не найден.
    """
    candidates = [
        os.path.join(project_path, "senpy.toml"),
        os.path.join(project_path, "pyproject.toml"),
        os.path.join(os.path.dirname(project_path), "senpy.toml"),
        os.path.join(os.path.dirname(project_path), "pyproject.toml"),
        os.path.join(os.getcwd(), "senpy.toml"),
        os.path.join(os.getcwd(), "pyproject.toml"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            with (
                contextlib.suppress(tomllib.TOMLDecodeError, OSError),
                open(c, "rb") as f,
            ):
                data = tomllib.load(f)
                return data.get("tool", {}).get("senpy", data.get("senpy", {}))
    return {}
