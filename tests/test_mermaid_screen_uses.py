"""TDD-тест: Mermaid-рёбра label -- call screen --> screen и screen -- use --> screen.

used_screens — плоское множество: граф знает, что экран участвует
в потоке, но не знает КТО его использует. Рёбра call screen / show screen
из лейблов и use из экранов не рисуются. Новое поле FileScope.screen_uses
(источник -> экраны) даёт атрибуцию. SENPY_VERSION бампается: старые кэши
не содержат поля, без инвалидации рёбра исчезали бы на тёплом прогоне.
"""
from __future__ import annotations

from pathlib import Path

from senpy.analyzer import SenpyAnalyzer


def run_senpy_on_code(code: str, tmp_path: Path):
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(code, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    return analyzer


def test_label_call_screen_edge(tmp_path: Path):
    """call screen из лейбла -> ребро start -- call screen --> screen_stats_screen."""
    script = """
screen stats_screen:
    frame:
        text "Stats"

label start:
    call screen stats_screen
    "Дальше."
    return
"""
    analyzer = run_senpy_on_code(script, tmp_path)
    graph = analyzer.export_graph()
    assert "start -- call screen --> screen_stats_screen" in graph, (
        f"Нет ребра label->screen в графе:\n{graph}"
    )


def test_screen_use_edge(tmp_path: Path):
    """use внутри экрана -> ребро screen_hud -- use --> screen_nested_panel."""
    script = """
screen nested_panel:
    text "Panel"

screen hud:
    use nested_panel
    text "HUD"
"""
    analyzer = run_senpy_on_code(script, tmp_path)
    graph = analyzer.export_graph()
    assert "screen_hud -- use --> screen_nested_panel" in graph, (
        f"Нет ребра screen-use->screen в графе:\n{graph}"
    )


def test_show_screen_edge_and_missing_target_skipped(tmp_path: Path):
    """show screen из лейбла -> ребро; несуществующий экран в граф не попадает."""
    script = """
screen inventory:
    text "Inv"

label start:
    show screen inventory
    show screen ghost_screen
    return
"""
    analyzer = run_senpy_on_code(script, tmp_path)
    graph = analyzer.export_graph()
    assert "start -- call screen --> screen_inventory" in graph
    assert "ghost_screen" not in graph, (
        "Несуществующий экран не должен рисоваться (его ловит RPY204)"
    )


def test_existing_jump_action_edges_intact(tmp_path: Path):
    """Замок: узлы экранов и рёбра Jump-экшенов (Задача 5) не сломаны."""
    script = """
screen menu_screen:
    textbutton "Go" action Jump("forest")

label start:
    call screen menu_screen
    return

label forest:
    return
"""
    analyzer = run_senpy_on_code(script, tmp_path)
    graph = analyzer.export_graph()
    assert 'screen_menu_screen{"screen: menu_screen"}:::screen' in graph
    assert "screen_menu_screen -- action --> forest" in graph