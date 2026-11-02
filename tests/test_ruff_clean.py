"""Characterization test for CI-1: ruff check must exit 0.

This test ensures the Senpy codebase stays ruff-clean. If a developer
adds code that violates ruff rules (unused imports, bare except, type
comparisons, etc.), this test fails — preventing the violation from
being merged.

The test runs `ruff check .` as a subprocess (same as CI). It does NOT
run `ruff format --check` because ruff format would reformat ~105 files
in the current codebase — making format blocking is a separate task
(QUA-4 follow-up).

Configuration:
  - Rules: pyproject.toml [tool.ruff.lint] select/ignore
  - Per-file ignores: pyproject.toml [tool.ruff.lint.per-file-ignores]
  - Excluded paths: pyproject.toml [tool.ruff] extend-exclude
    (senpy-vscode, test_game, build, dist, .senpy_cache, senpy/vendor)

If this test fails:
  1. Run `ruff check .` to see the violations.
  2. Run `ruff check --fix .` for safe auto-fixes (import sorting, etc.).
  3. Manually fix unsafe violations (F841 unused locals, SIM105 try/except,
     etc.) — DO NOT use `--fix --unsafe-fixes` without review.
  4. If a violation is in vendored code (senpy/vendor/), it should be
     excluded — verify `senpy/vendor` is in extend-exclude in pyproject.toml.
  5. If a rule is too strict, add it to `ignore` in pyproject.toml
     (with a comment explaining why).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _ruff_available() -> bool:
    """Return True if ruff is installed and on PATH."""
    try:
        result = subprocess.run(
            ["ruff", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(not _ruff_available(), reason="ruff not installed")
class TestRuffClean:
    """Assert ruff check exits 0 on the Senpy codebase."""

    def test_ruff_check_exits_zero(self):
        """`ruff check .` must exit 0 — no style violations allowed.

        If this fails, run `ruff check .` to see violations, fix them,
        and re-run. See module docstring for the fix workflow.
        """
        result = subprocess.run(
            ["ruff", "check", "."],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            pytest.fail(
                f"ruff check failed with exit code {result.returncode}.\n\n"
                f"STDOUT:\n{result.stdout}\n\n"
                f"STDERR:\n{result.stderr}\n\n"
                f"To fix:\n"
                f"  1. Run `ruff check .` to see violations.\n"
                f"  2. Run `ruff check --fix .` for safe auto-fixes.\n"
                f"  3. Manually fix unsafe violations (F841, SIM105, etc.).\n"
                f"  4. See tests/test_ruff_clean.py docstring for details."
            )

    def test_ruff_config_exists(self):
        """pyproject.toml must have a [tool.ruff] section."""
        pyproject = _REPO_ROOT / "pyproject.toml"
        assert pyproject.exists(), "pyproject.toml missing"
        content = pyproject.read_text(encoding="utf-8")
        assert (
            "[tool.ruff]" in content
        ), "pyproject.toml must have a [tool.ruff] section for ruff config."
        assert (
            "[tool.ruff.lint]" in content
        ), "pyproject.toml must have a [tool.ruff.lint] section with select/ignore rules."

    def test_ruff_excludes_vendored_unrpyc(self):
        """senpy/vendor must be excluded — ruff --fix breaks lazy imports there."""
        pyproject = _REPO_ROOT / "pyproject.toml"
        content = pyproject.read_text(encoding="utf-8")
        # Check that senpy/vendor is in extend-exclude.
        # We look for the string in the [tool.ruff] section.
        ruff_section_start = content.find("[tool.ruff]")
        assert ruff_section_start != -1, "No [tool.ruff] section in pyproject.toml"
        ruff_section = content[ruff_section_start:]
        assert "senpy/vendor" in ruff_section, (
            "senpy/vendor must be in [tool.ruff] extend-exclude. "
            "Running ruff --fix on vendored unrpyc breaks lazy imports "
            "(see commit history for the regression this caused)."
        )


@pytest.mark.skipif(not _ruff_available(), reason="ruff not installed")
class TestPreCommitConfig:
    """Verify .pre-commit-config.yaml exists and references the clean-internal-ids hook."""

    def test_pre_commit_config_exists(self):
        """Pre-commit config must exist (CI-8)."""
        config = _REPO_ROOT / ".pre-commit-config.yaml"
        assert config.exists(), (
            ".pre-commit-config.yaml missing — install pre-commit hooks via "
            "`pip install pre-commit && pre-commit install`."
        )

    def test_pre_commit_has_ruff_hook(self):
        """Pre-commit config must include the ruff hook."""
        config = _REPO_ROOT / ".pre-commit-config.yaml"
        content = config.read_text(encoding="utf-8")
        assert (
            "ruff" in content
        ), ".pre-commit-config.yaml must reference ruff (astral-sh/ruff-pre-commit)."

    def test_pre_commit_has_clean_internal_ids_hook(self):
        """Pre-commit config must include the clean-internal-ids local hook.

        This is the safety net that prevents internal task IDs (DOC-1, CLI-17,
        etc.) from leaking into code via commits.
        """
        config = _REPO_ROOT / ".pre-commit-config.yaml"
        content = config.read_text(encoding="utf-8")
        assert "clean-internal-ids" in content, (
            ".pre-commit-config.yaml must include the clean-internal-ids hook "
            "(runs scripts/clean_internal_ids.py --dry-run on every commit)."
        )


class TestCIWorkflow:
    """Verify .github/workflows/ci.yml has the lint job (CI-1)."""

    def test_ci_workflow_exists(self):
        ci = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
        assert ci.exists(), ".github/workflows/ci.yml missing"

    def test_ci_has_lint_job(self):
        """ci.yml must have a `lint` job that runs ruff check (blocking)."""
        ci = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
        content = ci.read_text(encoding="utf-8")
        assert "  lint:" in content, "ci.yml must have a `lint` job. See CI-1 in the worklog."
        assert "ruff check" in content, "ci.yml lint job must run `ruff check` (blocking step)."

    def test_ci_has_mypy_step(self):
        """ci.yml lint job must include mypy (warn-only is fine for now)."""
        ci = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
        content = ci.read_text(encoding="utf-8")
        assert "mypy" in content, (
            "ci.yml lint job must include a mypy step (warn-only via "
            "continue-on-error is acceptable until QUA-7 is closed)."
        )
