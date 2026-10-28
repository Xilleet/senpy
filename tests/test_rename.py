"""Тесты для UX-2: textDocument/rename — переименование меток.

Проверяет, что rename() правильно:
1. Находит объявление label
2. Находит все jump/call ссылки на него
3. Возвращает WorkspaceEdit с правильными TextEdit'ами
4. Возвращает None для переименования переменной (пока не поддерживается)
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from lsprotocol import types as lsp

import senpy.server as server_mod
from senpy.analyzer import SenpyAnalyzer
from tests.test_lsp import MockDocument, MockWorkspace, setup_test_workspace


def _make_rename_params(uri: str, line: int, char: int, new_name: str) -> lsp.RenameParams:
    """Создаёт RenameParams для теста."""
    return lsp.RenameParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=line, character=char),
        new_name=new_name,
    )


def _read_script(tmp_path: Path) -> str:
    """Читает содержимое test script.rpy (SIM115-safe)."""
    return (tmp_path / "game" / "script.rpy").read_text(encoding="utf-8")


def test_rename_label_updates_declaration_and_jumps(tmp_path: Path):
    """Rename метки: обновляет объявление + все jump/call."""
    setup_test_workspace(tmp_path)

    # script.rpy (0-based line numbers):
    #  0: (empty)
    #  1: default player_gold = 100
    #  ...
    #  8: label start:
    #  9:     $ player_gold += 10
    # 10:     show sayori happy
    # 11:     jump forest_scene    <-- cursor here
    # 12: (empty)
    # 13: label forest_scene:      <-- declaration
    # 14:     "В лесу..."
    # 15:     jump deep_cave

    uri = "file:///test/script.rpy"
    doc = MockDocument(uri, _read_script(tmp_path))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    # Курсор на "forest_scene" в строке 11 (0-based) — jump forest_scene
    params = _make_rename_params(uri, line=11, char=10, new_name="new_forest")

    result = server_mod.rename(mock_ls, params)

    assert result is not None, "Rename должен вернуть WorkspaceEdit"
    assert result.changes is not None, "WorkspaceEdit должен содержать changes"

    # Должен быть хотя бы 1 файл с изменениями
    assert len(result.changes) > 0, "Должны быть изменения"

    # Соберём все TextEdit'ы
    all_edits = []
    for file_uri, edits in result.changes.items():
        all_edits.extend(edits)

    # Должно быть минимум 2 изменения:
    # 1. Объявление label forest_scene: (строка 13, 0-based)
    # 2. jump forest_scene (строка 11, 0-based)
    assert len(all_edits) >= 2, f"Ожидалось >= 2 изменений, получено {len(all_edits)}"

    # Проверим, что все новые тексты = "new_forest"
    for edit in all_edits:
        assert edit.new_text == "new_forest", f"Ожидался 'new_forest', получено '{edit.new_text}'"


def test_rename_label_from_declaration(tmp_path: Path):
    """Rename метки при клике на объявлении (label X:)."""
    setup_test_workspace(tmp_path)

    uri = "file:///test/script.rpy"
    doc = MockDocument(uri, _read_script(tmp_path))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    # Курсор на "forest_scene" в строке 13 (0-based) — label forest_scene:
    params = _make_rename_params(uri, line=13, char=6, new_name="renamed_forest")

    result = server_mod.rename(mock_ls, params)

    assert result is not None
    assert result.changes is not None

    all_edits = []
    for file_uri, edits in result.changes.items():
        all_edits.extend(edits)

    # Должно быть 2+ изменения (объявление + jump)
    assert len(all_edits) >= 2, f"Ожидалось >= 2 изменений, получено {len(all_edits)}"

    for edit in all_edits:
        assert edit.new_text == "renamed_forest"


def test_rename_returns_none_for_variable(tmp_path: Path):
    """Rename переменной (пока не поддерживается) — должен вернуть None."""
    setup_test_workspace(tmp_path)

    uri = "file:///test/script.rpy"
    doc = MockDocument(uri, _read_script(tmp_path))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    # Курсор на "player_gold" в строке 1 (0-based) — default player_gold = 100
    params = _make_rename_params(uri, line=1, char=8, new_name="new_gold")

    result = server_mod.rename(mock_ls, params)

    # Пока rename поддерживает только label'ы
    assert result is None, f"Rename переменной должен вернуть None, получено {result}"


def test_rename_returns_none_for_nonexistent_word(tmp_path: Path):
    """Rename на пустом/несуществующем слове — None."""
    setup_test_workspace(tmp_path)

    uri = "file:///test/script.rpy"
    doc = MockDocument(uri, _read_script(tmp_path))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    # Курсор в начале файла (пустая строка, 0-based line 0)
    params = _make_rename_params(uri, line=0, char=0, new_name="whatever")

    result = server_mod.rename(mock_ls, params)

    assert result is None, f"Rename на пустом слове должен вернуть None, получено {result}"


def test_rename_label_preserves_jump_syntax(tmp_path: Path):
    """Rename метки: проверяет что jump/call синтаксис сохраняется."""
    setup_test_workspace(tmp_path)

    # Создадим файл с call
    game_dir = tmp_path / "game"
    (game_dir / "script2.rpy").write_text(
        'label start:\n    call my_label()\n    return\n\nlabel my_label:\n    "Hello"\n    return\n',
        encoding="utf-8",
    )
    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    # UX-EXT-5: snapshot для autocomplete/rename (handler'ы теперь используют snapshot)
    server_mod._refresh_symbol_snapshot()

    # 0-based lines:
    # 0: label start:
    # 1:     call my_label()
    # 2:     return
    # 3: (empty)
    # 4: label my_label:       <-- cursor here
    # 5:     "Hello"
    # 6:     return

    uri = "file:///test/script2.rpy"
    script2_content = (game_dir / "script2.rpy").read_text(encoding="utf-8")
    doc = MockDocument(uri, script2_content)
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    # Курсор на "my_label" в строке 4 (0-based) — label my_label:
    params = _make_rename_params(uri, line=4, char=6, new_name="greeting")

    result = server_mod.rename(mock_ls, params)

    assert result is not None
    assert result.changes is not None

    all_edits = []
    for file_uri, edits in result.changes.items():
        all_edits.extend(edits)

    # Должно быть 2 изменения: объявление + call
    assert len(all_edits) >= 2, f"Ожидалось >= 2 изменений, получено {len(all_edits)}"

    for edit in all_edits:
        assert edit.new_text == "greeting"
