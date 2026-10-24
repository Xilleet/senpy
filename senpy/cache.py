from __future__ import annotations

import contextlib
import hashlib
import os
import pickle
import shutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from senpy.constants import SENPY_VERSION

if TYPE_CHECKING:
    from senpy.analyzer import SenpyAnalyzer
    from senpy.models import Diagnostic, FileScope


@dataclass
class CachedFileEntry:
    mtime: float
    size: int
    lines_count: int
    scope: FileScope
    diagnostics: list[Diagnostic] = field(default_factory=list)
    used_assets: set[str] = field(default_factory=set)


@dataclass
class CacheManifest:
    version: str
    global_symbol_hash: str
    files: dict[str, CachedFileEntry] = field(default_factory=dict)


class CacheManager:
    def __init__(self, project_path: str, enabled: bool = True):
        self.project_path = os.path.abspath(project_path)
        self.cache_dir = os.path.join(self.project_path, ".senpy_cache")
        self.manifest_path = os.path.join(self.cache_dir, "cache.pkl")
        self.enabled = enabled
        self.manifest: CacheManifest | None = None

    def clear(self) -> bool:
        """Полная очистка папки кэша."""
        if os.path.exists(self.cache_dir):
            shutil.rmtree(self.cache_dir, ignore_errors=True)
            return True
        return False

    def ensure_cache_dir(self) -> None:
        """Создаёт директорию кэша и защитный .gitignore."""
        if not self.enabled:
            return
        os.makedirs(self.cache_dir, exist_ok=True)
        gitignore = os.path.join(self.cache_dir, ".gitignore")
        if not os.path.exists(gitignore):
            with open(gitignore, "w", encoding="utf-8") as f:
                f.write("*\n")

    def load_manifest(self) -> CacheManifest | None:
        """Загружает манифест из кэша с проверкой версии."""
        if not self.enabled or not os.path.exists(self.manifest_path):
            return None
        with contextlib.suppress(OSError, pickle.PickleError, EOFError, AttributeError, ValueError):
            with open(self.manifest_path, "rb") as f:
                data = pickle.load(f)
            if isinstance(data, CacheManifest) and data.version == SENPY_VERSION:
                self.manifest = data
                return data
        return None

    def save_manifest(self, manifest: CacheManifest) -> None:
        """Атомарно сохраняет манифест в бинарный pickle."""
        if not self.enabled:
            return
        with contextlib.suppress(OSError, pickle.PickleError):
            self.ensure_cache_dir()
            tmp_path = self.manifest_path + ".tmp"
            with open(tmp_path, "wb") as f:
                pickle.dump(manifest, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp_path, self.manifest_path)

    @staticmethod
    def compute_global_hash(analyzer: SenpyAnalyzer) -> str:
        """Вычисляет хэш глобального состояния проекта (метки, экраны, сигнатуры, переменные)."""
        hasher = hashlib.md5()
        for lbl_name in sorted(analyzer.labels.keys()):
            hasher.update(lbl_name.encode("utf-8"))
            lbl = analyzer.labels[lbl_name]
            if lbl.signature:
                sig = lbl.signature
                hasher.update(str((sig.min_args, sig.max_args, sorted(sig.all_names))).encode("utf-8"))

        for scr_name in sorted(analyzer.screens.keys()):
            hasher.update(scr_name.encode("utf-8"))
            scr = analyzer.screens[scr_name]
            if scr.signature:
                sig = scr.signature
                hasher.update(str((sig.min_args, sig.max_args, sorted(sig.all_names))).encode("utf-8"))

        for sym in sorted(analyzer.declared_symbols):
            hasher.update(sym.encode("utf-8"))
            if sym in analyzer.variables and analyzer.variables[sym].type_name:
                hasher.update(analyzer.variables[sym].type_name.encode("utf-8"))

        for var in sorted(analyzer.variables.values(), key=lambda v: v.name):
            if var.is_constant:
                hasher.update(var.name.encode("utf-8"))

        for img_name in sorted(analyzer.images.keys()):
            hasher.update(img_name.encode("utf-8"))

        for chan in sorted(analyzer.registered_audio_channels):
            hasher.update(chan.encode("utf-8"))

        return hasher.hexdigest()