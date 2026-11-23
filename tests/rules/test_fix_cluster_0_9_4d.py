"""RED tests for stability & data integrity.

``generate_defaults_file`` silently overwrites existing
``senpy_defaults.rpy`` — user edits (noqa, comments, custom defaults)
are lost without warning.

``AnalysisPipeline.run()`` does not clean up
``_dry_run_callback`` on exception — a second call without the callback
still behaves as dry-run (files not written).

``format_dispatch._process_files`` catches ``OSError`` but not
``UnicodeDecodeError`` — ``read_text(encoding="utf-8")`` on a file with
invalid UTF-8 bytes raises ``UnicodeDecodeError`` (subclass of
``ValueError``, NOT ``OSError``), crashing ``senpy format``.

``_get_logical_line`` does not join a bare triple-quoted string
opener in a ``$``-block (no bracket, no backslash) — a ``$``-statement
that opens a triple-quoted string without brackets is returned as a
single line, ``ast.parse`` fails with ``SyntaxError: unterminated
triple-quoted string``, RPY110 fires on valid code.
"""

from __future__ import annotations

import tempfile
import textwrap
from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer


def _analyze(code: str, *, fix: bool = False) -> tuple[list, str]:
    with tempfile.TemporaryDirectory(prefix="senpy_094d_") as tmp:
        game_dir = Path(tmp) / "game"
        game_dir.mkdir(parents=True, exist_ok=True)
        script = game_dir / "script.rpy"
        script.write_text(code, encoding="utf-8")
        analyzer = SenpyAnalyzer(str(tmp), no_cache=True, fix=fix)
        result = analyzer.run(quiet=True)
        fixed_content = script.read_text(encoding="utf-8") if fix else code
        return list(result.diagnostics), fixed_content


# =============================================================================
# FIX-48: generate_defaults_file silently overwrites existing file
# =============================================================================


class TestGenerateDefaultsBackupExisting:
    """``generate_defaults_file`` must not silently overwrite an existing
    ``senpy_defaults.rpy``. User edits (# noqa, comments, custom defaults)
    would be lost without warning.

    Before FIX-48: ``open(out_file, "w")`` truncated the file at open time.

    After FIX-48: if the file exists, a WARNING is logged and a backup
    copy (``senpy_defaults.rpy.bak``) is written before the overwrite.
    """

    def test_existing_defaults_file_backed_up(self, tmp_path: Path) -> None:
        """RED: existing file is silently overwritten, no backup created."""
        game_dir = tmp_path / "game"
        game_dir.mkdir(parents=True, exist_ok=True)
        defaults_file = game_dir / "senpy_defaults.rpy"
        # Write a user-edited file with custom content.
        user_content = "## My custom defaults\n# noqa: RPY104\ndefault my_var = 42\n"
        defaults_file.write_text(user_content, encoding="utf-8")
        # Create a script that produces missing defaults.
        (game_dir / "script.rpy").write_text(
            textwrap.dedent(
                """
                label start:
                    $ undefined_var = 10
                    return
                """
            ),
            encoding="utf-8",
        )
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        assert analyzer.missing_defaults, "Expected missing_defaults to be populated"
        analyzer.generate_defaults_file()
        # The backup file must exist with the original user content.
        backup = game_dir / "senpy_defaults.rpy.bak"
        assert backup.exists(), (
            "Existing senpy_defaults.rpy must be backed up to .bak before "
            "overwrite — user edits would be lost without warning."
        )
        assert (
            backup.read_text(encoding="utf-8") == user_content
        ), f"Backup must contain the original user content. Got: {backup.read_text()!r}"


# =============================================================================
# FIX-51: _dry_run_callback not cleaned up on exception
# =============================================================================


class TestDryRunCallbackCleanup:
    """``AnalysisPipeline.run()`` must clean up ``_dry_run_callback``
    even if the run raises an exception. Without cleanup, a second call
    to ``run()`` without the callback still behaves as dry-run.

    Before FIX-51: ``self._dry_run_callback = dry_run_callback`` at the
    top of ``run()`` with no ``try/finally`` — if ``_analyze_all_files``
    or ``_finalize_results`` raised, the callback stayed set.

    After FIX-51: ``try/finally: self._dry_run_callback = None``.
    """

    def test_dry_run_callback_cleared_after_run(self, tmp_path: Path) -> None:
        """RED: _dry_run_callback leaks across runs when exception occurs.

        We test the simpler case: after a normal run with a callback,
        the callback must be cleared so a subsequent run without one
        writes to disk normally.
        """
        game_dir = tmp_path / "game"
        game_dir.mkdir(parents=True, exist_ok=True)
        (game_dir / "script.rpy").write_text(
            textwrap.dedent(
                """
                label start:
                    "hello"
                    return
                """
            ),
            encoding="utf-8",
        )
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        # Run with a dry_run_callback — captures what would be written.
        captured: list[tuple[str, list[str]]] = []

        def cb(file_path: str, lines: list[str]) -> None:
            captured.append((file_path, lines))

        analyzer.run(quiet=True, dry_run_callback=cb)
        # After run(), _dry_run_callback must be None (cleaned up).
        assert analyzer._pipeline._dry_run_callback is None, (
            "_dry_run_callback must be cleared after run() — if it leaks, "
            "a subsequent run() without the callback still behaves as "
            "dry-run (files not written to disk)."
        )


# =============================================================================
# FIX-70: format_dispatch UnicodeDecodeError not caught
# =============================================================================


class TestFormatUnicodeDecodeError:
    """``senpy format`` must not crash with a raw traceback when a .rpy
    file contains invalid UTF-8 bytes.

    Before FIX-70: ``f.read_text(encoding="utf-8")`` raised
    ``UnicodeDecodeError`` (subclass of ``ValueError``, NOT ``OSError``).
    The ``except OSError`` clause did not catch it, and the exception
    propagated to the top of ``senpy format``, crashing the CLI.

    After FIX-70: ``except (OSError, UnicodeDecodeError) as e:`` — the
    file is skipped with a user-friendly error message.
    """

    def test_format_skips_invalid_utf8_file(self, tmp_path: Path) -> None:
        """RED: senpy format crashes on invalid UTF-8 instead of skipping."""
        from senpy.cli.format_dispatch import _process_files
        from senpy.formatter import FormatConfig, Formatter

        game_dir = tmp_path / "game"
        game_dir.mkdir(parents=True, exist_ok=True)
        # Write a file with invalid UTF-8 bytes.
        bad_file = game_dir / "bad.rpy"
        bad_file.write_bytes(b"\xff\xfe\x00l\x00a\x00b\x00e\x00l\x00")
        # Write a valid file too — format should skip bad.rpy and still
        # process the valid one.
        good_file = game_dir / "good.rpy"
        good_file.write_text('label start:\n    "hello"\n    return\n', encoding="utf-8")

        formatter = Formatter(FormatConfig())
        try:
            _process_files([bad_file, good_file], formatter, check=False, diff=False)
        except UnicodeDecodeError:
            pytest.fail(
                "senpy format must not crash with UnicodeDecodeError on "
                "invalid UTF-8 — the file should be skipped like an OSError."
            )
        # The valid file should still be processed (no crash).
        assert good_file.read_text(encoding="utf-8") is not None


# =============================================================================
# FIX-75: bare triple-string-opener in $-block → false RPY110
# =============================================================================


class TestBareTripleStringOpenerRPY110:
    """A ``$``-statement that opens a triple-quoted string without
    brackets or backslash continuation must not trigger RPY110.

    Before FIX-75: ``_get_logical_line`` returned ``$ x = \"\"\"`` as a
    single line (no backslash, no bracket → no join). ``ast.parse``
    failed with ``SyntaxError: unterminated triple-quoted string``,
    RPY110 fired on valid multi-line code.

    After FIX-75: when ``ast.parse`` for a ``$``-statement fails with a
    string-related SyntaxError, the analyzer retries with a forward
    lookahead that joins lines until the triple-quote closes. If the
    retry succeeds, RPY110 is suppressed.
    """

    def test_bare_triple_string_no_rpy110(self) -> None:
        """RED: RPY110 fires on valid ``$ x = \"\"\"\\n...\\n\"\"\"``."""
        code = textwrap.dedent(
            '''
            label start:
                $ long_text = """
                This is a multi-line string
                that spans several lines.
                """
                return
            '''
        )
        diags, _ = _analyze(code)
        rpy110 = [d for d in diags if d.code == "RPY110"]
        assert rpy110 == [], (
            f"RPY110 must not fire on a valid bare triple-quoted string "
            f"opener in a $-statement. The code is valid Python — "
            f"_get_logical_line must join the continuation lines. "
            f"Got: {[(d.line_number, d.message) for d in rpy110]}"
        )
