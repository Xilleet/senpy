from __future__ import annotations

import hashlib
import os
import pickle
import shutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from senpy.core.constants import SENPY_VERSION
from senpy.core.logging import get_logger

_logger = get_logger("cache")

# CachedFileEntry and CacheManifest are defined HERE (in cache.py), not in a
# separate cache_manifest.py. Reason: Python 3.14 changed dataclasses._is_type(),
# which reaches into sys.modules while decorating a @dataclass. If the dataclasses
# are in a separate module imported during __init__.py loading, Python 3.14
# crashes with AttributeError: 'NoneType' object has no attribute '__dict__'.
# Inlining into cache.py solves the problem — there is no separate module to import.
#
# Phase 1.6 (0.5.3) broke the analyzer ↔ cache cycle by extracting the dataclasses.
# In 0.6.1 we put them back, because the cycle is already broken via the
# DiagnosticSink Protocol (Phase 1.3) and a TYPE_CHECKING guard. The extraction is
# no longer needed.

if TYPE_CHECKING:
    from senpy.core.analyzer import SenpyAnalyzer
    from senpy.core.models import Diagnostic, FileScope


@dataclass(slots=True)
class CachedFileEntry:
    """Metadata of a single cached file (for the Tier 1 cache)."""

    mtime: float
    size: int
    lines_count: int
    scope: FileScope
    diagnostics: list[Diagnostic] = field(default_factory=list)
    used_assets: set[str] = field(default_factory=set)
    content_hash: str = ""
    collect_diagnostics: list[Diagnostic] = field(default_factory=list)
    # Per-file fixable/fixed counters. Stored on cache miss (the delta added
    # by analyzing this file) and restored on Tier 2 cache hit. Without these,
    # warm runs underreport fixable diagnostics and the CLI drops the
    # "[*] N fixable with the --fix option" footer.
    fixable_count: int = 0
    fixed_count: int = 0


@dataclass(slots=True)
class CacheManifest:
    """Full cache manifest: Senpy version + global symbol hash + all files."""

    version: str
    global_symbol_hash: str
    files: dict[str, CachedFileEntry] = field(default_factory=dict)


def compute_file_hash(file_path: str) -> str:
    """Compute a fast BLAKE2b hash of the file contents for cache invalidation.

    Why BLAKE2b (not MD5, despite MD5 being faster on tiny files):
    - Faster on modern CPUs for typical .rpy sizes (3-5x with SIMD).
    - Not flagged by enterprise security scanners as "weak crypto"
      (MD5 is, even for non-security use cases — this blocks
      adoption in corporate environments).
    - Modern standard (RFC 7693), recommended by NIST.

    The hash is used ONLY for cache invalidation (detect when a .rpy
    file changed between runs). It is NOT used for security — an
    attacker who can plant a collision in their own .rpy file gains
    nothing (the cache is per-project, not shared across users).

    Migration safety: the cache manifest carries a `version` field
    (= SENPY_VERSION). When Senpy is upgraded (e.g. 0.7.4 -> 0.7.5),
    `CacheManager.load_manifest()` rejects the old cache via
    `data.version == SENPY_VERSION` check, so the BLAKE2b switch is
    transparent — old MD5 hashes are simply ignored, the cache is
    rebuilt from scratch on the first 0.7.5 run.
    """
    try:
        with open(file_path, "rb") as f:
            return hashlib.blake2b(f.read()).hexdigest()
    except OSError:
        return ""


class SafeCacheUnpickler(pickle.Unpickler):
    """Unpickler with a module allowlist: cache.pkl comes from an untrusted source.

    The .senpy_cache folder lives INSIDE the Ren'Py project and travels with it
    (project sharing, downloads, third-party mods), so a plain pickle.load = RCE
    via __reduce__ in a planted file. Legitimate cache contents are only our
    dataclasses and primitives — any find_class outside the allowlist is enough
    to reject the file. A broken cache = None = a regular rebuild.
    """

    ALLOWED_MODULES = frozenset(
        {
            "senpy.cache",  # backward compat
            "senpy.cache_manifest",  # backward compat
            "senpy.core.cache",  # Phase 2: new path
            "senpy.core.cache_manifest",  # Phase 2: new path
            "senpy.models",  # backward compat
            "senpy.core.models",  # Phase 2: new path
            "senpy.symbols",  # backward compat
            "senpy.core.symbols",  # Phase 2: new path
            "senpy.signature",  # backward compat
            "senpy.core.signature",  # Phase 2: new path
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
        """Full cleanup of the cache folder."""
        if os.path.exists(self.cache_dir):
            shutil.rmtree(self.cache_dir, ignore_errors=True)
            return True
        return False

    def ensure_cache_dir(self) -> None:
        """Creates the cache directory and a protective .gitignore."""
        if not self.enabled:
            return
        os.makedirs(self.cache_dir, exist_ok=True)
        gitignore = os.path.join(self.cache_dir, ".gitignore")
        if not os.path.exists(gitignore):
            with open(gitignore, "w", encoding="utf-8") as f:
                f.write("*\n")

    def load_manifest(self) -> CacheManifest | None:
        """Loads the manifest from the cache with a version check."""
        if not self.enabled or not os.path.exists(self.manifest_path):
            return None
        try:
            with open(self.manifest_path, "rb") as f:
                data = SafeCacheUnpickler(f).load()
            if isinstance(data, CacheManifest) and data.version == SENPY_VERSION:
                self.manifest = data
                return data
        except (OSError, pickle.PickleError, EOFError, AttributeError, ValueError) as e:
            # log debug instead of silent suppress. Cache corruption
            # is recoverable (just rebuild), but tracking it helps spot bugs.
            _logger.debug(
                "failed to load cache manifest from %s: %s",
                self.manifest_path,
                e,
            )
        return None

    def save_manifest(self, manifest: CacheManifest) -> None:
        """Atomically saves the manifest to a binary pickle."""
        if not self.enabled:
            return
        try:
            self.ensure_cache_dir()
            tmp_path = self.manifest_path + ".tmp"
            with open(tmp_path, "wb") as f:
                pickle.dump(manifest, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp_path, self.manifest_path)
        except (OSError, pickle.PickleError) as e:
            # log debug instead of silent suppress. Save failure is
            # recoverable (next run rebuilds), but indicates disk issues.
            _logger.debug(
                "failed to save cache manifest to %s: %s",
                self.manifest_path,
                e,
            )

    @staticmethod
    def compute_global_hash(analyzer: SenpyAnalyzer) -> str:
        """Compute a BLAKE2b hash of the project global state (labels, screens, signatures, variables).

        Used to detect when the global symbol table changed between
        runs (e.g. a label was added in file A, which means file B's
        `jump X` may now resolve differently). See compute_file_hash
        for the BLAKE2b rationale.
        """
        hasher = hashlib.blake2b()
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
            if sym:
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
