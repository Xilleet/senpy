from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from senpy.core.analyzer import SenpyAnalyzer

# Путь к папке с фикстурами: tests/fixtures/rules/
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "rules"


def get_fixture_files() -> list[Path]:
    """Собирает все .rpy файлы из директорий фикстур."""
    if not FIXTURES_DIR.exists():
        return []
    return list(FIXTURES_DIR.rglob("*.rpy"))


def normalize_diagnostics(diagnostics: list) -> list[dict[str, Any]]:
    """Нормализует диагностики для сохранения в JSON, отсекая нестабильные абсолютные пути."""
    result = []
    for d in diagnostics:
        result.append(
            {
                "code": d.code,
                "severity": d.severity,
                "line": d.line_number,
                "message_fragment": d.message[:100],  # Сохраняем стабильный фрагмент
                # В будущем сюда можно добавить проверку col и end_col, если нужно
            }
        )
    # Сортируем по строке, чтобы порядок всегда был детерминированным
    return sorted(result, key=lambda x: x["line"])


@pytest.mark.parametrize("rpy_file", get_fixture_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_rule_fixture(rpy_file: Path, update_snapshots: bool, tmp_path: Path):
    rule_id = rpy_file.parent.name  # Ожидаем структуру: fixtures/rules/RPYxxx/bad_1.rpy
    is_bad = rpy_file.name.startswith("bad_")

    # Изолируем запуск, копируя тестируемый файл во временную директорию
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    test_file = game_dir / rpy_file.name
    test_file.write_text(rpy_file.read_text(encoding="utf-8"), encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)

    # Фильтруем диагностики только по целевому правилу (чтобы изолировать тесты друг от друга)
    target_diags = [d for d in result.diagnostics if d.code == rule_id]

    if not is_bad:
        # Для позитивных тестов мы ожидаем ровно 0 ошибок по этому правилу
        assert len(target_diags) == 0, (
            f"Expected 0 '{rule_id}' diagnostics for positive test {rpy_file.name}, but got: {target_diags}"
        )
    else:
        # Для негативных тестов сверяем снимок
        snapshot_file = rpy_file.with_suffix(".json")
        actual_json = normalize_diagnostics(target_diags)

        if update_snapshots:
            # Режим обновления: генерируем/перезаписываем JSON
            snapshot_file.write_text(
                json.dumps(actual_json, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            pytest.skip(f"Snapshot updated for {rpy_file.name}")
        else:
            # Обычный режим: сравниваем результат с диском
            assert snapshot_file.exists(), (
                f"Snapshot is missing: {snapshot_file}. Run pytest with '--update-snapshots'."
            )
            expected_json = json.loads(snapshot_file.read_text(encoding="utf-8"))
            assert actual_json == expected_json, (
                f"Snapshot mismatch for {rpy_file.name}. Run with '--update-snapshots' if the change was intentional."
            )
