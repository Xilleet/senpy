"""Regression tests for LSP event-handling bugs.

Two bug classes covered here, both P2 (0.8.1 желательно):

    * Closed-document re-add: when ``did_change`` schedules a
      per-URI debounce timer and ``did_close`` fires before the timer
      expires, the timer's callback re-adds the (now-closed) document
      to ``in_memory_files``. The fix is for ``did_close`` to cancel
      the pending per-URI timer and remove the URI from the timer dict.

    * Watched-files change is a no-op stub: when an asset file (a
      ``.png`` / ``.webp`` / ``.ogg`` / ``.mp3`` / ``.wav``) is added,
      removed, or modified on disk outside the editor, the long-lived
      LSP server's ``AssetManager`` does not refresh its index. Hover
      cards and RPY501-503 keep showing stale data until the user
      restarts the server. The fix is to implement
      ``did_change_watched_files``: filter events by asset extensions
      and refresh ``AssetManager`` with a debounce.

Both bugs reproduce only inside the LSP server runtime, so these tests
use a mock LSP server setup similar to ``tests/test_lsp_race.py``.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from lsprotocol import types as lsp

import senpy.lsp.server as server_mod
from senpy.core.analyzer import SenpyAnalyzer


class MockDocument:
    def __init__(self, uri: str, content: str):
        self.uri = uri
        self.lines = content.splitlines(keepends=True)
        self.source = content


class MockWorkspace:
    def __init__(self, docs: dict[str, MockDocument] | None = None):
        self.docs = docs or {}

    def get_text_document(self, uri: str):
        return self.docs.get(uri)


@pytest.fixture(autouse=True)
def _clean_lsp_state():
    """Reset LSP server module-level state before AND after each test."""
    # Before: clear timers
    if getattr(server_mod, "_full_timer", None) is not None:
        try:
            server_mod._lsp_server.full_timer.cancel()
        except Exception:
            pass
        server_mod._lsp_server.full_timer = None
    if getattr(server_mod, "_change_timer", None) is not None:
        try:
            server_mod._lsp_server.change_timer.cancel()
        except Exception:
            pass
        server_mod._lsp_server.change_timer = None
    lsp_server = getattr(server_mod, "_lsp_server", None)
    if lsp_server is not None and hasattr(lsp_server, "change_timers"):
        for t in list(lsp_server.change_timers.values()):
            try:
                t.cancel()
            except Exception:
                pass
        lsp_server.change_timers.clear()

    yield  # test runs here

    # After: same cleanup (the autouse fixture in conftest also does this,
    # but we run early to ensure timers don't fire between tests).
    if getattr(server_mod, "_full_timer", None) is not None:
        try:
            server_mod._lsp_server.full_timer.cancel()
        except Exception:
            pass
        server_mod._lsp_server.full_timer = None
    if getattr(server_mod, "_change_timer", None) is not None:
        try:
            server_mod._lsp_server.change_timer.cancel()
        except Exception:
            pass
        server_mod._lsp_server.change_timer = None
    lsp_server = getattr(server_mod, "_lsp_server", None)
    if lsp_server is not None and hasattr(lsp_server, "change_timers"):
        for t in list(lsp_server.change_timers.values()):
            try:
                t.cancel()
            except Exception:
                pass
        lsp_server.change_timers.clear()


def _setup_lsp_server(tmp_path: Path, rpy_content: str):
    """Set up a minimal LSP server with a project + .rpy file."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    script_file = game_dir / "script.rpy"
    script_file.write_text(rpy_content, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    server_mod._lsp_server.active_analyzer = analyzer
    server_mod._lsp_server.is_initialized = True
    return script_file, analyzer


# ---------------------------------------------------------------------------
# Closed-document re-add via pending timer
# ---------------------------------------------------------------------------


def test_did_close_cancels_pending_change_timer(tmp_path: Path) -> None:
    """Reproducer: ``did_change`` schedules a per-URI 150ms timer; if
    ``did_close`` fires before the timer expires, the timer's callback
    (`run_single_file_diagnostics`) re-adds the now-closed document to
    ``in_memory_files``. The fix is for ``did_close`` to cancel the
    per-URI timer and pop the URI from ``change_timers``.

    We test the contract directly: after `did_change` → `did_close`, the
    URI must not have a pending timer in `_lsp_server.change_timers`.
    """
    rpy = "label start:\n    return\n"
    script_file, analyzer = _setup_lsp_server(tmp_path, rpy)
    uri = server_mod._path_to_uri(str(script_file))

    doc = MockDocument(uri, rpy)
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace({uri: doc})

    # did_change schedules a 150ms timer for this URI.
    from senpy.lsp.handlers.text_document import did_change, did_close

    params_change = lsp.DidChangeTextDocumentParams(
        text_document=lsp.VersionedTextDocumentIdentifier(uri=uri, version=2),
        content_changes=[],
    )
    did_change(mock_ls, params_change)
    assert (
        uri in server_mod._lsp_server.change_timers
    ), "did_change should have scheduled a per-URI timer"

    # did_close should cancel that timer and clean up the dict entry.
    params_close = lsp.DidCloseTextDocumentParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
    )
    did_close(mock_ls, params_close)
    assert uri not in server_mod._lsp_server.change_timers, (
        f"did_close must cancel the per-URI timer. change_timers still "
        f"contains: {server_mod._lsp_server.change_timers}"
    )

    # Wait past the original 150ms deadline to verify the timer does not
    # fire and re-add the document to in_memory_files.
    time.sleep(0.25)
    norm_file = server_mod._normalize_path(server_mod._uri_to_path(uri))
    assert norm_file not in analyzer.in_memory_files, (
        f"Closed document was re-added to in_memory_files by a stale "
        f"timer. in_memory_files={analyzer.in_memory_files}"
    )


# ---------------------------------------------------------------------------
# Watched-files change refreshes AssetManager
# ---------------------------------------------------------------------------


def test_did_change_watched_files_refreshes_asset_manager(tmp_path: Path) -> None:
    """Reproducer: when an asset file (e.g. a ``.png``) is added on disk
    outside the editor, the LSP server's ``AssetManager`` does not
    refresh its index. Hover cards and RPY501-503 keep showing stale
    data until the server is restarted.

    The fix: ``did_change_watched_files`` filters events by asset
    extensions and refreshes ``AssetManager`` (with a debounce to
    avoid spamming on bulk operations like git checkout).

    We test the contract directly: after a watched-files event for a
    new ``.png`` file, ``analyzer.assets.valid_images`` must contain
    the new image.
    """
    rpy = "label start:\n    return\n"
    script_file, analyzer = _setup_lsp_server(tmp_path, rpy)

    # Add a new image file on disk.
    images_dir = tmp_path / "game" / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    new_image = images_dir / "town_bg.png"
    new_image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)  # minimal PNG header

    # Verify the AssetManager has not yet indexed the new image.
    initial_valid = set(analyzer.assets.valid_images)
    assert (
        "town_bg" not in initial_valid
    ), "Sanity check: before the watched-files event, the new image should not be in valid_images."

    # Simulate the LSP workspace notifying the server of the file change.
    from senpy.lsp.handlers.text_document import did_change_watched_files

    file_uri = server_mod._path_to_uri(str(new_image))
    mock_ls = MagicMock()
    params = lsp.DidChangeWatchedFilesParams(
        changes=[
            lsp.FileEvent(
                uri=file_uri,
                type=lsp.FileChangeType.Created,
            )
        ]
    )
    did_change_watched_files(mock_ls, params)

    # Allow any debounce timer to fire (the implementation may use a
    # short debounce; wait long enough to cover it).
    time.sleep(0.5)

    # The AssetManager must have re-indexed and now include the new image.
    refreshed_valid = set(analyzer.assets.valid_images)
    assert "town_bg" in refreshed_valid, (
        f"did_change_watched_files must refresh AssetManager so the new "
        f"image is indexed. valid_images before={initial_valid}, "
        f"after={refreshed_valid}"
    )


def test_did_change_watched_files_ignores_non_asset_extensions(
    tmp_path: Path,
) -> None:
    """Counter-case: events for non-asset files (e.g. ``.txt``) must
    NOT trigger a refresh. Avoids expensive re-indexing on every
    documentation file change.
    """
    rpy = "label start:\n    return\n"
    script_file, analyzer = _setup_lsp_server(tmp_path, rpy)

    # Add a non-asset file on disk.
    game_dir = tmp_path / "game"
    readme_file = game_dir / "README.txt"
    readme_file.write_text("not an asset", encoding="utf-8")

    from senpy.lsp.handlers.text_document import did_change_watched_files

    file_uri = server_mod._path_to_uri(str(readme_file))
    mock_ls = MagicMock()
    params = lsp.DidChangeWatchedFilesParams(
        changes=[
            lsp.FileEvent(
                uri=file_uri,
                type=lsp.FileChangeType.Created,
            )
        ]
    )
    did_change_watched_files(mock_ls, params)
    time.sleep(0.5)

    # The AssetManager should not have re-indexed — non-asset extension.
    # We verify the known_assets set did NOT grow due to a refresh
    # (the .txt file should never be added to known_assets).
    assert "readme.txt" not in analyzer.assets.known_assets, (
        f"Non-asset .txt file should not be added to known_assets. "
        f"known_assets={analyzer.assets.known_assets}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
