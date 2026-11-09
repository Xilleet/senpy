"""Centralized path constants for tests.

Why this exists:
    Several test files used `Path(__file__).parent.parent` to walk from
    `tests/<file>.py` up to the repo root. That breaks the moment a test
    moves into a subdirectory: `tests/lsp/<file>.py` has `.parent.parent`
    pointing at `tests/`, not at the repo root.

    By importing from this module, tests become location-independent.
    Every path constant here is anchored to `__file__` of THIS module
    (`tests/_helpers/paths.py`), which does not move during restructure.

All paths are resolved (absolute) so they don't depend on pytest's CWD.
"""

from __future__ import annotations

from pathlib import Path

# tests/_helpers/paths.py → parents[0]=_helpers, [1]=tests, [2]=repo root
REPO_ROOT: Path = Path(__file__).resolve().parents[2]
TESTS_DIR: Path = REPO_ROOT / "tests"
FIXTURES_DIR: Path = TESTS_DIR / "fixtures" / "rules"
CROSS_FILE_FIXTURES_DIR: Path = TESTS_DIR / "fixtures" / "rpy109_cross_file"
SCRIPTS_DIR: Path = REPO_ROOT / "scripts"
VSCODE_DIR: Path = REPO_ROOT / "senpy-vscode"
PLUGIN_DIR: Path = REPO_ROOT / "examples" / "todo_comment_plugin"
MY_SENPY_PLUGIN_DIR: Path = REPO_ROOT / "examples" / "my_senpy_plugin"
SECURITY_MD: Path = REPO_ROOT / "SECURITY.md"
EXTENSION_TS: Path = VSCODE_DIR / "src" / "extension.ts"
VSCODE_PACKAGE_JSON: Path = VSCODE_DIR / "package.json"
CHECK_CYCLES_SCRIPT: Path = SCRIPTS_DIR / "check_cycles.py"
