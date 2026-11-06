"""TDD tests for plugin trust-on-first-use (TOFU) before load.

``senpy/plugins/loader.py:load_plugin()`` used to call
``entry_point.load()`` (which imports the plugin's Python module and
executes **all top-level code** — ``__init__.py``, ``rules.py``, class
body, ``@register_rule`` decorators) BEFORE calling ``trust_callback``.
The trust check only decided whether the rule class entered
``_REGISTERED_LINT_RULES``, not whether the plugin module was imported.

This meant a malicious plugin ``pip install senpy-evil-helper`` would
execute its ``__init__.py`` on every Senpy run (including CI/LSP) —
trust-check was advisory, not enforced. The ``@register_rule``
import-time side effect also mutated ``_REGISTERED_LINT_RULES`` even
when trust was declined.

After the fix: ``trust_callback(plugin_name)`` runs BEFORE
``entry_point.load()``. If trust is declined, the plugin module is
never imported — no top-level code runs, no registry mutation, no
marker files, no network calls. Trust is now a real gate, not a
cosmetic filter.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from senpy.plugins.autoload import autoload_plugins, reset_autoload_state
from senpy.plugins.loader import load_all_plugins, load_plugin
from senpy.plugins.registry import get_registered_lint_rules

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _SideEffectEntryPoint:
    """Fake entry point whose ``load()`` has an observable side effect.

    The side effect (creating a marker file) models what a malicious
    plugin would do in its top-level code: write to disk, mutate global
    state, make network calls. If ``load()`` is called at all, the side
    effect happens — so the test can assert on the marker file's
    existence to prove whether the plugin module was imported.
    """

    def __init__(self, name: str, marker_path: Path):
        self.name = name
        self.group = "senpy.plugins"
        self.value = "test_module:TestRule"
        self._marker_path = marker_path
        self.load_call_count = 0

    def load(self):
        self.load_call_count += 1
        # Side effect: create the marker file. This is the "plugin ran"
        # signal — if this file exists after the test, load() was called.
        self._marker_path.parent.mkdir(parents=True, exist_ok=True)
        self._marker_path.write_text("plugin ran", encoding="utf-8")

        from senpy.plugins.base import Rule, RuleMeta

        class TestRule(Rule):
            meta = RuleMeta(code="RPY901", docs="test", severity="WARNING")
            PLUGIN_API_VERSION = "1.0"

            def check(self, ctx):  # type: ignore[override]
                return []

        return TestRule


def _trust_decline(_name: str) -> bool:
    """Trust callback that declines every plugin."""
    return False


def _trust_approve(_name: str) -> bool:
    """Trust callback that approves every plugin."""
    return True


@pytest.fixture(autouse=True)
def _clean_autoload_state():
    """Reset autoload + registry before AND after every test."""
    reset_autoload_state()
    with patch("senpy.plugins.loader._default_trust_callback", side_effect=_trust_approve):
        yield
    reset_autoload_state()


# ---------------------------------------------------------------------------
# load_plugin() — trust BEFORE load
# ---------------------------------------------------------------------------


class TestLoadPluginTrustBeforeLoad:
    """``load_plugin()`` must call ``trust_callback`` BEFORE
    ``entry_point.load()`` — otherwise the plugin's top-level code
    runs even when trust is declined.
    """

    def test_declined_trust_does_not_call_load(self, tmp_path: Path):
        """When trust is declined, ``entry_point.load()`` must NOT be called.

        Before the fix: ``load()`` was called first, then trust was
        checked — so a malicious plugin's top-level code ran even
        when the user declined trust.
        """
        marker = tmp_path / "plugin_ran.marker"
        ep = _SideEffectEntryPoint("untrusted-plugin", marker)

        result = load_plugin(ep, trust_callback=_trust_decline)

        assert result is None, "load_plugin should return None when trust is declined"
        assert ep.load_call_count == 0, (
            f"entry_point.load() was called {ep.load_call_count} time(s) even "
            "though trust was declined — the plugin's top-level code ran. "
            "trust_callback must run BEFORE load()."
        )
        assert not marker.exists(), (
            "Plugin side effect (marker file) was created even though trust "
            "was declined — the plugin module was imported. This is the TOFU "
            "bypass: malicious top-level code (network calls, file writes, "
            "registry mutation) would have executed."
        )

    def test_approved_trust_does_call_load(self, tmp_path: Path):
        """When trust is approved, ``entry_point.load()`` IS called.

        Regression guard: the fix must NOT break the legitimate use
        case — trusted plugins must still load and run.
        """
        marker = tmp_path / "plugin_ran.marker"
        ep = _SideEffectEntryPoint("trusted-plugin", marker)

        result = load_plugin(ep, trust_callback=_trust_approve)

        assert (
            result is not None
        ), "load_plugin should return a _LoadedEntryPoint when trust is approved"
        assert ep.load_call_count == 1, (
            f"entry_point.load() was called {ep.load_call_count} time(s), expected 1. "
            "Trusted plugins must be loaded exactly once."
        )
        assert marker.exists(), (
            "Plugin side effect (marker file) was NOT created even though trust "
            "was approved and load() should have run. The fix is too strict — "
            "it prevents trusted plugins from loading."
        )

    def test_declined_trust_does_not_mutate_registry(self, tmp_path: Path):
        """When trust is declined, ``_REGISTERED_LINT_RULES`` must NOT be mutated.

        Before the fix: ``@register_rule`` at module level (the documented
        plugin convention) appended to ``_REGISTERED_LINT_RULES`` during
        ``load()``, even when trust was later declined. The registry was
        left polluted with the untrusted plugin's rule class.
        """
        marker = tmp_path / "plugin_ran.marker"
        ep = _SideEffectEntryPoint("untrusted-plugin", marker)

        # Use the real @register_rule side effect by importing a module
        # that uses it. For this test we patch the registry to track
        # mutations via the mock entry point's load().
        registry_before = list(get_registered_lint_rules())

        result = load_plugin(ep, trust_callback=_trust_decline)

        registry_after = list(get_registered_lint_rules())
        assert result is None
        assert registry_after == registry_before, (
            "_REGISTERED_LINT_RULES was mutated even though trust was declined. "
            f"Before: {len(registry_before)} rules, after: {len(registry_after)}. "
            "The @register_rule import-time side effect must not run when "
            "trust is declined — load() must not be called."
        )

    def test_default_callback_used_when_none_passed(self, tmp_path: Path):
        """When trust_callback=None, the default callback is used.

        In non-TTY (CI/LSP) environments the default callback declines
        untrusted plugins without prompting. This test verifies the
        default callback is still consulted (not bypassed) after the
        trust-before-load refactor.
        """
        marker = tmp_path / "plugin_ran.marker"
        ep = _SideEffectEntryPoint("untrusted-plugin", marker)

        # Patch the default callback to decline (simulates CI/LSP non-TTY)
        with patch("senpy.plugins.loader._default_trust_callback", side_effect=_trust_decline):
            result = load_plugin(ep)  # trust_callback=None → uses default

        assert result is None, (
            "load_plugin with trust_callback=None must use the default callback, "
            "which declines untrusted plugins in non-TTY environments."
        )
        assert ep.load_call_count == 0, (
            "Default trust callback declined, but load() was still called. "
            "The default callback path must also respect trust-before-load."
        )


# ---------------------------------------------------------------------------
# load_all_plugins() — trust BEFORE load at the batch level
# ---------------------------------------------------------------------------


class TestLoadAllPluginsTrustBeforeLoad:
    """``load_all_plugins()`` must respect trust-before-load for every
    plugin in the batch — a single untrusted plugin must not run its
    top-level code, even if other plugins in the batch are trusted.
    """

    def test_untrusted_plugin_in_batch_does_not_run(self, tmp_path: Path):
        """A batch with one untrusted + one trusted plugin: only the
        trusted one's ``load()`` is called.
        """
        untrusted_marker = tmp_path / "untrusted_ran.marker"
        trusted_marker = tmp_path / "trusted_ran.marker"

        untrusted_ep = _SideEffectEntryPoint("untrusted-plugin", untrusted_marker)
        trusted_ep = _SideEffectEntryPoint("trusted-plugin", trusted_marker)

        def selective_trust(name: str) -> bool:
            return name == "trusted-plugin"

        with patch(
            "senpy.plugins.loader._get_entry_points", return_value=[untrusted_ep, trusted_ep]
        ):
            loaded = load_all_plugins(trust_callback=selective_trust)

        # Only the trusted plugin should be loaded.
        assert len(loaded) == 1, (
            f"Expected 1 loaded plugin (trusted), got {len(loaded)}. "
            "Untrusted plugins must be skipped entirely."
        )
        assert loaded[0].name == "trusted-plugin"

        # The untrusted plugin's load() must NOT have been called.
        assert untrusted_ep.load_call_count == 0, (
            "Untrusted plugin's load() was called in the batch — its top-level "
            "code ran even though trust was declined."
        )
        assert not untrusted_marker.exists(), (
            "Untrusted plugin's side effect (marker file) was created — "
            "load() was called despite trust decline."
        )
        # The trusted plugin's load() MUST have been called.
        assert trusted_ep.load_call_count == 1
        assert trusted_marker.exists()


# ---------------------------------------------------------------------------
# autoload_plugins() — end-to-end trust-before-load
# ---------------------------------------------------------------------------


class TestAutoloadPluginsTrustBeforeLoad:
    """End-to-end: ``autoload_plugins()`` (called from CLI entry points)
    must not run untrusted plugin top-level code.
    """

    def test_untrusted_plugin_does_not_run_via_autoload(self, tmp_path: Path):
        """autoload_plugins() with an untrusted plugin: load() not called."""
        marker = tmp_path / "plugin_ran.marker"
        ep = _SideEffectEntryPoint("untrusted-plugin", marker)

        with patch("senpy.plugins.loader._get_entry_points", return_value=[ep]):
            with patch("senpy.plugins.loader._default_trust_callback", side_effect=_trust_decline):
                autoload_plugins()

        assert not marker.exists(), (
            "autoload_plugins() ran an untrusted plugin's top-level code "
            "(marker file was created). autoload must respect trust-before-load "
            "so that CI/LSP runs do not execute untrusted plugin code."
        )

    def test_trusted_plugin_runs_via_autoload(self, tmp_path: Path):
        """autoload_plugins() with a trusted plugin: load() IS called.

        Regression guard: the fix must not break the legitimate autoload
        path for trusted plugins.
        """
        marker = tmp_path / "plugin_ran.marker"
        ep = _SideEffectEntryPoint("trusted-plugin", marker)

        with patch("senpy.plugins.loader._get_entry_points", return_value=[ep]):
            with patch("senpy.plugins.loader._default_trust_callback", side_effect=_trust_approve):
                autoload_plugins()

        assert marker.exists(), (
            "autoload_plugins() did NOT run a trusted plugin's top-level code "
            "(marker file was not created). The fix is too strict — trusted "
            "plugins must still load via autoload."
        )
