"""Single source of truth for the Senpy version.

All other locations (pyproject.toml, constants.SENPY_VERSION, server.py,
senpy-vscode/package.json) must be synchronized with this file via
`python bump_version.py`.

Change the version only here (or via `bump_version.py`, which will
update it here and everywhere else automatically).
"""

from __future__ import annotations

__version__ = "0.7.5"

# Convenient aliases for use in different parts of the codebase
# (e.g. the LSP server often needs "v0.4.7" with the prefix).
VERSION_WITH_PREFIX = f"v{__version__}"

# Semver parsing for complex checks (e.g. cache invalidation by major.minor)
MAJOR: int = 0
MINOR: int = 7
PATCH: int = 5

__all__ = ["__version__", "VERSION_WITH_PREFIX", "MAJOR", "MINOR", "PATCH"]
