from __future__ import annotations

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


SCRIPT = """default player_gold = 100

label start:
    "Начало."
    jump chapter_one

label chapter_one:
    "Глава один."
    call chapter_two
    return

label chapter_two:
    "Глава два."
    jump chapter_one

label unreachable_label:
    return
"""
# 1-based нумерация: 5 = jump chapter_one, 7 = label chapter_one:,
# 9 = call chapter_two, 14 = jump chapter_one, 16 = label unreachable_label:


def setup_test_workspace(tmp_path: Path):
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    script_file = game_dir / "script.rpy"
    script_file.write_text(SCRIPT, encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)

    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    # UX-EXT-5: snapshot для references (handler'ы теперь используют snapshot)
    server_mod._refresh_symbol_snapshot()

    return script_file, analyzer


def _make_ls(uri: str) -> MagicMock:
    """MagicMock с подключённым workspace: без этого len(doc.lines) == 0 и гарды режут запрос."""
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(MockDocument(uri, SCRIPT))
    return mock_ls


def _make_params(uri: str, line: int, character: int, include_declaration: bool):
    return lsp.ReferenceParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=line, character=character),
        context=lsp.ReferenceContext(include_declaration=include_declaration),
    )


def _locations_as_lines(result) -> set:
    return {(loc.range.start.line, loc.range.start.character) for loc in result}


def test_references_jumps_and_calls(tmp_path: Path):
    """[LSP] Find References на метку собирает jump- и call-ссылки по всему проекту"""
    script_file, _ = setup_test_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))

    # Курсор внутри chapter_one на строке "    jump chapter_one" (0-базная строка 4)
    result = server_mod.references(
        _make_ls(uri), _make_params(uri, line=4, character=10, include_declaration=True)
    )

    assert result is not None
    assert len(result) == 3
    assert all(loc.uri == uri for loc in result)
    # Декларация (0-базная 6) + jump (4) + jump (13)
    assert _locations_as_lines(result) == {(6, 0), (4, 0), (13, 0)}


def test_references_include_declaration_flag(tmp_path: Path):
    """[LSP] include_declaration=False исключает декларацию из результата"""
    script_file, _ = setup_test_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))

    result = server_mod.references(
        _make_ls(uri), _make_params(uri, line=4, character=10, include_declaration=False)
    )

    assert len(result) == 2
    assert _locations_as_lines(result) == {(4, 0), (13, 0)}


def test_references_unreferenced_label(tmp_path: Path):
    """[LSP] Метка без ссылок: с декларацией — одна локация, без — пусто"""
    script_file, _ = setup_test_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))

    # Курсор на unreachable_label в "label unreachable_label:" (0-базная 15)
    with_decl = server_mod.references(
        _make_ls(uri), _make_params(uri, line=15, character=8, include_declaration=True)
    )
    assert len(with_decl) == 1
    assert _locations_as_lines(with_decl) == {(15, 0)}

    without_decl = server_mod.references(
        _make_ls(uri), _make_params(uri, line=15, character=8, include_declaration=False)
    )
    assert without_decl == []


def test_references_variables_not_supported_yet(tmp_path: Path):
    """[LSP] Срез 1: references для переменных пока не поддержан — возвращается None"""
    script_file, _ = setup_test_workspace(tmp_path)
    uri = server_mod._path_to_uri(str(script_file))

    # Курсор на player_gold в строке default (0-базная 0)
    result = server_mod.references(
        _make_ls(uri), _make_params(uri, line=0, character=9, include_declaration=True)
    )
    assert result is None
