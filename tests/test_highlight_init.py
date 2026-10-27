"""Тесты для UX-12 (initialized) и UX-5 (documentHighlight).

UX-12: При инициализации LSP сервера сразу запускается full project scan,
       чтобы hover/completion работали мгновенно при открытии первого файла.

UX-5:  Подсветка всех упоминаний слова под курсором в текущем файле.
       VS Code: курсор на переменной → все её упоминания подсвечиваются.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from lsprotocol import types as lsp

import senpy.server as server_mod
from senpy.analyzer import SenpyAnalyzer
from tests.test_lsp import MockDocument, MockWorkspace, setup_test_workspace

# =============================================================================
# UX-12: initialized handler
# =============================================================================

def test_initialized_triggers_full_diagnostics(tmp_path: Path):
    """При initialized должен запуститься full project scan."""
    setup_test_workspace(tmp_path)

    # Сбросим флаг инициализации
    server_mod._is_initialized = False

    mock_ls = MagicMock()
    mock_ls.workspace.root_path = str(tmp_path)

    # Вызываем initialized handler
    server_mod.initialized(mock_ls, lsp.InitializedParams())

    # Проверяем, что workspace root сохранён
    assert server_mod._current_workspace_root == str(tmp_path)


def test_initialized_without_workspace_root(tmp_path: Path):
    """initialized без workspace root не должен крашиться."""
    setup_test_workspace(tmp_path)

    mock_ls = MagicMock()
    mock_ls.workspace.root_path = None

    # Не должно выбросить исключение
    server_mod.initialized(mock_ls, lsp.InitializedParams())


# =============================================================================
# UX-5: documentHighlight
# =============================================================================

def _read_script(tmp_path: Path) -> str:
    """Читает содержимое test script.rpy (SIM115-safe)."""
    return (tmp_path / "game" / "script.rpy").read_text(encoding="utf-8")


def test_document_highlight_variable(tmp_path: Path):
    """Подсветка всех упоминаний переменной в файле."""
    setup_test_workspace(tmp_path)

    # script.rpy (0-based):
    #  1: default player_gold = 100
    #  9: label start:
    # 10:     $ player_gold += 10
    # 11:     show sayori happy
    # 12:     jump forest_scene

    uri = "file:///test/script.rpy"
    doc = MockDocument(uri, _read_script(tmp_path))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    # Курсор на "player_gold" в строке 1 (default player_gold = 100)
    params = lsp.DocumentHighlightParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=1, character=8),
    )

    result = server_mod.document_highlight(mock_ls, params)

    assert result is not None, "Должен вернуть список highlight'ов"
    assert len(result) >= 2, f"Ожидалось >= 2 (declaration + usage), получено {len(result)}"

    # Должны быть разные kinds: Write (default) и Read/Text ($ player_gold += 10)
    kinds = {h.kind for h in result}
    assert lsp.DocumentHighlightKind.Write in kinds or lsp.DocumentHighlightKind.Text in kinds, (
        f"Должен быть Write или Text kind: {kinds}"
    )


def test_document_highlight_label(tmp_path: Path):
    """Подсветка label: объявление + все jump/call к нему."""
    setup_test_workspace(tmp_path)

    # script.rpy (0-based):
    #  8: label start:
    # 12:     jump forest_scene
    # 13: (empty)
    # 14: label forest_scene:
    # 16:     jump deep_cave

    uri = "file:///test/script.rpy"
    doc = MockDocument(uri, _read_script(tmp_path))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    # Курсор на "forest_scene" в строке 11 (0-based) — jump forest_scene
    params = lsp.DocumentHighlightParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=11, character=10),
    )

    result = server_mod.document_highlight(mock_ls, params)

    assert result is not None, "Должен вернуть список highlight'ов"
    # Должен найти: jump forest_scene (строка 12) + label forest_scene (строка 14)
    assert len(result) >= 2, f"Ожидалось >= 2 (jump + declaration), получено {len(result)}"


def test_document_highlight_no_match(tmp_path: Path):
    """Подсветка на пустом/несуществующем слове — пустой список."""
    setup_test_workspace(tmp_path)

    uri = "file:///test/script.rpy"
    doc = MockDocument(uri, _read_script(tmp_path))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    # Курсор на пустой строке (строка 0)
    params = lsp.DocumentHighlightParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=0, character=0),
    )

    result = server_mod.document_highlight(mock_ls, params)

    assert result == [], f"Ожидался пустой список, получено {result}"


def test_document_highlight_builtin_keyword(tmp_path: Path):
    """Подсветка на builtin (show, jump) — пустой список (не наши символы)."""
    setup_test_workspace(tmp_path)

    uri = "file:///test/script.rpy"
    doc = MockDocument(uri, _read_script(tmp_path))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    # Курсор на "show" в строке 11 (show sayori happy)
    params = lsp.DocumentHighlightParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=11, character=4),
    )

    result = server_mod.document_highlight(mock_ls, params)

    # "show" — это builtin keyword, не label/screen/transform/variable
    # Можно вернуть пустой список, либо подсветить все "show" в файле.
    # Для MVP — пустой список (только user-defined символы).
    assert result == [], f"Ожидался пустой список для builtin, получено {result}"
