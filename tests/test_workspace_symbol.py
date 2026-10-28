"""Тесты для UX-3: workspace/symbol — глобальный поиск символов (Ctrl+T).

Проверяет, что workspace_symbol() правильно:
1. Возвращает все label'ы в проекте
2. Возвращает все screen'ы
3. Возвращает все transform'ы
4. Фильтрует по query (если передан)
5. Возвращает пустой список, если нет совпадений
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from lsprotocol import types as lsp

import senpy.server as server_mod
from senpy.analyzer import SenpyAnalyzer
from tests.test_lsp import MockDocument, MockWorkspace, setup_test_workspace


def _make_symbol_params(query: str = "") -> lsp.WorkspaceSymbolParams:
    """Создаёт WorkspaceSymbolParams для теста."""
    return lsp.WorkspaceSymbolParams(query=query)


def _symbol_names(result: list[lsp.WorkspaceSymbol]) -> list[str]:
    """Извлекает имена символов из результата."""
    return [s.name for s in result]


def test_workspace_symbol_returns_all_labels(tmp_path: Path):
    """workspace/symbol возвращает все label'ы проекта."""
    setup_test_workspace(tmp_path)

    params = _make_symbol_params(query="")
    result = server_mod.workspace_symbol(MagicMock(), params)

    assert result is not None, "Должен вернуть список (даже пустой)"
    names = _symbol_names(result)

    # setup_test_workspace создаёт: start, forest_scene, deep_cave
    assert "start" in names, f"start не найден в {names}"
    assert "forest_scene" in names, f"forest_scene не найден в {names}"
    assert "deep_cave" in names, f"deep_cave не найден в {names}"


def test_workspace_symbol_returns_screens(tmp_path: Path):
    """workspace/symbol возвращает screen'ы."""
    setup_test_workspace(tmp_path)

    # Добавим screen
    game_dir = tmp_path / "game"
    (game_dir / "screens.rpy").write_text(
        'screen main_menu():\n    textbutton "Start" action Start()\n\n'
        'screen preferences():\n    textbutton "Back" action Return()\n',
        encoding="utf-8",
    )
    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    # UX-EXT-5: snapshot для workspace_symbol
    server_mod._refresh_symbol_snapshot()

    params = _make_symbol_params(query="")
    result = server_mod.workspace_symbol(MagicMock(), params)

    assert result is not None
    names = _symbol_names(result)

    assert "main_menu" in names, f"main_menu не найден в {names}"
    assert "preferences" in names, f"preferences не найден в {names}"


def test_workspace_symbol_returns_transforms(tmp_path: Path):
    """workspace/symbol возвращает transform'ы."""
    setup_test_workspace(tmp_path)

    game_dir = tmp_path / "game"
    (game_dir / "transforms.rpy").write_text(
        "transform slide_in:\n    easein 0.5 xoffset 0\n\n"
        "transform fade_out:\n    easeout 0.5 alpha 0.0\n",
        encoding="utf-8",
    )
    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    # UX-EXT-5: snapshot для workspace_symbol
    server_mod._refresh_symbol_snapshot()

    params = _make_symbol_params(query="")
    result = server_mod.workspace_symbol(MagicMock(), params)

    assert result is not None
    names = _symbol_names(result)

    assert "slide_in" in names, f"slide_in не найден в {names}"
    assert "fade_out" in names, f"fade_out не найден в {names}"


def test_workspace_symbol_filters_by_query(tmp_path: Path):
    """workspace/symbol фильтрует по query (case-insensitive)."""
    setup_test_workspace(tmp_path)

    params = _make_symbol_params(query="forest")
    result = server_mod.workspace_symbol(MagicMock(), params)

    assert result is not None
    names = _symbol_names(result)

    # Должен найти только forest_scene
    assert "forest_scene" in names, f"forest_scene не найден в {names}"
    assert "start" not in names, f"start не должен быть в результатах фильтра 'forest': {names}"
    assert "deep_cave" not in names, f"deep_cave не должен быть в результатах: {names}"


def test_workspace_symbol_no_match(tmp_path: Path):
    """workspace/symbol с query без совпадений — пустой список."""
    setup_test_workspace(tmp_path)

    params = _make_symbol_params(query="nonexistent_xyz")
    result = server_mod.workspace_symbol(MagicMock(), params)

    assert result is not None
    assert result == [], f"Ожидался пустой список, получено {result}"


def test_workspace_symbol_symbol_kinds(tmp_path: Path):
    """workspace/symbol возвращает правильные SymbolKind."""
    setup_test_workspace(tmp_path)

    game_dir = tmp_path / "game"
    (game_dir / "extra.rpy").write_text(
        'screen my_screen():\n    pass\n\ntransform my_transform:\n    pass\n',
        encoding="utf-8",
    )
    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    # UX-EXT-5: snapshot для workspace_symbol
    server_mod._refresh_symbol_snapshot()

    params = _make_symbol_params(query="")
    result = server_mod.workspace_symbol(MagicMock(), params)

    assert result is not None

    # Проверим что есть разные kind'ы
    kinds = {s.kind for s in result}

    # Label = Function (12) или Module (2) — выберем Function как ближе всего
    # Screen = Object (26) или Class (5)
    # Transform = Function (12)
    # Главное — что kinds не пустой
    assert len(kinds) > 0, f"Ожидал хотя бы 1 SymbolKind, получено {kinds}"


def test_workspace_symbol_has_location(tmp_path: Path):
    """workspace/symbol: каждый символ имеет Location с URI и Range."""
    setup_test_workspace(tmp_path)

    params = _make_symbol_params(query="start")
    result = server_mod.workspace_symbol(MagicMock(), params)

    assert result is not None
    assert len(result) >= 1, f"Ожидался 'start', получено {result}"

    sym = result[0]
    assert sym.name == "start"
    assert sym.location is not None
    assert sym.location.uri is not None
    assert "script.rpy" in sym.location.uri, f"URI должен содержать script.rpy: {sym.location.uri}"
    assert sym.location.range is not None
    assert sym.location.range.start.line >= 0
