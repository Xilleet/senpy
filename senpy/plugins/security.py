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
from datetime import UTC, datetime
from pathlib import Path

from senpy.core.exceptions import PluginError
from senpy.core.logging import get_logger

_logger = get_logger("plugins.security")

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

    # Prune audit_warnings entries for plugins no longer in the trust
    # list — keeps the store tidy if a plugin was untrusted by an older
    # Senpy that didn't clean up audit_warnings.
    trusted = set(data["plugins"])
    for orphan in list(set(data["audit_warnings"]) - trusted):
        data["audit_warnings"].pop(orphan, None)

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
    store = _read_trust_store()
    if plugin_name not in store["plugins"]:
        store["plugins"].append(plugin_name)
    # Update trusted_at timestamp (ISO 8601 UTC)
    store["trusted_at"][plugin_name] = datetime.now(UTC).isoformat()
    _write_trust_store(store)


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
    store = _read_trust_store()
    if plugin_name not in store["plugins"]:
        return False
    store["plugins"].remove(plugin_name)
    store["trusted_at"].pop(plugin_name, None)
    store.get("audit_warnings", {}).pop(plugin_name, None)
    _write_trust_store(store)
    return True


def get_trusted_plugins() -> list[str]:
    """Returns list of all trusted plugin names (sorted)."""
    store = _read_trust_store()
    return sorted(store.get("plugins", []))
