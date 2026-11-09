"""Tests for `senpy.core.renpy_builtins` — single source of truth for
BUILTIN_SYMBOLS and BUILTIN_ACTIONS, plus runtime extension via
``senpy.toml [tool.senpy].additional_builtins`` / ``.additional_actions``.

  Shipped defaults include the previously-missing names that triggered
     user-facing false positives:
       - ``achievement`` in BUILTIN_SYMBOLS (RPY202 on
         ``if achievement.steam:`` inside a screen).
       - ``GamepadCalibrate`` in BUILTIN_ACTIONS (RPY206 on
         ``textbutton "Calibrate" action GamepadCalibrate()``).
  The defaults stay a plain ``set`` so the existing contract
     (``isinstance(BUILTIN_SYMBOLS, set)`` in tests/core/test_imports.py)
     is preserved through the extraction.
  ``senpy.toml`` extension: when a user lists ``additional_builtins``
     or ``additional_actions``, the analyzer merges them with the shipped
     defaults so the same rules stop firing on user-declared names.
  SymbolTable survives ``reset()`` and ``rebuild_from_scopes()`` with
     the user-extended built-ins intact — no silent loss across runs.
  Invalid identifiers in ``additional_builtins`` (digits, spaces,
     non-ASCII, non-string) are silently filtered so a typo in
     ``senpy.toml`` cannot poison the symbol table.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.config import SenpyConfig
from senpy.core.constants import BUILTIN_ACTIONS, BUILTIN_SYMBOLS
from senpy.core.symbol_table import SymbolTable


# =============================================================================
# 1. Shipped defaults — the previously-missing names are present
# =============================================================================
class TestShippedDefaults:
    """The two names that triggered user false positives are now shipped."""

    def test_achievement_is_builtin_symbol(self) -> None:
        """`if achievement.steam:` must not fire RPY202/RPY103.

        ``achievement`` is a runtime-provided Ren'Py namespace documented
        at https://www.renpy.org/doc/html/achievements.html. Previously
        missing from BUILTIN_SYMBOLS — caused RPY202 false positives on
        the ``developers_info`` screen of a real user project.
        """
        assert "achievement" in BUILTIN_SYMBOLS

    def test_gamepad_calibrate_is_builtin_action(self) -> None:
        """`action GamepadCalibrate()` must not fire RPY206.

        ``GamepadCalibrate`` is a documented Ren'Py screen action that
        invokes the gamepad calibration routine — calling it with ``()``
        in the ``action`` slot is the documented usage, not an immediate
        call. Previously missing from BUILTIN_ACTIONS.
        """
        assert "GamepadCalibrate" in BUILTIN_ACTIONS

    def test_builtin_symbols_is_a_set(self) -> None:
        """Existing contract: BUILTIN_SYMBOLS is a plain set.

        tests/core/test_imports.py asserts this; the extraction to
        ``renpy_builtins.py`` must not change the runtime type.
        """
        assert isinstance(BUILTIN_SYMBOLS, set)

    def test_builtin_actions_is_a_set(self) -> None:
        """Existing contract: BUILTIN_ACTIONS is a plain set."""
        assert isinstance(BUILTIN_ACTIONS, set)

    def test_achievement_suppresses_rpy202_end_to_end(self, tmp_path: Path) -> None:
        """End-to-end: ``if achievement.steam:`` inside a screen produces
        NO RPY202 (was: false positive before the whitelist fix)."""
        project = tmp_path / "game"
        project.mkdir()
        (project / "script.rpy").write_text(
            "screen developers_info():\n"
            '    text f"Steam: {achievement.steam}"\n'
            "label start:\n"
            '    "Hello"\n',
            encoding="utf-8",
        )
        a = SenpyAnalyzer(str(tmp_path))
        a.run(quiet=True)
        rpy202 = [d for d in a.diagnostics if d.code == "RPY202"]
        assert not rpy202, (
            f"RPY202 fired on `achievement.steam` access — should be "
            f"silenced by BUILTIN_SYMBOLS. Got: {[d.message for d in rpy202]}"
        )

    def test_gamepad_calibrate_suppresses_rpy206_end_to_end(self, tmp_path: Path) -> None:
        """End-to-end: ``action GamepadCalibrate()`` produces no RPY206."""
        project = tmp_path / "game"
        project.mkdir()
        (project / "script.rpy").write_text(
            "screen gamepad_setup():\n"
            '    textbutton "Calibrate" action GamepadCalibrate()\n'
            "label start:\n"
            '    "Hello"\n',
            encoding="utf-8",
        )
        a = SenpyAnalyzer(str(tmp_path))
        a.run(quiet=True)
        rpy206 = [d for d in a.diagnostics if d.code == "RPY206"]
        assert not rpy206, (
            f"RPY206 fired on `action GamepadCalibrate()` — should be "
            f"silenced by BUILTIN_ACTIONS. Got: {[d.message for d in rpy206]}"
        )


# =============================================================================
# 2. Config schema — additional_builtins / additional_actions
# =============================================================================
class TestConfigFields:
    """Pydantic schema accepts the new fields and applies defaults."""

    def test_defaults_are_empty_lists(self) -> None:
        cfg = SenpyConfig()
        assert cfg.additional_builtins == []
        assert cfg.additional_actions == []

    def test_accepts_string_lists(self) -> None:
        cfg = SenpyConfig(
            additional_builtins=["iap", "updater"],
            additional_actions=["MyCustomAction"],
        )
        assert cfg.additional_builtins == ["iap", "updater"]
        assert cfg.additional_actions == ["MyCustomAction"]

    def test_unknown_fields_still_ignored(self) -> None:
        """Forward-compat: unknown keys do not raise."""
        cfg = SenpyConfig(unknown_future_field=42)  # type: ignore[call-arg]
        assert cfg.additional_builtins == []

    def test_load_config_merges_additional_builtins(self, tmp_path: Path) -> None:
        """`senpy.toml [tool.senpy].additional_builtins` reaches analyzer."""
        (tmp_path / "senpy.toml").write_text(
            "[tool.senpy]\n"
            'additional_builtins = ["iap", "my_namespace"]\n'
            'additional_actions = ["MyAction"]\n',
            encoding="utf-8",
        )
        (tmp_path / "game").mkdir()
        (tmp_path / "game" / "script.rpy").write_text('label start:\n    "Hi"\n', encoding="utf-8")
        a = SenpyAnalyzer(str(tmp_path))
        assert "iap" in a._additional_builtins
        assert "my_namespace" in a._additional_builtins
        assert "MyAction" in a._additional_actions


# =============================================================================
# 3. SymbolTable — additional_builtins survive reset / rebuild
# =============================================================================
class TestSymbolTableExtension:
    """SymbolTable merges additional_builtins into declared_symbols."""

    def test_additional_builtins_added_to_declared_symbols(self) -> None:
        st = SymbolTable(additional_builtins={"iap", "my_namespace"})
        assert "iap" in st.declared_symbols
        assert "my_namespace" in st.declared_symbols
        # And shipped defaults still present.
        assert "renpy" in st.declared_symbols
        assert "achievement" in st.declared_symbols

    def test_additional_builtins_survive_reset(self) -> None:
        st = SymbolTable(additional_builtins={"iap"})
        assert "iap" in st.declared_symbols
        st.reset()
        # After reset, the additional_builtins must be re-merged —
        # otherwise the same analyzer instance loses the config-provided
        # extensions on a second run().
        assert "iap" in st.declared_symbols

    def test_invalid_identifiers_filtered(self) -> None:
        """`additional_builtins` containing non-identifier strings
        (digits, spaces) and non-string entries are silently dropped so
        a typo in senpy.toml cannot poison the symbol table.

        Note: PEP 3131 allows Unicode letters in identifiers — `é` is a
        legitimate identifier and is NOT filtered. We only filter
        syntactically-invalid Python identifiers."""
        st = SymbolTable(
            additional_builtins={  # type: ignore[arg-type]
                "valid_name",
                "123invalid",  # starts with digit
                "with space",  # contains space
                "good_é_name",  # valid Unicode identifier (PEP 3131)
                42,  # non-string
                None,  # non-string
            }
        )
        assert "valid_name" in st.declared_symbols
        assert "good_é_name" in st.declared_symbols  # PEP 3131 — valid
        assert "123invalid" not in st.declared_symbols
        assert "with space" not in st.declared_symbols

    def test_no_additional_builtins_default(self) -> None:
        """SymbolTable() with no args still works — pure defaults."""
        st = SymbolTable()
        assert "renpy" in st.declared_symbols
        assert "achievement" in st.declared_symbols


# =============================================================================
# 4. End-to-end: config-supplied namespace silences RPY202
# =============================================================================
class TestConfigExtensionEndToEnd:
    """A user-listed namespace in senpy.toml silences the same rules as
    a shipped builtin."""

    def test_additional_builtin_silences_rpy202(self, tmp_path: Path) -> None:
        (tmp_path / "senpy.toml").write_text(
            '[tool.senpy]\nadditional_builtins = ["iap"]\n',
            encoding="utf-8",
        )
        game = tmp_path / "game"
        game.mkdir()
        (game / "script.rpy").write_text(
            "screen store():\n"
            '    text f"Purchases: {iap.total}"\n'
            "label start:\n"
            '    "Hello"\n',
            encoding="utf-8",
        )
        a = SenpyAnalyzer(str(tmp_path))
        a.run(quiet=True)
        rpy202 = [d for d in a.diagnostics if d.code == "RPY202"]
        assert not rpy202, (
            f"RPY202 fired on `iap.total` access despite `iap` being in "
            f"senpy.toml additional_builtins. Got: {[d.message for d in rpy202]}"
        )

    def test_additional_action_silences_rpy206(self, tmp_path: Path) -> None:
        (tmp_path / "senpy.toml").write_text(
            '[tool.senpy]\nadditional_actions = ["MyCustomAction"]\n',
            encoding="utf-8",
        )
        game = tmp_path / "game"
        game.mkdir()
        (game / "script.rpy").write_text(
            "screen s():\n"
            '    textbutton "Custom" action MyCustomAction()\n'
            "label start:\n"
            '    "Hello"\n',
            encoding="utf-8",
        )
        a = SenpyAnalyzer(str(tmp_path))
        a.run(quiet=True)
        rpy206 = [d for d in a.diagnostics if d.code == "RPY206"]
        assert not rpy206, (
            f"RPY206 fired on `action MyCustomAction()` despite "
            f"`MyCustomAction` being in senpy.toml additional_actions. "
            f"Got: {[d.message for d in rpy206]}"
        )

    def test_unknown_action_still_fires_rpy206(self, tmp_path: Path) -> None:
        """Sanity: a function call that's NOT in BUILTIN_ACTIONS and NOT
        in additional_actions still fires RPY206 — we didn't break
        the rule, only extended the allowlist."""
        game = tmp_path / "game"
        game.mkdir()
        (game / "script.rpy").write_text(
            "screen s():\n"
            '    textbutton "Bad" action user_defined_func()\n'
            "label start:\n"
            '    "Hello"\n',
            encoding="utf-8",
        )
        a = SenpyAnalyzer(str(tmp_path))
        a.run(quiet=True)
        rpy206 = [d for d in a.diagnostics if d.code == "RPY206"]
        assert rpy206, (
            "RPY206 did not fire on `action user_defined_func()` — the "
            "rule must still fire for genuinely-unknown actions."
        )
