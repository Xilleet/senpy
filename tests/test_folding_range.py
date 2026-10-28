"""Тесты для UX-1: textDocument/foldingRange.

Проверяет, что folding_range() правильно определяет границы сворачиваемых блоков:
label, screen, menu, init python, transform, python.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from lsprotocol import types as lsp
from test_lsp import MockDocument, MockWorkspace, setup_test_workspace

import senpy.server as server_mod
from senpy.analyzer import SenpyAnalyzer


def test_folding_range_label_blocks(tmp_path: Path):
    """Folding ranges для label блоков."""
    setup_test_workspace(tmp_path)

    content = """label start:
    "Hello"
    jump chapter2

label chapter2:
    "World"
    return
"""
    uri = "file:///test/script.rpy"
    doc = MockDocument(uri, content)
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    params = lsp.FoldingRangeParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
    )

    result = server_mod.folding_range(mock_ls, params)

    # Должно быть 2 folding range (по одному на каждый label)
    assert len(result) == 2, f"Expected 2 folding ranges, got {len(result)}: {result}"

    # label start: строки 0-2 (0-based)
    assert result[0].start_line == 0
    assert result[0].end_line == 2

    # label chapter2: строки 4-6
    assert result[1].start_line == 4
    assert result[1].end_line == 6


def test_folding_range_screen_block(tmp_path: Path):
    """Folding range для screen блока."""
    setup_test_workspace(tmp_path)

    content = """screen main_menu():
    textbutton "Start" action Start()
    textbutton "Quit" action Quit()
"""
    uri = "file:///test/script.rpy"
    doc = MockDocument(uri, content)
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    params = lsp.FoldingRangeParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
    )

    result = server_mod.folding_range(mock_ls, params)

    assert len(result) == 1, f"Expected 1 folding range, got {len(result)}"
    assert result[0].start_line == 0
    assert result[0].end_line == 2


def test_folding_range_menu_block(tmp_path: Path):
    """Folding range для menu блока."""
    setup_test_workspace(tmp_path)

    content = """label start:
    menu:
        "Option 1":
            "You chose 1"
        "Option 2":
            "You chose 2"
    return
"""
    uri = "file:///test/script.rpy"
    doc = MockDocument(uri, content)
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    params = lsp.FoldingRangeParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
    )

    result = server_mod.folding_range(mock_ls, params)

    # Должно быть 2 range: label start + menu
    assert len(result) == 2, f"Expected 2 folding ranges, got {len(result)}"

    # label start: строки 0-6
    assert result[0].start_line == 0
    assert result[0].end_line == 6

    # menu: строки 1-5
    assert result[1].start_line == 1
    assert result[1].end_line == 5


def test_folding_range_init_python(tmp_path: Path):
    """Folding range для init python блока."""
    setup_test_workspace(tmp_path)

    content = """init python:
    config.developer = True
    import math
"""
    uri = "file:///test/script.rpy"
    doc = MockDocument(uri, content)
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    params = lsp.FoldingRangeParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
    )

    result = server_mod.folding_range(mock_ls, params)

    assert len(result) == 1, f"Expected 1 folding range, got {len(result)}"
    assert result[0].start_line == 0
    assert result[0].end_line == 2


def test_folding_range_empty_file(tmp_path: Path):
    """Пустой файл — нет folding ranges."""
    setup_test_workspace(tmp_path)

    uri = "file:///test/empty.rpy"
    doc = MockDocument(uri, "")
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    params = lsp.FoldingRangeParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
    )

    result = server_mod.folding_range(mock_ls, params)

    assert result == [], f"Expected empty list for empty file, got {result}"


def test_folding_range_no_blocks(tmp_path: Path):
    """Файл без scope-opening ключевых слов — нет folding ranges."""
    setup_test_workspace(tmp_path)

    content = '''# Just comments
# And dialogue
"Hello world"
'''
    uri = "file:///test/no_blocks.rpy"
    doc = MockDocument(uri, content)
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    params = lsp.FoldingRangeParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
    )

    result = server_mod.folding_range(mock_ls, params)

    assert result == [], f"Expected empty list for no blocks, got {result}"


def test_folding_range_nested_blocks(tmp_path: Path):
    """Вложенные блоки: label с menu внутри."""
    setup_test_workspace(tmp_path)

    content = """label start:
    menu:
        "Go left":
            jump left_path
        "Go right":
            jump right_path

label left_path:
    "You went left"
    return

label right_path:
    "You went right"
    return
"""
    uri = "file:///test/nested.rpy"
    doc = MockDocument(uri, content)
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    params = lsp.FoldingRangeParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
    )

    result = server_mod.folding_range(mock_ls, params)

    # 4 range: label start + menu + label left_path + label right_path
    assert len(result) == 4, f"Expected 4 folding ranges, got {len(result)}"

    # Проверяем, что все range имеют правильный kind
    for r in result:
        assert r.kind == lsp.FoldingRangeKind.Region


def test_folding_range_transform_block(tmp_path: Path):
    """Folding range для transform блока."""
    setup_test_workspace(tmp_path)

    content = """transform slide_in:
    easein 0.5 xoffset 0
    on update:
        pass
"""
    uri = "file:///test/transform.rpy"
    doc = MockDocument(uri, content)
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    params = lsp.FoldingRangeParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
    )

    result = server_mod.folding_range(mock_ls, params)

    assert len(result) >= 1, f"Expected at least 1 folding range, got {len(result)}"
    assert result[0].start_line == 0
