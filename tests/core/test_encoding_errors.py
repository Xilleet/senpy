"""TDD-тест: молчаливый пропуск файлов с битой кодировкой.

До фикса UnicodeDecodeError глох в `except (UnicodeDecodeError, OSError): pass`
в analyzer.py — файл в cp1251 молча выпадал из анализа, и линтер рапортовал
«проект чист», хотя Ren'Py упадёт на загрузке такого скрипта.
"""

from __future__ import annotations

from pathlib import Path

from senpy.core.analyzer import SenpyAnalyzer


def make_broken_main(tmp_path: Path) -> None:
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    broken = 'label start:\n    "Привет"\n    jump finale\n'.encode("cp1251")
    (game_dir / "broken.rpy").write_bytes(broken)


def test_broken_utf8_main_file_reported(tmp_path: Path):
    """cp1251-файл больше не молчит: ровно один RPY100 ERROR"""
    make_broken_main(tmp_path)
    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)
    rpy100 = [d for d in result.diagnostics if d.code == "RPY100"]
    assert len(rpy100) == 1, f"Ожидался ровно один RPY100, есть: {result.diagnostics}"
    assert rpy100[0].severity == "ERROR"
    assert rpy100[0].file_path.replace("\\", "/").endswith("broken.rpy")


def test_broken_utf8_tl_file_reported(tmp_path: Path):
    """cp1251-файл в game/tl/ ловится через _analyze_tl_file (второй эмиссионный путь)"""
    make_broken_main(tmp_path)
    tl_dir = tmp_path / "game" / "tl" / "russian"
    tl_dir.mkdir(parents=True, exist_ok=True)
    broken_tl = 'label broken_tl:\n    old "Привет"\n    new "Hi"\n'.encode("cp1251")
    (tl_dir / "script.rpy").write_bytes(broken_tl)
    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)
    rpy100 = [d for d in result.diagnostics if d.code == "RPY100"]
    assert len(rpy100) == 2, f"Ожидались RPY100 на оба файла, есть: {[d.file_path for d in rpy100]}"


def test_rpy100_survives_warm_run(tmp_path: Path):
    """Кэш-детерминизм: битый файл не кэшируется -> RPY100 и на тёплом прогоне"""
    make_broken_main(tmp_path)
    (tmp_path / "game" / "valid.rpy").write_text(
        'default score = 0\n\nlabel start:\n    "ок"\n', encoding="utf-8"
    )
    r1 = SenpyAnalyzer(str(tmp_path)).run(quiet=True)
    r2 = SenpyAnalyzer(str(tmp_path)).run(quiet=True)
    assert any(d.code == "RPY100" for d in r1.diagnostics), "Холодный прогон потерял RPY100"
    assert any(d.code == "RPY100" for d in r2.diagnostics), "Тёплый прогон потерял RPY100"


def test_valid_files_no_rpy100(tmp_path: Path):
    """Замок: валидный UTF-8 проект не получает RPY100"""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(
        'default score = 0\n\nlabel start:\n    "Привет, мир."\n    jump finale\n\nlabel finale:\n    return\n',
        encoding="utf-8",
    )
    result = SenpyAnalyzer(str(tmp_path)).run(quiet=True)
    assert not [d for d in result.diagnostics if d.code == "RPY100"]
