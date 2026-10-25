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
    assert "start" in analyzer.labels
    assert "next_scene" in analyzer.labels
    assert analyzer.labels["next_scene"].line_number == 6


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

def test_type_tainting_catches_rpy108(tmp_path: Path):
    """Verify RPY108 catches incompatible augmented assignment and type taint overwrites"""
    code = """
default player_name = "Eileen"
default score = 100

label start:
    $ player_name += 1       # RPY108 [ERROR]: str += int -> fatal TypeError
    $ score = "MAX"          # RPY108 [WARNING]: int = str -> type taint overwrite
    $ valid_score = score + 5
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy108_diags = [d for d in result.diagnostics if d.code == "RPY108"]

    # Стандарт 6.1: точное количество, строки, сообщения и строгость
    assert len(rpy108_diags) == 2

    # 1. Фатальный TypeError при +=
    d_fatal = next(d for d in rpy108_diags if d.severity == "ERROR")
    assert d_fatal.line_number == 6
    assert "player_name" in d_fatal.message
    assert "type 'str'" in d_fatal.message
    assert "type 'int'" in d_fatal.message

    # 2. Несовместимое присваивание
    d_warn = next(d for d in rpy108_diags if d.severity == "WARNING")
    assert d_warn.line_number == 7
    assert "score" in d_warn.message
    assert "incompatible type 'str'" in d_warn.message

    # Negative case: валидный код даёт 0 ошибок RPY108
    clean_code = """
default player_name = "Eileen"
default score = 100

label start:
    $ player_name += " Doe"
    $ score += 50
    $ score = 200
    return
"""
    clean_result, _ = run_senpy_on_code(clean_code, tmp_path / "clean_proj")
    clean_rpy108 = [d for d in clean_result.diagnostics if d.code == "RPY108"]
    assert len(clean_rpy108) == 0

def test_init_dependency_graph_rpy109(tmp_path: Path):
    """Verify RPY109 catches functions called before they are loaded alphabetically"""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)

    # a_setup.rpy пытается вызвать функцию из z_utils.rpy
    a_code = """
init python:
    # Исполняется сразу при загрузке:
    setup_gui()
"""
    # z_utils.rpy загружается позже
    z_code = """
init python:
    def setup_gui():
        pass
"""
    (game_dir / "a_setup.rpy").write_text(a_code, encoding="utf-8")
    (game_dir / "z_utils.rpy").write_text(z_code, encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)
    
    rpy109_diags = [d for d in result.diagnostics if d.code == "RPY109"]
    
    # 1. Поймали ошибку в a_setup.rpy
    assert len(rpy109_diags) == 1
    diag = rpy109_diags[0]
    assert "a_setup.rpy" in diag.file_path
    assert "setup_gui" in diag.message
    assert "z_utils.rpy" in diag.message
    assert diag.severity == "ERROR"
    assert diag.line_number == 4

    # Negative case: переименовываем файлы в правильном порядке
    (game_dir / "a_setup.rpy").unlink()
    (game_dir / "z_utils.rpy").unlink()
    (game_dir / "m_utils.rpy").write_text(z_code, encoding="utf-8")
    (game_dir / "z_setup.rpy").write_text(a_code, encoding="utf-8")

    clean_analyzer = SenpyAnalyzer(str(tmp_path))
    clean_result = clean_analyzer.run(quiet=True)
    assert not any(d.code == "RPY109" for d in clean_result.diagnostics)

def test_init_ci_generates_workflow_file(tmp_path: Path):
    """Verify --init-ci generates a valid .github/workflows/senpy.yml workflow"""
    from senpy.ci import init_ci_workflow

    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)

    workflow_path, created = init_ci_workflow(str(game_dir))
    assert created is True

    wf_file = Path(workflow_path)
    assert wf_file.exists()
    assert wf_file.name == "senpy.yml"
    assert wf_file.parent.name == "workflows"
    assert wf_file.parent.parent.name == ".github"

    content = wf_file.read_text(encoding="utf-8")
    assert "upload-sarif@v3" in content
    assert "security-events: write" in content
    assert "senpy game/ --format sarif" in content

def test_translation_coverage_calculation(tmp_path: Path):
    """Verify --coverage accurately computes translation progress percentages across languages"""
    from senpy.coverage import calculate_translation_coverage

    game_dir = tmp_path / "game"
    tl_ru = game_dir / "tl" / "russian"
    tl_es = game_dir / "tl" / "spanish"
    tl_ru.mkdir(parents=True, exist_ok=True)
    tl_es.mkdir(parents=True, exist_ok=True)

    # Русский: 3 строки, 2 переведено, 1 пустая (66.7%)
    ru_script = """
translate russian strings:
    old "Start"
    new "Начать"

    old "Quit"
    new "Выход"

    old "Options"
    new ""
"""
    # Испанский: 2 строки, 2 переведено (100.0%)
    es_script = """
translate spanish strings:
    old "Start"
    new "Iniciar"

    old "Quit"
    new "Salir"
"""
    (tl_ru / "common.rpy").write_text(ru_script, encoding="utf-8")
    (tl_es / "common.rpy").write_text(es_script, encoding="utf-8")

    stats = calculate_translation_coverage(str(tmp_path))

    assert "russian" in stats
    assert "spanish" in stats

    assert stats["russian"].total_strings == 3
    assert stats["russian"].translated_strings == 2
    assert stats["russian"].empty_strings == 1
    assert stats["russian"].coverage_percent == 66.7

    assert stats["spanish"].total_strings == 2
    assert stats["spanish"].translated_strings == 2
    assert stats["spanish"].empty_strings == 0
    assert stats["spanish"].coverage_percent == 100.0

def test_export_wiki_generation(tmp_path: Path):
    """Verify --export-wiki extracts characters, typed variables, and terminal endings"""
    from senpy.wiki import generate_project_wiki

    code = """
define e = Character("Eileen")
default player_gold = 100
define MAX_HP = 50

label start:
    $ player_gold += 10
    jump good_end

label good_end:
    "Победа!"
    return
"""
    _result, _script_file = run_senpy_on_code(code, tmp_path)
    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)

    wiki_content = generate_project_wiki(analyzer)

    # 1. Проверяем персонажей
    assert "## Characters" in wiki_content
    assert "`e`" in wiki_content

    # 2. Проверяем переменные и их типы
    assert "## State & Variables" in wiki_content
    assert "`player_gold`" in wiki_content
    assert "`int`" in wiki_content
    assert "`MAX_HP`" in wiki_content

    # 3. Проверяем концовку
    assert "## Story Endings" in wiki_content
    assert "`good_end`" in wiki_content

def test_generate_stubs_creates_valid_pyi_files(tmp_path: Path):
    """Verify --generate-stubs creates store.pyi and renpy.pyi with accurate types"""
    from senpy.stubs import generate_stubs

    code = """
default player_gold = 100
default player_name = "Eileen"
default is_quest_active = False

label start:
    return
"""
    _result, _script_file = run_senpy_on_code(code, tmp_path)
    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)

    out_dir, count = generate_stubs(analyzer, out_dir="custom_typings")
    stubs_path = Path(out_dir)

    assert stubs_path.exists()
    assert count >= 3

    # 1. Проверяем renpy.pyi
    renpy_pyi = (stubs_path / "renpy.pyi").read_text(encoding="utf-8")
    assert "def jump(label: str)" in renpy_pyi
    assert "class _Music:" in renpy_pyi

    # 2. Проверяем типизированный store.pyi
    store_pyi = (stubs_path / "store.pyi").read_text(encoding="utf-8")
    assert "player_gold: int" in store_pyi
    assert "player_name: str" in store_pyi
    assert "is_quest_active: bool" in store_pyi
    assert "persistent: Any" in store_pyi

def test_traceback_inspector_parses_crash_log(tmp_path: Path):
    """Verify Traceback Inspector parses traceback.txt and maps runtime crashes to Senpy rules"""
    from senpy.traceback import parse_traceback_file

    fake_traceback = """
I'm sorry, but an uncaught exception occurred.

While running game code:
  File "game/script.rpy", line 42, in script
    $ player_gold += 10
NameError: name 'player_gold' is not defined

-- Full Traceback ------------------------------------------------------------
...
"""
    tb_file = tmp_path / "traceback.txt"
    tb_file.write_text(fake_traceback, encoding="utf-8")

    crash = parse_traceback_file(str(tb_file))
    assert crash is not None
    assert crash.file_path == "game/script.rpy"
    assert crash.line_number == 42
    assert crash.exception_type == "NameError"
    assert "player_gold" in crash.exception_message
    assert crash.rule_code == "RPY104"
    assert "default player_gold = ..." in crash.explanation

def test_signature_missing_required_keyword_arg(tmp_path: Path):
    """Verify validate_call_arguments catches missing positional argument even if optional kwarg is passed"""
    code = """
label quest(item, count=1):
    return

label start:
    call quest(count=5)  # Missing required 'item'!
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy310 = [d for d in result.diagnostics if d.code == "RPY310"]
    assert len(rpy310) == 1
    assert "missing required argument 'item'" in rpy310[0].message
    assert rpy310[0].line_number == 6


def test_label_parameters_do_not_leak_into_global_scope(tmp_path: Path):
    """Verify parameters of one label do not leak into global symbols for other labels"""
    code = """
label battle(target_enemy, power=10):
    if target_enemy:
        "Атака!"
    return

label explore:
    if target_enemy:  # RPY103: переменная не объявлена в этой метке!
        "Враг найден!"
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy103 = [d for d in result.diagnostics if d.code == "RPY103"]
    assert len(rpy103) == 1
    assert "target_enemy" in rpy103[0].message
    assert rpy103[0].line_number == 8


def test_call_screen_does_not_create_dummy_jump_target(tmp_path: Path):
    """Verify 'call screen' does not register a jump to a label named 'screen'"""
    code = """
screen test_scr():
    text "Hello"

label start:
    call screen test_scr
    return
"""
    _result, _ = run_senpy_on_code(code, tmp_path)
    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    assert "screen" not in analyzer.labels["start"].outgoing_jumps


def test_rules_database_completeness():
    """Verify RULES_DATABASE contains all 40 rules declared in RULE_SEVERITY"""
    from senpy.models import RULE_SEVERITY
    from senpy.rules_info import RULES_DATABASE
    missing = set(RULE_SEVERITY.keys()) - set(RULES_DATABASE.keys())
    assert not missing, f"RULES_DATABASE is missing rules: {missing}"
    assert len(RULES_DATABASE) == 40

def test_if_branch_flow_sensitive_uninitialized_variable(tmp_path: Path):
    """Verify RPY404 detects variables defined only in 'if' branch without 'else'"""
    code = """
label start:
    if quest_started:
        $ secret_code = 1234

    if secret_code == 1234:
        "Код введен: [secret_code]"
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy404_diags = [d for d in result.diagnostics if d.code == "RPY404"]

    # Должно поймать дважды: в условии (line 6) и в реплике (line 7)
    assert len(rpy404_diags) == 2
    assert any(d.line_number == 6 and "secret_code" in d.message and "condition is False" in d.message for d in rpy404_diags)
    assert any(d.line_number == 7 and "[secret_code]" in d.message and "condition is False" in d.message for d in rpy404_diags)


def test_if_else_asymmetry_flow_sensitive(tmp_path: Path):
    """Verify RPY404 detects variable defined in 'if' but missing in 'else'"""
    code = """
label start:
    if quest_started:
        $ secret_token = "ABC"
    else:
        $ dummy = 1

    if secret_token:
        "Успех"
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy404_diags = [d for d in result.diagnostics if d.code == "RPY404"]
    assert len(rpy404_diags) == 1
    assert rpy404_diags[0].line_number == 8
    assert "secret_token" in rpy404_diags[0].message
    assert "else branch was taken" in rpy404_diags[0].message


def test_if_else_both_branches_define_variable_is_safe(tmp_path: Path):
    """Verify zero RPY404 when variable is assigned in both 'if' and 'else' branches"""
    code = """
label start:
    if quest_started:
        $ secret_token = "ABC"
    else:
        $ secret_token = "DEF"

    if secret_token == "ABC":
        "Успех: [secret_token]"
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy404_diags = [d for d in result.diagnostics if d.code == "RPY404"]
    assert len(rpy404_diags) == 0


def test_if_branch_variable_with_default_is_safe(tmp_path: Path):
    """Verify variable declared via top-level 'default' never triggers RPY404 in 'if'"""
    code = """
default secret_token = "DEFAULT"

label start:
    if quest_started:
        $ secret_token = "ABC"

    if secret_token == "ABC":
        "Токен: [secret_token]"
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy404_diags = [d for d in result.diagnostics if d.code == "RPY404"]
    assert len(rpy404_diags) == 0


def test_incompatible_method_calls_on_known_types_rpy108(tmp_path: Path):
    """Verify RPY108 catches calling invalid methods on known collection types (list.add, dict.append, str.pop)."""
    code = """
default inventory = ["potion"]
default quest_flags = {"started": True}
default player_name = "Eileen"

label start:
    # 1. Позитивные случаи (ошибки):
    $ inventory.add("sword")          # Ошибка: у list нет .add(), нужен .append() (line 8)
    $ quest_flags.append("finished")  # Ошибка: у dict нет .append(), нужен .update() (line 9)
    $ player_name.pop()               # Ошибка: у str нет .pop() (line 10)

    # 2. Негативные случаи (валидный код - 0 ошибок):
    $ inventory.append("shield")
    $ inventory.extend(["herb"])
    $ quest_flags.update({"act1": True})
    $ quest_flags.get("started")
    $ clean_name = player_name.upper()
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy108_diags = [d for d in result.diagnostics if d.code == "RPY108" and "AttributeError" in d.message]

    # Ровно 3 ошибки, точные строки 8, 9, 10, уровень ERROR
    assert len(rpy108_diags) == 3, f"Expected 3 method call diagnostics, got: {rpy108_diags}"

    # Проверка 1: inventory.add -> подсказка append
    d_list = next(d for d in rpy108_diags if d.line_number == 8)
    assert d_list.severity == "ERROR"
    assert "inventory" in d_list.message
    assert "list" in d_list.message
    assert ".add()" in d_list.message
    assert ".append()" in d_list.message

    # Проверка 2: quest_flags.append
    d_dict = next(d for d in rpy108_diags if d.line_number == 9)
    assert d_dict.severity == "ERROR"
    assert "quest_flags" in d_dict.message
    assert "dict" in d_dict.message
    assert ".append()" in d_dict.message

    # Проверка 3: player_name.pop
    d_str = next(d for d in rpy108_diags if d.line_number == 10)
    assert d_str.severity == "ERROR"
    assert "player_name" in d_str.message
    assert "str" in d_str.message
    assert ".pop()" in d_str.message


def test_unresolved_transform_in_show_at_rpy502(tmp_path: Path):
    """Verify RPY502 catches typos and unresolved transforms/positions in 'show ... at' clauses."""
    code = """
image sayori 1a = "sayori_1a.png"

transform custom_bounce:
    yoffset 0
    easein 0.2 yoffset -20
    easeout 0.2 yoffset 0

label start:
    # 1. Позитивные случаи (ошибки):
    show sayori 1a at cneter                # Опечатка в позиции 'center' (line 11)
    show sayori at missing_transform        # Необъявленный трансформ (line 12)
    show sayori at missing_anim(0.5)        # Необъявленный трансформ с параметрами (line 13)

    # 2. Негативные случаи (валидный код - 0 ошибок):
    show sayori 1a at center
    show sayori 1a at left, custom_bounce with dissolve
    show sayori at truecenter
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    transform_diags = [d for d in result.diagnostics if d.code == "RPY502" and "Transform" in d.message]

    # Ожидаем ровно 3 диагностики на строках 11, 12, 13
    assert len(transform_diags) == 3, f"Expected 3 transform diagnostics, got: {transform_diags}"

    # Ошибка 1: опечатка в center с подсказкой и автофиксом
    d_typo = next(d for d in transform_diags if d.line_number == 11)
    assert "cneter" in d_typo.message
    assert "center" in d_typo.message
    assert d_typo.fix_replacement == "center"

    # Ошибка 2: отсутствующий трансформ
    d_missing = next(d for d in transform_diags if d.line_number == 12)
    assert "missing_transform" in d_missing.message

    # Ошибка 3: отсутствующий трансформ с аргументами
    d_param = next(d for d in transform_diags if d.line_number == 13)
    assert "missing_anim" in d_param.message


def test_unresolved_transition_in_with_clause_rpy502(tmp_path: Path):
    """Verify RPY502 catches typos and unresolved transitions in 'with' clauses."""
    code = """
image sayori 1a = "sayori_1a.png"
define custom_fade = Fade(0.5, 0.0, 0.5)

label start:
    # 1. Позитивные случаи (ошибки):
    show sayori 1a with disolve            # Опечатка в 'dissolve' (line 8)
    with fdae                              # Опечатка в 'fade' на отдельной строке (line 9)
    with missing_transition                # Несуществующий переход (line 10)
    show sayori with missing_wipe(0.5)     # Несуществующий переход с аргументами (line 11)

    # 2. Негативные случаи (валидный код - 0 ошибок):
    show sayori 1a with dissolve
    with fade
    with None
    with custom_fade
    with Dissolve(1.0)
    "Диалог с переходом" with dissolve
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    transition_diags = [d for d in result.diagnostics if d.code == "RPY502" and "Transition" in d.message]

    # Ожидаем ровно 4 диагностики на строках 7, 8, 9, 10
    assert len(transition_diags) == 4, f"Expected 4 transition diagnostics, got: {transition_diags}"

    # Ошибка 1: опечатка в dissolve (строка 7)
    d_dissolve = next(d for d in transition_diags if d.line_number == 7)
    assert "disolve" in d_dissolve.message
    assert "dissolve" in d_dissolve.message
    assert d_dissolve.fix_replacement == "dissolve"

    # Ошибка 2: опечатка в fade (строка 8)
    d_fade = next(d for d in transition_diags if d.line_number == 8)
    assert "fdae" in d_fade.message
    assert "fade" in d_fade.message
    assert d_fade.fix_replacement == "fade"

    # Ошибка 3: отсутствующий переход (строка 9)
    d_missing = next(d for d in transition_diags if d.line_number == 9)
    assert "missing_transition" in d_missing.message

    # Ошибка 4: отсутствующий переход с параметрами (строка 10)
    d_param = next(d for d in transition_diags if d.line_number == 10)
    assert "missing_wipe" in d_param.message

def test_screen_action_setvariable_undeclared_rpy202(tmp_path: Path):
    """Verify RPY202 catches undeclared variables in SetVariable and ToggleVariable screen actions."""
    code = """
default player_gold = 100
default sound_muted = False

screen shop():
    # 1. Позитивные случаи (ошибки / опечатки):
    textbutton "Buy" action SetVariable("plater_gold", 50)     # Опечатка в player_gold (строка 7)
    textbutton "Mute" action ToggleVariable("snd_muted")       # Опечатка в sound_muted (строка 8)

    # 2. Негативные случаи (валидный код - 0 ошибок):
    textbutton "Legit Buy" action SetVariable("player_gold", 90)
    textbutton "Legit Mute" action ToggleVariable("sound_muted")
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy202_diags = [d for d in result.diagnostics if d.code == "RPY202" and "action references" in d.message]

    # Ожидаем ровно 2 диагностики на строках 7 и 8
    assert len(rpy202_diags) == 2, f"Expected 2 RPY202 action diagnostics, got: {rpy202_diags}"

    d_gold = next(d for d in rpy202_diags if d.line_number == 7)
    assert "plater_gold" in d_gold.message
    assert "player_gold" in d_gold.message

    d_sound = next(d for d in rpy202_diags if d.line_number == 8)
    assert "snd_muted" in d_sound.message
    assert "sound_muted" in d_sound.message


def test_screen_action_show_non_existent_screen_rpy204(tmp_path: Path):
    """Verify RPY204 catches non-existent screens referenced in Show/ShowMenu/Hide actions."""
    code = """
screen inventory_hud():
    text "Inventory"

screen main_ui():
    # 1. Позитивные случаи (ошибки / опечатки):
    textbutton "Open" action Show("inventroy_hud")          # Опечатка в inventory_hud (строка 7)
    textbutton "Custom" action ShowMenu("ghost_menu")       # Несуществующий экран (строка 8)

    # 2. Негативные случаи (валидный код - 0 ошибок):
    textbutton "Legit" action Show("inventory_hud")
    textbutton "Save" action ShowMenu("save")
    textbutton "Close" action Hide()
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy204_action_diags = [d for d in result.diagnostics if d.code == "RPY204" and "action" in d.message]

    # Ожидаем ровно 2 диагностики на строках 7 и 8
    assert len(rpy204_action_diags) == 2, f"Expected 2 RPY204 action diagnostics, got: {rpy204_action_diags}"

    # Ошибка 1: опечатка в inventory_hud с подсказкой и заменой
    d_typo = next(d for d in rpy204_action_diags if d.line_number == 7)
    assert "inventroy_hud" in d_typo.message
    assert "inventory_hud" in d_typo.message
    assert d_typo.fix_replacement == "inventory_hud"

    # Ошибка 2: несуществующий экран в ShowMenu
    d_missing = next(d for d in rpy204_action_diags if d.line_number == 8)
    assert "ghost_menu" in d_missing.message


def test_conflict_define_and_default_declaration_rpy105(tmp_path: Path):
    """Verify RPY105 catches variables declared with both 'define' and 'default'."""
    code = """
# 1. Позитивные случаи (конфликты объявлений):
define karma = 0
default karma = 0       # Ошибка: karma уже объявлена через define! (line 4)

default affection = 10
define affection = 10   # Ошибка: affection уже объявлена через default! (line 7)

# 2. Негативные случаи (валидный код - 0 ошибок):
default player_gold = 100
define MAX_GOLD = 9999
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    conflict_diags = [d for d in result.diagnostics if d.code == "RPY105" and "both 'define' and 'default'" in d.message]

    # Ожидаем ровно 2 диагностики на строках 4 и 7, уровень ERROR
    assert len(conflict_diags) == 2, f"Expected 2 conflicting declaration diagnostics, got: {conflict_diags}"

    d_karma = next(d for d in conflict_diags if d.line_number == 4)
    assert d_karma.severity == "ERROR"
    assert "karma" in d_karma.message
    assert "define" in d_karma.message
    assert "default" in d_karma.message

    d_affection = next(d for d in conflict_diags if d.line_number == 7)
    assert d_affection.severity == "ERROR"
    assert "affection" in d_affection.message


def test_jump_call_in_actions_and_python_rpy302(tmp_path: Path):
    """Verify RPY302 catches invalid labels in Jump/Call actions and renpy.jump/call."""
    code = """
label start:
    return

screen nav():
    # 1. Позитивные случаи в экранах:
    textbutton "1" action Jump("strt")       # RPY302 (line 7)
    textbutton "2" action Call("btle")       # RPY302 (line 8)

label test_py:
    # 2. Позитивные случаи в Python-коде:
    $ renpy.jump("edning")                   # RPY302 (line 12)
    $ renpy.call("chpter2")                  # RPY302 (line 13)

    # 3. Негативные случаи (валидный код - 0 ошибок):
    $ renpy.jump("start")
    $ renpy.call("start")
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy302_diags = [d for d in result.diagnostics if d.code == "RPY302"]

    # Ожидаем ровно 4 ошибки (строки 7, 8, 12, 13)
    assert len(rpy302_diags) == 4, f"Expected 4 RPY302 diagnostics, got: {rpy302_diags}"

    assert any(d.line_number == 7 and "strt" in d.message for d in rpy302_diags)
    assert any(d.line_number == 8 and "btle" in d.message for d in rpy302_diags)
    assert any(d.line_number == 12 and "edning" in d.message for d in rpy302_diags)
    assert any(d.line_number == 13 and "chpter2" in d.message for d in rpy302_diags)


def test_dynamic_jumps_do_not_trigger_false_positives_rpy302(tmp_path: Path):
    """Verify dynamic transitions (variables, expressions) do not trigger false RPY302."""
    code = """
label start:
    $ target_label = "ending"
    jump expression target_label
    call expression target_label

    $ renpy.jump(target_label)
    $ renpy.call(target_label)
    return

screen dynamic_nav(target):
    textbutton "Go" action Jump(target)
    textbutton "Do" action Call(target)
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy302_diags = [d for d in result.diagnostics if d.code == "RPY302"]
    
    # Линтер не должен выдать ни одной ошибки RPY302 на переменные без кавычек!
    assert len(rpy302_diags) == 0, f"False RPY302 on dynamic routing: {rpy302_diags}"


def test_undeclared_variables_in_subscripts_and_methods_rpy102(tmp_path: Path):
    """Verify RPY102 catches undeclared variables mutated via subscripts and methods."""
    code = """
label start:
    # 1. Позитивные случаи (переменные не объявлены, будет NameError):
    $ missing_dict["key"] = 1           # RPY102 (line 4)
    $ missing_list.append("sword")      # RPY102 (line 5)
    $ missing_stats["hp"] += 10         # RPY102 (line 6)

    # 2. Негативные случаи (переменные объявлены, 0 ошибок):
    $ valid_dict = {}
    $ valid_dict["key"] = 1
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy102_diags = [d for d in result.diagnostics if d.code == "RPY102" and "before declaration" in d.message]

    # Строгость по правилу 1.2: ожидаем ровно 3 диагностики на строках 4, 5 и 6
    assert len(rpy102_diags) == 3, f"Expected 3 RPY102 diagnostics, got: {rpy102_diags}"

    assert any(d.line_number == 4 and "missing_dict" in d.message for d in rpy102_diags)
    assert any(d.line_number == 5 and "missing_list" in d.message for d in rpy102_diags)
    assert any(d.line_number == 6 and "missing_stats" in d.message for d in rpy102_diags)


def test_cache_invalidates_on_same_size_same_mtime_content_change(tmp_path: Path):
    """Verify incremental cache invalidates via content_hash even when size and mtime are identical."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    script_file = game_dir / "script.rpy"

    # Шаг 1: файл версии 1 (пишем байты напрямую)
    code_v1 = b"default hero_gold = 100\n"
    script_file.write_bytes(code_v1)
    orig_size = script_file.stat().st_size

    # Холодный прогон: кэш создан
    analyzer_1 = SenpyAnalyzer(str(tmp_path))
    analyzer_1.run(quiet=True)
    assert "hero_gold" in analyzer_1.declared_symbols

    # Запоминаем исходный mtime
    orig_mtime = script_file.stat().st_mtime

    # Шаг 2: файл версии 2 (размер идентичен, но переменная другая!)
    code_v2 = b"default hero_mana = 100\n"
    script_file.write_bytes(code_v2)
    assert script_file.stat().st_size == orig_size

    # Принудительно возвращаем точный старый mtime, имитируя коллизию метаданных
    import os
    os.utime(str(script_file), (orig_mtime, orig_mtime))

    # Шаг 3: тёплый повторный запуск
    analyzer_2 = SenpyAnalyzer(str(tmp_path))
    analyzer_2.run(quiet=True)

    # На старом коде этот ассерт обязан упасть, так как кэш выдаст устаревший hero_gold!
    assert "hero_mana" in analyzer_2.declared_symbols, "Cache served stale scope: new variable 'hero_mana' was missed!"
    assert "hero_gold" not in analyzer_2.declared_symbols, "Cache served stale scope: old variable 'hero_gold' retained!"


def test_per_rule_severity_override(tmp_path: Path):
    """Verify severity_overrides elevates RPY104 to ERROR and demotes RPY308 to INFO."""
    code = """
label start:
    $ uninit_var = 100   # RPY104 (default: WARNING)

label next_scene:        # RPY308: fallthrough (default: WARNING)
    return
"""
    # 1. Дефолтное поведение: оба правила имеют уровень WARNING
    res_default, _ = run_senpy_on_code(code, tmp_path / "default_proj")
    d104_def = next(d for d in res_default.diagnostics if d.code == "RPY104")
    d308_def = next(d for d in res_default.diagnostics if d.code == "RPY308")
    assert d104_def.severity == "WARNING"
    assert d308_def.severity == "WARNING"

    # 2. Переопределяем строгость: RPY104 -> ERROR, RPY308 -> INFO
    game_dir = tmp_path / "custom_proj" / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(code, encoding="utf-8")

    analyzer = SenpyAnalyzer(
        str(tmp_path / "custom_proj"),
        severity_overrides={"RPY104": "ERROR", "RPY308": "INFO"},
    )
    res_custom = analyzer.run(quiet=True)

    d104_custom = next(d for d in res_custom.diagnostics if d.code == "RPY104")
    d308_custom = next(d for d in res_custom.diagnostics if d.code == "RPY308")

    assert d104_custom.severity == "ERROR"
    assert d308_custom.severity == "INFO"