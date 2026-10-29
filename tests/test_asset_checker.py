"""TDD тесты для AssetChecker _check_* методов — Phase 4, Step 1 (0.5.7).

RED: эти тесты падают, потому что _check_* методы ещё не существуют.
GREEN: после extraction из check_line — тесты проходят.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


@dataclass
class MockImage:
    name: str = ""
    is_layered: bool = False
    attributes: set = None
    body: str = ""
    file_path: str = ""
    line_number: int = 0

    def __post_init__(self):
        if self.attributes is None:
            self.attributes = set()


class MockAnalyzer:
    """Минимальный mock для DiagnosticSink + asset store."""
    def __init__(self):
        self.diagnostics = []
        self.images = {}
        self.valid_images = {"black", "white", "bg"}
        self.known_assets = set()
        self.defined_audio_map = {}
        self.registered_audio_channels = set()
        self.audio_dir_files = {}
        self.fixable_count = 0
        self.fixed_count = 0
        self.fix = False
        self._used_assets = set()

    def _add_diagnostic(self, diag, noqa_map):
        self.diagnostics.append(diag)

    def _get_utf16_range(self, raw, name):
        return (0, len(name))

    def _mark_asset_used(self, asset):
        self._used_assets.add(asset)

    def _get_tag_known_attributes(self, base_tag, all_valid):
        return self.images.get(base_tag, MockImage()).attributes


def _make_checker(analyzer=None):
    from senpy.core.scope import ScopeStack
    from senpy.rules.checkers.asset import AssetChecker
    return AssetChecker(analyzer or MockAnalyzer())


def _make_scope(in_screen=False):
    from senpy.core.scope import Scope, ScopeStack, ScopeType
    ss = ScopeStack({"renpy", "config", "persistent", "store"})
    if in_screen:
        ss.push(Scope(ScopeType.SCREEN, "test_screen"))
    return ss


class TestCheckShowScene:
    """_check_show_scene — RPY502 (show/scene + ATL transforms)."""

    def test_method_exists(self):
        from senpy.rules.checkers.asset import AssetChecker
        assert hasattr(AssetChecker, "_check_show_scene")

    def test_valid_image_no_diagnostic(self):
        """show bg — валидное изображение, нет diagnostic."""
        from senpy.core.models import Diagnostic
        analyzer = MockAnalyzer()
        analyzer.valid_images = {"bg", "black", "white"}
        checker = _make_checker(analyzer)
        checker._check_show_scene("test.rpy", 0, "show bg", "show bg", _make_scope(), {})
        assert len(analyzer.diagnostics) == 0

    def test_invalid_sprite_rpy502(self):
        """show nonexistent — RPY502."""
        analyzer = MockAnalyzer()
        analyzer.valid_images = {"bg"}
        checker = _make_checker(analyzer)
        checker._check_show_scene("test.rpy", 0, "show ghost", "show ghost", _make_scope(), {})
        assert any(d.code == "RPY502" for d in analyzer.diagnostics)

    def test_at_transform_undefined_rpy502(self):
        """show bg at undefined_transform — RPY502."""
        analyzer = MockAnalyzer()
        analyzer.valid_images = {"bg"}
        analyzer.declared_symbols = set()
        analyzer.user_symbols = set()
        checker = _make_checker(analyzer)
        checker._check_show_scene("test.rpy", 0, "show bg at slide", "show bg at slide", _make_scope(), {})
        assert any(d.code == "RPY502" for d in analyzer.diagnostics)


class TestCheckAudioStatement:
    """_check_audio_statement — RPY501/RPY505 (play/queue/stop)."""

    def test_method_exists(self):
        from senpy.rules.checkers.asset import AssetChecker
        assert hasattr(AssetChecker, "_check_audio_statement")

    def test_play_valid_channel_no_file_rpy501(self):
        """play music без файла, без define audio → RPY501."""
        analyzer = MockAnalyzer()
        analyzer.registered_audio_channels = {"music"}
        checker = _make_checker(analyzer)
        checker._check_audio_statement("test.rpy", 0, "play music", "play music", {})
        assert any(d.code == "RPY501" for d in analyzer.diagnostics)

    def test_play_invalid_channel_rpy505(self):
        """play bad_channel → RPY505."""
        analyzer = MockAnalyzer()
        checker = _make_checker(analyzer)
        checker._check_audio_statement("test.rpy", 0, 'play bad_channel "song.ogg"', 'play bad_channel "song.ogg"', {})
        assert any(d.code == "RPY505" for d in analyzer.diagnostics)

    def test_stop_invalid_channel_rpy505(self):
        """stop bad_channel → RPY505."""
        analyzer = MockAnalyzer()
        checker = _make_checker(analyzer)
        checker._check_audio_statement("test.rpy", 0, "stop bad_channel", "stop bad_channel", {})
        assert any(d.code == "RPY505" for d in analyzer.diagnostics)

    def test_play_missing_audio_file_rpy501(self):
        """play music "nonexistent.ogg" → RPY501."""
        analyzer = MockAnalyzer()
        analyzer.registered_audio_channels = {"music"}
        analyzer.known_assets = set()
        checker = _make_checker(analyzer)
        checker._check_audio_statement("test.rpy", 0, 'play music "nonexistent.ogg"', 'play music "nonexistent.ogg"', {})
        assert any(d.code == "RPY501" for d in analyzer.diagnostics)

    def test_voice_loop_rpy505(self):
        """play voice loop "song.ogg" → RPY505 (loop on voice)."""
        analyzer = MockAnalyzer()
        analyzer.registered_audio_channels = {"voice"}
        analyzer.known_assets = {"song.ogg"}
        checker = _make_checker(analyzer)
        checker._check_audio_statement("test.rpy", 0, 'play voice "song.ogg" loop', 'play voice "song.ogg" loop', {})
        assert any(d.code == "RPY505" for d in analyzer.diagnostics)


class TestCheckLineRefactored:
    """Интеграционный тест: check_line вызывает _check_* методы."""

    def test_show_invalid_sprite(self):
        """check_line обрабатывает show ghost → RPY502."""
        from senpy.core.models import Diagnostic
        analyzer = MockAnalyzer()
        analyzer.valid_images = {"bg"}
        checker = _make_checker(analyzer)
        checker.check_line("test.rpy", 0, "show ghost", "show ghost", _make_scope(), {}, [])
        assert any(d.code == "RPY502" for d in analyzer.diagnostics)

    def test_play_invalid_channel(self):
        """check_line обрабатывает play bad → RPY505."""
        analyzer = MockAnalyzer()
        checker = _make_checker(analyzer)
        checker.check_line("test.rpy", 0, 'play bad "song.ogg"', 'play bad "song.ogg"', _make_scope(), {}, [])
        assert any(d.code == "RPY505" for d in analyzer.diagnostics)

    def test_normal_line_no_diagnostic(self):
        """check_line на обычной строке — нет diagnostic."""
        analyzer = MockAnalyzer()
        checker = _make_checker(analyzer)
        checker.check_line("test.rpy", 0, '"Hello world"', '"Hello world"', _make_scope(), {}, [])
        assert len(analyzer.diagnostics) == 0
