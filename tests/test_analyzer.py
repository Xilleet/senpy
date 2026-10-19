import os
from pathlib import Path

import pytest

from senpy.analyzer import SenpyAnalyzer


def run_senpy_on_code(code: str, tmp_path: Path, fix: bool = False):
    """Вспомогательная функция: сохраняет код во временный .rpy и прогоняет Senpy."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(exist_ok=True)
    script_file = game_dir / "script.rpy"
    script_file.write_text(code, encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path), fix=fix)
    result = analyzer.run()
    return result, script_file


# Эталонный тестовый сценарий: покрывает ВСЕ 23 правила Senpy
MEGA_TEST_SCRIPT = """
init python:
    def calculate_bonus(x):
        return x * 2

    import random   # RPY106

image bg room = "room_day.png"
image bg room = "room_night.png"   # RPY504

default friend_name = "Дима"
define max_hp = 100

label infinite_scene:
    "Эта метка объявлена, но забыли поставить return!"

label start:
    "Добро пожаловать в игру!"

    $ max_hp += 10   # RPY105

    python:
        unregistered_var = 100   # RPY104
        magic_points += 5        # RPY102

    call infinite_scene   # RPY306: метка есть, но возврата нет!

    # RPY103: переменная без объявления в сюжетном условии
    if quest_unlocked_secret:
        "Секретный квест"

    # RPY403: заведомо ложное условие
    if False:
        "Этот блок никогда не выполнится"

    # RPY305: неэкранированные кавычки в реплике
    "Она сказала "Привет" и ушла."

default player_gold = 100

screen shop():
    $ player_gold -= 10   # RPY201

    python:
        for i in range(10):   # RPY205
            pass

    if special_discount_active:   # RPY202
        text "Скидка активна!"

    textbutton "Купить меч"   # RPY203

label bad_end:
    "Это тупиковая концовка, и линтер на нее НЕ ругается!"

label chapter_two:
    "Внимание: {b}опасная зона!"   # RPY301
    jump bad_edd   # RPY302

$ player_gold -= 10 

label test_flow:
    menu:
        "Взять факел":
            $ has_torch = True
            "Вы берете факел."

        "Идти в темноте":
            "Вы идете наощупь."

        "Сдаться и лечь спать":   # RPY402

    if has_torch:   # RPY401
        "Свет факела разгоняет тьму."

label test_new_rules:
    "Этот текст покрашен {color=#12345}странным цветом{/color}."   # RPY304
    play music "bgm/non_existent_track.ogg"   # RPY501

label forgotten_secret_draft:   # RPY303: метка без прямых переходов
    jump missing_secret_room
    "Привет [ghost_character], добро пожаловать в подвал!"   # RPY101

    $ bad_inventory = set()   # RPY106
    call screen non_existent_shop_menu   # RPY204
    show sayori 99z_crazy_pose   # RPY502
"""


def test_mega_broken_script_catches_all_rules(tmp_path: Path):
    """Проверяем, что эталонный скрипт с ошибками ловит ВСЕ 23 правила Senpy."""
    result, _ = run_senpy_on_code(MEGA_TEST_SCRIPT, tmp_path)
    codes_found = {d.code for d in result.diagnostics}

    # Полная матрица всех 23 правил линтера
    all_23_rules = {
        "RPY101", "RPY102", "RPY103", "RPY104", "RPY105", "RPY106",
        "RPY201", "RPY202", "RPY203", "RPY204", "RPY205",
        "RPY301", "RPY302", "RPY303", "RPY304", "RPY305", "RPY306",
        "RPY401", "RPY402", "RPY403",
        "RPY501", "RPY502", "RPY504",
    }

    missing_rules = all_23_rules - codes_found
    assert not missing_rules, f"Linter missed expected rules: {missing_rules}"


def test_clean_script_has_zero_errors(tmp_path: Path):
    """Идеальный сценарий не должен выдавать ошибок."""
    clean_code = """
default player_gold = 100
define MAX_LEVEL = 50

label start:
    $ player_gold += 50
    "У вас [player_gold] золота."
    return
"""
    result, _ = run_senpy_on_code(clean_code, tmp_path)
    errors_and_warnings = [d for d in result.diagnostics if d.severity in ("ERROR", "WARNING")]
    assert len(errors_and_warnings) == 0, f"Unexpected diagnostics: {errors_and_warnings}"


def test_escaped_brackets_dont_trigger_rpy301_or_rpy101(tmp_path: Path):
    """Проверяем исправление экранирования: {{b}} и [[var]] не должны ломать парсер."""
    code = """
label start:
    "Нажмите {{b}}, чтобы использовать способность."
    "Символ [[x]] не является переменной."
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    codes = {d.code for d in result.diagnostics}
    assert "RPY301" not in codes
    assert "RPY101" not in codes


def test_dialogue_with_attributes_and_clauses(tmp_path: Path):
    """Проверяем реплики с эмоциями (eileen happy '...') и фразами 'with dissolve'."""
    code = """
define e = Character("Эйлин")

label start:
    e happy glasses "Привет, игрок!" with dissolve
    "За кадром" "Всё спокойно."
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    assert len(result.diagnostics) == 0


def test_local_variables_in_python_def_dont_trigger_rpy104(tmp_path: Path):
    """Локальные переменные функций и циклов внутри python: не требуют default."""
    code = """
label start:
    python:
        def compute_sum(items):
            total = 0
            for item in items:
                total += item
            return total
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    codes = {d.code for d in result.diagnostics}
    assert "RPY104" not in codes
    assert "RPY102" not in codes


def test_autofix_unclosed_tags(tmp_path: Path):
    """Проверяем автофикс незакрытых тегов RPY301 (параметр --fix)."""
    broken_code = """
label start:
    "Тут незакрытый {b}{i}жирный курсив."
    return
"""
    result, script_file = run_senpy_on_code(broken_code, tmp_path, fix=True)
    fixed_content = script_file.read_text(encoding="utf-8")

    assert result.fixed_count > 0
    assert "{/i}{/b}\"" in fixed_content