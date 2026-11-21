"""RED→GREEN tests for the 0.9.3 batch: screen.py severity
hardcodes route through ``RULE_SEVERITY``.

Three diagnostics in ``screen.py`` hardcoded their ``severity``
field (RPY208 -> "ERROR", RPY202 -> "WARNING", RPY207 -> "ERROR").
The values happened to match ``RULES_DATABASE``, so behaviour was
identical, but the hardcode was a drift hazard: a future edit to
``rules_info.py`` would leave screen.py on the old value.

The fix replaces each hardcode with ``RULE_SEVERITY["RPYxxx"]``.
The behavioural test below proves the wiring: monkeypatch
``RULE_SEVERITY["RPY208"]`` to ``"INFO"``, run the analyzer on an
RPY208-triggering snippet, and assert the diagnostic carries
``"INFO"``. With the hardcode in place the diagnostic would still
read ``"ERROR"`` and the test fails (RED). After the fix the
diagnostic reads the monkeypatched value (GREEN).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.models import RULE_SEVERITY


def _run_analyzer_on(rpy_content: str, tmp_path: Path):
    """Run SenpyAnalyzer on a single .rpy file inside a minimal game/ dir."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "scenario.rpy").write_text(rpy_content, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)
    return result, analyzer


# ---------------------------------------------------------------------------
# RPY208 — SetVariable on screen-local variable.
# ---------------------------------------------------------------------------

_RPY208_RPY = """\
screen shop():
    default selected_item = None
    textbutton "Sword" action SetVariable("selected_item", "Sword")
"""


def test_fix11_rpy208_severity_reads_rule_severity(tmp_path: Path, monkeypatch) -> None:
    """RPY208 severity must come from ``RULE_SEVERITY["RPY208"]``.

    Before the fix: ``screen.py`` hardcoded ``severity="ERROR"`` and
    the diagnostic ignored ``RULE_SEVERITY``. After the fix: the
    diagnostic reads ``RULE_SEVERITY["RPY208"]`` at emit time, so
    monkeypatching the dict (simulating a future bump in
    ``rules_info.py``) propagates to the emitted diagnostic.
    """
    monkeypatch.setitem(RULE_SEVERITY, "RPY208", "INFO")
    result, _ = _run_analyzer_on(_RPY208_RPY, tmp_path)
    rpy208 = [d for d in result.diagnostics if d.code == "RPY208"]
    assert rpy208, "RPY208 must fire for SetVariable on a screen-local default"
    assert rpy208[0].severity == "INFO", (
        f"RPY208 severity must read RULE_SEVERITY['RPY208'] "
        f"(monkeypatched to 'INFO'); got {rpy208[0].severity!r}. "
        f"screen.py likely still hardcodes severity='ERROR'."
    )


# ---------------------------------------------------------------------------
# RPY207 — invalid arguments to show/call screen.
# ---------------------------------------------------------------------------

_RPY207_RPY = """\
screen inv(sort_by):
    text sort_by

screen main_ui():
    call screen inv()
"""


def test_fix11_rpy207_severity_reads_rule_severity(tmp_path: Path, monkeypatch) -> None:
    """RPY207 severity must come from ``RULE_SEVERITY["RPY207"]``."""
    monkeypatch.setitem(RULE_SEVERITY, "RPY207", "INFO")
    result, _ = _run_analyzer_on(_RPY207_RPY, tmp_path)
    rpy207 = [d for d in result.diagnostics if d.code == "RPY207"]
    assert rpy207, "RPY207 must fire for a missing required screen argument"
    assert rpy207[0].severity == "INFO", (
        f"RPY207 severity must read RULE_SEVERITY['RPY207'] "
        f"(monkeypatched to 'INFO'); got {rpy207[0].severity!r}. "
        f"screen.py likely still hardcodes severity='ERROR'."
    )


# ---------------------------------------------------------------------------
# RPY202 — SetVariable on undeclared variable.
# ---------------------------------------------------------------------------

_RPY202_RPY = """\
screen main_ui():
    textbutton "Open" action SetVariable("undeclared_var", 1)
"""


def test_fix11_rpy202_severity_reads_rule_severity(tmp_path: Path, monkeypatch) -> None:
    """RPY202 severity must come from ``RULE_SEVERITY["RPY202"]``."""
    monkeypatch.setitem(RULE_SEVERITY, "RPY202", "ERROR")
    result, _ = _run_analyzer_on(_RPY202_RPY, tmp_path)
    rpy202 = [d for d in result.diagnostics if d.code == "RPY202"]
    assert rpy202, "RPY202 must fire for SetVariable on an undeclared variable"
    assert rpy202[0].severity == "ERROR", (
        f"RPY202 severity must read RULE_SEVERITY['RPY202'] "
        f"(monkeypatched to 'ERROR'); got {rpy202[0].severity!r}."
    )


# ---------------------------------------------------------------------------
# Structural guard: no ``severity="..."`` hardcode left in screen.py.
# ---------------------------------------------------------------------------


def test_fix11_no_severity_hardcode_in_screen_py() -> None:
    """No active ``severity="<LEVEL>"`` line may remain in screen.py.

    The fix removes all three hardcodes. This structural guard
    fails if a future contributor re-introduces one. Comments and
    docstrings mentioning the literal are allowed — only lines that
    actually construct a ``Diagnostic(...)`` with a hardcoded
    ``severity=`` count.
    """
    import re

    screen_py = Path(__file__).resolve().parents[2] / "senpy" / "rules" / "checkers" / "screen.py"
    text = screen_py.read_text(encoding="utf-8")
    # A hardcoded severity looks like ``severity="ERROR"`` (or WARNING/INFO/HINT)
    # as a keyword arg of a Diagnostic() call. We accept the literal in
    # comments / docstrings (the explanation block mentions it).
    bad: list[str] = []
    pattern = re.compile(r"^\s*severity\s*=\s*\"(ERROR|WARNING|INFO|HINT)\"\s*,?\s*$")
    for i, line in enumerate(text.splitlines(), start=1):
        # Skip comment lines (the doc references ``severity="ERROR"``
        # in prose — those start with ``#`` or are inside a docstring).
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if pattern.match(line):
            bad.append(f"{screen_py}:{i}: {line.strip()}")
    assert not bad, (
        "screen.py still hardcodes severity= — route through "
        "RULE_SEVERITY['RPYxxx']:\n" + "\n".join(bad)
    )
