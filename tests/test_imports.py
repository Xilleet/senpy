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
      (например `from senpy.analyzer` → `from senpy.core.analyzer`),
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
        from senpy.analyzer import SenpyAnalyzer
        assert SenpyAnalyzer is not None
        assert hasattr(SenpyAnalyzer, "run")
        assert hasattr(SenpyAnalyzer, "_collect_symbols")
        assert hasattr(SenpyAnalyzer, "_analyze_file")

    def test_import_senpy_models(self):
        """Diagnostic, RULE_SEVERITY, AnalysisResult, FileScope — модели данных."""
        from senpy.models import Diagnostic, RULE_SEVERITY, AnalysisResult, FileScope
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
        from senpy.cache import (
            CacheManager, CacheManifest, CachedFileEntry, SafeCacheUnpickler,
            compute_file_hash,
        )
        assert CacheManager is not None
        assert CacheManifest is not None
        assert CachedFileEntry is not None
        assert SafeCacheUnpickler is not None
        assert callable(compute_file_hash)

    def test_import_senpy_constants(self):
        """SENPY_VERSION — из single source of truth (__version__.py)."""
        from senpy.constants import SENPY_VERSION
        assert SENPY_VERSION is not None
        assert isinstance(SENPY_VERSION, str)
        assert len(SENPY_VERSION.split(".")) == 3  # X.Y.Z

    def test_import_senpy_version(self):
        """__version__ — single source of truth."""
        from senpy.__version__ import __version__, VERSION_WITH_PREFIX, MAJOR, MINOR, PATCH
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
        from senpy.cli import main
        assert callable(main)

    def test_import_cli_dispatch_format(self):
        """_dispatch_format — subcommand `senpy format`."""
        from senpy.cli import _dispatch_format
        assert callable(_dispatch_format)

    def test_import_cli_commands_handlers(self):
        """Все handler'ы из _cli_commands.py — для subcommands."""
        from senpy._cli_commands import (
            handle_traceback, handle_init_ci, handle_coverage,
            handle_clear_cache, handle_stats, handle_export_wiki,
            handle_export_html, handle_graph, handle_defaults, handle_stubs,
        )
        for handler in [
            handle_traceback, handle_init_ci, handle_coverage,
            handle_clear_cache, handle_stats, handle_export_wiki,
            handle_export_html, handle_graph, handle_defaults, handle_stubs,
        ]:
            assert callable(handler), f"{handler} should be callable"

    def test_import_unrpyc_bootstrap(self):
        """Функции unrpyc/rpa — для декомпиляции .rpyc и извлечения .rpa."""
        from senpy._unrpyc_bootstrap import (
            load_config, find_in_directory_tree, download_unrpyc,
            find_unrpyc_executable, extract_scripts_from_rpa,
            decompile_to_sandbox,
        )
        for func in [
            load_config, find_in_directory_tree, download_unrpyc,
            find_unrpyc_executable, extract_scripts_from_rpa,
            decompile_to_sandbox,
        ]:
            assert callable(func), f"{func} should be callable"

    def test_import_server(self):
        """LSP-сервер и его handlers."""
        from senpy.server import server
        assert server is not None
        # server — экземпляр LanguageServer из pygls
        assert hasattr(server, "feature")

    def test_import_server_handlers(self):
        """Главные LSP handlers — должны быть импортируемы."""
        from senpy.server import (
            did_open, did_change, did_save, did_close,
            did_change_watched_files, code_action, completions,
            definition, references, hover, document_symbols,
            folding_range, prepare_rename, rename,
            workspace_symbol, document_highlight,
            run_full_project_diagnostics, run_single_file_diagnostics,
            schedule_full_diagnostics, schedule_change_diagnostics,
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
        from senpy.checkers import BaseChecker
        assert BaseChecker is not None
        assert hasattr(BaseChecker, "check_line")

    def test_import_all_checkers(self):
        """5 конкретных чекеров — Strategy pattern."""
        from senpy.checkers import (
            FormattingChecker, ScreenChecker, AssetChecker,
            DialogueChecker, StateChecker,
        )
        for cls in [
            FormattingChecker, ScreenChecker, AssetChecker,
            DialogueChecker, StateChecker,
        ]:
            assert cls is not None

    def test_import_python_ast(self):
        """PythonAstChecker + type inference функции."""
        from senpy.python_ast import (
            PythonAstChecker, infer_ast_type, infer_expr_type,
            infer_default_value, extract_assigned_names,
        )
        assert PythonAstChecker is not None
        for func in [infer_ast_type, infer_expr_type, infer_default_value, extract_assigned_names]:
            assert callable(func)

    def test_import_flow(self):
        """StoryFlowAnalyzer + вспомогательные функции."""
        from senpy.flow import StoryFlowAnalyzer, FlowBranch, merge_flow_branches
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
        from senpy.renpy_api import RENPY_API_DOCS, get_renpy_api_hover
        assert isinstance(RENPY_API_DOCS, dict)
        assert len(RENPY_API_DOCS) > 100, "Должно быть 220+ API описаний"
        assert callable(get_renpy_api_hover)

    def test_import_text_tags(self):
        """text_tags — парсинг {b}, {i}, [var] и т.д."""
        from senpy.text_tags import get_utf16_range
        assert callable(get_utf16_range)

    def test_import_assets(self):
        """AssetManager — индексация спрайтов/аудио."""
        from senpy.assets import AssetManager
        assert AssetManager is not None

    def test_import_rpa(self):
        """safe_load_rpa_index — безопасная загрузка .rpa архивов."""
        from senpy.rpa import safe_load_rpa_index
        assert callable(safe_load_rpa_index)

    def test_import_tsundere(self):
        """Tsundere-режим — IS_RU и сообщения."""
        from senpy.tsundere import IS_RU
        assert isinstance(IS_RU, bool)

    def test_import_deprecated(self):
        """DEPRECATED_APIS — для RPY107."""
        from senpy.deprecated import DEPRECATED_APIS
        assert isinstance(DEPRECATED_APIS, dict)
        assert len(DEPRECATED_APIS) > 0

    def test_import_constants(self):
        """BUILTIN_SCREENS, BUILTIN_COLORS, BUILTIN_AUDIO_CHANNELS, BUILTIN_SYMBOLS."""
        from senpy.constants import (
            BUILTIN_SCREENS, BUILTIN_COLORS, BUILTIN_AUDIO_CHANNELS,
            BUILTIN_SYMBOLS, CLAUSE_KEYWORDS,
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
        from senpy.symbols import (
            VariableSymbol, LabelSymbol, ScreenSymbol,
            ImageSymbol, TransformSymbol,
        )
        for cls in [VariableSymbol, LabelSymbol, ScreenSymbol,
                    ImageSymbol, TransformSymbol]:
            assert cls is not None

    def test_import_scope(self):
        """Scope, ScopeStack, ScopeType — отслеживание области видимости."""
        from senpy.scope import Scope, ScopeStack, ScopeType
        assert Scope is not None
        assert ScopeStack is not None
        assert ScopeType is not None

    def test_import_signature(self):
        """SignatureInfo + парсеры сигнатур."""
        from senpy.signature import (
            SignatureInfo, parse_signature, parse_call_args,
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
        from senpy.sarif import generate_sarif
        assert callable(generate_sarif)

    def test_import_html_report(self):
        """generate_html_report — standalone HTML с Mermaid."""
        from senpy.html_report import generate_html_report
        assert callable(generate_html_report)

    def test_import_wiki(self):
        """generate_project_wiki — Markdown-документация по правилам."""
        from senpy.wiki import generate_project_wiki
        assert callable(generate_project_wiki)

    def test_import_stubs(self):
        """generate_stubs — Python type stubs (.pyi)."""
        from senpy.stubs import generate_stubs
        assert callable(generate_stubs)

    def test_import_ci(self):
        """init_ci_workflow, find_repo_root — GitHub Actions workflow generation."""
        from senpy.ci import init_ci_workflow, find_repo_root
        assert callable(init_ci_workflow)
        assert callable(find_repo_root)

    def test_import_traceback(self):
        """find_latest_traceback, parse_traceback_file — анализ краш-логов."""
        from senpy.traceback import find_latest_traceback, parse_traceback_file
        assert callable(find_latest_traceback)
        assert callable(parse_traceback_file)

    def test_import_stats(self):
        """collect_story_stats, extract_character_names — статистика по проекту."""
        from senpy.stats import collect_story_stats, extract_character_names, StoryStats, CharacterStats
        assert callable(collect_story_stats)
        assert callable(extract_character_names)
        assert StoryStats is not None
        assert CharacterStats is not None

    def test_import_coverage(self):
        """calculate_translation_coverage — translation coverage."""
        from senpy.coverage import calculate_translation_coverage, LanguageStats
        assert callable(calculate_translation_coverage)
        assert LanguageStats is not None

    def test_import_rules_info(self):
        """RULES_DATABASE — машиночитаемая база правил."""
        from senpy.rules_info import RULES_DATABASE
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
            Formatter, FormatConfig, FormatContext, register_rule,
        )
        assert Formatter is not None
        assert FormatConfig is not None
        assert FormatContext is not None
        assert callable(register_rule)

    def test_formatter_format_code_method(self):
        """Formatter.format_code — главный API."""
        from senpy.formatter import Formatter, FormatConfig
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
        from senpy.vendor.unrpyc import RPYCDecompilationError, BadRpycException
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
        """senpy.__version__ — должно быть доступно."""
        import senpy
        # На момент 0.5.2 __version__ может не быть в senpy/__init__.py,
        # но это планируется добавить в 0.5.3 (см. worklog Фаза 1.1)
        # Пока проверяем через senpy.__version__ submodule
        from senpy.__version__ import __version__
        assert __version__ == "0.5.2" or __version__.startswith("0.5.")


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
        "senpy.analyzer",
        "senpy.models",
        "senpy.cache",
        "senpy.constants",
        "senpy.coverage",
        "senpy.scope",
        "senpy.signature",
        "senpy.symbols",
        # Rules
        "senpy.checkers",
        "senpy.python_ast",
        "senpy.flow",
        "senpy.deprecated",
        "senpy.rules_info",
        # CLI
        "senpy.cli",
        "senpy._cli_commands",
        "senpy._unrpyc_bootstrap",
        # LSP
        "senpy.server",
        # I/O formats
        "senpy.sarif",
        "senpy.html_report",
        "senpy.wiki",
        "senpy.stubs",
        "senpy.ci",
        "senpy.traceback",
        "senpy.stats",
        # Domain
        "senpy.renpy_api",
        "senpy.text_tags",
        "senpy.assets",
        "senpy.rpa",
        "senpy.tsundere",
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
        ("senpy.analyzer", "senpy.cli"),
        ("senpy.analyzer", "senpy.checkers"),
        ("senpy.analyzer", "senpy.python_ast"),
        ("senpy.analyzer", "senpy.flow"),
        ("senpy.analyzer", "senpy.cache"),
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
