"""Single source of truth for the Senpy version.

All other places (pyproject.toml, constants.SENPY_VERSION, server.py,
senpy-vscode/package.json) must be synced with this file via
`python bump_version.py`.

Change the version only here (or via `bump_version.py`, which itself
will set it here and in all the other places).
"""

from __future__ import annotations

__version__ = "0.7.2"

# Convenient aliases for use in various places of the code
# (for example, the LSP server often needs "v0.4.7" with the prefix).
VERSION_WITH_PREFIX = f"v{__version__}"

# Semver parsing for complex checks (for example, cache invalidation by major.minor)
MAJOR: int = 0
MINOR: int = 7
PATCH: int = 2

__all__ = ["__version__", "VERSION_WITH_PREFIX", "MAJOR", "MINOR", "PATCH"]
