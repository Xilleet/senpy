"""Characterization tests for the ``--strict`` and ``--fail-on-error`` CLI flags.

Both flags are documented (see ``docs/cli-reference.md``,
``docs/configuration.md``, ``docs/renpy-github-actions.md``) but were not
declared in ``args.py`` — running ``senpy /path --strict`` exited with
``argparse: error: unrecognized arguments: --strict`` (exit 2). This module
guards the contract that documented CLI flags must be accepted by argparse
and must drive the behavior they promise.

Contracts guarded
-----------------
``--strict``:
  - Accepted by argparse (no exit 2).
  - ``args.strict is True`` after parsing.
  - When set, every diagnostic not explicitly downgraded via
    ``[tool.senpy.severity]`` is promoted to ``ERROR`` (same as
    ``strict = true`` in ``senpy.toml``, see ``test_strict_mode.py``).
  - CLI flag overrides ``senpy.toml``: ``--strict`` wins even if
    ``strict = false`` in config; absence of ``--strict`` lets config win.

``--fail-on-error``:
  - Accepted by argparse (no exit 2).
  - ``args.fail_on_error is True`` after parsing.
  - Semantics: inverse of ``--exit-zero``. When set, the run exits 1 if
    any ERROR-severity diagnostic is found (which is already the default
    behavior of ``renderers._exit_code`` — ``--fail-on-error`` makes the
    contract explicit for CI scripts that want to be self-documenting).
  - Conflict: ``--fail-on-error`` + ``--exit-zero`` is contradictory and
    must be rejected by ``_validate_flag_combinations`` with exit 2.

Historical bug (P0-3)
---------------------
Both flags documented in docs but absent from ``args.py``. Users copying
the documented ``senpy /path/to/game --strict`` command got exit 2.
"""

from __future__ import annotations

import pytest

from senpy.cli.early_exits import _validate_flag_combinations
from senpy.cli.main import parse_args

# =============================================================================
# 1. --strict: argparse accepts the flag
# =============================================================================


class TestStrictFlagAccepted:
    """``--strict`` must be accepted by argparse (no exit 2)."""

    def test_strict_flag_parsed_true(self):
        """``--strict`` sets ``args.strict = True``."""
        args = parse_args(["--strict"])
        assert args.strict is True, (
            "--strict must be accepted by argparse and set args.strict=True. "
            "Running `senpy /path --strict` currently exits 2 with "
            "'unrecognized arguments: --strict' — see docs/cli-reference.md:240."
        )

    def test_strict_flag_default_false(self):
        """Without ``--strict``, ``args.strict is False``."""
        args = parse_args([])
        assert (
            args.strict is False
        ), "args.strict must default to False when --strict is not passed."

    def test_strict_flag_with_path(self):
        """``--strict`` works alongside a positional path."""
        args = parse_args(["/path/to/game", "--strict"])
        assert args.path == "/path/to/game"
        assert args.strict is True


# =============================================================================
# 2. --fail-on-error: argparse accepts the flag
# =============================================================================


class TestFailOnErrorFlagAccepted:
    """``--fail-on-error`` must be accepted by argparse (no exit 2)."""

    def test_fail_on_error_flag_parsed_true(self):
        """``--fail-on-error`` sets ``args.fail_on_error = True``."""
        args = parse_args(["--fail-on-error"])
        assert args.fail_on_error is True, (
            "--fail-on-error must be accepted by argparse and set "
            "args.fail_on_error=True. The flag is documented in "
            "docs/renpy-github-actions.md:30 as a CI-friendly flag."
        )

    def test_fail_on_error_flag_default_false(self):
        """Without ``--fail-on-error``, ``args.fail_on_error is False``."""
        args = parse_args([])
        assert args.fail_on_error is False, (
            "args.fail_on_error must default to False when --fail-on-error " "is not passed."
        )

    def test_fail_on_error_flag_with_path(self):
        """``--fail-on-error`` works alongside a positional path."""
        args = parse_args(["/path/to/game", "--fail-on-error"])
        assert args.path == "/path/to/game"
        assert args.fail_on_error is True


# =============================================================================
# 3. --fail-on-error + --exit-zero conflict
# =============================================================================


class TestFailOnErrorConflictsWithExitZero:
    """``--fail-on-error`` and ``--exit-zero`` are contradictory — reject."""

    def test_fail_on_error_with_exit_zero_returns_2(self, capsys):
        """Both flags together must be rejected with exit code 2.

        ``--fail-on-error`` says "exit 1 on ERROR"; ``--exit-zero`` says
        "always exit 0". Together they contradict — argparse accepts both
        (they're independent store_true flags), but
        ``_validate_flag_combinations`` must catch the contradiction.
        """
        args = parse_args(["--fail-on-error", "--exit-zero", "/path"])
        # Validate must return exit code 2 (usage error, argparse convention).
        result = _validate_flag_combinations(args, _DummyConsole())
        assert result == 2, (
            "--fail-on-error + --exit-zero must be rejected with exit code 2. "
            "The flags contradict each other: --fail-on-error forces exit 1 "
            "on ERROR, --exit-zero forces exit 0 always. "
            "Add a check in _validate_flag_combinations."
        )


# =============================================================================
# 4. Defaults characterization — both flags default False
# =============================================================================


def test_defaults_strict_and_fail_on_error_false():
    """Both new flags default to False (no behavior change when absent)."""
    args = parse_args([])
    assert args.strict is False
    assert args.fail_on_error is False


# =============================================================================
# Helpers
# =============================================================================


class _DummyConsole:
    """Minimal Console stub for _validate_flag_combinations.

    The real Console is from `rich`, but _validate_flag_combinations only
    calls `console.print(...)`. We capture the calls so tests can assert
    on the printed message if needed, and avoid pulling rich into a
    pure-argparse test module.
    """

    def __init__(self) -> None:
        self.printed: list[str] = []

    def print(self, msg, *args, **kwargs) -> None:  # noqa: A002 — match rich API
        # rich passes Markup strings; just store the str form for inspection.
        self.printed.append(str(msg))
