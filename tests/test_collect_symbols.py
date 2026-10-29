"""TDD тесты для _collect_* методов — Phase 3, Step 5 (0.5.6).

RED: эти тесты падают, потому что _collect_* методы ещё не существуют.
GREEN: после extraction из _collect_symbols — тесты проходят.

Тестирует что каждый _collect_* метод существует и обрабатывает
соответствующий тип объявления, создавая правильные symbols.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _make_project(tmp_path: Path, script: str) -> str:
    """Создаёт минимальный Ren'Py проект с game/script.rpy."""
    game = tmp_path / "game"
    game.mkdir(parents=True)
    script_file = game / "script.rpy"
    script_file.write_text(script, encoding="utf-8")
    return str(tmp_path)


class TestCollectDefault:
    """_collect_default — default var = expr."""

    def test_method_exists(self):
        from senpy.core.analyzer import SenpyAnalyzer
        assert hasattr(SenpyAnalyzer, "_collect_default")

    def test_default_creates_variable(self, tmp_path):
        """default x = 1 → VariableSymbol создан."""
        from senpy.core.analyzer import SenpyAnalyzer
        project = _make_project(tmp_path, 'default x = 1\n')
        analyzer = SenpyAnalyzer(project)
        analyzer.run(quiet=True)
        assert "x" in analyzer.variables
        assert analyzer.variables["x"].is_constant is False


class TestCollectDefine:
    """_collect_define — define var = expr."""

    def test_method_exists(self):
        from senpy.core.analyzer import SenpyAnalyzer
        assert hasattr(SenpyAnalyzer, "_collect_define")

    def test_define_creates_constant(self, tmp_path):
        """define CONST = 42 → VariableSymbol с is_constant=True."""
        from senpy.core.analyzer import SenpyAnalyzer
        project = _make_project(tmp_path, 'define CONST = 42\n')
        analyzer = SenpyAnalyzer(project)
        analyzer.run(quiet=True)
        assert "CONST" in analyzer.variables
        assert analyzer.variables["CONST"].is_constant is True


class TestCollectDefineAudio:
    """_collect_define_audio — define audio.NAME = file."""

    def test_method_exists(self):
        from senpy.core.analyzer import SenpyAnalyzer
        assert hasattr(SenpyAnalyzer, "_collect_define_audio")

    def test_define_audio_creates_alias(self, tmp_path):
        """define audio.music = "bgm.ogg" → alias в defined_audio_map."""
        from senpy.core.analyzer import SenpyAnalyzer
        project = _make_project(tmp_path, 'define audio.music = "bgm.ogg"\n')
        analyzer = SenpyAnalyzer(project)
        analyzer.run(quiet=True)
        assert "music" in analyzer.defined_audio_map
        assert analyzer.defined_audio_map["music"] == "bgm.ogg"


class TestCollectScreenTransform:
    """_collect_screen_transform — screen + transform."""

    def test_method_exists(self):
        from senpy.core.analyzer import SenpyAnalyzer
        assert hasattr(SenpyAnalyzer, "_collect_screen_transform")

    def test_screen_creates_symbol(self, tmp_path):
        """screen foo(): → ScreenSymbol."""
        from senpy.core.analyzer import SenpyAnalyzer
        project = _make_project(tmp_path, 'screen foo():\n    pass\n')
        analyzer = SenpyAnalyzer(project)
        analyzer.run(quiet=True)
        assert "foo" in analyzer.screens

    def test_transform_creates_symbol(self, tmp_path):
        """transform slide: → TransformSymbol."""
        from senpy.core.analyzer import SenpyAnalyzer
        project = _make_project(tmp_path, 'transform slide:\n    linear 1.0 xoffset 100\n')
        analyzer = SenpyAnalyzer(project)
        analyzer.run(quiet=True)
        assert "slide" in analyzer.transforms


class TestCollectLabel:
    """_collect_label — label name(params):."""

    def test_method_exists(self):
        from senpy.core.analyzer import SenpyAnalyzer
        assert hasattr(SenpyAnalyzer, "_collect_label")

    def test_label_creates_symbol(self, tmp_path):
        """label start: → LabelSymbol."""
        from senpy.core.analyzer import SenpyAnalyzer
        project = _make_project(tmp_path, 'label start:\n    return\n')
        analyzer = SenpyAnalyzer(project)
        analyzer.run(quiet=True)
        assert "start" in analyzer.labels
        assert analyzer.labels["start"].has_return is True


class TestCollectLabelBody:
    """_collect_label_body — jump/call/return + screen edges."""

    def test_method_exists(self):
        from senpy.core.analyzer import SenpyAnalyzer
        assert hasattr(SenpyAnalyzer, "_collect_label_body")


class TestCollectImages:
    """_collect_images — layeredimage + image."""

    def test_method_exists(self):
        from senpy.core.analyzer import SenpyAnalyzer
        assert hasattr(SenpyAnalyzer, "_collect_images")

    def test_image_creates_symbol(self, tmp_path):
        """image bg = "bg.png" → ImageSymbol."""
        from senpy.core.analyzer import SenpyAnalyzer
        project = _make_project(tmp_path, 'image bg = "bg.png"\n')
        analyzer = SenpyAnalyzer(project)
        analyzer.run(quiet=True)
        assert "bg" in analyzer.images


class TestCollectMisc:
    """_collect_misc — channels, dynamic jumps, init python."""

    def test_method_exists(self):
        from senpy.core.analyzer import SenpyAnalyzer
        assert hasattr(SenpyAnalyzer, "_collect_misc")


class TestCollectSymbolsRefactored:
    """Интеграционные тесты: _collect_symbols вызывает _collect_* методы."""

    def test_default_and_define(self, tmp_path):
        """_collect_symbols обрабатывает default + define."""
        from senpy.core.analyzer import SenpyAnalyzer
        project = _make_project(tmp_path, 'default x = 1\ndefine CONST = 42\n')
        analyzer = SenpyAnalyzer(project)
        analyzer.run(quiet=True)
        assert "x" in analyzer.variables
        assert "CONST" in analyzer.variables
        assert analyzer.variables["CONST"].is_constant is True

    def test_label_with_jump(self, tmp_path):
        """_collect_symbols обрабатывает label + jump."""
        from senpy.core.analyzer import SenpyAnalyzer
        project = _make_project(tmp_path, 'label start:\n    jump chapter2\nlabel chapter2:\n    return\n')
        analyzer = SenpyAnalyzer(project)
        analyzer.run(quiet=True)
        assert "start" in analyzer.labels
        assert "chapter2" in analyzer.labels
        assert "chapter2" in analyzer.labels["start"].outgoing_jumps

    def test_screen_with_use(self, tmp_path):
        """_collect_symbols обрабатывает screen + use."""
        from senpy.core.analyzer import SenpyAnalyzer
        project = _make_project(tmp_path, 'screen main():\n    use sub\nscreen sub():\n    pass\n')
        analyzer = SenpyAnalyzer(project)
        analyzer.run(quiet=True)
        assert "main" in analyzer.screens
        assert "sub" in analyzer.screens
        assert "sub" in analyzer.used_screens

    def test_image_declaration(self, tmp_path):
        """_collect_symbols обрабатывает image."""
        from senpy.core.analyzer import SenpyAnalyzer
        project = _make_project(tmp_path, 'image bg room = "room.png"\n')
        analyzer = SenpyAnalyzer(project)
        analyzer.run(quiet=True)
        assert "bg room" in analyzer.images

    def test_init_python_block(self, tmp_path):
        """_collect_symbols обрабатывает init python блок."""
        from senpy.core.analyzer import SenpyAnalyzer
        project = _make_project(tmp_path, 'init python:\n    def foo():\n        return 42\n')
        analyzer = SenpyAnalyzer(project)
        analyzer.run(quiet=True)
        assert "foo" in analyzer.declared_symbols
