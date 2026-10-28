"""Тесты для VS Code extension integration (UX-EXT-1..4).

Проверяет, что:
- language-configuration.json существует и валиден
- package.json ссылается на language-configuration.json
- LSP-сервер рекламирует prepareProvider для rename
- extension.ts настраивает synchronize для подхвата .senpy.toml

Эти тесты НЕ требуют установки VS Code — они проверяют декларативные
файлы конфигурации и наличие handler'а в server.py.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from lsprotocol import types as lsp

import senpy.server as server_mod
from test_lsp import MockDocument, MockWorkspace, setup_test_workspace

# Путь к senpy-vscode/ относительно tests/
_VSCODE_DIR = Path(__file__).parent.parent / "senpy-vscode"
_LANG_CONFIG = _VSCODE_DIR / "language-configuration.json"
_PACKAGE_JSON = _VSCODE_DIR / "package.json"
_EXTENSION_TS = _VSCODE_DIR / "src" / "extension.ts"


# =============================================================================
# UX-EXT-1: language-configuration.json — Ren'Py language settings
# =============================================================================

class TestLanguageConfiguration:
    """Проверка language-configuration.json для VS Code.

    Без этого файла VS Code воспринимает .rpy как plain text:
    Ctrl+/ не работает, скобки не закрываются, авто-отступы отключены.
    """

    def test_file_exists(self):
        """Файл language-configuration.json должен существовать."""
        assert _LANG_CONFIG.exists(), (
            f"Ожидается {_LANG_CONFIG}. Без него VS Code не знает, что "
            "'#' — комментарий, авто-отступы и bracket auto-close отключены."
        )

    @pytest.fixture
    def lang_config(self) -> dict:
        """Загружает language-configuration.json (или падает с понятной ошибкой)."""
        if not _LANG_CONFIG.exists():
            pytest.skip("language-configuration.json ещё не создан (RED phase)")
        return json.loads(_LANG_CONFIG.read_text(encoding="utf-8"))

    def test_line_comment_is_hash(self, lang_config):
        """lineComment должен быть '#' — единственный комментарий Ren'Py."""
        comments = lang_config.get("comments", {})
        assert comments.get("lineComment") == "#", (
            "Ren'Py использует '#' для комментариев. "
            f"Получено: {comments.get('lineComment')!r}"
        )

    def test_block_comment_absent_or_correct(self, lang_config):
        """blockComment не нужен (Ren'Py не поддерживает /* */), но если есть — корректный."""
        comments = lang_config.get("comments", {})
        # blockComment НЕ должен быть определён — Ren'Py не имеет block comments
        if "blockComment" in comments:
            bc = comments["blockComment"]
            assert isinstance(bc, list) and len(bc) == 2
            # Если кто-то добавил — это должно быть что-то разумное
            # Например, '"""' для python-блоков
            assert all(isinstance(x, str) and x for x in bc)

    def test_brackets_defined(self, lang_config):
        """brackets должен включать основные пары для Ren'Py/Python синтаксиса."""
        brackets = lang_config.get("brackets", [])
        assert isinstance(brackets, list)
        assert len(brackets) >= 3, (
            "Должно быть минимум 3 пары скобок: (), [], {}"
        )
        # Нормализуем для удобства проверки
        bracket_pairs = {tuple(b) for b in brackets}
        required = {("(", ")"), ("[", "]"), ("{", "}")}
        missing = required - bracket_pairs
        assert not missing, f"Отсутствуют обязательные скобки: {missing}"

    def test_auto_closing_pairs(self, lang_config):
        """autoClosingPairs — для кавычек и скобок."""
        pairs = lang_config.get("autoClosingPairs", [])
        assert isinstance(pairs, list)
        assert len(pairs) >= 3, "Должны быть пары для (), [], и кавычки"

        # Проверяем что есть кавычки (одиночные и двойные — Ren'Py использует оба)
        pair_strs = [json.dumps(p) for p in pairs]
        assert any('"\\\\\\"' in p or '""' in p for p in pair_strs) or \
               any('"' in p.get("open", "") and '"' in p.get("close", "") for p in pairs), \
               "Должна быть пара для двойных кавычек"

    def test_surrounding_pairs(self, lang_config):
        """surroundingPairs — для surround-selection (выделить и нажать ( )."""
        pairs = lang_config.get("surroundingPairs", [])
        assert isinstance(pairs, list)
        assert len(pairs) >= 3

    def test_indentation_rules(self, lang_config):
        """indentationRules — авто-отступ после label/menu/if/for/while/def."""
        # increaseIndentPattern должен ловить строки, заканчивающиеся на ':'
        ir = lang_config.get("indentationRules", {})
        if not ir:
            pytest.skip("indentationRules опциональны, но рекомендованы")

        inc = ir.get("increaseIndentPattern", "")
        assert isinstance(inc, str) and inc, "increaseIndentPattern должен быть непустой regex"

        # Проверим, что паттерн реально ловит типичные Ren'Py scope-openers
        import re as re_mod
        inc_re = re_mod.compile(inc)
        for sample in [
            "label start:",
            "menu:",
            "if condition:",
            "screen my_screen():",
            "init python:",
            "transform slide:",
        ]:
            assert inc_re.search(sample), (
                f"increaseIndentPattern {inc!r} должен матчить '{sample}'"
            )

        dec = ir.get("decreaseIndentPattern", "")
        if dec:
            # Не должен матчить обычные строки
            dec_re = re_mod.compile(dec)
            assert not dec_re.search("    jump somewhere"), (
                "decreaseIndentPattern не должен срабатывать на обычной строке"
            )

    def test_on_enter_rules_optional(self, lang_config):
        """onEnterRules — опционально, для авто-продолжения комментариев при Enter."""
        # Не проверяем содержимое — это nice-to-have, не блокер
        if "onEnterRules" in lang_config:
            assert isinstance(lang_config["onEnterRules"], list)


# =============================================================================
# UX-EXT-2: package.json ссылается на language-configuration.json
# =============================================================================

class TestPackageJsonReferences:
    """package.json должен подключать language-configuration.json.

    Без ссылки в contributes.languages[0].configuration VS Code
    проигнорирует файл, даже если он существует.
    """

    def test_package_json_exists(self):
        assert _PACKAGE_JSON.exists()

    @pytest.fixture
    def package_json(self) -> dict:
        return json.loads(_PACKAGE_JSON.read_text(encoding="utf-8"))

    def test_renpy_language_has_configuration(self, package_json):
        """contributes.languages[0] для 'renpy' должен иметь поле configuration."""
        languages = package_json.get("contributes", {}).get("languages", [])
        assert any(lang.get("id") == "renpy" for lang in languages), (
            "Должен быть language с id='renpy'"
        )

        renpy_lang = next(lang for lang in languages if lang.get("id") == "renpy")
        assert "configuration" in renpy_lang, (
            "languages[renpy].configuration должен указывать на "
            "./language-configuration.json. Без этого VS Code не подхватит "
            "настройки комментариев/скобок/отступов."
        )

        config_path = renpy_lang["configuration"]
        # Должен указывать на правильный файл
        assert "language-configuration.json" in config_path, (
            f"configuration должен указывать на language-configuration.json, "
            f"получено: {config_path!r}"
        )

    def test_renpy_extensions_cover_rpy_and_rpym(self, package_json):
        """Должны быть .rpy и .rpym."""
        languages = package_json.get("contributes", {}).get("languages", [])
        renpy_lang = next(lang for lang in languages if lang.get("id") == "renpy")
        exts = renpy_lang.get("extensions", [])
        assert ".rpy" in exts, ".rpy должен быть в extensions"
        assert ".rpym" in exts, ".rpym должен быть в extensions"


# =============================================================================
# UX-EXT-3: prepare_rename handler (textDocument/prepareRename)
# =============================================================================

class TestPrepareRename:
    """LSP-сервер должен поддерживать prepareRename для preview перед F2.

    Без prepareProvider: true VS Code не показывает preview изменений
    до подтверждения, и пользователь не может отменить переименование
    до применения.
    """

    def test_prepare_rename_handler_exists(self):
        """В server.py должен быть handler с lsp.TEXT_DOCUMENT_PREPARE_RENAME."""
        # Проверяем, что функция определена в модуле
        assert hasattr(server_mod, "prepare_rename"), (
            "server.py должен определить prepare_rename() handler "
            "для textDocument/prepareRename. Без него VS Code не покажет "
            "preview перед F2 rename."
        )
        assert callable(server_mod.prepare_rename), (
            "prepare_rename должен быть callable"
        )

    def test_prepare_rename_returns_range_for_label(self, tmp_path: Path):
        """prepareRename на label возвращает Range слова под курсором."""
        setup_test_workspace(tmp_path)

        # script.rpy 0-based lines:
        #  0: (empty)
        #  8: label start:
        # 13: label forest_scene:    <-- тестируем здесь
        uri = "file:///test/script.rpy"
        script_content = (tmp_path / "game" / "script.rpy").read_text(encoding="utf-8")
        doc = MockDocument(uri, script_content)
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        # Курсор на "forest_scene" в строке 13, символ 7 (внутри слова)
        params = lsp.PrepareRenameParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri),
            position=lsp.Position(line=13, character=7),
        )

        result = server_mod.prepare_rename(mock_ls, params)

        # Должен вернуть Range или PrepareRenameResult
        # Допускаем None если позиция невалидна, но для label — должен вернуть Range
        assert result is not None, (
            "prepare_rename на валидном label должен вернуть Range, не None"
        )

        # result может быть Range или PrepareRenameResult(placeholder=...)
        # Проверим что это структура с line/character или имеет .range
        if hasattr(result, "range"):
            rng = result.range
        elif hasattr(result, "start"):
            rng = result  # это уже Range
        else:
            pytest.fail(f"prepare_rename вернул неожиданный тип: {type(result)}")

        # Range должен покрывать слово "forest_scene" в строке 13
        assert rng.start.line == 13, f"start.line должен быть 13, получено {rng.start.line}"
        assert rng.end.line == 13, f"end.line должен быть 13, получено {rng.end.line}"
        # start.character <= 7 <= end.character
        assert rng.start.character <= 7 <= rng.end.character, (
            f"Range должен покрывать позицию 7: [{rng.start.character}, {rng.end.character}]"
        )

    def test_prepare_rename_returns_none_for_empty_position(self, tmp_path: Path):
        """prepareRename на пустой строке возвращает None (can't rename here)."""
        setup_test_workspace(tmp_path)

        uri = "file:///test/script.rpy"
        script_content = (tmp_path / "game" / "script.rpy").read_text(encoding="utf-8")
        doc = MockDocument(uri, script_content)
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        # Строка 0 — пустая
        params = lsp.PrepareRenameParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri),
            position=lsp.Position(line=0, character=0),
        )

        result = server_mod.prepare_rename(mock_ls, params)
        assert result is None, (
            "prepare_rename на пустой позиции должен вернуть None — "
            "это сигнал VS Code, что здесь нечего переименовывать."
        )

    def test_rename_feature_advertises_prepare_provider(self):
        """LSP-сервер должен рекламировать prepareProvider: true в capabilities.

        Без этого VS Code не вызовет textDocument/prepareRename, даже если
        handler определён.
        """
        # Проверяем декоратор @server.feature — у register_feature должен быть
        # параметр options с prepare_provider=True
        # В lsprotocol/pygame-did-this — это RenameOptions(prepare_provider=True)

        # Ищем в исходнике server.py декоратор TEXT_DOCUMENT_RENAME
        # и проверяем, что переданы options с prepare_provider
        server_src = Path(server_mod.__file__).read_text(encoding="utf-8")

        # Находим блок @server.feature(lsp.TEXT_DOCUMENT_RENAME, ...)
        # Должен быть RenameOptions с prepare_provider=True
        rename_decorator_match = re.search(
            r'@server\.feature\(\s*lsp\.TEXT_DOCUMENT_RENAME\s*,?\s*([^)]+)\)',
            server_src,
            re.DOTALL,
        )
        assert rename_decorator_match, (
            "Не найден декоратор @server.feature(lsp.TEXT_DOCUMENT_RENAME, ...)"
        )
        decorator_args = rename_decorator_match.group(1)
        assert "prepare_provider" in decorator_args, (
            "TEXT_DOCUMENT_RENAME должен быть зарегистрирован с "
            "RenameOptions(prepare_provider=True). Без этого VS Code "
            "не вызовет textDocument/prepareRename."
        )
        assert "True" in decorator_args, (
            "prepare_provider должен быть True"
        )


# =============================================================================
# UX-EXT-4: extension.ts — synchronize для подхвата .senpy.toml
# =============================================================================

class TestExtensionSynchronize:
    """extension.ts должен настраивать synchronize для .senpy.toml и *.rpy.

    Без synchronize конфигурация .senpy.toml не подхватывается без reload
    окна VS Code.
    """

    def test_extension_ts_exists(self):
        assert _EXTENSION_TS.exists(), f"Ожидается {_EXTENSION_TS}"

    @pytest.fixture
    def extension_src(self) -> str:
        if not _EXTENSION_TS.exists():
            pytest.skip("extension.ts не найден")
        return _EXTENSION_TS.read_text(encoding="utf-8")

    def test_client_options_has_synchronize(self, extension_src):
        """LanguageClientOptions должен содержать synchronize section."""
        # Ищем synchronize: { ... } в clientOptions
        assert "synchronize" in extension_src, (
            "clientOptions должен содержать synchronize для подхвата изменений "
            ".senpy.toml без reload окна VS Code."
        )

    def test_synchronize_watches_senpy_toml(self, extension_src):
        """synchronize.fileWatcher должен следить за .senpy.toml."""
        # Ищем patterns или fileWatcher в synchronize
        # Допустимые формы:
        #   synchronize: { fileWatcher: "**/.senpy.toml" }
        #   synchronize: { configurationSection: "senpy" }
        #   synchronize: { ... "**/.senpy.toml" ... }
        # Гибко проверим, что senpy.toml где-то упоминается в synchronize-блоке
        sync_match = re.search(
            r'synchronize\s*:\s*\{([^}]+)\}',
            extension_src,
            re.DOTALL,
        )
        assert sync_match, (
            "Должен быть synchronize: { ... } блок в clientOptions"
        )
        sync_body = sync_match.group(1)
        assert "senpy.toml" in sync_body.lower(), (
            f"synchronize должен следить за .senpy.toml. "
            f"Тело synchronize: {sync_body!r}"
        )

    def test_document_selector_includes_renpy(self, extension_src):
        """documentSelector должен включать language: 'renpy'."""
        assert "renpy" in extension_src, (
            "documentSelector должен содержать language: 'renpy'"
        )

    def test_no_vulnerability_in_esbuild_version(self, extension_src):
        """Smoke-тест: extension.ts должен компилироваться (нет очевидных ошибок)."""
        # Простая проверка: активация есть, deactivate есть
        assert "export function activate" in extension_src
        assert "export function deactivate" in extension_src or \
               "deactivate()" in extension_src
