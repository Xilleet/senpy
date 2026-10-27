"""TDD: play/queue без файла — файл берётся из 'define audio.<канал>'.

Раньше 'play титры' (без файла) была невидима для анализатора:
RE_AUDIO_STATEMENT требовал файл после канала. Из-за этого:
  - актив из 'define audio.X' не помечался использованным (ложный RPY503),
  - голый 'play music' без файла и без 'define audio.music' проходил молча
    (в рантайме Ren'Py это исключение).
"""

from __future__ import annotations

from pathlib import Path

from senpy.analyzer import SenpyAnalyzer


def run_senpy_on_code(code: str, tmp_path: Path):
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(code, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    return analyzer.run(quiet=True)


def test_play_without_file_uses_audio_namespace(tmp_path: Path):
    """play X без файла при существующем define audio.X: чисто, актив помечен использованным"""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "audio").mkdir()
    (game_dir / "audio" / "titles.ogg").write_bytes(b"dummy")

    code = """
define audio.титры = "audio/titles.ogg"

label start:
    play титры
    return
"""
    result = run_senpy_on_code(code, tmp_path)
    bad = [d for d in result.diagnostics if d.code in ("RPY501", "RPY503", "RPY505")]
    assert bad == [], f"False diagnostics for bare play with audio namespace: {bad}"


def test_bare_play_without_define_warns(tmp_path: Path):
    """play X без файла и без define audio.X -> RPY501 (в рантайме это исключение)"""
    code = """
label start:
    play music
    return
"""
    result = run_senpy_on_code(code, tmp_path)
    codes = [d.code for d in result.diagnostics]
    assert "RPY501" in codes, f"Ожидался RPY501 на 'play music' без файла, получено: {codes}"
