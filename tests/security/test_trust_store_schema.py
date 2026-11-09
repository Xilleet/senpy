"""Regression tests for trust store schema versioning.

The trust store at ``~/.senpy/trusted_plugins.json`` previously had no
schema versioning: ``_read_trust_store`` returned whatever was on disk
(after basic structural validation) and ``_TRUST_STORE_VERSION`` was
a constant that was never compared against the on-disk ``version`` field.
Any future change to the format (e.g. adding ``audit_warnings`` for
R-P0-1 plugin import-time audit) would silently "zero out" trust for
every previously-trusted plugin — users would see the ``[y/N]`` prompt
again for each plugin, even though they had already trusted it.

After:
- ``_TRUST_STORE_VERSION`` is bumped to 2.
- The schema gains a new top-level field ``audit_warnings`` — a dict
  mapping ``plugin_name`` → ``list[str]`` of audit warning strings
  (populated by R-P0-1's plugin import-time audit, when that lands).
  This is an ADDITIVE change: existing v1 stores are migrated on read
  by adding an empty ``audit_warnings`` dict, no user action required.
- ``_read_trust_store`` checks ``data["version"]`` against
  ``_TRUST_STORE_VERSION``. On mismatch (e.g. an old v1 store on disk
  after Senpy upgrades to v2), the store is migrated in-place: version
  field bumped, missing fields added with empty defaults. A INFO log
  records the migration so users can see what happened.
- Corrupt JSON still returns a fresh empty v2 store (existing
  fail-safe behavior, preserved).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from senpy.plugins import security

# =============================================================================
# Schema version
# =============================================================================


class TestTrustStoreVersion:
    """``_TRUST_STORE_VERSION`` must be bumped to 2 (schema with
    ``audit_warnings`` field)."""

    def test_version_is_2(self) -> None:
        assert security._TRUST_STORE_VERSION == 2, (
            "Trust store version must be 2 after R-P0-2 — the schema "
            "gained the `audit_warnings` field. If this fails, the bump "
            "was reverted or never applied."
        )


# =============================================================================
# Fresh trust store (no file on disk)
# =============================================================================


class TestFreshTrustStore:
    """A missing trust store file returns a fresh v2 structure."""

    def test_missing_file_returns_v2_structure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        # Reimport to pick up the env var.
        import importlib

        importlib.reload(security)

        data = security._read_trust_store()
        assert data["version"] == 2
        assert data["plugins"] == []
        assert data["trusted_at"] == {}
        assert data.get("audit_warnings") == {}, (
            "Fresh v2 trust store must include an empty `audit_warnings` "
            "dict — this is the field R-P0-1 will populate."
        )


# =============================================================================
# Migration: v1 store on disk → v2 in memory
# =============================================================================


class TestV1ToV2Migration:
    """A v1 trust store (without ``audit_warnings``) is migrated to v2
    on read, in-place. Trusted plugins are preserved — users do NOT
    see the ``[y/N]`` prompt again."""

    def _write_v1_store(self, path: Path, plugins: list[str]) -> None:
        """Write a v1 trust store to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        v1_data = {
            "version": 1,
            "plugins": plugins,
            "trusted_at": dict.fromkeys(plugins, "2026-10-30T12:00:00Z"),
        }
        path.write_text(json.dumps(v1_data), encoding="utf-8")

    def test_v1_store_migrated_to_v2_on_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        import importlib

        importlib.reload(security)

        store_path = Path(security.get_trust_store_path())
        self._write_v1_store(store_path, ["my-plugin", "another-plugin"])

        data = security._read_trust_store()

        # Version bumped to 2.
        assert (
            data["version"] == 2
        ), f"v1 store must be migrated to v2 on read, got version={data['version']}"
        # Trusted plugins preserved — no silent trust loss.
        assert "my-plugin" in data["plugins"]
        assert "another-plugin" in data["plugins"]
        # trusted_at preserved.
        assert "my-plugin" in data["trusted_at"]
        # audit_warnings added as empty dict (R-P0-1 will populate it).
        assert data.get("audit_warnings") == {}, (
            "Migrated v2 store must have an empty `audit_warnings` dict — "
            "R-P0-1 will populate it during the next plugin audit pass."
        )

    def test_v1_store_with_no_plugins_migrates_cleanly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Edge case: v1 store with empty plugins list."""
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        import importlib

        importlib.reload(security)

        store_path = Path(security.get_trust_store_path())
        self._write_v1_store(store_path, [])

        data = security._read_trust_store()
        assert data["version"] == 2
        assert data["plugins"] == []
        assert data.get("audit_warnings") == {}

    def test_v1_store_migration_logs_info(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        """An INFO log must be emitted when a v1 store is migrated —
        so users running ``--verbose`` can see what happened."""
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        import importlib

        importlib.reload(security)

        store_path = Path(security.get_trust_store_path())
        self._write_v1_store(store_path, ["my-plugin"])

        with caplog.at_level("INFO"):
            security._read_trust_store()

        matching = [
            r
            for r in caplog.records
            if r.levelname == "INFO" and "trust store" in r.getMessage().lower()
        ]
        assert matching, (
            "An INFO log must be emitted when migrating a v1 trust store to v2. "
            f"Got records: {[(r.levelname, r.getMessage()) for r in caplog.records]}"
        )

    def test_migration_persists_to_disk_on_next_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After a v1→v2 migration in memory, the next ``trust_plugin``
        call writes the v2 structure to disk — so the migration
        persists across runs."""
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        import importlib

        importlib.reload(security)

        store_path = Path(security.get_trust_store_path())
        self._write_v1_store(store_path, ["existing-plugin"])

        # Read triggers migration in memory.
        security._read_trust_store()
        # trust_plugin writes the migrated structure back to disk.
        security.trust_plugin("new-plugin")

        with open(store_path, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk["version"] == 2, (
            "After trust_plugin write, on-disk version must be 2 — "
            "the migration must persist, not just live in memory."
        )
        assert "existing-plugin" in on_disk["plugins"]
        assert "new-plugin" in on_disk["plugins"]
        assert on_disk.get("audit_warnings") == {}


# =============================================================================
# Corrupt JSON still fail-safes to empty v2 store
# =============================================================================


class TestCorruptJsonFailSafe:
    """Corrupt JSON on disk returns a fresh empty v2 store — existing
    fail-safe behavior, preserved by R-P0-2."""

    def test_corrupt_json_returns_empty_v2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        import importlib

        importlib.reload(security)

        store_path = Path(security.get_trust_store_path())
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text("{not valid json", encoding="utf-8")

        data = security._read_trust_store()
        assert data["version"] == 2
        assert data["plugins"] == []
        assert data["trusted_at"] == {}
        assert data.get("audit_warnings") == {}


# =============================================================================
# Forward compatibility: unknown future version
# =============================================================================


class TestUnknownFutureVersion:
    """A trust store with a version NEWER than _TRUST_STORE_VERSION (e.g.
    a future v3 store read by a v2-aware Senpy) is migrated down to v2
    by re-validating the structure. Trusted plugins are preserved when
    the structure is still compatible (list + dict + dict)."""

    def test_future_version_store_migrates_down(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A future v3 store (with extra fields Senpy doesn't know about)
        is migrated down to v2 — known fields are preserved, unknown
        fields are dropped, version is reset to 2."""
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        import importlib

        importlib.reload(security)

        store_path = Path(security.get_trust_store_path())
        store_path.parent.mkdir(parents=True, exist_ok=True)
        future_data = {
            "version": 99,
            "plugins": ["future-plugin"],
            "trusted_at": {"future-plugin": "2030-01-01T00:00:00Z"},
            "audit_warnings": {"future-plugin": ["future-warning"]},
            "future_field": "unknown to v2 Senpy",
        }
        store_path.write_text(json.dumps(future_data), encoding="utf-8")

        data = security._read_trust_store()
        # Version normalized to 2.
        assert data["version"] == 2
        # Known fields preserved.
        assert "future-plugin" in data["plugins"]
        assert "future-plugin" in data["trusted_at"]
        assert data.get("audit_warnings", {}).get("future-plugin") == ["future-warning"]
        # Unknown fields dropped (we only keep the v2 schema keys).
        assert "future_field" not in data


# =============================================================================
# audit_warnings field (placeholder for now)
# =============================================================================


class TestAuditWarningsField:
    """The ``audit_warnings`` field exists in the v2 schema. R-P0-1 will
    populate it; for now it's always an empty dict on fresh/migrated
    stores. These tests pin down the field's existence so R-P0-1 can
    rely on it."""

    def test_trust_plugin_does_not_touch_audit_warnings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``trust_plugin`` must NOT clear or modify ``audit_warnings`` —
        R-P0-1 will set them separately during the import-time audit.
        ``trust_plugin`` only records the trust decision and timestamp."""
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        import importlib

        importlib.reload(security)

        # Pre-populate audit_warnings to simulate R-P0-1 having run.
        store_path = Path(security.get_trust_store_path())
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_with_warnings = {
            "version": 2,
            "plugins": ["existing-plugin"],
            "trusted_at": {"existing-plugin": "2026-10-30T12:00:00Z"},
            "audit_warnings": {"existing-plugin": ["uses os module"]},
        }
        store_path.write_text(json.dumps(store_with_warnings), encoding="utf-8")

        # Trust a new plugin.
        security.trust_plugin("new-plugin")

        with open(store_path, encoding="utf-8") as f:
            data = json.load(f)
        # existing-plugin's audit_warnings must be preserved.
        assert data["audit_warnings"]["existing-plugin"] == ["uses os module"], (
            "trust_plugin must NOT clear audit_warnings for existing plugins — "
            "R-P0-1 owns that field."
        )
        # new-plugin has no audit_warnings yet (R-P0-1 hasn't run for it).
        assert data["audit_warnings"].get("new-plugin", []) == []

    def test_untrust_plugin_removes_audit_warnings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``untrust_plugin`` must clean up the plugin's ``audit_warnings``
        entry too — otherwise stale audit warnings would accumulate for
        untrusted plugins and resurface if the user re-trusts later."""
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        import importlib

        importlib.reload(security)

        store_path = Path(security.get_trust_store_path())
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_with_warnings = {
            "version": 2,
            "plugins": ["doomed-plugin"],
            "trusted_at": {"doomed-plugin": "2026-10-30T12:00:00Z"},
            "audit_warnings": {"doomed-plugin": ["uses subprocess"]},
        }
        store_path.write_text(json.dumps(store_with_warnings), encoding="utf-8")

        result = security.untrust_plugin("doomed-plugin")
        assert result is True

        with open(store_path, encoding="utf-8") as f:
            data = json.load(f)
        assert "doomed-plugin" not in data["plugins"]
        assert "doomed-plugin" not in data["trusted_at"]
        assert "doomed-plugin" not in data["audit_warnings"], (
            "untrust_plugin must remove the plugin's audit_warnings entry — "
            "stale warnings should not accumulate for untrusted plugins."
        )
