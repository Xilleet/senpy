"""Backward compat re-export — CachedFileEntry и CacheManifest теперь в cache.py.

В 0.6.1 dataclass'ы возвращены в cache.py из-за Python 3.14 бага с
dataclasses._is_type() (AttributeError при импорте отдельного модуля
во время загрузки __init__.py). Этот файл сохранён только для backward
compat — `from senpy.core.cache_manifest import CachedFileEntry` продолжает работать.
"""
from __future__ import annotations

from senpy.core.cache import CachedFileEntry, CacheManifest

__all__ = ["CachedFileEntry", "CacheManifest"]
