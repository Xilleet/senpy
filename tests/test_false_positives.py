from __future__ import annotations

from pathlib import Path

from senpy.analyzer import SenpyAnalyzer


def run_senpy_on_code(code: str, tmp_path: Path):
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    script_file = game_dir / "script.rpy"
    script_file.write_text(code, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)
    return result

def test_fp_ignore_noqa_comments(tmp_path: Path):
    """Verify # noqa comments correctly suppress targeted warnings"""
    code = """
label start:
    $ bad_var += 1      # noqa: RPY102
    "Unclosed {b}tag"   # senpy: ignore[RPY301]
    return
"""
    result = run_senpy_on_code(code, tmp_path)
    # Ошибки есть, но они подавлены через noqa, значит результат должен быть пуст!
    assert len(result.diagnostics) == 0

def test_fp_python_assets_not_flagged_as_unused(tmp_path: Path):
    """Verify assets referenced purely in Python blocks do not trigger false RPY503"""
    code = """
label start:
    $ renpy.music.play("audio/secret_track.ogg")
    python:
        renpy.show("images/hidden_bg.png")
    return
"""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    
    (game_dir / "audio").mkdir()
    (game_dir / "audio" / "secret_track.ogg").write_bytes(b"dummy")
    (game_dir / "images").mkdir()
    (game_dir / "images" / "hidden_bg.png").write_bytes(b"dummy")
    
    result = run_senpy_on_code(code, tmp_path)
    rpy503_diags = [d for d in result.diagnostics if d.code == "RPY503"]
    assert len(rpy503_diags) == 0, f"False RPY503 for Python assets: {rpy503_diags}"