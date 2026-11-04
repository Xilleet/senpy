from __future__ import annotations

import os
import pickle
import zlib
from typing import ClassVar

from senpy.core.constants import (
    AUDIO_EXTENSIONS,
    BUILTIN_COLORS,
    IGNORED_DIRS,
    IMAGE_EXTENSIONS,
    MEDIA_EXTENSIONS,
    VIDEO_EXTENSIONS,
)
from senpy.core.logging import get_logger
from senpy.core.models import Diagnostic
from senpy.domain.rpa import safe_load_rpa_index

_logger = get_logger("domain.assets")

# Senpy's own configuration / output artifacts. These files are
# NOT game assets and must not be classified as `unused_assets` (would
# produce confusing false positives like "senpy.toml is an unused asset"
# on every project).
#
# Lowercased basenames — matched case-insensitively against the file
# basename in AssetManager.index().
SENPY_OWN_FILES: frozenset[str] = frozenset(
    {
        "senpy.toml",  # Senpy project config
        ".senpyignore",  # Senpy ignore-list (gitignore-style)
        ".senpy-cache",  # Legacy name (rare)
        "report.json",  # senpy inspect / lint output
        "report.txt",  # senpy inspect / lint output (text)
        "test_report.json",  # pytest artifact (conftest.py)
        "test_report.txt",  # pytest artifact (conftest.py)
    }
)

# File extensions that are NEVER game assets. Files with these
# extensions are auto-excluded from `unused_assets` even without a
# `.senpy-ignore` file.
#
# Rationale: when running `senpy inspect` on a real mod (e.g. DDLC:
# Blue Skies), ~90% of the ~500 "unused assets" were .rpyc/.rpa/.md/
# .txt/.psd files — build artifacts, documentation, archives, and
# Photoshop source files. Including them as "unused assets" is
# confusing noise that drowns out the real signal (~50 actually
# unused sprites/audio).
#
# Ren'Py loads assets from `game/` by extension: .png/.jpg/.webp/.ogg/
# .wav/.mp3/.mp4/.webm. Everything else is either a build artifact
# (.rpyc bytecode, .rpa archive), a source file (.rpy), documentation
# (.md/.txt), a binary (.exe/.sh/.app), or a design source (.psd).
# None of these are "unused game assets" in the RPY503 sense.
#
# If a user has a legitimate game file with one of these extensions
# (very unlikely — Ren'Py wouldn't load it), they can still reference
# it in code and it will be tracked via `used_asset_keys`.
NON_ASSET_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Ren'Py build artifacts (auto-generated, not user-authored assets)
        ".rpyc",  # Compiled Ren'Py bytecode
        ".rpyb",  # Compiled Ren'Py bytecode (older format)
        ".rpymc",  # Compiled Ren'Py module bytecode
        ".rpa",  # Ren'Py archive (Ren'Py loads contents at runtime), but this is temporary.
        ".rpy",  # Ren'Py source (not an asset, it's code)
        ".rpym",  # Ren'Py module source
        # Documentation and notes
        ".md",  # Markdown documentation
        ".txt",  # Plain text notes
        ".rst",  # reStructuredText documentation
        # Archives (Ren'Py doesn't load these directly; mods unpack them)
        ".zip",  # ZIP archive (mods may unpack at first run)
        ".7z",  # 7-Zip archive
        ".tar",  # Tar archive
        ".gz",  # Gzip archive
        # Binaries and launchers
        ".exe",  # Windows executable
        ".sh",  # Shell script
        ".dll",  # shared libraries
        ".so",  # shared libraries
        ".dylib",  # shared libraries
        ".bat",  # Windows batch script
        ".cmd",  # Windows command script
        # Design sources
        ".psd",  # Photoshop source
        ".xcf",  # GIMP source
        ".ai",  # Illustrator source
        # Senpy / Python
        ".py",  # Python source
        ".pyc",  # Python bytecode
        ".toml",  # TOML config
        ".json",  # JSON (config or output)
        ".yaml",  # YAML config
        ".yml",  # YAML config
        ".spec",  # PyInstaller spec
    }
)


def find_orphaned_rpyc(project_path: str) -> list[str]:
    """Finds compiled .rpyc files that have no corresponding .rpy source."""
    orphans = []
    for root, dirs, filenames in os.walk(project_path, followlinks=False):
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
        # Name -> disk path maps for hover preview.
        #   image_name_to_path: Ren'Py image-name token (e.g. "eileen happy")
        #                       -> absolute disk path of the underlying file.
        #                       Built from images/* auto-discovery (mirrors
        #                       Ren'Py runtime namespacing) plus lowercased
        #                       basename for files outside images/.
        #   audio_name_to_path: stem (e.g. "bgm_calm") -> absolute disk path.
        #                       Covers both audio/* files and define audio.X
        #                       targets that resolve to a file on disk.
        self.image_name_to_path: dict[str, str] = {}
        self.audio_name_to_path: dict[str, str] = {}
        self.used_asset_keys: set[str] = set()

    def index(self) -> None:
        """Scans the project directory and RPA archives, indexing all media files."""
        self._reset_asset_state()

        if self.project_path in self._asset_cache:
            cached_assets, cached_images = self._asset_cache[self.project_path]
            self.known_assets = set(cached_assets)
            self.valid_images = set(cached_images)

        self._index_disk_files()
        self._index_valid_images()

        self._asset_cache[self.project_path] = (set(self.known_assets), set(self.valid_images))

    def _reset_asset_state(self) -> None:
        """Clear all asset indexes before re-indexing."""
        self.known_assets.clear()
        self.valid_images = set(BUILTIN_COLORS)
        self.media_disk_files.clear()
        self.audio_dir_files.clear()
        self.image_name_to_path.clear()
        self.audio_name_to_path.clear()
        self.used_asset_keys.clear()

    def _index_disk_files(self) -> None:
        """Walk the project directory, registering disk files and RPA archives.

        Populates `known_assets`, `media_disk_files`, `audio_dir_files`,
        `image_name_to_path`, `audio_name_to_path`. Skips Senpy-own files
        and non-asset extensions.
        """
        for root, dirs, filenames in os.walk(self.project_path, followlinks=False):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for f in filenames:
                # Skip Senpy's own configuration / output artifacts.
                # These are NOT game assets — they are Senpy's own files
                # (config, ignore-list, test/inspection reports). Including
                # them in `unused_assets` produces confusing false positives
                # (e.g. "senpy.toml is an unused asset" on every project).
                if f.lower() in SENPY_OWN_FILES:
                    continue
                # Skip files with non-asset extensions (.rpyc, .rpa, .md,
                # .txt, .psd, .exe, .sh, .zip, etc.). These are build
                # artifacts, documentation, archives, or design sources —
                # NOT game assets. See NON_ASSET_EXTENSIONS docstring for
                # the full rationale.
                _, ext = os.path.splitext(f.lower())
                if ext in NON_ASSET_EXTENSIONS:
                    continue
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
                        # Audio hover resolves by stem (e.g. "play music
                        # bgm_calm" → key "bgm_calm"). Last writer wins is fine:
                        # ambiguity in Ren'Py projects is rare and the hover
                        # just needs to display *some* file.
                        self.audio_name_to_path.setdefault(stem, full_path)

                    # Index image (and video) files for hover. We
                    # register keys for both the tokenized "namespaced" name
                    # (images/foo/bar.png → "foo bar") and the bare basename,
                    # mirroring Ren'Py runtime auto-discovery. Outside images/
                    # we register only the basename. Video files are included
                    # because Ren'Py treats `image intro = Movie("intro.mp4")`
                    # + `show intro` the same way as static images.
                    if ext in IMAGE_EXTENSIONS or ext in VIDEO_EXTENSIONS:
                        self._register_image_for_hover(clean_rel, full_path)

                if f.lower().endswith(".rpa"):
                    self._read_rpa_index(full_path)

    def _index_valid_images(self) -> None:
        """Populate `valid_images` with tokenized names from `known_assets`.

        Strict parsing applies only to the official images/ standard:
        `images/foo/bar.png` → "foo bar" + "bar". Other assets are
        registered as-is by `_index_disk_files`.
        """
        for asset in self.known_assets:
            base, ext = os.path.splitext(asset)

            # Keep strict parsing only for the official images/ standard
            if ext.lower() in (".png", ".webp", ".jpg", ".jpeg"):
                clean_name = base.replace("\\", "/").lower()
                clean_name = clean_name.removeprefix("game/")
                if clean_name.startswith("images/"):
                    clean_name = clean_name.removeprefix("images/")
                    tokenized = clean_name.replace("/", " ").replace("_", " ")
                    self.valid_images.add(tokenized)
                    self.valid_images.add(os.path.basename(clean_name))

    def _register_image_for_hover(self, clean_rel: str, full_path: str) -> None:
        """Register *full_path* under one or more Ren'Py image-name keys.

        Mirrors Ren'Py's image auto-discovery: files inside ``images/`` are
        also reachable by their tokenized path (``images/eileen/happy.png``
        → key ``"eileen happy"``); files elsewhere are only reachable by
        their bare basename. We register both the spaced and underscored
        variants of each key, since Ren'Py script may use either form.
        """
        # Strip extension, lowercase for case-insensitive lookup.
        stem_rel = os.path.splitext(clean_rel)[0]
        basename = os.path.basename(stem_rel)

        if stem_rel.startswith("images/"):
            tail = stem_rel.removeprefix("images/")
            spaced = tail.replace("/", " ").replace("_", " ").strip()
            if spaced:
                self.image_name_to_path.setdefault(spaced, full_path)
                self.image_name_to_path.setdefault(spaced.replace(" ", "_"), full_path)
        # Always register the bare basename too (covers files outside
        # images/ and the common Ren'Py pattern `image bg = "bg.png"`
        # where the script references the basename directly).
        if basename:
            self.image_name_to_path.setdefault(basename, full_path)
            self.image_name_to_path.setdefault(basename.replace("_", " "), full_path)

    def resolve_image_path(self, name: str) -> str | None:
        """Resolve a Ren'Py image reference (e.g. ``"eileen happy"``) to an
        absolute filesystem path, or None if no matching file is on disk.

        Tries in order: exact key, lowercased key, underscore↔space variants.
        """
        if not name:
            return None
        candidates = [name, name.lower(), name.replace(" ", "_"), name.replace("_", " ")]
        for c in candidates:
            hit = self.image_name_to_path.get(c)
            if hit and os.path.exists(hit):
                return hit
        return None

    def resolve_audio_path(self, name: str) -> str | None:
        """Resolve an audio stem (e.g. ``"bgm_calm"``) to an absolute
        filesystem path, or None if not on disk."""
        if not name:
            return None
        hit = self.audio_name_to_path.get(name) or self.audio_name_to_path.get(name.lower())
        if hit and os.path.exists(hit):
            return hit
        return None

    def is_video_file(self, path: str) -> bool:
        """Return True if *path* has a video extension. Used by hover to
        switch from inline image preview to a "Play in default app" link
        (VS Code's image viewer cannot decode WebM/MP4/etc.)."""
        return os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS

    def register_audio_alias(self, alias: str, target_file: str) -> None:
        """Register a `define audio.ALIAS = "target_file"` alias.

        Resolves *target_file* (relative to game/) to an absolute disk path
        via media_disk_files and stores it under the alias key so audio hover
        can look it up by alias name. Called by the analyzer at parse time.
        """
        if not alias or not target_file:
            return
        # Try a few candidate keys matching how media_disk_files is keyed
        # (rel_path with forward slashes, lowercased, optionally game/-prefixed).
        for candidate in (
            target_file,
            target_file.removeprefix("game/"),
            f"game/{target_file.removeprefix('game/')}",
            os.path.basename(target_file),
        ):
            hit = self.media_disk_files.get(candidate)
            if hit and os.path.exists(hit):
                self.audio_name_to_path[alias] = hit
                return
        # File not on disk yet (e.g. exists only inside an .rpa, or doesn't
        # exist at all). Skip silently — hover just won't resolve.

    def _read_rpa_index(self, rpa_path: str) -> None:
        try:
            with open(rpa_path, "rb") as f:
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
        except (OSError, zlib.error, pickle.UnpicklingError, ValueError) as e:
            # log debug instead of silent suppress. RPA index read
            # failure is non-critical (assets from this archive just not
            # registered); but tracking it helps spot corrupt .rpa files.
            _logger.debug("failed to read RPA index %s: %s", rpa_path, e)

    def mark_used(self, asset_ref: str) -> None:
        """Registers usage of an asset in the code."""
        ref_norm = asset_ref.replace("\\", "/").lower().strip()
        self.used_asset_keys.add(ref_norm)
        self.used_asset_keys.add(os.path.basename(ref_norm))

    def check_unused(self) -> list[Diagnostic]:
        """RPY503: Finds media files on disk that are not referenced in the scenario."""
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
