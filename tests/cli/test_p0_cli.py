"""Regression-тесты для P0-багов CLI (cli.py).

P0-1: --output-file для text-формата молча игнорировался.
      senpy path/ --output-file report.txt писал в stdout, не в файл.

Контракт после фикса:
- Файл создаётся по пути --output-file
- В файле есть diagnostics-карточки и сводная таблица
- stdout НЕ содержит diagnostics-вывода (только progress "Scanning...")
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests._helpers.paths import REPO_ROOT


def _write_project(tmp_path: Path) -> Path:
    """Минимальный Ren'Py-проект с заведомо известными diagnostic'ами."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(
        """
label start:
    "Hello, [unknown_var]!"   # RPY101: undeclared interpolation
    jump nonexistent_label    # RPY302: broken jump target
    return
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
    )


def test_p0_1_output_file_writes_to_file_for_text_format(tmp_path: Path):
    """P0-1 regression: --output-file для text-формата должен писать в файл.

    До фикса: файл НЕ создавался, diagnostics шли в stdout.
    После фикса: файл создаётся и содержит diagnostics.
    """
    project = _write_project(tmp_path)
    out_file = tmp_path / "report.txt"

    result = _run_cli(["--output-file", str(out_file)], project)

    assert out_file.exists(), (
        f"--output-file для text-формата не создал файл.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )

    content = out_file.read_text(encoding="utf-8")
    assert len(content) > 0, "Файл отчёта пустой"

    assert "RPY" in content, f"В файле нет RPY-кодов. Содержимое:\n{content[:500]}"

    assert (
        "Diagnostics Summary" in content or "Rule" in content
    ), f"В файле нет сводной таблицы. Содержимое:\n{content[:500]}"

    assert (
        "RPY101" not in result.stdout
    ), f"Diagnostic RPY101 утёк в stdout вместо файла:\n{result.stdout}"


def test_p0_1_output_file_creates_parent_directory(tmp_path: Path):
    """P0-1 доп.: --output-file в несуществующей директории должен её создать.

    Раньше open(path, "w") падал с FileNotFoundError, если родительская
    директория не существует (TD-C23). Теперь — makedirs(exist_ok=True).
    """
    project = _write_project(tmp_path)
    nested_out = tmp_path / "reports" / "nested" / "report.txt"

    result = _run_cli(["--output-file", str(nested_out)], project)

    assert (
        nested_out.exists()
    ), f"Вложенная директория не создана.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert nested_out.stat().st_size > 0


def test_p0_1_stdout_works_without_output_file(tmp_path: Path):
    """P0-1 regression: без --output-file поведение не должно измениться.

    Без --output-file diagnostics идут в stdout, как раньше.
    """
    project = _write_project(tmp_path)

    result = _run_cli([], project)

    assert (
        "RPY" in result.stdout
    ), f"Без --output-file diagnostics не пошли в stdout:\n{result.stdout}"


def test_p0_2_stats_does_not_rescan_project(tmp_path: Path):
    """P0-2 regression: --stats не должен создавать второй SenpyAnalyzer.

    До фикса: cli.py:647-648 создавал новый SenpyAnalyzer(args.path) без
    extra_files и без fix=args.fix, теряя декомпилированные файлы и время.
    После фикса: переиспользуется уже готовый analyzer с полным набором.

    Проверяем контракт: monkey-patch SenpyAnalyzer, считаем инстанциации.
    Должна быть ровно 1 инстанциация на весь запуск с --stats.
    """
    project = _write_project(tmp_path)

    test_script = tmp_path / "_count_analyzer.py"
    test_script.write_text(
        """
import os
import sys

# Перехватываем SenpyAnalyzer до импорта cli
from senpy.core.analyzer import SenpyAnalyzer
_original_init = SenpyAnalyzer.__init__
_counter = [0]

def _counting_init(self, *args, **kwargs):
    _counter[0] += 1
    _original_init(self, *args, **kwargs)

SenpyAnalyzer.__init__ = _counting_init

# Подменяем exit, чтобы поймать sys.exit и напечатать счётчик
import builtins
_real_exit = sys.exit
def _capturing_exit(code=0):
    print(f"ANALYZER_INSTANTIATIONS={_counter[0]}", file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
sys.exit = _capturing_exit

# Теперь запускаем CLI
from senpy.cli.main import main
sys.argv = ["senpy", os.environ["PROJECT_PATH"], "--stats", "--output-format", "json"]
try:
    main()
except SystemExit:
    print(f"ANALYZER_INSTANTIATIONS={_counter[0]}", file=sys.stderr)
""",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PROJECT_PATH"] = str(project)
    # PYTHONPATH указывает на корень проекта, чтобы `from senpy.core.analyzer import ...` работал
    env["PYTHONPATH"] = str(REPO_ROOT)

    result = subprocess.run(
        [sys.executable, str(test_script)],
        capture_output=True,
        text=True,
        env=env,
        encoding="utf-8",
    )

    # Должна быть ровно 1 инстанциация (раньше было 2)
    assert "ANALYZER_INSTANTIATIONS=1" in result.stderr, (
        f"Ожидалась 1 инстанциация SenpyAnalyzer, но:\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_p0_2_stats_returns_correct_data(tmp_path: Path):
    """P0-2 доп.: --stats должен вернуть корректные данные после фикса.

    Базовый smoke-тест: --stats --output-format json возвращает JSON с
    ожидаемыми полями. Раньше это работало, но через перескан — теперь
    через переиспользование, контракт не должен измениться.
    """
    import json

    project = _write_project(tmp_path)
    result = _run_cli(["--stats", "--output-format", "json"], project)

    data = json.loads(result.stdout)

    assert "total_dialogue_lines" in data
    assert "total_words" in data
    assert "total_chars" in data
    assert "characters" in data
    assert isinstance(data["characters"], list)

    assert len(data["characters"]) >= 1


import os  # noqa: E402


def _write_traceback_project(tmp_path: Path, filename: str = "errors.txt") -> Path:
    """Проект с краш-логом заданного имени."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(
        """label start:\n    "Hello"\n    return\n""",
        encoding="utf-8",
    )
    # Имитация Ren'Py краш-лога
    (tmp_path / filename).write_text(
        """Full traceback:
  File "game/script.rpy", line 5, in <module>
    "[unknown_var]"
NameError: name 'unknown_var' is not defined
""",
        encoding="utf-8",
    )
    return tmp_path


def test_p0_3_traceback_finds_errors_txt_via_default_const(tmp_path: Path):
    """P0-3 regression: `senpy --traceback` (без аргумента) должен найти errors.txt.

    До фикса: const="traceback.txt" жёстко привязан к traceback.txt.
    После фикса: если traceback.txt не существует — авто-поиск через
    find_latest_traceback (который знает и про errors.txt, и про game/).
    """
    project = _write_traceback_project(tmp_path, filename="errors.txt")
    # Важно: errors.txt есть, traceback.txt нет
    assert (tmp_path / "errors.txt").exists()
    assert not (tmp_path / "traceback.txt").exists()

    result = _run_cli(["--traceback"], project)

    # Должен найти и распарсить
    assert (
        "Traceback Inspector" in result.stdout
    ), f"Не нашли errors.txt через авто-поиск.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    # Должен определить правило RPY104 (NameError)
    assert "RPY104" in result.stdout


def test_p0_3_traceback_explicit_relative_path(tmp_path: Path):
    """P0-3 доп.: --traceback errors.txt (явное относительное имя) должен найтись.

    До фикса: parse_traceback_file("errors.txt") искал только в CWD.
    После фикса: пробуем относительно args.path.
    """
    project = _write_traceback_project(tmp_path, filename="errors.txt")

    result = _run_cli(["--traceback", "errors.txt"], project)

    assert (
        "Traceback Inspector" in result.stdout
    ), f"Явный относительный путь не отрезолвился к args.path.\nstdout:\n{result.stdout}\n"


def test_p0_3_traceback_nonexistent_file_gives_helpful_hint(tmp_path: Path):
    """P0-3 доп.: --traceback /nonexistent — дружелюбное сообщение + hint."""
    project = _write_traceback_project(tmp_path, filename="errors.txt")

    result = _run_cli(["--traceback", "/nonexistent.txt"], project)

    # Должно быть сообщение об ошибке
    assert "Could not find" in result.stdout
    # Должен быть hint
    assert "Hint" in result.stdout


def test_p0_3_traceback_default_const_works_when_traceback_txt_exists(tmp_path: Path):
    """P0-3 regression: обратная совместимость — traceback.txt по-прежнему работает."""
    project = _write_traceback_project(tmp_path, filename="traceback.txt")
    assert (tmp_path / "traceback.txt").exists()

    result = _run_cli(["--traceback"], project)

    assert "Traceback Inspector" in result.stdout
    assert "RPY104" in result.stdout


# =============================================================================
# --fix on read-only file must surface the failure (silent OSError regression)
# =============================================================================


def _write_fixable_project(tmp_path: Path) -> Path:
    """Project whose .rpy file the formatter would rewrite (tabs → spaces)."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(
        "label start:\n\t$x=1\n\treturn\n",
        encoding="utf-8",
    )
    return tmp_path


def _make_readonly(path: Path) -> None:
    path.chmod(0o444)


def _restore_writable(path: Path) -> None:
    try:
        path.chmod(0o644)
    except OSError:
        pass


def test_fix_on_readonly_file_exits_nonzero(tmp_path: Path):
    """``senpy --fix`` on a read-only file must exit 1, not 0.

    Before the fix: ``OSError`` from ``open(..., "w")`` was silently
    swallowed (``except OSError: pass``), the run looked successful, and
    the user believed the fixes were applied.
    """
    project = _write_fixable_project(tmp_path)
    script = project / "game" / "script.rpy"
    _make_readonly(script)
    try:
        result = _run_cli(["--fix", "--no-cache"], project)
    finally:
        _restore_writable(script)

    assert result.returncode != 0, (
        f"--fix on a read-only file must exit non-zero, got 0.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_fix_on_readonly_file_warns_in_output(tmp_path: Path):
    """The user must be told which file could not be written."""
    project = _write_fixable_project(tmp_path)
    script = project / "game" / "script.rpy"
    _make_readonly(script)
    try:
        result = _run_cli(["--fix", "--no-cache"], project)
    finally:
        _restore_writable(script)

    combined = result.stdout + result.stderr
    assert "script.rpy" in combined, (
        f"Output must mention script.rpy as the file that could not be written.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    # Both text and "Failed to write" wording should appear in the warning.
    assert "Failed to write" in combined or "failed to write" in combined.lower(), (
        f"Output must contain a 'Failed to write' warning.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_fix_on_writable_file_exits_zero_when_no_errors(tmp_path: Path):
    """``senpy --fix`` on a writable file with no semantic errors → exit 0.

    Regression guard: the failed-writes exit code must NOT trigger on a
    normal successful fix. Otherwise the new check breaks every working
    ``--fix`` invocation.
    """
    project = _write_fixable_project(tmp_path)
    result = _run_cli(["--fix", "--no-cache"], project)
    assert result.returncode == 0, (
        f"--fix on a writable file with no errors must exit 0, got {result.returncode}.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


# =============================================================================
# --exit-zero must be honoured by every output format (silent exit-code regression)
# =============================================================================


@pytest.mark.parametrize("output_format", ["sarif", "json", "junit", "github", "rdjson", "gitlab"])
def test_exit_zero_forces_exit_0_for_every_format(tmp_path: Path, output_format: str):
    """``senpy --exit-zero --format <X>`` on a project with ERROR diagnostics
    must exit 0, not 1.

    Before the fix only ``render_text`` honoured ``args.exit_zero``; the other
    six renderers returned ``1 if error_count > 0 else 0`` unconditionally.
    Users who wrote ``senpy --exit-zero --format sarif`` for a non-blocking CI
    nightly report got exit 1 — breaking ``continue-on-error`` workflows.
    """
    project = _write_project(tmp_path)
    result = _run_cli(["--exit-zero", "--format", output_format], project)
    assert result.returncode == 0, (
        f"--exit-zero with --format {output_format} must exit 0 even with ERROR diagnostics.\n"
        f"got exit {result.returncode}.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
