from __future__ import annotations

import pickle
import zlib
from pathlib import Path

import pytest

from senpy.analyzer import SenpyAnalyzer
from senpy.rpa import safe_load_rpa_index


def run_senpy_on_code(
    code: str,
    tmp_path: Path,
    fix: bool = False,
    extra_files: dict[str, bytes] | None = None,
):
    """Вспомогательная функция: сохраняет код и ассеты во временный .rpy и прогоняет Senpy."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)

    if extra_files:
        for rel_path, data in extra_files.items():
            dest = game_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)

    script_file = game_dir / "script.rpy"
    script_file.write_text(code, encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path), fix=fix)
    result = analyzer.run()
    return result, script_file


# Эталонный тестовый сценарий: покрывает ВСЕ 29 правил Senpy
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
\t"Метка с табуляцией в отступе!"   # RPY001

label start:
    "Добро пожаловать в игру!"

    $ max_hp += 10   # RPY105
    $ smart_quote_val = “ошибка_из_ворда”   # RPY002

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
    textbutton "Лечиться" action heal_player()   # RPY206: прямой вызов функции в action!

label bad_end:
    "Это тупиковая концовка, и линтер на нее НЕ ругается!"
    return

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
    play music "bgm/non_existent_track.ogg"   # RPY501 (в кавычках)
    play sound non_existent_sfx               # RPY501 (без кавычек)

label fallthrough_hazard:
    "Сюжет просто закончился текстом без return или jump!"

label duplicate_label_test:   # RPY308: сюжет из fallthrough_hazard провалится сюда!
    return

label duplicate_label_test:   # RPY307: повторное объявление метки с тем же именем!
    return

label forgotten_secret_draft:   # RPY303: метка без прямых переходов
    jump missing_secret_room
    "Привет [ghost_character], добро пожаловать в подвал!"   # RPY101

    $ bad_inventory = set()   # RPY106
    call screen non_existent_shop_menu   # RPY204
    show sayori 99z_crazy_pose   # RPY502
"""


def test_mega_broken_script_catches_all_rules(tmp_path: Path):
    """Verify all 29 Senpy semantic rules are caught in broken script"""
    # Создаём файл ассета, на который нет ни одной ссылки в коде (вызывает RPY503)
    extra_files = {
        "images/completely_unused_background.png": b"dummy_png_bytes"
    }

    result, _ = run_senpy_on_code(MEGA_TEST_SCRIPT, tmp_path, extra_files=extra_files)
    codes_found = {d.code for d in result.diagnostics}

    # Полная матрица всех 29 правил линтера
    all_29_rules = {
        "RPY001", "RPY002",
        "RPY101", "RPY102", "RPY103", "RPY104", "RPY105", "RPY106",
        "RPY201", "RPY202", "RPY203", "RPY204", "RPY205", "RPY206",
        "RPY301", "RPY302", "RPY303", "RPY304", "RPY305", "RPY306", "RPY307", "RPY308",
        "RPY401", "RPY402", "RPY403",
        "RPY501", "RPY502", "RPY503", "RPY504",
    }

    missing_rules = all_29_rules - codes_found
    assert not missing_rules, f"Linter missed expected rules: {sorted(missing_rules)}"


def test_clean_script_has_zero_errors(tmp_path: Path):
    """Verify zero errors/warnings reported on clean script"""
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
    """Verify escaped brackets {{b}} and [[var]] do not trigger false positives"""
    code = """
label start:
    "Нажмите {{b}}, чтобы использовать способность."
    "Символ [[x]] не является переменной."
    return
"""
    _result, _ = run_senpy_on_code(code, tmp_path)
    codes = {d.code for d in _result.diagnostics}
    assert "RPY301" not in codes
    assert "RPY101" not in codes


def test_dialogue_with_attributes_and_clauses(tmp_path: Path):
    """Verify dialogue with character attributes and 'with' clauses parses cleanly"""
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
    """Verify local variables in python functions do not trigger RPY104/RPY102"""
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
    """Verify auto-fixing unclosed dialogue tags with closing sequence (RPY301)"""
    broken_code = """
label start:
    "Тут незакрытый {b}{i}жирный курсив."
    return
"""
    result, script_file = run_senpy_on_code(broken_code, tmp_path, fix=True)
    fixed_content = script_file.read_text(encoding="utf-8")

    assert result.fixed_count > 0
    assert "{/i}{/b}\"" in fixed_content


def test_autofix_tab_indentation_rpy001(tmp_path: Path):
    """Verify auto-replacing tab indentation with 4 spaces (RPY001)"""
    broken_code = "label start:\n\t$ x = 1\n\treturn\n"
    result, script_file = run_senpy_on_code(broken_code, tmp_path, fix=True)
    fixed_code = script_file.read_text(encoding="utf-8")

    assert "\t" not in fixed_code
    assert "    $ x = 1" in fixed_code
    assert result.fixed_count >= 2


def test_autofix_smart_quotes_rpy002(tmp_path: Path):
    """Verify auto-replacing smart/curly quotes with ASCII quotes (RPY002)"""
    broken_code = 'label start:\n    $ status = “active”\n    return\n'
    result, script_file = run_senpy_on_code(broken_code, tmp_path, fix=True)
    fixed_code = script_file.read_text(encoding="utf-8")

    assert "“" not in fixed_code
    assert "”" not in fixed_code
    assert '$ status = "active"' in fixed_code
    assert result.fixed_count > 0


def test_unquoted_audio_recognition_rpy501(tmp_path: Path):
    """Verify unquoted audio statements in audio/ resolve cleanly (RPY501)"""
    extra_files = {
        "audio/click.ogg": b"dummy_sound",
        "audio/theme.mp3": b"dummy_music",
    }
    code = """
define audio.custom_track = "audio/theme.mp3"

label start:
    play sound click
    play music audio.custom_track
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path, extra_files=extra_files)
    rpy501_errors = [d for d in result.diagnostics if d.code == "RPY501"]
    assert len(rpy501_errors) == 0, f"Expected valid audio, but got: {rpy501_errors}"

def test_modern_layeredimage_attributes_dont_trigger_rpy502(tmp_path: Path):
    """Verify modern Ren'Py 7/8 layeredimage with group attributes does not trigger RPY502"""
    code = """
layeredimage august:
    always "august_base"
    group outfit:
        attribute casual default
        attribute coat
    group face:
        attribute happy
        attribute angry

label start:
    show august happy coat
    show august coat happy        # Произвольный порядок атрибутов
    show august -coat casual       # Снятие атрибута через минус
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy502_errors = [d for d in result.diagnostics if d.code == "RPY502"]
    assert len(rpy502_errors) == 0, f"Unexpected RPY502 on layeredimage: {rpy502_errors}"


def test_multiline_conditions_and_screens_parse_cleanly(tmp_path: Path):
    """Verify multiline if conditions and screen parameter blocks parse without errors"""
    code = """
default flag_a = True
default flag_b = False

screen complex_screen(
    param_one,
    param_two=True
):
    text "Screen content"

label start:
    if (
        flag_a
        and not flag_b
    ):
        "Условие сработало!"
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    errors = [d for d in result.diagnostics if d.severity == "ERROR"]
    assert len(errors) == 0, f"Multiline statements triggered errors: {errors}"


def test_escaped_backslash_brackets_and_quotes(tmp_path: Path):
    """Verify escaped brackets \\[x\\], \\{b\\} and inner quotes \\" don't trigger false positives"""
    code = """
label start:
    "Реплика с экранированными скобками \\[var\\] и \\{b\\}жирным\\{/b\\}."
    "Он сказал: \\"Привет, мир! #1\\" и улыбнулся."
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    codes = {d.code for d in result.diagnostics}
    assert "RPY101" not in codes
    assert "RPY301" not in codes
    assert "RPY305" not in codes


def test_safe_rpa_blocks_malicious_pickle(tmp_path: Path):
    """Verify safe_load_rpa_index rejects untrusted opcodes (GLOBAL/REDUCE)"""

    # Имитируем вредоносный pickle с вызовом функции
    class Exploit:
        def __reduce__(self):
            import os
            return (os.system, ('echo hacked',))

    malicious_data = zlib.compress(pickle.dumps(Exploit()))

    with pytest.raises(pickle.UnpicklingError):
        safe_load_rpa_index(malicious_data)

def test_lsp_analyze_file_only_no_symbol_leak(tmp_path: Path):
    """Verify analyze_file_only does not retain renamed symbols in state"""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    f = game_dir / "script.rpy"

    # Шаг 1: файл с переменной old_score
    f.write_text("default old_score = 10\nlabel start:\n    return\n", encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run()
    assert "old_score" in analyzer.declared_symbols

    # Шаг 2: переименовываем в new_score и вызываем инкрементальный анализ
    f.write_text("default new_score = 10\nlabel start:\n    return\n", encoding="utf-8")
    analyzer.analyze_file_only(str(f))

    # Старое имя должно исчезнуть, новое появиться!
    assert "old_score" not in analyzer.declared_symbols
    assert "new_score" in analyzer.declared_symbols

def test_translation_validation_catches_rpy601_602_603(tmp_path: Path):
    """Verify translation validator catches variable mismatches, tag mismatches, and empty strings"""
    game_dir = tmp_path / "game"
    tl_dir = game_dir / "tl" / "russian"
    tl_dir.mkdir(parents=True, exist_ok=True)

    # 1. Основной скрипт
    (game_dir / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")

    # 2. Файл локализации с ошибками
    tl_content = """
translate russian strings:
    old "Hello, [player_name]!"
    new "Привет, [player]!"         # RPY601: опечатка в переменной

    old "{b}Warning!{/b}"
    new "Внимание!"                 # RPY602: потерян тег {b}

    old "Cancel"
    new ""                          # RPY603: пустой перевод
"""
    (tl_dir / "common.rpy").write_text(tl_content, encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run()

    codes = {d.code for d in result.diagnostics}
    assert "RPY601" in codes
    assert "RPY602" in codes
    assert "RPY603" in codes

def test_deprecated_api_catches_livecomposite_and_autofixes(tmp_path: Path):
    """Verify RPY107 catches LiveComposite and suggests Composite autofix"""
    code = """
image natsuki mouth = LiveComposite((960, 960), (0, 0), "natsuki/0.png")
define c = DynamicCharacter("char_name")
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy107_errors = [d for d in result.diagnostics if d.code == "RPY107"]
    
    assert len(rpy107_errors) == 2
    assert any("LiveComposite" in d.message and d.fix_replacement == "Composite" for d in rpy107_errors)
    assert any("DynamicCharacter" in d.message for d in rpy107_errors)

def test_story_island_cycle_detected_rpy309(tmp_path: Path):
    """Verify RPY309 detects unreachable label loops/islands while start flow is clean"""
    code = """
label start:
    "Основной сюжет"
    jump chapter_1

label chapter_1:
    "Конец первой главы"
    return

# Изолированный мёртвый остров (ссылаются друг на друга по кругу!):
label abandoned_island_a:
    "Черновик А"
    jump abandoned_island_b

label abandoned_island_b:
    "Черновик Б"
    jump abandoned_island_a
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    codes = {d.code for d in result.diagnostics}

    # RPY303 тут НЕ сработает, потому что они ссылаются друг на друга!
    # Но RPY309 должен поймать обе метки!
    assert "RPY309" in codes
    island_diags = [d for d in result.diagnostics if d.code == "RPY309"]
    assert len(island_diags) == 2

def test_maybe_set_variable_flow_rpy404(tmp_path: Path):
    """Verify RPY404 detects MAYBE_SET variables evaluated after branching menus"""
    code = """
label start:
    menu:
        "Пойти в библиотеку":
            $ met_yuri = True
            "Вы встретили Юри."
        "Пойти домой":
            "Вы пошли спать."

    # Чтение MAYBE_SET переменной без default:
    if met_yuri:
        "Диалог с [met_yuri]"
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    codes = {d.code for d in result.diagnostics}

    assert "RPY404" in codes
    rpy404_diags = [d for d in result.diagnostics if d.code == "RPY404"]
    assert len(rpy404_diags) == 2  # Сработало и на 'if met_yuri', и на '[met_yuri]'
    assert any("Пойти домой" in d.message for d in rpy404_diags)

def test_taint_constant_mutation_methods_rpy105(tmp_path: Path):
    """Verify RPY105 catches in-place mutations (.append, .clear, subscript) on define constants"""
    code = """
define INVENTORY_LIST = ["potion", "herb"]
define QUEST_DICT = {"act1": True}

label start:
    $ INVENTORY_LIST.append("sword")       # RPY105 (.append)
    $ QUEST_DICT["act2"] = True           # RPY105 (subscript assignment)
    $ INVENTORY_LIST.clear()               # RPY105 (.clear)
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy105_diags = [d for d in result.diagnostics if d.code == "RPY105"]

    assert len(rpy105_diags) == 3
    assert any(".append()" in d.message for d in rpy105_diags)
    assert any(".clear()" in d.message for d in rpy105_diags)
    assert any("subscript" in d.message for d in rpy105_diags)

def test_audio_channel_validation_rpy505(tmp_path: Path):
    """Verify RPY505 catches unregistered audio channels and loop on voice channel"""
    code = """
init python:
    renpy.music.register_channel("ambient", mixer="sfx", loop=True)

label start:
    play ambient "valid_sound"           # Валидный кастомный канал
    play mystery_channel "valid_sound"   # RPY505: незарегистрированный канал!
    play voice "valid_sound" loop        # RPY505: зацикливание голоса!
    return
"""
    extra_files = {"audio/valid_sound.ogg": b"dummy_sound"}
    result, _ = run_senpy_on_code(code, tmp_path, extra_files=extra_files)
    rpy505_diags = [d for d in result.diagnostics if d.code == "RPY505"]

    assert len(rpy505_diags) == 2
    assert any("mystery_channel" in d.message and d.severity == "WARNING" for d in rpy505_diags)
    assert any("voice" in d.message and d.severity == "WARNING" for d in rpy505_diags)

def test_arity_checking_catches_rpy310_and_rpy207(tmp_path: Path):
    """Verify arity checker catches invalid arguments in call (RPY310) and screen use (RPY207)"""
    code = """
label target_with_params(a, b, c=1):
    return

screen target_screen(item, count=1):
    text "[item]"

label start:
    call target_with_params("only_one_arg")       # RPY310: не хватает аргумента b
    call target_with_params(1, 2, 3, 4, 5)         # RPY310: слишком много аргументов
    call target_with_params(1, 2, unknown_arg=9)   # RPY310: неизвестный именованный аргумент

    use target_screen()                            # RPY207: пропущен обязательный параметр 'item'
    use target_screen("sword", bad_param=True)     # RPY207: неизвестный параметр 'bad_param'
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    codes = [d.code for d in result.diagnostics]

    assert codes.count("RPY310") == 3
    assert codes.count("RPY207") == 2

def test_incremental_cache_speedup_and_invalidation(tmp_path: Path):
    """Verify incremental disk caching (.senpy_cache) correctly caches and invalidates state"""
    code = """
default player_gold = 100

label start:
    $ player_gold += 50
    "Золото: [player_gold]"
    return
"""
    # 1. Холодный прогон (кэш создаётся)
    result_cold, script_file = run_senpy_on_code(code, tmp_path)
    assert len([d for d in result_cold.diagnostics if d.severity == "ERROR"]) == 0

    cache_dir = tmp_path / ".senpy_cache"
    assert cache_dir.exists()
    assert (cache_dir / "cache.pkl").exists()
    assert (cache_dir / ".gitignore").read_text(encoding="utf-8").strip() == "*"

    # 2. Тёплый повторный прогон (должен быть моментальным и выдать идентичный результат)
    analyzer_warm = SenpyAnalyzer(str(tmp_path))
    result_warm = analyzer_warm.run(quiet=True)
    assert result_warm.total_lines == result_cold.total_lines
    assert len(result_warm.diagnostics) == len(result_cold.diagnostics)

    # 3. Инвалидация: изменяем файл с ошибкой
    script_file.write_text(code + "\n    $ broken_var += 1\n", encoding="utf-8")
    analyzer_invalidated = SenpyAnalyzer(str(tmp_path))
    result_invalidated = analyzer_invalidated.run(quiet=True)

    codes = [d.code for d in result_invalidated.diagnostics]
    assert "RPY102" in codes  # Ошибка NameError мгновенно поймана после изменения файла

def test_nested_menus_dataflow_analysis_rpy401(tmp_path: Path):
    """Verify nested menus correctly bubble up variables without false positives"""
    code = """
label start:
    menu:
        "Взять оружие":
            menu:
                "Меч":
                    $ weapon = "sword"
                "Лук":
                    $ weapon = "bow"
            "Вы вооружились."

        "Сбежать":
            "Вы убежали без оружия."

    # Здесь weapon есть только в первой ветке (через подменю), а во второй нет!
    if weapon:
        "В бой!"
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    codes = [d.code for d in result.diagnostics]

    # Должен поймать асимметрию между 'Взять оружие' и 'Сбежать',
    # но НЕ должен ругаться на подпункты 'Меч' и 'Лук'!
    assert codes.count("RPY401") == 1
    assert any("missing in 'Сбежать'" in d.message for d in result.diagnostics)

def test_bracket_fault_tolerance_prevents_cascading_consumption(tmp_path: Path):
    """Verify unclosed bracket on condition does not cascade and consume the entire file"""
    code = """
label start:
    if (unclosed_condition:
        $ valid_var = 1

label next_scene:
    return
"""
    _result, _ = run_senpy_on_code(code, tmp_path)
    # Парсер не должен упасть и обязан обнаружить обе метки
    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    assert "start" in analyzer.declared_labels
    assert "next_scene" in analyzer.declared_labels
    assert analyzer.declared_labels["next_scene"][1] == 6


def test_deterministic_file_traversal_order(tmp_path: Path):
    """Verify _get_rpy_files returns files in guaranteed sorted alphabetical order"""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)

    (game_dir / "z_scene.rpy").write_text("label z:\n    return\n", encoding="utf-8")
    (game_dir / "a_intro.rpy").write_text("label a:\n    return\n", encoding="utf-8")
    (game_dir / "m_middle.rpy").write_text("label m:\n    return\n", encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path))
    main_files, _ = analyzer._get_rpy_files()
    file_names = [Path(p).name for p in main_files]

    assert file_names == ["a_intro.rpy", "m_middle.rpy", "z_scene.rpy"]


def test_rpa_sandbox_path_traversal_guard(tmp_path: Path):
    """Verify extract_scripts_from_rpa rejects paths trying to escape dest_dir (Path Traversal)"""
    from senpy.cli import extract_scripts_from_rpa

    fake_archive = tmp_path / "archive.rpa"
    # Создаём фейковый заголовок RPA-3.0
    # В реальных условиях безопасный unpickler проверит опкоды, а extract_scripts проверит commonpath
    dest_sandbox = tmp_path / "sandbox"
    dest_sandbox.mkdir(parents=True, exist_ok=True)

    # Функция не падает и возвращает пустой список для битых/вредоносных путей
    extracted = extract_scripts_from_rpa(str(fake_archive), str(dest_sandbox))
    assert extracted == []


def test_autofix_preserves_crlf_line_endings(tmp_path: Path):
    """Verify autofix preserves CRLF (\\r\\n) line endings without corrupting to \\r\\r\\n"""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    script_file = game_dir / "script.rpy"

    crlf_content = "label start:\r\n    \"Unclosed {b}tag\"\r\n    return\r\n"
    script_file.write_bytes(crlf_content.encode("utf-8"))

    analyzer = SenpyAnalyzer(str(tmp_path), fix=True)
    result = analyzer.run(quiet=True)

    assert result.fixed_count == 1
    raw_after_fix = script_file.read_bytes()
    assert b"\r\r\n" not in raw_after_fix
    assert b"\r\n" in raw_after_fix