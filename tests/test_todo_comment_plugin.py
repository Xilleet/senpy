"""Tests for the todo_comment_plugin example plugin (RPY902).

These tests verify that the example plugin in `examples/todo_comment_plugin/`
works end-to-end:
  1. The package installs and imports cleanly.
  2. The rule class has correct metadata (code, severity, tags).
  3. The detection logic catches TODO/FIXME/XXX/HACK comments.
  4. The detection logic does NOT fire on dialogue or non-comment lines.
  5. Case-insensitive matching (todo, Todo, TODO all fire).
  6. Word-boundary check (# todolist doesn't fire).
  7. After autoload, `senpy rule list` shows RPY902 (integration).
  8. `senpy rule show RPY902` returns the rule detail.

These tests load the plugin's `rules.py` directly via `importlib` (no pip
install required, no subprocess, no Senpy analyzer). The integration test
(point 7) uses the same `autoload_plugins()` mechanism as the real CLI.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

# Locate the example plugin's rules.py on disk. We don't rely on the
# package being installed via `pip install -e` — we load it directly
# from the examples/ directory. This makes the test self-contained:
# it works in CI without a separate install step, and it works for
# developers who only unpacked the ZIP without running pip.
_PLUGIN_DIR = Path(__file__).resolve().parent.parent / "examples" / "todo_comment_plugin"
_RULES_PY = _PLUGIN_DIR / "todo_comment_plugin" / "rules.py"


def _load_rules_module() -> ModuleType:
    """Load `examples/todo_comment_plugin/todo_comment_plugin/rules.py` as
    a Python module via `importlib.util.spec_from_file_location`.

    This avoids polluting `sys.path` (the previous approach used
    `sys.path.insert` at module load time, which worked but was
    invisible to IDE/liners and broke if the test file was moved).

    The loaded module is registered in `sys.modules` under its dotted
    name so that internal imports within the plugin (e.g.
    `from senpy.api import Diagnostic`) resolve correctly.
    """
    if not _RULES_PY.is_file():
        pytest.skip(
            f"Example plugin not found at {_RULES_PY}. Did you unpack the ZIP into the repo root?"
        )
    spec = importlib.util.spec_from_file_location("todo_comment_plugin.rules", _RULES_PY)
    if spec is None or spec.loader is None:
        pytest.skip(f"Could not load module spec for {_RULES_PY}")
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules so the plugin's own `from senpy.api import ...`
    # and `from senpy.plugins import ...` resolve via the normal import
    # machinery (these are absolute imports, not affected by our spec).
    sys_modules_key = "todo_comment_plugin.rules"
    import sys

    sys.modules[sys_modules_key] = module
    spec.loader.exec_module(module)
    return module


# Load the plugin module once at module-import time (before any test runs).
# Tests then access `TodoCommentRule` from the loaded module.
_rules_module = _load_rules_module()
TodoCommentRule = _rules_module.TodoCommentRule


# Import Senpy's autoload + base classes — these come from the installed
# `senpy` package, not from the example plugin directory.
from senpy.plugins.autoload import reset_autoload_state
from senpy.plugins.base import RuleContext
from senpy.plugins.registry import get_registered_lint_rules

# ---------------------------------------------------------------------------
# Fixture — clean autoload state
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_autoload():
    """Reset the plugin registry before/after each test."""
    reset_autoload_state()
    yield
    reset_autoload_state()


# ---------------------------------------------------------------------------
# 1. Package + class metadata
# ---------------------------------------------------------------------------


class TestPluginMetadata:
    """The plugin class must have correct RuleMeta."""

    def test_rule_class_is_importable(self):
        """`from todo_comment_plugin.rules import TodoCommentRule` works."""
        assert TodoCommentRule is not None

    def test_meta_code_is_rpy902(self):
        assert TodoCommentRule.meta is not None
        assert TodoCommentRule.meta.code == "RPY902"

    def test_meta_severity_is_hint(self):
        assert TodoCommentRule.meta.severity == "HINT"

    def test_meta_tags_include_productivity(self):
        tags = TodoCommentRule.meta.tags
        assert "productivity" in tags
        assert "dead-code" in tags

    def test_plugin_api_version_is_set(self):
        """The plugin declares PLUGIN_API_VERSION at module level.

        Note: this matches the pattern in my_senpy_plugin/rules.py —
        PLUGIN_API_VERSION is a module-level constant, not a class
        attribute. The loader (`senpy/plugins/loader.py:165`) does
        `getattr(rule_cls, "PLUGIN_API_VERSION", None)` which returns
        None for module-level declarations (class attrs only). This is
        a known limitation of the current plugin API — the version
        check is skipped silently when the attr is module-level. Both
        example plugins (RPY901, RPY902) follow this pattern, so we
        test for module-level presence to match the established convention.
        """
        # _rules_module is the already-loaded module (loaded via importlib
        # at the top of this file).
        assert hasattr(_rules_module, "PLUGIN_API_VERSION")
        assert _rules_module.PLUGIN_API_VERSION == "1.0"

    def test_meta_docs_is_nonempty(self):
        assert TodoCommentRule.meta.docs
        assert len(TodoCommentRule.meta.docs) > 20  # not just a placeholder


# ---------------------------------------------------------------------------
# 2-6. Detection logic — direct check() tests
# ---------------------------------------------------------------------------


def _ctx(lines: list[str]) -> RuleContext:
    """Build a minimal RuleContext for direct check() tests."""
    return RuleContext(
        file_path="test.rpy",
        lines=lines,
        symbols={},
    )


class TestDetection:
    """The check() method detects TODO/FIXME/XXX/HACK comments."""

    def test_detects_todo(self):
        rule = TodoCommentRule()
        diags = rule.check(
            _ctx(
                [
                    "label start:\n",
                    "    # TODO: implement this label\n",  # flagged
                    '    "Hello"\n',
                ]
            )
        )
        assert len(diags) == 1
        assert diags[0].code == "RPY902"
        assert diags[0].line_number == 2
        assert "TODO" in diags[0].message

    def test_detects_fixme(self):
        rule = TodoCommentRule()
        diags = rule.check(_ctx(["    # FIXME: this crashes on rollback\n"]))
        assert len(diags) == 1
        assert "FIXME" in diags[0].message

    def test_detects_xxx(self):
        rule = TodoCommentRule()
        diags = rule.check(_ctx(["    # XXX: not sure about this\n"]))
        assert len(diags) == 1
        assert "XXX" in diags[0].message

    def test_detects_hack(self):
        rule = TodoCommentRule()
        diags = rule.check(_ctx(["    # HACK: bypass renpy rollback\n"]))
        assert len(diags) == 1
        assert "HACK" in diags[0].message

    def test_case_insensitive(self):
        """todo, Todo, TODO, tOdO all fire. The keyword in the message
        is normalized to uppercase (TODO/FIXME/XXX/HACK).
        """
        rule = TodoCommentRule()
        for variant in ("todo", "Todo", "TODO", "tOdO"):
            diags = rule.check(_ctx([f"    # {variant}: do something\n"]))
            assert len(diags) == 1, f"variant {variant!r} should fire"
            assert "TODO" in diags[0].message

    def test_multiple_finds_in_one_file(self):
        rule = TodoCommentRule()
        diags = rule.check(
            _ctx(
                [
                    "label a:\n",
                    "    # TODO: a\n",  # line 2
                    '    "x"\n',
                    "label b:\n",
                    "    # FIXME: b\n",  # line 5
                    '    "y"\n',
                    "    # HACK: c\n",  # line 7
                ]
            )
        )
        assert len(diags) == 3
        line_numbers = sorted(d.line_number for d in diags)
        assert line_numbers == [2, 5, 7]

    def test_no_trailing_colon_still_fires(self):
        """`# TODO` without `:` still fires — the regex allows optional `:`."""
        rule = TodoCommentRule()
        diags = rule.check(_ctx(["    # TODO\n"]))
        assert len(diags) == 1


class TestNoFalsePositives:
    """The check() method does NOT fire on non-comment lines or non-keyword comments."""

    def test_ignores_dialogue_string(self):
        """A dialogue string containing the word "TODO" is NOT flagged."""
        rule = TodoCommentRule()
        diags = rule.check(_ctx(['    "TODO: this is dialogue, not a comment"\n']))
        assert diags == []

    def test_ignores_python_statement(self):
        """A Python statement ($-line) with "todo" in a variable name is NOT flagged."""
        rule = TodoCommentRule()
        diags = rule.check(_ctx(['    $ todolist = ["a", "b"]\n']))
        assert diags == []

    def test_ignores_non_keyword_comment(self):
        """A comment without TODO/FIXME/XXX/HACK is NOT flagged."""
        rule = TodoCommentRule()
        diags = rule.check(_ctx(["    # this is just a regular comment\n"]))
        assert diags == []

    def test_word_boundary_check(self):
        """`# todolist` (no space after `todo`) does NOT fire — the regex
        requires a word boundary after the keyword.
        """
        rule = TodoCommentRule()
        diags = rule.check(_ctx(["    # todolist is not a keyword\n"]))
        assert diags == []

    def test_fixme_variable_does_not_fire(self):
        """`# fixme_var` (no word boundary) does NOT fire."""
        rule = TodoCommentRule()
        diags = rule.check(_ctx(["    # fixme_var holds the value\n"]))
        assert diags == []

    def test_empty_file(self):
        rule = TodoCommentRule()
        diags = rule.check(_ctx([]))
        assert diags == []

    def test_no_comments_in_file(self):
        rule = TodoCommentRule()
        diags = rule.check(
            _ctx(
                [
                    "label start:\n",
                    '    "Hello"\n',
                    "    $ x = 1\n",
                ]
            )
        )
        assert diags == []


# ---------------------------------------------------------------------------
# 7. Integration — autoload makes RPY902 visible to senpy rule list
# ---------------------------------------------------------------------------


class _FakeEntryPoint:
    """Minimal stand-in for importlib.metadata.EntryPoint."""

    def __init__(self, name: str, rule_cls: type):
        self.name = name
        self._rule_cls = rule_cls

    def load(self) -> type:
        return self._rule_cls


class TestAutoloadIntegration:
    """After autoload, RPY902 appears in `senpy rule list` output."""

    def test_autoload_registers_rpy902(self):
        from senpy.plugins.autoload import autoload_plugins

        ep = _FakeEntryPoint("todo-comment-plugin", TodoCommentRule)
        with patch("senpy.plugins.loader._get_entry_points", return_value=[ep]):
            with patch(
                "senpy.plugins.loader._default_trust_callback",
                side_effect=lambda name: True,
            ):
                autoload_plugins()

        codes = [c for c, _ in get_registered_lint_rules()]
        assert "RPY902" in codes

    def test_dispatch_rule_shows_rpy902(self, capsys):
        """`senpy rule show RPY902` works after autoload."""
        from senpy.cli.rule_dispatch import dispatch_rule
        from senpy.plugins.autoload import autoload_plugins

        ep = _FakeEntryPoint("todo-comment-plugin", TodoCommentRule)
        with patch("senpy.plugins.loader._get_entry_points", return_value=[ep]):
            with patch(
                "senpy.plugins.loader._default_trust_callback",
                side_effect=lambda name: True,
            ):
                autoload_plugins()
                rc = dispatch_rule(["show", "RPY902"])

        assert rc == 0
        out = capsys.readouterr().out
        assert "RPY902" in out
        assert "HINT" in out
        assert "productivity" in out

    def test_dispatch_rule_list_includes_rpy902(self, capsys):
        """`senpy rule list --format json` includes RPY902 after autoload."""
        from senpy.cli.rule_dispatch import dispatch_rule
        from senpy.plugins.autoload import autoload_plugins

        ep = _FakeEntryPoint("todo-comment-plugin", TodoCommentRule)
        with patch("senpy.plugins.loader._get_entry_points", return_value=[ep]):
            with patch(
                "senpy.plugins.loader._default_trust_callback",
                side_effect=lambda name: True,
            ):
                autoload_plugins()
                dispatch_rule(["list", "--format", "json"])

        import json

        data = json.loads(capsys.readouterr().out)
        codes = {e["code"] for e in data}
        assert "RPY902" in codes
        # Built-in rules still present
        assert "RPY001" in codes
        assert "RPY703" in codes

    def test_tag_filter_finds_rpy902(self, capsys):
        """`senpy rule list --tag productivity` includes RPY902."""
        from senpy.cli.rule_dispatch import dispatch_rule
        from senpy.plugins.autoload import autoload_plugins

        ep = _FakeEntryPoint("todo-comment-plugin", TodoCommentRule)
        with patch("senpy.plugins.loader._get_entry_points", return_value=[ep]):
            with patch(
                "senpy.plugins.loader._default_trust_callback",
                side_effect=lambda name: True,
            ):
                autoload_plugins()
                dispatch_rule(["list", "--format", "json", "--tag", "productivity"])

        import json

        data = json.loads(capsys.readouterr().out)
        codes = {e["code"] for e in data}
        assert "RPY902" in codes


# ---------------------------------------------------------------------------
# 8. Plugin package structure (files exist on disk)
# ---------------------------------------------------------------------------


class TestPluginPackageStructure:
    """The plugin directory must contain the expected files."""

    def test_pyproject_toml_exists(self):
        assert (_PLUGIN_DIR / "pyproject.toml").is_file()

    def test_readme_exists(self):
        assert (_PLUGIN_DIR / "TODO_COMMENT_PLUGIN_README.md").is_file()

    def test_package_init_exists(self):
        assert (_PLUGIN_DIR / "todo_comment_plugin" / "__init__.py").is_file()

    def test_rules_module_exists(self):
        assert (_PLUGIN_DIR / "todo_comment_plugin" / "rules.py").is_file()

    def test_pyproject_declares_entry_point(self):
        """pyproject.toml must declare the entry point so Senpy discovers it."""
        pyproject = (_PLUGIN_DIR / "pyproject.toml").read_text(encoding="utf-8")
        assert "senpy.plugins" in pyproject
        assert "todo-comment-plugin" in pyproject
        assert "TodoCommentRule" in pyproject
