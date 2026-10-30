from __future__ import annotations

import contextlib
import hashlib
import os
import pickle
import shutil
from typing import TYPE_CHECKING

from senpy.core.cache_manifest import CacheManifest
from senpy.core.constants import SENPY_VERSION

# CachedFileEntry и CacheManifest вынесены в senpy/cache_manifest.py (Фаза 1.6).
# Реэкспортируем для backward compat: `from senpy.core.cache import CachedFileEntry` работает.

if TYPE_CHECKING:
    from senpy.core.analyzer import SenpyAnalyzer


def compute_file_hash(file_path: str) -> str:
    """Вычисляет быстрый MD5-хэш содержимого файла для защиты кэша от коллизий."""
    try:
        with open(file_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except OSError:
        return ""


class SafeCacheUnpickler(pickle.Unpickler):
    """Unpickler с белым списком модулей: cache.pkl приходит из недоверенного источника.

    Папка .senpy_cache лежит ВНУТРИ проекта Ren'Py и переезжает вместе с ним
    (шаринг проекта, скачивание, чужие моды), поэтому plain pickle.load = RCE
    через __reduce__ в подложенном файле. Легитимное содержимое кэша — только
    наши dataclasses и примитивы, любого find_class вне списка достаточно,
    чтобы отвергнуть файл. Сломанный кэш = None = штатная пересборка.
    """

    ALLOWED_MODULES = frozenset(
        {
            "senpy.cache",  # backward compat
            "senpy.cache_manifest",  # backward compat
            "senpy.core.cache",  # Фаза 2: новый путь
            "senpy.core.cache_manifest",  # Фаза 2: новый путь
            "senpy.models",  # backward compat
            "senpy.core.models",  # Фаза 2: новый путь
            "senpy.symbols",  # backward compat
            "senpy.core.symbols",  # Фаза 2: новый путь
            "senpy.signature",  # backward compat
            "senpy.core.signature",  # Фаза 2: новый путь
        }
    )

    # Redirect old module paths to new ones (0.5.5 restructuring).
    # Old cache.pkl files may reference senpy.cache, senpy.models, etc.
    # which no longer exist as physical modules. We redirect them to
    # the new senpy.core.* paths so old caches can still be loaded.
    _MODULE_REDIRECTS = {
        "senpy.cache": "senpy.core.cache",
        "senpy.cache_manifest": "senpy.core.cache_manifest",
        "senpy.models": "senpy.core.models",
        "senpy.symbols": "senpy.core.symbols",
        "senpy.signature": "senpy.core.signature",
    }

    def find_class(self, module: str, name: str):
        if module in self.ALLOWED_MODULES:
            # Redirect old module paths to new ones (backward compat)
            actual_module = self._MODULE_REDIRECTS.get(module, module)
            return super().find_class(actual_module, name)
        raise pickle.UnpicklingError(
            f"Security Error: Forbidden import '{module}.{name}' in senpy cache"
        )


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
                data = SafeCacheUnpickler(f).load()
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
                hasher.update(
                    str((sig.min_args, sig.max_args, sorted(sig.all_names))).encode("utf-8")
                )

        for scr_name in sorted(analyzer.screens.keys()):
            hasher.update(scr_name.encode("utf-8"))
            scr = analyzer.screens[scr_name]
            if scr.signature:
                sig = scr.signature
                hasher.update(
                    str((sig.min_args, sig.max_args, sorted(sig.all_names))).encode("utf-8")
                )

        for sym in sorted(analyzer.declared_symbols):
            hasher.update(sym.encode("utf-8"))
            if sym in analyzer.variables and analyzer.variables[sym].type_name:
                hasher.update(analyzer.variables[sym].type_name.encode("utf-8"))

        for var in sorted(analyzer.variables.values(), key=lambda v: v.name):
            if var.is_constant:
                hasher.update(var.name.encode("utf-8"))

        for img_name in sorted(analyzer.images.keys()):
            hasher.update(img_name.encode("utf-8"))

        for trans_name in sorted(analyzer.transforms.keys()):
            hasher.update(trans_name.encode("utf-8"))

        for chan in sorted(analyzer.registered_audio_channels):
            hasher.update(chan.encode("utf-8"))

        return hasher.hexdigest()
