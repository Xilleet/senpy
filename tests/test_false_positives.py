from __future__ import annotations

from pathlib import Path

from senpy.analyzer import SenpyAnalyzer


def run_senpy_on_code(code: str, tmp_path: Path):
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    script_file = game_dir / "script.rpy"
    script_file.write_text(code, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)
    return result


def test_fp_atl_transforms_and_transitions(tmp_path: Path):
    """Verify ATL blocks and complex transitions do not trigger false variables or loops"""
    code = """
image sayori 1a = "sayori.png"

transform pulse_effect(delay=0.5):
    alpha 0.0
    linear delay alpha 1.0
    pause delay
    repeat

label start:
    show sayori 1a at pulse_effect(0.2) with dissolve
    return
"""
    result = run_senpy_on_code(code, tmp_path)
    # Трансформы содержат ключевые слова (alpha, linear, pause). 
    # Линтер не должен считать их необъявленными переменными!
    assert len(result.diagnostics) == 0


def test_fp_complex_screen_actions_and_lists(tmp_path: Path):
    """Verify multiple actions in lists and hovered/unhovered events pass cleanly"""
    code = """
default is_hovered = False
default money = 100

screen complex_ui():
    textbutton "Click Me":
        # Список экшенов: не должно срабатывать RPY206 (вызов функции)
        action [SetVariable("money", money + 10), Return()]
        # Hovered экшены: не должно срабатывать RPY201 (мутация)
        hovered SetVariable("is_hovered", True)
        unhovered SetVariable("is_hovered", False)

label start:
    call screen complex_ui
    return
"""
    result = run_senpy_on_code(code, tmp_path)
    assert len(result.diagnostics) == 0


def test_fp_python_comprehensions_and_generators(tmp_path: Path):
    """Verify Python list/dict comprehensions do not leak uninitialized variable warnings"""
    code = """
default my_list = []
default my_dict = {}
default a = 0
default b = 0

label start:
    python:
        # Переменные 'x', 'k', 'v' существуют только внутри генераторов.
        # Линтер не должен орать, что они используются без объявления (RPY103/RPY102).
        my_list = [x * 2 for x in range(10) if x % 2 == 0]
        my_dict = {k: v for k, v in enumerate(my_list)}
        
        # Безопасное присваивание кортежей:
        a, b = (1, 2)
    return
"""
    result = run_senpy_on_code(code, tmp_path)
    assert len(result.diagnostics) == 0


def test_fp_advanced_dialogue_formatting(tmp_path: Path):
    """Verify string interpolations with modifiers (!t, !u, :.2f) do not trigger RPY101"""
    code = """
default player_name = "Eileen"
default score = 95.567

label start:
    # Сложное форматирование: перевод (!t), верхний регистр (!u), округление (:.1f)
    "Name translated: [player_name!t]"
    "Name uppercase: [player_name!u]"
    "Score rounded: [score:.1f]"
    return
"""
    result = run_senpy_on_code(code, tmp_path)
    # Линтер должен корректно отсечь суффиксы и проверить только базовые имена 'player_name' и 'score'
    assert len(result.diagnostics) == 0


def test_fp_ignore_noqa_comments(tmp_path: Path):
    """Verify # noqa comments correctly suppress targeted warnings"""
    code = """
label start:
    $ bad_var += 1      # noqa: RPY102
    "Unclosed {b}tag"   # senpy: ignore[RPY301]
    return
"""
    result = run_senpy_on_code(code, tmp_path)
    # Ошибки есть, но они подавлены через noqa, значит результат должен быть пуст!
    assert len(result.diagnostics) == 0