"""Characterization tests for parse_args.

parse_args creates argparse parser with 5 groups of arguments:
  1. General (--version, path positional)
  2. Rules & Documentation (--rules, --rule)
  3. Analysis & Autofix (--fix, --coverage, --stats, --defaults, --errors-only,
     --info, --ignore, --select, --extend-select, --extend-ignore, --max-errors,
     --no-cache, --clear-cache, --check, --diff, --exit-zero, --show-fixes)
  4. Visualization & Reports (--export-html, --export-wiki, --graph, --graph-file,
     --output-format, --output-file)
  5. Tools & Integrations (--lsp, --init-ci, --traceback, --stubs, --decompile,
     --unrpyc, --tsundere)

After ARCH-2: parse_args will call 5 helpers (_add_general_args, _add_rules_args,
_add_lint_args, _add_export_args, _add_tools_args). Behavior must be identical.
"""
from __future__ import annotations

import pytest

from senpy.cli.main import parse_args

# =============================================================================
# 1. Defaults — no args
# =============================================================================

def test_parse_args_defaults():
    """parse_args with no argv returns Namespace with all defaults."""
    args = parse_args([])

    assert args.path == "."
    assert args.version is False
    assert args.rules is False
    assert args.rule is None
    assert args.fix is False
    assert args.coverage is False
    assert args.stats is False
    assert args.defaults is False
    assert args.errors_only is False
    assert args.info is False
    assert args.ignore is None
    assert args.select is None
    assert args.extend_select is None
    assert args.extend_ignore is None
    assert args.max_errors is None
    assert args.no_cache is False
    assert args.clear_cache is False
    assert args.check is False
    assert args.diff is False
    assert args.exit_zero is False
    assert args.show_fixes is False
    assert args.export_html is None
    assert args.export_wiki is None
    assert args.graph is False
    assert args.graph_file is None
    assert args.output_format == "text"
    assert args.output_file is None
    assert args.lsp is False
    assert args.init_ci is False
    assert args.traceback is None
    assert args.stubs is None
    assert args.decompile is False
    assert args.unrpyc is None
    assert args.tsundere is False


# =============================================================================
# 2. Positional path
# =============================================================================

def test_parse_args_positional_path():
    """parse_args with positional arg sets path."""
    args = parse_args(["/path/to/project"])
    assert args.path == "/path/to/project"


def test_parse_args_default_path_is_dot():
    """Without path arg, default is '.'."""
    args = parse_args([])
    assert args.path == "."


# =============================================================================
# 3. Boolean flags
# =============================================================================

@pytest.mark.parametrize("flag,attr", [
    ("--version", "version"),
    ("--rules", "rules"),
    ("--fix", "fix"),
    ("--coverage", "coverage"),
    ("--stats", "stats"),
    ("--defaults", "defaults"),
    ("--errors-only", "errors_only"),
    ("--info", "info"),
    ("--no-cache", "no_cache"),
    ("--clear-cache", "clear_cache"),
    ("--check", "check"),
    ("--diff", "diff"),
    ("--exit-zero", "exit_zero"),
    ("--show-fixes", "show_fixes"),
    ("--graph", "graph"),
    ("--lsp", "lsp"),
    ("--init-ci", "init_ci"),
    ("--decompile", "decompile"),
    ("--tsundere", "tsundere"),
])
def test_parse_args_boolean_flags(flag, attr):
    """Each boolean flag sets its attribute to True."""
    args = parse_args([flag])
    assert getattr(args, attr) is True


# =============================================================================
# 4. String/value flags
# =============================================================================

def test_parse_args_rule_flag():
    """--rule RPY104 sets rule attribute."""
    args = parse_args(["--rule", "RPY104"])
    assert args.rule == "RPY104"


def test_parse_args_ignore_flag_multiple():
    """--ignore RPY101 RPY102 sets list."""
    args = parse_args(["--ignore", "RPY101", "RPY102"])
    assert args.ignore == ["RPY101", "RPY102"]


def test_parse_args_select_flag():
    """--select RPY101 RPY102 sets list."""
    args = parse_args(["--select", "RPY101", "RPY102"])
    assert args.select == ["RPY101", "RPY102"]


def test_parse_args_extend_select_flag():
    """--extend-select RPY103 sets list."""
    args = parse_args(["--extend-select", "RPY103"])
    assert args.extend_select == ["RPY103"]


def test_parse_args_extend_ignore_flag():
    """--extend-ignore RPY104 sets list."""
    args = parse_args(["--extend-ignore", "RPY104"])
    assert args.extend_ignore == ["RPY104"]


def test_parse_args_max_errors_int():
    """--max-errors 100 sets int."""
    args = parse_args(["--max-errors", "100"])
    assert args.max_errors == 100


def test_parse_args_export_html():
    """--export-html report.html sets string."""
    args = parse_args(["--export-html", "report.html"])
    assert args.export_html == "report.html"


def test_parse_args_export_wiki_with_value():
    """--export-wiki DOCS.md sets string."""
    args = parse_args(["--export-wiki", "DOCS.md"])
    assert args.export_wiki == "DOCS.md"


def test_parse_args_export_wiki_no_value_uses_const():
    """--export-wiki without value uses const 'PROJECT_WIKI.md'."""
    args = parse_args(["--export-wiki"])
    assert args.export_wiki == "PROJECT_WIKI.md"


def test_parse_args_graph_file():
    """--graph-file story.md sets string."""
    args = parse_args(["--graph-file", "story.md"])
    assert args.graph_file == "story.md"


def test_parse_args_output_format_choices():
    """--output-format accepts all 5 choices."""
    for fmt in ["text", "json", "sarif", "junit", "github"]:
        args = parse_args(["--output-format", fmt])
        assert args.output_format == fmt


def test_parse_args_output_format_alias():
    """--format is alias for --output-format."""
    args = parse_args(["--format", "json"])
    assert args.output_format == "json"


def test_parse_args_output_file():
    """--output-file report.txt sets string."""
    args = parse_args(["--output-file", "report.txt"])
    assert args.output_file == "report.txt"


def test_parse_args_traceback_with_value():
    """--traceback errors.txt sets string."""
    args = parse_args(["--traceback", "errors.txt"])
    assert args.traceback == "errors.txt"


def test_parse_args_traceback_no_value_uses_const():
    """--traceback without value uses const 'traceback.txt'."""
    args = parse_args(["--traceback"])
    assert args.traceback == "traceback.txt"


def test_parse_args_stubs_with_value():
    """--stubs my_typings/ sets string."""
    args = parse_args(["--stubs", "my_typings/"])
    assert args.stubs == "my_typings/"


def test_parse_args_stubs_no_value_uses_const():
    """--stubs without value uses const 'typings'."""
    args = parse_args(["--stubs"])
    assert args.stubs == "typings"


def test_parse_args_unrpyc():
    """--unrpyc /path/to/unrpyc.py sets string."""
    args = parse_args(["--unrpyc", "/path/to/unrpyc.py"])
    assert args.unrpyc == "/path/to/unrpyc.py"


# =============================================================================
# 5. Combined flags
# =============================================================================

def test_parse_args_multiple_flags_combined():
    """Multiple flags can be combined."""
    args = parse_args([
        "/path/to/project",
        "--fix",
        "--errors-only",
        "--no-cache",
        "--output-format", "json",
    ])
    assert args.path == "/path/to/project"
    assert args.fix is True
    assert args.errors_only is True
    assert args.no_cache is True
    assert args.output_format == "json"


def test_parse_args_path_with_flags():
    """Path positional works alongside flags."""
    args = parse_args(["--fix", "/path/to/project", "--no-cache"])
    assert args.path == "/path/to/project"
    assert args.fix is True
    assert args.no_cache is True


# =============================================================================
# 6. Help exits with SystemExit
# =============================================================================

def test_parse_args_help_exits_zero(capsys):
    """--help prints help and exits 0."""
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    # Help should mention key flags
    assert "--fix" in captured.out
    assert "--output-format" in captured.out
    assert "--lsp" in captured.out


# =============================================================================
# 7. Invalid choices raise SystemExit
# =============================================================================

def test_parse_args_invalid_output_format_exits_nonzero(capsys):
    """--output-format invalid choice exits with error."""
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["--output-format", "invalid"])
    assert exc_info.value.code != 0


# =============================================================================
# 8. Backward compat — parse_args importable
# =============================================================================

def test_parse_args_importable_from_cli_main():
    """parse_args must remain importable from senpy.cli.main after ARCH-2."""
    from senpy.cli.main import parse_args as f1
    assert callable(f1)
