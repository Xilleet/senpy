"""Tests for:

_PLUGINS_LOADED thread safety.
    ``senpy/plugins/autoload.py:43,76,93`` — module-level boolean
    ``_PLUGINS_LOADED`` without lock. LSP doesn't call autoload from
    worker threads now, but if added — race condition (two threads both
    see _PLUGINS_LOADED=False, both load plugins). Add ``threading.Lock``
    around check-and-set.

GitHub Actions `%` → `%25` escape.
    ``render_github`` in ``senpy/cli/renderers.py`` escapes `\n` → space
    and `::` → space, but does NOT escape `%` → `%25`. Per GitHub Actions
    workflow command spec, `%` must be escaped (also CR/LF as `%0D`/`%0A`,
    but `\n` → space already handles LF). Message like ``RPY104: 50%
    complete`` gets truncated/mangled at the `%`.

RPY707 deterministic tie-breaker.
    ``_emit_unused_channel_diagnostic`` in ``senpy/rules/dead_code.py``
    iterates ``register_lines.items()`` — dict order is insertion-ordered
    in CPython 3.7+ but not contracted as deterministic for multi-file
    channel registration. If one channel is registered in multiple files,
    the chosen declaration line depends on iteration order. Add
    deterministic tie-breaker: choose lowest ``(file_path, line_idx)``
    lexicographically.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

# =============================================================================
# P2-9: _PLUGINS_LOADED thread safety
# =============================================================================


class TestPluginsLoadedThreadSafety:
    """_PLUGINS_LOADED must be protected by a lock."""

    def test_autoload_has_lock(self):
        """autoload module must define a threading.Lock for _PLUGINS_LOADED.

        Before P2-9: _PLUGINS_LOADED was a bare bool — two threads could
        both see False and both call the loader. After P2-9: a Lock
        protects the check-and-set.
        """
        from senpy.plugins import autoload

        assert hasattr(autoload, "_PLUGINS_LOADED_LOCK"), (
            "senpy.plugins.autoload must define _PLUGINS_LOADED_LOCK "
            "(threading.Lock) to protect the _PLUGINS_LOADED check-and-set. "
            "Without it, concurrent autoload_plugins() calls race."
        )
        assert isinstance(autoload._PLUGINS_LOADED_LOCK, type(threading.Lock())), (
            f"_PLUGINS_LOADED_LOCK must be a threading.Lock instance, "
            f"got {type(autoload._PLUGINS_LOADED_LOCK)}"
        )

    def test_concurrent_autoload_no_double_load(self, tmp_path: Path):
        """Two threads calling autoload_plugins() must not double-load.

        This is a smoke test — true race conditions are hard to reproduce
        deterministically, but the lock's presence + idempotency check
        means the second caller is a no-op even under contention.
        """
        from senpy.plugins import autoload
        from senpy.plugins.autoload import autoload_plugins

        # Reset to unloaded state.
        autoload._PLUGINS_LOADED = False

        # If there's no _load_plugins_internal, just verify idempotency
        # via _PLUGINS_LOADED flag — second call must be no-op.
        errors: list[str] = []

        def worker():
            try:
                autoload_plugins()
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # After all threads finish, _PLUGINS_LOADED must be True.
        assert autoload._PLUGINS_LOADED is True, (
            "After concurrent autoload_plugins() calls, _PLUGINS_LOADED " "must be True."
        )
        assert errors == [], f"Concurrent autoload_plugins() raised errors: {errors}"


# =============================================================================
# P2-13: GitHub Actions % escape
# =============================================================================


class TestGithubActionsPercentEscape:
    """render_github must escape % → %25 per workflow command spec."""

    def test_percent_in_message_escaped(self, tmp_path: Path, capsys):
        """A message containing % must be escaped to %25.

        Before P2-13: ``RPY104: 50% complete`` was printed as-is —
        GitHub Actions truncated/mangled at the %. After P2-13: the
        message is escaped to ``RPY104: 50%25 complete``.
        """
        import argparse

        from senpy.cli._console import console
        from senpy.cli.renderers import render_github
        from senpy.core.models import Diagnostic

        diag = Diagnostic(
            file_path=str(tmp_path / "script.rpy"),
            line_number=1,
            line_content="$ x = 1",
            code="RPY104",
            message="Variable 'x' is 50% complete",
            severity="ERROR",
            col=0,
        )
        args = argparse.Namespace(
            path=str(tmp_path),
            output_file=None,
            exit_zero=False,
        )
        render_github([diag], args, console)

        captured = capsys.readouterr()
        assert "%25" in captured.out, (
            f"render_github must escape % → %25 in messages. " f"Got output:\n{captured.out}"
        )
        # The raw % (not %25) must NOT appear in the message part.
        # (It may appear in the workflow command syntax, but not in the
        # user-facing message text.)
        assert (
            "50%25 complete" in captured.out
        ), f"Expected '50%25 complete' in output, got:\n{captured.out}"


# =============================================================================
# P2-18: RPY707 deterministic tie-breaker
# =============================================================================


class TestRPY707DeterministicTieBreaker:
    """RPY707 must pick a deterministic declaration line for multi-file channels."""

    def test_rpy707_picks_lowest_file_path(self, tmp_path: Path):
        """When a channel is registered in multiple files, RPY707 must pick
        the lowest (file_path, line_idx) lexicographically — not whatever
        dict iteration order gives.

        Creates two files (z_first.rpy and a_second.rpy) both registering
        the same channel. RPY707 must report the declaration in
        a_second.rpy (lowest file_path), regardless of file processing order.
        """
        from senpy.core.analyzer import SenpyAnalyzer

        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)

        # z_first.rpy registers the channel (processed first alphabetically? No —
        # 'z' > 'a', so a_second.rpy is first. But register_lines dict order
        # depends on which file's _collect_symbols ran first, not alphabetical.)
        (game / "z_first.rpy").write_text(
            "init python:\n"
            '    renpy.music.register_channel("unused_chan", mixer="music")\n'
            "label z_label:\n"
            "    return\n",
            encoding="utf-8",
        )
        (game / "a_second.rpy").write_text(
            "init python:\n"
            '    renpy.music.register_channel("unused_chan", mixer="music")\n'
            "label a_label:\n"
            "    return\n",
            encoding="utf-8",
        )

        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)

        rpy707 = [d for d in analyzer.diagnostics if d.code == "RPY707"]
        assert rpy707, (
            "RPY707 must fire — 'unused_chan' is registered but never used "
            "in any play/queue/stop statement."
        )
        # The reported declaration must be in a_second.rpy (lowest file_path
        # lexicographically), NOT z_first.rpy.
        diag = rpy707[0]
        assert "a_second.rpy" in diag.file_path, (
            f"RPY707 must report the declaration in a_second.rpy (lowest "
            f"file_path lexicographically). Got: {diag.file_path}"
        )
