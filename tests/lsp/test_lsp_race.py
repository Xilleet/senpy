"""LSP-гонка — читатели реестров под RWLock write lock.

Писатели (run_full_project_diagnostics / run_single_file_diagnostics) мутируют
реестры _active_analyzer только под write lock rw_lock, а читающие обработчики
(completions / definition / hover / document_symbols / code_action) берут read
lock: возможны "RuntimeError: dictionary changed size during iteration",
половинные снапшоты и запись _collect_symbols в file_scopes посреди чужого run().

Эталонное поведение: читатель, запущенный при занятом write lock, ОБЯЗАН ждать
его освобождения и только потом читать (детерминированная проверка, не стресс).

Историческая справка: до 0.8.0 использовался module-level
``_analysis_lock`` (exclusive threading.Lock) поверх RWLock read lock — это
сериализовало всех reader'ов. После 0.8.0 exclusive lock удалён, RWLock стал
единственным механизмом синхронизации. Эти тесты теперь берут write lock
и проверяют, что reader под read lock ждёт его освобождения.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

from lsprotocol import types as lsp

import senpy.lsp.server as server_mod
from senpy.core.analyzer import SenpyAnalyzer


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
    server_mod._lsp_server.active_analyzer = analyzer
    server_mod._lsp_server.is_initialized = True
    return script_file, analyzer


def _assert_reader_blocked_by_write_lock(mock_ls, params, handler):
    """Читатель при занятом write lock обязан ждать; после освобождения — доделать."""
    finished = threading.Event()

    def reader():
        handler(mock_ls, params)
        finished.set()

    # Берём write lock — reader (под read lock) обязан ждать.
    with server_mod._lsp_server.rw_lock.write_lock():
        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t.join(timeout=0.5)
        assert not finished.is_set(), (
            f"{handler.__name__} прочитал реестры анализатора, НЕ дождавшись "
            "write lock — гонка с run_full/run_single_diagnostics"
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
    _assert_reader_blocked_by_write_lock(mock_ls, params, server_mod.completions)


def test_definition_waits_for_analysis_lock(tmp_path: Path):
    script_file, _ = setup_test_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(MockDocument(uri, "label start:\n    jump forest_scene\n"))
    params = lsp.DefinitionParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=1, character=9),  # на слове forest_scene
    )
    _assert_reader_blocked_by_write_lock(mock_ls, params, server_mod.definition)


def test_document_symbols_waits_for_analysis_lock(tmp_path: Path):
    script_file, _ = setup_test_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(MockDocument(uri, "label start:\n    return\n"))
    params = lsp.DocumentSymbolParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
    )
    _assert_reader_blocked_by_write_lock(mock_ls, params, server_mod.document_symbols)


def test_did_close_waits_for_write_lock(tmp_path: Path):
    """did_close мутирует ``_active_analyzer.in_memory_files`` — это writer.

    Пока внешний writer (run_full / run_single_file_diagnostics) держит
    write lock, did_close обязан ждать его освобождения. Без блокировки
    возможна гонка: did_close выкидывает ключ из ``in_memory_files``
    посреди записи ``run_single_file_diagnostics``, и reader видит
    половинное состояние реестра.
    """
    script_file, _ = setup_test_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))
    mock_ls = MagicMock()
    params = lsp.DidCloseTextDocumentParams(text_document=lsp.TextDocumentIdentifier(uri=uri))
    _assert_reader_blocked_by_write_lock(mock_ls, params, server_mod.did_close)
