"""TDD-тесты: Mermaid-граф сюжета должен показывать экраны и их рёбра.

Jump()-экшены внутри экранов признаны
рёбрами графа достижимости, но generate_mermaid_graph рисует только
label->label переходы. Экраны-участники потока должны появляться узлами,
их экшены — рёбрами к меткам, а senpy-meta — координатами экрана для навигации.
"""

from __future__ import annotations

import json
from pathlib import Path

from senpy.core.analyzer import SenpyAnalyzer


def run_senpy_on_code(code: str, tmp_path: Path):
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(code, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    return analyzer.run(quiet=True), analyzer


SCRIPT_SCREEN_JUMP = """
screen stats_screen():
    vbox:
        textbutton "Статы" action Jump("stats_label")
    
label stats_label:
    return

label start:
    call screen stats_screen
"""


def test_screen_jump_action_edges_in_graph(tmp_path: Path):
    """Экран-участник потока = узел; его Jump-экшен = ребро к метке."""
    _, analyzer = run_senpy_on_code(SCRIPT_SCREEN_JUMP, tmp_path)
    graph = analyzer.export_graph()

    assert "```mermaid" in graph
    # Узел экрана (шестиугольник + класс screen)
    assert "screen_stats_screen" in graph
    assert ":::screen" in graph
    # Ребро экшена к существующей метке
    assert "screen_stats_screen -- action --> stats_label" in graph


def test_screen_missing_action_target_marked(tmp_path: Path):
    """Jump-экшен на несуществующую метку -> пунктирное ребро :::missing."""
    script = """
screen magic_screen():
    textbutton "Магия" action Jump("ghost_label")

label start:
    call screen magic_screen
"""
    _, analyzer = run_senpy_on_code(script, tmp_path)
    graph = analyzer.export_graph()

    assert "screen_magic_screen" in graph
    assert "screen_magic_screen -. action .-> ghost_label:::missing" in graph


def test_screen_nodes_in_meta_locations(tmp_path: Path):
    """senpy-meta содержит координаты экрана (type=screen) для навигации."""
    _, analyzer = run_senpy_on_code(SCRIPT_SCREEN_JUMP, tmp_path)
    graph = analyzer.export_graph()

    meta_str = graph.split("```senpy-meta")[1].split("```")[0].strip()
    meta = json.loads(meta_str)
    loc = meta["locations"]["screen_stats_screen"]
    assert loc["type"] == "screen"
    assert loc["line"] > 0
    assert loc["file"].endswith("script.rpy")


def test_graph_without_screens_has_no_screen_nodes(tmp_path: Path):
    """Негативный контроль: проект без экранов не получает экранных узлов."""
    script = """
label start:
    jump finale

label finale:
    return
"""
    _, analyzer = run_senpy_on_code(script, tmp_path)
    graph = analyzer.export_graph()

    assert ":::screen" not in graph
    assert '"screen: ' not in graph
