"""TDD-тест: LSP-гонка — читатели реестров без _analysis_lock.

Писатели (run_full_project_diagnostics / run_single_file_diagnostics) мутируют
реестры _active_analyzer только под _analysis_lock, а читающие обработчики
(completions / definition / hover / document_symbols / code_action) читают те
же реестры без лока: возможны "RuntimeError: dictionary changed size during
iteration", половинные снапшоты и запись _collect_symbols в file_scopes
посреди чужого run().

Эталонное поведение: читатель, запущенный при занятом локе, ОБЯЗАН ждать
освобождения и только потом читать (детерминированная проверка, не стресс).
"""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

from lsprotocol import types as lsp

import senpy.server as server_mod
from senpy.analyzer import SenpyAnalyzer


class MockDocument:
    def __init__(self, uri: str, content: str):
        self.uri = uri
        self.lines = content.splitlines(keepends=True)


class MockWorkspace:
    def __init__(self, doc: MockDocument):
        self.doc = doc

    def get_text_document(self, uri: str):
        return self.doc if self.doc.uri == uri else None


def setup_test_workspace(tmp_path: Path):
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    script_file = game_dir / "script.rpy"
    script_file.write_text(
        """
default player_gold = 100

label start:
    $ player_gold += 10
    jump forest_scene

label forest_scene:
    return
""",
        encoding="utf-8",
    )
    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    return script_file, analyzer


def _assert_reader_blocked_by_lock(mock_ls, params, handler):
    """Читатель при занятом _analysis_lock обязан ждать; после освобождения — доделать."""
    finished = threading.Event()

    def reader():
        handler(mock_ls, params)
        finished.set()

    with server_mod._analysis_lock:
        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t.join(timeout=0.5)
        assert not finished.is_set(), (
            f"{handler.__name__} прочитал реестры анализатора, НЕ дождавшись "
            "_analysis_lock — гонка с run_full/run_single_diagnostics"
        )
    t.join(timeout=2.0)
    assert finished.is_set(), f"{handler.__name__} не завершился после освобождения лока"


def test_completions_waits_for_analysis_lock(tmp_path: Path):
    script_file, _ = setup_test_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(MockDocument(uri, "label test:\n    jump "))
    params = lsp.CompletionParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=1, character=9),
    )
    _assert_reader_blocked_by_lock(mock_ls, params, server_mod.completions)


def test_definition_waits_for_analysis_lock(tmp_path: Path):
    script_file, _ = setup_test_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(MockDocument(uri, "label start:\n    jump forest_scene\n"))
    params = lsp.DefinitionParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=1, character=9),  # на слове forest_scene
    )
    _assert_reader_blocked_by_lock(mock_ls, params, server_mod.definition)


def test_document_symbols_waits_for_analysis_lock(tmp_path: Path):
    script_file, _ = setup_test_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(MockDocument(uri, "label start:\n    return\n"))
    params = lsp.DocumentSymbolParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
    )
    _assert_reader_blocked_by_lock(mock_ls, params, server_mod.document_symbols)