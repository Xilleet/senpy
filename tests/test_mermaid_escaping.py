"""TDD-тест: экранирование имён в Mermaid-графе.

Ren'Py допускает саб-метки с точками (label .start -> chapter.start) и метки,
чьи имена совпадают с зарезервированными словами Mermaid (end). До фикса такие
имена попадали в id узлов/рёбер как есть и ломали парсинг диаграммы в вебвью;
тексты fallthrough/return-узлов эммитились без кавычек.
"""

from __future__ import annotations

from pathlib import Path

from senpy.analyzer import SenpyAnalyzer


def run_senpy_on_code(code: str, tmp_path: Path):
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(code, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    return analyzer.run(quiet=True), analyzer


def get_graph(tmp_path: Path, code: str) -> str:
    _, analyzer = run_senpy_on_code(code, tmp_path)
    return analyzer.export_graph()


SCRIPT_DOTTED = """
label start:
    jump chapter.start

label chapter:
    "Глава без выхода."

label .start:
    jump финиш

label финиш:
    return
"""

SCRIPT_END = """
label start:
    jump end

label end:
    return
"""

SCRIPT_MISSING = """
label start:
    jump ghost.target
"""

SCRIPT_PLAIN = """
label start:
    jump chapter_one

label chapter_one:
    jump start
"""

SCRIPT_SCREEN_PLAIN = """
screen hub():
    textbutton "Далее" action Jump("finale")

label start:
    show screen hub
    "Хаб."
    jump finale

label finale:
    return
"""


def test_dotted_label_id_sanitized_text_kept(tmp_path: Path):
    """Саб-метка chapter.start: id санитизирован (точка -> _), текст в кавычках"""
    graph = get_graph(tmp_path, SCRIPT_DOTTED)
    assert '    chapter_start["chapter.start"]' in graph
    assert "    start --> chapter_start" in graph
    assert "\n    chapter.start" not in graph


def test_fallthrough_and_cyrillic_text_quoted(tmp_path: Path):
    """Fallthrough-текст в кавычках; кириллица сохраняется в id и тексте"""
    graph = get_graph(tmp_path, SCRIPT_DOTTED)
    assert '    chapter[["chapter"]]:::fallthrough' in graph
    assert '    финиш(["финиш"])' in graph


def test_reserved_end_label_rendered(tmp_path: Path):
    """Метка end: id получает суффикс (end_), иначе Mermaid парсер умирает"""
    graph = get_graph(tmp_path, SCRIPT_END)
    assert '    end_(["end"])' in graph
    # таргет end имеет return -> ребро рисуется как call (is_call=has_return)
    assert "    start -- call --> end_" in graph


def test_missing_dotted_target_quoted(tmp_path: Path):
    """Несуществующая dotted-цель: id санитизирован, сырое имя в тексте"""
    graph = get_graph(tmp_path, SCRIPT_MISSING)
    assert '    start -. jump .-> ghost_target["ghost.target"]:::missing' in graph
    assert "-> ghost.target" not in graph


def test_plain_labels_unchanged(tmp_path: Path):
    """Замок: обычные имена рендерятся как раньше"""
    graph = get_graph(tmp_path, SCRIPT_PLAIN)
    assert '    chapter_one["chapter_one"]' in graph
    assert "    start --> chapter_one" in graph
    assert "    chapter_one --> start" in graph


def test_plain_screens_unchanged(tmp_path: Path):
    """Замок: экранные узлы/рёбра для простых имён прежние"""
    graph = get_graph(tmp_path, SCRIPT_SCREEN_PLAIN)
    assert '    screen_hub{"screen: hub"}:::screen' in graph
    assert "    screen_hub -- action --> finale" in graph
