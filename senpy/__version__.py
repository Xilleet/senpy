"""Single source of truth для версии Senpy.

Все остальные места (pyproject.toml, constants.SENPY_VERSION, server.py,
senpy-vscode/package.json) должны синхронизироваться с этим файлом через
`python bump_version.py`.

Изменять версию только здесь (или через `bump_version.py`, который сам
проставит её сюда и во все остальные места).
"""
from __future__ import annotations

__version__ = "0.6.3"

# Удобные алиасы для использования в разных местах кода
# (например, в LSP-сервере часто нужен "v0.4.7" с префиксом).
VERSION_WITH_PREFIX = f"v{__version__}"

# Semver-разбор для сложных проверок (например, cache invalidation по major.minor)
MAJOR: int = 0
MINOR: int = 6
PATCH: int = 3

__all__ = ["__version__", "VERSION_WITH_PREFIX", "MAJOR", "MINOR", "PATCH"]
