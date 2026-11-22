"""RED→GREEN tests for the silent-except logging cluster.

Three roadmap items share one root cause: ``except OSError`` /
``except (OSError, UnicodeDecodeError)`` blocks that swallow the
exception without any log line, so a file that cannot be read
(PermissionError, disk error, race condition, encoding) silently
drops out of analysis and the user sees "0 diagnostics" with no
clue that anything was skipped.

  * coverage.py:53        — ``except (OSError, UnicodeDecodeError): continue``
  * file_collector.py:840 — ``except OSError: pass``
  * translation.py:39/304/368 — three swallow blocks in analyze_tl_file,
    _build_lang_map, _find_first_occurrence

The fix adds a ``_logger.warning(...)`` line to each block, naming the
file and the exception. These tests assert the warning is emitted
through the central ``senpy`` logger (so ``caplog`` and any
production handler can see it), using ``unittest.mock.patch`` on
``builtins.open`` for deterministic OSError without depending on
filesystem permissions (which would be unreliable under a root
sandbox).

Covers the coverage-logging fix, the collector-logging fix, the translation-logging fix.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.coverage import calculate_translation_coverage
from senpy.core.logging import setup_logging
from senpy.rules.checkers.translation import (
    _build_lang_map,
    _find_first_occurrence,
    analyze_tl_file,
)


@pytest.fixture(autouse=True)
def reset_logging():
    """Clean logger config before each test (NullHandler, propagate=True).

    caplog captures via the root logger's propagation, so the senpy
    logger must have propagate=True and a NullHandler (no StreamHandler
    that would steal the record). ``setup_logging()`` with no args is
    exactly that configuration.
    """
    setup_logging()
    yield


# ===========================================================================
# Shared helper: open() that raises OSError for a specific path only.
# ===========================================================================


def _open_raising_for(target_suffix: str, exc: Exception):
    """Return a side_effect that raises *exc* when the opened path ends
    with *target_suffix*, and falls through to the real builtins.open
    otherwise. This lets discover/walk succeed while the per-file read
    fails — exactly the production failure mode.
    """
    real_open = open  # capture before patching

    def side_effect(path, *args, **kwargs):
        p = str(path).replace("\\", "/")
        if p.endswith(target_suffix):
            raise exc
        return real_open(path, *args, **kwargs)

    return side_effect


# ===========================================================================
# the coverage-logging fix: coverage.py — OSError on a TL file must log a warning
# ===========================================================================


def test_coverage_logs_warning_on_unreadable_tl_file(tmp_path: Path, caplog):
    """calculate_translation_coverage must warn when a TL file cannot be read.

    RED today: ``except (OSError, UnicodeDecodeError): continue`` in
    coverage.py swallows the exception; the user gets an empty
    language report with no indication that a file was skipped.
    """
    game = tmp_path / "game"
    ru_dir = game / "tl" / "russian"
    ru_dir.mkdir(parents=True)
    (ru_dir / "common.rpy").write_text('translate russian start:\n    "привет"\n', encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="senpy"):
        with patch(
            "builtins.open",
            side_effect=_open_raising_for(
                "tl/russian/common.rpy", OSError("Permission denied (simulated)")
            ),
        ):
            calculate_translation_coverage(str(tmp_path))

    # The file was skipped, so russian has no strings — but the point
    # is that a WARNING was logged naming the file and the error.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, (
        "no WARNING logged when coverage skipped an unreadable TL file — "
        "the coverage-logging fix not applied"
    )
    msg = warnings[0].getMessage()
    assert "common.rpy" in msg, f"warning message must name the skipped file; got: {msg!r}"
    assert (
        "Permission denied" in msg
    ), f"warning message must include the exception detail; got: {msg!r}"


# ===========================================================================
# the collector-logging fix: file_collector.py — OSError in _collect_symbols must log a warning
# ===========================================================================


def test_collect_symbols_logs_warning_on_oserror(tmp_path: Path, caplog):
    """_collect_symbols must warn when a file open raises OSError.

    RED today: ``except OSError: pass`` (file_collector.py:840) silently
    skips the file. The user sees "0 diagnostics" and assumes the
    file was clean, when in fact it was never read.

    We exercise the path through SenpyAnalyzer.run() — discover walks
    the directory successfully (file exists), but the per-file
    _collect_symbols open() raises OSError.
    """
    game = tmp_path / "game"
    game.mkdir(parents=True)
    (game / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)

    with caplog.at_level(logging.WARNING, logger="senpy"):
        with patch(
            "builtins.open",
            side_effect=_open_raising_for("game/script.rpy", OSError("disk error (simulated)")),
        ):
            # _collect_symbols is called inside run(); we call it
            # directly to avoid the full run() machinery, but the
            # exception path is identical.
            analyzer._collect_symbols(str(game / "script.rpy"))

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, (
        "no WARNING logged when _collect_symbols skipped an unreadable file — "
        "the collector-logging fix not applied"
    )
    msg = warnings[0].getMessage()
    assert "script.rpy" in msg, f"warning message must name the skipped file; got: {msg!r}"
    assert "disk error" in msg, f"warning message must include the exception detail; got: {msg!r}"


# ===========================================================================
# the translation-logging fix: translation.py — three swallow sites must each log a warning
# ===========================================================================


def _make_fake_analyzer() -> MagicMock:
    """Minimal analyzer stand-in for analyze_tl_file.

    analyze_tl_file reads analyzer.in_memory_files (empty), then opens
    the file directly. On UnicodeDecodeError it calls
    analyzer._emit_encoding_error; on OSError it returns. We stub both
    so the OSError path is the one exercised.
    """
    a = MagicMock()
    a.in_memory_files = {}
    a.diagnostics = []
    a.total_lines = 0
    return a


def test_analyze_tl_file_logs_warning_on_oserror(tmp_path: Path, caplog):
    """analyze_tl_file must warn when the TL file open raises OSError.

    RED today: ``except OSError: return`` (translation.py:39) silently
    returns — the file drops out of TL analysis with no trace.
    """
    tl_dir = tmp_path / "game" / "tl" / "russian"
    tl_dir.mkdir(parents=True)
    tl_file = tl_dir / "common.rpy"
    tl_file.write_text('translate russian start:\n    "привет"\n', encoding="utf-8")

    analyzer = _make_fake_analyzer()

    with caplog.at_level(logging.WARNING, logger="senpy"):
        with patch(
            "builtins.open",
            side_effect=_open_raising_for(
                "tl/russian/common.rpy", OSError("file handle revoked (simulated)")
            ),
        ):
            analyze_tl_file(analyzer, str(tl_file))

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, (
        "no WARNING logged when analyze_tl_file skipped an unreadable TL file — "
        "the translation-logging fix (site 1) not applied"
    )
    msg = warnings[0].getMessage()
    assert "common.rpy" in msg, f"warning message must name the skipped file; got: {msg!r}"
    assert (
        "file handle revoked" in msg
    ), f"warning message must include the exception detail; got: {msg!r}"


def test_build_lang_map_logs_warning_on_oserror(tmp_path: Path, caplog):
    """_build_lang_map must warn when a TL file open raises OSError.

    RED today: ``except (OSError, UnicodeDecodeError): continue``
    (translation.py:304) silently skips — the language map is built
    from a partial corpus with no indication.
    """
    tl_dir = tmp_path / "game" / "tl" / "russian"
    tl_dir.mkdir(parents=True)
    tl_file = tl_dir / "common.rpy"
    tl_file.write_text('translate russian start:\n    "привет"\n', encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="senpy"):
        with patch(
            "builtins.open",
            side_effect=_open_raising_for("tl/russian/common.rpy", OSError("io error (simulated)")),
        ):
            _build_lang_map([str(tl_file)])

    # Function still returns (graceful degradation), but a warning
    # must have been logged.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, (
        "no WARNING logged when _build_lang_map skipped an unreadable TL file — "
        "the translation-logging fix (site 2) not applied"
    )
    msg = warnings[0].getMessage()
    assert "common.rpy" in msg, f"warning message must name the skipped file; got: {msg!r}"


def test_find_first_occurrence_logs_warning_on_oserror(tmp_path: Path, caplog):
    """_find_first_occurrence must warn when a TL file open raises OSError.

    RED today: ``except (OSError, UnicodeDecodeError): continue``
    (translation.py:368) silently skips — the lookup returns
    ("<unknown>", 0) with no clue why.
    """
    tl_dir = tmp_path / "game" / "tl" / "russian"
    tl_dir.mkdir(parents=True)
    tl_file = tl_dir / "common.rpy"
    tl_file.write_text('old "hello"\nnew "привет"\n', encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="senpy"):
        with patch(
            "builtins.open",
            side_effect=_open_raising_for(
                "tl/russian/common.rpy", OSError("read failed (simulated)")
            ),
        ):
            _find_first_occurrence("hello", "russian", [str(tl_file)])

    # Function returns ("<unknown>", 0) but must log a warning first.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, (
        "no WARNING logged when _find_first_occurrence skipped an unreadable TL file — "
        "the translation-logging fix (site 3) not applied"
    )
    msg = warnings[0].getMessage()
    assert "common.rpy" in msg, f"warning message must name the skipped file; got: {msg!r}"
