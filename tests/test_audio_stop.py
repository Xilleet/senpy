from __future__ import annotations

from pathlib import Path

from senpy.analyzer import SenpyAnalyzer


def run_senpy_on_code(code: str, tmp_path: Path):
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(code, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    return analyzer.run(quiet=True)


def test_stop_builtin_channel_ok(tmp_path: Path):
    """stop music / stop sound fadeout — валидные каналы, ноль диагностик."""
    code = """
label start:
    stop music
    stop sound fadeout 2.0
    return
"""
    result = run_senpy_on_code(code, tmp_path)
    rpy505 = [d for d in result.diagnostics if d.code == "RPY505"]
    assert not rpy505, (
        f"False RPY505 for built-in channels: {[(d.line_number, d.message) for d in rpy505]}"
    )


def test_stop_unknown_channel_warns(tmp_path: Path):
    """stop <несуществующий канал> -> RPY505 (раньше stop не проверялся вовсе)."""
    code = """
label start:
    stop night_ambience
    return
"""
    result = run_senpy_on_code(code, tmp_path)
    rpy505 = [d for d in result.diagnostics if d.code == "RPY505"]
    assert len(rpy505) == 1 and rpy505[0].line_number == 3, (
        f"Expected RPY505 at line 3, got: {[(d.code, d.line_number) for d in result.diagnostics]}"
    )


def test_stop_channel_from_define_audio_ok(tmp_path: Path):
    """stop титры при define audio.титры — не RPY505 (консистентно с play/queue из Задачи 3)."""
    code = """
define audio.титры = "audio/titles.ogg"

label start:
    stop титры
    return
"""
    result = run_senpy_on_code(code, tmp_path)
    rpy505 = [d for d in result.diagnostics if d.code == "RPY505"]
    assert not rpy505, (
        f"False RPY505 for define audio channel: {[(d.line_number, d.message) for d in rpy505]}"
    )
