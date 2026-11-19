"""End-to-end integration tests for plugin import-time audit.

These tests verify the integration of three subsystems that were
previously tested only in isolation:

    audit.py (AST scan)  ↔  loader.load_plugin()  ↔  security.py (trust store)

The unit tests in ``test_audit.py`` cover the AST scanner in isolation
(feed source code, get warnings). The unit tests in
``test_plugin_tofu_before_load.py`` cover the trust-before-load
guarantee (declined trust → no ``entry_point.load()`` call). But
neither verifies that ``load_plugin()`` actually invokes the audit,
passes the entry point to it, and stores the resulting warnings in the
trust store where ``_default_trust_callback`` can find them.

That integration is the contract:

    load_plugin(ep)
        ↓
    audit_plugin_via_entry_point(ep)  ← reads .py source via importlib.metadata
        ↓
    store_audit_warnings(name, warnings)  ← writes to trust store
        ↓
    _default_trust_callback(name)
        ↓
    get_audit_warnings(name)  ← reads from trust store
        ↓
    prints warnings to user before [y/N] prompt

If any link breaks (e.g. audit skipped, warnings not stored, callback
doesn't read them), the user sees no warnings before trusting a plugin
that uses ``subprocess.run`` or ``eval()`` — silently accepting
dangerous code.

Additionally, after the "skip audit if already trusted" optimisation, a pre-trusted plugin must NOT re-run the audit
on subsequent loads, and its previously-stored audit_warnings must be
preserved (not overwritten with a fresh scan result).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from senpy.plugins.loader import load_plugin
from senpy.plugins.security import (
    get_audit_warnings,
    is_plugin_trusted,
    store_audit_warnings,
    trust_plugin,
    untrust_plugin,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _FakeEntryPointWithSource:
    """Fake entry point whose ``value`` resolves to a plugin package
    whose source files are discoverable via ``importlib.metadata.files()``.

    The audit reads source files through ``importlib.metadata.files()``
    — which returns a list of ``PackagePath`` objects. To test the audit
    integration without installing a real plugin package, we patch
    ``importlib.metadata.files`` to return a fake list of in-memory
    source files.

    Each call to ``load()`` returns a Rule subclass — but in the audit
    flow, ``load()`` is only reached AFTER the audit runs and AFTER
    trust is granted. So for audit-only tests we decline trust (or
    pre-trust), and ``load()`` is never called.
    """

    def __init__(
        self,
        name: str,
        source_files: dict[str, str],
        module_path: str = "test_plugin.rules:TestRule",
    ):
        self.name = name
        self.group = "senpy.plugins"
        self.value = module_path
        self._source_files = source_files
        self.load_call_count = 0

    def load(self):
        self.load_call_count += 1
        from senpy.plugins.base import Rule, RuleMeta

        class TestRule(Rule):
            meta = RuleMeta(code="RPY901", docs="test", severity="WARNING")
            PLUGIN_API_VERSION = "1.0"

            def check(self, ctx):  # type: ignore[override]
                return []

        return TestRule


class _FakePackagePath:
    """Minimal stand-in for ``importlib.metadata.PackagePath``.

    ``audit_plugin_via_entry_point`` calls ``pkg_path.read_text(encoding="utf-8")``
    on each path whose name ends with ``.py``. We provide a ``read_text``
    method returning the source content, and a ``__str__`` returning
    the path string (used as the dict key).
    """

    def __init__(self, path_str: str, content: str):
        self._path = path_str
        self._content = content

    def __str__(self) -> str:
        return self._path

    def read_text(self, encoding: str = "utf-8") -> str:
        return self._content


def _patch_metadata_files(source_files: dict[str, str]):
    """Patch ``importlib.metadata.files`` to return a list of
    ``_FakePackagePath`` objects built from ``source_files``.

    Returns the patcher (call ``.start()`` / ``.stop()`` or use as a
    context manager).
    """
    fake_paths = [_FakePackagePath(p, c) for p, c in source_files.items()]
    return patch("importlib.metadata.files", return_value=fake_paths)


def _trust_decline(_name: str) -> bool:
    return False


def _trust_approve(_name: str) -> bool:
    return True


@pytest.fixture(autouse=True)
def _isolated_trust_store(monkeypatch, tmp_path):
    """Point SENPY_HOME at a fresh tmp dir for every test — guarantees
    the trust store is empty and on-disk state from one test does not
    leak into another.
    """
    monkeypatch.setenv("SENPY_HOME", str(tmp_path))
    yield
    # No cleanup needed — tmp_path is auto-removed by pytest.


# ---------------------------------------------------------------------------
# Integration: load_plugin → audit → trust store
# ---------------------------------------------------------------------------


class TestLoadPluginAuditIntegration:
    """Verify that ``load_plugin()`` actually runs the audit and stores
    warnings in the trust store before the trust prompt is shown.

    These are the integration tests that ``test_audit.py`` (unit-level)
    and ``test_plugin_tofu_before_load.py`` (trust-level) cannot cover
    on their own.
    """

    def test_dangerous_plugin_warnings_reach_trust_store(self, tmp_path: Path):
        """A plugin whose source uses ``subprocess.run`` must end up
        with the corresponding warning in ``audit_warnings`` AFTER
        ``load_plugin()`` runs — even when trust is declined.

        Why declined: the audit runs BEFORE the trust prompt (R-P0-1
        contract). The user should see warnings regardless of whether
        they end up trusting the plugin. If the audit only ran for
        trusted plugins, a declined plugin would never be audited, and
        re-running ``senpy`` would re-prompt without any warning context.
        """
        ep = _FakeEntryPointWithSource(
            name="evil-helper",
            source_files={
                "rules.py": "import subprocess\nsubprocess.run(['ls'])\n",
            },
        )

        # Patch importlib.metadata.files so the audit can find our fake
        # source without installing a real plugin package.
        with _patch_metadata_files(ep._source_files):
            # Trust declined — but the audit must STILL have run.
            result = load_plugin(ep, trust_callback=_trust_decline)

        assert result is None, "Declined trust must short-circuit before load()."

        # The audit must have stored warnings BEFORE the trust prompt.
        stored = get_audit_warnings("evil-helper")
        assert stored, (
            "Audit warnings were not stored in trust store — load_plugin() "
            "either skipped the audit or did not call store_audit_warnings(). "
            "The user would see no warnings before the [y/N] prompt, even "
            "though the plugin uses subprocess.run()."
        )
        assert any("subprocess" in w for w in stored), (
            f"Expected a subprocess warning in {stored!r}, got none. "
            "The audit did not detect `import subprocess` + `subprocess.run`."
        )

    def test_clean_plugin_stores_empty_warnings(self, tmp_path: Path):
        """A plugin with safe source must store an empty list (not None,
        not absent) in ``audit_warnings``. This distinguishes "audited,
        found nothing" from "never audited".
        """
        ep = _FakeEntryPointWithSource(
            name="clean-plugin",
            source_files={
                "rules.py": "import re\nx = 1\n",
            },
        )

        with _patch_metadata_files(ep._source_files):
            result = load_plugin(ep, trust_callback=_trust_decline)

        assert result is None
        stored = get_audit_warnings("clean-plugin")
        assert stored == [], (
            f"Expected empty list (audited, no warnings), got {stored!r}. "
            "A clean plugin must record `audit_warnings[name] = []` so the "
            "trust callback can distinguish audited-clean from not-audited."
        )

    def test_audit_failure_does_not_block_loading(self, tmp_path: Path):
        """If ``importlib.metadata.files()`` raises (e.g. editable
        install without metadata), the audit fails silently and the
        plugin proceeds to the trust prompt. The audit is advisory —
        a missing audit must NOT prevent loading.
        """
        ep = _FakeEntryPointWithSource(
            name="metadata-less-plugin",
            source_files={"rules.py": "import subprocess\n"},
        )

        # Patch importlib.metadata.files to raise — simulates a plugin
        # installed via ``pip install -e .`` without proper metadata.
        with patch("importlib.metadata.files", side_effect=ModuleNotFoundError("no metadata")):
            # Trust approved — but the audit must fail first.
            result = load_plugin(ep, trust_callback=_trust_approve)

        # The audit failed, but the plugin must still load (advisory).
        assert result is not None, (
            "load_plugin returned None despite trust being approved — "
            "an audit failure must not block plugin loading (audit is advisory)."
        )
        # No warnings were stored (audit couldn't run).
        assert get_audit_warnings("metadata-less-plugin") == []

    def test_audit_warning_shown_in_default_trust_callback(
        self, tmp_path: Path, capsys, monkeypatch
    ):
        """The default trust callback (interactive TTY path) must
        print audit warnings to stderr before the [y/N] prompt — so
        the user can make an informed trust decision.

        This is the end-to-end test that ``test_audit.py`` and
        ``test_plugin_tofu_before_load.py`` cannot verify on their own:
        it ties the audit output to the user-facing prompt.
        """
        # Pre-store audit warnings for a plugin — simulates the audit
        # having already run before the callback is invoked.
        store_audit_warnings("risky-plugin", ["Plugin uses subprocess"])

        # Simulate interactive TTY (sys.stdin.isatty() returns True)
        # and provide 'n' as user input (decline trust).
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda prompt: "n")

        from senpy.plugins.loader import _default_trust_callback

        result = _default_trust_callback("risky-plugin")

        assert result is False, "User declined, callback must return False."
        captured = capsys.readouterr()
        assert (
            "risky-plugin" in captured.err
        ), "Plugin name must appear in stderr before the prompt."
        assert "subprocess" in captured.err, (
            "Audit warning text must appear in stderr before the prompt — "
            "the user needs to see what risky patterns the audit found."
        )

    def test_audit_skipped_for_pre_trusted_plugin(self, tmp_path: Path):
        """When a plugin is already in the trust store, ``load_plugin()``
        must SKIP the audit. This is the post-0.9.0 optimisation:

          - First load (untrusted): audit runs, warnings stored, user
            prompted with warnings visible.
          - Subsequent loads (trusted): audit skipped, previously-stored
            warnings preserved in trust store (NOT overwritten).

        Why skip: re-auditing on every Senpy start re-scans all .py
        files (slow, especially in LSP mode), and a package upgrade
        between runs would overwrite the original audit result the user
        trusted based on — confusing the user.

        Re-audit on demand: ``senpy --untrust-plugin NAME`` clears
        trust; the next ``senpy --trust-plugin NAME`` re-runs the audit
        because the plugin is no longer pre-trusted when load_plugin is
        called.
        """
        # Step 1: pre-trust the plugin and store original audit warnings.
        trust_plugin("pre-trusted-plugin")
        original_warnings = ["Plugin uses subprocess.run()"]
        store_audit_warnings("pre-trusted-plugin", original_warnings)

        ep = _FakeEntryPointWithSource(
            name="pre-trusted-plugin",
            # Different (more dangerous) source than what was originally
            # audited. If the audit re-runs, it would find these new
            # patterns and overwrite the original warnings.
            source_files={
                "rules.py": "import socket\nimport ctypes\nsocket.socket()\n",
            },
        )

        # Track whether audit_plugin_via_entry_point was called.
        with patch("senpy.plugins.audit.audit_plugin_via_entry_point") as mock_audit:
            mock_audit.return_value.warnings = ["NEW WARNING — should not be stored"]
            mock_audit.return_value.has_warnings = True
            mock_audit.return_value.files_scanned = 1
            mock_audit.return_value.error = None

            with _patch_metadata_files(ep._source_files):
                result = load_plugin(ep, trust_callback=_trust_approve)

        # Audit must NOT have been called.
        assert not mock_audit.called, (
            "Audit was called for a pre-trusted plugin. The audit should "
            "be skipped when the plugin is already in the trust store — "
            "re-auditing on every load is wasteful and would overwrite "
            "the original audit_warnings the user trusted based on."
        )

        # Plugin must still have loaded (trust approved).
        assert result is not None, "Trusted plugin must load."

        # Original audit warnings must be preserved in trust store.
        stored = get_audit_warnings("pre-trusted-plugin")
        assert stored == original_warnings, (
            f"Expected original warnings {original_warnings!r}, got {stored!r}. "
            "Pre-trusted plugin's audit_warnings must be preserved — not "
            "overwritten by a fresh scan that the optimisation is supposed "
            "to skip."
        )

    def test_re_audit_after_untrust(self, tmp_path: Path):
        """After ``untrust_plugin(NAME)``, the next ``load_plugin`` call
        must re-run the audit (because the plugin is no longer pre-trusted).

        This is the user-facing "re-audit on demand" flow:

            senpy --untrust-plugin risky-plugin
            senpy --trust-plugin risky-plugin   # re-runs audit

        Without this contract, a user who ``pip install --upgrade``d a
        plugin would have no way to refresh the audit result — the
        optimisation in ``test_audit_skipped_for_pre_trusted_plugin``
        would keep showing the old warnings.
        """
        # Step 1: pre-trust + audit.
        trust_plugin("risky-plugin")
        store_audit_warnings("risky-plugin", ["OLD: uses subprocess"])

        # Step 2: untrust — clears trust AND audit_warnings.
        untrusted = untrust_plugin("risky-plugin")
        assert untrusted, "untrust_plugin must return True for a trusted plugin."
        assert not is_plugin_trusted("risky-plugin")
        assert get_audit_warnings("risky-plugin") == [], (
            "untrust_plugin must clear audit_warnings — otherwise stale "
            "warnings would resurface if the user re-trusts the plugin."
        )

        # Step 3: new load_plugin call — must re-run audit (plugin is
        # no longer pre-trusted).
        ep = _FakeEntryPointWithSource(
            name="risky-plugin",
            source_files={
                "rules.py": "import socket\nsocket.socket()\n",  # NEW pattern
            },
        )

        with _patch_metadata_files(ep._source_files):
            load_plugin(ep, trust_callback=_trust_decline)

        # New audit_warnings must reflect the new source, not the old.
        stored = get_audit_warnings("risky-plugin")
        assert any("socket" in w for w in stored), (
            f"After untrust+reload, audit must re-run and find the new socket "
            f"pattern. Got {stored!r}."
        )
        assert not any("subprocess" in w for w in stored), (
            f"Old subprocess warning must not persist after re-audit. " f"Got {stored!r}."
        )

    def test_audit_warnings_persist_across_loads(self, tmp_path: Path):
        """Audit warnings stored by ``load_plugin`` (first load) must
        persist on disk — they survive across Senpy invocations because
        the trust store is a JSON file at ``~/.senpy/trusted_plugins.json``.

        This test verifies the persistence by reading the JSON file
        directly (not via the ``get_audit_warnings`` API) to catch
        any accidental in-memory-only storage.
        """
        ep = _FakeEntryPointWithSource(
            name="persistent-plugin",
            source_files={"rules.py": "import os\nos.system('rm -rf /')\n"},
        )

        with _patch_metadata_files(ep._source_files):
            load_plugin(ep, trust_callback=_trust_decline)

        # Read the trust store JSON directly — verifies on-disk persistence.
        trust_store_path = tmp_path / "trusted_plugins.json"
        assert (
            trust_store_path.exists()
        ), "Trust store JSON must be written to disk after store_audit_warnings."
        with open(trust_store_path, encoding="utf-8") as f:
            on_disk = json.load(f)

        assert (
            "audit_warnings" in on_disk
        ), "audit_warnings field must be present in the on-disk trust store."
        assert (
            "persistent-plugin" in on_disk["audit_warnings"]
        ), "Plugin name must be a key in audit_warnings dict on disk."
        warnings = on_disk["audit_warnings"]["persistent-plugin"]
        assert any(
            "os.system" in w for w in warnings
        ), f"os.system warning must be in on-disk audit_warnings. Got {warnings!r}."
