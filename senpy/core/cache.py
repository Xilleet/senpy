from __future__ import annotations

import hashlib
import os
import pickle
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from senpy.core.constants import SENPY_VERSION
from senpy.core.logging import get_logger

_logger = get_logger("cache")

# =============================================================================
# Cross-process lock
# =============================================================================
# When pre-commit hook and LSP server run simultaneously on the same
# project, both may try to save_manifest() at the same time. Without a
# lock, one process's write can clobber the other's, or a reader can
# see a half-written file (though os.replace mitigates the latter).
#
# The lock file (cache.lock) lives next to cache.pkl. On Unix we use
# fcntl.flock(LOCK_EX); on Windows msvcrt.locking(LK_NBLCK, 1).
# If the lock cannot be acquired within 5 seconds, the operation
# degrades gracefully: load returns None (cold rebuild), save is
# skipped (next run will persist).

try:
    import fcntl as _fcntl  # Unix only

    _HAS_FCNTL = True
except ImportError:
    _fcntl = None
    _HAS_FCNTL = False

try:
    import msvcrt as _msvcrt  # Windows only

    _HAS_MSVCRT = True
except ImportError:
    _msvcrt = None
    _HAS_MSVCRT = False

_LOCK_TIMEOUT = 5.0  # seconds to wait before degrading
_LOCK_RETRY_INTERVAL = 0.1  # seconds between lock attempts

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
    # Per-file `missing_defaults` snapshot (var_name → suggested default
    # value). Populated during `_visit_assign` (python_ast.py) on cache
    # miss, restored on Tier 2 cache hit so `generate_defaults_file()`
    # produces the same output on warm runs as on cold runs.
    missing_defaults: dict[str, str] = field(default_factory=dict)


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
    def __init__(
        self,
        project_path: str,
        enabled: bool = True,
        cache_dir: str | None = None,
    ):
        self.project_path = os.path.abspath(project_path)
        # cache_dir: explicit override (CLI --cache-dir) wins; otherwise
        # default to <project>/.senpy_cache. The override is useful for CI
        # with a shared cache between runs (e.g. actions/cache on a
        # custom path). Previously this was hardcoded and --cache-dir was
        # a dead flag (P1-5).
        if cache_dir:
            self.cache_dir = os.path.abspath(cache_dir)
        else:
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

    # ------------------------------------------------------------------
    # Cross-process lock
    # ------------------------------------------------------------------

    @property
    def _lock_path(self) -> str:
        """Path to the lock file (cache.lock next to cache.pkl)."""
        return os.path.join(self.cache_dir, "cache.lock")

    def _acquire_lock(self) -> object | None:
        """Acquire an exclusive cross-process lock on cache.lock.

        Returns a lock handle (file descriptor wrapper) if acquired,
        None if the lock could not be acquired within the timeout
        (graceful degradation: caller proceeds without cache).

        On Unix: fcntl.flock(LOCK_EX | LOCK_NB) with retry loop.
        On Windows: msvcrt.locking(LK_NBLCK, 1) with retry loop.
        On platforms with neither: returns None (no locking, legacy
        behavior — safe because os.replace is still atomic).
        """
        if not self.enabled:
            return None
        self.ensure_cache_dir()

        try:
            fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR)
        except OSError as e:
            _logger.debug("cache lock: cannot open %s: %s", self._lock_path, e)
            return None

        deadline = time.monotonic() + _LOCK_TIMEOUT
        while True:
            try:
                if _HAS_FCNTL:
                    _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                    return fd  # acquired on Unix
                elif _HAS_MSVCRT:
                    _msvcrt.locking(fd, _msvcrt.LK_NBLCK, 1)
                    return fd  # acquired on Windows
                else:
                    os.close(fd)
                    return None  # no locking primitive available
            except (OSError, PermissionError):
                # Lock is held by another process. Retry or degrade.
                if time.monotonic() >= deadline:
                    _logger.debug(
                        "cache lock: could not acquire %s within %.1fs — "
                        "degrading (cold rebuild or skip save)",
                        self._lock_path,
                        _LOCK_TIMEOUT,
                    )
                    try:  # noqa: SIM105
                        os.close(fd)
                    except OSError:
                        pass
                    return None
                time.sleep(_LOCK_RETRY_INTERVAL)

    def _release_lock(self, lock_handle: object | None) -> None:
        """Release the cross-process lock acquired by _acquire_lock."""
        if lock_handle is None:
            return
        fd = lock_handle  # it's an int file descriptor
        try:
            if _HAS_FCNTL:
                _fcntl.flock(fd, _fcntl.LOCK_UN)
            elif _HAS_MSVCRT:
                # Seek back to start and unlock 1 byte
                os.lseek(fd, 0, os.SEEK_SET)
                _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)
        except OSError:
            pass  # best-effort
        finally:
            try:  # noqa: SIM105
                os.close(fd)
            except OSError:
                pass

    def load_manifest(self) -> CacheManifest | None:
        """Loads the manifest from the cache with a version check.

        Acquires a cross-process lock (R-P0-8) to prevent reading a
        cache.pkl that is being written by another process. If the lock
        cannot be acquired within the timeout, returns None (cold rebuild).
        """
        if not self.enabled or not os.path.exists(self.manifest_path):
            return None
        lock = self._acquire_lock()
        if lock is None and self.enabled:
            _logger.debug("cache lock: load_manifest degraded — another process holds the lock")
            return None
        try:
            with open(self.manifest_path, "rb") as f:
                data = SafeCacheUnpickler(f).load()
            if isinstance(data, CacheManifest) and data.version == SENPY_VERSION:
                self.manifest = data
                return data
        except (OSError, pickle.PickleError, EOFError, AttributeError, ValueError) as e:
            _logger.debug(
                "failed to load cache manifest from %s: %s",
                self.manifest_path,
                e,
            )
        finally:
            self._release_lock(lock)
        return None

    def save_manifest(self, manifest: CacheManifest) -> None:
        """Atomically saves the manifest to a binary pickle.

        Acquires a cross-process lock (R-P0-8) to prevent concurrent
        writes from different processes (pre-commit hook + LSP server).
        If the lock cannot be acquired within the timeout, the save is
        skipped (next run will persist).

        Uses ``tempfile.mkstemp`` for a unique temp filename per call, so
        concurrent invocations on the same project cannot clobber each
        other's temp file before the atomic ``os.replace``.
        """
        if not self.enabled:
            return
        lock = self._acquire_lock()
        if lock is None and self.enabled:
            _logger.debug("cache lock: save_manifest skipped — another process holds the lock")
            return
        try:
            self.ensure_cache_dir()
            fd, tmp_path = tempfile.mkstemp(dir=self.cache_dir, prefix="cache.pkl.", suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as f:
                    pickle.dump(manifest, f, protocol=pickle.HIGHEST_PROTOCOL)
                os.replace(tmp_path, self.manifest_path)
            except BaseException:
                try:  # noqa: SIM105
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except (OSError, pickle.PickleError) as e:
            _logger.debug(
                "failed to save cache manifest to %s: %s",
                self.manifest_path,
                e,
            )
        finally:
            self._release_lock(lock)

    @staticmethod
    def compute_global_hash(analyzer: SenpyAnalyzer) -> str:
        """Compute a BLAKE2b hash of the project global state (labels, screens, signatures, variables).

        Used to detect when the global symbol table changed between
        runs (e.g. a label was added in file A, which means file B's
        `jump X` may now resolve differently). See compute_file_hash
        for the BLAKE2b rationale.

        The hash includes every symbol field that another file's
        diagnostics can depend on:
          - label: name, signature, has_return, outgoing_jumps
            (RPY306/309/706 depend on whether a label returns and
            where it jumps).
          - screen: name, signature.
          - variable: name, type_name, is_constant, is_character.
          - image: name, image_path, is_layered, attributes, body
            (cross-file layeredimage attribute lookups depend on these).
          - transform: name, signature (RPY706 unused-param depends on
            the declared parameter list).
          - registered_audio_channels.

        Note: filesystem-dependent data (AssetManager.valid_images,
        audio_dir_files, defined_audio_map target paths) is NOT part
        of this hash. A separate ``environment_fingerprint`` (see
        ``compute_environment_fingerprint`` below) covers asset
        add/delete scenarios.
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
            # has_return: RPY306 (call without return) and RPY309 (story
            # islands) depend on whether a label returns. Without this,
            # adding/removing `return` in file A would not invalidate file
            # B's cached diagnostics.
            hasher.update(str(lbl.has_return).encode("utf-8"))
            # outgoing_jumps: RPY302 (broken jump) and RPY309 (story
            # islands) depend on where a label jumps. Sorted for determinism.
            hasher.update(str(sorted(lbl.outgoing_jumps)).encode("utf-8"))
            # fall_through_to: RPY309 reachability uses this implicit edge
            # to model control flow between adjacent labels in a file.
            # Without hashing it, adding/removing a `return` between two
            # labels in file A (which toggles whether the first falls
            # through to the second) would not invalidate file B's cached
            # RPY309 diagnostics.
            hasher.update(str(lbl.fall_through_to).encode("utf-8"))

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
            # is_character: RPY105 (constant mutation) checks this flag —
            # a Character variable allows mutation, a plain constant does not.
            # Without hashing is_character, flipping it (e.g. Character →
            # plain value with the same type_name) would not invalidate the
            # cache. The docstring already claims this is hashed.
            hasher.update(str(var.is_character).encode("utf-8"))

        for img_name in sorted(analyzer.images.keys()):
            hasher.update(img_name.encode("utf-8"))
            img = analyzer.images[img_name]
            # image_path: LSP hover uses it to resolve the on-disk preview.
            # Without this, changing the path string would not invalidate
            # cached hover info.
            hasher.update((img.image_path or "").encode("utf-8"))
            # is_layered + attributes: AssetChecker uses
            # images[base_tag].attributes for layeredimage attribute
            # validation. Without these, cross-file layeredimage changes
            # would not invalidate the cache.
            hasher.update(str(img.is_layered).encode("utf-8"))
            hasher.update(str(sorted(img.attributes)).encode("utf-8"))
            # body: the full source of the image declaration. Captures
            # any structural change not covered by the fields above
            # (e.g. a layeredimage gaining a new `always` block without
            # a named attribute).
            hasher.update((img.body or "").encode("utf-8"))

        for trans_name in sorted(analyzer.transforms.keys()):
            hasher.update(trans_name.encode("utf-8"))
            trans = analyzer.transforms[trans_name]
            # signature: RPY706 (unused transform parameter) depends on
            # the declared parameter list. Without this, adding/removing
            # a parameter in file A would not invalidate file B's cached
            # diagnostics.
            if trans.signature:
                sig = trans.signature
                hasher.update(
                    str((sig.min_args, sig.max_args, sorted(sig.all_names))).encode("utf-8")
                )

        for chan in sorted(analyzer.registered_audio_channels):
            hasher.update(chan.encode("utf-8"))

        return hasher.hexdigest()

    @staticmethod
    def compute_environment_fingerprint(analyzer: SenpyAnalyzer) -> str:
        """Compute a BLAKE2b fingerprint of filesystem-dependent state.

        Covers the asset/audio state that the symbol hash
        (``compute_global_hash``) does NOT include — the on-disk file
        sets and audio alias target paths that ``AssetChecker`` and
        LSP hover depend on:

          - ``AssetManager.valid_images`` (built from ``os.walk`` over
            ``images/`` — changes when a ``.png`` is added/deleted).
          - ``AssetManager.known_assets`` (built from ``os.walk`` over
            the project — changes when any asset file is added/deleted).
          - ``AssetManager.audio_dir_files`` (built from ``os.walk``
            over ``audio/`` — changes when an ``.ogg`` is added/deleted).
          - ``defined_audio_map`` target paths (parsed from ``.rpy``
            ``define audio.X = "path"`` — the *target* path, not the
            alias name, which is already in the symbol hash).

        Without this fingerprint, a warm run after adding/removing a
        ``.png`` or ``.ogg`` file would serve stale ``RPY501``/``RPY502``/
        ``RPY503`` from the Tier-2 cache (the ``.rpy`` files are
        byte-identical, so the symbol hash is unchanged).

        The fingerprint hashes the AssetManager state (already built
        by ``_index_disk_files`` during ``analyzer.run()``) — no
        additional ``os.walk`` is performed.
        """
        hasher = hashlib.blake2b()

        # valid_images: set of tokenized image names (e.g. "bg town").
        # Changes when a .png is added/removed in images/.
        for img in sorted(analyzer.valid_images):
            hasher.update(img.encode("utf-8"))

        # known_assets: set of all on-disk asset relative paths.
        # Changes when any asset file (image, audio, video) is
        # added/removed anywhere in the project.
        for asset in sorted(analyzer.known_assets):
            hasher.update(asset.encode("utf-8"))

        # audio_dir_files: dict stem→relative_path for audio files.
        # Changes when an .ogg/.mp3/.wav is added/removed in audio/.
        for stem, rel_path in sorted(analyzer.audio_dir_files.items()):
            hasher.update(stem.encode("utf-8"))
            hasher.update(rel_path.encode("utf-8"))

        # defined_audio_map: dict alias→target_path, parsed from .rpy
        # ``define audio.X = "path"``. The alias name (X) is in the
        # symbol hash, but the target path is not — it's a
        # filesystem-dependent value. Changes when the user renames
        # an audio file and updates the alias target.
        for alias, target_path in sorted(analyzer.defined_audio_map.items()):
            hasher.update(alias.encode("utf-8"))
            hasher.update(target_path.encode("utf-8"))

        # Plugin execution flag: toggling `enable_plugins` in senpy.toml
        # must invalidate the Tier 2 cache, because cold run with plugins
        # off skips plugin rule check() calls (no plugin diagnostics) but
        # warm run with plugins on would serve the same cached diagnostics
        # (still no plugin diagnostics). Hashing the flag here forces a
        # Tier 2 miss when the user flips the setting.
        hasher.update(b"enable_plugins=")
        hasher.update(str(getattr(analyzer, "enable_plugins", False)).encode("utf-8"))

        return hasher.hexdigest()

    @staticmethod
    def compute_combined_hash(analyzer: SenpyAnalyzer) -> str:
        """Compute the combined global cache hash.

        Combines the symbol hash (``compute_global_hash`` — labels,
        screens, variables, images, transforms, audio channels) with
        the environment fingerprint (``compute_environment_fingerprint``
        — on-disk asset sets, audio alias target paths) into a single
        BLAKE2b hash. This is the hash stored in
        ``CacheManifest.global_symbol_hash`` and compared across runs
        to decide whether the Tier-2 cache is still valid.

        Old manifests (pre-B.2) store only the symbol hash without the
        environment fingerprint — they will mismatch on the next run
        (env fingerprint is now appended) and trigger a cache rebuild.
        """
        symbol_hash = CacheManager.compute_global_hash(analyzer)
        env_fp = CacheManager.compute_environment_fingerprint(analyzer)
        combined = hashlib.blake2b()
        combined.update(symbol_hash.encode("utf-8"))
        combined.update(env_fp.encode("utf-8"))
        return combined.hexdigest()
