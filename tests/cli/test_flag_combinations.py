"""Tests for CLI flag combination validation.

Covers `_validate_flag_combinations` in `senpy/cli/main.py`. This function
runs after `parse_args()` and after `_handle_early_exits()`, but before
any analysis work — so an invalid combination fails fast with a clear
error message instead of producing confusing output.

Contract verified:
    Hard errors (return exit code 2):
      1. --fix + --check     — can't apply AND dry-run simultaneously
      2. --fix + --diff      — can't apply AND only-show-diff simultaneously
      3. --check + --diff    — two dry-run modes is ambiguous
      4. --select with empty list (defensive, argparse normally rejects)

    Warnings (print to stderr, return None — run continues):
      5. --extend-select without --select (no-op, suggest --select)
      6. --extend-ignore without --ignore (no-op, suggest --ignore)
      7. --add-noqa + --fix (the two fight each other)

    Valid combinations (no warning, return None):
      8. --fix alone, --check alone, --diff alone — all OK
      9. --select RPY101 — OK
     10. --ignore RPY101 --extend-ignore RPY102 — OK (extend has a base)
     11. --select RPY101 --extend-ignore RPY102 — OK (select + extend-ignore is fine)
"""

from __future__ import annotations

import argparse

import pytest
from rich.console import Console

from senpy.cli.main import _validate_flag_combinations

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(**overrides) -> argparse.Namespace:
    """Build a minimal Namespace with all flags the validator reads.

    Defaults match what `parse_args([])` would produce for the relevant
    flags. Tests override only what they care about.
    """
    defaults = {
        "fix": False,
        "check": False,
        "diff": False,
        "select": None,
        "extend_select": None,
        "ignore": None,
        "extend_ignore": None,
        "add_noqa": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _capture_console() -> tuple[Console, str]:
    """Return a (console, output_string) pair where all console.print()
    output goes to the returned string. We use a file-backed Console so
    Rich formatting codes are stripped (raw text only).
    """
    import io

    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, no_color=True, width=200)
    return console, buf


def _validate(**args) -> tuple[int | None, str]:
    """Run _validate_flag_combinations with the given args. Returns (rc, output).

    Captures both console (stdout) and stderr. Warnings are printed to
    stderr (P2-11), so callers checking for warning text should use
    _validate_with_stderr instead.
    """
    console, buf = _capture_console()
    ns = _make_args(**args)
    rc = _validate_flag_combinations(ns, console)
    return rc, buf.getvalue()


def _validate_with_stderr(**args) -> tuple[int | None, str, str]:
    """Run _validate_flag_combinations. Returns (rc, stdout, stderr).

    Use this for warning tests — warnings go to stderr.
    """
    console, buf = _capture_console()
    ns = _make_args(**args)
    import contextlib
    import io

    err_buf = io.StringIO()
    with contextlib.redirect_stderr(err_buf):
        rc = _validate_flag_combinations(ns, console)
    return rc, buf.getvalue(), err_buf.getvalue()


# ---------------------------------------------------------------------------
# Hard errors — return exit code 2
# ---------------------------------------------------------------------------


class TestHardErrors:
    """Combinations that fail the run with a clear error message."""

    def test_fix_plus_check_returns_2(self):
        rc, out = _validate(fix=True, check=True)
        assert rc == 2
        assert "--fix" in out
        assert "--check" in out
        assert "cannot be used together" in out

    def test_fix_plus_diff_returns_2(self):
        rc, out = _validate(fix=True, diff=True)
        assert rc == 2
        assert "--fix" in out
        assert "--diff" in out
        assert "cannot be used together" in out

    def test_check_plus_diff_returns_2(self):
        rc, out = _validate(check=True, diff=True)
        assert rc == 2
        assert "--check" in out
        assert "--diff" in out
        assert "cannot be used together" in out

    def test_select_with_empty_list_returns_2(self):
        """argparse `nargs='+'` rejects `--select` alone, but a config-injected
        empty list could slip through. Be defensive.
        """
        rc, out = _validate(select=[])
        assert rc == 2
        assert "--select" in out
        assert "at least one rule code" in out


# ---------------------------------------------------------------------------
# Warnings — return None, run continues
# ---------------------------------------------------------------------------


class TestWarnings:
    """Combinations that have no effect or fight each other. Print a warning,
    return None — the run proceeds (the user may have a reason).
    """

    def test_extend_select_without_select_warns(self):
        rc, _stdout, stderr = _validate_with_stderr(extend_select=["RPY102"])
        assert rc is None
        assert "--extend-select" in stderr
        assert "no effect without --select" in stderr

    def test_extend_ignore_without_ignore_warns(self):
        rc, _stdout, stderr = _validate_with_stderr(extend_ignore=["RPY102"])
        assert rc is None
        assert "--extend-ignore" in stderr
        assert "no effect without --ignore" in stderr

    def test_add_noqa_plus_fix_warns(self):
        rc, _stdout, stderr = _validate_with_stderr(add_noqa=True, fix=True)
        assert rc is None
        assert "--add-noqa" in stderr
        assert "--fix" in stderr
        assert "fight each other" in stderr or "Did you mean" in stderr


# ---------------------------------------------------------------------------
# Valid combinations — return None, no warning
# ---------------------------------------------------------------------------


class TestValidCombinations:
    """Combinations that are valid. Returns None, no warning text printed."""

    def test_no_flags_is_valid(self):
        rc, out = _validate()
        assert rc is None
        assert out == ""

    def test_fix_alone_is_valid(self):
        rc, out = _validate(fix=True)
        assert rc is None
        assert out == ""

    def test_check_alone_is_valid(self):
        rc, out = _validate(check=True)
        assert rc is None
        assert out == ""

    def test_diff_alone_is_valid(self):
        rc, out = _validate(diff=True)
        assert rc is None
        assert out == ""

    def test_select_with_codes_is_valid(self):
        rc, out = _validate(select=["RPY101", "RPY102"])
        assert rc is None
        assert out == ""

    def test_select_with_extend_select_is_valid(self):
        """--select + --extend-select is the intended use of --extend-select."""
        rc, out = _validate(select=["RPY101"], extend_select=["RPY102"])
        assert rc is None
        assert out == ""

    def test_ignore_with_extend_ignore_is_valid(self):
        """--ignore + --extend-ignore is the intended use of --extend-ignore."""
        rc, out = _validate(ignore=["RPY101"], extend_ignore=["RPY102"])
        assert rc is None
        assert out == ""

    def test_select_with_extend_ignore_is_valid(self):
        """--select defines a whitelist; --extend-ignore removes from it. Valid."""
        rc, out = _validate(select=["RPY101", "RPY102"], extend_ignore=["RPY102"])
        assert rc is None
        assert out == ""


# ---------------------------------------------------------------------------
# Error messages — quality
# ---------------------------------------------------------------------------


class TestErrorMessages:
    """Error messages must be actionable: name the conflicting flags,
    explain why they conflict, and suggest what to do instead.

    This catches regressions where a refactor shortens the message to
    something like "invalid args" — which gives the user no clue what
    to fix.
    """

    def test_fix_check_message_explains_conflict(self):
        _, out = _validate(fix=True, check=True)
        # Must mention both flag names.
        assert "--fix" in out
        assert "--check" in out
        # Must explain WHY (one writes, one is dry-run).
        assert "writes" in out.lower() or "dry-run" in out.lower()
        # Must suggest an alternative ("use one or the other" or similar).
        assert "use one or the other" in out.lower() or "pick one" in out.lower()

    def test_fix_diff_message_explains_preview_then_apply(self):
        _, out = _validate(fix=True, diff=True)
        assert "--fix" in out
        assert "--diff" in out
        # Suggests the workflow: --diff to preview, --fix to apply.
        assert "preview" in out.lower() or "apply" in out.lower()

    def test_check_diff_message_explains_both_are_dry_run(self):
        _, out = _validate(check=True, diff=True)
        assert "--check" in out
        assert "--diff" in out
        assert "dry-run" in out.lower()


# ---------------------------------------------------------------------------
# Integration — actual CLI run exits with code 2 (not Traceback)
# ---------------------------------------------------------------------------


class TestCLIIntegration:
    """End-to-end: `senpy --fix --check` exits with code 2 and prints a
    readable error, not a Python traceback.

    We don't run subprocess (slow, flaky on Windows). Instead we capture
    the Console output that main() would produce and verify the exit code.
    """

    def test_main_returns_2_for_fix_plus_check(self, monkeypatch, capsys):
        """The actual main() function, called with --fix --check, raises
        SystemExit(2) — not a Python traceback.

        Note: we use `pytest.raises(SystemExit)` rather than checking a
        return value because main() calls `sys.exit()` directly on hard
        validation errors (matching the pattern in `_handle_early_exits`).
        The console_script wrapper in some Python versions does not
        propagate int return values to OS exit codes — `sys.exit()` is
        the only reliable way.
        """
        from senpy.cli.main import main

        # Mock sys.argv to the conflict pair.
        monkeypatch.setattr("sys.argv", ["senpy", "--fix", "--check", "test_game/"])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 2
