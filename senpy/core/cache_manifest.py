"""Backward compat re-export — CachedFileEntry and CacheManifest are now in cache.py.

In 0.6.1 the dataclasses were returned to cache.py due to a Python 3.14 bug
with dataclasses._is_type() (AttributeError when importing a separate module
during __init__.py loading). This file is kept only for backward compat —
`from senpy.core.cache_manifest import CachedFileEntry` keeps working.
"""

from __future__ import annotations

from senpy.core.cache import CachedFileEntry, CacheManifest

__all__ = ["CachedFileEntry", "CacheManifest"]
