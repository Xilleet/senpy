"""LSP-17 + LSP-18: rename и references для variables/transform/screen.

До этого спринта rename/references работали только для labels.
После LSP-17/18 — поддерживаются variables, transforms, screens.

Контракт:
  - rename на variable → обновляет объявление (default/define) + все
    текстовые вхождения в .rpy файлах проекта.
  - rename на transform → обновляет объявление (transform X:) + все
    `show ... at X` / `with X` ссылки.
  - rename на screen → обновляет объявление (screen X:) + все
    `use X()` / `call screen X` / `show screen X` ссылки.
  - references на variable/transform/screen → возвращает все текстовые
    вхождения по всем .rpy файлам.
  - include_declaration flag уважается.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from lsprotocol import types as lsp

import senpy.lsp.server as server_mod
from senpy.core.analyzer import SenpyAnalyzer


class MockDocument:
    def __init__(self, uri: str, content: str):
        self.uri = uri
        self.lines = content.splitlines(keepends=True)
        self.source = content


class MockWorkspace:
    def __init__(self, doc: MockDocument):
        self.doc = doc

    def get_text_document(self, uri: str):
        return self.doc if self.doc.uri == uri else None


# =============================================================================
# rename для variables/transforms/screens
# =============================================================================

def test_rename_variable_updates_declaration_and_usage(tmp_path: Path):
    """LSP-17: rename variable — обновляет default + все использования."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)
    script = game_dir / "script.rpy"
    script.write_text(
        "default player_gold = 100\n"
        "\n"
        "label start:\n"
        '    "You have [player_gold] gold."\n'
        "    $ player_gold += 10\n"
        "    return\n",
        encoding="utf-8",
    )

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    server_mod._refresh_symbol_snapshot()

    uri = server_mod._path_to_uri(str(script))
    doc = MockDocument(uri, script.read_text(encoding="utf-8"))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    # Курсор на "player_gold" в строке 0 (default player_gold = 100)
    params = lsp.RenameParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=0, character=8),
        new_name="new_gold",
    )

    result = server_mod.rename(mock_ls, params)

    assert result is not None, "Rename variable should return WorkspaceEdit"
    assert result.changes is not None

    all_edits = []
    for file_uri, edits in result.changes.items():
        all_edits.extend(edits)

    # Должно быть минимум 3 изменения:
    # 1. default player_gold = 100  (declaration)
    # 2. [player_gold]              (interpolation in dialogue)
    # 3. $ player_gold += 10        (assignment)
    assert len(all_edits) >= 3, (
        f"Expected >= 3 edits for variable rename, got {len(all_edits)}"
    )

    for edit in all_edits:
        assert edit.new_text == "new_gold"


def test_rename_transform_updates_declaration_and_show_at(tmp_path: Path):
    """LSP-17: rename transform — обновляет transform X: + show ... at X."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)
    script = game_dir / "script.rpy"
    script.write_text(
        "transform slide_in:\n"
        "    ease 0.5 xalign 0.0\n"
        "\n"
        "label start:\n"
        "    show bg room at slide_in\n"
        "    return\n",
        encoding="utf-8",
    )

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    server_mod._refresh_symbol_snapshot()

    uri = server_mod._path_to_uri(str(script))
    doc = MockDocument(uri, script.read_text(encoding="utf-8"))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    # Курсор на "slide_in" в строке 0 (transform slide_in:)
    params = lsp.RenameParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=0, character=10),
        new_name="slide_left",
    )

    result = server_mod.rename(mock_ls, params)

    assert result is not None, "Rename transform should return WorkspaceEdit"
    assert result.changes is not None

    all_edits = []
    for file_uri, edits in result.changes.items():
        all_edits.extend(edits)

    # Минимум 2: объявление + show ... at slide_in
    assert len(all_edits) >= 2, (
        f"Expected >= 2 edits for transform rename, got {len(all_edits)}"
    )

    for edit in all_edits:
        assert edit.new_text == "slide_left"


def test_rename_screen_updates_declaration_and_use(tmp_path: Path):
    """LSP-17: rename screen — обновляет screen X(): + use X()."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)
    script = game_dir / "script.rpy"
    script.write_text(
        "screen confirm_dialog():\n"
        "    textbutton 'OK':\n"
        "        action Return()\n"
        "\n"
        "label start:\n"
        "    call screen confirm_dialog()\n"
        "    return\n",
        encoding="utf-8",
    )

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    server_mod._refresh_symbol_snapshot()

    uri = server_mod._path_to_uri(str(script))
    doc = MockDocument(uri, script.read_text(encoding="utf-8"))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    # Курсор на "confirm_dialog" в строке 0 (screen confirm_dialog():)
    params = lsp.RenameParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=0, character=7),
        new_name="ok_dialog",
    )

    result = server_mod.rename(mock_ls, params)

    assert result is not None, "Rename screen should return WorkspaceEdit"
    assert result.changes is not None

    all_edits = []
    for file_uri, edits in result.changes.items():
        all_edits.extend(edits)

    # Минимум 2: объявление + call screen confirm_dialog()
    assert len(all_edits) >= 2, (
        f"Expected >= 2 edits for screen rename, got {len(all_edits)}"
    )

    for edit in all_edits:
        assert edit.new_text == "ok_dialog"


# =============================================================================
# references для variables/transforms/screens
# =============================================================================

def test_references_variable_finds_all_usages(tmp_path: Path):
    """LSP-18: references на variable — все вхождения по проекту."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)
    script = game_dir / "script.rpy"
    script.write_text(
        "default player_gold = 100\n"
        "\n"
        "label start:\n"
        '    "You have [player_gold] gold."\n'
        "    $ player_gold += 10\n"
        "    return\n",
        encoding="utf-8",
    )

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    server_mod._refresh_symbol_snapshot()

    uri = server_mod._path_to_uri(str(script))
    doc = MockDocument(uri, script.read_text(encoding="utf-8"))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    # Курсор на "player_gold" в строке 0 (default player_gold = 100)
    params = lsp.ReferenceParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=0, character=8),
        context=lsp.ReferenceContext(include_declaration=True),
    )

    result = server_mod.references(mock_ls, params)

    assert result is not None, "References for variable should return locations"
    # Должно быть минимум 3: объявление + [player_gold] + $ player_gold += 10
    assert len(result) >= 3, (
        f"Expected >= 3 references for variable, got {len(result)}"
    )


def test_references_variable_without_declaration(tmp_path: Path):
    """LSP-18: references на variable с include_declaration=False."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)
    script = game_dir / "script.rpy"
    script.write_text(
        "default player_gold = 100\n"
        "\n"
        "label start:\n"
        '    "You have [player_gold] gold."\n'
        "    $ player_gold += 10\n"
        "    return\n",
        encoding="utf-8",
    )

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    server_mod._refresh_symbol_snapshot()

    uri = server_mod._path_to_uri(str(script))
    doc = MockDocument(uri, script.read_text(encoding="utf-8"))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    params = lsp.ReferenceParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=0, character=8),
        context=lsp.ReferenceContext(include_declaration=False),
    )

    result = server_mod.references(mock_ls, params)

    assert result is not None
    # Без объявления: [player_gold] + $ player_gold += 10 = 2
    assert len(result) >= 2


def test_references_transform_finds_show_at_usages(tmp_path: Path):
    """LSP-18: references на transform — все show ... at X."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)
    script = game_dir / "script.rpy"
    script.write_text(
        "transform slide_in:\n"
        "    ease 0.5 xalign 0.0\n"
        "\n"
        "label start:\n"
        "    show bg room at slide_in\n"
        "    show char happy at slide_in\n"
        "    return\n",
        encoding="utf-8",
    )

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    server_mod._refresh_symbol_snapshot()

    uri = server_mod._path_to_uri(str(script))
    doc = MockDocument(uri, script.read_text(encoding="utf-8"))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    # Курсор на "slide_in" в строке 0 (transform slide_in:)
    params = lsp.ReferenceParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=0, character=10),
        context=lsp.ReferenceContext(include_declaration=True),
    )

    result = server_mod.references(mock_ls, params)

    assert result is not None
    # Минимум 3: объявление + 2 show ... at slide_in
    assert len(result) >= 3


def test_references_screen_finds_use_and_call_screen(tmp_path: Path):
    """LSP-18: references на screen — все use X() и call screen X()."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)
    script = game_dir / "script.rpy"
    script.write_text(
        "screen confirm_dialog():\n"
        "    textbutton 'OK':\n"
        "        action Return()\n"
        "\n"
        "label start:\n"
        "    call screen confirm_dialog()\n"
        "    return\n",
        encoding="utf-8",
    )

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    server_mod._refresh_symbol_snapshot()

    uri = server_mod._path_to_uri(str(script))
    doc = MockDocument(uri, script.read_text(encoding="utf-8"))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    # Курсор на "confirm_dialog" в строке 0 (screen confirm_dialog():)
    params = lsp.ReferenceParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=0, character=7),
        context=lsp.ReferenceContext(include_declaration=True),
    )

    result = server_mod.references(mock_ls, params)

    assert result is not None
    # Минимум 2: объявление + call screen confirm_dialog()
    assert len(result) >= 2


# =============================================================================
# Backward compat: label rename/references продолжают работать
# =============================================================================

def test_rename_label_still_works(tmp_path: Path):
    """LSP-17: label rename не сломан после добавления variable/transform/screen."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)
    script = game_dir / "script.rpy"
    script.write_text(
        "label start:\n"
        "    jump my_label\n"
        "    return\n"
        "\n"
        "label my_label:\n"
        "    return\n",
        encoding="utf-8",
    )

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    server_mod._refresh_symbol_snapshot()

    uri = server_mod._path_to_uri(str(script))
    doc = MockDocument(uri, script.read_text(encoding="utf-8"))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    # Курсор на "my_label" в строке 4 (label my_label:)
    params = lsp.RenameParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=4, character=6),
        new_name="greeting",
    )

    result = server_mod.rename(mock_ls, params)

    assert result is not None
    assert result.changes is not None

    all_edits = []
    for file_uri, edits in result.changes.items():
        all_edits.extend(edits)

    # 2: объявление + jump my_label
    assert len(all_edits) >= 2


def test_references_label_still_works(tmp_path: Path):
    """LSP-18: label references не сломан."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)
    script = game_dir / "script.rpy"
    script.write_text(
        "label start:\n"
        "    jump my_label\n"
        "    return\n"
        "\n"
        "label my_label:\n"
        "    return\n",
        encoding="utf-8",
    )

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    server_mod._refresh_symbol_snapshot()

    uri = server_mod._path_to_uri(str(script))
    doc = MockDocument(uri, script.read_text(encoding="utf-8"))
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    # Курсор на "my_label" в строке 4 (label my_label:)
    params = lsp.ReferenceParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=4, character=6),
        context=lsp.ReferenceContext(include_declaration=True),
    )

    result = server_mod.references(mock_ls, params)

    assert result is not None
    # 2: объявление + jump my_label
    assert len(result) >= 2
