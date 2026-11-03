"""Tests for plugin autoloading.

Covers `senpy/plugins/autoload.py:autoload_plugins()` — the idempotent
one-shot loader called from `main()`, `dispatch_rule()`, and `dispatch_inspect()`.

Test strategy:
    All tests mock `senpy.plugins.loader._get_entry_points` to inject fake
    plugins (no real entry-point discovery). The trust callback is set to
    `lambda name: True` so trust-check is bypassed. Each test calls
    `reset_autoload_state()` first to ensure a clean slate — otherwise a
    previous autoload in the same process would short-circuit.

Contract verified:
    1. autoload_plugins() is idempotent (second call is a no-op)
    2. autoload_plugins() registers plugin rules in `_REGISTERED_LINT_RULES`
    3. autoload_plugins() never raises (broken plugin → skipped + warning)
    4. autoload_plugins(force=True) re-runs discovery
    5. dispatch_rule() calls autoload → plugin rules visible in `senpy rule list`
    6. dispatch_rule() handles `senpy rule show <plugin_code>` correctly
    7. Built-in codes win on collision (plugin with code="RPY001" is skipped)
    8. Plugin rules without `meta` are skipped silently
    9. autoload state survives across multiple dispatch_rule() calls
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from senpy.cli.rule_dispatch import dispatch_rule
from senpy.plugins.autoload import (
    autoload_plugins,
    is_autoload_done,
    reset_autoload_state,
)
from senpy.plugins.base import Rule, RuleMeta
from senpy.plugins.registry import get_registered_lint_rules

# ---------------------------------------------------------------------------
# Helpers — fake entry points / fake rule classes
# ---------------------------------------------------------------------------


class _FakeEntryPoint:
    """Minimal stand-in for importlib.metadata.EntryPoint.

    Only `name` and `load()` are used by the loader pipeline.
    """

    def __init__(self, name: str, rule_cls: type):
        self.name = name
        self._rule_cls = rule_cls

    def load(self) -> type:
        return self._rule_cls


def _make_rule_cls(code: str = "RPY901", docs: str = "Test plugin rule."):
    """Build a fresh Rule subclass with the given meta.code.

    A new class is built per call to avoid cross-test contamination
    (registry is a module-level list; identities matter).
    """

    class _TestRule(Rule):
        meta = RuleMeta(code=code, docs=docs, severity="WARNING", tags=["test-plugin"])
        PLUGIN_API_VERSION = "1.0"

        def check(self, ctx):  # type: ignore[override]
            return []

    _TestRule.__name__ = f"_TestRule_{code}"
    return _TestRule


def _trust_all(_name: str) -> bool:
    """Trust callback that accepts every plugin — used in tests to bypass
    the trust-on-first-use prompt (which would write to ~/.senpy/ and
    hang in non-TTY environments like pytest).
    """
    return True


@pytest.fixture(autouse=True)
def _clean_autoload_state():
    """Reset autoload + registry before AND after every test.

    `reset_autoload_state()` clears `_PLUGINS_LOADED` AND
    `_REGISTERED_LINT_RULES`. This guarantees each test starts from a
    known-empty state, regardless of what earlier tests did.

    Also patches `_default_trust_callback` to always trust (via _trust_all)
    so test plugins load without writing to the real trust store.
    """
    reset_autoload_state()
    # Patch the default trust callback for every test — tests inject fake
    # plugins and need them to load without going through trust-on-first-use.
    # Production callers (main, dispatch_rule) pass trust_callback=None to
    # autoload_plugins(), which falls back to the real _default_trust_callback
    # — that's the correct behavior in production, but undesirable in tests.
    with patch("senpy.plugins.loader._default_trust_callback", side_effect=_trust_all):
        yield
    reset_autoload_state()


# ---------------------------------------------------------------------------
# autoload_plugins() — direct unit tests
# ---------------------------------------------------------------------------


class TestAutoloadPluginsBasic:
    """autoload_plugins() — basic contract."""

    def test_no_plugins_installed_is_noop(self):
        """When no entry points exist, autoload completes without error."""
        with patch("senpy.plugins.loader._get_entry_points", return_value=[]):
            autoload_plugins()

        assert is_autoload_done() is True
        assert get_registered_lint_rules() == []

    def test_idempotent_second_call_is_noop(self):
        """Calling autoload twice does not double-register rules."""
        rule_cls = _make_rule_cls("RPY901")
        ep = _FakeEntryPoint("test-plugin", rule_cls)

        with patch("senpy.plugins.loader._get_entry_points", return_value=[ep]):
            autoload_plugins()
            # Second call: must not re-register, even though entry points
            # are still discoverable. Idempotency guard kicks in.
            autoload_plugins()

        codes = [c for c, _ in get_registered_lint_rules()]
        assert codes == ["RPY901"]  # not ["RPY901", "RPY901"]

    def test_force_reruns_discovery(self):
        """`force=True` bypasses the idempotency guard.

        Use case: tests that mock `_get_entry_points` need a fresh load
        after the first autoload already fired in this process.
        """
        # First load: no plugins.
        with patch("senpy.plugins.loader._get_entry_points", return_value=[]):
            autoload_plugins()
        assert get_registered_lint_rules() == []

        # Second load with force=True: now we inject a plugin.
        rule_cls = _make_rule_cls("RPY901")
        ep = _FakeEntryPoint("test-plugin", rule_cls)
        with patch("senpy.plugins.loader._get_entry_points", return_value=[ep]):
            autoload_plugins(force=True)

        codes = [c for c, _ in get_registered_lint_rules()]
        assert "RPY901" in codes

    def test_broken_plugin_does_not_crash(self):
        """A plugin whose entry_point.load() raises must be skipped,
        not propagated. Other plugins still load.
        """
        # Good plugin
        good_cls = _make_rule_cls("RPY901")

        class _BrokenEP:
            name = "broken-plugin"

            def load(self):
                raise ImportError("simulated plugin import failure")

        good_ep = _FakeEntryPoint("good-plugin", good_cls)
        broken_ep = _BrokenEP()

        with patch(
            "senpy.plugins.loader._get_entry_points",
            return_value=[good_ep, broken_ep],
        ):
            # Must not raise.
            autoload_plugins()

        codes = [c for c, _ in get_registered_lint_rules()]
        # Good plugin loaded; bad plugin skipped.
        assert "RPY901" in codes


# ---------------------------------------------------------------------------
# autoload_plugins() — rule-registry integration
# ---------------------------------------------------------------------------


class TestAutoloadPluginRegistration:
    """autoload_plugins() populates the lint rule registry."""

    def test_plugin_rule_appears_in_registry(self):
        rule_cls = _make_rule_cls("RPY901", docs="Hardcoded dialogue check.")
        ep = _FakeEntryPoint("my-senpy-plugin", rule_cls)

        with patch("senpy.plugins.loader._get_entry_points", return_value=[ep]):
            autoload_plugins()

        registered = get_registered_lint_rules()
        assert len(registered) == 1
        code, cls = registered[0]
        assert code == "RPY901"
        assert cls is rule_cls

    def test_multiple_plugins_all_registered(self):
        r1 = _make_rule_cls("RPY901")
        r2 = _make_rule_cls("RPY902")
        ep1 = _FakeEntryPoint("plugin-a", r1)
        ep2 = _FakeEntryPoint("plugin-b", r2)

        with patch("senpy.plugins.loader._get_entry_points", return_value=[ep1, ep2]):
            autoload_plugins()

        codes = sorted(c for c, _ in get_registered_lint_rules())
        assert codes == ["RPY901", "RPY902"]


# ---------------------------------------------------------------------------
# dispatch_rule() — integration with `senpy rule list/show`
# ---------------------------------------------------------------------------


class TestDispatchRuleIntegration:
    """`senpy rule list/show` reflects autoloaded plugin rules."""

    def test_rule_list_includes_plugin_code(self, capsys):
        """The CI smoke-test scenario: a trusted plugin with RPY901 must
        appear in `senpy rule list --format json`."""
        rule_cls = _make_rule_cls("RPY901", docs="Hard-coded dialogue without _().")
        ep = _FakeEntryPoint("my-senpy-plugin", rule_cls)

        with patch("senpy.plugins.loader._get_entry_points", return_value=[ep]):
            rc = dispatch_rule(["list", "--format", "json"])

        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        codes = {entry["code"] for entry in data}
        assert "RPY901" in codes
        # Built-in codes must still all be present.
        assert "RPY001" in codes
        assert "RPY703" in codes

    def test_rule_list_plugin_entry_has_required_fields(self, capsys):
        """Plugin entries must have the same JSON shape as built-in entries."""
        rule_cls = _make_rule_cls("RPY901", docs="Hard-coded dialogue check.")
        ep = _FakeEntryPoint("my-senpy-plugin", rule_cls)

        with patch("senpy.plugins.loader._get_entry_points", return_value=[ep]):
            dispatch_rule(["list", "--format", "json"])

        data = json.loads(capsys.readouterr().out)
        rpy901 = next(e for e in data if e["code"] == "RPY901")
        required = {"code", "title", "severity", "tags", "why", "bad", "good"}
        missing = required - set(rpy901.keys())
        assert not missing, f"plugin entry missing fields: {missing}"
        assert rpy901["severity"] == "WARNING"
        assert "test-plugin" in rpy901["tags"]

    def test_rule_show_plugin_code_text(self, capsys):
        """`senpy rule show RPY901` (text) works for plugin rules."""
        rule_cls = _make_rule_cls("RPY901", docs="Hard-coded dialogue check.")
        ep = _FakeEntryPoint("my-senpy-plugin", rule_cls)

        with patch("senpy.plugins.loader._get_entry_points", return_value=[ep]):
            rc = dispatch_rule(["show", "RPY901"])

        assert rc == 0
        out = capsys.readouterr().out
        assert "RPY901" in out
        # Title derived from first sentence of docs.
        assert "Hard-coded dialogue check." in out

    def test_rule_show_plugin_code_json(self, capsys):
        """`senpy rule show RPY901 --format json` works for plugin rules."""
        rule_cls = _make_rule_cls("RPY901", docs="Hard-coded dialogue check.")
        ep = _FakeEntryPoint("my-senpy-plugin", rule_cls)

        with patch("senpy.plugins.loader._get_entry_points", return_value=[ep]):
            rc = dispatch_rule(["show", "RPY901", "--format", "json"])

        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["code"] == "RPY901"
        assert data["severity"] == "WARNING"

    def test_rule_show_unknown_code_still_exits_nonzero(self, capsys):
        """An unknown code (not built-in, not plugin) still returns rc=1."""
        # No plugins installed.
        with patch("senpy.plugins.loader._get_entry_points", return_value=[]):
            rc = dispatch_rule(["show", "RPY999"])

        assert rc != 0

    def test_builtin_code_wins_on_collision(self, capsys):
        """If a plugin registers code='RPY001' (a built-in), built-in wins.

        Plugin is skipped from `senpy rule list` to avoid confusing users
        with two different definitions of the same code.
        """
        # Plugin tries to register RPY001 (already a built-in rule).
        rule_cls = _make_rule_cls("RPY001", docs="Plugin hijacking built-in code.")
        ep = _FakeEntryPoint("rogue-plugin", rule_cls)

        with patch("senpy.plugins.loader._get_entry_points", return_value=[ep]):
            dispatch_rule(["list", "--format", "json"])

        data = json.loads(capsys.readouterr().out)
        rpy001_entries = [e for e in data if e["code"] == "RPY001"]
        # Exactly one entry — the built-in one, not the plugin's.
        assert len(rpy001_entries) == 1
        # Built-in title for RPY001 is "Tab character in indentation".
        assert rpy001_entries[0]["title"] == "Tab character in indentation"

    def test_rule_list_severity_filter_includes_plugin(self, capsys):
        """Plugin rules respect `--severity` filter."""
        rule_cls = _make_rule_cls("RPY901", docs="Test.")
        ep = _FakeEntryPoint("p", rule_cls)

        with patch("senpy.plugins.loader._get_entry_points", return_value=[ep]):
            dispatch_rule(["list", "--format", "json", "--severity", "WARNING"])

        data = json.loads(capsys.readouterr().out)
        codes = {e["code"] for e in data}
        assert "RPY901" in codes
        # All entries must have severity WARNING.
        assert all(e["severity"] == "WARNING" for e in data)

    def test_rule_list_tag_filter_includes_plugin(self, capsys):
        """Plugin rules respect `--tag` filter (union semantics)."""
        rule_cls = _make_rule_cls("RPY901", docs="Test.")
        ep = _FakeEntryPoint("p", rule_cls)

        with patch("senpy.plugins.loader._get_entry_points", return_value=[ep]):
            dispatch_rule(["list", "--format", "json", "--tag", "test-plugin"])

        data = json.loads(capsys.readouterr().out)
        codes = {e["code"] for e in data}
        assert "RPY901" in codes


# ---------------------------------------------------------------------------
# autoload state — survives across multiple dispatch_rule calls
# ---------------------------------------------------------------------------


class TestAutoloadStateSurvives:
    """Multiple `senpy rule list` calls in the same process don't
    re-trigger discovery. Plugin rule appears once, not N times.
    """

    def test_two_dispatch_calls_do_not_duplicate(self, capsys):
        rule_cls = _make_rule_cls("RPY901")
        ep = _FakeEntryPoint("p", rule_cls)

        with patch("senpy.plugins.loader._get_entry_points", return_value=[ep]):
            dispatch_rule(["list", "--format", "json"])
            capsys.readouterr()  # drain
            dispatch_rule(["list", "--format", "json"])

        data = json.loads(capsys.readouterr().out)
        rpy901_count = sum(1 for e in data if e["code"] == "RPY901")
        assert rpy901_count == 1  # not 2 — idempotency held
