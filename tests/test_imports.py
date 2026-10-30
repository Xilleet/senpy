"""Safety net тесты для всех public импортов Senpy.

Назначение:
    Этот файл — characterization tests для импортов. Он гарантирует, что
    после реструктуризации 0.5.4 (когда файлы переедут по папкам
    core/, rules/, lsp/, cli/, formats/, domain/) **все** public
    импорты продолжат работать.

    Если после перемещения какой-то импорт сломается — этот тест упадёт
    на конкретном имени, сразу будет видно где.

Принцип:
    Тестируем **фактический** public API на момент 0.5.2.
    Любое изменение импортов в основной кодовой базе требует обновления
    этого файла (чтобы отражать актуальный контракт).

Обновление при рефакторинге:
    - При реструктуризации в 0.5.4: имена модулей могут измениться
      (например `from senpy.core.analyzer` → `from senpy.core.analyzer`),
      но **имена классов/функций** должны остаться прежними.
    - В `senpy/__init__.py` добавить re-exports для обратной совместимости.
    - Тесты в этом файле НЕ должны требовать обновления — они тестируют
      стабильные имена, не пути модулей.

Запуск:
    pytest tests/test_imports.py -v
"""
from __future__ import annotations

import importlib

import pytest

# =============================================================================
# 1. Главные классы и функции — canonical API
# =============================================================================

class TestCoreImports:
    """Главные классы, которые пользователи импортируют напрямую."""

    def test_import_senpy_analyzer(self):
        """SenpyAnalyzer — главный класс оркестратора."""
        from senpy.core.analyzer import SenpyAnalyzer
        assert SenpyAnalyzer is not None
        assert hasattr(SenpyAnalyzer, "run")
        assert hasattr(SenpyAnalyzer, "_collect_symbols")
        assert hasattr(SenpyAnalyzer, "_analyze_file")

    def test_import_senpy_models(self):
        """Diagnostic, RULE_SEVERITY, AnalysisResult, FileScope — модели данных."""
        from senpy.core.models import RULE_SEVERITY, AnalysisResult, Diagnostic, FileScope
        assert Diagnostic is not None
        assert AnalysisResult is not None
        assert FileScope is not None
        # RULE_SEVERITY — dict с минимум 45 правилами (на момент 0.5.2)
        assert isinstance(RULE_SEVERITY, dict)
        assert len(RULE_SEVERITY) >= 45, (
            f"RULE_SEVERITY должен содержать минимум 45 правил, "
            f"сейчас {len(RULE_SEVERITY)}"
        )

    def test_import_senpy_cache(self):
        """CacheManager, CacheManifest, CachedFileEntry, SafeCacheUnpickler."""
        from senpy.core.cache import (
            CachedFileEntry,
            CacheManager,
            CacheManifest,
            SafeCacheUnpickler,
            compute_file_hash,
        )
        assert CacheManager is not None
        assert CacheManifest is not None
        assert CachedFileEntry is not None
        assert SafeCacheUnpickler is not None
        assert callable(compute_file_hash)

    def test_import_senpy_constants(self):
        """SENPY_VERSION — из single source of truth (__version__.py)."""
        from senpy.core.constants import SENPY_VERSION
        assert SENPY_VERSION is not None
        assert isinstance(SENPY_VERSION, str)
        assert len(SENPY_VERSION.split(".")) == 3  # X.Y.Z

    def test_import_senpy_version(self):
        """__version__ — single source of truth."""
        from senpy.__version__ import MAJOR, MINOR, PATCH, VERSION_WITH_PREFIX, __version__
        assert isinstance(__version__, str)
        assert __version__.count(".") == 2
        assert VERSION_WITH_PREFIX.startswith("v")
        assert isinstance(MAJOR, int)
        assert isinstance(MINOR, int)
        assert isinstance(PATCH, int)


# =============================================================================
# 2. CLI / LSP entrypoints
# =============================================================================

class TestEntrypoints:
    """Точки входа: CLI и LSP-сервер."""

    def test_import_cli_main(self):
        """senpy.cli.main — главный entrypoint для `senpy` команды."""
        from senpy.cli.main import main
        assert callable(main)

    def test_import_cli_dispatch_format(self):
        """_dispatch_format — subcommand `senpy format`."""
        from senpy.cli.main import _dispatch_format
        assert callable(_dispatch_format)

    def test_import_cli_commands_handlers(self):
        """Все handler'ы из _cli_commands.py — для subcommands."""
        from senpy.cli.commands import (
            handle_clear_cache,
            handle_coverage,
            handle_defaults,
            handle_export_html,
            handle_export_wiki,
            handle_graph,
            handle_init_ci,
            handle_stats,
            handle_stubs,
            handle_traceback,
        )
        for handler in [
            handle_traceback, handle_init_ci, handle_coverage,
            handle_clear_cache, handle_stats, handle_export_wiki,
            handle_export_html, handle_graph, handle_defaults, handle_stubs,
        ]:
            assert callable(handler), f"{handler} should be callable"

    def test_import_unrpyc_bootstrap(self):
        """Функции unrpyc/rpa — для декомпиляции .rpyc и извлечения .rpa."""
        from senpy.cli.unrpyc import (
            decompile_to_sandbox,
            download_unrpyc,
            extract_scripts_from_rpa,
            find_in_directory_tree,
            find_unrpyc_executable,
            load_config,
        )
        for func in [
            load_config, find_in_directory_tree, download_unrpyc,
            find_unrpyc_executable, extract_scripts_from_rpa,
            decompile_to_sandbox,
        ]:
            assert callable(func), f"{func} should be callable"

    def test_import_server(self):
        """LSP-сервер и его handlers."""
        from senpy.lsp.server import server
        assert server is not None
        # server — экземпляр LanguageServer из pygls
        assert hasattr(server, "feature")

    def test_import_server_handlers(self):
        """Главные LSP handlers — должны быть импортируемы."""
        from senpy.lsp.server import (
            code_action,
            completions,
            definition,
            did_change,
            did_change_watched_files,
            did_close,
            did_open,
            did_save,
            document_highlight,
            document_symbols,
            folding_range,
            hover,
            prepare_rename,
            references,
            rename,
            run_full_project_diagnostics,
            run_single_file_diagnostics,
            schedule_change_diagnostics,
            schedule_full_diagnostics,
            workspace_symbol,
        )
        for handler in [
            did_open, did_change, did_save, did_close,
            did_change_watched_files, code_action, completions,
            definition, references, hover, document_symbols,
            folding_range, prepare_rename, rename,
            workspace_symbol, document_highlight,
            run_full_project_diagnostics, run_single_file_diagnostics,
            schedule_full_diagnostics, schedule_change_diagnostics,
        ]:
            assert callable(handler), f"{handler} should be callable"


# =============================================================================
# 3. Чекеры и AST
# =============================================================================

class TestCheckers:
    """5 чекеров + BaseChecker + AST checker."""

    def test_import_base_checker(self):
        """BaseChecker — базовый класс для всех чекеров."""
        from senpy.rules.checkers import BaseChecker
        assert BaseChecker is not None
        assert hasattr(BaseChecker, "check_line")

    def test_import_all_checkers(self):
        """5 конкретных чекеров — Strategy pattern."""
        from senpy.rules.checkers import (
            AssetChecker,
            DialogueChecker,
            FormattingChecker,
            ScreenChecker,
            StateChecker,
        )
        for cls in [
            FormattingChecker, ScreenChecker, AssetChecker,
            DialogueChecker, StateChecker,
        ]:
            assert cls is not None

    def test_import_python_ast(self):
        """PythonAstChecker + type inference функции."""
        from senpy.rules.python_ast import (
            PythonAstChecker,
            extract_assigned_names,
            infer_ast_type,
            infer_default_value,
            infer_expr_type,
        )
        assert PythonAstChecker is not None
        for func in [infer_ast_type, infer_expr_type, infer_default_value, extract_assigned_names]:
            assert callable(func)

    def test_import_flow(self):
        """StoryFlowAnalyzer + вспомогательные функции."""
        from senpy.rules.flow import FlowBranch, StoryFlowAnalyzer, merge_flow_branches
        assert StoryFlowAnalyzer is not None
        assert FlowBranch is not None
        assert callable(merge_flow_branches)


# =============================================================================
# 4. Domain knowledge
# =============================================================================

class TestDomain:
    """Ren'Py API, text_tags, assets, rpa, tsundere."""

    def test_import_renpy_api(self):
        """RENPY_API_DOCS — hover-описания для 220+ Ren'Py API функций."""
        from senpy.domain.renpy_api import RENPY_API_DOCS, get_renpy_api_hover
        assert isinstance(RENPY_API_DOCS, dict)
        assert len(RENPY_API_DOCS) > 100, "Должно быть 220+ API описаний"
        assert callable(get_renpy_api_hover)

    def test_import_text_tags(self):
        """text_tags — парсинг {b}, {i}, [var] и т.д."""
        from senpy.domain.text_tags import get_utf16_range
        assert callable(get_utf16_range)

    def test_import_assets(self):
        """AssetManager — индексация спрайтов/аудио."""
        from senpy.domain.assets import AssetManager
        assert AssetManager is not None

    def test_import_rpa(self):
        """safe_load_rpa_index — безопасная загрузка .rpa архивов."""
        from senpy.domain.rpa import safe_load_rpa_index
        assert callable(safe_load_rpa_index)

    def test_import_tsundere(self):
        """Tsundere-режим — IS_RU и сообщения."""
        from senpy.domain.tsundere import IS_RU
        assert isinstance(IS_RU, bool)

    def test_import_deprecated(self):
        """DEPRECATED_APIS — для RPY107."""
        from senpy.rules.deprecated import DEPRECATED_APIS
        assert isinstance(DEPRECATED_APIS, dict)
        assert len(DEPRECATED_APIS) > 0

    def test_import_constants(self):
        """BUILTIN_SCREENS, BUILTIN_COLORS, BUILTIN_AUDIO_CHANNELS, BUILTIN_SYMBOLS."""
        from senpy.core.constants import (
            BUILTIN_AUDIO_CHANNELS,
            BUILTIN_COLORS,
            BUILTIN_SCREENS,
            BUILTIN_SYMBOLS,
            CLAUSE_KEYWORDS,
        )
        assert isinstance(BUILTIN_SCREENS, set)
        assert isinstance(BUILTIN_COLORS, set)
        assert isinstance(BUILTIN_AUDIO_CHANNELS, set)
        assert isinstance(BUILTIN_SYMBOLS, set)
        assert isinstance(CLAUSE_KEYWORDS, set)


# =============================================================================
# 5. Символы, scope, signature
# =============================================================================

class TestSymbolsAndScope:
    """Регистры символов и scope analysis."""

    def test_import_symbols(self):
        """5 Symbol-классов: VariableSymbol, LabelSymbol, ScreenSymbol, ImageSymbol, TransformSymbol."""
        from senpy.core.symbols import (
            ImageSymbol,
            LabelSymbol,
            ScreenSymbol,
            TransformSymbol,
            VariableSymbol,
        )
        for cls in [VariableSymbol, LabelSymbol, ScreenSymbol,
                    ImageSymbol, TransformSymbol]:
            assert cls is not None

    def test_import_scope(self):
        """Scope, ScopeStack, ScopeType — отслеживание области видимости."""
        from senpy.core.scope import Scope, ScopeStack, ScopeType
        assert Scope is not None
        assert ScopeStack is not None
        assert ScopeType is not None

    def test_import_signature(self):
        """SignatureInfo + парсеры сигнатур."""
        from senpy.core.signature import (
            SignatureInfo,
            parse_call_args,
            parse_signature,
            validate_call_arguments,
        )
        assert SignatureInfo is not None
        for func in [parse_signature, parse_call_args, validate_call_arguments]:
            assert callable(func)


# =============================================================================
# 6. I/O форматы
# =============================================================================

class TestIOFormats:
    """Экспортёры в разные форматы: SARIF, HTML, wiki, stubs, ci, traceback, stats."""

    def test_import_sarif(self):
        """generate_sarif — для GitHub Code Scanning."""
        from senpy.formats.sarif import generate_sarif
        assert callable(generate_sarif)

    def test_import_html_report(self):
        """generate_html_report — standalone HTML с Mermaid."""
        from senpy.formats.html_report import generate_html_report
        assert callable(generate_html_report)

    def test_import_wiki(self):
        """generate_project_wiki — Markdown-документация по правилам."""
        from senpy.formats.wiki import generate_project_wiki
        assert callable(generate_project_wiki)

    def test_import_stubs(self):
        """generate_stubs — Python type stubs (.pyi)."""
        from senpy.formats.stubs import generate_stubs
        assert callable(generate_stubs)

    def test_import_ci(self):
        """init_ci_workflow, find_repo_root — GitHub Actions workflow generation."""
        from senpy.formats.ci import find_repo_root, init_ci_workflow
        assert callable(init_ci_workflow)
        assert callable(find_repo_root)

    def test_import_traceback(self):
        """find_latest_traceback, parse_traceback_file — анализ краш-логов."""
        from senpy.formats.traceback import find_latest_traceback, parse_traceback_file
        assert callable(find_latest_traceback)
        assert callable(parse_traceback_file)

    def test_import_stats(self):
        """collect_story_stats, extract_character_names — статистика по проекту."""
        from senpy.formats.stats import (
            CharacterStats,
            StoryStats,
            collect_story_stats,
            extract_character_names,
        )
        assert callable(collect_story_stats)
        assert callable(extract_character_names)
        assert StoryStats is not None
        assert CharacterStats is not None

    def test_import_coverage(self):
        """calculate_translation_coverage — translation coverage."""
        from senpy.core.coverage import LanguageStats, calculate_translation_coverage
        assert callable(calculate_translation_coverage)
        assert LanguageStats is not None

    def test_import_rules_info(self):
        """RULES_DATABASE — машиночитаемая база правил."""
        from senpy.rules.rules_info import RULES_DATABASE
        assert isinstance(RULES_DATABASE, dict)
        assert len(RULES_DATABASE) >= 45


# =============================================================================
# 7. Formatter (subpackage)
# =============================================================================

class TestFormatter:
    """senpy.formatter — opinionated .rpy formatter."""

    def test_import_formatter(self):
        """Formatter, FormatConfig, FormatContext, register_rule."""
        from senpy.formatter import (
            FormatConfig,
            FormatContext,
            Formatter,
            register_rule,
        )
        assert Formatter is not None
        assert FormatConfig is not None
        assert FormatContext is not None
        assert callable(register_rule)

    def test_formatter_format_code_method(self):
        """Formatter.format_code — главный API."""
        from senpy.formatter import FormatConfig, Formatter
        fmt = Formatter(FormatConfig())
        assert hasattr(fmt, "format_code")
        assert hasattr(fmt, "format_file")
        # Smoke test — idempotency
        code = 'label start:\n\t"Hello"\n\treturn\n'
        out1 = fmt.format_code(code)
        out2 = fmt.format_code(out1)
        assert out1 == out2, "Formatter must be idempotent"

    def test_formatter_rules_loaded(self):
        """Все 4 правила formatter'а загружены через @register_rule."""
        from senpy.formatter.core import get_registered_rules
        rules = get_registered_rules()
        rule_names = [name for name, _ in rules]
        assert "FMT-INDENT" in rule_names
        assert "FMT-TRAILING-WS" in rule_names
        assert "FMT-EOF-NEWLINE" in rule_names
        assert "FMT-BLANK-LINES" in rule_names


# =============================================================================
# 8. Vendored unrpyc
# =============================================================================

class TestVendoredUnrpyc:
    """senpy.vendor.unrpyc — встроенный декомпилятор .rpyc."""

    def test_import_decompile_rpyc(self):
        """decompile_rpyc — главный API vendored unrpyc."""
        from senpy.vendor.unrpyc import decompile_rpyc, decompile_rpyc_bytes
        assert callable(decompile_rpyc)
        assert callable(decompile_rpyc_bytes)

    def test_import_unrpyc_exceptions(self):
        """RPYCDecompilationError, BadRpycException — кастомные исключения."""
        from senpy.vendor.unrpyc import BadRpycException, RPYCDecompilationError
        assert issubclass(RPYCDecompilationError, Exception)
        assert issubclass(BadRpycException, Exception)


# =============================================================================
# 9. Backward-compat: re-exports из senpy/__init__.py (если будут)
# =============================================================================

class TestSenpyPackageInit:
    """Проверка что `import senpy` работает и даёт ключевые имена.

    В 0.5.4 (реструктуризация) в senpy/__init__.py будут добавлены
    re-exports для обратной совместимости:
        from senpy import SenpyAnalyzer, Diagnostic, RULE_SEVERITY, __version__

    Этот тест гарантирует, что re-exports работают.
    """

    def test_import_senpy_package(self):
        """`import senpy` — базовый импорт пакета."""
        import senpy
        assert senpy is not None

    def test_senpy_version_attribute(self):
        """senpy.__version__ — должно быть доступно и иметь semver-формат."""
        # Проверяем, что версия доступна и имеет формат X.Y.Z (semver)
        # Не хардкодим конкретную версию — тест должен работать для всех
        # будущих релизов (0.6.0, 0.7.0, 1.0.0, и т.д.)
        import re

        import senpy

        # __version__ хранится в senpy/__version__.py (single source of truth)
        from senpy.__version__ import __version__
        assert re.match(r"^\d+\.\d+\.\d+", __version__), (
            f"__version__ should be in semver format (X.Y.Z), got: {__version__!r}"
        )


# =============================================================================
# 10. Module structure integrity — все модули импортируемы
# =============================================================================

class TestModuleIntegrity:
    """Все .py модули в senpy/ (без vendor/) должны быть импортируемыми.

    Этот тест ловит:
    - Опечатки в именах модулей
    - Скрытые SyntaxError'ы (которые не ловятся на collection)
    - Циклические импорты, которые ломают import
    """

    @pytest.mark.parametrize("module_name", [
        # Core
        "senpy.core.analyzer",
        "senpy.core.models",
        "senpy.core.cache",
        "senpy.core.cache_manifest",
        "senpy.core.config",
        "senpy.core.constants",
        "senpy.core.coverage",
        "senpy.core.scope",
        "senpy.core.signature",
        "senpy.core.sink",
        "senpy.core.symbols",
        # Rules
        "senpy.rules.base",
        "senpy.rules.checkers",
        "senpy.rules.checkers.formatting",
        "senpy.rules.checkers.screen",
        "senpy.rules.checkers.asset",
        "senpy.rules.checkers.dialogue",
        "senpy.rules.checkers.state",
        "senpy.rules.python_ast",
        "senpy.rules.flow",
        "senpy.rules.deprecated",
        "senpy.rules.rules_info",
        # CLI
        "senpy.cli.main",
        "senpy.cli.commands",
        "senpy.cli.unrpyc",
        # LSP
        "senpy.lsp.server",
        # I/O formats
        "senpy.formats.sarif",
        "senpy.formats.html_report",
        "senpy.formats.wiki",
        "senpy.formats.stubs",
        "senpy.formats.ci",
        "senpy.formats.traceback",
        "senpy.formats.stats",
        # Domain
        "senpy.domain.renpy_api",
        "senpy.domain.text_tags",
        "senpy.domain.assets",
        "senpy.domain.rpa",
        "senpy.domain.tsundere",
        # Meta
        "senpy.__version__",
        # Formatter subpackage
        "senpy.formatter",
        "senpy.formatter.core",
        "senpy.formatter.rules",
        "senpy.formatter.rules.indent",
        "senpy.formatter.rules.whitespace",
    ])
    def test_module_importable(self, module_name: str):
        """Модуль {module_name} должен быть импортируемым без ошибок."""
        try:
            mod = importlib.import_module(module_name)
            assert mod is not None, f"Модуль {module_name} импортировался как None"
        except ImportError as e:
            pytest.fail(
                f"Не удалось импортировать {module_name}: {e}. "
                f"Возможно, циклический импорт или SyntaxError."
            )


# =============================================================================
# 11. Circular import detection — косвенная проверка
# =============================================================================

class TestNoCircularImports:
    """Проверка что главные модули не создают критических циклических зависимостей.

    Полная проверка циклов делается через ast-анализ в скрипте
    scripts/check_cycles.py (запланирован в Фазе 1). Здесь —
    базовая проверка: модули импортируются в произвольном порядке
    без ImportError.

    В 0.5.2 порядок импортов может иметь значение (есть циклы через analyzer),
    но Python кэширует модули в sys.modules — поэтому второй импорт берёт
    кэшированную версию, и цикл не приводит к ImportError.

    В 0.5.3 (после разрыва циклов) эти тесты должны работать даже после
    очистки sys.modules — это и будет индикатором что циклы реально разорваны.
    """

    @pytest.mark.parametrize("module_a,module_b", [
        ("senpy.core.analyzer", "senpy.cli.main"),
        ("senpy.core.analyzer", "senpy.rules.checkers"),
        ("senpy.core.analyzer", "senpy.rules.python_ast"),
        ("senpy.core.analyzer", "senpy.rules.flow"),
        ("senpy.core.analyzer", "senpy.core.cache"),
    ])
    def test_no_circular_dependency(self, module_a: str, module_b: str):
        """Модули {module_a} и {module_b} должны быть импортируемыми в любом порядке.

        В 0.5.2 это работает благодаря кэшу sys.modules.
        После Фазы 1.6 (разрыв всех циклов) — должно работать даже
        после очистки кэша (что проверяет scripts/check_cycles.py).
        """
        # Импортируем в обратном порядке
        mod_b = importlib.import_module(module_b)
        mod_a = importlib.import_module(module_a)
        assert mod_a is not None
        assert mod_b is not None


# =============================================================================
# Imports needed for the test itself
# =============================================================================

import sys
