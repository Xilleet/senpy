from __future__ import annotations

from senpy.cli._console import console  # noqa: F401 — re-exported for backward compat
from senpy.cli.args import (  # noqa: F401 — re-exported for backward compat
    _add_export_args,
    _add_general_args,
    _add_lint_args,
    _add_rules_args,
    _add_tools_args,
    parse_args,
)
from senpy.cli.commands import (  # noqa: F401 — re-exported for backward compat
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
from senpy.cli.discover import (  # noqa: F401 — re-exported for backward compat
    _decompile_sandbox,
    _find_orphaned_rpyc,
    _find_rpy_files,
    discover_files,
)
from senpy.cli.early_exits import (  # noqa: F401 — re-exported for backward compat
    _dispatch_subcommand,
    _handle_early_exits,
    _validate_flag_combinations,
)
from senpy.cli.filters import (  # noqa: F401 — re-exported for backward compat
    _build_full_ignored,
    _build_select_codes,
    _build_tag_filters,
    _count_hidden_info,
    _filter_active,
    filter_diagnostics,
    load_senpy_ignore,
)
from senpy.cli.renderers import (  # noqa: F401 — re-exported for backward compat
    SEVERITY_STYLES,
    _render_diagnostic_cards,
    _render_fixable_report,
    _render_summary_line,
    _render_summary_table,
    _xml_escape,
    render_github,
    render_gitlab,
    render_json,
    render_junit,
    render_rdjson,
    render_sarif,
    render_text,
)
from senpy.cli.runner import (  # noqa: F401 — re-exported for backward compat
    _exit_with_output_redirect,
    _handle_check_mode,
    _handle_diff_mode,
    _handle_output_format,
    _handle_post_analysis,
    _make_file_console,
    _null_redirect,
    _NullRedirect,
    _print_scan_banner,
    _replace_console,
    _ReplaceConsole,
    _run_analysis,
    _setup_diff_interception,
    _setup_rule_filters,
    main,
)
from senpy.cli.unrpyc import (  # noqa: F401 — re-exported for backward compat with tests
    decompile_to_sandbox,
    extract_scripts_from_rpa,
    find_unrpyc_executable,
)
from senpy.core.analyzer import SenpyAnalyzer  # noqa: F401 — re-exported for backward compat
from senpy.core.config import load_config  # noqa: F401 — re-exported for backward compat
from senpy.domain.tsundere import TSUNDERE_UI  # noqa: F401 — re-exported for backward compat
from senpy.formats.traceback import (  # noqa: F401 — re-exported for backward compat
    find_latest_traceback,
    parse_traceback_file,
)
from senpy.formatter import FormatConfig, Formatter  # noqa: F401 — re-exported for backward compat


def _dispatch_format(argv: list[str]) -> int:
    """Handle `senpy format` subcommand.

    Re-exported from cli/format_dispatch.py (extracted in 0.6.4,).
    Kept here for backward compatibility — existing callers and tests use
    `from senpy.cli.main import _dispatch_format`.
    """
    from senpy.cli.format_dispatch import dispatch_format

    return dispatch_format(argv)


if __name__ == "__main__":
    main()
