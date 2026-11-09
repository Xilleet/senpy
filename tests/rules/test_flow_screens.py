from __future__ import annotations

from pathlib import Path

from senpy.core.analyzer import SenpyAnalyzer


def run_senpy_on_code(code: str, tmp_path: Path):
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(code, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    return analyzer.run(quiet=True)


def test_rpy309_no_fp_label_reachable_via_screen_action(tmp_path: Path):
    """Метка, достижимая только через Jump() в экране, не получает RPY309."""
    code = """
label start:
    show screen hud
    "Игра началась."
    return

screen hud():
    textbutton "В меню" action Jump("menu_return")

label menu_return:
    return
"""
    result = run_senpy_on_code(code, tmp_path)
    islands = [d for d in result.diagnostics if d.code == "RPY309"]
    assert not islands, (
        f"False RPY309 for screen-reachable label: {[d.line_number for d in islands]}"
    )


def test_rpy309_no_fp_label_reachable_via_use_chain(tmp_path: Path):
    """Цепочка call screen -> use -> Jump тоже открывает метку."""
    code = """
label start:
    call screen navigator
    return

screen navigator():
    use submenu

screen submenu():
    textbutton "Дальше" action Jump("far_away")

label far_away:
    return
"""
    result = run_senpy_on_code(code, tmp_path)
    islands = [d for d in result.diagnostics if d.code == "RPY309"]
    assert not islands, f"False RPY309 via use-chain: {[d.line_number for d in islands]}"


def test_rpy309_unused_screen_targets_still_flagged(tmp_path: Path):
    """Экран, нигде не показанный, — мост недействителен: RPY309 остаётся."""
    code = """
label start:
    "Просто текст."
    return

screen orphan_scr():
    textbutton "Туда" action Jump("orphan_target")

label orphan_target:
    return
"""
    result = run_senpy_on_code(code, tmp_path)
    islands = [d for d in result.diagnostics if d.code == "RPY309"]
    assert len(islands) == 1 and islands[0].line_number == 9, (
        f"Expected exactly one RPY309 at line 9, got: {[(d.line_number) for d in islands]}"
    )
