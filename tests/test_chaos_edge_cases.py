from __future__ import annotations

from pathlib import Path

from senpy.analyzer import SenpyAnalyzer


def run_code(code: str, tmp_path: Path):
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    target = game_dir / "script.rpy"
    target.write_text(code, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)
    return result, analyzer


def test_chaos_keyword_shadowing_variables(tmp_path: Path):
    """[Chaos] Ren'Py script keywords (label, screen, show, scene) used as variable names."""
    code = """
default label = "prologue"
default screen = "main_hud"
default show = True
default scene = 42

label start:
    $ label = "chapter_1"
    $ screen = "inventory"
    $ show = False
    $ scene += 1

    if show and scene > 10:
        "Status: [label], [screen], [scene]"
    return
"""
    result, analyzer = run_code(code, tmp_path)
    errors = [d for d in result.diagnostics if d.severity == "ERROR"]

    # Линтер не должен сойти с ума, перепутать переменные с реальными операторами
    # show/scene/label и не должен выдать ложных ScriptError
    assert len(errors) == 0, f"Keyword shadowing confused the parser: {errors}"
    assert "label" in analyzer.variables
    assert "screen" in analyzer.variables


def test_chaos_diabolical_text_tags_and_escapes(tmp_path: Path):
    """[Chaos] Diabolical text tags: triple braces, quoted font paths, mixed case, self-closing tags."""
    code = """
label start:
    # 1. Тройные фигурные скобки: экранирование {{ + открывающий тег {b}
    "Score: {{{b}100{/b}}} points!"

    # 2. Тег с пробелами и кавычками в параметре
    "{font='fonts/custom font.ttf'}Special text{/font}"

    # 3. Самозакрывающиеся теги {w=1.0}, {p} внутри парного {i}
    "{i}Wait a second...{w=1.0}{p} Done!{/i}"

    # 4. Верхний регистр тегов (Ren'Py регистронезависим к тегам)
    "{B}LOUD TEXT{/B}"

    # 5. Экранированные квадратные скобки внутри цветного текста
    "{color=#ff00ff}Matrix: [[0, 1]]{/color}"
    return
"""
    result, _ = run_code(code, tmp_path)
    tag_errors = [d for d in result.diagnostics if d.code in ("RPY301", "RPY304", "RPY101")]
    assert len(tag_errors) == 0, f"Brutal text tags failed validation: {tag_errors}"


def test_chaos_deeply_nested_all_terminating_branches(tmp_path: Path):
    """[Chaos] Multi-level nested menus where EVERY branch terminates via return or jump."""
    code = """
label start:
    menu:
        "Take Left Tunnel":
            menu:
                "Step into fire":
                    $ fate = "burned"
                    jump death_ending
                "Drink poison":
                    $ fate = "poisoned"
                    return
        "Take Right Tunnel":
            $ fate = "crushed"
            jump rock_ending

    # Сюда управление НИКОГДА не дойдёт!
    # Линтер не должен выдать RPY401 или RPY404 на переменную fate!
    if fate == "burned":
        "Impossible point."

label death_ending:
    return

label rock_ending:
    return
"""
    result, _ = run_code(code, tmp_path)
    rpy401 = [d for d in result.diagnostics if d.code == "RPY401"]
    rpy404 = [d for d in result.diagnostics if d.code == "RPY404"]

    # Так как все развилки меню терминируются (jump / return), слияния веток нет
    assert len(rpy401) == 0, f"False RPY401 on terminated menu: {rpy401}"
    assert len(rpy404) == 0, f"False RPY404 on unreachable post-menu: {rpy404}"


def test_chaos_python_walrus_and_nested_comprehensions(tmp_path: Path):
    """[Chaos] Modern Python 3.8+ walrus operator (:=) and nested comprehensions in Ren'Py store."""
    code = """
default raw_data = [1, 2, 3, 4, 5]

label start:
    python:
        # Моржовый оператор внутри спискового включения
        filtered = [y for x in raw_data if (y := x * 2) > 4]
        # Вложенные словари и генераторы
        grid = {x: {y: x * y for y in range(3)} for x in range(3)}

    if len(filtered) > 0:
        "Processed [filtered]"
    return
"""
    result, _ = run_code(code, tmp_path)
    # Переменные y, x существуют только локально внутри выражений и не должны
    # протекать в глобальный store как ошибки RPY104/RPY102
    rpy104_errors = [d for d in result.diagnostics if d.code == "RPY104" and d.line_content.strip().startswith(("x =", "y ="))]
    assert len(rpy104_errors) == 0, f"Comprehension locals leaked into RPY104: {rpy104_errors}"


def test_chaos_cyclic_jump_torture_graph(tmp_path: Path):
    """[Chaos] Highly cyclic spaghetti jump labyrinth (stress-testing DFS recursion limit in can_reach_return)."""
    # Генерируем клубок из 30 меток, прыгающих друг в друга по кругу
    lines = ["label start:\n    call node_0\n    return\n"]
    for i in range(30):
        next_node = f"node_{(i + 1) % 30}"
        alt_node = f"node_{(i + 7) % 30}"
        lines.append(f"label node_{i}:")
        lines.append("    if False:")
        lines.append(f"        jump {alt_node}")
        if i == 29:
            lines.append("    return")  # Только последний узел имеет выход
        else:
            lines.append(f"    jump {next_node}\n")

    code = "\n".join(lines)
    result, _ = run_code(code, tmp_path)

    # Функция _can_reach_return() обязана найти путь к return и не упасть с RecursionError
    rpy306 = [d for d in result.diagnostics if d.code == "RPY306"]
    assert len(rpy306) == 0, f"Cyclic graph failed to resolve return path: {rpy306}"


def test_chaos_comments_and_hashes_torture(tmp_path: Path):
    """[Chaos] Comment characters '#' inside triple quotes, regex strings, and dialogue text."""
    code = """
label start:
    "She said: \\"Look at #hashtag and hex #123456 color!\\"" # Real comment
    $ regex_pattern = r"^[a-z]+#[0-9]+$"   # Comment with pattern # not code
    $ message = "String with # and escaped \\" quotes inside"
    return
"""
    result, _ = run_code(code, tmp_path)
    # Хэши внутри кавычек не должны обрезать строки
    errors = [d for d in result.diagnostics if d.severity == "ERROR"]
    assert len(errors) == 0, f"Comments inside strings corrupted lexical parse: {errors}"

def test_chaos_audio_playlist_syntax(tmp_path: Path):
    """[Chaos] Ren'Py audio playlists syntax: play music [ 'intro.ogg', 'loop.ogg' ]."""
    extra_files = {
        "audio/track_intro.ogg": b"dummy_intro",
        "audio/track_loop.ogg": b"dummy_loop",
    }
    # Ren'Py официально поддерживает списки треков в play music для бесшовного intro -> loop
    code = """
label start:
    play music [ "audio/track_intro.ogg", "audio/track_loop.ogg" ]
    return
"""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    for rel_path, data in extra_files.items():
        dest = game_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    (game_dir / "script.rpy").write_text(code, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)

    # Линтер не должен споткнуться о скобки списка [ ] и не должен решить,
    # что '[' — это несуществующий аудиофайл (RPY501)
    rpy501_errors = [d for d in result.diagnostics if d.code == "RPY501"]
    assert len(rpy501_errors) == 0, f"Playlist brackets triggered false RPY501: {rpy501_errors}"


def test_chaos_augmented_subscript_mutation_on_define(tmp_path: Path):
    """[Chaos] In-place augmented mutation on subscript of define constant ($ CONST['key'] += 10)."""
    code = """
define PLAYER_STATS = {"hp": 100, "mana": 50}

label start:
    # Опасная мутация константы через += по ключу словаря! Должна ловиться как RPY105!
    $ PLAYER_STATS["hp"] += 20
    $ PLAYER_STATS["mana"] -= 10
    return
"""
    result, _ = run_code(code, tmp_path)
    rpy105_errors = [d for d in result.diagnostics if d.code == "RPY105"]

    # Линтер ОБЯЗАН поймать обе мутации константы PLAYER_STATS
    assert len(rpy105_errors) == 2, f"Augmented subscript mutation bypassed RPY105: {rpy105_errors}"


def test_chaos_multiline_dialogue_with_backslashes_and_comments(tmp_path: Path):
    """[Chaos] Multiline dialogue glued by backslashes with inline comments on each line."""
    code = """
label start:
    "First part of line " \
    "second part with {b}bold tag " \  # Inline comment on continuation line
    "that is closed here{/b}."
    return
"""
    result, _ = run_code(code, tmp_path)
    # Склеивание строк через backslash не должно обрезать кавычки или оставить тег {b} открытым
    errors = [d for d in result.diagnostics if d.code in ("RPY301", "RPY305")]
    assert len(errors) == 0, f"Backslash continuation with comments broke dialogue parse: {errors}"


def test_chaos_unicode_emojis_surrogates_and_cjk_brackets(tmp_path: Path):
    """[Chaos] Unicode 4-byte surrogate emojis (🚀🌸), CJK quotes 「...」, and text tags alignment."""
    code = """
default player_name = "Таро"

label start:
    "「Привет, [player_name]!」 🌸 Добро пожаловать на борт 🚀! {b}Успех!{/b}"
    return
"""
    result, _ = run_code(code, tmp_path)
    # Линтер обязан корректно посчитать UTF-16 смещения без падений по IndexError
    errors = [d for d in result.diagnostics if d.severity == "ERROR"]
    assert len(errors) == 0, f"Surrogate pairs and CJK characters caused errors: {errors}"


def test_chaos_complex_screen_timers_and_action_lists(tmp_path: Path):
    """[Chaos] Complex screen with timer, action lists, sensitivity and local scope."""
    code = """
default quick_time_active = True
default qte_score = 0

screen qte_event():
    # Таймер со списком экшенов
    timer 3.0:
        action [SetVariable("quick_time_active", False), Return()]

    # Кнопка с условием чувствительности и экшенами
    textbutton "SMASH!":
        sensitive quick_time_active
        action [SetVariable("qte_score", qte_score + 1), Return()]

label start:
    call screen qte_event
    return
"""
    result, _ = run_code(code, tmp_path)
    # Не должно быть ложных RPY203 (кнопка без action) или RPY206 (вызов функции)
    screen_errors = [d for d in result.diagnostics if d.code in ("RPY203", "RPY206", "RPY201")]
    assert len(screen_errors) == 0, f"Screen with timer/action lists triggered false alarms: {screen_errors}"

def test_chaos_renpy_local_sub_labels_with_dots(tmp_path: Path):
    """[Chaos] Ren'Py official sub-labels syntax: 'label .local_name:' and 'jump .local_name'."""
    code = """
label dungeon_hub:
    "You enter the hub."
    jump .armory

label .armory:
    "Inside the local armory sub-scene."
    return

label outside:
    # Прыжок на несуществующую локальную под-метку ОБЯЗАН вызывать RPY302!
    jump .missing_sub
"""
    result, analyzer = run_code(code, tmp_path)
    # 1. Метка .armory (или dungeon_hub.armory) ОБЯЗАНА быть зарегистрирована в словаре labels!
    assert any(".armory" in name for name in analyzer.labels), "Linter failed to register sub-label with dot!"

    # 2. Прыжок в никуда jump .missing_sub ОБЯЗАН вызывать RPY302!
    rpy302 = [d for d in result.diagnostics if d.code == "RPY302"]
    assert len(rpy302) == 1, f"Linter was blind to invalid local jump: {rpy302}"


def test_chaos_menu_choice_arguments_and_conditions(tmp_path: Path):
    """[Chaos] Ren'Py 7.4+ menu choice arguments: 'Choice' (arg, kw=val) if condition:."""
    code = """
default player_gold = 100

label shop_hub:
    menu:
        # Выбор с аргументами в скобках + переменная только в одной ветке
        "Buy Excalibur" ("legendary", cost=100) if player_gold >= 100:
            $ got_excalibur = True
            "You obtained Excalibur!"

        "Leave empty-handed" (icon="door"):
            "You left."

    # Асимметрия веток обязана триггерить RPY401, даже если у выборов были аргументы в скобках!
    if got_excalibur:
        "Wielding the sword!"
    return
"""
    result, _ = run_code(code, tmp_path)
    rpy401 = [d for d in result.diagnostics if d.code == "RPY401"]
    assert len(rpy401) == 1, f"Linter failed to parse menu choices with arguments: {rpy401}"

def test_chaos_multiline_default_nested_collections(tmp_path: Path):
    """[Chaos] Multiline default dictionary spanning multiple lines with comments inside."""
    code = """
default quest_tree = {
    "act1": [
        "meet_monika",
        "find_key", # Comment inside collection
    ],
    "completed": False,
}

label start:
    if quest_tree["completed"]:
        "Done!"
    return
"""
    result, analyzer = run_code(code, tmp_path)
    errors = [d for d in result.diagnostics if d.severity == "ERROR"]

    # Линтер обязан склеить конструкцию, определить тип 'dict' и не выдать RPY103 (undeclared variable)
    assert len(errors) == 0, f"Multiline default collection caused parsing errors: {errors}"
    assert "quest_tree" in analyzer.variables
    assert analyzer.variables["quest_tree"].type_name == "dict"


def test_chaos_url_parameters_in_dialogue_anchor_tags(tmp_path: Path):
    """[Chaos] Web links in dialogue with query strings {a=https://url?x=1&y=2}Text{/a}."""
    code = """
label start:
    "Check our website at {a=https://renpy.org/doc/html/screens.html?param=value&id=42}Documentation{/a}!"
    return
"""
    result, _ = run_code(code, tmp_path)
    tag_errors = [d for d in result.diagnostics if d.code in ("RPY301", "RPY304")]
    # Знаки '=' и '&' внутри параметра тега не должны ломать парсер тегов
    assert len(tag_errors) == 0, f"URL parameters inside tag broke parser: {tag_errors}"


def test_chaos_complex_expression_inside_interpolation(tmp_path: Path):
    """[Chaos] Python method calls with arguments inside text interpolation [obj.method(arg)]."""
    code = """
init python:
    class Hero:
        def get_title(self, bold=False):
            return "Champion"

default hero = Hero()

label start:
    "Welcome, [hero.get_title(bold=True)]! Your journey begins."
    return
"""
    result, _ = run_code(code, tmp_path)
    # Линтер должен понять, что корень выражения — объявленная переменная 'hero',
    # и не должен ругаться на get_title или True как на необъявленные переменные (RPY101)
    rpy101_errors = [d for d in result.diagnostics if d.code == "RPY101"]
    assert len(rpy101_errors) == 0, f"Method call inside interpolation triggered RPY101: {rpy101_errors}"