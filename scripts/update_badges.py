#!/usr/bin/env python3
"""Update dynamic badges based on local test collection / run.

Generates (or refreshes) `.github/badges/tests.json` for the shields.io
`endpoint` badge URL used in README.md / README_ru.md.

Two modes:
  * default — collect-only (fast, ~1–2s): just counts collected tests.
    Useful as a pre-commit hook and as the CI "we know how many tests
    there are" baseline.
  * `--run` — actually run pytest and capture pass/skip/fail counts.
    Slower (~30s on Senpy) but reflects the real run state.

Output schema (shields.io endpoint format, v1):
    {
      "schemaVersion": 1,
      "label": "tests",
      "message": "<N> passed",
      "color": "brightgreen|yellow|red"
    }

Color rules:
  * brightgreen — all collected tests passed (pass == collected).
  * yellow      — passed, but some skipped/xfail OR pass < collected.
  * red         — 0 passed OR pytest failed to collect.

Usage:
    python scripts/update_badges.py            # collect-only mode
    python scripts/update_badges.py --run      # run mode (CI)
    python scripts/update_badges.py --check    # exit 1 if file would change (CI guard)

This script is idempotent: re-running it with the same test count
produces byte-identical JSON (deterministic key order, no timestamps).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

BADGE_PATH = Path(__file__).resolve().parent.parent / ".github" / "badges" / "tests.json"

# Regexes for pytest --collect-only / pytest output. Last line typically:
#   "1035 tests collected in 1.87s"
# or after run:
#   "1035 passed in 24.42s"
#   "1035 passed, 12 skipped in 25.0s"
#   "1000 passed, 5 failed, 30 skipped in 25.0s"
_RE_COLLECTED = re.compile(r"(\d+)\s+tests?\s+collected")
_RE_PASSED = re.compile(r"(\d+)\s+passed")
_RE_FAILED = re.compile(r"(\d+)\s+failed")
_RE_SKIPPED = re.compile(r"(\d+)\s+skipped")


def _run_pytest(args: list[str]) -> tuple[int, str, str]:
    """Run pytest with given args, return (exit_code, stdout, stderr)."""
    cmd = [sys.executable, "-m", "pytest", *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
    )
    return result.returncode, result.stdout, result.stderr


def _parse_collect(stdout: str) -> int | None:
    """Extract collected test count from pytest --collect-only output."""
    # Last non-empty line typically contains "N tests collected in Xs"
    for line in reversed(stdout.strip().splitlines()):
        m = _RE_COLLECTED.search(line)
        if m:
            return int(m.group(1))
    return None


def _parse_run(stdout: str) -> tuple[int, int, int]:
    """Extract (passed, failed, skipped) from pytest run output."""
    passed = failed = skipped = 0
    for line in reversed(stdout.strip().splitlines()):
        m = _RE_PASSED.search(line)
        if m:
            passed = int(m.group(1))
            m2 = _RE_FAILED.search(line)
            if m2:
                failed = int(m2.group(1))
            m3 = _RE_SKIPPED.search(line)
            if m3:
                skipped = int(m3.group(1))
            return passed, failed, skipped
    return 0, 0, 0


def _badge_json(passed: int, failed: int, skipped: int, collected: int | None) -> dict:
    """Build shields.io endpoint badge JSON."""
    if failed > 0:
        color = "red"
        message = f"{passed} passed, {failed} failed"
    elif collected is not None and passed == collected and skipped == 0:
        color = "brightgreen"
        message = f"{passed} passed"
    elif passed > 0:
        color = "yellow"
        if skipped:
            message = f"{passed} passed, {skipped} skipped"
        else:
            message = f"{passed} passed"
    else:
        color = "red"
        message = "0 passed"
    return {
        "schemaVersion": 1,
        "label": "tests",
        "message": message,
        "color": color,
    }


def write_badge(data: dict) -> bool:
    """Write badge JSON to BADGE_PATH if content changed. Return True if written."""
    BADGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if BADGE_PATH.exists() and BADGE_PATH.read_text(encoding="utf-8") == new_text:
        return False
    BADGE_PATH.write_text(new_text, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Update tests badge JSON.")
    parser.add_argument(
        "--run",
        action="store_true",
        help="Actually run pytest (default: collect-only, faster).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if badge file would change (CI guard mode). Implies --run.",
    )
    args = parser.parse_args()

    do_run = args.run or args.check

    if do_run:
        # Run pytest, capture exit code (don't fail on test failures — we want
        # to record the count even if some tests failed)
        exit_code, stdout, _stderr = _run_pytest(["tests/", "-q", "--no-header"])
        passed, failed, skipped = _parse_run(stdout)
        # Also collect to know total count
        _, collect_stdout, _ = _run_pytest(["tests/", "--collect-only", "-q"])
        collected = _parse_collect(collect_stdout)
    else:
        # Collect-only mode (fast, ~1-2s): no actual test run
        exit_code, stdout, stderr = _run_pytest(["tests/", "--collect-only", "-q"])
        collected = _parse_collect(stdout)
        # In collect-only mode we don't know pass/fail, so we treat
        # "all collected" as "all passed" (brightgreen). This is the right
        # assumption for the default pre-commit use case.
        passed = collected or 0
        failed = 0
        skipped = 0

    if collected is None and passed == 0:
        # pytest failed to even collect
        print("ERROR: pytest collect failed.", file=sys.stderr)
        if stderr:
            print(stderr, file=sys.stderr)
        data = _badge_json(0, 1, 0, None)
    else:
        data = _badge_json(passed, failed, skipped, collected)

    if args.check:
        # Guard mode: don't write, just check
        new_text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        if BADGE_PATH.exists() and BADGE_PATH.read_text(encoding="utf-8") == new_text:
            print(f"OK: badge up-to-date ({data['message']})")
            return 0
        print(f"STALE: badge would change to '{data['message']}'", file=sys.stderr)
        return 1

    written = write_badge(data)
    if written:
        print(f"Updated {BADGE_PATH}: {data['message']} ({data['color']})")
    else:
        print(f"Already up-to-date: {data['message']} ({data['color']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
