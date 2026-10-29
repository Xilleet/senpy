"""Tests for 0.6.0 Под-спринт 2b (Заход 2): Plugin loading + trust-on-first-use.

EXT-1: Plugin loading via [project.entry-points."senpy.plugins"].
       Uses importlib.metadata.entry_points to discover installed plugins.
       Each plugin is a Rule subclass in a separate pip package.

SEC-P2: Trust-on-first-use security model.
        - First time plugin loads: Senpy asks "Trust plugin X? [y/N]"
        - User choice persisted to ~/.senpy/trusted_plugins.json
        - Subsequent loads: trust store check (no prompt)
        - Non-interactive (CI, no TTY): only pre-trusted plugins load

EXT-11: examples/my_senpy_plugin/ — working example plugin (separate test).

Architecture:
    senpy/plugins/
    ├── loader.py        # EXT-1: discover_plugins, load_plugin, load_all_plugins
    └── security.py      # EXTENDED: + trust store (trust_plugin, is_plugin_trusted)

Trust store: ~/.senpy/trusted_plugins.json
    {
        "version": 1,
        "plugins": ["my-senpy-plugin", "another-plugin"],
        "trusted_at": {"my-senpy-plugin": "2026-10-30T12:00:00Z"}
    }
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# =============================================================================
# EXT-1: Plugin discovery via entry_points
# =============================================================================


class TestPluginDiscovery:
    """EXT-1: discover_plugins() returns list of installed senpy plugins.

    Plugins are discovered via Python's importlib.metadata entry_points
    mechanism. Each plugin package declares:

        [project.entry-points."senpy.plugins"]
        my_rule = "my_senpy_plugin.rules:MyRule"

    discover_plugins() returns list of EntryPoint objects (not loaded yet).
    Loading happens in load_plugin() — separation allows trust check first.
    """

    def test_discover_plugins_function_exists(self):
        """discover_plugins() must be importable from senpy.plugins.loader."""
        from senpy.plugins.loader import discover_plugins
        assert callable(discover_plugins)

    def test_discover_plugins_returns_list(self):
        """discover_plugins() returns a list (possibly empty)."""
        from senpy.plugins.loader import discover_plugins
        plugins = discover_plugins()
        assert isinstance(plugins, list)

    def test_discover_plugins_empty_when_no_plugins_installed(self):
        """When no plugins are installed, discover_plugins() returns empty list."""
        from senpy.plugins.loader import discover_plugins
        # Mock entry_points to return empty
        with patch("senpy.plugins.loader._get_entry_points", return_value=[]):
            plugins = discover_plugins()
        assert plugins == []


class TestPluginLoading:
    """EXT-1: load_plugin() loads a single plugin with isolation + api_version check.

    Contract:
        1. Load entry_point value (the Rule subclass)
        2. Verify it's a Rule subclass (skip with warning if not)
        3. Check plugin's api_version (skip with warning if incompatible)
        4. If trust_callback provided, call it; if declined, skip
        5. Return loaded Rule class, or None if skipped/failed

    Isolation: if plugin fails to load (import error, etc.), return None
    and log — do NOT propagate exception to caller.
    """

    def test_load_plugin_function_exists(self):
        """load_plugin() must be importable from senpy.plugins.loader."""
        from senpy.plugins.loader import load_plugin
        assert callable(load_plugin)

    def test_load_plugin_loads_valid_rule(self):
        """load_plugin() returns the Rule subclass for a valid entry point."""
        from senpy.plugins.loader import load_plugin, _LoadedEntryPoint
        from senpy.plugins.base import Rule, RuleMeta

        # Create a mock entry point that loads a valid Rule subclass
        class _MockEntryPoint:
            name = "test-plugin"
            group = "senpy.plugins"
            value = "test_module:TestRule"

            def load(self):
                class TestRule(Rule):
                    meta = RuleMeta(code="RPY999", docs="test", severity="WARNING")
                    PLUGIN_API_VERSION = "1.0"
                    def check(self, ctx):
                        return []
                return TestRule

        # Trust explicitly (otherwise default callback declines in non-TTY test env)
        result = load_plugin(_MockEntryPoint(), trust_callback=lambda name: True)
        assert result is not None
        # Result is _LoadedEntryPoint with name + rule_cls
        assert isinstance(result, _LoadedEntryPoint)
        assert result.name == "test-plugin"
        assert issubclass(result.rule_cls, Rule)

    def test_load_plugin_skips_non_rule_class(self):
        """If entry point loads a non-Rule class, return None (skip with warning)."""
        from senpy.plugins.loader import load_plugin

        class _MockEntryPoint:
            name = "bad-plugin"
            group = "senpy.plugins"
            value = "test_module:NotARule"

            def load(self):
                class NotARule:
                    pass
                return NotARule

        result = load_plugin(_MockEntryPoint())
        assert result is None

    def test_load_plugin_skips_incompatible_api_version(self):
        """If plugin declares api_version 2.0 (incompatible), skip."""
        from senpy.plugins.loader import load_plugin

        class _MockEntryPoint:
            name = "old-plugin"
            group = "senpy.plugins"
            value = "test_module:OldRule"

            def load(self):
                from senpy.plugins.base import Rule, RuleMeta
                class OldRule(Rule):
                    meta = RuleMeta(code="RPY999", docs="old", severity="WARNING")
                    PLUGIN_API_VERSION = "2.0"  # incompatible
                    def check(self, ctx):
                        return []
                return OldRule

        result = load_plugin(_MockEntryPoint())
        assert result is None  # skipped due to version mismatch

    def test_load_plugin_handles_import_error_gracefully(self):
        """If entry_point.load() raises ImportError, return None (isolation)."""
        from senpy.plugins.loader import load_plugin

        class _BrokenEntryPoint:
            name = "broken-plugin"
            group = "senpy.plugins"
            value = "nonexistent_module:SomeClass"

            def load(self):
                raise ImportError("Module not found")

        result = load_plugin(_BrokenEntryPoint())
        assert result is None  # isolated, not propagated

    def test_load_plugin_with_trust_callback_accepted(self):
        """If trust_callback returns True, plugin loads."""
        from senpy.plugins.loader import load_plugin

        class _MockEntryPoint:
            name = "new-plugin"
            value = "test:Rule"

            def load(self):
                from senpy.plugins.base import Rule, RuleMeta
                class TestRule(Rule):
                    meta = RuleMeta(code="RPY999", docs="test", severity="WARNING")
                    PLUGIN_API_VERSION = "1.0"
                    def check(self, ctx):
                        return []
                return TestRule

        # Trust callback accepts
        result = load_plugin(_MockEntryPoint(), trust_callback=lambda name: True)
        assert result is not None

    def test_load_plugin_with_trust_callback_declined(self):
        """If trust_callback returns False, plugin is NOT loaded (None)."""
        from senpy.plugins.loader import load_plugin

        class _MockEntryPoint:
            name = "untrusted-plugin"
            value = "test:Rule"

            def load(self):
                from senpy.plugins.base import Rule, RuleMeta
                class TestRule(Rule):
                    meta = RuleMeta(code="RPY999", docs="test", severity="WARNING")
                    PLUGIN_API_VERSION = "1.0"
                    def check(self, ctx):
                        return []
                return TestRule

        # Trust callback declines
        result = load_plugin(_MockEntryPoint(), trust_callback=lambda name: False)
        assert result is None


class TestLoadAllPlugins:
    """EXT-1: load_all_plugins() discovers + loads all plugins with trust check."""

    def test_load_all_plugins_function_exists(self):
        """load_all_plugins() must be importable from senpy.plugins.loader."""
        from senpy.plugins.loader import load_all_plugins
        assert callable(load_all_plugins)

    def test_load_all_plugins_returns_list_of_loaded(self):
        """load_all_plugins() returns list of _LoadedEntryPoint (successfully loaded)."""
        from senpy.plugins.loader import load_all_plugins

        # Mock: no plugins installed
        with patch("senpy.plugins.loader._get_entry_points", return_value=[]):
            result = load_all_plugins()
        assert isinstance(result, list)
        assert result == []

    def test_load_all_plugins_skips_failed_isolated(self):
        """If one plugin fails to load, others still load (isolation)."""
        from senpy.plugins.loader import load_all_plugins, _LoadedEntryPoint

        class _GoodEntryPoint:
            name = "good-plugin"
            value = "test:Rule"
            def load(self):
                from senpy.plugins.base import Rule, RuleMeta
                class TestRule(Rule):
                    meta = RuleMeta(code="RPY999", docs="test", severity="WARNING")
                    PLUGIN_API_VERSION = "1.0"
                    def check(self, ctx):
                        return []
                return TestRule

        class _BadEntryPoint:
            name = "bad-plugin"
            value = "broken:Rule"
            def load(self):
                raise ImportError("broken")

        # Auto-trust all (we're testing isolation, not trust)
        with patch("senpy.plugins.loader._get_entry_points",
                   return_value=[_GoodEntryPoint(), _BadEntryPoint()]):
            result = load_all_plugins(trust_callback=lambda name: True)

        # Good plugin loaded, bad one skipped
        assert len(result) == 1
        assert result[0].name == "good-plugin"


# =============================================================================
# SEC-P2: Trust store (~/.senpy/trusted_plugins.json)
# =============================================================================


class TestTrustStore:
    """SEC-P2: Trust store for trust-on-first-use security model.

    Trust store location: ~/.senpy/trusted_plugins.json (or SENPY_HOME env var)
    Format:
        {
            "version": 1,
            "plugins": ["my-senpy-plugin", "another-plugin"],
            "trusted_at": {
                "my-senpy-plugin": "2026-10-30T12:00:00Z",
                "another-plugin": "2026-10-30T13:00:00Z"
            }
        }
    """

    def test_get_trust_store_path_function_exists(self):
        """get_trust_store_path() returns path to trust store."""
        from senpy.plugins.security import get_trust_store_path
        path = get_trust_store_path()
        assert isinstance(path, str)
        assert ".senpy" in path or "senpy" in path.lower()
        assert path.endswith("trusted_plugins.json")

    def test_get_trust_store_path_respects_env_var(self, monkeypatch, tmp_path):
        """SENPY_HOME env var overrides default ~/.senpy location."""
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        from senpy.plugins.security import get_trust_store_path
        path = get_trust_store_path()
        assert str(tmp_path) in path
        assert path.endswith("trusted_plugins.json")

    def test_is_plugin_trusted_returns_false_for_unknown(self, monkeypatch, tmp_path):
        """is_plugin_trusted() returns False for plugin not in trust store."""
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        from senpy.plugins.security import is_plugin_trusted
        # Trust store doesn't exist yet
        assert is_plugin_trusted("unknown-plugin") is False

    def test_trust_plugin_adds_to_store(self, monkeypatch, tmp_path):
        """trust_plugin(name) adds plugin to trust store."""
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        from senpy.plugins.security import trust_plugin, is_plugin_trusted
        # Initially not trusted
        assert is_plugin_trusted("my-plugin") is False
        # Trust it
        trust_plugin("my-plugin")
        # Now trusted
        assert is_plugin_trusted("my-plugin") is True

    def test_trust_plugin_persists_to_disk(self, monkeypatch, tmp_path):
        """trust_plugin() writes to disk (survives restart)."""
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        from senpy.plugins.security import trust_plugin, is_plugin_trusted, get_trust_store_path

        trust_plugin("persistent-plugin")

        # Verify file on disk
        store_path = get_trust_store_path()
        assert os.path.exists(store_path)
        with open(store_path) as f:
            data = json.load(f)
        assert "persistent-plugin" in data["plugins"]

        # Simulate restart: is_plugin_trusted reads from disk
        # (clear any in-memory cache)
        assert is_plugin_trusted("persistent-plugin") is True

    def test_untrust_plugin_removes_from_store(self, monkeypatch, tmp_path):
        """untrust_plugin(name) removes plugin from trust store."""
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        from senpy.plugins.security import trust_plugin, untrust_plugin, is_plugin_trusted

        trust_plugin("temp-plugin")
        assert is_plugin_trusted("temp-plugin") is True

        untrust_plugin("temp-plugin")
        assert is_plugin_trusted("temp-plugin") is False

    def test_trust_store_handles_corrupt_json(self, monkeypatch, tmp_path):
        """If trust store JSON is corrupt, treat as empty (not crash)."""
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        from senpy.plugins.security import is_plugin_trusted, get_trust_store_path

        # Write corrupt JSON
        store_path = get_trust_store_path()
        os.makedirs(os.path.dirname(store_path), exist_ok=True)
        with open(store_path, "w") as f:
            f.write("{ this is not valid json")

        # Should not raise, should return False
        assert is_plugin_trusted("any-plugin") is False


# =============================================================================
# SEC-P2: Default trust callback (interactive prompt)
# =============================================================================


class TestDefaultTrustCallback:
    """SEC-P2: Default trust callback behavior.

    When no explicit trust_callback is provided to load_all_plugins():
    - In TTY (interactive): prompt user "Trust plugin X? [y/N]"
    - In non-TTY (CI, piped): decline all untrusted plugins (fail-safe)
    """

    def test_default_trust_callback_declines_in_non_tty(self, monkeypatch):
        """In non-interactive (no TTY), default callback declines all."""
        from senpy.plugins.loader import _default_trust_callback
        # Simulate non-TTY
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        result = _default_trust_callback("any-plugin")
        assert result is False

    def test_default_trust_callback_accepts_if_pre_trusted(self, monkeypatch, tmp_path):
        """If plugin is in trust store, default callback accepts without prompt."""
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        from senpy.plugins.loader import _default_trust_callback
        from senpy.plugins.security import trust_plugin

        trust_plugin("pre-trusted")
        result = _default_trust_callback("pre-trusted")
        assert result is True


# =============================================================================
# Integration: load_all_plugins with trust store
# =============================================================================


class TestLoadAllPluginsWithTrust:
    """End-to-end: load_all_plugins() with real trust store behavior."""

    def test_trusted_plugin_loads_without_prompt(self, monkeypatch, tmp_path):
        """Pre-trusted plugin loads silently (no prompt)."""
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        from senpy.plugins.loader import load_all_plugins
        from senpy.plugins.security import trust_plugin

        # Pre-trust the plugin
        trust_plugin("trusted-test-plugin")

        class _MockEntryPoint:
            name = "trusted-test-plugin"
            value = "test:Rule"
            def load(self):
                from senpy.plugins.base import Rule, RuleMeta
                class TestRule(Rule):
                    meta = RuleMeta(code="RPY999", docs="test", severity="WARNING")
                    PLUGIN_API_VERSION = "1.0"
                    def check(self, ctx):
                        return []
                return TestRule

        # Non-TTY mode — but plugin is pre-trusted, so should load
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        with patch("senpy.plugins.loader._get_entry_points",
                   return_value=[_MockEntryPoint()]):
            result = load_all_plugins()  # default trust callback

        assert len(result) == 1
        assert result[0].name == "trusted-test-plugin"

    def test_untrusted_plugin_skipped_in_non_tty(self, monkeypatch, tmp_path):
        """Untrusted plugin is skipped in non-TTY (CI) mode — fail-safe."""
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        from senpy.plugins.loader import load_all_plugins

        class _MockEntryPoint:
            name = "untrusted-test-plugin"
            value = "test:Rule"
            def load(self):
                from senpy.plugins.base import Rule, RuleMeta
                class TestRule(Rule):
                    meta = RuleMeta(code="RPY999", docs="test", severity="WARNING")
                    PLUGIN_API_VERSION = "1.0"
                    def check(self, ctx):
                        return []
                return TestRule

        # Non-TTY mode — untrusted plugin should be skipped
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        with patch("senpy.plugins.loader._get_entry_points",
                   return_value=[_MockEntryPoint()]):
            result = load_all_plugins()  # default trust callback

        assert result == []  # untrusted plugin skipped


# =============================================================================
# EXT-1: register_loaded_plugins() — integration with rule registry
# =============================================================================


class TestRegisterLoadedPlugins:
    """After load_all_plugins(), loaded rules should be registered via @register_rule
    equivalent mechanism, so SenpyAnalyzer can find them.
    """

    def test_register_loaded_plugins_function_exists(self):
        """register_loaded_plugins() registers all loaded plugin rules in the
        lint rule registry (so get_registered_lint_rules() returns them)."""
        from senpy.plugins.loader import register_loaded_plugins
        assert callable(register_loaded_plugins)

    def test_register_loaded_plugins_adds_to_registry(self, monkeypatch, tmp_path):
        """After register_loaded_plugins(), plugin rules appear in
        get_registered_lint_rules()."""
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))
        from senpy.plugins.loader import register_loaded_plugins, load_all_plugins
        from senpy.plugins.registry import get_registered_lint_rules, clear_registered_lint_rules
        from senpy.plugins.security import trust_plugin

        # Clear registry first (test isolation)
        clear_registered_lint_rules()

        # Pre-trust and set up mock plugin
        trust_plugin("registry-test-plugin")

        class _MockEntryPoint:
            name = "registry-test-plugin"
            value = "test:Rule"
            def load(self):
                from senpy.plugins.base import Rule, RuleMeta
                class TestRule(Rule):
                    meta = RuleMeta(code="RPY999", docs="test", severity="WARNING")
                    PLUGIN_API_VERSION = "1.0"
                    def check(self, ctx):
                        return []
                return TestRule

        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        with patch("senpy.plugins.loader._get_entry_points",
                   return_value=[_MockEntryPoint()]):
            loaded = load_all_plugins()
            register_loaded_plugins(loaded)

        # Verify plugin rule is in registry
        codes = [code for code, _ in get_registered_lint_rules()]
        assert "RPY999" in codes

        # Cleanup
        clear_registered_lint_rules()


# =============================================================================
# EXT-11: Example plugin (examples/my_senpy_plugin/) works correctly
# =============================================================================



# =============================================================================
# EXT-11: Example plugin (examples/my_senpy_plugin/) works correctly
# =============================================================================


def _get_examples_path() -> str:
    """Returns path to examples/my_senpy_plugin/ (relative to this test file)."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "examples", "my_senpy_plugin"
    )


def _examples_plugin_exists() -> bool:
    """True if examples/my_senpy_plugin/ directory exists (with rules.py)."""
    path = _get_examples_path()
    return (
        os.path.isdir(path)
        and os.path.isdir(os.path.join(path, "my_senpy_plugin"))
        and os.path.isfile(os.path.join(path, "my_senpy_plugin", "rules.py"))
    )


# Skip all tests in this class if example plugin not installed.
# Reason: example plugin lives in examples/, which is optional.
# CI without examples/ should still pass — example plugin is for documentation.
_skip_if_no_examples = pytest.mark.skipif(
    not _examples_plugin_exists(),
    reason="examples/my_senpy_plugin/ not found (optional — copy from senpy_0_6_0_subprint_2b/examples/)"
)


@_skip_if_no_examples
class TestExamplePlugin:
    """EXT-11: examples/my_senpy_plugin/ — working example plugin.

    Verifies that the example plugin:
    - Can be imported
    - Has correct PLUGIN_API_VERSION (compatible with Senpy)
    - Defines a Rule subclass with valid RuleMeta
    - The Rule.check() returns expected Diagnostics

    SKIPPED if examples/my_senpy_plugin/ is not installed (optional — copy
    from senpy_0_6_0_subprint_2b/examples/ to your project's examples/).
    """

    def test_example_plugin_imports(self):
        """Example plugin module can be imported (when path is set)."""
        import sys
        examples_path = _get_examples_path()
        sys.path.insert(0, examples_path)
        try:
            from my_senpy_plugin.rules import HardcodedDialogueRule
            assert HardcodedDialogueRule is not None
        finally:
            sys.path.remove(examples_path)

    def test_example_plugin_api_version_compatible(self):
        """Example plugin's PLUGIN_API_VERSION is compatible with Senpy."""
        import sys
        examples_path = _get_examples_path()
        sys.path.insert(0, examples_path)
        try:
            from my_senpy_plugin.rules import PLUGIN_API_VERSION
            from senpy.plugins.security import check_api_version
            assert check_api_version(PLUGIN_API_VERSION) is True
        finally:
            sys.path.remove(examples_path)

    def test_example_plugin_rule_works(self):
        """Example plugin's HardcodedDialogueRule returns correct diagnostics."""
        import sys
        examples_path = _get_examples_path()
        sys.path.insert(0, examples_path)
        try:
            from my_senpy_plugin.rules import HardcodedDialogueRule
            from senpy.plugins.base import RuleContext
            from senpy.api import Diagnostic

            rule = HardcodedDialogueRule()
            ctx = RuleContext(
                file_path="test.rpy",
                lines=[
                    'label start:\n',
                    '    "Hello, world!"\n',           # flagged
                    '    _("Translated")\n',            # OK
                    '    \'Single quoted\'\n',          # flagged
                    '    $ x = 1\n',                    # not dialogue
                    '    return\n',
                ],
                symbols={},
            )
            diags = rule.check(ctx)

            assert len(diags) == 2
            assert all(isinstance(d, Diagnostic) for d in diags)
            assert all(d.code == "RPY901" for d in diags)
            assert diags[0].line_number == 2  # "Hello, world!"
            assert diags[1].line_number == 4  # 'Single quoted'
            assert diags[0].severity == "WARNING"
        finally:
            sys.path.remove(examples_path)

    def test_example_plugin_meta_valid(self):
        """Example plugin's RuleMeta has valid fields."""
        import sys
        examples_path = _get_examples_path()
        sys.path.insert(0, examples_path)
        try:
            from my_senpy_plugin.rules import HardcodedDialogueRule
            meta = HardcodedDialogueRule.meta
            assert meta is not None
            assert meta.code == "RPY901"
            assert meta.severity == "WARNING"
            assert "translations" in meta.tags
            assert meta.fixable is False
        finally:
            sys.path.remove(examples_path)
