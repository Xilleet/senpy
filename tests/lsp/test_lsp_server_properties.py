"""SenpyLSPServer @property accessors delegate to module globals.

When migrates LSP handlers from ``server_mod._active_analyzer``
to ``server_mod._lsp_server.active_analyzer``, we need a guarantee that
both access paths hit the SAME state. These tests pin that contract.

If a future refactor breaks the delegation (e.g., makes
``_lsp_server.active_analyzer`` a real instance attribute while
``_active_analyzer`` is still a separate module global), these tests
go red — preventing silent state divergence.

Tests cover all 8 properties added:

    - active_analyzer      ↔ _active_analyzer
    - is_initialized       ↔ _is_initialized
    - current_workspace_root ↔ _current_workspace_root
    - latest_diagnostics_by_path ↔ _latest_diagnostics_by_path
    - previously_diagnosed_uris ↔ _previously_diagnosed_uris
    - change_timer         ↔ _change_timer
    - full_timer           ↔ _full_timer
    - symbol_snapshot      ↔ _symbol_snapshot

Each test verifies:
    1. Reading ``_lsp_server.<attr>`` returns the same object as
       reading the module global ``_<attr>``.
    2. Writing ``_lsp_server.<attr> = X`` updates the module global
       to ``X``.
    3. Writing the module global ``_<attr> = Y`` is visible from the
       next read of ``_lsp_server.<attr>``.
"""

from __future__ import annotations

import threading

import pytest

from senpy.lsp import server as server_mod
from senpy.lsp.server import _lsp_server

# =============================================================================
# Helpers — save and restore module global state between tests
# =============================================================================


@pytest.fixture
def restore_globals():
    """Snapshot module globals before the test, restore after.

    These tests mutate module-level state to verify the delegation
    contract. Without restoration, mutations would leak across tests
    and break other LSP tests that run after this file.
    """
    snapshot = {
        "_active_analyzer": server_mod._active_analyzer,
        "_is_initialized": server_mod._is_initialized,
        "_current_workspace_root": server_mod._current_workspace_root,
        "_latest_diagnostics_by_path": server_mod._latest_diagnostics_by_path,
        "_previously_diagnosed_uris": server_mod._previously_diagnosed_uris,
        "_change_timer": server_mod._change_timer,
        "_full_timer": server_mod._full_timer,
        "_symbol_snapshot": server_mod._symbol_snapshot,
    }
    yield
    for name, value in snapshot.items():
        setattr(server_mod, name, value)


# =============================================================================
# Per-property delegation tests
# =============================================================================


class TestPropertyDelegation:
    """Each @property on SenpyLSPServer must delegate read/write to the
    corresponding module global."""

    def test_active_analyzer_read_matches_global(self, restore_globals):
        """_lsp_server.active_analyzer returns the same object as
        the module global _active_analyzer."""
        # Default state — both None
        assert _lsp_server.active_analyzer is server_mod._active_analyzer

        # Set via module global — visible from property
        sentinel = object()  # unique sentinel object
        server_mod._active_analyzer = sentinel  # type: ignore[assignment]
        assert _lsp_server.active_analyzer is sentinel
        assert _lsp_server.active_analyzer is server_mod._active_analyzer

    def test_active_analyzer_write_updates_global(self, restore_globals):
        """Assigning _lsp_server.active_analyzer = X updates the module
        global _active_analyzer to X."""
        sentinel = object()
        _lsp_server.active_analyzer = sentinel  # type: ignore[assignment]
        assert server_mod._active_analyzer is sentinel

    def test_is_initialized_read_matches_global(self, restore_globals):
        assert _lsp_server.is_initialized is server_mod._is_initialized
        server_mod._is_initialized = True
        assert _lsp_server.is_initialized is True
        server_mod._is_initialized = False
        assert _lsp_server.is_initialized is False

    def test_is_initialized_write_updates_global(self, restore_globals):
        _lsp_server.is_initialized = True
        assert server_mod._is_initialized is True
        _lsp_server.is_initialized = False
        assert server_mod._is_initialized is False

    def test_current_workspace_root_delegation(self, restore_globals):
        assert _lsp_server.current_workspace_root is server_mod._current_workspace_root
        server_mod._current_workspace_root = "/tmp/test_workspace"
        assert _lsp_server.current_workspace_root == "/tmp/test_workspace"
        _lsp_server.current_workspace_root = "/another/path"
        assert server_mod._current_workspace_root == "/another/path"

    def test_latest_diagnostics_by_path_delegation(self, restore_globals):
        # Default — both reference the same dict object.
        assert _lsp_server.latest_diagnostics_by_path is server_mod._latest_diagnostics_by_path
        # Mutations via module global are visible from property.
        server_mod._latest_diagnostics_by_path["x"] = []
        assert "x" in _lsp_server.latest_diagnostics_by_path
        # Reassignment via property updates module global.
        new_dict = {"y": []}
        _lsp_server.latest_diagnostics_by_path = new_dict
        assert server_mod._latest_diagnostics_by_path is new_dict

    def test_previously_diagnosed_uris_delegation(self, restore_globals):
        assert _lsp_server.previously_diagnosed_uris is server_mod._previously_diagnosed_uris
        server_mod._previously_diagnosed_uris.add("file://x.rpy")
        assert "file://x.rpy" in _lsp_server.previously_diagnosed_uris
        new_set = {"file://y.rpy"}
        _lsp_server.previously_diagnosed_uris = new_set
        assert server_mod._previously_diagnosed_uris is new_set

    def test_change_timer_delegation(self, restore_globals):
        assert _lsp_server.change_timer is server_mod._change_timer
        # Set a real Timer object
        t = threading.Timer(99.0, lambda: None)
        try:
            _lsp_server.change_timer = t
            assert server_mod._change_timer is t
            # Read back via module global
            assert _lsp_server.change_timer is server_mod._change_timer
        finally:
            t.cancel()
        _lsp_server.change_timer = None
        assert server_mod._change_timer is None

    def test_full_timer_delegation(self, restore_globals):
        assert _lsp_server.full_timer is server_mod._full_timer
        t = threading.Timer(99.0, lambda: None)
        try:
            server_mod._full_timer = t
            assert _lsp_server.full_timer is t
        finally:
            t.cancel()
        server_mod._full_timer = None
        assert _lsp_server.full_timer is None

    def test_symbol_snapshot_delegation(self, restore_globals):
        assert _lsp_server.symbol_snapshot is server_mod._symbol_snapshot
        # Mutations via module global are visible from property
        server_mod._symbol_snapshot["labels"]["test_label"] = object()
        assert "test_label" in _lsp_server.symbol_snapshot["labels"]
        # Reassignment via property
        new_snapshot = {"labels": {}, "screens": {}}
        _lsp_server.symbol_snapshot = new_snapshot
        assert server_mod._symbol_snapshot is new_snapshot


# =============================================================================
# Existing instance attributes (not delegated) still work
# =============================================================================


class TestExistingInstanceAttrs:
    """Phase 3.1 added @property accessors but the EXISTING instance
    attributes (``change_timers``, ``rw_lock``, ``change_generations``,
    ``full_generation``) must remain as real instance state, not
    delegated. These tests pin that distinction."""

    def test_change_timers_is_real_instance_attr(self):
        """change_timers (plural) is a real dict on the instance,
        not a property delegating to a module global."""
        assert isinstance(_lsp_server.change_timers, dict)
        # Mutating the instance dict doesn't touch module globals
        # (there's no module-level _change_timers plural counterpart).
        _lsp_server.change_timers["file://test"] = None
        assert "file://test" in _lsp_server.change_timers
        _lsp_server.change_timers.clear()

    def test_rw_lock_is_real_instance_attr(self):
        from senpy.lsp.server import _RWLock

        assert isinstance(_lsp_server.rw_lock, _RWLock)

    def test_change_generations_is_real_instance_attr(self):
        assert isinstance(_lsp_server.change_generations, dict)

    def test_full_generation_is_real_instance_attr(self):
        assert isinstance(_lsp_server.full_generation, int)
