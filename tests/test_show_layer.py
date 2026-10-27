"""TDD-тест RPY502-FP на `show layer <имя>`.

`show layer master at default` — легальный стейтмент Ren'Py (renpy.show_layer_at,
доки: "Python equivalent of the show layer <layer> at <at_list> statement"):
очищает слой и опционально применяет к нему трансформ. Слово `layer`
зарезервировано парсером Ren'Py и НЕ может быть тегом изображения.

До фикса RE_SHOW_SCENE не знал про `layer`: img_tokens = ["layer", "master"] ->
ложный RPY502 "Sprite or background 'layer' not found in assets or 'image'
definitions" на каждом сбросе камеры/трансформа слоя.
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


def test_show_layer_is_not_an_image_tag(tmp_path: Path):
    """Драйвер: show layer master at default / show layer screens — ноль RPY502."""
    script = """
label start:
    show layer master at default
    "Сцена началась."
    show layer screens
    "Конец."
    return
"""
    result, _ = run_senpy_on_code(script, tmp_path)
    fps = [d for d in result.diagnostics if d.code == "RPY502" and "show layer" in d.line_content]
    assert fps == [], f"Ложный RPY502 на легальном show layer: {[d.message for d in fps]}"


def test_regular_show_still_validates_attributes(tmp_path: Path):
    """Замок: гард не должен убить обычную проверку атрибутов show."""
    script = """
image eileen happy = "eileen_happy.png"

label start:
    show eileen angry
    "Привет!"
    return
"""
    result, _ = run_senpy_on_code(script, tmp_path)
    rpy502 = [d for d in result.diagnostics if d.code == "RPY502"]
    assert len(rpy502) == 1 and "angry" in rpy502[0].message, (
        f"Ожидался RPY502 на неизвестном атрибуте 'angry', получено: {[d.message for d in rpy502]}"
    )


def test_show_layer_still_validates_transforms(tmp_path: Path):
    """Замок: at-проверка трансформов работает и для show layer."""
    script = """
label start:
    show layer master at nonexistent_transform
    "Привет!"
    return
"""
    result, _ = run_senpy_on_code(script, tmp_path)
    rpy502 = [d for d in result.diagnostics if d.code == "RPY502"]
    assert len(rpy502) == 1 and "nonexistent_transform" in rpy502[0].message, (
        f"Ожидался RPY502 на неизвестном трансформе, получено: {[d.message for d in rpy502]}"
    )
