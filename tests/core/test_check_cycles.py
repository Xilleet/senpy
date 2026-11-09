"""Local pytest safety net for ``scripts/check_cycles.py``.

CI runs ``scripts/check_cycles.py`` as a standalone step before
ruff/pytest (``.github/workflows/ci.yml:67``). Without a matching
pytest test, the cycle check is invisible during local development —
a contributor can run ``pytest`` and see green, then push and watch CI
fail on the cycle step. That is exactly the regression that slipped
through when ``format_dispatch`` started importing ``console`` from
``main`` (which already lazily imports ``format_dispatch``).

This test runs the script in-process and asserts exit code 0, so the
cycle check is part of the local pytest quality gate, not only CI.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests._helpers.paths import CHECK_CYCLES_SCRIPT


def test_check_cycles_script_passes() -> None:
    """``scripts/check_cycles.py`` must exit 0 — no circular imports in senpy/.

    Runs the script in-process via ``python -m`` so the test inherits the
    current interpreter's sys.path. Asserts both the exit code and that
    the stdout contains the ``[OK]`` marker, so a silent script failure
    (e.g. the script exiting 0 for the wrong reason) is still caught.
    """
    script = CHECK_CYCLES_SCRIPT
    assert script.is_file(), f"check_cycles.py missing at {script}"

    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, (
        f"check_cycles.py exited {result.returncode} — circular import detected.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert (
        "[OK] No circular imports found" in result.stdout
    ), f"check_cycles.py exited 0 but did not report OK — unexpected output:\n{result.stdout}"
