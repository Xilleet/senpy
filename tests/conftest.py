import json
import time
from pathlib import Path

import pytest

_TEST_RESULTS = []
_SESSION_START = 0.0


def pytest_sessionstart(session):
    global _SESSION_START
    _SESSION_START = time.perf_counter()


def pytest_collection_modifyitems(session, config, items):
    """Заменяет техническое имя def на понятный английский заголовок из докстринг."""
    for item in items:
        doc = (item.function.__doc__ or "").strip()
        title = doc.splitlines()[0].strip() if doc else item.name
        item.user_title = title
        # Подменяем nodeid, чтобы именно он печатался в консоли
        item._nodeid = f"{item.path.as_posix()}::{title}"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Собирает результаты каждого теста для отчётов."""
    outcome = yield
    report = outcome.get_result()

    if report.when == "call" or (report.when == "setup" and report.failed):
        title = getattr(item, "user_title", item.name)
        _TEST_RESULTS.append({
            "name": item.name,
            "title": title,
            "status": report.outcome.upper(),  # PASSED, FAILED, SKIPPED
            "duration": round(report.duration, 4),
            "error": str(report.longrepr) if report.failed else None,
        })


def pytest_sessionfinish(session, exitstatus):
    """По завершении тестов сохраняет test_report.txt и test_report.json."""
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
        json.dumps(json_data, indent=2, ensure_ascii=False),
        encoding="utf-8"
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