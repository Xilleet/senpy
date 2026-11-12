"""Tests for LSP document_symbols not mutating analyzer under read lock.

``document_symbols`` in ``senpy/lsp/handlers/navigation.py`` (lines
838-841) had a fallback: if ``file_scopes[norm_path]`` was missing, it
called ``analyzer._collect_symbols(file_path)`` to populate it on the
fly. But ``document_symbols`` is registered with ``@_with_analysis_lock``
which takes the **read** lock — and ``_collect_symbols`` mutates
``analyzer.file_scopes[norm_path]`` and ``analyzer._stage1_lines``,
violating the ``_RWLock`` contract (readers must not write).

The race scenario: ``did_open`` schedules ``run_full_project_diagnostics``
with a 300ms debounce. If ``document_symbols`` arrives in those 300ms
(before the full analysis populates ``file_scopes``), the handler fell
back to ``_collect_symbols`` — mutating shared state under a read lock.

The fix: remove the fallback. If ``file_scopes[norm_path]`` is missing,
return ``[]``. The full analysis (already scheduled by ``did_open``)
will populate the scope; the next ``document_symbols`` call (VS Code
re-requests outline on ``did_change``/``did_save``) will see it.

This test module guards the contract: ``document_symbols`` must NOT
call ``_collect_symbols`` (no mutation under read lock).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from lsprotocol import types as lsp

from senpy.core.analyzer import SenpyAnalyzer
from senpy.lsp import server as server_mod
from senpy.lsp.handlers.navigation import document_symbols
from tests._helpers.lsp import MockDocument, MockWorkspace


def _make_doc_symbol_params(uri: str) -> lsp.DocumentSymbolParams:
    """Build DocumentSymbolParams for the given URI."""
    return lsp.DocumentSymbolParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
    )


def _setup_project_with_label(tmp_path: Path) -> Path:
    """Create a project with one .rpy file containing a label."""
    game = tmp_path / "game"
    game.mkdir(parents=True, exist_ok=True)
    (game / "script.rpy").write_text(
        'label start:\n    "Hello"\n    return\n',
        encoding="utf-8",
    )
    return tmp_path


def _initialize_lsp_without_full_analysis(project_root: Path) -> SenpyAnalyzer:
    """Initialize the LSP server with an analyzer but DON'T run full analysis.

    This simulates the race: did_open scheduled full analysis (300ms debounce),
    but document_symbols arrives before it runs. file_scopes is empty.
    """
    analyzer = SenpyAnalyzer(str(project_root))
    # Deliberately do NOT call analyzer.run() — file_scopes stays empty.
    server_mod._lsp_server.active_analyzer = analyzer
    server_mod._lsp_server.is_initialized = True
    server_mod._refresh_symbol_snapshot()
    return analyzer


class TestDocumentSymbolsDoesNotMutateUnderReadLock:
    """document_symbols must NOT call _collect_symbols (no mutation under read lock)."""

    def test_document_symbols_returns_empty_when_scope_missing(self, tmp_path: Path):
        """If file_scopes[norm_path] is missing, return [] — do not mutate.

        Before P1-8: document_symbols called _collect_symbols(file_path)
        to populate the scope on the fly. This mutated analyzer.file_scopes
        and analyzer._stage1_lines under the read lock — violating _RWLock.

        After P1-8: return [] immediately. The full analysis (scheduled by
        did_open) will populate the scope; the next document_symbols call
        will see it.
        """
        project_root = _setup_project_with_label(tmp_path)
        analyzer = _initialize_lsp_without_full_analysis(project_root)

        # Verify the test setup: file_scopes is empty (no full analysis ran).
        script_path = str(project_root / "game" / "script.rpy")
        norm_path = server_mod._normalize_path(script_path)
        assert norm_path not in analyzer.file_scopes, (
            "Test setup: file_scopes must be empty (no full analysis ran) "
            "to simulate the did_open → document_symbols race."
        )

        # Use _path_to_uri (not f"file://{script_path}") — the server's
        # helper produces the canonical file URI (file:///C:/... on Windows,
        # file:///tmp/... on POSIX). Hardcoding f"file://{path}" breaks on
        # Windows because _uri_to_path may not parse file://C:\... correctly.
        uri = server_mod._path_to_uri(script_path)
        doc = MockDocument(uri, (project_root / "game" / "script.rpy").read_text(encoding="utf-8"))
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        # Spy on _collect_symbols to verify it is NOT called.
        collect_calls: list[str] = []
        original_collect = analyzer._collector._collect_symbols

        def spy_collect(file_path: str):
            collect_calls.append(file_path)
            return original_collect(file_path)

        analyzer._collector._collect_symbols = spy_collect

        params = _make_doc_symbol_params(uri)
        result = document_symbols(mock_ls, params)

        # document_symbols must return [] (no scope available).
        # Before P1-8: it would have called _collect_symbols and returned symbols.
        assert (
            result == []
        ), f"document_symbols must return [] when file_scopes is empty. Got: {result}"
        # And it must NOT have called _collect_symbols (no mutation under read lock).
        assert collect_calls == [], (
            f"document_symbols must NOT call _collect_symbols (mutation under "
            f"read lock violates _RWLock contract). Got calls: {collect_calls}"
        )

    def test_document_symbols_returns_symbols_when_scope_present(self, tmp_path: Path):
        """When file_scopes IS populated (after full analysis), return symbols.

        Sanity test: the normal path (scope present) must still work.
        Guards against the fix accidentally breaking the happy path.
        """
        project_root = _setup_project_with_label(tmp_path)
        analyzer = SenpyAnalyzer(str(project_root))
        analyzer.run(quiet=True)  # Full analysis — populates file_scopes.
        server_mod._lsp_server.active_analyzer = analyzer
        server_mod._lsp_server.is_initialized = True
        server_mod._refresh_symbol_snapshot()

        script_path = str(project_root / "game" / "script.rpy")
        norm_path = server_mod._normalize_path(script_path)
        assert (
            norm_path in analyzer.file_scopes
        ), "Test setup: file_scopes must be populated after full analysis."

        uri = server_mod._path_to_uri(script_path)
        doc = MockDocument(uri, (project_root / "game" / "script.rpy").read_text(encoding="utf-8"))
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        params = _make_doc_symbol_params(uri)
        result = document_symbols(mock_ls, params)

        # Must return at least one symbol (the "start" label).
        assert (
            result
        ), f"document_symbols must return symbols when file_scopes is populated. Got: {result}"
        # The "start" label must be in the results.
        symbol_names = [s.name for s in result]
        assert (
            "start" in symbol_names
        ), f"document_symbols must include the 'start' label. Got: {symbol_names}"

    def test_document_symbols_does_not_populate_file_scopes(self, tmp_path: Path):
        """document_symbols must not add to analyzer.file_scopes.

        Direct assertion on the analyzer state: after calling
        document_symbols with an empty file_scopes, the dict must still
        be empty (no side-effect mutation).
        """
        project_root = _setup_project_with_label(tmp_path)
        analyzer = _initialize_lsp_without_full_analysis(project_root)

        script_path = str(project_root / "game" / "script.rpy")
        norm_path = server_mod._normalize_path(script_path)
        assert (
            norm_path not in analyzer.file_scopes
        ), "Test setup: file_scopes must be empty before document_symbols."

        uri = server_mod._path_to_uri(script_path)
        doc = MockDocument(uri, (project_root / "game" / "script.rpy").read_text(encoding="utf-8"))
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        params = _make_doc_symbol_params(uri)
        document_symbols(mock_ls, params)

        # file_scopes must still NOT contain the path — no mutation.
        assert norm_path not in analyzer.file_scopes, (
            "document_symbols must NOT populate analyzer.file_scopes. "
            f"After the call, file_scopes contains: {list(analyzer.file_scopes)}. "
            "This is a mutation under the read lock — violates _RWLock contract."
        )
