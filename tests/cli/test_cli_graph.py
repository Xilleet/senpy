"""TDD-тесты: CLI-контракт --graph для VS Code-расширения.

Расширение (senpy.showStoryGraph) запускает `senpy <root> --graph` через
cp.exec и парсит stdout регулярками ```mermaid```/```senpy-meta```.
До фикса: (а) graph_content вообще не печатался в stdout (ветка печатала
"saved to None!"), (б) rich на Windows-пайпе уходил в legacy-рендерер
и ронял процесс (Senpy Graph Error), (в) piped stdout в cp1251 портил
кириллицу в senpy-meta.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _write_project(tmp_path: Path) -> Path:
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(
        """
screen stats_screen():
    textbutton "Статы" action Jump("stats_label")

label stats_label:
    return

label start:
    call screen stats_screen
""",
        encoding="utf-8",
    )
    return tmp_path


def _run_cli(args: list[str], tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "senpy.cli", str(tmp_path), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


def test_graph_stdout_contains_blocks(tmp_path: Path):
    """--graph без файла: сырые блоки mermaid + senpy-meta в stdout."""
    _write_project(tmp_path)
    proc = _run_cli(["--graph"], tmp_path)

    assert proc.returncode == 0, f"CLI упал: {proc.stderr}"
    assert "```mermaid" in proc.stdout
    assert "graph TD" in proc.stdout
    assert "```senpy-meta" in proc.stdout
    # Экран-участник из Задачи 5 виден в графе
    assert "screen_stats_screen" in proc.stdout


def test_graph_stdout_meta_json_parseable(tmp_path: Path):
    """senpy-meta в stdout — валидный JSON (не размотан soft-wrap'ом rich)."""
    _write_project(tmp_path)
    proc = _run_cli(["--graph"], tmp_path)

    meta_str = proc.stdout.split("```senpy-meta")[1].split("```")[0].strip()
    meta = json.loads(meta_str)
    assert "start" in meta["locations"]
    assert "screen_stats_screen" in meta["locations"]


def test_graph_file_writes_content(tmp_path: Path):
    """--graph-file: файл записан, в stdout нет 'None'."""
    _write_project(tmp_path)
    out_file = tmp_path / "story.md"
    proc = _run_cli(["--graph-file", str(out_file)], tmp_path)

    assert proc.returncode == 0, f"CLI упал: {proc.stderr}"
    content = out_file.read_text(encoding="utf-8")
    assert "```mermaid" in content
    assert "screen_stats_screen" in content
    assert "None" not in proc.stdout
