"""TDD тесты для parse_args() — Phase 3, Step 1 (0.5.6).

RED: эти тесты падают, потому что parse_args() ещё не существует.
GREEN: после extraction из main() — тесты проходят.

Тестирует:
1. parse_args() существует и возвращает Namespace
2. Дефолтные значения корректны (path=".", output_format="text", etc.)
3. Ключевые флаги парсятся правильно (--fix, --check, --diff, --version, etc.)
4. --ignore парсит список кодов
5. --output-format принимает text/json/sarif
6. --output-format отклоняет невалидные значения
7. Позиционный аргумент path работает
"""
from __future__ import annotations

import pytest


class TestParseArgs:
    """Тесты для parse_args() — извлечено из main() в Phase 3 Step 1."""

    def test_parse_args_exists(self):
        """parse_args() должна существовать в senpy.cli.main."""
        from senpy.cli.main import parse_args
        assert callable(parse_args)

    def test_parse_args_returns_namespace(self):
        """parse_args() возвращает argparse.Namespace."""
        import argparse
        from senpy.cli.main import parse_args
        args = parse_args([])
        assert isinstance(args, argparse.Namespace)

    def test_default_path_is_dot(self):
        """Без аргументов path = '.' (текущая директория)."""
        from senpy.cli.main import parse_args
        args = parse_args([])
        assert args.path == "."

    def test_positional_path(self):
        """Позиционный аргумент — путь к проекту."""
        from senpy.cli.main import parse_args
        args = parse_args(["/some/project"])
        assert args.path == "/some/project"

    def test_default_output_format_is_text(self):
        """Дефолтный output_format = 'text'."""
        from senpy.cli.main import parse_args
        args = parse_args([])
        assert args.output_format == "text"

    def test_output_format_json(self):
        """--output-format json парсится."""
        from senpy.cli.main import parse_args
        args = parse_args(["--output-format", "json"])
        assert args.output_format == "json"

    def test_output_format_sarif(self):
        """--output-format sarif парсится."""
        from senpy.cli.main import parse_args
        args = parse_args(["--output-format", "sarif"])
        assert args.output_format == "sarif"

    def test_output_format_alias(self):
        """--format работает как alias для --output-format."""
        from senpy.cli.main import parse_args
        args = parse_args(["--format", "json"])
        assert args.output_format == "json"

    def test_output_format_invalid_rejected(self):
        """Невалидный --output-format отклоняется."""
        from senpy.cli.main import parse_args
        with pytest.raises(SystemExit):
            parse_args(["--output-format", "xml"])

    def test_version_flag(self):
        """--version парсится как store_true."""
        from senpy.cli.main import parse_args
        args = parse_args(["--version"])
        assert args.version is True

    def test_fix_flag(self):
        """--fix парсится как store_true."""
        from senpy.cli.main import parse_args
        args = parse_args(["--fix"])
        assert args.fix is True

    def test_check_flag(self):
        """--check парсится как store_true."""
        from senpy.cli.main import parse_args
        args = parse_args(["--check"])
        assert args.check is True

    def test_diff_flag(self):
        """--diff парсится как store_true."""
        from senpy.cli.main import parse_args
        args = parse_args(["--diff"])
        assert args.diff is True

    def test_exit_zero_flag(self):
        """--exit-zero парсится как store_true."""
        from senpy.cli.main import parse_args
        args = parse_args(["--exit-zero"])
        assert args.exit_zero is True

    def test_lsp_flag(self):
        """--lsp парсится как store_true."""
        from senpy.cli.main import parse_args
        args = parse_args(["--lsp"])
        assert args.lsp is True

    def test_tsundere_flag(self):
        """--tsundere парсится как store_true."""
        from senpy.cli.main import parse_args
        args = parse_args(["--tsundere"])
        assert args.tsundere is True

    def test_ignore_parses_list(self):
        """--ignore парсит список кодов правил."""
        from senpy.cli.main import parse_args
        args = parse_args(["--ignore", "RPY104", "RPY101"])
        assert args.ignore == ["RPY104", "RPY101"]

    def test_ignore_default_none(self):
        """Без --ignore args.ignore = None."""
        from senpy.cli.main import parse_args
        args = parse_args([])
        assert args.ignore is None

    def test_max_errors_int(self):
        """--max-errors парсится как int."""
        from senpy.cli.main import parse_args
        args = parse_args(["--max-errors", "100"])
        assert args.max_errors == 100

    def test_no_cache_flag(self):
        """--no-cache парсится как store_true."""
        from senpy.cli.main import parse_args
        args = parse_args(["--no-cache"])
        assert args.no_cache is True

    def test_rules_flag(self):
        """--rules парсится как store_true."""
        from senpy.cli.main import parse_args
        args = parse_args(["--rules"])
        assert args.rules is True

    def test_rule_flag_with_value(self):
        """--rule RPY104 парсится с значением."""
        from senpy.cli.main import parse_args
        args = parse_args(["--rule", "RPY104"])
        assert args.rule == "RPY104"

    def test_decompile_flag(self):
        """--decompile парсится как store_true."""
        from senpy.cli.main import parse_args
        args = parse_args(["--decompile"])
        assert args.decompile is True

    def test_errors_only_flag(self):
        """--errors-only парсится как store_true."""
        from senpy.cli.main import parse_args
        args = parse_args(["--errors-only"])
        assert args.errors_only is True

    def test_graph_flag(self):
        """--graph парсится как store_true."""
        from senpy.cli.main import parse_args
        args = parse_args(["--graph"])
        assert args.graph is True

    def test_output_file_flag(self):
        """--output-file парсится с значением."""
        from senpy.cli.main import parse_args
        args = parse_args(["--output-file", "report.txt"])
        assert args.output_file == "report.txt"

    def test_traceback_default_const(self):
        """--traceback без аргумента даёт const='traceback.txt'."""
        from senpy.cli.main import parse_args
        args = parse_args(["--traceback"])
        assert args.traceback == "traceback.txt"

    def test_traceback_with_value(self):
        """--traceback errors.txt парсится с явным значением."""
        from senpy.cli.main import parse_args
        args = parse_args(["--traceback", "errors.txt"])
        assert args.traceback == "errors.txt"

    def test_all_defaults_false(self):
        """Все store_true флаги по умолчанию False."""
        from senpy.cli.main import parse_args
        args = parse_args([])
        assert args.version is False
        assert args.fix is False
        assert args.check is False
        assert args.diff is False
        assert args.exit_zero is False
        assert args.lsp is False
        assert args.tsundere is False
        assert args.no_cache is False
        assert args.clear_cache is False
        assert args.rules is False
        assert args.decompile is False
        assert args.errors_only is False
        assert args.info is False
        assert args.graph is False
        assert args.coverage is False
        assert args.stats is False
        assert args.defaults is False
