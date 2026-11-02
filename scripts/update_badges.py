#!/usr/bin/env python3
"""Update dynamic badges for Senpy.

Generates JSON badge files in `.github/badges/` for shields.io `endpoint`
badge URLs used in README.md / README_ru.md.

Badges generated:
  * tests.json       — test count (pass/fail/skip) from pytest
  * rules.json       — lint rule count from RULES_DATABASE
  * lsp.json         — LSP handler count (public functions in handlers/)
  * coverage.json    — coverage % from pytest --cov
  * speed.json       — cold/warm analysis speed (generative .rpy benchmark)

Usage:
    python scripts/update_badges.py            # collect-only tests + static badges
    python scripts/update_badges.py --run      # full run (tests + coverage + speed)
    python scripts/update_badges.py --check    # exit 1 if any badge would change

This script is idempotent: re-running with the same data produces
byte-identical JSON (deterministic key order, no timestamps).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BADGES_DIR = REPO_ROOT / ".github" / "badges"

# Regexes for pytest output
_RE_COLLECTED = re.compile(r"(\d+)\s+tests?\s+collected")
_RE_PASSED = re.compile(r"(\d+)\s+passed")
_RE_FAILED = re.compile(r"(\d+)\s+failed")
_RE_SKIPPED = re.compile(r"(\d+)\s+skipped")
_RE_COVERAGE = re.compile(r"TOTAL\s+\d+\s+\d+\s+\d+\s+\d+\s+(\d+\.\d+)%")


def _run_pytest(args: list[str]) -> tuple[int, str, str]:
    """Run pytest with given args, return (exit_code, stdout, stderr)."""
    cmd = [sys.executable, "-m", "pytest", *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return result.returncode, result.stdout, result.stderr


def _parse_collect(stdout: str) -> int | None:
    for line in reversed(stdout.strip().splitlines()):
        m = _RE_COLLECTED.search(line)
        if m:
            return int(m.group(1))
    return None


def _parse_run(stdout: str) -> tuple[int, int, int]:
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


def _parse_coverage(stdout: str) -> float | None:
    """Extract total coverage % from pytest --cov output."""
    for line in stdout.splitlines():
        m = _RE_COVERAGE.search(line)
        if m:
            return float(m.group(1))
    return None


# =============================================================================
# Badge builders
# =============================================================================


def _badge(label: str, message: str, color: str) -> dict:
    return {
        "schemaVersion": 1,
        "label": label,
        "message": message,
        "color": color,
    }


def _write_badge(name: str, data: dict) -> bool:
    """Write badge JSON to .github/badges/<name>.json. Return True if written."""
    path = BADGES_DIR / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    new_text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == new_text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def _build_tests_badge(run: bool) -> dict:
    """Build tests badge from pytest collect/run."""
    if run:
        _, stdout, _ = _run_pytest(["tests/", "-q", "--no-header"])
        passed, failed, skipped = _parse_run(stdout)
        _, collect_stdout, _ = _run_pytest(["tests/", "--collect-only", "-q"])
        collected = _parse_collect(collect_stdout)
    else:
        _, stdout, _ = _run_pytest(["tests/", "--collect-only", "-q"])
        collected = _parse_collect(stdout)
        passed = collected or 0
        failed = 0
        skipped = 0

    if failed > 0:
        return _badge("tests", f"{passed} passed, {failed} failed", "red")
    if collected is not None and passed == collected and skipped == 0:
        return _badge("tests", f"{passed} passed", "brightgreen")
    if passed > 0:
        msg = f"{passed} passed"
        if skipped:
            msg += f", {skipped} skipped"
        return _badge("tests", msg, "yellow")
    return _badge("tests", "0 passed", "red")


def _build_coverage_badge() -> dict:
    """Build coverage badge from pytest --cov output."""
    _, stdout, _ = _run_pytest(
        [
            "tests/",
            "-q",
            "--no-header",
            "--cov=senpy",
            "--cov-report=term",
        ]
    )
    pct = _parse_coverage(stdout)
    if pct is None:
        return _badge("coverage", "unknown", "lightgrey")
    if pct >= 80:
        color = "brightgreen"
    elif pct >= 60:
        color = "yellow"
    else:
        color = "red"
    return _badge("coverage", f"{pct:.1f}%", color)


def _build_rules_badge() -> dict:
    """Build rules count badge from RULES_DATABASE."""
    from senpy.rules.rules_info import RULES_DATABASE

    count = len(RULES_DATABASE)
    return _badge("rules", f"{count} rules", "orange")


def _build_lsp_badge() -> dict:
    """Build LSP handlers badge by counting public functions in handlers/."""
    handlers_dir = REPO_ROOT / "senpy" / "lsp" / "handlers"
    count = 0
    for py_file in handlers_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        try:
            import ast

            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                    count += 1
        except Exception:
            continue
    return _badge("LSP", f"{count} handlers", "purple")


def _build_speed_badge() -> dict:
    """Build speed badge from generative .rpy benchmark.

    Creates a 2000-line synthetic .rpy file, runs SenpyAnalyzer on it
    twice (cold + warm), reports the warm time.
    """
    import tempfile

    # Generate a 2000-line .rpy file
    lines = []
    lines.append("label start:")
    for i in range(1, 500):
        lines.append(f'    "Dialogue line {i} with [player_name]!"')
    for i in range(1, 250):
        lines.append(f"label scene_{i}:")
        lines.append(f'    "Scene {i} dialogue"')
        lines.append("    return")
    for i in range(1, 250):
        lines.append(f"transform trans_{i}:")
        lines.append("    ease 1.0 xoffset 100")
    rpy_content = "\n".join(lines) + "\n"

    with tempfile.TemporaryDirectory(prefix="senpy_bench_") as tmp:
        game_dir = os.path.join(tmp, "game")
        os.makedirs(game_dir)
        script_path = os.path.join(game_dir, "script.rpy")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(rpy_content)

        from senpy.core.analyzer import SenpyAnalyzer

        # Cold run (no cache)
        analyzer = SenpyAnalyzer(tmp, no_cache=True)
        t0 = time.perf_counter()
        analyzer.run(quiet=True)
        cold = time.perf_counter() - t0

        # Warm run (with cache from cold run)
        analyzer2 = SenpyAnalyzer(tmp)
        t0 = time.perf_counter()
        analyzer2.run(quiet=True)
        warm = time.perf_counter() - t0

    if warm < 0.1:
        color = "brightgreen"
    elif warm < 1.0:
        color = "green"
    else:
        color = "yellow"
    return _badge("speed", f"{warm:.3f}s warm ({cold:.1f}s cold)", color)


# =============================================================================
# Main
# =============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(description="Update dynamic badges.")
    parser.add_argument(
        "--run", action="store_true", help="Full run: pytest + coverage + speed benchmark."
    )
    parser.add_argument("--check", action="store_true", help="Exit 1 if any badge would change.")
    args = parser.parse_args()

    do_run = args.run or args.check
    badges: dict[str, dict] = {}

    # Tests badge
    badges["tests"] = _build_tests_badge(run=do_run)

    # Static badges (always cheap, no pytest needed)
    badges["rules"] = _build_rules_badge()
    badges["lsp"] = _build_lsp_badge()

    # Coverage badge (only in --run mode, requires pytest --cov)
    if do_run:
        badges["coverage"] = _build_coverage_badge()
        badges["speed"] = _build_speed_badge()
    else:
        # In collect-only mode, keep existing coverage/speed badges
        for name in ("coverage", "speed"):
            path = BADGES_DIR / f"{name}.json"
            if path.exists():
                badges[name] = json.loads(path.read_text())

    # Write badges
    changed = False
    for name, data in badges.items():
        if args.check:
            path = BADGES_DIR / f"{name}.json"
            new_text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
            if path.exists() and path.read_text(encoding="utf-8") == new_text:
                print(f"OK: {name} up-to-date ({data['message']})")
            else:
                print(f"STALE: {name} would change to '{data['message']}'", file=sys.stderr)
                changed = True
        else:
            written = _write_badge(name, data)
            if written:
                print(f"Updated {name}.json: {data['message']} ({data['color']})")
            else:
                print(f"Already up-to-date: {name} ({data['message']})")

    return 1 if (args.check and changed) else 0


if __name__ == "__main__":
    sys.exit(main())
