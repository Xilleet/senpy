"""Plugin API version check + trust store.

api_version compatibility check.
trust-on-first-use security model.

Trust store location: ~/.senpy/trusted_plugins.json (or $SENPY_HOME/trusted_plugins.json)
Format:
    {
        "version": 1,
        "plugins": ["my-senpy-plugin", "another-plugin"],
        "trusted_at": {
            "my-senpy-plugin": "2026-10-30T12:00:00Z",
            "another-plugin": "2026-10-30T13:00:00Z"
        }
    }
"""
from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

# =============================================================================
# API version (unchanged from Заход 1)
# =============================================================================

PLUGIN_API_VERSION = "1.0"
_RE_API_VERSION = re.compile(r"^\d+\.\d+$")


class ApiVersionMismatchError(Exception):
    """Raised when plugin's api_version is incompatible with Senpy's."""

    def __init__(self, plugin_version: str, senpy_version: str):
        self.plugin_version = plugin_version
        self.senpy_version = senpy_version
        super().__init__(
            f"Plugin API version mismatch: plugin requires {plugin_version!r}, "
            f"but Senpy provides {senpy_version!r}. "
            f"Plugin may use APIs that don't exist or have changed. "
            f"Please update the plugin or use a compatible Senpy version."
        )


def check_api_version(plugin_api_version: str, *, raise_on_mismatch: bool = False) -> bool:
    """Check if plugin's api_version is compatible with Senpy's.

    See module docstring in Заход 1 for compatibility rules.
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
_TRUST_STORE_VERSION = 1


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


def _read_trust_store() -> dict:
    """Read trust store from disk. Returns empty structure if missing/corrupt.

    Never raises — corrupt JSON is treated as empty (fail-safe).
    """
    path = get_trust_store_path()
    if not os.path.exists(path):
        return {"version": _TRUST_STORE_VERSION, "plugins": [], "trusted_at": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # Validate structure
        if not isinstance(data, dict):
            return {"version": _TRUST_STORE_VERSION, "plugins": [], "trusted_at": {}}
        if "plugins" not in data or not isinstance(data["plugins"], list):
            data["plugins"] = []
        if "trusted_at" not in data or not isinstance(data["trusted_at"], dict):
            data["trusted_at"] = {}
        return data
    except (json.JSONDecodeError, OSError, ValueError):
        # Corrupt JSON → treat as empty
        return {"version": _TRUST_STORE_VERSION, "plugins": [], "trusted_at": {}}


def _write_trust_store(data: dict) -> None:
    """Write trust store to disk (atomic-ish: creates dir first)."""
    path = get_trust_store_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


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
    _write_trust_store(store)
    return True


def get_trusted_plugins() -> list[str]:
    """Returns list of all trusted plugin names (sorted)."""
    store = _read_trust_store()
    return sorted(store.get("plugins", []))
