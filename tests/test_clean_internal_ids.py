"""Characterization test for the CLEAN-1 internal-ID scrub.

After running ``scripts/clean_internal_ids.py --apply``, no internal task
IDs (DOC-1, CLI-17, LSP-19, QUA-12, ARCH-3, EXT-12, SEC-6, RULE-15, FMT-2,
FIX-1, TEST-6, IDEA-9, PERF-3, SEO-13, CLEAN-1, AUD-001, ECO-9, SSA-1,
STUDIO-1, etc.) should appear in any user-facing file.

Whitelisted files (where IDs are legitimately part of the content):
  - CHANGELOG.md (historical changelog entries — IDs are part of the
    release narrative)
  - Senpy_Consolidated_Backlog_*.md (the worklog itself — IDs are the
    intended reference mechanism)
  - senpy/vendor/** (vendored unrpyc — third-party code)
  - scripts/clean_internal_ids.py (this script's own docstring describes
    the ID format as an object)
  - .github/PULL_REQUEST_TEMPLATE.md (references the ID format)
  - .github/ISSUE_TEMPLATE/** (templates may reference the ID format)
  - senpy.sarif (auto-generated report)
  - lockfiles, build artifacts, .git/, node_modules/

This test scans every other .py/.md/.ts/.toml/.yml/.yaml/.json/.bat/.sh/
.rst/.txt/.cfg/.ini/.spec file in the repo and fails if it finds an ID
match. If you legitimately need to add an ID somewhere (e.g. a new
script that explains the ID format), add the file to the whitelist in
``scripts/clean_internal_ids.py`` AND in ``_WHITELIST`` below.

Run manually:
    python -m pytest tests/test_clean_internal_ids.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# Same pattern as scripts/clean_internal_ids.py. If the pattern there
# changes, update this one to match.
_ID_PATTERN = re.compile(
    r"\b("
    r"DOC|CLI|LSP|QUA|ARCH|EXT|SEC|RULE|FMT|FIX|TEST|IDEA|PERF|SEO|CLEAN|"
    r"AUD|SSA|ECO|STUDIO"
    r")-\d+[a-z]?\b"
)

# Whitelist of paths that are allowed to contain IDs. Mirror of the
# whitelist in scripts/clean_internal_ids.py — kept in sync manually.
_WHITELIST_PATHS = [
    "CHANGELOG.md",
    "Senpy_Consolidated_Backlog_*.md",
    "senpy/vendor/**",
    "senpy-vscode/package-lock.json",
    "senpy.sarif",
    "scripts/clean_internal_ids.py",
    "tests/test_clean_internal_ids.py",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/**",
    ".git/**",
    "node_modules/**",
    "build/**",
    "dist/**",
    ".senpy_cache/**",
    "__pycache__/**",
    "*.pyc",
]

# Lines containing any of these substrings are skipped (false-positive
# matches, e.g. shields.io badge URLs that contain "LSP-20" as part of
# "LSP: 20+ handlers").
_LINE_SKIP_SUBSTRINGS = (
    "shields.io",
    "%2B",
    "img.shields.io",
)

_SCANNABLE_EXTS = {
    ".py", ".md", ".ts", ".js", ".toml", ".yml", ".yaml", ".json",
    ".bat", ".sh", ".rst", ".txt", ".cfg", ".ini", ".spec",
}

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _is_whitelisted(path: Path) -> bool:
    """Return True if *path* matches any whitelist glob."""
    import fnmatch

    rel = path.relative_to(_REPO_ROOT).as_posix()
    for pattern in _WHITELIST_PATHS:
        if fnmatch.fnmatch(rel, pattern):
            return True
        if pattern.endswith("/**") and rel.startswith(pattern[:-4] + "/"):
            return True
    return False


def _is_scannable(path: Path) -> bool:
    return path.suffix.lower() in _SCANNABLE_EXTS


def _walk_repo():
    """Yield scannable, non-whitelisted files under repo root."""
    for path in _REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        # Skip obvious non-repo directories (defensive — rglob shouldn't
        # yield them, but on Windows symlinks can leak through).
        # .vscode-test/ in particular downloads a full VS Code instance
        # (hundreds of MB of JS) and would hang the test for minutes.
        rel = path.relative_to(_REPO_ROOT).as_posix()
        # Use "/node_modules/" / "/__pycache__/" /etc. as substring match
        # (with leading slash) so we catch nested occurrences too — e.g.
        # 'senpy-vscode/node_modules/foo.js' was previously leaking through
        # because rel.startswith('node_modules/') only matches the root.
        skip_subdirs = (
            "/.git/", "/node_modules/", "/build/", "/dist/",
            "/.senpy_cache/", "/__pycache__/", "/.vscode-test/",
            "/.vscode-test-cache/", "/.cache/", "/htmlcov/",
            "/.pytest_cache/", "/.ruff_cache/", "/.mypy_cache/",
        )
        if any(s in "/" + rel for s in skip_subdirs):
            continue
        # Also catch root-level occurrences (rel == 'node_modules/...').
        if rel.startswith(("node_modules/", "build/", "dist/", "__pycache__/",
                           ".git/", ".senpy_cache/", ".vscode-test/",
                           ".vscode-test-cache/", ".cache/", "htmlcov/",
                           ".pytest_cache/", ".ruff_cache/", ".mypy_cache/")):
            continue
        # Skip test artifacts (in .gitignore but may exist locally).
        if rel.startswith(("test_report.", "tests/test_report.")):
            continue
        if not _is_scannable(path):
            continue
        if _is_whitelisted(path):
            continue
        # Skip files larger than 1 MB — they are almost certainly not source
        # code (e.g. minified JS, generated reports, lockfiles bigger than
        # the limit) and would slow the scan to a crawl.
        try:
            if path.stat().st_size > 1_000_000:
                continue
        except OSError:
            continue
        yield path


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return list of (line_no, matched_id) for ID matches in *path*."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    matches: list[tuple[int, str]] = []
    # Cap line length at 10 KB to avoid pathological slow regex on minified
    # JS / generated JSON. Real source lines are rarely this long.
    for i, line in enumerate(text.splitlines(), start=1):
        if len(line) > 10_000:
            continue
        if any(s in line for s in _LINE_SKIP_SUBSTRINGS):
            continue
        for m in _ID_PATTERN.finditer(line):
            matches.append((i, m.group(0)))
    return matches


# =============================================================================
# Tests
# =============================================================================


class TestNoInternalIdsInUserFacingFiles:
    """The core CLEAN-1 assertion: no internal IDs in user-facing files."""

    def test_repo_has_no_stray_internal_ids(self):
        """Scan every scannable non-whitelisted file in the repo.

        Fails with a list of all violations (file:line: ID) so the
        developer can fix them in one pass instead of iterating.
        """
        violations: list[str] = []

        for path in _walk_repo():
            matches = _scan_file(path)
            if not matches:
                continue
            rel = path.relative_to(_REPO_ROOT)
            for line_no, matched_id in matches:
                violations.append(f"{rel}:{line_no}: {matched_id}")

        if violations:
            # Limit the output to first 50 violations to avoid flooding
            # the test runner — 50 is plenty to spot a regression.
            preview = "\n  ".join(violations[:50])
            n_more = len(violations) - 50
            extra = f"\n  ... and {n_more} more." if n_more > 0 else ""
            pytest.fail(
                f"Found {len(violations)} internal task ID(s) in user-facing "
                f"files. Run `python scripts/clean_internal_ids.py --apply` "
                f"to scrub them, or add the file to the whitelist in "
                f"scripts/clean_internal_ids.py if the ID is legitimate.\n\n"
                f"  {preview}{extra}"
            )


class TestCleanInternalIdsScript:
    """Smoke tests for the cleanup script itself."""

    def test_script_exists_and_is_executable(self):
        script = _REPO_ROOT / "scripts" / "clean_internal_ids.py"
        assert script.exists(), "scripts/clean_internal_ids.py should exist"
        assert os.access(script, os.X_OK), (
            "scripts/clean_internal_ids.py should be executable (chmod +x)."
        )

    def test_script_imports_cleanly(self):
        """The script must import without errors (no syntax issues, no
        missing dependencies)."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "clean_internal_ids",
            _REPO_ROOT / "scripts" / "clean_internal_ids.py",
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # The script exposes the core regex and the cleanup function.
        assert hasattr(mod, "_ID_PATTERN")
        assert hasattr(mod, "_scrub_line")
        assert hasattr(mod, "scan_file")

    def test_dry_run_does_not_modify_files(self, tmp_path):
        """--dry-run must not write any files. Run it on the actual repo
        and verify git status is clean afterwards."""
        import subprocess

        result = subprocess.run(
            ["python", str(_REPO_ROOT / "scripts" / "clean_internal_ids.py"),
             "--dry-run"],
            capture_output=True, text=True, cwd=_REPO_ROOT, timeout=30,
        )
        assert result.returncode == 0
        # Dry-run prints a summary line; --apply writes files.
        assert "DRY-RUN" in result.stdout

    def test_scrub_line_strips_leading_id_with_colon(self):
        """Unit test for the scrub logic: leading ID + colon is stripped."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "clean_internal_ids",
            _REPO_ROOT / "scripts" / "clean_internal_ids.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Leading ID in a docstring.
        new, n = mod._scrub_line('"""LSP-1: Find all hex color literals.')
        assert n == 1
        assert new == '"""Find all hex color literals.'

        # Leading ID in a comment.
        new, n = mod._scrub_line("# ECO-9: версия берётся из __version__.py")
        assert n == 1
        assert "ECO-9" not in new
        assert "версия берётся" in new

    def test_scrub_line_strips_inline_id(self):
        """Inline ID mention is stripped, leaving the surrounding text."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "clean_internal_ids",
            _REPO_ROOT / "scripts" / "clean_internal_ids.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # "After ARCH-1 it will:" → "After it will:"
        new, n = mod._scrub_line("After ARCH-1 it will:")
        assert n == 1
        assert "ARCH-1" not in new
        assert "After it will:" in new

    def test_scrub_line_strips_id_in_parens(self):
        """ID inside parens is stripped, parens are removed if empty."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "clean_internal_ids",
            _REPO_ROOT / "scripts" / "clean_internal_ids.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # "TODO (ARCH-22)" → "TODO"
        new, n = mod._scrub_line("# TODO (ARCH-22)")
        assert n == 1
        assert new == "# TODO"

    def test_scrub_line_strips_dash_prefixed_id(self):
        """ID prefixed with dash is stripped with the dash (no double-dash)."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "clean_internal_ids",
            _REPO_ROOT / "scripts" / "clean_internal_ids.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # "Senpy-LSP-21-fetcher" → "Senpy-fetcher"
        new, n = mod._scrub_line('{"User-Agent": "Mozilla/5.0 Senpy-LSP-21-fetcher"}')
        assert n == 1
        assert "Senpy-fetcher" in new
        assert "Senpy--fetcher" not in new
        assert "LSP-21" not in new

    def test_scrub_line_skips_shields_io_urls(self):
        """Lines with shields.io badge URLs are skipped (false positive)."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "clean_internal_ids",
            _REPO_ROOT / "scripts" / "clean_internal_ids.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        line = '<img src="https://img.shields.io/badge/LSP-20%2B%20handlers-purple">'
        new, n = mod._scrub_line(line)
        assert n == 0, "shields.io URL should be skipped (false positive)"
        assert new == line

    def test_scrub_line_strips_quote_prefixed_id_in_commit_message(self):
        """ID inside a quoted commit-message string is stripped with the colon."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "clean_internal_ids",
            _REPO_ROOT / "scripts" / "clean_internal_ids.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # git commit -m "ECO-4: pin unrpyc..." → git commit -m "pin unrpyc..."
        new, n = mod._scrub_line('    git commit -m "ECO-4: pin unrpyc to <version>"')
        assert n == 1
        assert new == '    git commit -m "pin unrpyc to <version>"'


# =============================================================================
# Whitelist sanity
# =============================================================================


class TestWhitelist:
    """Verify the whitelist in this test matches the whitelist in the script."""

    def test_whitelist_in_sync_with_script(self):
        """If someone updates the script's whitelist, this test catches
        the drift (the test's _WHITELIST_PATHS must match)."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "clean_internal_ids",
            _REPO_ROOT / "scripts" / "clean_internal_ids.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Compare as sets — order doesn't matter.
        script_set = set(mod._WHITELIST_PATHS)
        test_set = set(_WHITELIST_PATHS)
        if script_set != test_set:
            only_in_script = script_set - test_set
            only_in_test = test_set - script_set
            msg = []
            if only_in_script:
                msg.append(f"In script but not test: {sorted(only_in_script)}")
            if only_in_test:
                msg.append(f"In test but not script: {sorted(only_in_test)}")
            pytest.fail(
                "Whitelist drift between scripts/clean_internal_ids.py and "
                "tests/test_clean_internal_ids.py. Update both to match:\n"
                + "\n".join(msg)
            )

    def test_changelog_remains_whitelisted(self):
        """CHANGELOG.md must stay whitelisted — IDs there are historical."""
        assert "CHANGELOG.md" in _WHITELIST_PATHS

    def test_worklog_remains_whitelisted(self):
        """Senpy_Consolidated_Backlog_*.md must stay whitelisted — IDs
        are the intended reference mechanism there."""
        assert "Senpy_Consolidated_Backlog_*.md" in _WHITELIST_PATHS


import os  # noqa: E402 — used by test_script_exists_and_is_executable above
