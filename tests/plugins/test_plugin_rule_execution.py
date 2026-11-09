"""End-to-end integration test for plugin rule execution during analysis.

Regression for B2 (T-003): the plugin system was metadata-only —
``Rule.check(ctx)`` was never invoked from the analyzer's lint loop.
A user who installed and trusted an example plugin (e.g.
``todo_comment_plugin``) would see RPY902 in ``senpy rule list`` output
but RPY902 would never fire on actual ``.rpy`` files.

These tests verify that:
  1. With ``enable_plugins = true`` in senpy.toml, registered plugin
     rules run during ``analyzer.run()``.
  2. Without ``enable_plugins``, plugin rules are silent (default false
     in 0.8.0 — see T-003 in WORKLOG).
  3. Plugin rule diagnostics honour ``# noqa`` directives (because
     they go through ``_add_diagnostic_by_file``, see T-004).
  4. A broken plugin rule (one whose ``check()`` raises) is isolated —
     it does not crash the analyzer, other rules continue to run.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

from senpy.core.analyzer import SenpyAnalyzer
from senpy.plugins.autoload import reset_autoload_state
from senpy.plugins.registry import (
    clear_registered_lint_rules,
    get_registered_lint_rules,
)
from tests._helpers.paths import PLUGIN_DIR

# Locate the example plugin's rules.py on disk.
_PLUGIN_DIR = PLUGIN_DIR
_RULES_PY = _PLUGIN_DIR / "todo_comment_plugin" / "rules.py"


def _load_rules_module() -> ModuleType:
    """Load the example plugin's rules.py and register it in sys.modules
    so ``from senpy.api import Diagnostic`` inside the plugin resolves."""
    if not _RULES_PY.is_file():
        pytest.skip(f"Example plugin not found at {_RULES_PY}")
    spec = importlib.util.spec_from_file_location("todo_comment_plugin.rules", _RULES_PY)
    if spec is None or spec.loader is None:
        pytest.skip(f"Could not load module spec for {_RULES_PY}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["todo_comment_plugin.rules"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset plugin registry before/after each test."""
    reset_autoload_state()
    clear_registered_lint_rules()
    yield
    reset_autoload_state()
    clear_registered_lint_rules()


@pytest.fixture
def todo_plugin_registered():
    """Load the example todo_comment_plugin and register its Rule."""
    rules_module = _load_rules_module()
    # The plugin module's @register_rule decorator has already registered
    # TodoCommentRule in the global registry on import. Just confirm it's
    # there.
    registered = list(get_registered_lint_rules())
    assert any(
        cls is rules_module.TodoCommentRule for _code, cls in registered
    ), "TodoCommentRule not registered after loading the example plugin"
    return rules_module.TodoCommentRule


def _make_game(tmp_path: Path, code: str) -> Path:
    """Write code into a tmp game/script.rpy."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(code, encoding="utf-8")
    return tmp_path


# =============================================================================
# 1. enable_plugins = True — plugin rule fires during run()
# =============================================================================


def test_plugin_rule_fires_when_enable_plugins_true(todo_plugin_registered, tmp_path: Path):
    """With enable_plugins=True in senpy.toml, RPY902 must fire on a
    file containing a TODO comment."""
    # senpy.toml enables plugins
    (tmp_path / "senpy.toml").write_text("[senpy]\nenable_plugins = true\n", encoding="utf-8")

    code = "# TODO: implement this label\nlabel start:\n    return\n"
    _make_game(tmp_path, code)

    analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
    result = analyzer.run(quiet=True)

    rpy902_diags = [d for d in result.diagnostics if d.code == "RPY902"]
    assert len(rpy902_diags) == 1, (
        f"Expected exactly 1 RPY902 diagnostic, got {len(rpy902_diags)}. "
        f"Plugin rule.check() must be invoked when enable_plugins=true."
    )
    assert "TODO" in rpy902_diags[0].message
    assert rpy902_diags[0].line_number == 1


# =============================================================================
# 2. enable_plugins default — plugin rule is silent
# =============================================================================


def test_plugin_rule_silent_when_enable_plugins_not_set(todo_plugin_registered, tmp_path: Path):
    """Without enable_plugins in senpy.toml, RPY902 must NOT fire —
    the default is False in 0.8.0 (opt-in to plugin execution)."""
    # No senpy.toml → default config → enable_plugins defaults to False
    code = "# TODO: implement this label\nlabel start:\n    return\n"
    _make_game(tmp_path, code)

    analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
    result = analyzer.run(quiet=True)

    rpy902_diags = [d for d in result.diagnostics if d.code == "RPY902"]
    assert len(rpy902_diags) == 0, (
        "Plugin rule fired even though enable_plugins was not set "
        "in config — should default to False in 0.8.0"
    )


# =============================================================================
# 3. enable_plugins = False explicitly — plugin rule is silent
# =============================================================================


def test_plugin_rule_silent_when_enable_plugins_false(todo_plugin_registered, tmp_path: Path):
    """With enable_plugins=False in senpy.toml, RPY902 must NOT fire."""
    (tmp_path / "senpy.toml").write_text("[senpy]\nenable_plugins = false\n", encoding="utf-8")

    code = "# TODO: implement this label\nlabel start:\n    return\n"
    _make_game(tmp_path, code)

    analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
    result = analyzer.run(quiet=True)

    rpy902_diags = [d for d in result.diagnostics if d.code == "RPY902"]
    assert len(rpy902_diags) == 0


# =============================================================================
# 4. Plugin rule diagnostics honour # noqa directives (T-004 integration)
# =============================================================================


def test_plugin_rule_diagnostic_honours_noqa(todo_plugin_registered, tmp_path: Path):
    """A plugin rule diagnostic must be suppressable via # noqa.

    This re-uses the per-file noqa_map populated during _analyze_file
    (see T-004), so plugin rule diagnostics go through
    ``_add_diagnostic_by_file`` rather than being appended directly.
    """
    (tmp_path / "senpy.toml").write_text("[senpy]\nenable_plugins = true\n", encoding="utf-8")

    code = "# TODO: implement this label  # noqa: RPY902\nlabel start:\n    return\n"
    _make_game(tmp_path, code)

    analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
    result = analyzer.run(quiet=True)

    rpy902_diags = [d for d in result.diagnostics if d.code == "RPY902"]
    assert len(rpy902_diags) == 0, (
        "RPY902 fired despite `# noqa: RPY902` on the offending line — "
        "plugin diagnostics must respect inline suppression directives"
    )


# =============================================================================
# 5. A broken plugin rule is isolated — does not crash the analyzer
# =============================================================================


def test_broken_plugin_rule_is_isolated(tmp_path: Path):
    """If a plugin rule's check() raises an exception, the analyzer
    must continue running other rules. The broken rule's diagnostic is
    skipped, but no other diagnostics are lost."""
    from senpy.plugins import Rule, RuleContext, RuleMeta, register_rule

    (tmp_path / "senpy.toml").write_text("[senpy]\nenable_plugins = true\n", encoding="utf-8")

    @register_rule("RPY997")
    class _BrokenRule(Rule):
        meta = RuleMeta(
            code="RPY997",
            docs="A rule that always raises — for isolation testing",
            severity="WARNING",
            tags=["test-isolation"],
        )

        def check(self, ctx: RuleContext):  # type: ignore[override]
            raise RuntimeError("intentional plugin crash for test")

    code = (
        "# TODO: this should still fire RPY902 even with a broken rule\nlabel start:\n    return\n"
    )
    _make_game(tmp_path, code)

    # Also load the todo_comment_plugin so we have another rule that should
    # still run despite _BrokenRule crashing.
    _load_rules_module()

    analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
    result = analyzer.run(quiet=True)

    # _BrokenRule's RPY997 is NOT in the diagnostics — the exception was
    # caught and the rule was skipped.
    rpy997_diags = [d for d in result.diagnostics if d.code == "RPY997"]
    assert len(rpy997_diags) == 0

    # RPY902 (todo_comment_plugin) DID fire — the broken rule did not
    # crash the analyzer.
    rpy902_diags = [d for d in result.diagnostics if d.code == "RPY902"]
    assert len(rpy902_diags) == 1, "Other plugin rules must still run even when one rule raised"
