"""Path normalization utilities for Senpy.

Provides a single ``normalize_path`` function used across the codebase
to produce canonical, platform-independent path keys for dict lookups
(e.g. ``file_scopes``, ``in_memory_files``, ``_latest_diagnostics_by_path``).

Before this module existed, ``os.path.normcase(os.path.abspath(...))``
was inlined in 12+ places across ``analyzer.py``, ``stats.py``,
``translation.py``, ``dead_code.py``, ``lsp/server.py``, and ``unrpyc.py``.
"""

from __future__ import annotations

import os


def normalize_path(path: str) -> str:
    """Return a canonical, case-normalized absolute path.

    Equivalent to ``os.path.normcase(os.path.abspath(path))``.
    Used as a dict key for file-scoped state (file_scopes,
    in_memory_files, diagnostics caches).

    On Windows, ``normcase`` lowercases the path. On Linux/macOS, it's
    a no-op (case-sensitive filesystems). ``abspath`` resolves ``.``,
    ``..``, and symlinks to produce an absolute path.
    """
    return os.path.normcase(os.path.abspath(path))
