"""Dataclasses для кэша Senpy — вынесено из senpy/cache.py.

Фаза 1.6 (0.5.3): разрыв циклической зависимости analyzer ↔ cache.
CacheManifest и CachedFileEntry не имеют зависимостей от analyzer,
только от senpy.models. Вынесение их в отдельный модуль позволяет
cache.py зависеть от cache_manifest однонаправленно.

CacheManager (в senpy/cache.py) всё ещё использует SenpyAnalyzer через
TYPE_CHECKING (для compute_global_hash), но это только type hint,
не runtime импорт. Цикл разорван на уровне импортов.

Public API:
    CachedFileEntry — метаданные одного закэшированного файла
    CacheManifest — полный манифест кэша (все файлы + global hash)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from senpy.core.models import Diagnostic, FileScope


@dataclass
class CachedFileEntry:
    """Метаданные одного закэшированного файла (для Tier 1 cache)."""
    mtime: float
    size: int
    lines_count: int
    scope: FileScope
    diagnostics: list[Diagnostic] = field(default_factory=list)
    used_assets: set[str] = field(default_factory=set)
    content_hash: str = ""
    collect_diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass
class CacheManifest:
    """Полный манифест кэша: версия Senpy + global symbol hash + все файлы."""
    version: str
    global_symbol_hash: str
    files: dict[str, CachedFileEntry] = field(default_factory=dict)
