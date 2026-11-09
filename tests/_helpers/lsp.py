"""Shared LSP test helpers.

Extracted from `tests/test_lsp.py` so that 12+ test files can import
`MockDocument`, `MockWorkspace`, `setup_test_workspace` without
`test_lsp.py` being on `sys.path` (which only works in pytest's default
`prepend` import mode and breaks in `importlib` mode after subdirectory
moves).

Kept verbatim from the original — do not change semantics without
auditing every importer.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock  # noqa: F401  — preserved from original

from lsprotocol import types as lsp  # noqa: F401  — preserved from original

import senpy.lsp.server as server_mod
from senpy.core.analyzer import SenpyAnalyzer


class MockDocument:
    def __init__(self, uri: str, content: str):
        self.uri = uri
        self.lines = content.splitlines(keepends=True)
        self.source = content  # для совместимости с pygls TextDocument API


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
    # UX: refresh symbol snapshot, чтобы autocomplete/hover/rename/
    # workspace_symbol видели labels/screens/transforms (handler'ы теперь
    # используют snapshot, не _active_analyzer.labels напрямую).
    server_mod._refresh_symbol_snapshot()

    return script_file, analyzer
