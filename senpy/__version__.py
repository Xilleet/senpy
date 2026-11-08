"""Single source of truth for the Senpy version.

The version is defined here as ``__version__``. ``bump_version.py`` reads
this file and updates the following locations automatically:
- ``senpy-vscode/package.json``
- ``.github/release-header.md``
- ``docs/install.md``
- ``docs/index.md``
- ``.pre-commit-hooks.yaml`` (rev: line)

``pyproject.toml``, ``constants.SENPY_VERSION``, and ``server.py`` read the
version dynamically from this file (via ``importlib.metadata`` or direct
import) — they do NOT need bumping.

Change the version only here (or via ``bump_version.py``, which will
update it here and everywhere else automatically).
"""

from __future__ import annotations

__version__ = "0.8.4"

# Convenient aliases for use in different parts of the codebase
# (e.g. the LSP server often needs "v0.4.7" with the prefix).
VERSION_WITH_PREFIX = f"v{__version__}"

# Semver parsing for complex checks (e.g. cache invalidation by major.minor)
MAJOR: int = 0
MINOR: int = 8
PATCH: int = 4

__all__ = ["__version__", "VERSION_WITH_PREFIX", "MAJOR", "MINOR", "PATCH"]
