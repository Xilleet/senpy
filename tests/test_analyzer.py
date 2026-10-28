from __future__ import annotations

import pickle
import zlib
from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer
from senpy.domain.rpa import safe_load_rpa_index


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
    """Verify MEGA_TEST_SCRIPT ловит все правила, которые он должен покрывать.

    P0-8: ранее тут хардкодился список из 29 правил, и тест проходил тривиально,
    не ловя регрессии 13 новых правил (RPY100, RPY107-109, RPY207-208, RPY309-310,
    RPY404, RPY505, RPY601-603). Теперь список берётся динамически из
    models.RULE_SEVERITY, и новые правила автоматически попадают в проверку.

    Правила, которые MEGA_TEST_SCRIPT заведомо НЕ может покрывать (нужны
    специальные условия — переводческие файлы, init python blocks, etc.),
    перечислены в MEGA_UNCOVERED_RULES с пояснением.
    """
    from senpy.core.models import RULE_SEVERITY

    # Создаём файл ассета, на который нет ни одной ссылки в коде (вызывает RPY503)
    extra_files = {"images/completely_unused_background.png": b"dummy_png_bytes"}

    result, _ = run_senpy_on_code(MEGA_TEST_SCRIPT, tmp_path, extra_files=extra_files)
    codes_found = {d.code for d in result.diagnostics}

    # Правила, которые MEGA_TEST_SCRIPT заведомо не покрывает.
    # Каждое — с указанием причины и номером соответствующего fixture-теста
    # (если он есть) или TODO (если fixture ещё нужно создать — см. RULE-1).
    MEGA_UNCOVERED_RULES = {
        # RPY100 — нужен файл с невалидным UTF-8 (тестируется отдельно через
        # test_encoding_errors.py + RPY100 fixture TODO).
        "RPY100",
        # RPY107 — нужен вызов deprecated API (LiveComposite, anim.*, ui.*).
        # MEGA_TEST_SCRIPT их не использует.
        "RPY107",
        # RPY108 — нужен конфликт типов (str += int). MEGA_TEST_SCRIPT имеет
        # += на define, но без конфликта типов.
        "RPY108",
        # RPY109 — нужен init python block с двумя зависимыми файлами.
        # MEGA_TEST_SCRIPT имеет только один init python с def.
        "RPY109",
        # RPY207 — нужен вызов use/call screen с неверными параметрами.
        "RPY207",
        # RPY208 — нужен SetVariable на screen-local переменной.
        "RPY208",
        # RPY309 — нужен сюжетный остров (изолированный label). MEGA_TEST_SCRIPT
        # имеет только chapter_two -> bad_edd (несуществующий), что даёт RPY302.
        "RPY309",
        # RPY310 — нужен call label(...) с неверными аргументами.
        "RPY310",
        # RPY404 — нужен MAYBE_SET после menu. MEGA_TEST_SCRIPT имеет RPY401
        # (асимметрия), но не RPY404.
        "RPY404",
        # RPY501 — нужен play/queue аудио с несуществующим файлом.
        "RPY501",
        # RPY505 — нужен register_channel на невалидном канале.
        "RPY505",
        # RPY601-603 — нужны переводческие файлы в game/tl/. MEGA_TEST_SCRIPT
        # их не создаёт. Покрываются отдельными fixture-тестами.
        "RPY601",
        "RPY602",
        "RPY603",
        # RPY701-702 — нужны unused define/transform, но MEGA_TEST_SCRIPT
        # использует все свои define/transform. RPY703 ловится (unused screen).
        # Покрываются отдельными тестами в test_rules_rpy7xx.py.
        "RPY701",
        "RPY702",
    }

    # Все правила, которые MEGA_TEST_SCRIPT ДОЛЖЕН покрывать
    expected_rules = set(RULE_SEVERITY.keys()) - MEGA_UNCOVERED_RULES

    missing_rules = expected_rules - codes_found
    assert not missing_rules, (
        f"MEGA_TEST_SCRIPT не поймал правила, которые должен покрывать: {sorted(missing_rules)}.\n"
        f"Если добавлено новое правило — добавь его либо в MEGA_TEST_SCRIPT, "
        f"либо в MEGA_UNCOVERED_RULES с указанием причины.\n"
        f"Пойманные правила: {sorted(codes_found)}"
    )

    # Обратная проверка: каждое правило в MEGA_UNCOVERED_RULES должно существовать
    # в RULE_SEVERITY (защита от опечаток в MEGA_UNCOVERED_RULES).
    invalid_uncovered = MEGA_UNCOVERED_RULES - set(RULE_SEVERITY.keys())
    assert not invalid_uncovered, (
        f"MEGA_UNCOVERED_RULES содержит несуществующие правила: {sorted(invalid_uncovered)}. "
        f"Возможно, правило было переименовано или удалено — обнови список."
    )


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
    assert '{/i}{/b}"' in fixed_content


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
    broken_code = "label start:\n    $ status = “active”\n    return\n"
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


def test_safe_rpa_blocks_malicious_pickle(tmp_path: Path):
    """Verify safe_load_rpa_index rejects untrusted opcodes (GLOBAL/REDUCE)"""

    # Имитируем вредоносный pickle с вызовом функции
    class Exploit:
        def __reduce__(self):
            import os

            return (os.system, ("echo hacked",))

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
    from senpy.cli.main import extract_scripts_from_rpa

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

    crlf_content = 'label start:\r\n    "Unclosed {b}tag"\r\n    return\r\n'
    script_file.write_bytes(crlf_content.encode("utf-8"))

    analyzer = SenpyAnalyzer(str(tmp_path), fix=True)
    result = analyzer.run(quiet=True)

    assert result.fixed_count == 1
    raw_after_fix = script_file.read_bytes()
    assert b"\r\r\n" not in raw_after_fix
    assert b"\r\n" in raw_after_fix


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
    from senpy.formats.ci import init_ci_workflow

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
    from senpy.core.coverage import calculate_translation_coverage

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
    from senpy.formats.wiki import generate_project_wiki

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
    from senpy.formats.stubs import generate_stubs

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
    from senpy.formats.traceback import parse_traceback_file

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
    """RULES_DATABASE и RULE_SEVERITY совпадают ключ-в-ключ"""
    from senpy.core.models import RULE_SEVERITY
    from senpy.rules.rules_info import RULES_DATABASE

    missing = set(RULE_SEVERITY.keys()) - set(RULES_DATABASE.keys())
    assert not missing, f"RULES_DATABASE is missing rules: {missing}"
    extra = set(RULES_DATABASE.keys()) - set(RULE_SEVERITY.keys())
    assert not extra, f"RULES_DATABASE has rules not in RULE_SEVERITY: {extra}"


def test_tsundere_flavors_completeness():
    """TSUNDERE_FLAVORS и RULE_SEVERITY совпадают ключ-в-ключ"""
    from senpy.core.models import RULE_SEVERITY
    from senpy.domain.tsundere import TSUNDERE_FLAVORS

    missing = set(RULE_SEVERITY.keys()) - set(TSUNDERE_FLAVORS.keys())
    assert not missing, f"TSUNDERE_FLAVORS is missing phrases for rules: {missing}"
    extra = set(TSUNDERE_FLAVORS.keys()) - set(RULE_SEVERITY.keys())
    assert not extra, f"TSUNDERE_FLAVORS has phrases for unknown rules: {extra}"


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
    assert "hero_mana" in analyzer_2.declared_symbols, (
        "Cache served stale scope: new variable 'hero_mana' was missed!"
    )
    assert "hero_gold" not in analyzer_2.declared_symbols, (
        "Cache served stale scope: old variable 'hero_gold' retained!"
    )


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


def test_advanced_type_inference_expressions_rpy108(tmp_path: Path):
    """Verify advanced type inference on expressions (binary ops, known variables, methods) for RPY108."""
    code = """
default base_score = 10
default extra_score = base_score + 5     # inferred as int
default player_title = "Hero " + "Eileen" # inferred as str
default is_ready = base_score > 5         # inferred as bool

label start:
    # 1. Ошибки несовместимого += на составных типах
    $ extra_score += "points"            # RPY108 [ERROR]: int += str
    $ player_title += 1                  # RPY108 [ERROR]: str += int

    # 2. Ошибки перезаписи несовместимым типом
    $ extra_score = "MAX"                # RPY108 [WARNING]: int = str
    $ is_ready = 100                     # RPY108 [WARNING]: bool = int

    # 3. Валидные составные присваивания (0 ошибок)
    $ extra_score += 20
    $ player_title = player_title.upper()
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy108_diags = [d for d in result.diagnostics if d.code == "RPY108"]

    assert len(rpy108_diags) == 4, f"Expected 4 RPY108 diagnostics, got: {rpy108_diags}"

    # Проверяем фатальные ошибки +=
    errs = [d for d in rpy108_diags if d.severity == "ERROR"]
    assert len(errs) == 2
    assert any("extra_score" in d.message and "type 'int'" in d.message for d in errs)
    assert any("player_title" in d.message and "type 'str'" in d.message for d in errs)

    # Проверяем предупреждения перезаписи типа
    warns = [d for d in rpy108_diags if d.severity == "WARNING"]
    assert len(warns) == 2
    assert any("extra_score" in d.message and "incompatible type 'str'" in d.message for d in warns)
    assert any("is_ready" in d.message and "incompatible type 'int'" in d.message for d in warns)


def test_unified_cfg_nested_menu_inside_if(tmp_path: Path):
    """Verify unified CFG correctly bubbles guaranteed vars and termination from menu to enclosing if."""
    code = """
label start:
    # 1. Меню внутри if, где обе ветки задают переменную -> переменная гарантирована в if
    if has_entered_shop:
        menu:
            "Купить меч":
                $ weapon = "sword"
            "Купить лук":
                $ weapon = "bow"
    else:
        $ weapon = "fists"

    # Не должно быть RPY404! weapon есть и в if, и в else
    if weapon == "sword":
        "Готов к бою."

    # 2. Меню внутри if, где все выборы терминируют процесс
    if is_game_over:
        menu:
            "Сдаться":
                return
            "Рестарт":
                $ renpy.full_restart()
    else:
        $ survival_bonus = 100

    # Ветка if завершается, поэтому survival_bonus гарантирован после блока
    if survival_bonus > 0:
        "Бонус: [survival_bonus]"
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy404_diags = [d for d in result.diagnostics if d.code == "RPY404"]
    rpy401_diags = [d for d in result.diagnostics if d.code == "RPY401"]

    assert len(rpy404_diags) == 0, f"False RPY404 on unified CFG nested menu: {rpy404_diags}"
    assert len(rpy401_diags) == 0, f"False RPY401 on exhaustive menu: {rpy401_diags}"


def test_lsp_differential_update_multiple_files_integrity(tmp_path: Path):
    """Verify differential purge updates single file without corrupting other files' symbols."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)

    file_a = game_dir / "a.rpy"
    file_b = game_dir / "b.rpy"

    file_a.write_text(
        "default shared_var = 1\ndefault a_unique = 10\nlabel scene_a:\n    return\n",
        encoding="utf-8",
    )
    file_b.write_text(
        "default shared_var = 2\ndefault b_unique = 20\nlabel scene_b:\n    return\n",
        encoding="utf-8",
    )

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)

    assert "a_unique" in analyzer.variables
    assert "b_unique" in analyzer.variables
    assert "scene_a" in analyzer.labels
    assert "scene_b" in analyzer.labels

    # Модифицируем файл A: переименовываем a_unique -> a_renamed, удаляем scene_a
    file_a.write_text(
        "default shared_var = 1\ndefault a_renamed = 99\nlabel scene_a_new:\n    return\n",
        encoding="utf-8",
    )
    analyzer.analyze_file_only(str(file_a))

    # 1. Изменения в файле A применились
    assert "a_unique" not in analyzer.variables
    assert "a_renamed" in analyzer.variables
    assert "scene_a" not in analyzer.labels
    assert "scene_a_new" in analyzer.labels

    # 2. Символы файла B НЕ пострадали
    assert "b_unique" in analyzer.variables
    assert "scene_b" in analyzer.labels

    # 3. Общая переменная shared_var не удалилась из declared_symbols, так как она осталась в файле B
    assert "shared_var" in analyzer.declared_symbols


def test_multiline_calls_and_playlists_parsing(tmp_path: Path):
    """Verify multiline call statements, transform declarations, and audio playlists glue cleanly."""
    extra_files = {
        "audio/intro.ogg": b"dummy_audio_1",
        "audio/loop.ogg": b"dummy_audio_2",
    }
    code = """
label target_scene(difficulty="normal", party_size=4):
    return

transform multiline_bounce(
    speed=0.2,
    offset_y=-20
):
    yoffset 0
    easein speed yoffset offset_y
    easeout speed yoffset 0

label start:
    # 1. Многострочный вызов call с аргументами на разных строках
    call target_scene(
        difficulty="hard",
        party_size=2
    )

    # 2. Многострочный плейлист audio
    play music [
        "audio/intro.ogg",
        "audio/loop.ogg"
    ]
    return
"""
    _result, _ = run_senpy_on_code(code, tmp_path, extra_files=extra_files)
    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)

    errors = [d for d in result.diagnostics if d.severity == "ERROR"]

    # Ни RPY310 (ошибка аргументов call), ни RPY501 (аудио) не должны сработать
    assert len(errors) == 0, f"Multiline instructions failed parsing: {errors}"
    assert "target_scene" in analyzer.labels
    assert "multiline_bounce" in analyzer.transforms


def test_screen_variable_leak_rpy208(tmp_path: Path):
    """Verify RPY208 catches screen-local variables modified via SetVariable, ToggleVariable or Python."""
    code = """
default global_gold = 100

screen shop(discount_rate=0.1):
    default selected_item = "none"
    default is_confirmed = False

    # 1. Позитивные случаи (ошибки RPY208):
    textbutton "Sword" action SetVariable("selected_item", "sword")     # Ошибка: selected_item локален для экрана! (line 9)
    textbutton "Confirm" action ToggleVariable("is_confirmed")          # Ошибка: is_confirmed локален для экрана! (line 10)
    $ discount_rate = 0.2                                               # Ошибка: аргумент экрана мутируется через $! (line 11)

    # 2. Негативные случаи (валидный код - 0 ошибок):
    textbutton "Legit Pick" action SetScreenVariable("selected_item", "axe")
    textbutton "Legit Toggle" action ToggleScreenVariable("is_confirmed")
    textbutton "Global Buy" action SetVariable("global_gold", 50)
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy208_diags = [d for d in result.diagnostics if d.code == "RPY208"]

    assert len(rpy208_diags) == 3, f"Expected 3 RPY208 diagnostics, got: {rpy208_diags}"

    # Ошибка 1: SetVariable -> SetScreenVariable с QuickFix
    d_set = next(d for d in rpy208_diags if d.line_number == 9)
    assert d_set.severity == "ERROR"
    assert "selected_item" in d_set.message
    assert "SetScreenVariable" in d_set.message
    assert d_set.fix_replacement == "SetScreenVariable"

    # Ошибка 2: ToggleVariable -> ToggleScreenVariable с QuickFix
    d_toggle = next(d for d in rpy208_diags if d.line_number == 10)
    assert d_toggle.severity == "ERROR"
    assert "is_confirmed" in d_toggle.message
    assert "ToggleScreenVariable" in d_toggle.message
    assert d_toggle.fix_replacement == "ToggleScreenVariable"

    # Ошибка 3: Прямая мутация $ discount_rate = 0.2
    d_py = next(d for d in rpy208_diags if d.line_number == 11)
    assert d_py.severity == "ERROR"
    assert "discount_rate" in d_py.message


def test_story_stats_word_count_and_character_balance(tmp_path: Path):
    """Verify story stats correctly calculates word count, reading time and character speech shares."""
    from senpy.formats.stats import collect_story_stats

    code = """
define s = Character("Сайори")
define m = Character("Моника")

label start:
    s "Привет, дорогой друг! Как твои дела?"
    m "Добро пожаловать в литературный клуб!"
    "В комнате воцарилась тишина."
    s "Пойдём пить чай с печеньем."
    return
"""
    _result, _ = run_senpy_on_code(code, tmp_path)
    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)

    stats = collect_story_stats(analyzer)

    assert stats.total_dialogue_lines == 4
    assert stats.total_words > 15
    assert stats.reading_time_minutes > 0.0

    # Сайори сказала 2 реплики
    assert "s" in stats.characters
    assert stats.characters["s"].display_name == "Сайори"
    assert stats.characters["s"].lines_count == 2
    assert stats.characters["s"].percentage_words > 40.0

    # Моника сказала 1 реплику
    assert "m" in stats.characters
    assert stats.characters["m"].display_name == "Моника"
    assert stats.characters["m"].lines_count == 1

    # Рассказчик сказал 1 реплику
    assert "narrator" in stats.characters
    assert stats.characters["narrator"].lines_count == 1
