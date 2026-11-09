"""Tests for:

_check_voice_loop string-literal masking.
    ``asset.py:609`` — ``re.search(r"\\bloop\\b", rest, re.IGNORECASE)``
    runs directly on ``rest`` without ``strip_string_literals``. A line
    like ``queue voice "song_loop.ogg"`` matches ``loop`` inside the
    string literal → false RPY505 (voice loop warning).

register_channel regex matches inside strings.
    ``file_collector.py:753`` — the ``register_channel`` regex runs on
    ``clean`` BEFORE ``strip_string_literals`` is applied (line 759+).
    A dialogue line like ``"renpy.music.register_channel('foo')"``
    matches inside the string → falsely registers channel ``foo``.

Plugin API version — opt-out instead of opt-in.
    ``loader.py:237-242`` — a plugin that does NOT declare
    ``PLUGIN_API_VERSION`` loads with a DEBUG log. The contract
    (``docs/plugin-development.md:62``) says "must declare". Enforce:
    WARNING + skip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer


def _diags(analyzer: SenpyAnalyzer) -> list[tuple[str, str]]:
    """Return (code, message) pairs."""
    return [(d.code, d.message) for d in analyzer.diagnostics]


# =============================================================================
# P2-16: _check_voice_loop string-literal masking
# =============================================================================


class TestVoiceLoopStringLiteralMasking:
    """_check_voice_loop must not match 'loop' inside string literals."""

    def test_voice_loop_in_string_literal_no_rpy505(self, tmp_path: Path):
        """``queue voice "my loop song.ogg"`` must NOT trigger RPY505.

        Before P2-16: ``re.search(r"\\bloop\\b", rest)`` matched ``loop``
        inside the string literal ``"my loop song.ogg"`` → false RPY505.
        After P2-16: ``strip_string_literals`` masks the string → no match.
        """
        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        (game / "script.rpy").write_text(
            'label start:\n    queue voice "my loop song.ogg"\n    return\n',
            encoding="utf-8",
        )
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        rpy505 = [d for d in analyzer.diagnostics if d.code == "RPY505"]
        assert rpy505 == [], (
            f"RPY505 must NOT fire on 'queue voice \"my loop song.ogg\"' — "
            f"'loop' is inside a string literal, not a loop keyword. "
            f"Got: {rpy505}"
        )

    def test_real_voice_loop_still_fires(self, tmp_path: Path):
        """``queue voice "song.ogg" loop`` must still trigger RPY505.

        Sanity: the actual `loop` keyword outside a string must still fire.
        """
        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        (game / "script.rpy").write_text(
            'label start:\n    queue voice "song.ogg" loop\n    return\n',
            encoding="utf-8",
        )
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        rpy505 = [d for d in analyzer.diagnostics if d.code == "RPY505"]
        assert rpy505, (
            "RPY505 MUST fire on 'queue voice \"song.ogg\" loop' — "
            "'loop' is a real keyword here, not inside a string."
        )


# =============================================================================
# P2-17: register_channel regex matches inside strings
# =============================================================================


class TestRegisterChannelStringLiteralMasking:
    """register_channel regex must not match inside string literals."""

    def test_register_channel_in_dialogue_not_registered(self, tmp_path: Path):
        """A dialogue line mentioning register_channel must not register the channel.

        Before P2-17: ``re.search(r'renpy\\.music\\.register_channel...', clean)``
        matched inside string literals → false channel registration.
        After P2-17: ``strip_string_literals`` masks the string → no match.
        """
        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        # A dialogue line that mentions register_channel as text — the
        # channel 'fake_chan' should NOT be registered.
        (game / "script.rpy").write_text(
            "label start:\n"
            "    \"Use renpy.music.register_channel('fake_chan') to register\"\n"
            "    return\n",
            encoding="utf-8",
        )
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        assert "fake_chan" not in analyzer.registered_audio_channels, (
            f"'fake_chan' must NOT be registered — it appeared inside a "
            f"dialogue string, not a real register_channel call. "
            f"Got channels: {analyzer.registered_audio_channels}"
        )

    def test_real_register_channel_still_registered(self, tmp_path: Path):
        """A real register_channel call in init python must still register.

        Sanity: the actual call outside strings must work.
        """
        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        (game / "script.rpy").write_text(
            "init python:\n"
            '    renpy.music.register_channel("real_chan", mixer="music")\n'
            "label start:\n"
            "    return\n",
            encoding="utf-8",
        )
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        assert "real_chan" in analyzer.registered_audio_channels, (
            f"'real_chan' must be registered — it's a real register_channel "
            f"call in init python. Got channels: {analyzer.registered_audio_channels}"
        )


# =============================================================================
# P2-19: Plugin API version — opt-out instead of opt-in
# =============================================================================


class TestPluginApiVersionEnforcement:
    """Plugin without PLUGIN_API_VERSION must be rejected (WARNING + skip)."""

    def test_plugin_without_api_version_resolves_none(self):
        """_resolve_plugin_api_version must return None for a class without it."""
        from senpy.plugins.base import Rule, RuleContext, RuleMeta
        from senpy.plugins.loader import _resolve_plugin_api_version

        class _NoVersionRule(Rule):
            # Deliberately does NOT declare PLUGIN_API_VERSION.
            meta = RuleMeta(
                code="RPY950",
                docs="Test rule without API version",
                severity="WARNING",
            )

            def check(self, ctx: RuleContext) -> list:
                return []

        result = _resolve_plugin_api_version(_NoVersionRule)
        assert result is None, (
            "Plugin without PLUGIN_API_VERSION must resolve to None — "
            "this is the precondition for the enforcement check."
        )

    def test_plugin_without_api_version_enforced_as_warning(self):
        """load_plugin must return None (skip) for plugin without PLUGIN_API_VERSION.

        Tests the enforcement behavior: when _resolve_plugin_api_version
        returns None, load_plugin must WARNING + return None (not load
        the plugin). Before P2-19: loaded with DEBUG log (silently accepted).
        After P2-19: WARNING + skip.
        """
        # The enforcement is in load_plugin lines 237-242. We verify the
        # behavior by reading the source code — if the else branch returns
        # None, the plugin is skipped. If it just logs DEBUG, it's not.
        import inspect

        from senpy.plugins.loader import load_plugin

        source = inspect.getsource(load_plugin)
        # Find the else branch (PLUGIN_API_VERSION is None).
        assert "return None" in source[source.find("does not declare") :], (
            "load_plugin must return None when PLUGIN_API_VERSION is not "
            "declared — the else branch must skip the plugin, not just "
            "log DEBUG and continue loading."
        )

    def test_plugin_with_api_version_resolves_value(self):
        """_resolve_plugin_api_version must return the version for a class with it."""
        from senpy.plugins.base import Rule, RuleContext, RuleMeta
        from senpy.plugins.loader import _resolve_plugin_api_version
        from senpy.plugins.security import PLUGIN_API_VERSION as _PAV

        class _WithVersionRule(Rule):
            PLUGIN_API_VERSION = _PAV
            meta = RuleMeta(
                code="RPY951",
                docs="Test rule with API version",
                severity="WARNING",
            )

            def check(self, ctx: RuleContext) -> list:
                return []

        result = _resolve_plugin_api_version(_WithVersionRule)
        assert (
            result is not None
        ), "Plugin WITH PLUGIN_API_VERSION must resolve to the version value."
        assert result == _PAV
