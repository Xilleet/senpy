"""Plugin API version check + trust store.

api_version compatibility check.
trust-on-first-use security model.

Trust store location: ~/.senpy/trusted_plugins.json (or $SENPY_HOME/trusted_plugins.json)

Schema (v2, since R-P0-2):
    {
        "version": 2,
        "plugins": ["my-senpy-plugin", "another-plugin"],
        "trusted_at": {
            "my-senpy-plugin": "2026-10-30T12:00:00Z",
            "another-plugin": "2026-10-30T13:00:00Z"
        },
        "audit_warnings": {
            "my-senpy-plugin": ["uses os module at top level"],
            "another-plugin": []
        }
    }

The ``audit_warnings`` field was added in R-P0-2 (schema v2) as
preparation for R-P0-1 (plugin import-time audit). It maps plugin name
→ list of audit warning strings. R-P0-1 will populate it during the
import-time audit; for now (R-P0-2 only) it is always an empty dict on
fresh/migrated stores.

Schema versioning:
- v1 (Senpy ≤ 0.8.4): no ``audit_warnings`` field, ``version: 1``.
- v2 (Senpy ≥ 0.9.0): adds ``audit_warnings`` dict, ``version: 2``.

``_read_trust_store`` migrates v1 stores to v2 on read (in-place field
addition, no trust loss). Future versions (v3+) will follow the same
additive migration pattern.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

from senpy.core.exceptions import PluginError
from senpy.core.logging import get_logger

_logger = get_logger("plugins.security")

# =============================================================================
# Cross-process lock for trust store read-modify-write
# =============================================================================
# Same pattern as ``senpy/core/cache.py`` — when pre-commit and LSP server
# run simultaneously on the same project (or two CLI invocations), both may
# try to ``trust_plugin`` / ``untrust_plugin`` / ``store_audit_warnings`` at
# the same time. Without a lock around the read-modify-write cycle, one
# process's write clobbers the other's grant (data loss: P1 reads {A},
# P2 reads {A}, P1 writes {A,B}, P2 writes {A,C} → B lost).
#
# The lock file (trusted_plugins.lock) lives next to trusted_plugins.json.
# On Unix we use ``fcntl.flock(LOCK_EX)``; on Windows ``msvcrt.locking``.
# If the lock cannot be acquired within 5 seconds, the operation degrades
# gracefully: the RMW proceeds without locking (same as before this
# fix — rare concurrent trust operations may still lose grants, but a
# single trust operation never blocks indefinitely).

_fcntl: ModuleType | None = None
try:
    import fcntl as _fcntl_mod  # Unix only

    _fcntl = _fcntl_mod
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

_msvcrt: ModuleType | None = None
try:
    import msvcrt as _msvcrt_mod  # Windows only

    _msvcrt = _msvcrt_mod
    _HAS_MSVCRT = True
except ImportError:
    _HAS_MSVCRT = False

_TRUST_LOCK_TIMEOUT = 5.0  # seconds to wait before degrading
_TRUST_LOCK_RETRY_INTERVAL = 0.1  # seconds between lock attempts

# =============================================================================
# API version (unchanged from Stage 1)
# =============================================================================

PLUGIN_API_VERSION = "1.0"
_RE_API_VERSION = re.compile(r"^\d+\.\d+$")


class ApiVersionMismatchError(PluginError):
    """Raised when plugin's api_version is incompatible with Senpy's.

    This allows callers to catch it via `except PluginError:` or `except SenpyError:`.
    """

    def __init__(self, plugin_version: str, senpy_version: str):
        self.plugin_version = plugin_version
        self.senpy_version = senpy_version
        message = (
            f"Plugin API version mismatch: plugin requires {plugin_version!r}, "
            f"but Senpy provides {senpy_version!r}. "
            f"Plugin may use APIs that don't exist or have changed. "
            f"Please update the plugin or use a compatible Senpy version."
        )
        # PluginError.__init__ takes (message, cause=None); we don't have a
        # cause here, just pass message.
        super().__init__(message)


def check_api_version(plugin_api_version: str, *, raise_on_mismatch: bool = False) -> bool:
    """Check if plugin's api_version is compatible with Senpy's.

    See module docstring in Stage 1 for compatibility rules.
    """
    if not _RE_API_VERSION.match(plugin_api_version):
        if raise_on_mismatch:
            raise ApiVersionMismatchError(plugin_api_version, PLUGIN_API_VERSION)
        return False

    plugin_major, plugin_minor = (int(x) for x in plugin_api_version.split("."))
    senpy_major, senpy_minor = (int(x) for x in PLUGIN_API_VERSION.split("."))

    if plugin_major != senpy_major:
        if raise_on_mismatch:
            raise ApiVersionMismatchError(plugin_api_version, PLUGIN_API_VERSION)
        return False

    if plugin_minor > senpy_minor:
        if raise_on_mismatch:
            raise ApiVersionMismatchError(plugin_api_version, PLUGIN_API_VERSION)
        return False

    return True


# =============================================================================
# Trust store
# =============================================================================

_TRUST_STORE_FILENAME = "trusted_plugins.json"
_TRUST_STORE_VERSION = 2


def get_trust_store_path() -> str:
    """Returns path to trust store JSON file.

    Location priority:
        1. $SENPY_HOME/trusted_plugins.json (if SENPY_HOME env var set)
        2. ~/.senpy/trusted_plugins.json (default, user home)

    The directory is created if it doesn't exist (lazy, on first write).
    """
    senpy_home = os.environ.get("SENPY_HOME")
    if senpy_home:
        base = Path(senpy_home)
    else:
        base = Path.home() / ".senpy"
    return str(base / _TRUST_STORE_FILENAME)


def _empty_trust_store() -> dict:
    """Return a fresh empty v2 trust store structure."""
    return {
        "version": _TRUST_STORE_VERSION,
        "plugins": [],
        "trusted_at": {},
        "audit_warnings": {},
    }


def _migrate_trust_store(data: dict) -> dict:
    """Migrate a trust store dict to the current schema version.

    Additive migration: missing fields are added with empty defaults,
    version is normalized to ``_TRUST_STORE_VERSION``, unknown fields
    are dropped. Trusted plugins and their ``trusted_at`` entries are
    preserved across migrations — users never see the ``[y/N]`` prompt
    again for plugins they already trusted.

    A INFO log is emitted when the on-disk version differs from the
    current schema version, so users running with ``--verbose`` can see
    that a migration happened.
    """
    on_disk_version = data.get("version", 1)
    if on_disk_version != _TRUST_STORE_VERSION:
        _logger.info(
            "Migrating trust store schema v%s → v%s (additive: trusted "
            "plugins preserved, missing fields added with empty defaults).",
            on_disk_version,
            _TRUST_STORE_VERSION,
        )

    # Normalize version to current.
    data["version"] = _TRUST_STORE_VERSION

    # Validate / additively repair known fields.
    if not isinstance(data.get("plugins"), list):
        data["plugins"] = []
    if not isinstance(data.get("trusted_at"), dict):
        data["trusted_at"] = {}
    if not isinstance(data.get("audit_warnings"), dict):
        data["audit_warnings"] = {}

    # Drop unknown fields (forward-compat: a future v3 store read by v2
    # Senpy keeps only the fields it knows about).
    known_keys = {"version", "plugins", "trusted_at", "audit_warnings"}
    for unknown in list(set(data) - known_keys):
        data.pop(unknown, None)

    # audit_warnings are stored BEFORE the trust prompt (the
    # plugin is not yet trusted when the audit runs). Do NOT prune them
    # here — that would delete the warnings before the user sees them.
    # untrust_plugin() already cleans up audit_warnings when a plugin is
    # explicitly untrusted.

    return data


def _read_trust_store() -> dict:
    """Read trust store from disk. Returns empty structure if missing/corrupt.

    Never raises — corrupt JSON is treated as empty (fail-safe).
    Migrates older schema versions (v1) to the current version (v2) on
    read, additively — trusted plugins are preserved.
    """
    path = get_trust_store_path()
    if not os.path.exists(path):
        return _empty_trust_store()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty_trust_store()
        return _migrate_trust_store(data)
    except (json.JSONDecodeError, OSError, ValueError):
        # Corrupt JSON → treat as empty
        return _empty_trust_store()


def _write_trust_store(data: dict) -> None:
    """Write trust store to disk atomically.

    Writes the new content to a sibling temp file first, then ``os.replace``s
    it onto the real path. ``os.replace`` is atomic on POSIX and Windows, so
    a crash during ``json.dump`` cannot leave a partially-written trust
    store: either the previous content survives intact, or the new content
    fully replaces it. The temp file is cleaned up if the rename fails.

    Uses ``tempfile.mkstemp`` for a unique temp filename per call, so
    concurrent invocations cannot clobber each other's temp file before
    the atomic ``os.replace``. Previously used a fixed
    ``trusted_plugins.json.tmp`` name, which under concurrent writes
    produced interleaved JSON bytes (self-healing via ``_read_trust_store``
    catching the bad JSON, but a one-time empty trust store was the
    observable cost).
    """
    path = get_trust_store_path()
    store_dir = os.path.dirname(path)
    os.makedirs(store_dir, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=store_dir, prefix="trusted_plugins.json.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except BaseException:
        # Clean up the temp file if anything went wrong (write error, rename
        # failure, KeyboardInterrupt, ...). The previously persisted trust
        # store at ``path`` is left untouched because os.replace has not
        # happened yet.
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def _trust_lock_path() -> str:
    """Path to the lock file (``trusted_plugins.lock`` next to the JSON)."""
    json_path = get_trust_store_path()
    return json_path + ".lock"


def _acquire_trust_lock() -> int | None:
    """Acquire an exclusive cross-process lock for trust store RMW.

    Returns a file descriptor if acquired, ``None`` if the lock could not
    be acquired within ``_TRUST_LOCK_TIMEOUT`` seconds (graceful
    degradation: caller proceeds without locking — same behaviour as
    before this lock was added, rare concurrent trust operations may
    still lose grants).

    Pattern mirrors ``CacheManager._acquire_lock`` in ``senpy/core/cache.py``.
    """
    lock_path = _trust_lock_path()
    store_dir = os.path.dirname(lock_path)
    if store_dir:
        os.makedirs(store_dir, exist_ok=True)

    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    except OSError as e:
        _logger.debug("trust lock: cannot open %s: %s", lock_path, e)
        return None

    deadline = time.monotonic() + _TRUST_LOCK_TIMEOUT
    while True:
        try:
            if _HAS_FCNTL:
                assert _fcntl is not None
                _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                return fd  # acquired on Unix
            elif _HAS_MSVCRT:
                # msvcrt.locking / LK_NBLCK / LK_UNLCK are Windows-only;
                # on Unix mypy cannot see them. Runtime is guarded by
                # ``_HAS_MSVCRT`` so the call is never reached on Linux.
                assert _msvcrt is not None
                _msvcrt.locking(fd, _msvcrt.LK_NBLCK, 1)
                return fd  # acquired on Windows
            else:
                os.close(fd)
                return None  # no locking primitive available
        except (OSError, PermissionError):
            # Lock is held by another process. Retry or degrade.
            if time.monotonic() >= deadline:
                _logger.debug(
                    "trust lock: could not acquire %s within %.1fs — "
                    "degrading (RMW proceeds without lock, concurrent "
                    "trust operations may still lose grants)",
                    lock_path,
                    _TRUST_LOCK_TIMEOUT,
                )
                try:  # noqa: SIM105
                    os.close(fd)
                except OSError:
                    pass
                return None
            time.sleep(_TRUST_LOCK_RETRY_INTERVAL)


def _release_trust_lock(lock_handle: int | None) -> None:
    """Release the cross-process lock acquired by ``_acquire_trust_lock``."""
    if lock_handle is None:
        return
    fd = lock_handle  # int file descriptor
    try:
        if _HAS_FCNTL:
            assert _fcntl is not None
            _fcntl.flock(fd, _fcntl.LOCK_UN)
        elif _HAS_MSVCRT:
            # Seek back to start and unlock 1 byte.
            assert _msvcrt is not None
            os.lseek(fd, 0, os.SEEK_SET)
            _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)
    except OSError:
        pass  # best-effort
    finally:
        try:  # noqa: SIM105
            os.close(fd)
        except OSError:
            pass


@contextlib.contextmanager
def _with_trust_store_lock():
    """Context manager that acquires the trust store lock for the duration
    of a read-modify-write cycle.

    Usage::

        with _with_trust_store_lock():
            store = _read_trust_store()
            store["plugins"].append(name)
            _write_trust_store(store)

    The lock is best-effort: if it cannot be acquired within
    ``_TRUST_LOCK_TIMEOUT`` seconds, the RMW proceeds without locking (same
    behaviour as before this lock was added — better to proceed than to
    block the CLI indefinitely).
    """
    lock_handle = _acquire_trust_lock()
    try:
        yield
    finally:
        _release_trust_lock(lock_handle)


def _modify_trust_store(mutator):
    """Run ``mutator(store)`` inside the trust store lock, then persist.

    ``mutator`` receives the current store dict and may mutate it in place.
    The result is written back atomically. The whole RMW cycle is guarded
    by ``_with_trust_store_lock()`` so concurrent calls (LSP + CLI, or two
    parallel CLI invocations) cannot lose grants.

    This is the canonical entry point for any trust store mutation —
    ``trust_plugin`` / ``untrust_plugin`` / ``store_audit_warnings`` all
    delegate to it.
    """
    with _with_trust_store_lock():
        store = _read_trust_store()
        mutator(store)
        _write_trust_store(store)


def is_plugin_trusted(plugin_name: str) -> bool:
    """Check if plugin is in trust store (previously trusted by user).

    Args:
        plugin_name: Name of the plugin (matches entry_point name, e.g. "my-senpy-plugin")

    Returns:
        True if plugin is trusted, False otherwise.
        Never raises — corrupt/missing trust store → False.
    """
    store = _read_trust_store()
    return plugin_name in store.get("plugins", [])


def trust_plugin(plugin_name: str) -> None:
    """Add plugin to trust store. Persists to disk immediately.

    Args:
        plugin_name: Name of the plugin to trust.
    """

    def _mutator(store: dict) -> None:
        if plugin_name not in store["plugins"]:
            store["plugins"].append(plugin_name)
        # Update trusted_at timestamp (ISO 8601 UTC)
        store["trusted_at"][plugin_name] = datetime.now(UTC).isoformat()

    _modify_trust_store(_mutator)


def untrust_plugin(plugin_name: str) -> bool:
    """Remove plugin from trust store. Persists to disk.

    Also removes the plugin's ``audit_warnings`` entry (if any) so stale
    warnings don't accumulate for untrusted plugins and resurface if the
    user re-trusts the plugin later.

    Args:
        plugin_name: Name of the plugin to untrust.

    Returns:
        True if plugin was trusted and is now removed, False if it wasn't trusted.
    """
    # Read once outside the lock to decide whether to do anything at all.
    # The lock-protected RMW below re-reads and mutates — there's a small
    # race window between this check and the lock acquisition, but it's
    # benign: if the plugin is untrusted concurrently between the check and
    # the lock, the inner ``if plugin_name not in store["plugins"]`` returns
    # False (idempotent).
    if not is_plugin_trusted(plugin_name):
        return False

    def _mutator(store: dict) -> None:
        # Re-check inside the lock — another caller may have untrusted
        # between our outer check and the lock acquisition.
        if plugin_name not in store["plugins"]:
            return
        store["plugins"].remove(plugin_name)
        store["trusted_at"].pop(plugin_name, None)
        store.get("audit_warnings", {}).pop(plugin_name, None)

    _modify_trust_store(_mutator)
    return True


def get_trusted_plugins() -> list[str]:
    """Returns list of all trusted plugin names (sorted)."""
    store = _read_trust_store()
    return sorted(store.get("plugins", []))


# =============================================================================
# Audit warnings
# =============================================================================


def store_audit_warnings(plugin_name: str, warnings: list[str]) -> None:
    """Store audit warnings for a plugin in the trust store.

    Called by ``load_plugin()`` after running the AST-based audit
    (``senpy.plugins.audit``) but before the trust prompt. The warnings
    are read by ``_default_trust_callback`` and shown to the user.

    Persists to disk immediately (same pattern as trust_plugin/untrust_plugin).
    Overwrites any existing warnings for this plugin.
    """

    def _mutator(store: dict) -> None:
        store.setdefault("audit_warnings", {})[plugin_name] = warnings

    _modify_trust_store(_mutator)


def get_audit_warnings(plugin_name: str) -> list[str]:
    """Get audit warnings for a plugin from the trust store.

    Returns an empty list if no warnings are stored (plugin was not
    audited, or audit found no issues).
    """
    store = _read_trust_store()
    return store.get("audit_warnings", {}).get(plugin_name, [])
