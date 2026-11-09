"""Senpy tests restructure — Phase 1: extract shared helpers, centralize
path constants, switch pytest to importlib mode. Run BEFORE moving any
test files into subdirectories.

This script is IDEMPOTENT: re-running it on an already-migrated tree
should be a no-op (it asserts that expected source strings still exist
before replacing them; if they're already gone, it just reports and skips).

What it does (in order):
  1. Create tests/__init__.py (empty package marker).
  2. Create tests/_helpers/__init__.py (empty package marker).
  3. Create tests/_helpers/paths.py with REPO_ROOT, TESTS_DIR,
     FIXTURES_DIR, CROSS_FILE_FIXTURES_DIR, VSCODE_DIR, PLUGIN_DIR,
     SECURITY_MD, EXTENSION_TS, VSCODE_PACKAGE_JSON, SCRIPTS_DIR,
     CHECK_CYCLES_SCRIPT.
  4. Create tests/_helpers/lsp.py — MockDocument, MockWorkspace,
     setup_test_workspace (extracted verbatim from tests/test_lsp.py).
  5. Create tests/_helpers/subprint.py — MockDocument, MockWorkspace
     (extracted verbatim from tests/test_0_6_0_subprint_3a.py).
  6. Move tests/_quickfix_sim.py → tests/_helpers/quickfix.py
     (content unchanged).
  7. Edit tests/test_lsp.py — remove the helper definitions, import
     them from tests._helpers.lsp.
  8. Edit tests/test_0_6_0_subprint_3a.py — remove the helper
     definitions, import from tests._helpers.subprint.
  9. Update 12 importers of `test_lsp` → `tests._helpers.lsp`.
 10. Update 1 importer of `test_0_6_0_subprint_3a` → `tests._helpers.subprint`.
 11. Update 2 importers of `_quickfix_sim` → `tests._helpers.quickfix`.
 12. Update Path(__file__).parent.parent references in 18 files
     (with and without .resolve()) → import REPO_ROOT etc.
 13. Update Path(__file__).parent / "fixtures" / ... in 3 files
     → import FIXTURES_DIR / CROSS_FILE_FIXTURES_DIR.
 14. Update pyproject.toml addopts to include --import-mode=importlib.

What it does NOT do:
  - Move any test_*.py into subdirectories (that's Phase 2+).
  - Touch tests/fixtures/.
  - Touch tests/conftest.py.
  - Touch run_tests.py.

Run from repo root:  python3 scripts/migrate_tests_helpers.py
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

# Repo root defaults to <project>/senpy but can be overridden via argv[1].
_DEFAULT_REPO = Path(__file__).resolve().parent.parent / "senpy"
REPO = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else _DEFAULT_REPO
TESTS = REPO / "tests"
HELPERS = TESTS / "_helpers"


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

_changes: list[str] = []


def log(msg: str) -> None:
    print(f"  · {msg}")
    _changes.append(msg)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# --------------------------------------------------------------------------- #
# Step 1+2: package markers
# --------------------------------------------------------------------------- #

def create_package_markers() -> None:
    section("Step 1+2: package markers")
    for path in (TESTS / "__init__.py", HELPERS / "__init__.py"):
        if path.exists():
            print(f"  · skip (exists): {path.relative_to(REPO)}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '"""Package marker. Empty by design — enables `--import-mode=importlib`.\n"""\n',
            encoding="utf-8",
        )
        log(f"created {path.relative_to(REPO)}")


# --------------------------------------------------------------------------- #
# Step 3: tests/_helpers/paths.py
# --------------------------------------------------------------------------- #

PATHS_PY = '''"""Centralized path constants for tests.

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
SECURITY_MD: Path = REPO_ROOT / "SECURITY.md"
EXTENSION_TS: Path = VSCODE_DIR / "src" / "extension.ts"
VSCODE_PACKAGE_JSON: Path = VSCODE_DIR / "package.json"
CHECK_CYCLES_SCRIPT: Path = SCRIPTS_DIR / "check_cycles.py"
'''


def create_paths_module() -> None:
    section("Step 3: tests/_helpers/paths.py")
    out = HELPERS / "paths.py"
    if out.exists() and out.read_text(encoding="utf-8") == PATHS_PY:
        print(f"  · skip (up to date): {out.relative_to(REPO)}")
        return
    HELPERS.mkdir(parents=True, exist_ok=True)
    out.write_text(PATHS_PY, encoding="utf-8")
    log(f"wrote {out.relative_to(REPO)}")


# --------------------------------------------------------------------------- #
# Step 4: tests/_helpers/lsp.py (extracted from test_lsp.py)
# --------------------------------------------------------------------------- #

LSP_PY = '''"""Shared LSP test helpers.

Extracted from `tests/test_lsp.py` so that 12+ test files can import
`MockDocument`, `MockWorkspace`, `setup_test_workspace` without
`test_lsp.py` being on `sys.path` (which only works in pytest's default
`prepend` import mode and breaks in `importlib` mode after subdirectory
moves).

Kept verbatim from the original — do not change semantics without
auditing every importer.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock  # noqa: F401  — preserved from original

from lsprotocol import types as lsp  # noqa: F401  — preserved from original

import senpy.lsp.server as server_mod
from senpy.core.analyzer import SenpyAnalyzer


class MockDocument:
    def __init__(self, uri: str, content: str):
        self.uri = uri
        self.lines = content.splitlines(keepends=True)
        self.source = content  # для совместимости с pygls TextDocument API


class MockWorkspace:
    def __init__(self, doc: MockDocument):
        self.doc = doc

    def get_text_document(self, uri: str):
        return self.doc if self.doc.uri == uri else None


def setup_test_workspace(tmp_path: Path):
    """Создаёт тестовый проект Ren'Py и инициализирует анализатор в LSP сервере."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)

    script_content = """
default player_gold = 100
define max_hp = 50

layeredimage sayori:
    attribute happy
    attribute shocked

label start:
    $ player_gold += 10
    show sayori happy
    jump forest_scene

label forest_scene:
    "В лесу..."
    jump deep_cave

label deep_cave:
    return
"""
    script_file = game_dir / "script.rpy"
    script_file.write_text(script_content, encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)

    # Инициализируем синглтон анализатора в server.py
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    # UX: refresh symbol snapshot, чтобы autocomplete/hover/rename/
    # workspace_symbol видели labels/screens/transforms (handler'ы теперь
    # используют snapshot, не _active_analyzer.labels напрямую).
    server_mod._refresh_symbol_snapshot()

    return script_file, analyzer
'''


def create_lsp_helper() -> None:
    section("Step 4: tests/_helpers/lsp.py")
    out = HELPERS / "lsp.py"
    if out.exists() and out.read_text(encoding="utf-8") == LSP_PY:
        print(f"  · skip (up to date): {out.relative_to(REPO)}")
        return
    out.write_text(LSP_PY, encoding="utf-8")
    log(f"wrote {out.relative_to(REPO)}")


# --------------------------------------------------------------------------- #
# Step 5: tests/_helpers/subprint.py (extracted from test_0_6_0_subprint_3a.py)
# --------------------------------------------------------------------------- #

SUBPRINT_PY = '''"""Shared mocks for Под-спринт 3 (color & formatting LSP tests).

Extracted from `tests/test_0_6_0_subprint_3a.py` so that
`test_0_6_0_subprint_3b.py` can import `MockDocument`, `MockWorkspace`
without depending on a sibling test module being importable.

NOTE: these classes are intentionally different from the ones in
`tests/_helpers/lsp.py` (different constructor signatures, different
semantics). Do not merge them.
"""

from __future__ import annotations


class MockDocument:
    """Minimal mock of pygls TextDocument for testing."""

    def __init__(self, uri: str, source: str):
        self.uri = uri
        self._source = source
        # Split into lines, preserve newlines
        self.lines = source.splitlines(keepends=True)

    @property
    def source(self) -> str:
        return self._source

    def __len__(self) -> int:
        return len(self.lines)


class MockWorkspace:
    """Minimal mock of pygls Workspace."""

    def __init__(
        self, documents: dict[str, MockDocument] | None = None, root_path: str | None = None
    ):
        self._documents = documents or {}
        self.root_path = root_path

    def get_text_document(self, uri: str) -> MockDocument | None:
        return self._documents.get(uri)
'''


def create_subprint_helper() -> None:
    section("Step 5: tests/_helpers/subprint.py")
    out = HELPERS / "subprint.py"
    if out.exists() and out.read_text(encoding="utf-8") == SUBPRINT_PY:
        print(f"  · skip (up to date): {out.relative_to(REPO)}")
        return
    out.write_text(SUBPRINT_PY, encoding="utf-8")
    log(f"wrote {out.relative_to(REPO)}")


# --------------------------------------------------------------------------- #
# Step 6: move tests/_quickfix_sim.py → tests/_helpers/quickfix.py
# --------------------------------------------------------------------------- #

def move_quickfix_sim() -> None:
    section("Step 6: tests/_quickfix_sim.py → tests/_helpers/quickfix.py")
    src = TESTS / "_quickfix_sim.py"
    dst = HELPERS / "quickfix.py"
    if not src.exists():
        if dst.exists():
            print(f"  · skip (already moved): {dst.relative_to(REPO)}")
            return
        raise RuntimeError(f"expected source missing: {src}")
    if dst.exists():
        if src.read_text(encoding="utf-8") == dst.read_text(encoding="utf-8"):
            src.unlink()
            print("  · skip (dst exists, removed leftover src)")
            return
        raise RuntimeError(f"dst exists but content differs: {dst}")
    shutil.move(str(src), str(dst))
    log(f"moved {src.relative_to(REPO)} → {dst.relative_to(REPO)}")


# --------------------------------------------------------------------------- #
# Step 7: edit test_lsp.py to import helpers instead of defining them
# --------------------------------------------------------------------------- #

def refactor_test_lsp() -> None:
    section("Step 7: tests/test_lsp.py — import from tests._helpers.lsp")
    path = TESTS / "test_lsp.py"
    text = path.read_text(encoding="utf-8")

    old_block = '''class MockDocument:
    def __init__(self, uri: str, content: str):
        self.uri = uri
        self.lines = content.splitlines(keepends=True)
        self.source = content  # для совместимости с pygls TextDocument API


class MockWorkspace:
    def __init__(self, doc: MockDocument):
        self.doc = doc

    def get_text_document(self, uri: str):
        return self.doc if self.doc.uri == uri else None


def setup_test_workspace(tmp_path: Path):
    """Создаёт тестовый проект Ren'Py и инициализирует анализатор в LSP сервере."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)

    script_content = """
default player_gold = 100
define max_hp = 50

layeredimage sayori:
    attribute happy
    attribute shocked

label start:
    $ player_gold += 10
    show sayori happy
    jump forest_scene

label forest_scene:
    "В лесу..."
    jump deep_cave

label deep_cave:
    return
"""
    script_file = game_dir / "script.rpy"
    script_file.write_text(script_content, encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)

    # Инициализируем синглтон анализатора в server.py
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    # UX: refresh symbol snapshot, чтобы autocomplete/hover/rename/
    # workspace_symbol видели labels/screens/transforms (handler'ы теперь
    # используют snapshot, не _active_analyzer.labels напрямую).
    server_mod._refresh_symbol_snapshot()

    return script_file, analyzer'''

    new_block = '''from tests._helpers.lsp import (  # noqa: F401  — re-exported for back-compat
    MockDocument,
    MockWorkspace,
    setup_test_workspace,
)'''

    if new_block in text:
        print(f"  · skip (already migrated): {path.relative_to(REPO)}")
        return

    if old_block not in text:
        raise RuntimeError(
            "test_lsp.py: expected helper block not found verbatim. Manual review required."
        )

    new_text = text.replace(old_block, new_block)
    path.write_text(new_text, encoding="utf-8")
    log(f"edited {path.relative_to(REPO)}: helper block → import (1 replacement)")


# --------------------------------------------------------------------------- #
# Step 8: edit test_0_6_0_subprint_3a.py
# --------------------------------------------------------------------------- #

def refactor_subprint_3a() -> None:
    section("Step 8: tests/test_0_6_0_subprint_3a.py — import from tests._helpers.subprint")
    path = TESTS / "test_0_6_0_subprint_3a.py"
    text = path.read_text(encoding="utf-8")

    old_block = '''class MockDocument:
    """Minimal mock of pygls TextDocument for testing."""

    def __init__(self, uri: str, source: str):
        self.uri = uri
        self._source = source
        # Split into lines, preserve newlines
        self.lines = source.splitlines(keepends=True)

    @property
    def source(self) -> str:
        return self._source

    def __len__(self) -> int:
        return len(self.lines)


class MockWorkspace:
    """Minimal mock of pygls Workspace."""

    def __init__(
        self, documents: dict[str, MockDocument] | None = None, root_path: str | None = None
    ):
        self._documents = documents or {}
        self.root_path = root_path

    def get_text_document(self, uri: str) -> MockDocument | None:
        return self._documents.get(uri)'''

    new_block = '''from tests._helpers.subprint import (  # noqa: F401  — re-exported for back-compat
    MockDocument,
    MockWorkspace,
)'''

    if new_block in text:
        print(f"  · skip (already migrated): {path.relative_to(REPO)}")
        return

    if old_block not in text:
        raise RuntimeError(
            "test_0_6_0_subprint_3a.py: expected helper block not found verbatim."
        )

    new_text = text.replace(old_block, new_block)
    path.write_text(new_text, encoding="utf-8")
    log(f"edited {path.relative_to(REPO)}: helper block → import (1 replacement)")


# --------------------------------------------------------------------------- #
# Step 9: update 12 importers of `from test_lsp import ...`
# --------------------------------------------------------------------------- #

TEST_LSP_IMPORTERS = [
    "tests/test_workspace_symbol.py",
    "tests/test_lsp_asset_hover.py",
    "tests/test_prepare_rename_non_label.py",
    "tests/test_lsp_empty_uri_regression.py",
    "tests/test_lsp_text_document.py",
    "tests/test_document_symbols_no_mutation.py",
    "tests/test_vscode_extension.py",
    "tests/test_ux_ext_5_6_7.py",
    "tests/test_highlight_init.py",
    "tests/test_folding_range.py",
    "tests/test_references_snapshot.py",
    "tests/test_rename.py",
]


def update_test_lsp_importers() -> None:
    section("Step 9: rewrite `from test_lsp import` → `from tests._helpers.lsp import`")
    for rel in TEST_LSP_IMPORTERS:
        path = REPO / rel
        if not path.exists():
            raise RuntimeError(f"missing importer: {rel}")
        text = path.read_text(encoding="utf-8")
        new_text = re.sub(
            r"^from test_lsp import ",
            "from tests._helpers.lsp import ",
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if new_text == text:
            if "from tests._helpers.lsp import" in text:
                print(f"  · skip (already migrated): {rel}")
                continue
            raise RuntimeError(f"no `from test_lsp import` in {rel}")
        path.write_text(new_text, encoding="utf-8")
        log(f"edited {rel}: import rewritten")


# --------------------------------------------------------------------------- #
# Step 10: update importer of `from test_0_6_0_subprint_3a import ...`
# --------------------------------------------------------------------------- #

def update_subprint_importer() -> None:
    section(
        "Step 10: rewrite `from test_0_6_0_subprint_3a import` → `from tests._helpers.subprint import`"
    )
    path = TESTS / "test_0_6_0_subprint_3b.py"
    text = path.read_text(encoding="utf-8")
    new_text = re.sub(
        r"^from test_0_6_0_subprint_3a import ",
        "from tests._helpers.subprint import ",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if new_text == text:
        if "from tests._helpers.subprint import" in text:
            print("  · skip (already migrated): tests/test_0_6_0_subprint_3b.py")
            return
        raise RuntimeError("no `from test_0_6_0_subprint_3a import` in 3b")
    path.write_text(new_text, encoding="utf-8")
    log("edited tests/test_0_6_0_subprint_3b.py: import rewritten")


# --------------------------------------------------------------------------- #
# Step 11: update 2 importers of `from _quickfix_sim import ...`
# --------------------------------------------------------------------------- #

QUICKFIX_IMPORTERS = [
    "tests/test_quickfix_cluster.py",
    "tests/test_quickfix_preserves_validity.py",
]


def update_quickfix_importers() -> None:
    section(
        "Step 11: rewrite `from _quickfix_sim import` → `from tests._helpers.quickfix import`"
    )
    for rel in QUICKFIX_IMPORTERS:
        path = REPO / rel
        text = path.read_text(encoding="utf-8")
        new_text = re.sub(
            r"^from _quickfix_sim import ",
            "from tests._helpers.quickfix import ",
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if new_text == text:
            if "from tests._helpers.quickfix import" in text:
                print(f"  · skip (already migrated): {rel}")
                continue
            raise RuntimeError(f"no `from _quickfix_sim import` in {rel}")
        path.write_text(new_text, encoding="utf-8")
        log(f"edited {rel}: import rewritten")


# --------------------------------------------------------------------------- #
# Step 12+13: replace Path(__file__).parent.parent and Path(__file__).parent / "fixtures"
# --------------------------------------------------------------------------- #

PARENT_PARENT_FILES = {
    "tests/test_post_080_fixes.py": [
        ('Path(__file__).parent.parent / "senpy-vscode" / "src" / "extension.ts"',
         "EXTENSION_TS"),
        ('Path(__file__).parent.parent / "SECURITY.md"', "SECURITY_MD"),
    ],
    "tests/test_vscode_extension.py": [
        ('Path(__file__).parent.parent / "senpy-vscode"', "VSCODE_DIR"),
    ],
    "tests/test_lsp_21_api_docs.py": [
        ("Path(__file__).parent.parent", "REPO_ROOT"),
    ],
    "tests/test_lsp_asset_hover.py": [
        ('Path(__file__).parent.parent / "senpy-vscode" / "src" / "extension.ts"',
         "EXTENSION_TS"),
        ('Path(__file__).parent.parent / "senpy-vscode" / "package.json"',
         "VSCODE_PACKAGE_JSON"),
    ],
    "tests/test_p0_cli.py": [
        ("Path(__file__).parent.parent", "REPO_ROOT"),
    ],
    "tests/test_main_characterization.py": [
        ("Path(__file__).parent.parent", "REPO_ROOT"),
    ],
}

RESOLVE_PARENT_PARENT_FILES = {
    "tests/test_plugin_rule_execution.py": [
        ('Path(__file__).resolve().parent.parent / "examples" / "todo_comment_plugin"',
         "PLUGIN_DIR"),
    ],
    "tests/test_packaging.py": [
        ("Path(__file__).resolve().parent.parent", "REPO_ROOT"),
    ],
    "tests/test_check_cycles.py": [
        ('Path(__file__).resolve().parent.parent / "scripts" / "check_cycles.py"',
         "CHECK_CYCLES_SCRIPT"),
    ],
    "tests/test_pre_commit_hooks.py": [
        ("Path(__file__).resolve().parent.parent", "REPO_ROOT"),
    ],
    "tests/test_lsp_plugin_execution.py": [
        ('Path(__file__).resolve().parent.parent / "examples" / "todo_comment_plugin"',
         "PLUGIN_DIR"),
    ],
    "tests/test_inspect_cli.py": [
        ("Path(__file__).resolve().parent.parent", "REPO_ROOT"),
    ],
    "tests/test_ux_ext_5_6_7.py": [
        ('Path(__file__).resolve().parent.parent / "senpy-vscode"', "VSCODE_DIR"),
    ],
    "tests/test_inspect.py": [
        ("Path(__file__).resolve().parent.parent", "REPO_ROOT"),
    ],
    "tests/test_todo_comment_plugin.py": [
        ('Path(__file__).resolve().parent.parent / "examples" / "todo_comment_plugin"',
         "PLUGIN_DIR"),
    ],
    "tests/test_ruff_clean.py": [
        ("Path(__file__).resolve().parent.parent", "REPO_ROOT"),
    ],
    "tests/test_no_russian_comments.py": [
        ("Path(__file__).resolve().parent.parent", "REPO_ROOT"),
    ],
    "tests/test_clean_internal_ids.py": [
        ("Path(__file__).resolve().parent.parent", "REPO_ROOT"),
    ],
}

FIXTURES_PATH_FILES = {
    "tests/test_fixtures.py": [
        ('Path(__file__).parent / "fixtures" / "rules"', "FIXTURES_DIR"),
    ],
    "tests/test_quickfix_preserves_validity.py": [
        ('Path(__file__).parent / "fixtures" / "rules"', "FIXTURES_DIR"),
    ],
    "tests/test_rpy109_cross_file_fixture.py": [
        ('Path(__file__).parent / "fixtures" / "rpy109_cross_file"',
         "CROSS_FILE_FIXTURES_DIR"),
    ],
}


def add_paths_import(text: str, names: list[str]) -> str:
    """Insert `from tests._helpers.paths import ...` after the
    `from __future__ import annotations` line. Returns the new text.

    Idempotent: if the import already exists, returns text unchanged.
    """
    if len(names) == 1:
        import_line = f"from tests._helpers.paths import {names[0]}\n"
    else:
        import_line = (
            "from tests._helpers.paths import (\n"
            + "".join(f"    {n},\n" for n in names)
            + ")\n"
        )

    if "from tests._helpers.paths import" in text:
        return text

    m = re.search(r"^from __future__ import annotations\n", text, re.MULTILINE)
    if m:
        insert_at = m.end()
        return text[:insert_at] + "\n" + import_line + text[insert_at:]

    return import_line + text


def replace_path_constants(files_map: dict[str, list[tuple[str, str]]]) -> None:
    for rel, replacements in files_map.items():
        path = REPO / rel
        if not path.exists():
            raise RuntimeError(f"missing file: {rel}")
        text = path.read_text(encoding="utf-8")
        names_needed: list[str] = []
        modified = text
        for old, new in replacements:
            count = modified.count(old)
            if count == 0:
                continue
            modified = modified.replace(old, new)
            if new not in names_needed:
                names_needed.append(new)
        if modified == text:
            if "from tests._helpers.paths import" in text:
                print(f"  · skip (already migrated): {rel}")
                continue
            raise RuntimeError(f"no path patterns matched in {rel}")
        names_sorted = sorted(names_needed)
        modified = add_paths_import(modified, names_sorted)
        path.write_text(modified, encoding="utf-8")
        log(
            f"edited {rel}: {len(names_needed)} path constant(s) replaced, import added"
        )


def update_path_arithmetic() -> None:
    section(
        "Step 12+13: replace Path(__file__).parent.parent and Path(__file__).parent / 'fixtures'"
    )
    print("  -- parent.parent (no resolve) --")
    replace_path_constants(PARENT_PARENT_FILES)
    print("  -- resolve().parent.parent --")
    replace_path_constants(RESOLVE_PARENT_PARENT_FILES)
    print("  -- parent / 'fixtures' --")
    replace_path_constants(FIXTURES_PATH_FILES)


# --------------------------------------------------------------------------- #
# Step 14: pyproject.toml — add --import-mode=importlib
# --------------------------------------------------------------------------- #

def update_pyproject() -> None:
    section("Step 14: pyproject.toml — add --import-mode=importlib")
    path = REPO / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    if "--import-mode=importlib" in text:
        print("  · skip (already migrated): pyproject.toml")
        return
    old = '''addopts = [
    "--strict-markers",
    "--strict-config",
    "-ra",
]'''
    new = '''addopts = [
    "--strict-markers",
    "--strict-config",
    "-ra",
    "--import-mode=importlib",
]'''
    if old not in text:
        raise RuntimeError("pyproject.toml: addopts block not found verbatim")
    path.write_text(text.replace(old, new), encoding="utf-8")
    log("edited pyproject.toml: added --import-mode=importlib to addopts")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def main() -> int:
    print(f"Repo root: {REPO}")
    print(f"Tests dir: {TESTS}")

    create_package_markers()
    create_paths_module()
    create_lsp_helper()
    create_subprint_helper()
    move_quickfix_sim()
    refactor_test_lsp()
    refactor_subprint_3a()
    update_test_lsp_importers()
    update_subprint_importer()
    update_quickfix_importers()
    update_path_arithmetic()
    update_pyproject()

    print(f"\n=== DONE — {len(_changes)} change(s) ===")
    for c in _changes:
        print(f"  · {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
