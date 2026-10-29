"""Pytest configuration и hooks для Senpy.

Этот файл — замена старому conftest.py. Главное изменение (P0'-9):

    БОЛЬШЕ НЕ ПОДМЕНЯЕМ item._nodeid через private pytest API.

Раньше строка `item._nodeid = f"{item.path.as_posix()}::{title}"` ломала:
    - `pytest -k "test_p0_1"` — поиск по подстроке nodeid не находил тест
    - `pytest --lf` (last failed) — мог работать некорректно
    - IDE интеграции (PyCharm, VS Code Test Explorer) — путались в nodeid

Теперь используется `item.user_title` — это официальный pytest API
для отображения пользовательского имени в отчётах. nodeid остаётся
оригинальным (`tests/test_x.py::test_function_name`), а user_title
добавляется как метаданные для отчётов.

Если вам нужно красивое имя в консоли — используйте `pytest --tb=short`
или кастомный reporter через `pytest_report_header` / `pytest_runtest_logreport`.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

_TEST_RESULTS: list[dict] = []
_SESSION_START: float = 0.0


def pytest_sessionstart(session: pytest.Session) -> None:
    """Фиксируем время старта сессии."""
    global _SESSION_START
    _SESSION_START = time.perf_counter()


def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    """P0'-9: НЕ подменяем nodeid, а используем user_title (официальный pytest API).

    Раньше тут было:
        item._nodeid = f"{item.path.as_posix()}::{title}"
    Что ломало `-k`, `--lf`, IDE интеграции.

    Теперь: сохраняем user_title как метаданные для отчётов
    (test_report.json/txt, генерируемых в pytest_sessionfinish).
    nodeid остаётся оригинальным.
    """
    for item in items:
        doc = (item.function.__doc__ or "").strip()  # type: ignore[attr-defined]
        title = doc.splitlines()[0].strip() if doc else item.name
        # Сохраняем как атрибут — отчёты будут использовать user_title.
        # nodeid НЕ трогаем — это private pytest API.
        item.user_title = title  # type: ignore[attr-defined]


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo
) -> object:
    """Собирает результаты каждого теста для отчётов."""
    outcome = yield
    report: pytest.TestReport = outcome.get_result()

    if report.when == "call" or (report.when == "setup" and report.failed):
        title = getattr(item, "user_title", item.name)
        _TEST_RESULTS.append(
            {
                "name": item.name,
                "title": title,
                "status": report.outcome.upper(),  # PASSED, FAILED, SKIPPED
                "duration": round(report.duration, 4),
                "error": str(report.longrepr) if report.failed else None,
            }
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """По завершении тестов сохраняет test_report.txt и test_report.json.

    Эти файлы добавлены в .gitignore — НЕ коммитятся (P0'-12 fix).
    Генерируются только для локального просмотра.
    """
    total_duration = time.perf_counter() - _SESSION_START
    total = len(_TEST_RESULTS)
    passed = sum(1 for r in _TEST_RESULTS if r["status"] == "PASSED")
    failed = sum(1 for r in _TEST_RESULTS if r["status"] == "FAILED")
    skipped = sum(1 for r in _TEST_RESULTS if r["status"] == "SKIPPED")

    overall_status = "ALL PASSED" if failed == 0 else "FAILED"

    # 1. Генерируем test_report.json
    json_data = {
        "summary": {
            "status": overall_status,
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "duration_sec": round(total_duration, 3),
        },
        "tests": [
            {
                "function": r["name"],
                "title": r["title"],
                "status": r["status"],
                "duration_sec": r["duration"],
                "error": r["error"],
            }
            for r in _TEST_RESULTS
        ],
    }
    Path("test_report.json").write_text(
        json.dumps(json_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 2. Генерируем test_report.txt
    txt_lines = [
        "=" * 60,
        f"SENPY TEST REPORT - {overall_status}",
        "=" * 60,
        f"Total Tests:  {total}",
        f"Passed:       {passed}",
        f"Failed:       {failed}",
        f"Skipped:      {skipped}",
        f"Duration:     {total_duration:.3f}s",
        "=" * 60,
        "\nTEST EXECUTION DETAILS:",
    ]

    for r in _TEST_RESULTS:
        icon = "[PASS]" if r["status"] == "PASSED" else "[FAIL]"
        txt_lines.append(f"  {icon} {r['title']} ({r['duration']}s)")

    if failed > 0:
        txt_lines.append("\n" + "=" * 60)
        txt_lines.append("DETAILS OF FAILURES:")
        txt_lines.append("=" * 60)
        for i, r in enumerate((t for t in _TEST_RESULTS if t["status"] == "FAILED"), 1):
            txt_lines.append(f"\n[{i}] {r['title']}")
            txt_lines.append(f"    Function: {r['name']}")
            txt_lines.append("-" * 40)
            txt_lines.append(r["error"] or "Unknown error")
            txt_lines.append("-" * 40)

    Path("test_report.txt").write_text("\n".join(txt_lines), encoding="utf-8")


def pytest_addoption(parser: pytest.Parser) -> None:
    """Добавляем флаг для автоматического обновления JSON-снимков."""
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Update JSON snapshots for fixture tests",
    )


@pytest.fixture
def update_snapshots(request: pytest.FixtureRequest) -> bool:
    """Fixture: возвращает True если передан --update-snapshots."""
    return request.config.getoption("--update-snapshots")


@pytest.fixture(autouse=True)
def _clean_lsp_state_after_test():
    """Autouse fixture: чистит LSP-серверный state после каждого теста.

    Проблема: LSP-тесты (test_lsp*, test_ux_ext_5_6_7, ...) мутируют
    module-level state в senpy.lsp.server (_active_analyzer, _change_timer,
    _full_timer, _lsp_server.change_timers). Если тест создаёт реальный
    timer (не замоканный) и не отменяет его — timer срабатывает через
    0.15-0.3s в фоновом потоке, вызывая run_single_file_diagnostics или
    run_full_project_diagnostics. На Windows это может упасть с
    ValueError: path is on mount 'D:', start on mount 'C:' (cross-mount
    relpath), что проявляется как PytestUnhandledThreadExceptionWarning
    в последующих test_p0_cli тестах.

    Решение: после каждого теста отменяем все pending timer'ы и сбрасываем
    LSP state. Это не влияет на тесты, которые используют patch() для
    mock'а schedule_* — patch восстанавливается автоматически.
    """
    yield  # тест выполняется здесь

    # Cleanup после теста
    try:
        import senpy.lsp.server as server_mod
        # Отменим все timer'ы
        if getattr(server_mod, "_full_timer", None) is not None:
            try:
                server_mod._full_timer.cancel()
            except Exception:
                pass
            server_mod._full_timer = None
        if getattr(server_mod, "_change_timer", None) is not None:
            try:
                server_mod._change_timer.cancel()
            except Exception:
                pass
            server_mod._change_timer = None
        # Per-URI timer'ы
        lsp_server = getattr(server_mod, "_lsp_server", None)
        if lsp_server is not None and hasattr(lsp_server, "change_timers"):
            for t in list(lsp_server.change_timers.values()):
                try:
                    t.cancel()
                except Exception:
                    pass
            lsp_server.change_timers.clear()
    except ImportError:
        # senpy.lsp.server ещё не импортирован этим тестом — ничего не делаем
        pass
