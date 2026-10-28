from __future__ import annotations

import contextlib
import os
import pickle
import zlib
from typing import ClassVar

from senpy.constants import (
    AUDIO_EXTENSIONS,
    BUILTIN_COLORS,
    IGNORED_DIRS,
    MEDIA_EXTENSIONS,
)
from senpy.models import Diagnostic
from senpy.rpa import safe_load_rpa_index


def find_orphaned_rpyc(project_path: str) -> list[str]:
    """Находит скомпилированные .rpyc файлы, у которых нет исходных .rpy."""
    orphans = []
    for root, dirs, filenames in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for f in filenames:
            if f.endswith(".rpyc"):
                base_name = f[:-1]
                rpy_path = os.path.join(root, base_name)
                if not os.path.exists(rpy_path):
                    orphans.append(os.path.join(root, f))
    return orphans


class AssetManager:
    _asset_cache: ClassVar[dict[str, tuple[set[str], set[str]]]] = {}

    def __init__(self, project_path: str):
        self.project_path = os.path.abspath(project_path)
        self.known_assets: set[str] = set()
        self.valid_images: set[str] = set(BUILTIN_COLORS)
        self.media_disk_files: dict[str, str] = {}  # rel_path -> full_path
        self.audio_dir_files: dict[str, str] = {}  # stem -> full rel path
        self.used_asset_keys: set[str] = set()

    def index(self) -> None:
        """Сканирует директорию проекта и RPA-архивы, индексируя все медиафайлы."""
        self.known_assets.clear()
        self.valid_images = set(BUILTIN_COLORS)
        self.media_disk_files.clear()
        self.audio_dir_files.clear()
        self.used_asset_keys.clear()

        if self.project_path in self._asset_cache:
            cached_assets, cached_images = self._asset_cache[self.project_path]
            self.known_assets = set(cached_assets)
            self.valid_images = set(cached_images)

        for root, dirs, filenames in os.walk(self.project_path):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for f in filenames:
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, self.project_path).replace("\\", "/").lower()
                self.known_assets.add(rel_path)
                self.known_assets.add(f.lower())

                clean_rel = rel_path.removeprefix("game/")
                self.known_assets.add(clean_rel)

                _, ext = os.path.splitext(f.lower())
                if ext in MEDIA_EXTENSIONS:
                    self.media_disk_files[rel_path] = full_path

                    if clean_rel.startswith(("audio/", "bgm/", "sfx/")) and ext in AUDIO_EXTENSIONS:
                        stem = os.path.splitext(os.path.basename(clean_rel))[0]
                        self.audio_dir_files[stem] = rel_path

                if f.lower().endswith(".rpa"):
                    self._read_rpa_index(full_path)

        for asset in self.known_assets:
            base, ext = os.path.splitext(asset)

            # Оставляем строгий парсинг только для официального стандарта images/
            if ext.lower() in (".png", ".webp", ".jpg", ".jpeg"):
                clean_name = base.replace("\\", "/").lower()
                clean_name = clean_name.removeprefix("game/")
                if clean_name.startswith("images/"):
                    clean_name = clean_name.removeprefix("images/")
                    tokenized = clean_name.replace("/", " ").replace("_", " ")
                    self.valid_images.add(tokenized)
                    self.valid_images.add(os.path.basename(clean_name))

        self._asset_cache[self.project_path] = (set(self.known_assets), set(self.valid_images))

    def _read_rpa_index(self, rpa_path: str) -> None:
        with (
            contextlib.suppress(OSError, zlib.error, pickle.UnpicklingError, ValueError),
            open(rpa_path, "rb") as f,
        ):
            header = f.read(40)
            if header.startswith((b"RPA-3.0 ", b"RPA-2.0 ")):
                offset = int(header[8:24], 16)
                f.seek(offset)
                index = safe_load_rpa_index(f.read())
                for filename in index:
                    clean_fn = filename.replace("\\", "/").lower()
                    self.known_assets.add(clean_fn)
                    self.known_assets.add(os.path.basename(clean_fn))
                    if clean_fn.startswith("game/"):
                        self.known_assets.add(clean_fn[5:])

    def mark_used(self, asset_ref: str) -> None:
        """Регистрирует использование ассета в коде."""
        ref_norm = asset_ref.replace("\\", "/").lower().strip()
        self.used_asset_keys.add(ref_norm)
        self.used_asset_keys.add(os.path.basename(ref_norm))

    def check_unused(self) -> list[Diagnostic]:
        """RPY503: Находит медиафайлы на диске, на которые нет ссылок в сценарии."""
        diagnostics: list[Diagnostic] = []
        for rel_path, full_path in sorted(self.media_disk_files.items()):
            if rel_path.startswith("tl/") or "/tl/" in rel_path:
                continue
            base_fn = os.path.basename(rel_path)
            stem, _ = os.path.splitext(base_fn)

            clean_rel = rel_path
            clean_rel = clean_rel.removeprefix("game/")

            tokenized = clean_rel
            tokenized = tokenized.removeprefix("images/")
            tokenized_stem = os.path.splitext(tokenized)[0].replace("/", " ").replace("_", " ")

            is_used = (
                rel_path in self.used_asset_keys
                or clean_rel in self.used_asset_keys
                or base_fn in self.used_asset_keys
                or stem in self.used_asset_keys
                or tokenized_stem in self.used_asset_keys
            )

            if not is_used:
                diagnostics.append(
                    Diagnostic(
                        file_path=full_path,
                        line_number=1,
                        line_content=f"[file] {rel_path}",
                        code="RPY503",
                        message=f"Unused media asset '{rel_path}' is never referenced in scripts. Increases distribution size.",
                        severity="WARNING",
                    )
                )
        return diagnostics
