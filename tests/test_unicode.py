"""TDD-тесты для ASCII / Unicode (кириллица) в именах символов."""

from __future__ import annotations

from pathlib import Path

from senpy.analyzer import SenpyAnalyzer


def run_senpy_on_code(code: str, tmp_path: Path):
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(code, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    return analyzer.run(quiet=True), analyzer


SCRIPT_ASCII = """
default health = 100
define counter = 0

label finale:
    return

label start:
    $ health += 1
    "Health: [health], counter: [counter]."
    jump finale
"""

SCRIPT_CYRILLIC = """
default здоровье = 100
define счётчик = 0

label финиш:
    return

label start:
    $ здоровье += 1
    "Здоровье: [здоровье], счётчик: [счётчик]."
    jump финиш
"""


def test_cyrillic_no_false_errors(tmp_path: Path):
    """Кириллица: нет ложных ERROR на default/jump/интерполяции"""
    result, _ = run_senpy_on_code(SCRIPT_CYRILLIC, tmp_path)
    errors = [d for d in result.diagnostics if d.severity == "ERROR"]
    assert errors == [], f"Ложные ERROR на кириллице: {errors}"


def test_cyrillic_ascii_parity(tmp_path: Path):
    """Паритет: кириллический код даёт те же коды диагностик, что ASCII-аналог"""
    result_ascii, _ = run_senpy_on_code(SCRIPT_ASCII, tmp_path)
    result_cyr, _ = run_senpy_on_code(SCRIPT_CYRILLIC, tmp_path)
    codes_ascii = sorted(d.code for d in result_ascii.diagnostics)
    codes_cyr = sorted(d.code for d in result_cyr.diagnostics)
    assert codes_cyr == codes_ascii, f"Паритет нарушен: ASCII={codes_ascii}, Cyrillic={codes_cyr}"


def test_cyrillic_symbols_registered(tmp_path: Path):
    """Реестры анализатора наполнены кириллическими символами (паритет регистрации)"""
    _, analyzer = run_senpy_on_code(SCRIPT_CYRILLIC, tmp_path)
    assert "здоровье" in analyzer.variables, "default-переменная не зарегистрирована"
    assert "счётчик" in analyzer.variables, "define-переменная не зарегистрирована"
    assert "финиш" in analyzer.labels, "label не зарегистрирован"
    assert "start" in analyzer.labels


SCRIPT_ASCII_TYPO = """
default health = 100

screen ui:
    textbutton "H" action SetVariable("helth", 5)
    textbutton "S" action Show("missing_scr")
    textbutton "C" action Jump("no_such_label")

label start:
    call screen ui
    return
"""

SCRIPT_CYRILLIC_TYPO = """
default здоровье = 100

screen менюшка:
    textbutton "З" action SetVariable("здороьбе", 5)
    textbutton "Э" action Show("нет_экрана")
    textbutton "П" action Jump("нет_лейбла")

label start:
    call screen менюшка
    return
"""


def test_action_string_args_cyrillic_parity(tmp_path: Path):
    """Опечатки в строковых аргументах экшенов ловятся одинаково для ASCII и кириллицы"""
    result_ascii, _ = run_senpy_on_code(SCRIPT_ASCII_TYPO, tmp_path)
    result_cyr, _ = run_senpy_on_code(SCRIPT_CYRILLIC_TYPO, tmp_path)
    codes_ascii = sorted(d.code for d in result_ascii.diagnostics)
    codes_cyr = sorted(d.code for d in result_cyr.diagnostics)
    assert codes_ascii, "ASCII-контроль должен ловить опечатки, иначе тест бессмыслен"
    assert codes_cyr == codes_ascii, f"Паритет нарушен: ASCII={codes_ascii}, Cyrillic={codes_cyr}"


def test_cyrillic_audio_channel_registered(tmp_path: Path):
    """Свой аудио-канал с кириллическим именем: play по нему не должен давать RPY505"""
    (tmp_path / "game").mkdir(parents=True, exist_ok=True)
    (tmp_path / "game" / "song.ogg").write_bytes(b"dummy")
    code = """
init python:
    renpy.music.register_channel("музыка", "music", loop=True)

label start:
    play музыка "song.ogg"
    return
"""
    result, _ = run_senpy_on_code(code, tmp_path)
    rpy505 = [d for d in result.diagnostics if d.code == "RPY505"]
    assert rpy505 == [], f"Ложный RPY505 на зарегистрированном канале: {rpy505}"
