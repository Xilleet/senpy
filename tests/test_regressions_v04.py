from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from senpy.analyzer import SenpyAnalyzer
from senpy.cli import main as cli_main


def run_analyzer(code: str, tmp_path: Path, filename: str = "script.rpy"):
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    target = game_dir / filename
    target.write_text(code, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)
    return result, analyzer


def test_regression_cli_auto_detects_traceback_without_flag(tmp_path: Path):
    """[Regression v0.4.1] Verify CLI handles existing traceback.txt without UnboundLocalError crash."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")

    traceback_content = """I'm sorry, but an uncaught exception occurred.
While running game code:
  File "game/un.rpy", line 5, in script
AttributeError: 'NoneType' object has no attribute 'something'
"""
    (tmp_path / "traceback.txt").write_text(traceback_content, encoding="utf-8")

    test_args = ["senpy", str(tmp_path)]
    with patch("sys.argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            cli_main()
        assert exc_info.value.code == 0


def test_regression_rpy109_builtins_and_dotted_defines(tmp_path: Path):
    """[Regression v0.4.1] Verify built-in transitions and dotted defines (config.xxx, gui.xxx) never trigger RPY109."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)

    (game_dir / "definitions.rpy").write_text(
        """
init python:
    config.window_hide_transition = dissolve
    config.window_show_transition = fade
    gui.init(1280, 720)
""",
        encoding="utf-8",
    )

    (game_dir / "screens.rpy").write_text(
        """
define config.has_quicksave = True
define gui.text_size = 30
screen main_menu():
    text "Menu"
""",
        encoding="utf-8",
    )

    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)

    rpy109_errors = [d for d in result.diagnostics if d.code == "RPY109"]
    # Ни config, ни gui, ни dissolve не должны вызывать RPY109
    assert len(rpy109_errors) == 0, f"False RPY109 detected: {[d.message for d in rpy109_errors]}"


def test_regression_object_model_integrity_across_subsystems(tmp_path: Path):
    """[Regression v0.4.0] Verify unified Symbol objects hold correct metadata across passes."""
    code = """
default player_gold = 500
define max_stamina = 100
define narrator_char = Character("Narrator")

label chapter_prologue(difficulty=1):
    jump chapter_one

label chapter_one:
    return
"""
    result, analyzer = run_analyzer(code, tmp_path)
    assert len([d for d in result.diagnostics if d.severity == "ERROR"]) == 0

    # Проверяем, что объекты в памяти держат правильные флаги
    gold_sym = analyzer.variables["player_gold"]
    assert gold_sym.is_constant is False
    assert gold_sym.is_character is False
    assert gold_sym.type_name == "int"

    stamina_sym = analyzer.variables["max_stamina"]
    assert stamina_sym.is_constant is True
    assert stamina_sym.is_character is False

    char_sym = analyzer.variables["narrator_char"]
    assert char_sym.is_character is True

    lbl_sym = analyzer.labels["chapter_prologue"]
    assert lbl_sym.signature is not None
    assert "difficulty" in lbl_sym.signature.all_names
    assert "chapter_one" in lbl_sym.outgoing_jumps
