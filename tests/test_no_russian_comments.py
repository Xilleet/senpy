"""Guard test: no Russian text in comments or docstrings.

After the CLEAN-2 cleanup (0.7.2), all Russian comments and docstrings in
senpy/ were translated to English. This test ensures no new Russian
text leaks back into comments (# ...) or docstrings ("\"\"\"...\"\"\") in
future commits.

Whitelisted files (where Russian is intentionally part of the content):
  - senpy/domain/tsundere.py -- easter egg mode, intentionally Russian
  - senpy/vendor/** -- vendored unrpyc, third-party code
  - String literals inside code (e.g. "Privet") are NOT checked --
    only # comments and triple-quote docstrings are scanned.

This test is modelled after test_clean_internal_ids.py (CLEAN-1 guard).

Run manually:
    python -m pytest tests/test_no_russian_comments.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Cyrillic character range (Russian alphabet + Ё/ё)
_CYRILLIC_RE = re.compile(r"[а-яА-ЯёЁ]")

# Files where Russian is intentionally part of the content.
_WHITELIST = {
    "senpy/domain/tsundere.py",  # Easter egg mode — intentionally Russian
    # TODO (post-0.7.5): translate these scripts to English and remove
    # them from the whitelist. They have 7-61 Russian comment lines each.
    # Tracked as follow-up to WL-638.
    "scripts/restructure_senpy.py",
    "scripts/update_unrpyc_pin.py",
    # clean_internal_ids.py has one Russian word ("версия") inside a
    # docstring example showing what the script scrubs. It's part of
    # the documentation, not a real Russian comment.
    "scripts/clean_internal_ids.py",
    # sync_rule_count.py has Russian words in regex patterns (правил, правила)
    # — they are functional patterns for matching Russian text in README_ru.md.
    "scripts/sync_rule_count.py",
}

# Directories to skip entirely.
_SKIP_DIRS = {
    "senpy/vendor",  # Vendored unrpyc — third-party code
}

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _should_skip(rel_path: str) -> bool:
    """Return True if the file should not be scanned."""
    if rel_path in _WHITELIST:
        return True
    for skip_dir in _SKIP_DIRS:
        if rel_path.startswith(skip_dir + "/"):
            return True
    return False


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return list of (line_no, line_content) for lines containing Russian
    text in a # comment or docstring.

    We scan line-by-line. A line is flagged if:
      - It contains Cyrillic characters, AND
      - It starts with # (or has # after whitespace), OR
      - It is inside a triple-quote docstring

    Lines that are pure code (no comment, no docstring) are NOT flagged,
    even if they contain Russian string literals (e.g. ``"Привет"``).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    violations: list[tuple[int, str]] = []
    in_docstring = False

    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()

        # Track triple-quote docstring state (simple state machine).
        # This is intentionally simple — it may have edge cases with
        # triple quotes inside strings, but for our purposes (catching
        # Russian in docstrings) it's good enough.
        if '"""' in stripped:
            count = stripped.count('"""')
            if count == 1:
                in_docstring = not in_docstring
            # count == 2 means single-line docstring — both open and close
            # on the same line, so the state doesn't change.

        has_cyrillic = bool(_CYRILLIC_RE.search(line))
        if not has_cyrillic:
            continue

        # Is this line a comment or docstring line?
        is_comment = stripped.startswith("#")
        is_docstring_line = in_docstring or '"""' in stripped

        if is_comment or is_docstring_line:
            violations.append((i, line.rstrip()))

    return violations


class TestNoRussianInCommentsOrDocstrings:
    """The core CLEAN-2 assertion: no Russian text in # comments or
    \"\"\" docstrings in senpy/ source files."""

    def test_no_russian_comments_or_docstrings(self):
        """Scan every .py file in senpy/ (excluding vendor and tsundere)
        for Russian text in comments and docstrings.

        Fails with a list of all violations (file:line: content) so the
        developer can translate them in one pass.
        """
        violations: list[str] = []

        senpy_dir = _REPO_ROOT / "senpy"
        for path in senpy_dir.rglob("*.py"):
            rel = path.relative_to(_REPO_ROOT).as_posix()
            if _should_skip(rel):
                continue
            matches = _scan_file(path)
            if not matches:
                continue
            for line_no, content in matches:
                # Truncate long lines for readability
                display = content[:120] + "..." if len(content) > 120 else content
                violations.append(f"  {rel}:{line_no}: {display}")

        if violations:
            preview = "\n".join(violations[:50])
            n_more = len(violations) - 50
            extra = f"\n  ... and {n_more} more." if n_more > 0 else ""
            pytest.fail(
                f"Found {len(violations)} line(s) with Russian text in "
                f"comments or docstrings. Translate them to English.\n\n"
                f"{preview}{extra}"
            )


class TestNoRussianInRootLevelScripts:
    """Extend the CLEAN-2 assertion to root-level .py files.

    The test above only scanned `senpy/`. The root-level
    dev tools (`bump_version.py`, `run_tests.py`, `scripts/*.py`) were
    not covered, so Russian comments leaked back in (notably in
    `bump_version.py`, whose template regenerated Russian docstrings
    in `senpy/__version__.py` on every version bump).

    This test scans root-level .py files for the same rule: no Russian
    in # comments or docstrings. String literals are still OK.
    """

    # Root-level .py files to scan (relative to repo root).
    _ROOT_FILES = {
        "bump_version.py",
        "run_tests.py",
    }

    # Directories to scan recursively (relative to repo root).
    _ROOT_DIRS = {
        "scripts",
    }

    def test_no_russian_in_root_level_scripts(self):
        violations: list[str] = []

        # Single files at the repo root.
        for rel_path in self._ROOT_FILES:
            path = _REPO_ROOT / rel_path
            if not path.exists():
                continue
            matches = _scan_file(path)
            for line_no, content in matches:
                display = content[:120] + "..." if len(content) > 120 else content
                violations.append(f"  {rel_path}:{line_no}: {display}")

        # Directories (recursive).
        for dir_rel in self._ROOT_DIRS:
            dir_path = _REPO_ROOT / dir_rel
            if not dir_path.exists():
                continue
            for path in dir_path.rglob("*.py"):
                rel = path.relative_to(_REPO_ROOT).as_posix()
                if _should_skip(rel):
                    continue
                matches = _scan_file(path)
                for line_no, content in matches:
                    display = content[:120] + "..." if len(content) > 120 else content
                    violations.append(f"  {rel}:{line_no}: {display}")

        if violations:
            preview = "\n".join(violations[:50])
            n_more = len(violations) - 50
            extra = f"\n  ... and {n_more} more." if n_more > 0 else ""
            pytest.fail(
                f"Found {len(violations)} line(s) with Russian text in "
                f"comments or docstrings of root-level scripts. Translate "
                f"them to English.\n\n"
                f"{preview}{extra}"
            )
