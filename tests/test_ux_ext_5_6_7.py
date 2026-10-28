"""Тесты для UX-EXT-5..7: cross-file autocomplete, hover-ссылка, prepare_rename.

UX-EXT-5: Autocomplete должен предлагать labels из ВСЕХ файлов проекта,
не только из текущего. Регрессия: после did_change single-file анализ
очищал _active_analyzer.labels, оставляя только labels текущего файла.

UX-EXT-6: Hover-карточка должна содержать кликабельную Markdown-ссылку
на объявление (file:// URI с #L42 anchor), не просто текст в backticks.

UX-EXT-7: workspace/didChangeConfiguration не должен падать с ошибкой
"Ignoring notification for unknown method". Сервер должен либо
регистрировать handler, либо extension не должен слать этот notification.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from lsprotocol import types as lsp

import senpy.server as server_mod
from senpy.analyzer import SenpyAnalyzer
from tests.test_lsp import MockDocument, MockWorkspace, setup_test_workspace


_VSCODE_DIR = Path(__file__).resolve().parent.parent / "senpy-vscode"
_EXTENSION_TS = _VSCODE_DIR / "src" / "extension.ts"


def _make_completion_params(uri: str, line: int, char: int) -> lsp.CompletionParams:
    return lsp.CompletionParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=line, character=char),
    )


def _make_hover_params(uri: str, line: int, char: int) -> lsp.HoverParams:
    return lsp.HoverParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=line, character=char),
    )


# =============================================================================
# UX-EXT-5: Cross-file autocomplete
# =============================================================================

class TestCrossFileAutocomplete:
    """Автокомплит должен предлагать labels из ВСЕХ файлов проекта.

    Регрессия: после did_change + analyze_file_only _active_analyzer.labels
    содержал только labels текущего файла, и autocomplete не показывал
    labels из других .rpy файлов. Например, в day1a.rpy вводили jump day10
    — но label'ы из day10a.rpy не появлялись.
    """

    def test_jump_completion_offers_labels_from_other_files(self, tmp_path: Path):
        """jump в file1.rpy должен предлагать labels из file2.rpy."""
        game_dir = tmp_path / "game"
        game_dir.mkdir(parents=True, exist_ok=True)

        # file1.rpy: один label, который jump'ит куда-то
        (game_dir / "file1.rpy").write_text(
            "label start:\n"
            "    jump \n"  # курсор после "jump "
            "    return\n",
            encoding="utf-8",
        )

        # file2.rpy: label во втором файле
        (game_dir / "file2.rpy").write_text(
            "label day10_intro:\n"
            "    \"Day 10\"\n"
            "    return\n",
            encoding="utf-8",
        )

        analyzer = SenpyAnalyzer(str(tmp_path))
        analyzer.run(quiet=True)
        server_mod._active_analyzer = analyzer
        server_mod._is_initialized = True
        # UX-EXT-5: в реальном LSP server.py это вызывается в run_full_project_diagnostics.
        # В тестах вызываем явно, т.к. тест идёт напрямую через analyzer.run().
        server_mod._refresh_symbol_snapshot()

        # Симулируем did_change на file1.rpy (как делает VS Code при вводе)
        file1_uri = "file:///test/file1.rpy"
        file1_content = (game_dir / "file1.rpy").read_text(encoding="utf-8")

        # Вызываем analyze_file_only (это делает did_change handler)
        import os
        analyzer.in_memory_files[
            os.path.normcase(os.path.abspath(str(game_dir / "file1.rpy")))
        ] = file1_content
        analyzer.analyze_file_only(str(game_dir / "file1.rpy"))

        # Теперь вызываем autocomplete на строке 1, после "jump "
        doc = MockDocument(file1_uri, file1_content)
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        # position: line=1, character=9 (после "    jump ")
        params = _make_completion_params(file1_uri, line=1, char=9)
        result = server_mod.completions(mock_ls, params)

        assert result is not None, "Completion должен вернуть список"
        labels = [item.label for item in result.items]

        # КРИТИЧЕСКИЙ АССЕРТ: label из ДРУГОГО файла должен быть в списке
        assert "day10_intro" in labels, (
            f"Autocomplete должен предлагать labels из ВСЕХ файлов проекта. "
            f"Получено: {labels}. Ожидается 'day10_intro' (из file2.rpy)."
        )
        # И свой собственный label тоже
        assert "start" in labels, f"start тоже должен быть. Получено: {labels}"

    def test_call_completion_offers_labels_from_all_files(self, tmp_path: Path):
        """call в одном файле должен предлагать labels из всех файлов."""
        game_dir = tmp_path / "game"
        game_dir.mkdir(parents=True, exist_ok=True)

        (game_dir / "a.rpy").write_text(
            "label start:\n"
            "    call \n"
            "    return\n",
            encoding="utf-8",
        )
        (game_dir / "b.rpy").write_text(
            "label chapter_two:\n"
            "    return\n",
            encoding="utf-8",
        )
        (game_dir / "c.rpy").write_text(
            "label ending_credits:\n"
            "    return\n",
            encoding="utf-8",
        )

        analyzer = SenpyAnalyzer(str(tmp_path))
        analyzer.run(quiet=True)
        server_mod._active_analyzer = analyzer
        server_mod._is_initialized = True
        # UX-EXT-5: refresh snapshot (как делает run_full_project_diagnostics)
        server_mod._refresh_symbol_snapshot()

        # did_change на a.rpy
        import os
        a_path = str(game_dir / "a.rpy")
        a_content = (game_dir / "a.rpy").read_text(encoding="utf-8")
        norm_a = os.path.normcase(os.path.abspath(a_path))
        analyzer.in_memory_files[norm_a] = a_content
        analyzer.analyze_file_only(a_path)

        a_uri = "file:///test/a.rpy"
        doc = MockDocument(a_uri, a_content)
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        params = _make_completion_params(a_uri, line=1, char=10)
        result = server_mod.completions(mock_ls, params)

        labels = [item.label for item in result.items]
        assert "chapter_two" in labels, f"Из b.rpy должен быть. Получено: {labels}"
        assert "ending_credits" in labels, f"Из c.rpy должен быть. Получено: {labels}"


# =============================================================================
# UX-EXT-6: Hover-карточка с кликабельной ссылкой
# =============================================================================

class TestHoverClickableLink:
    """Hover должен содержать Markdown-ссылку на file:// URI с #L42 anchor.

    Сейчас: *Declared at `script.rpy:42`* — это просто текст, не кликабельный.
    Надо: *Declared at [`script.rpy:42`](file:///path/to/script.rpy#L42)* —
    VS Code откроет файл на нужной строке при клике.
    """

    def test_hover_variable_has_clickable_link(self, tmp_path: Path):
        """Hover на переменной содержит Markdown-ссылку file://...#L<line>."""
        setup_test_workspace(tmp_path)
        # UX-EXT-5: setup_test_workspace не вызывает _refresh_symbol_snapshot,
        # поэтому hover (который теперь использует snapshot) не найдёт переменную.
        server_mod._refresh_symbol_snapshot()

        # script.rpy (0-based):
        #  0: (empty)
        #  1: default player_gold = 100    <-- переменная, hover here
        uri = "file:///test/script.rpy"
        script_content = (tmp_path / "game" / "script.rpy").read_text(encoding="utf-8")
        doc = MockDocument(uri, script_content)
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        # Курсор на "player_gold" в строке 1, символ 10
        params = _make_hover_params(uri, line=1, char=10)
        result = server_mod.hover(mock_ls, params)

        assert result is not None, "Hover должен вернуть контент"
        assert result.contents is not None
        content = result.contents.value

        # Должна быть Markdown-ссылка вида [text](file://...#L1)
        import re
        # Ищем паттерн: [что-то](file://путь#L<номер>)
        link_match = re.search(r'\[[^\]]+\]\((file://[^)]+#L\d+)\)', content)
        assert link_match, (
            f"Hover должен содержать Markdown-ссылку [text](file://...#L<N>). "
            f"Получено: {content!r}"
        )

        link_url = link_match.group(1)
        assert "#L" in link_url, f"Ссылка должна содержать #L anchor. URL: {link_url}"
        # Номер строки должен быть >= 1
        line_match = re.search(r'#L(\d+)', link_url)
        assert line_match, f"Должен быть номер строки. URL: {link_url}"
        assert int(line_match.group(1)) >= 1

    def test_hover_label_has_clickable_link(self, tmp_path: Path):
        """Hover на label содержит Markdown-ссылку на объявление."""
        setup_test_workspace(tmp_path)
        server_mod._refresh_symbol_snapshot()

        # script.rpy (0-based):
        # 13: label forest_scene:    <-- hover here
        uri = "file:///test/script.rpy"
        script_content = (tmp_path / "game" / "script.rpy").read_text(encoding="utf-8")
        doc = MockDocument(uri, script_content)
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        # Курсор на "forest_scene" в строке 13
        params = _make_hover_params(uri, line=13, char=10)
        result = server_mod.hover(mock_ls, params)

        assert result is not None
        content = result.contents.value

        import re
        link_match = re.search(r'\[[^\]]+\]\((file://[^)]+#L\d+)\)', content)
        assert link_match, (
            f"Hover на label должен содержать Markdown-ссылку. Получено: {content!r}"
        )

    def test_hover_link_points_to_correct_line(self, tmp_path: Path):
        """Ссылка должна указывать на правильную строку объявления."""
        setup_test_workspace(tmp_path)
        server_mod._refresh_symbol_snapshot()

        # default player_gold на строке 1 (0-based) = строка 2 (1-based)
        uri = "file:///test/script.rpy"
        script_content = (tmp_path / "game" / "script.rpy").read_text(encoding="utf-8")
        doc = MockDocument(uri, script_content)
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        params = _make_hover_params(uri, line=1, char=10)
        result = server_mod.hover(mock_ls, params)
        content = result.contents.value

        import re
        # default player_gold = 100 — это строка 2 в файле (1-based)
        # т.к. файл начинается с пустой строки (line 0 = empty)
        line_match = re.search(r'#L(\d+)', content)
        assert line_match, f"Не найден #L anchor в: {content!r}"
        line_num = int(line_match.group(1))
        # 1-based строка объявления player_gold
        assert line_num == 2, (
            f"Ссылка должна указывать на строку 2 (1-based), получено L{line_num}. "
            f"Content: {content!r}"
        )


# =============================================================================
# UX-EXT-7: workspace/didChangeConfiguration не должен падать
# =============================================================================

class TestDidChangeConfiguration:
    """Сервер не должен логировать 'Ignoring notification for unknown method
    workspace/didChangeConfiguration'.

    Варианты фикса:
    (a) Зарегистрировать handler для WORKSPACE_DID_CHANGE_CONFIGURATION в server.py
    (b) Убрать configurationSection из extension.ts synchronize
    (c) Оба варианта

    Выбран (b) — configurationSection @deprecated, не нужен.
    fileEvents для .senpy.toml достаточно — он триггерит
    workspace/didChangeWatchedFiles, который сервер уже умеет.
    """

    def test_extension_does_not_send_did_change_configuration(self):
        """extension.ts не должен содержать configurationSection как ПОЛЕ в synchronize.

        Если configurationSection есть как поле (не в комментарии), VS Code
        будет слать workspace/didChangeConfiguration, который сервер не умеет —
        в Output логируется ошибка.
        """
        if not _EXTENSION_TS.exists():
            pytest.skip("extension.ts не найден")
        src = _EXTENSION_TS.read_text(encoding="utf-8")

        # Если synchronize есть — в нём НЕ должно быть configurationSection как поля.
        # configurationSection в комментариях — ок (мы пишем почему убрали).
        import re
        sync_match = re.search(
            r'synchronize\s*:\s*\{([^}]+)\}',
            src,
            re.DOTALL,
        )
        if sync_match:
            sync_body = sync_match.group(1)
            # Удалим строки-комментарии (// ...) — в них configurationSection упоминается
            # только для документации "почему убрали".
            lines = sync_body.split("\n")
            code_lines = [
                ln for ln in lines
                if not ln.strip().startswith("//")
            ]
            code_only = "\n".join(code_lines)
            assert "configurationSection:" not in code_only, (
                "synchronize НЕ должен содержать configurationSection: как поле — "
                "это вызывает 'Ignoring notification for unknown method "
                "workspace/didChangeConfiguration' в логах. "
                "configurationSection @deprecated, используйте fileEvents + "
                "workspace/didChangeWatchedFiles (сервер уже умеет). "
                f"Только код (без комментариев): {code_only!r}"
            )

    def test_extension_keeps_file_events_for_senpy_toml(self):
        """fileEvents для .senpy.toml должен остаться — он нужен для hot-reload."""
        if not _EXTENSION_TS.exists():
            pytest.skip("extension.ts не найден")
        src = _EXTENSION_TS.read_text(encoding="utf-8")

        import re
        sync_match = re.search(
            r'synchronize\s*:\s*\{([^}]+)\}',
            src,
            re.DOTALL,
        )
        assert sync_match, "synchronize блок должен остаться (с fileEvents)"
        sync_body = sync_match.group(1)
        assert "fileEvents" in sync_body, (
            "fileEvents для .senpy.toml должен остаться в synchronize — "
            "это единственный способ получить hot-reload .senpy.toml"
        )
        assert "senpy.toml" in sync_body.lower(), (
            "fileEvents должен следить за .senpy.toml"
        )
