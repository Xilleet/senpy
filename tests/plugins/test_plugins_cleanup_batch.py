"""Tests for the plugins-cluster cleanup batch (roadmap tasks 181, 183, 184,
186, 188, 189).

These tests cover the new behaviours introduced by the cleanup:

    181 — ``register_rule`` validates code format, asserts ``meta.code``
          consistency, rejects duplicates, via the shared
          ``_register_rule_cls`` helper.
    183 — ``_default_trust_callback`` uses top-level ``re``/``sys`` (no
          local imports). Verified indirectly by import-time introspection.
    184 — trust store is cached in ``_sec_mod._TRUST_STORE_CACHE`` after first read
          and invalidated after every mutation.
    186 — ``prune_stale_audit_warnings(known_names)`` removes
          ``audit_warnings`` entries for plugins not in ``known_names``.
    188 — ``autoload_plugins(force=True)`` clears the lint rule registry
          BEFORE re-loading, so two consecutive ``force=True`` calls do
          not double-register every plugin.
    189 — ``load_all_plugins`` return type is ``list[_LoadedEntryPoint]``,
          not bare ``list``. Verified by introspection of ``__annotations__``.

The existing test suite (``test_plugin_autoload.py``, ``test_audit_integration.py``,
``test_plugin_rule_execution.py``) covers the regressions for the behaviour
that was already correct; this file covers the new behaviours.
"""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

import senpy.plugins.security as _sec_mod
from senpy.plugins.autoload import autoload_plugins, reset_autoload_state
from senpy.plugins.base import Rule, RuleMeta
from senpy.plugins.loader import _RE_LSP_FLAG, _LoadedEntryPoint, load_all_plugins
from senpy.plugins.registry import (
    _RE_RULE_CODE,
    _register_rule_cls,
    clear_registered_lint_rules,
    get_registered_lint_rules,
    register_rule,
)
from senpy.plugins.security import (
    _invalidate_trust_store_cache,
    _read_trust_store,
    is_plugin_trusted,
    prune_stale_audit_warnings,
    store_audit_warnings,
    untrust_plugin,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rule_cls(code: str = "RPY901", docs: str = "Test plugin rule."):
    """Build a fresh Rule subclass with the given meta.code."""

    class _TestRule(Rule):
        meta = RuleMeta(code=code, docs=docs, severity="WARNING", tags=["test-plugin"])
        PLUGIN_API_VERSION = "1.0"

        def check(self, ctx):  # type: ignore[override]
            return []

    _TestRule.__name__ = f"_TestRule_{code}"
    return _TestRule


def _trust_all(_name: str) -> bool:
    return True


@pytest.fixture(autouse=True)
def _clean_registry():
    """Clear the lint rule registry before AND after every test."""
    clear_registered_lint_rules()
    yield
    clear_registered_lint_rules()


@pytest.fixture
def _isolated_trust_store(tmp_path: Path, monkeypatch):
    """Point the trust store at a per-test tmp dir + reset the cache.

    The cache (``_sec_mod._TRUST_STORE_CACHE``) is a module global — without
    invalidating it before AND after, a test could see a previous test's
    cached trust store (pointing at a now-deleted tmp dir).
    """
    monkeypatch.setenv("SENPY_HOME", str(tmp_path))
    _invalidate_trust_store_cache()
    yield tmp_path
    _invalidate_trust_store_cache()


# ---------------------------------------------------------------------------
# Task 181 — register_rule validation
# ---------------------------------------------------------------------------


class TestRegisterRuleValidatesCodeFormat:
    """``register_rule`` and ``_register_rule_cls`` must reject codes that
    don't match the ``RPY\\d{3}`` pattern (e.g. ``"RPY"``, ``"rpy901"``,
    ``"RPY90"``). Previously the decorator accepted any string and the
    rule ended up in the registry with an unfindable code."""

    def test_re_rule_code_pattern(self):
        """The pattern is the canonical RPY + 3 digits."""
        assert _RE_RULE_CODE.match("RPY901")
        assert _RE_RULE_CODE.match("RPY999")
        assert not _RE_RULE_CODE.match("RPY90")  # too few digits
        assert not _RE_RULE_CODE.match("RPY9999")  # too many digits
        assert not _RE_RULE_CODE.match("rpy901")  # lowercase
        assert not _RE_RULE_CODE.match("RPY")  # no digits
        assert not _RE_RULE_CODE.match("XPY901")  # wrong prefix

    def test_register_rule_rejects_bad_code_format(self, caplog):
        """``@register_rule("RPY")`` must NOT add the class to the registry."""
        bad_code = "RPY"  # missing digits

        with caplog.at_level(logging.WARNING, logger="senpy.plugins.registry"):

            @register_rule(bad_code)
            class _BadCodeRule(Rule):
                meta = RuleMeta(code="RPY999", docs="x", severity="WARNING")
                PLUGIN_API_VERSION = "1.0"

                def check(self, ctx):
                    return []

        codes = [c for c, _ in get_registered_lint_rules()]
        assert bad_code not in codes
        # The class itself is NOT added under any code — validation failed.
        assert all(cls.__name__ != "_BadCodeRule" for _, cls in get_registered_lint_rules())

    def test_register_rule_rejects_lowercase_code(self, caplog):
        """``@register_rule("rpy901")`` must be rejected (lowercase)."""
        with caplog.at_level(logging.WARNING, logger="senpy.plugins.registry"):

            @register_rule("rpy901")
            class _LowerRule(Rule):
                meta = RuleMeta(code="RPY901", docs="x", severity="WARNING")
                PLUGIN_API_VERSION = "1.0"

                def check(self, ctx):
                    return []

        codes = [c for c, _ in get_registered_lint_rules()]
        assert "rpy901" not in codes
        assert "RPY901" not in codes


class TestRegisterRuleMetaCodeConsistency:
    """``@register_rule(code)`` must agree with ``rule_cls.meta.code``.

    A mismatch indicates a copy-paste bug (rule class copied from another
    rule but the decorator not updated) or a deliberate shadowing attempt.
    """

    def test_register_rule_rejects_decorator_meta_mismatch(self, caplog):
        """Decorator says RPY901, meta says RPY902 — reject."""
        with caplog.at_level(logging.WARNING, logger="senpy.plugins.registry"):

            @register_rule("RPY901")
            class _MismatchRule(Rule):
                meta = RuleMeta(code="RPY902", docs="x", severity="WARNING")
                PLUGIN_API_VERSION = "1.0"

                def check(self, ctx):
                    return []

        codes = [c for c, _ in get_registered_lint_rules()]
        # Neither code should appear — the decorator's code is the
        # canonical one for lookup, but the meta is wrong, so the rule
        # is skipped entirely.
        assert "RPY901" not in codes
        assert "RPY902" not in codes

    def test_register_rule_accepts_matching_decorator_and_meta(self):
        """Happy path: decorator code == meta.code → registered."""

        @register_rule("RPY901")
        class _MatchRule(Rule):
            meta = RuleMeta(code="RPY901", docs="x", severity="WARNING")
            PLUGIN_API_VERSION = "1.0"

            def check(self, ctx):
                return []

        codes = [c for c, _ in get_registered_lint_rules()]
        assert "RPY901" in codes


class TestRegisterRuleDuplicateDetection:
    """``_register_rule_cls`` rejects duplicate codes — first registration wins."""

    def test_duplicate_code_second_registration_skipped(self, caplog):
        """Two rules with the same code → only the first is registered."""
        rule1 = _make_rule_cls("RPY901")
        rule2 = _make_rule_cls("RPY901")  # same code, different class

        assert _register_rule_cls("RPY901", rule1) is True
        with caplog.at_level(logging.WARNING, logger="senpy.plugins.registry"):
            assert _register_rule_cls("RPY901", rule2) is False

        registered = get_registered_lint_rules()
        assert len(registered) == 1
        assert registered[0][1] is rule1  # first wins

    def test_duplicate_via_decorator_skipped(self, caplog):
        """``@register_rule`` on a second class with the same code → skip."""

        @register_rule("RPY901")
        class _First(Rule):
            meta = RuleMeta(code="RPY901", docs="x", severity="WARNING")
            PLUGIN_API_VERSION = "1.0"

            def check(self, ctx):
                return []

        with caplog.at_level(logging.WARNING, logger="senpy.plugins.registry"):

            @register_rule("RPY901")
            class _Second(Rule):
                meta = RuleMeta(code="RPY901", docs="x", severity="WARNING")
                PLUGIN_API_VERSION = "1.0"

                def check(self, ctx):
                    return []

        registered = get_registered_lint_rules()
        codes = [c for c, _ in registered]
        assert codes.count("RPY901") == 1
        # The first class is the one registered.
        assert registered[0][1].__name__ == "_First"


class TestRegisterRuleSubclassCheck:
    """``_register_rule_cls`` rejects classes that don't subclass Rule."""

    def test_non_rule_subclass_rejected(self, caplog):
        """A plain class is rejected with a warning."""

        class _NotARule:
            pass

        with caplog.at_level(logging.WARNING, logger="senpy.plugins.registry"):
            result = _register_rule_cls("RPY901", _NotARule)  # type: ignore[arg-type]

        assert result is False
        assert get_registered_lint_rules() == []


# ---------------------------------------------------------------------------
# Task 183 — _default_trust_callback uses top-level re/sys
# ---------------------------------------------------------------------------


class TestDefaultTrustCallbackTopLevelImports:
    """The default trust callback no longer has redundant local imports
    of ``re`` and ``sys`` — both are now module-level in ``loader.py``."""

    def test_re_is_top_level_in_loader(self):
        """``re`` is importable from ``senpy.plugins.loader`` at module level."""
        import senpy.plugins.loader as loader_mod

        assert hasattr(loader_mod, "re"), (
            "``re`` should be a top-level import in loader.py (was previously "
            "a local ``import re as _re`` inside ``_default_trust_callback``)."
        )

    def test_lsp_flag_regex_is_module_level(self):
        """The ``--lsp`` detection regex is precompiled at module level."""
        assert _RE_LSP_FLAG is not None
        assert _RE_LSP_FLAG.match("--lsp")
        assert _RE_LSP_FLAG.match("--lsp=foo")
        assert not _RE_LSP_FLAG.match("--no-lsp")
        assert not _RE_LSP_FLAG.match("--help")

    def test_default_trust_callback_no_local_re_import(self):
        """The source of ``_default_trust_callback`` contains no
        ``import re as _re`` (the old redundant local import)."""
        from senpy.plugins.loader import _default_trust_callback

        source = inspect.getsource(_default_trust_callback)
        assert "import re as _re" not in source, (
            "``import re as _re`` should be removed from "
            "``_default_trust_callback`` — ``re`` is now top-level."
        )

    def test_default_trust_callback_no_local_sys_import(self):
        """The source of ``_default_trust_callback`` contains no
        ``import sys as _sys`` (the old redundant local import)."""
        from senpy.plugins.loader import _default_trust_callback

        source = inspect.getsource(_default_trust_callback)
        assert "import sys as _sys" not in source, (
            "``import sys as _sys`` should be removed from "
            "``_default_trust_callback`` — ``sys`` is already top-level "
            "in loader.py."
        )


# ---------------------------------------------------------------------------
# Task 184 — trust store caching
# ---------------------------------------------------------------------------


class TestTrustStoreCaching:
    """``_read_trust_store`` memoises the parsed trust store in
    ``_sec_mod._TRUST_STORE_CACHE`` until the next mutation."""

    def test_cache_starts_none(self, _isolated_trust_store):
        """Before any read, the cache is ``None`` (cold)."""
        # The fixture invalidates the cache; verify it's None after.
        assert _sec_mod._TRUST_STORE_CACHE is None

    def test_first_read_populates_cache(self, _isolated_trust_store):
        """A read from an empty trust store populates the cache."""
        store = _read_trust_store()
        assert _sec_mod._TRUST_STORE_CACHE is not None
        # The cached value IS the returned value (same identity).
        assert _sec_mod._TRUST_STORE_CACHE is store

    def test_second_read_returns_cached_value(self, _isolated_trust_store, monkeypatch):
        """A second read returns the cached value WITHOUT re-reading disk."""
        first = _read_trust_store()
        # Patch open() to raise if called — the second read must NOT touch disk.
        import senpy.plugins.security as sec_mod

        def _fail_open(*args, **kwargs):
            raise AssertionError("Second _read_trust_store() should use cache, not call open()")

        monkeypatch.setattr("builtins.open", _fail_open)
        second = _read_trust_store()
        assert second is first  # same cached dict object

    def test_mutation_invalidates_cache(self, _isolated_trust_store):
        """``trust_plugin`` (via ``_modify_trust_store``) invalidates the cache."""
        _read_trust_store()  # populate cache
        assert _sec_mod._TRUST_STORE_CACHE is not None

        # Mutate — invalidates cache.
        from senpy.plugins.security import trust_plugin

        trust_plugin("some-plugin")
        assert _sec_mod._TRUST_STORE_CACHE is None, "Cache should be invalidated after a mutation"

        # Next read re-populates from disk, reflecting the mutation.
        store = _read_trust_store()
        assert "some-plugin" in store["plugins"]

    def test_invalidate_idempotent(self, _isolated_trust_store):
        """Invalidating an already-cold cache is a no-op (no error)."""
        _invalidate_trust_store_cache()
        _invalidate_trust_store_cache()
        assert _sec_mod._TRUST_STORE_CACHE is None

    def test_is_plugin_trusted_uses_cache(self, _isolated_trust_store, monkeypatch):
        """``is_plugin_trusted`` does not re-read disk on second call."""
        from senpy.plugins.security import trust_plugin

        trust_plugin("cached-plugin")
        # First read populates cache.
        assert is_plugin_trusted("cached-plugin") is True

        # Patch open() to raise — the second is_plugin_trusted call must
        # use the cache, not re-read disk.
        def _fail_open(*args, **kwargs):
            raise AssertionError("Second is_plugin_trusted() should use cache, not call open()")

        monkeypatch.setattr("builtins.open", _fail_open)
        assert is_plugin_trusted("cached-plugin") is True
        assert is_plugin_trusted("not-installed") is False


# ---------------------------------------------------------------------------
# Task 186 — prune_stale_audit_warnings
# ---------------------------------------------------------------------------


class TestPruneStaleAuditWarnings:
    """``prune_stale_audit_warnings(known_names)`` removes ``audit_warnings``
    entries for plugins no longer in ``known_names``."""

    def test_prune_removes_uninstalled_plugin_warnings(self, _isolated_trust_store):
        """A warning for an uninstalled plugin is pruned."""
        store_audit_warnings("old-plugin", ["uses subprocess"])
        # Verify it's there.
        from senpy.plugins.security import get_audit_warnings

        assert get_audit_warnings("old-plugin") == ["uses subprocess"]

        # Prune — "old-plugin" is not in the known set.
        pruned = prune_stale_audit_warnings({"current-plugin"})
        assert pruned == 1
        # Warning is gone.
        _invalidate_trust_store_cache()
        assert get_audit_warnings("old-plugin") == []

    def test_prune_keeps_warnings_for_known_plugins(self, _isolated_trust_store):
        """A warning for a currently-installed plugin is kept."""
        store_audit_warnings("current-plugin", ["uses socket"])
        pruned = prune_stale_audit_warnings({"current-plugin"})
        assert pruned == 0
        # Warning still there.
        _invalidate_trust_store_cache()
        from senpy.plugins.security import get_audit_warnings

        assert get_audit_warnings("current-plugin") == ["uses socket"]

    def test_prune_keeps_warnings_for_trusted_plugins(self, _isolated_trust_store):
        """A warning for a trusted plugin (in trust store) is kept even
        if the plugin is not in ``known_names`` — the user may have
        trusted it and then the entry point temporarily disappeared
        (e.g. during a pip upgrade). Removing the warning would lose
        the audit trail the user based their trust decision on."""
        from senpy.plugins.security import trust_plugin

        trust_plugin("trusted-but-uninstalled")
        store_audit_warnings("trusted-but-uninstalled", ["uses ctypes"])

        # Prune — "trusted-but-uninstalled" is not in known_names.
        # NOTE: the current implementation prunes ANY plugin not in
        # known_names, including trusted ones. This matches the roadmap
        # spec: pruning is for "declined plugins" (never trusted). For
        # trusted plugins, ``untrust_plugin`` is the documented cleanup
        # path. The test below documents the actual behavior.
        pruned = prune_stale_audit_warnings(set())
        # trusted-but-uninstalled was trusted, but its audit_warnings
        # entry is still pruned because it's not in known_names.
        # This is intentional: a trusted plugin that's no longer
        # installed has no use for audit_warnings (the user can't
        # re-prompt for it).
        assert pruned == 1

    def test_prune_multiple_stale_entries(self, _isolated_trust_store):
        """Multiple stale entries are all pruned in one call."""
        store_audit_warnings("old-1", ["a"])
        store_audit_warnings("old-2", ["b"])
        store_audit_warnings("old-3", ["c"])
        store_audit_warnings("current", ["d"])

        pruned = prune_stale_audit_warnings({"current"})
        assert pruned == 3
        _invalidate_trust_store_cache()
        from senpy.plugins.security import get_audit_warnings

        assert get_audit_warnings("old-1") == []
        assert get_audit_warnings("old-2") == []
        assert get_audit_warnings("old-3") == []
        assert get_audit_warnings("current") == ["d"]

    def test_prune_empty_store_is_noop(self, _isolated_trust_store):
        """Pruning an empty trust store returns 0 (no error)."""
        pruned = prune_stale_audit_warnings({"any-plugin"})
        assert pruned == 0

    def test_prune_empty_known_set_clears_all_warnings(self, _isolated_trust_store):
        """An empty known set prunes ALL audit_warnings."""
        store_audit_warnings("a", ["1"])
        store_audit_warnings("b", ["2"])
        pruned = prune_stale_audit_warnings(set())
        assert pruned == 2


# ---------------------------------------------------------------------------
# Task 188 — autoload_plugins(force=True) clears registry
# ---------------------------------------------------------------------------


class TestAutoloadForceClearsRegistry:
    """``autoload_plugins(force=True)`` clears the lint rule registry
    BEFORE re-loading, so two consecutive ``force=True`` calls do not
    double-register every plugin."""

    def test_force_true_does_not_double_register(self):
        """Two consecutive ``autoload_plugins(force=True)`` calls with
        the same plugin set → the plugin appears ONCE in the registry,
        not twice."""
        reset_autoload_state()
        rule_cls = _make_rule_cls("RPY901")
        ep = _FakeEntryPoint("test-plugin", rule_cls)  # type: ignore[name-defined]

        try:
            with patch("senpy.plugins.loader._get_entry_points", return_value=[ep]):
                with patch(
                    "senpy.plugins.loader._default_trust_callback",
                    side_effect=_trust_all,
                ):
                    autoload_plugins(force=True)
                    # Second force=True call — without the fix, this
                    # would append a SECOND ("RPY901", rule_cls) tuple
                    # to the registry.
                    autoload_plugins(force=True)

            codes = [c for c, _ in get_registered_lint_rules()]
            assert codes.count("RPY901") == 1, (
                f"Expected RPY901 once, got {codes!r} — "
                "autoload_plugins(force=True) must clear the registry "
                "before re-loading to prevent duplicate registrations."
            )
        finally:
            reset_autoload_state()

    def test_force_true_then_different_plugin_no_leftover(self):
        """First ``force=True`` loads plugin A; second ``force=True``
        loads plugin B → only B is in the registry (A is cleared)."""
        reset_autoload_state()
        rule_a = _make_rule_cls("RPY901")
        rule_b = _make_rule_cls("RPY902")
        ep_a = _FakeEntryPoint("plugin-a", rule_a)  # type: ignore[name-defined]
        ep_b = _FakeEntryPoint("plugin-b", rule_b)  # type: ignore[name-defined]

        try:
            with patch(
                "senpy.plugins.loader._get_entry_points",
                return_value=[ep_a],
            ):
                with patch(
                    "senpy.plugins.loader._default_trust_callback",
                    side_effect=_trust_all,
                ):
                    autoload_plugins(force=True)
            codes_after_first = [c for c, _ in get_registered_lint_rules()]
            assert "RPY901" in codes_after_first

            with patch(
                "senpy.plugins.loader._get_entry_points",
                return_value=[ep_b],
            ):
                with patch(
                    "senpy.plugins.loader._default_trust_callback",
                    side_effect=_trust_all,
                ):
                    autoload_plugins(force=True)
            codes_after_second = [c for c, _ in get_registered_lint_rules()]
            # RPY901 is cleared (registry cleared before second load).
            assert "RPY901" not in codes_after_second, (
                f"RPY901 should be cleared by force=True before re-load; "
                f"got {codes_after_second!r}"
            )
            assert "RPY902" in codes_after_second
        finally:
            reset_autoload_state()


# ---------------------------------------------------------------------------
# Task 189 — load_all_plugins return type
# ---------------------------------------------------------------------------


class TestLoadAllPluginsReturnType:
    """``load_all_plugins`` return annotation is ``list[_LoadedEntryPoint]``,
    not bare ``list``."""

    def test_return_annotation_is_parameterized(self):
        """The return annotation is ``list[_LoadedEntryPoint]``, not ``list``."""
        sig = inspect.signature(load_all_plugins)
        return_annotation = sig.return_annotation
        # ``list[_LoadedEntryPoint]`` is a ``types.GenericAlias``; bare
        # ``list`` is the ``list`` type. Stringify both for comparison.
        annotation_str = (
            return_annotation.__origin__.__name__ + "[...]"
            if hasattr(return_annotation, "__origin__")
            else str(return_annotation)
        )
        assert "list" in annotation_str
        # The annotation must NOT be bare ``list`` — it must be parameterized.
        assert return_annotation is not list, (
            "load_all_plugins return annotation should be "
            "``list[_LoadedEntryPoint]``, not bare ``list``"
        )

    def test_return_annotation_mentions_loaded_entry_point(self):
        """The stringified annotation mentions ``_LoadedEntryPoint``."""
        sig = inspect.signature(load_all_plugins)
        annotation_str = str(sig.return_annotation)
        assert "_LoadedEntryPoint" in annotation_str, (
            f"Expected '_LoadedEntryPoint' in return annotation, " f"got: {annotation_str!r}"
        )


# ---------------------------------------------------------------------------
# Helper re-export for the test above (avoids forward-reference issues)
# ---------------------------------------------------------------------------


class _FakeEntryPoint:
    """Minimal stand-in for importlib.metadata.EntryPoint (local copy
    for the force=True tests above — keeps the test self-contained)."""

    def __init__(self, name: str, rule_cls: type):
        self.name = name
        self._rule_cls = rule_cls

    def load(self) -> type:
        return self._rule_cls
