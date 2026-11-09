"""Integration test for plugin rule execution via the LSP server.

Verifies that plugin-generated diagnostics actually reach the LSP
client via ``textDocument/publishDiagnostics`` when the analyzer runs
through the LSP code path (did_open / did_change).

Mirrors production LSP analyzer instantiation: NO ``no_cache=True``
(matches ``server.py:411`` — ``SenpyAnalyzer(project_root)`` with
default kwargs). Tests the cold-run path (fresh ``tmp_path``, no
pre-existing ``.senpy_cache/cache.pkl``).

Two scenarios covered:
  1. **did_open / did_save path** → ``run_full_project_diagnostics``
     iterates all files, plugin rules fire, ``result.diagnostics``
     contains the plugin diagnostic, ``publishDiagnostics`` sends it.
  2. **did_change path** → ``run_single_file_diagnostics`` analyzes
     one file via ``analyze_file_only``, plugin rule fires on the
     in-memory content, ``publishDiagnostics`` sends it.

Also verifies the ``start_lsp()`` autoload fix: when an embedded host
calls ``start_lsp()`` directly (without going through ``main()``),
plugin rules must still be registered. Previously
``_REGISTERED_LINT_RULES`` would be empty and ``_run_plugin_rules``
would early-return — plugin diagnostics silently never reached the
client.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from lsprotocol import types as lsp

import senpy.lsp.server as server_mod
from senpy.core.analyzer import SenpyAnalyzer
from senpy.plugins.autoload import reset_autoload_state
from senpy.plugins.registry import (
    clear_registered_lint_rules,
    get_registered_lint_rules,
)

# Locate the example plugin's rules.py on disk.
_PLUGIN_DIR = Path(__file__).resolve().parent.parent / "examples" / "todo_comment_plugin"
_RULES_PY = _PLUGIN_DIR / "todo_comment_plugin" / "rules.py"


def _load_rules_module() -> ModuleType:
    """Load the example plugin's rules.py and register it in sys.modules
    so ``from senpy.api import Diagnostic`` inside the plugin resolves."""
    if not _RULES_PY.is_file():
        pytest.skip(f"Example plugin not found at {_RULES_PY}")
    spec = importlib.util.spec_from_file_location("todo_comment_plugin.rules", _RULES_PY)
    if spec is None or spec.loader is None:
        pytest.skip(f"Could not load module spec for {_RULES_PY}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["todo_comment_plugin.rules"] = module
    spec.loader.exec_module(module)
    return module


# =============================================================================
# Mock LS that records publishDiagnostics calls
# =============================================================================


class _MockDocument:
    def __init__(self, uri: str, content: str):
        self.uri = uri
        self.lines = content.splitlines(keepends=True)
        self.source = content


class _MockWorkspace:
    def __init__(self, doc: _MockDocument, root_path: str):
        self.doc = doc
        self.root_path = root_path

    def get_text_document(self, uri: str):
        return self.doc if self.doc.uri == uri else None


class _RecordingLS:
    """Mock LanguageServer that records publishDiagnostics calls."""

    def __init__(self, doc: _MockDocument, root_path: str):
        self.workspace = _MockWorkspace(doc, root_path)
        self.published: list[lsp.PublishDiagnosticsParams] = []

    def text_document_publish_diagnostics(self, params: lsp.PublishDiagnosticsParams) -> None:
        self.published.append(params)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset plugin registry AND LSP server module-level state."""
    reset_autoload_state()
    clear_registered_lint_rules()
    # LSP server state
    server_mod._active_analyzer = None
    server_mod._is_initialized = False
    server_mod._current_workspace_root = None
    server_mod._previously_diagnosed_uris = set()
    server_mod._latest_diagnostics_by_path = {}
    if getattr(server_mod, "_full_timer", None) is not None:
        try:
            server_mod._full_timer.cancel()
        except Exception:
            pass
        server_mod._full_timer = None
    if getattr(server_mod, "_change_timer", None) is not None:
        try:
            server_mod._change_timer.cancel()
        except Exception:
            pass
        server_mod._change_timer = None
    lsp_server = getattr(server_mod, "_lsp_server", None)
    if lsp_server is not None and hasattr(lsp_server, "change_timers"):
        for t in list(lsp_server.change_timers.values()):
            try:
                t.cancel()
            except Exception:
                pass
        lsp_server.change_timers.clear()

    yield

    # After: same cleanup
    reset_autoload_state()
    clear_registered_lint_rules()
    server_mod._active_analyzer = None
    server_mod._is_initialized = False
    server_mod._current_workspace_root = None
    server_mod._previously_diagnosed_uris = set()
    server_mod._latest_diagnostics_by_path = {}
    if getattr(server_mod, "_full_timer", None) is not None:
        try:
            server_mod._full_timer.cancel()
        except Exception:
            pass
        server_mod._full_timer = None
    if getattr(server_mod, "_change_timer", None) is not None:
        try:
            server_mod._change_timer.cancel()
        except Exception:
            pass
        server_mod._change_timer = None
    lsp_server = getattr(server_mod, "_lsp_server", None)
    if lsp_server is not None and hasattr(lsp_server, "change_timers"):
        for t in list(lsp_server.change_timers.values()):
            try:
                t.cancel()
            except Exception:
                pass
        lsp_server.change_timers.clear()


@pytest.fixture
def todo_plugin_registered():
    """Load the example todo_comment_plugin and register its Rule."""
    rules_module = _load_rules_module()
    registered = list(get_registered_lint_rules())
    assert any(
        cls is rules_module.TodoCommentRule for _code, cls in registered
    ), "TodoCommentRule not registered after loading the example plugin"
    return rules_module.TodoCommentRule


def _setup_project(tmp_path: Path, script_content: str) -> Path:
    """Create a Ren'Py project with senpy.toml enabling plugins."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(script_content, encoding="utf-8")
    # Enable plugins via senpy.toml — mirrors what a user would set.
    (tmp_path / "senpy.toml").write_text("[senpy]\nenable_plugins = true\n", encoding="utf-8")
    return tmp_path


# =============================================================================
# Tests
# =============================================================================


class TestLSPPluginExecutionFullProject:
    """did_open / did_save path → run_full_project_diagnostics → publishDiagnostics."""

    def test_plugin_diagnostic_reaches_publishDiagnostics_on_full_scan(
        self, todo_plugin_registered, tmp_path: Path
    ) -> None:
        """A .rpy file with a TODO comment must produce an RPY902
        diagnostic that flows through ``run_full_project_diagnostics``
        into ``publishDiagnostics``.

        Mirrors production LSP analyzer instantiation: NO ``no_cache=True``
        (matches ``server.py:411``). Cold run on fresh tmp_path.
        """
        script_content = "# TODO: implement this label\nlabel start:\n    return\n"
        project = _setup_project(tmp_path, script_content)
        script_file = project / "game" / "script.rpy"
        uri = server_mod._path_to_uri(str(script_file))

        # Production LSP path: SenpyAnalyzer(project_root) — no no_cache.
        analyzer = SenpyAnalyzer(str(project))
        analyzer.run(quiet=True)
        server_mod._active_analyzer = analyzer
        server_mod._is_initialized = True
        server_mod._current_workspace_root = str(project)
        server_mod._refresh_symbol_snapshot()

        # Recording mock LS with workspace root path set so the LSP
        # server can resolve the project root from a URI.
        doc = _MockDocument(uri, script_content)
        ls = _RecordingLS(doc, str(project))

        # Run the full-project diagnostics worker directly (same as
        # the debounce Timer would call after did_open).
        server_mod.run_full_project_diagnostics(ls, uri)

        # Assert: at least one publishDiagnostics call was made.
        assert ls.published, "run_full_project_diagnostics did not call publishDiagnostics at all"

        # Collect all diagnostics across all publish calls.
        all_diags: list[lsp.Diagnostic] = []
        for params in ls.published:
            all_diags.extend(params.diagnostics)

        # The plugin's RPY902 diagnostic must be present.
        rpy902_diags = [d for d in all_diags if d.code == "RPY902"]
        assert rpy902_diags, (
            f"RPY902 (plugin diagnostic) not in publishDiagnostics. "
            f"Got codes: {sorted({d.code for d in all_diags})}. "
            f"Plugin rule.check() did not fire, or its diagnostic did "
            f"not reach the LSP publish path."
        )

        # Sanity: the message mentions the TODO keyword.
        assert any("TODO" in d.message for d in rpy902_diags)


class TestLSPPluginExecutionSingleFile:
    """did_change path → run_single_file_diagnostics → publishDiagnostics."""

    def test_plugin_diagnostic_reaches_publishDiagnostics_on_single_file(
        self, todo_plugin_registered, tmp_path: Path
    ) -> None:
        """A .rpy file edited (did_change) with a TODO comment must
        produce an RPY902 diagnostic that flows through
        ``run_single_file_diagnostics`` into ``publishDiagnostics``.

        The single-file path bypasses Tier 2 cache (always re-analyzes),
        so plugin rules fire on every did_change — no cold/warm
        distinction here.
        """
        # Initial content (no TODO) — analyzer primed on this.
        initial_content = "label start:\n    return\n"
        project = _setup_project(tmp_path, initial_content)
        script_file = project / "game" / "script.rpy"
        uri = server_mod._path_to_uri(str(script_file))

        analyzer = SenpyAnalyzer(str(project))
        analyzer.run(quiet=True)
        server_mod._active_analyzer = analyzer
        server_mod._is_initialized = True
        server_mod._current_workspace_root = str(project)
        server_mod._refresh_symbol_snapshot()

        # User edits the file to add a TODO comment.
        edited_content = "# TODO: implement this label\nlabel start:\n    return\n"
        doc = _MockDocument(uri, edited_content)
        ls = _RecordingLS(doc, str(project))

        # Run the single-file diagnostics worker directly.
        server_mod.run_single_file_diagnostics(ls, uri, edited_content)

        # Assert: publishDiagnostics was called.
        assert ls.published, "run_single_file_diagnostics did not call publishDiagnostics"

        # The publish call for our URI must contain the RPY902.
        params = ls.published[-1]
        rpy902_diags = [d for d in params.diagnostics if d.code == "RPY902"]
        assert rpy902_diags, (
            f"RPY902 not in single-file publishDiagnostics. "
            f"Got codes: {sorted({d.code for d in params.diagnostics})}."
        )
        assert any("TODO" in d.message for d in rpy902_diags)

    def test_single_file_publish_only_for_requested_uri(
        self, todo_plugin_registered, tmp_path: Path
    ) -> None:
        """``run_single_file_diagnostics`` must publish diagnostics for
        exactly one URI (the file being edited), not for the whole
        project."""
        initial_content = "# TODO: one\nlabel start:\n    return\n"
        project = _setup_project(tmp_path, initial_content)
        script_file = project / "game" / "script.rpy"
        uri = server_mod._path_to_uri(str(script_file))

        analyzer = SenpyAnalyzer(str(project))
        analyzer.run(quiet=True)
        server_mod._active_analyzer = analyzer
        server_mod._is_initialized = True
        server_mod._current_workspace_root = str(project)
        server_mod._refresh_symbol_snapshot()

        doc = _MockDocument(uri, initial_content)
        ls = _RecordingLS(doc, str(project))

        server_mod.run_single_file_diagnostics(ls, uri, initial_content)

        # Exactly one publish call, for exactly our URI.
        assert len(ls.published) == 1, (
            f"Expected exactly 1 publishDiagnostics call for single-file "
            f"analysis, got {len(ls.published)}"
        )
        assert ls.published[0].uri == uri


class TestStartLSPAutoloadFix:
    """Verify that ``start_lsp()`` ensures plugin rules are registered,
    even when called directly by an embedded host (without ``main()``).

    Previously ``start_lsp()`` did not call ``autoload_plugins()``,
    so an embedded host invoking ``start_lsp()`` directly would have
    an empty ``_REGISTERED_LINT_RULES`` — ``_run_plugin_rules``
    early-returns and plugin diagnostics silently never reached the
    client.
    """

    def test_start_lsp_calls_autoload_plugins(self, todo_plugin_registered, monkeypatch) -> None:
        """``start_lsp()`` must invoke ``autoload_plugins()`` before
        starting the I/O loop."""
        from senpy.plugins import autoload as autoload_mod

        autoload_called = []

        def _tracking_autoload():
            autoload_called.append(True)

        monkeypatch.setattr(autoload_mod, "autoload_plugins", _tracking_autoload)
        # Patch server.start_io so we don't actually start the I/O loop.
        monkeypatch.setattr(server_mod.server, "start_io", lambda: None)

        try:
            server_mod.start_lsp()
        finally:
            # start_lsp may raise because of patched start_io returning None
            # — that's fine, we only care that autoload_plugins was called.
            pass

        assert autoload_called, (
            "start_lsp() did not call autoload_plugins(). An embedded "
            "host invoking start_lsp() directly would have no plugin "
            "rules registered — plugin diagnostics silently never reach "
            "the client."
        )

    def test_start_lsp_autoload_is_idempotent(self, todo_plugin_registered, monkeypatch) -> None:
        """If ``main()`` already called ``autoload_plugins()``,
        ``start_lsp()`` calling it again must be a safe no-op (the
        ``_PLUGINS_LOADED`` flag prevents double-loading)."""
        from senpy.plugins import autoload as autoload_mod

        # First call (simulating main() having run).
        autoload_mod.autoload_plugins()
        assert (
            autoload_mod._PLUGINS_LOADED
        ), "First autoload_plugins() call did not set _PLUGINS_LOADED"

        # Now start_lsp() — must not raise even though autoload was already called.
        monkeypatch.setattr(server_mod.server, "start_io", lambda: None)
        try:
            server_mod.start_lsp()
        except Exception as exc:
            pytest.fail(
                f"start_lsp() raised after autoload already ran: {exc!r}. "
                f"The autoload call in start_lsp() must be idempotent."
            )
