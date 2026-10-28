from __future__ import annotations

import json
import os
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
    """Создаёт тестовый проект Ren'Py и инициализирует анализатор в LSP сервере."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)

    script_content = """
default player_gold = 100
define max_hp = 50

layeredimage sayori:
    attribute happy
    attribute shocked

label start:
    $ player_gold += 10
    show sayori happy
    jump forest_scene

label forest_scene:
    "В лесу..."
    jump deep_cave

label deep_cave:
    return
"""
    script_file = game_dir / "script.rpy"
    script_file.write_text(script_content, encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)

    # Инициализируем синглтон анализатора в server.py
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    # UX-EXT-5: refresh symbol snapshot, чтобы autocomplete/hover/rename/
    # workspace_symbol видели labels/screens/transforms (handler'ы теперь
    # используют snapshot, не _active_analyzer.labels напрямую).
    server_mod._refresh_symbol_snapshot()

    return script_file, analyzer


def test_lsp_completion_labels(tmp_path: Path):
    """[LSP] Autocomplete suggests labels after 'jump ' and 'call '"""
    script_file, _ = setup_test_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))

    doc = MockDocument(uri, "label test:\n    jump ")
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    params = lsp.CompletionParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=1, character=9),  # Сразу после "jump "
    )

    result = server_mod.completions(mock_ls, params)
    labels = {item.label for item in result.items}

    assert "forest_scene" in labels
    assert "deep_cave" in labels
    assert "start" in labels


def test_lsp_completion_sprite_attributes(tmp_path: Path):
    """[LSP] Autocomplete suggests layeredimage attributes after 'show sayori '"""
    script_file, _ = setup_test_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))

    doc = MockDocument(uri, "label test:\n    show sayori ")
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    params = lsp.CompletionParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=1, character=16),  # Сразу после "show sayori "
    )

    result = server_mod.completions(mock_ls, params)
    attrs = {item.label for item in result.items}

    assert "happy" in attrs
    assert "shocked" in attrs


def test_lsp_go_to_definition(tmp_path: Path):
    """[LSP] F12 / Go-to-Definition handles labels, screens, variables, sprites and media files"""
    script_file, analyzer = setup_test_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))

    # 1. Переход к метке сюжета (label)
    doc_lbl = MockDocument(uri, "label test:\n    jump forest_scene")
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc_lbl)
    loc_lbl = server_mod.definition(
        mock_ls,
        lsp.DefinitionParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri),
            position=lsp.Position(line=1, character=12),
        ),
    )
    assert loc_lbl is not None
    assert loc_lbl.range.start.line == analyzer.labels["forest_scene"].line_number - 1

    # 2. Переход к переменной default
    doc_var = MockDocument(uri, "$ player_gold += 20")
    mock_ls.workspace = MockWorkspace(doc_var)
    loc_var = server_mod.definition(
        mock_ls,
        lsp.DefinitionParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri),
            position=lsp.Position(line=0, character=4),
        ),
    )
    assert loc_var is not None
    assert loc_var.range.start.line == analyzer.variables["player_gold"].line_number - 1

    # 3. Переход к layeredimage
    doc_img = MockDocument(uri, "show sayori happy")
    mock_ls.workspace = MockWorkspace(doc_img)
    loc_img = server_mod.definition(
        mock_ls,
        lsp.DefinitionParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri),
            position=lsp.Position(line=0, character=6),  # Курсор на слове "sayori"
        ),
    )
    assert loc_img is not None
    assert loc_img.range.start.line == analyzer.images["sayori"].line_number - 1

    # 4. Переход к аудиофайлу на диске
    audio_path = tmp_path / "game" / "audio" / "click.ogg"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"dummy_sound")
    analyzer.assets.media_disk_files["audio/click.ogg"] = str(audio_path)

    doc_audio = MockDocument(uri, 'play sound "audio/click.ogg"')
    mock_ls.workspace = MockWorkspace(doc_audio)
    loc_audio = server_mod.definition(
        mock_ls,
        lsp.DefinitionParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri),
            position=lsp.Position(line=0, character=16),  # Внутри кавычек
        ),
    )
    assert loc_audio is not None
    assert loc_audio.uri == server_mod._path_to_uri(str(audio_path))


def test_lsp_hover_variable_and_label(tmp_path: Path):
    """[LSP] Hover tooltip returns rich markdown for variables and branching labels"""
    script_file, _ = setup_test_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))

    mock_ls = MagicMock()

    # 1. Ховер на переменную player_gold
    doc_var = MockDocument(uri, "$ player_gold += 50")
    mock_ls.workspace = MockWorkspace(doc_var)
    h_var = server_mod.hover(
        mock_ls,
        lsp.HoverParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri),
            position=lsp.Position(line=0, character=4),
        ),
    )
    assert h_var is not None
    assert "player_gold" in h_var.contents.value
    assert "default player_gold = 100" in h_var.contents.value

    # 2. Ховер на метку forest_scene (должен содержать исходящий переход в deep_cave)
    doc_lbl = MockDocument(uri, "jump forest_scene")
    mock_ls.workspace = MockWorkspace(doc_lbl)
    h_lbl = server_mod.hover(
        mock_ls,
        lsp.HoverParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri),
            position=lsp.Position(line=0, character=7),
        ),
    )
    assert h_lbl is not None
    assert "forest_scene" in h_lbl.contents.value
    assert "deep_cave" in h_lbl.contents.value  # Проверяем наличие исходящего прыжка!


def test_lsp_document_symbols(tmp_path: Path):
    """[LSP] Document symbols returns outline hierarchy with labels, screens, images and variables"""
    script_file, _analyzer = setup_test_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))

    with open(script_file, encoding="utf-8") as f:
        content = f.read()

    doc = MockDocument(uri, content)
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)

    params = lsp.DocumentSymbolParams(text_document=lsp.TextDocumentIdentifier(uri=uri))

    symbols = server_mod.document_symbols(mock_ls, params)
    assert symbols is not None
    assert len(symbols) >= 6

    names = {s.name for s in symbols}
    assert "start" in names
    assert "forest_scene" in names
    assert "deep_cave" in names
    assert "sayori" in names  # layeredimage
    assert "player_gold" in names  # default
    assert "max_hp" in names  # define

    # Проверяем атрибуты метки для Outline и Breadcrumbs
    start_sym = next(s for s in symbols if s.name == "start")
    assert start_sym.kind == lsp.SymbolKind.Function
    assert start_sym.detail == "Label"
    # Блок start должен охватывать несколько строк до следующей сцены forest_scene
    assert start_sym.range.start.line < start_sym.range.end.line


def test_graph_export_and_interactive_metadata(tmp_path: Path):
    """[Flow & Graph] Verify export_graph contains valid Mermaid syntax and intact senpy-meta JSON"""
    _, analyzer = setup_test_workspace(tmp_path)
    graph_output = analyzer.export_graph()

    # 1. Проверяем наличие Mermaid
    assert "```mermaid" in graph_output
    assert "graph TD" in graph_output
    assert "deep_cave" in graph_output
    assert "forest_scene" in graph_output

    # 2. Проверяем наличие и валидность блока senpy-meta
    assert "```senpy-meta" in graph_output
    meta_json_str = graph_output.split("```senpy-meta")[1].split("```")[0].strip()
    meta = json.loads(meta_json_str)

    assert "locations" in meta
    assert "start" in meta["locations"]
    assert "forest_scene" in meta["locations"]
    assert meta["locations"]["forest_scene"]["line"] > 0


def test_lsp_hover_renpy_api_docs(tmp_path: Path):
    """[LSP] Hover tooltip returns rich markdown documentation for Ren'Py API and Actions"""
    script_file, _ = setup_test_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))

    mock_ls = MagicMock()

    # 1. Проверяем hover на renpy.pause
    doc_pause = MockDocument(uri, "$ renpy.pause(1.5)")
    mock_ls.workspace = MockWorkspace(doc_pause)
    h_pause = server_mod.hover(
        mock_ls,
        lsp.HoverParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri),
            position=lsp.Position(line=0, character=8),  # Курсор внутри "renpy.pause"
        ),
    )
    assert h_pause is not None
    assert "renpy.pause" in h_pause.contents.value
    assert "Pauses script execution" in h_pause.contents.value
    assert "hard=True" in h_pause.contents.value

    # 2. Проверяем hover на screen Action: SetVariable
    doc_action = MockDocument(uri, "textbutton 'Click' action SetVariable('x', 1)")
    mock_ls.workspace = MockWorkspace(doc_action)
    h_action = server_mod.hover(
        mock_ls,
        lsp.HoverParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri),
            position=lsp.Position(line=0, character=30),  # Курсор внутри "SetVariable"
        ),
    )
    assert h_action is not None
    assert "SetVariable" in h_action.contents.value
    assert "Screen Action" in h_action.contents.value


def test_lsp_code_action_quick_fixes(tmp_path: Path):
    """[LSP] Code Action generates QuickFix WorkspaceEdit for RPY001, RPY002, and RPY301"""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)

    # Строка 1: табуляция в отступе (RPY001)
    # Строка 2: фигурные кавычки в коде (RPY002)
    # Строка 3: незакрытый тег в диалоге (RPY301)
    # Строка 4: чистая строка без ошибок (отрицательный случай)
    content = (
        "label start:\n"
        "\t$ gold = 10\n"
        "    $ status = “active”\n"
        '    "Warning: {b}danger ahead!"\n'
        "    return\n"
    )
    script_file = game_dir / "quickfix_test.rpy"
    script_file.write_text(content, encoding="utf-8")
    uri = server_mod._path_to_uri(str(script_file))

    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)

    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    # UX-EXT-5: snapshot для handler'ов (autocomplete/hover/rename)
    server_mod._refresh_symbol_snapshot()

    # Регистрируем диагностики файла в кэше LSP сервера
    norm_path = os.path.normcase(os.path.abspath(str(script_file)))
    pairs = []
    for diag in result.diagnostics:
        if os.path.normcase(os.path.abspath(diag.file_path)) == norm_path:
            lsp_diag = server_mod._create_lsp_diagnostic(diag)
            pairs.append((diag, lsp_diag))
    server_mod._latest_diagnostics_by_path[norm_path] = pairs

    mock_ls = MagicMock()
    mock_doc = MockDocument(uri, content)
    mock_ls.workspace = MockWorkspace(mock_doc)

    # 1. Запрос CodeAction для строки 1 (RPY001 — замена табов на 4 пробела)
    params_rpy001 = lsp.CodeActionParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        range=lsp.Range(
            start=lsp.Position(line=1, character=0), end=lsp.Position(line=1, character=5)
        ),
        context=lsp.CodeActionContext(diagnostics=[]),
    )
    actions_rpy001 = server_mod.code_action(mock_ls, params_rpy001)
    assert len(actions_rpy001) == 1
    assert "Replace tabs with 4 spaces" in actions_rpy001[0].title
    assert actions_rpy001[0].kind == lsp.CodeActionKind.QuickFix
    assert actions_rpy001[0].edit.changes[uri][0].new_text == "    "

    # 2. Запрос CodeAction для строки 2 (RPY002 — замена типографских кавычек)
    params_rpy002 = lsp.CodeActionParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        range=lsp.Range(
            start=lsp.Position(line=2, character=0), end=lsp.Position(line=2, character=10)
        ),
        context=lsp.CodeActionContext(diagnostics=[]),
    )
    actions_rpy002 = server_mod.code_action(mock_ls, params_rpy002)
    assert len(actions_rpy002) == 1
    assert "Replace smart quotes" in actions_rpy002[0].title
    assert '"active"' in actions_rpy002[0].edit.changes[uri][0].new_text

    # 3. Запрос CodeAction для строки 3 (RPY301 — автозакрытие тега {b})
    params_rpy301 = lsp.CodeActionParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        range=lsp.Range(
            start=lsp.Position(line=3, character=0), end=lsp.Position(line=3, character=10)
        ),
        context=lsp.CodeActionContext(diagnostics=[]),
    )
    actions_rpy301 = server_mod.code_action(mock_ls, params_rpy301)
    assert len(actions_rpy301) == 1
    assert "Auto-close tag(s)" in actions_rpy301[0].title
    assert "{/b}" in actions_rpy301[0].edit.changes[uri][0].new_text

    # 4. Отрицательный случай: курсор на чистой строке 4 ('return') — никаких действий быть не должно
    params_clean = lsp.CodeActionParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        range=lsp.Range(
            start=lsp.Position(line=4, character=0), end=lsp.Position(line=4, character=5)
        ),
        context=lsp.CodeActionContext(diagnostics=[]),
    )
    actions_clean = server_mod.code_action(mock_ls, params_clean)
    assert len(actions_clean) == 0


def test_lsp_transform_navigation_and_symbols(tmp_path: Path):
    """[LSP] F12 Go-to-Definition, Document Symbols, and Autocomplete support for ATL transforms."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)

    content = (
        "transform custom_bounce:\n"
        "    yoffset 0\n"
        "    easein 0.2 yoffset -20\n"
        "\n"
        "label start:\n"
        "    show sayori at custom_bounce\n"
        "    return\n"
    )
    script_file = game_dir / "transform_test.rpy"
    script_file.write_text(content, encoding="utf-8")
    uri = server_mod._path_to_uri(str(script_file))

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)

    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    # UX-EXT-5: snapshot для handler'ов (autocomplete/hover/rename)
    server_mod._refresh_symbol_snapshot()

    mock_ls = MagicMock()
    mock_doc = MockDocument(uri, content)
    mock_ls.workspace = MockWorkspace(mock_doc)

    # 1. Проверка F12 Go-to-Definition на имени трансформа
    loc = server_mod.definition(
        mock_ls,
        lsp.DefinitionParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri),
            position=lsp.Position(line=5, character=22),  # Курсор внутри "custom_bounce"
        ),
    )
    assert loc is not None, "F12 failed to resolve location for ATL transform 'custom_bounce'"
    assert loc.range.start.line == 0, (
        f"Expected definition on line 0, got line {loc.range.start.line}"
    )

    # 2. Проверка Document Symbols (Outline / Ctrl+Shift+O)
    symbols = server_mod.document_symbols(
        mock_ls, lsp.DocumentSymbolParams(text_document=lsp.TextDocumentIdentifier(uri=uri))
    )
    trans_sym = next((s for s in symbols if s.name == "custom_bounce"), None)
    assert trans_sym is not None, (
        "Document symbols outline is missing ATL transform 'custom_bounce'"
    )
    assert trans_sym.detail == "Transform"

    # 3. Проверка автокомплита после 'at '
    doc_comp = MockDocument(uri, "show sayori at ")
    mock_ls.workspace = MockWorkspace(doc_comp)
    comp_res = server_mod.completions(
        mock_ls,
        lsp.CompletionParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri),
            position=lsp.Position(line=0, character=15),
        ),
    )
    comp_labels = {item.label for item in comp_res.items}
    assert "custom_bounce" in comp_labels, (
        "Autocomplete missing user-defined transform 'custom_bounce'"
    )
    assert "center" in comp_labels, "Autocomplete missing built-in position 'center'"
