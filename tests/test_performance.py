from pathlib import Path
from unittest.mock import patch

from senpy.analyzer import SenpyAnalyzer


def test_performance_python_asset_scan_is_localized(tmp_path: Path):
    """Verify _scan_python_assets is only called on Python blocks, avoiding global regex overhead."""
    code = """
label start:
    "Dialogue line 1"
    "Dialogue line 2"
    "Dialogue line 3"
    "Dialogue line 4"
    "Dialogue line 5"
    
    $ renpy.music.play("audio/track1.ogg")
    
    python:
        renpy.music.play("audio/track2.ogg")
        
    "Dialogue line 6"
    "Dialogue line 7"
    return

init python:
    renpy.music.play("audio/track3.ogg")
"""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(code, encoding="utf-8")

    (game_dir / "audio").mkdir()
    (game_dir / "audio" / "track1.ogg").write_bytes(b"dummy")
    (game_dir / "audio" / "track2.ogg").write_bytes(b"dummy")
    (game_dir / "audio" / "track3.ogg").write_bytes(b"dummy")

    analyzer = SenpyAnalyzer(str(tmp_path))

    with patch.object(
        analyzer, "_scan_python_assets", wraps=analyzer._scan_python_assets
    ) as mock_scan:
        result = analyzer.run(quiet=True)

        rpy503_diags = [d for d in result.diagnostics if d.code == "RPY503"]
        assert len(rpy503_diags) == 0

        assert mock_scan.call_count == 3, (
            f"Expected exactly 3 calls to asset scanner, but got {mock_scan.call_count}. Overhead detected!"
        )
