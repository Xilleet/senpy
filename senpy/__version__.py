"""Single source of truth for the Senpy version.

All other locations (pyproject.toml, constants.SENPY_VERSION, server.py,
senpy-vscode/package.json) must be synchronized with this file via
`python bump_version.py`.

Change the version only here (or via `bump_version.py`, which will
update it here and everywhere else automatically).
"""

from __future__ import annotations

__version__ = "0.9.2"

# Convenient aliases for use in different parts of the codebase
# (e.g. the LSP server often needs "v0.4.7" with the prefix).
VERSION_WITH_PREFIX = f"v{__version__}"

# Semver parsing for complex checks (e.g. cache invalidation by major.minor).
# Derived from ``__version__`` so a manual edit of the string above (without
# also updating these three ints) cannot silently desync cache invalidation
# logic. Previously these were independent hardcoded ints — anyone who
# bumped only ``__version__`` left MAJOR/MINOR/PATCH on the old values,
# and ``CacheManager.compute_environment_fingerprint`` (which hashes
# ``MAJOR.MINOR``) would produce wrong hashes.
# TODO: disable or modify the update behavior in bump_version; otherwise, this update breaks.
# NOTE confirmed — `python bump_version.py patch` rewrites
# this file and replaces the derived tuple below with hardcoded ints
# (0, 9, 3), reintroducing the desync risk above. After running
# bump_version.py, restore the derived form manually:
#   MAJOR, MINOR, PATCH = (int(x) for x in __version__.split("."))
# The proper fix is to teach bump_version.py to preserve this line.
MAJOR, MINOR, PATCH = (int(x) for x in __version__.split("."))

__all__ = ["__version__", "VERSION_WITH_PREFIX", "MAJOR", "MINOR", "PATCH"]
