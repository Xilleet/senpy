"""Characterization tests для text_document LSP handlers (0.6.0-1).

Safety net перед рефакторингом lsp/server.py в class SenpyLSPServer.
Проверяем что did_open/save/change/close/watched/initialized — корректно
делегируют в schedule_* функции и не падают на edge cases.

Эти тесты закрепляют текущее поведение, чтобы при переносе в
handlers/text_document.py ничего не сломалось.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from lsprotocol import types as lsp

from test_lsp import MockDocument, MockWorkspace, setup_test_workspace

import senpy.lsp.server as server_mod


# =============================================================================
# did_open — UX-1
# =============================================================================

def test_did_open_rpy_schedules_full_diagnostics(tmp_path: Path):
    """did_open для .rpy файла должен запустить schedule_full_diagnostics."""
    setup_test_workspace(tmp_path)
    script_file = tmp_path / "game" / "script.rpy"
    uri = server_mod._path_to_uri(str(script_file))

    mock_ls = MagicMock()

    with patch.object(server_mod, "schedule_full_diagnostics") as mock_schedule:
        params = lsp.DidOpenTextDocumentParams(
            text_document=lsp.TextDocumentItem(
                uri=uri, language_id="renpy", version=1, text="label start:"
            )
        )
        server_mod.did_open(mock_ls, params)
        mock_schedule.assert_called_once_with(mock_ls, uri)


def test_did_open_non_rpy_does_nothing(tmp_path: Path):
    """did_open для .py/.txt/.json — НЕ должен запускать schedule."""
    setup_test_workspace(tmp_path)
    mock_ls = MagicMock()

    with patch.object(server_mod, "schedule_full_diagnostics") as mock_schedule:
        params = lsp.DidOpenTextDocumentParams(
            text_document=lsp.TextDocumentItem(
                uri="file:///test/script.py", language_id="python", version=1, text=""
            )
        )
        server_mod.did_open(mock_ls, params)
        mock_schedule.assert_not_called()


# =============================================================================
# did_save — UX-3
# =============================================================================

def test_did_save_rpy_schedules_full_diagnostics(tmp_path: Path):
    """did_save для .rpy должен запустить полный пересканирование."""
    setup_test_workspace(tmp_path)
    script_file = tmp_path / "game" / "script.rpy"
    uri = server_mod._path_to_uri(str(script_file))

    mock_ls = MagicMock()

    with patch.object(server_mod, "schedule_full_diagnostics") as mock_schedule:
        params = lsp.DidSaveTextDocumentParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri)
        )
        server_mod.did_save(mock_ls, params)
        mock_schedule.assert_called_once_with(mock_ls, uri)


def test_did_save_non_rpy_does_nothing(tmp_path: Path):
    """did_save для не-.rpy — игнорируется."""
    setup_test_workspace(tmp_path)
    mock_ls = MagicMock()

    with patch.object(server_mod, "schedule_full_diagnostics") as mock_schedule:
        params = lsp.DidSaveTextDocumentParams(
            text_document=lsp.TextDocumentIdentifier(uri="file:///test/script.txt")
        )
        server_mod.did_save(mock_ls, params)
        mock_schedule.assert_not_called()


# =============================================================================
# did_change — UX-2
# =============================================================================

def test_did_change_rpy_schedules_change_diagnostics(tmp_path: Path):
    """did_change для .rpy запускает incremental analysis (single-file)."""
    setup_test_workspace(tmp_path)
    script_file = tmp_path / "game" / "script.rpy"
    uri = server_mod._path_to_uri(str(script_file))

    doc = MockDocument(uri, "label start:\n    jump ")
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    with patch.object(server_mod, "schedule_change_diagnostics") as mock_schedule:
        params = lsp.DidChangeTextDocumentParams(
            text_document=lsp.VersionedTextDocumentIdentifier(uri=uri, version=2),
            content_changes=[
                lsp.TextDocumentContentChangePartial(
                    range=lsp.Range(
                        start=lsp.Position(line=0, character=0),
                        end=lsp.Position(line=0, character=0),
                    ),
                    text="jump ",
                )
            ],
        )
        server_mod.did_change(mock_ls, params)
        mock_schedule.assert_called_once_with(mock_ls, uri)


def test_did_change_non_rpy_does_nothing(tmp_path: Path):
    """did_change для не-.rpy — игнорируется."""
    setup_test_workspace(tmp_path)
    mock_ls = MagicMock()

    with patch.object(server_mod, "schedule_change_diagnostics") as mock_schedule:
        params = lsp.DidChangeTextDocumentParams(
            text_document=lsp.VersionedTextDocumentIdentifier(
                uri="file:///test/script.py", version=2
            ),
            content_changes=[],
        )
        server_mod.did_change(mock_ls, params)
        mock_schedule.assert_not_called()


# =============================================================================
# did_close — UX-6
# =============================================================================

def test_did_close_clears_in_memory_buffer(tmp_path: Path):
    """did_close должен убрать файл из in-memory_files анализатора."""
    setup_test_workspace(tmp_path)
    script_file = tmp_path / "game" / "script.rpy"
    uri = server_mod._path_to_uri(str(script_file))

    norm_file = server_mod._normalize_path(str(script_file))
    # Симулируем что файл был в in-memory буфере
    assert server_mod._active_analyzer is not None
    server_mod._active_analyzer.in_memory_files[norm_file] = "label start:"

    mock_ls = MagicMock()
    params = lsp.DidCloseTextDocumentParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri)
    )
    server_mod.did_close(mock_ls, params)

    assert norm_file not in server_mod._active_analyzer.in_memory_files


def test_did_close_without_active_analyzer_does_not_crash(tmp_path: Path):
    """did_close при _active_analyzer = None — не должен крашиться."""
    setup_test_workspace(tmp_path)
    saved_analyzer = server_mod._active_analyzer
    server_mod._active_analyzer = None
    try:
        mock_ls = MagicMock()
        params = lsp.DidCloseTextDocumentParams(
            text_document=lsp.TextDocumentIdentifier(uri="file:///test/script.rpy")
        )
        # Не должно выбросить
        server_mod.did_close(mock_ls, params)
    finally:
        server_mod._active_analyzer = saved_analyzer


# =============================================================================
# did_change_watched_files — заглушка против спама в Output логе
# =============================================================================

def test_did_change_watched_files_is_noop(tmp_path: Path):
    """did_change_watched_files должен молча проглатывать события."""
    setup_test_workspace(tmp_path)
    mock_ls = MagicMock()

    params = lsp.DidChangeWatchedFilesParams(
        changes=[
            lsp.FileEvent(
                uri="file:///test/script.rpy",
                type=lsp.FileChangeType.Changed,
            )
        ]
    )
    # Не должно выбросить и не должно звать publish_diagnostics
    server_mod.did_change_watched_files(mock_ls, params)
    mock_ls.text_document_publish_diagnostics.assert_not_called()


# =============================================================================
# schedule_full_diagnostics — debounce logic
# =============================================================================

def test_schedule_full_diagnostics_cancels_previous_timer(tmp_path: Path):
    """Повторный вызов schedule_full_diagnostics отменяет предыдущий timer."""
    setup_test_workspace(tmp_path)
    mock_ls = MagicMock()
    uri = "file:///test/script.rpy"

    # Первый вызов создаёт timer
    server_mod._full_timer = None
    server_mod.schedule_full_diagnostics(mock_ls, uri)
    first_timer = server_mod._full_timer
    assert first_timer is not None

    # Второй вызов должен отменить первый
    with patch.object(first_timer, "cancel") as mock_cancel:
        server_mod.schedule_full_diagnostics(mock_ls, uri)
        mock_cancel.assert_called_once()

    # Cleanup: отменим timer, иначе он сработает через 0.3s и вызовет
    # run_full_project_diagnostics, который может упасть на cross-mount path.
    if server_mod._full_timer is not None:
        server_mod._full_timer.cancel()
        server_mod._full_timer = None


# =============================================================================
# schedule_change_diagnostics — debounce logic
# =============================================================================

def test_schedule_change_diagnostics_cancels_previous_timer(tmp_path: Path):
    """Повторный schedule_change_diagnostics отменяет предыдущий timer."""
    setup_test_workspace(tmp_path)
    script_file = tmp_path / "game" / "script.rpy"
    uri = server_mod._path_to_uri(str(script_file))

    doc = MockDocument(uri, "label start:")
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    server_mod._change_timer = None
    server_mod.schedule_change_diagnostics(mock_ls, uri)
    first_timer = server_mod._change_timer
    assert first_timer is not None

    with patch.object(first_timer, "cancel") as mock_cancel:
        server_mod.schedule_change_diagnostics(mock_ls, uri)
        mock_cancel.assert_called_once()

    # Cleanup: отменим timer, иначе он сработает через 0.15s и вызовет
    # run_single_file_diagnostics, который может упасть на cross-mount path
    # (Windows: tmp_path на C:, project на D:). Это причина
    # PytestUnhandledThreadExceptionWarning в последующих test_p0_cli тестах.
    if server_mod._change_timer is not None:
        server_mod._change_timer.cancel()
        server_mod._change_timer = None
    for t in server_mod._lsp_server.change_timers.values():
        t.cancel()
    server_mod._lsp_server.change_timers.clear()


def test_schedule_change_diagnostics_skips_unknown_uri(tmp_path: Path):
    """schedule_change_diagnostics молча выходит, если документ не найден."""
    setup_test_workspace(tmp_path)
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(MockDocument("file:///other.rpy", ""))

    server_mod._change_timer = None
    # URI которого нет в workspace — не должен упасть
    server_mod.schedule_change_diagnostics(mock_ls, "file:///unknown.rpy")
    # timer не должен быть создан
    assert server_mod._change_timer is None


def test_schedule_change_diagnostics_per_uri_isolation(tmp_path: Path):
    """P1'-8 (0.6.0-11): per-URI debounce — timer'ы для разных URI не конфликтуют.

    Раньше _change_timer был один на все URI. При редактировании двух файлов
    одновременно, scheduling timer для file2 отменял pending timer для file1.
    Теперь каждый URI имеет свой timer.
    """
    setup_test_workspace(tmp_path)

    doc1 = MockDocument("file:///test/file1.rpy", "label a:")
    doc2 = MockDocument("file:///test/file2.rpy", "label b:")

    class DualWorkspace:
        """Workspace, отдающий разные документы для разных URI."""
        def __init__(self):
            self._docs = {
                "file:///test/file1.rpy": doc1,
                "file:///test/file2.rpy": doc2,
            }
        def get_text_document(self, uri: str):
            return self._docs.get(uri)

    mock_ls = MagicMock()
    mock_ls.workspace = DualWorkspace()

    # Сбросим состояние
    server_mod._change_timer = None
    server_mod._lsp_server.change_timers.clear()

    # Schedule для file1
    server_mod.schedule_change_diagnostics(mock_ls, "file:///test/file1.rpy")
    timer1 = server_mod._lsp_server.change_timers.get("file:///test/file1.rpy")
    assert timer1 is not None, "Timer для file1 должен быть создан"

    # Schedule для file2 — НЕ должен отменить timer для file1
    server_mod.schedule_change_diagnostics(mock_ls, "file:///test/file2.rpy")
    timer2 = server_mod._lsp_server.change_timers.get("file:///test/file2.rpy")
    assert timer2 is not None, "Timer для file2 должен быть создан"
    assert timer1 is not timer2, "Timer'ы для разных URI должны быть разными объектами"

    # Timer для file1 всё ещё в dict'е (не отменён timer'ом для file2)
    assert "file:///test/file1.rpy" in server_mod._lsp_server.change_timers

    # Очистка
    timer1.cancel()
    timer2.cancel()
    server_mod._lsp_server.change_timers.clear()
    server_mod._change_timer = None


def test_schedule_change_diagnostics_same_uri_cancels_previous(tmp_path: Path):
    """P1'-8: повторный schedule для того же URI отменяет предыдущий timer."""
    setup_test_workspace(tmp_path)
    uri = "file:///test/script.rpy"
    doc = MockDocument(uri, "label a:")

    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    server_mod._change_timer = None
    server_mod._lsp_server.change_timers.clear()

    server_mod.schedule_change_diagnostics(mock_ls, uri)
    first_timer = server_mod._lsp_server.change_timers[uri]

    with patch.object(first_timer, "cancel") as mock_cancel:
        server_mod.schedule_change_diagnostics(mock_ls, uri)
        mock_cancel.assert_called_once()

    # Cleanup: отменим timer'ы перед очисткой dict, иначе они сработают
    # через 0.15s и вызовут run_single_file_diagnostics (cross-mount crash).
    for t in server_mod._lsp_server.change_timers.values():
        t.cancel()
    server_mod._lsp_server.change_timers.clear()
    if server_mod._change_timer is not None:
        server_mod._change_timer.cancel()
        server_mod._change_timer = None


# =============================================================================
# run_single_file_diagnostics — fallback path
# =============================================================================

def test_run_single_file_without_active_analyzer_schedules_full(tmp_path: Path):
    """Если _active_analyzer = None — single-file fallback на full scan."""
    setup_test_workspace(tmp_path)
    saved_analyzer = server_mod._active_analyzer
    saved_init = server_mod._is_initialized
    server_mod._active_analyzer = None
    server_mod._is_initialized = False
    try:
        mock_ls = MagicMock()
        with patch.object(server_mod, "schedule_full_diagnostics") as mock_schedule:
            server_mod.run_single_file_diagnostics(mock_ls, "file:///test.rpy", "label start:")
            mock_schedule.assert_called_once()
    finally:
        server_mod._active_analyzer = saved_analyzer
        server_mod._is_initialized = saved_init


# =============================================================================
# _normalize_path — P0-6 контракт
# =============================================================================

def test_normalize_path_idempotent():
    """_normalize_path должен быть идемпотентным."""
    p1 = server_mod._normalize_path("/foo/bar/script.rpy")
    p2 = server_mod._normalize_path(p1)
    assert p1 == p2


def test_normalize_path_handles_relative(tmp_path: Path, monkeypatch):
    """_normalize_path должен разворачивать относительные пути."""
    import os
    monkeypatch.chdir(tmp_path)
    p = server_mod._normalize_path("script.rpy")
    assert os.path.isabs(p)
    assert p.endswith("script.rpy")
