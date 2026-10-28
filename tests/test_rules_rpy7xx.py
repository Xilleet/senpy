"""Тесты для RPY701-703: Dead code detection (неиспользуемые объявления).

RPY701: Неиспользуемые `define`-константы
RPY702: Неиспользуемые `transform`-определения
RPY703: Неиспользуемые `screen`-определения

Все правила отключаются, если в проекте есть динамические jump'ы
(analyzer.has_dynamic_jumps = True), чтобы избежать ложных срабатываний.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from senpy.analyzer import SenpyAnalyzer


def _run_senpy(code: str, tmp_path: Path, extra_files: dict[str, bytes] | None = None):
    """Вспомогательная функция: сохраняет код и прогоняет Senpy."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)

    if extra_files:
        for rel_path, data in extra_files.items():
            dest = game_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)

    script_file = game_dir / "script.rpy"
    script_file.write_text(code, encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run()
    return result, script_file


# =============================================================================
# RPY701: Неиспользуемые define
# =============================================================================

def test_rpy701_unused_define(tmp_path: Path):
    """RPY701: define без использования → HINT."""
    code = """
define unused_const = 100
define used_const = 200

label start:
    $ player_gold = used_const
    return
"""
    result, _ = _run_senpy(code, tmp_path)
    codes = {d.code for d in result.diagnostics}
    assert "RPY701" in codes, f"RPY701 не сработал на unused define. Codes: {codes}"

    # Проверим, что used_const НЕ вызывает RPY701
    rpy701_diags = [d for d in result.diagnostics if d.code == "RPY701"]
    assert len(rpy701_diags) == 1, f"Ожидался 1 RPY701, получено {len(rpy701_diags)}"
    assert "unused_const" in rpy701_diags[0].message


def test_rpy701_used_define_not_flagged(tmp_path: Path):
    """RPY701: define используется в диалоге — не срабатывает."""
    code = """
define player_name = "Eileen"

label start:
    "Hello, [player_name]!"
    return
"""
    result, _ = _run_senpy(code, tmp_path)
    rpy701_diags = [d for d in result.diagnostics if d.code == "RPY701"]
    assert len(rpy701_diags) == 0, f"RPY701 не должен срабатывать на used define: {rpy701_diags}"


def test_rpy701_define_character_not_flagged(tmp_path: Path):
    """RPY701: Character define не срабатывает (они используются косвенно)."""
    code = """
define s = Character("Sayori")

label start:
    s "Hello!"
    return
"""
    result, _ = _run_senpy(code, tmp_path)
    rpy701_diags = [d for d in result.diagnostics if d.code == "RPY701"]
    assert len(rpy701_diags) == 0, f"Character define не должен давать RPY701: {rpy701_diags}"


# =============================================================================
# RPY702: Неиспользуемые transform
# =============================================================================

def test_rpy702_unused_transform(tmp_path: Path):
    """RPY702: transform без использования в show/scene at → HINT."""
    code = """
transform unused_slide:
    easein 0.5 xoffset 0

transform used_fade:
    easeout 0.5 alpha 0.0

label start:
    show bg room at used_fade
    return
"""
    result, _ = _run_senpy(code, tmp_path)
    codes = {d.code for d in result.diagnostics}
    assert "RPY702" in codes, f"RPY702 не сработал на unused transform. Codes: {codes}"

    rpy702_diags = [d for d in result.diagnostics if d.code == "RPY702"]
    assert len(rpy702_diags) == 1, f"Ожидался 1 RPY702, получено {len(rpy702_diags)}"
    assert "unused_slide" in rpy702_diags[0].message


def test_rpy702_used_transform_not_flagged(tmp_path: Path):
    """RPY702: transform используется — не срабатывает."""
    code = """
transform slide_in:
    easein 0.5 xoffset 0

label start:
    show sayori happy at slide_in
    return
"""
    result, _ = _run_senpy(code, tmp_path)
    rpy702_diags = [d for d in result.diagnostics if d.code == "RPY702"]
    assert len(rpy702_diags) == 0, f"Used transform не должен давать RPY702: {rpy702_diags}"


# =============================================================================
# RPY703: Неиспользуемые screen
# =============================================================================

def test_rpy703_unused_screen(tmp_path: Path):
    """RPY703: screen без call/use/Show → HINT."""
    code = """
screen unused_screen():
    textbutton "Do nothing" action NullAction()

screen used_screen():
    textbutton "Start" action Start()

label start:
    call screen used_screen
    return
"""
    result, _ = _run_senpy(code, tmp_path)
    codes = {d.code for d in result.diagnostics}
    assert "RPY703" in codes, f"RPY703 не сработал на unused screen. Codes: {codes}"

    rpy703_diags = [d for d in result.diagnostics if d.code == "RPY703"]
    assert len(rpy703_diags) == 1, f"Ожидался 1 RPY703, получено {len(rpy703_diags)}"
    assert "unused_screen" in rpy703_diags[0].message


def test_rpy703_used_screen_not_flagged(tmp_path: Path):
    """RPY703: screen используется через `use` — не срабатывает."""
    code = """
screen my_screen():
    text "Hello"

screen main_menu():
    use my_screen
"""
    result, _ = _run_senpy(code, tmp_path)
    rpy703_diags = [d for d in result.diagnostics if d.code == "RPY703"]
    assert len(rpy703_diags) == 0, f"Used screen не должен давать RPY703: {rpy703_diags}"


def test_rpy703_screen_used_via_show_action(tmp_path: Path):
    """RPY703: screen используется через Show action — не срабатывает."""
    code = """
screen my_screen():
    text "Hello"

label start:
    $ renpy.show_screen("my_screen")
    return
"""
    result, _ = _run_senpy(code, tmp_path)
    rpy703_diags = [d for d in result.diagnostics if d.code == "RPY703"]
    assert len(rpy703_diags) == 0, f"Show screen не должен давать RPY703: {rpy703_diags}"


# =============================================================================
# Отключение при динамических jump'ах
# =============================================================================

def test_rpy701_703_disabled_with_dynamic_jumps(tmp_path: Path):
    """RPY701-703 отключаются, если есть динамические jump'ы."""
    code = """
define unused_const = 100
transform unused_slide:
    easein 0.5 xoffset 0
screen unused_screen():
    pass

label start:
    $ target = "chapter_" + str(chapter)
    jump expression target
    return
"""
    result, _ = _run_senpy(code, tmp_path)
    codes = {d.code for d in result.diagnostics}
    assert "RPY701" not in codes, f"RPY701 должен быть отключён при dynamic jumps: {codes}"
    assert "RPY702" not in codes, f"RPY702 должен быть отключён при dynamic jumps: {codes}"
    assert "RPY703" not in codes, f"RPY703 должен быть отключён при dynamic jumps: {codes}"


# =============================================================================
# Регрессионный тест производительности (PERF-2)
# =============================================================================

def test_rpy7xx_performance_large_project(tmp_path: Path):
    """PERF-2: _check_unused_declarations должен быть O(N+M), а не O(N*M).

    Регрессия: изначальная реализация для каждого символа пробегала по всем
    строкам всех файлов с re.search — на DDLC (50 файлов, 77k строк) это
    приводило к зависанию на десятки секунд / минуту.

    Тест создаёт проект, имитирующий структуру DDLC по масштабу:
    - 50 .rpy файлов
    - ~1500 строк на файл (итого ~75k строк)
    - 200 define-констант, 100 transform, 100 screen (из них половина неиспользуемые)

    Алгоритм O(N+M) должен справляться за <5 секунд на любой разумной машине.
    Старый O(N*M) занял бы минуты.
    """
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)

    # Генерируем 50 файлов с ~1500 строк каждый
    num_files = 50
    lines_per_file = 1500
    num_defines = 200
    num_transforms = 100
    num_screens = 100

    # Стартовый файл с использованием половины символов (чтобы проверить, что
    # used-символы не вызывают RPY701-703)
    for f_idx in range(num_files):
        lines = []
        # Каждый файл содержит объявления define/transform/screen
        for i in range(num_defines // num_files + 1):
            n = f_idx * (num_defines // num_files + 1) + i
            if n >= num_defines:
                break
            # Чётные — used (используются в label), нечётные — unused
            if n % 2 == 0:
                lines.append(f"define const_{n} = {n}")
            else:
                lines.append(f"define unused_const_{n} = {n}")

        for i in range(num_transforms // num_files + 1):
            n = f_idx * (num_transforms // num_files + 1) + i
            if n >= num_transforms:
                break
            if n % 2 == 0:
                lines.append(f"transform tr_{n}:\n    easein 0.5 xoffset 0")
            else:
                lines.append(f"transform unused_tr_{n}:\n    easein 0.5 xoffset 0")

        for i in range(num_screens // num_files + 1):
            n = f_idx * (num_screens // num_files + 1) + i
            if n >= num_screens:
                break
            if n % 2 == 0:
                lines.append(f"screen scr_{n}():\n    text \"hello\"")
            else:
                lines.append(f"screen unused_scr_{n}():\n    text \"hello\"")

        # Используем чётные символы в label
        lines.append("label start:")
        for i in range(0, num_defines, 2):
            if f_idx == i % num_files:
                lines.append(f"    $ x = const_{i}")
        for i in range(0, num_transforms, 2):
            if f_idx == i % num_files:
                lines.append(f"    show bg at tr_{i}")
        for i in range(0, num_screens, 2):
            if f_idx == i % num_files:
                lines.append(f"    call screen scr_{i}")
        lines.append("    return")

        # Дополняем до lines_per_file строками-комментариями
        while len(lines) < lines_per_file:
            lines.append(f"    # padding line {len(lines)}")

        (game_dir / f"script_{f_idx:03d}.rpy").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    analyzer = SenpyAnalyzer(str(tmp_path))

    start = time.monotonic()
    result = analyzer.run()
    elapsed = time.monotonic() - start

    # Проверяем, что unused-символы действительно найдены (т.е. проверка реально
    # выполнилась, а не была отключена из-за has_dynamic_jumps)
    codes = {d.code for d in result.diagnostics}
    assert "RPY701" in codes, "RPY701 должен сработать на неиспользуемых define"
    assert "RPY702" in codes, "RPY702 должен сработать на неиспользуемых transform"
    assert "RPY703" in codes, "RPY703 должен сработать на неиспользуемых screen"

    # Главный ассерт: вся обработка (включая _check_unused_declarations)
    # должна уложиться в 10 секунд. Старый O(N*M) занял бы минуты.
    # 10 секунд — щадящий лимит, чтобы не флапать на медленных CI.
    assert elapsed < 10.0, (
        f"_check_unused_declarations слишком медленный ({elapsed:.2f}с на "
        f"{num_files} файлов × {lines_per_file} строк). "
        f"Вероятно, регрессия O(N+M) → O(N*M)."
    )
