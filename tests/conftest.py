import json
import time
from pathlib import Path

# Засекаем время старта независимо от версии pytest
_SESSION_START = time.time()


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Хук pytest: автоматически сохраняет результаты прогона в test_report.json и test_report.txt"""
    passed = len(terminalreporter.stats.get("passed", []))
    failed = len(terminalreporter.stats.get("failed", []))
    skipped = len(terminalreporter.stats.get("skipped", []))
    total = passed + failed + skipped

    duration = max(0.0, time.time() - _SESSION_START)

    failures_detail = []
    for rep in terminalreporter.stats.get("failed", []):
        failures_detail.append({
            "test": rep.nodeid,
            "message": str(rep.longrepr),
        })

    # 1. Генерация JSON-отчёта
    report_data = {
        "status": "PASSED" if exitstatus == 0 else "FAILED",
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "duration_sec": round(duration, 3),
        },
        "failures": failures_detail,
    }

    Path("test_report.json").write_text(
        json.dumps(report_data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # 2. Генерация TXT-отчёта
    txt_lines = [
        "=" * 60,
        f"SENPY TEST REPORT - {'ALL PASSED' if exitstatus == 0 else 'FAILED'}",
        "=" * 60,
        f"Total Tests:  {total}",
        f"Passed:       {passed}",
        f"Failed:       {failed}",
        f"Skipped:      {skipped}",
        f"Duration:     {duration:.3f}s",
        "=" * 60,
    ]

    if failures_detail:
        txt_lines.append("\nDETAILS OF FAILURES:")
        for idx, f in enumerate(failures_detail, start=1):
            txt_lines.append(f"\n[{idx}] {f['test']}")
            txt_lines.append("-" * 40)
            txt_lines.append(f["message"])
            txt_lines.append("-" * 40)

    Path("test_report.txt").write_text("\n".join(txt_lines), encoding="utf-8")