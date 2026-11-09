"""Regression tests for ``_write_fixed_file`` UnicodeEncodeError handling.

When ``--fix`` produces a replacement that contains a surrogate code point
(``\\udcXX``), the underlying ``open(..., encoding="utf-8").writelines()``
raises ``UnicodeEncodeError`` — which is NOT a subclass of ``OSError``.
Before this fix, ``_write_fixed_file`` only caught ``OSError`` and let
``UnicodeEncodeError`` propagate up to ``_analyze_file``'s broad
``except Exception`` clause — which emits a synthesized RPY000
"internal error" diagnostic. The user saw an internal-error message for
what is actually a fix-replacement-with-bad-bytes condition, and the
file never made it into ``failed_writes`` (so exit code 0 was possible
even though the fix never landed on disk).

After the fix:
- ``_write_fixed_file`` catches both ``OSError`` AND ``UnicodeEncodeError``.
- The path is appended to ``analyzer.failed_writes`` (same path as OSError).
- A WARNING is logged, matching the OSError path.
- ``_force_nonzero_if_failed_writes`` then forces exit code 1.
- The file is NOT replaced on disk (atomic-write contract preserved).

How surrogates actually arise:
- A rule's ``fix_replacement`` could include characters from an upstream
  decoder that produced surrogates (e.g. ``errors="surrogateescape"``).
- User .rpy files read with ``errors="replace"`` are then re-encoded for
  write — UTF-8 strict codec rejects lone surrogates.
- A plugin rule that synthesises replacement text from raw byte buffers
  can inject ``\\udcXX`` if it doesn't sanitize.

These tests exercise the third path via a monkeypatch on the formatter's
line-mutator, so the surrogate flows through the real pipeline rather
than being injected directly into ``_write_fixed_file``.
"""

from __future__ import annotations

import os
from pathlib import Path

from senpy.core.analysis_pipeline import AnalysisPipeline
from senpy.core.analyzer import SenpyAnalyzer

# =============================================================================
# Unit tests on _write_fixed_file directly
# =============================================================================


def _make_fixable_project(tmp_path: Path) -> Path:
    """Create a project whose only .rpy file is fixable by the formatter
    (tab indentation + no spaces around ``=``)."""
    game = tmp_path / "game"
    game.mkdir(parents=True, exist_ok=True)
    script = game / "script.rpy"
    script.write_text(
        "label start:\n\t$x=1\n\treturn\n",
        encoding="utf-8",
    )
    return script


class TestWriteFixedFileUnicodeEncodeError:
    """``_write_fixed_file`` must catch UnicodeEncodeError the same way
    it already catches OSError — record the path in failed_writes, log
    WARNING, do NOT re-raise."""

    def test_unicode_encode_error_recorded_in_failed_writes(self, tmp_path: Path) -> None:
        """A surrogate in the lines list must land in failed_writes."""
        script = _make_fixable_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), fix=False, no_cache=True)
        pipeline: AnalysisPipeline = analyzer._pipeline

        # A line containing a lone surrogate — UTF-8 codec rejects it.
        bad_lines = ["\udc80 invalid surrogate line\n"]

        # Must not raise.
        pipeline._write_fixed_file(str(script), bad_lines)

        assert any(
            os.path.normcase(p) == os.path.normcase(str(script)) or p.endswith("script.rpy")
            for p in analyzer.failed_writes
        ), (
            f"failed_writes must contain script.rpy after UnicodeEncodeError, "
            f"got: {list(analyzer.failed_writes)}"
        )

    def test_unicode_encode_error_logged_as_warning(self, tmp_path: Path, caplog) -> None:
        """A WARNING must be logged with the file path when the write fails
        on a surrogate — same log level as the OSError path."""
        script = _make_fixable_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), fix=False, no_cache=True)
        pipeline: AnalysisPipeline = analyzer._pipeline

        with caplog.at_level("WARNING"):
            pipeline._write_fixed_file(str(script), ["\udc80 surrogate\n"])

        script_name = script.name
        matching = [
            r for r in caplog.records if r.levelname == "WARNING" and script_name in r.getMessage()
        ]
        assert matching, (
            f"No WARNING log mentioning {script_name} was emitted. "
            f"Got records: {[(r.levelname, r.getMessage()) for r in caplog.records]}"
        )

    def test_unicode_encode_error_does_not_overwrite_existing_file(self, tmp_path: Path) -> None:
        """If the write fails, the existing file on disk must NOT be
        truncated or partially overwritten.

        This is the atomic-write contract: a failed write leaves the
        on-disk state as it was before the attempt.
        """
        script = _make_fixable_project(tmp_path)
        original_content = script.read_text(encoding="utf-8")

        analyzer = SenpyAnalyzer(str(tmp_path), fix=False, no_cache=True)
        analyzer._pipeline._write_fixed_file(str(script), ["\udc80 bad\n"])

        after = script.read_text(encoding="utf-8")
        assert after == original_content, (
            "File on disk was modified even though the write raised. "
            "Atomic-write contract violated."
        )

    def test_clean_write_unaffected(self, tmp_path: Path) -> None:
        """A normal write with valid UTF-8 must succeed and not record
        a failed_write. Guards against the fix being too broad."""
        script = _make_fixable_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), fix=False, no_cache=True)
        clean_lines = [
            "label start:\n",
            '    "Hello"\n',
            "    return\n",
        ]

        analyzer._pipeline._write_fixed_file(str(script), clean_lines)

        assert (
            list(analyzer.failed_writes) == []
        ), f"failed_writes should be empty on a clean write, got: {list(analyzer.failed_writes)}"
        assert script.read_text(encoding="utf-8") == "".join(clean_lines)


# =============================================================================
# End-to-end: surrogate in fix_replacement reaches failed_writes via run()
# =============================================================================


def _force_surrogate_in_fixed_lines(pipeline: AnalysisPipeline) -> None:
    """Monkeypatch ``_write_fixed_file`` so the LAST line it writes is
    a surrogate. This simulates a rule whose ``fix_replacement`` ends
    up containing a surrogate code point (e.g. via ``errors='surrogateescape'``
    upstream or a plugin rule that constructs replacement text from raw
    bytes).

    The monkeypatch wraps the original method: it appends one bad line
    to whatever the pipeline already computed, then delegates back to
    the real ``_write_fixed_file``. This exercises the real code path
    (open/writelines/close) rather than mocking ``open`` itself.
    """
    original = pipeline._write_fixed_file

    def _wrap(file_path: str, lines: list[str]) -> None:
        bad_lines = list(lines) + ["\udc80 injected surrogate\n"]
        original(file_path, bad_lines)

    pipeline._write_fixed_file = _wrap  # type: ignore[method-assign]


class TestEndToEndSurrogateInFixReplacement:
    """When ``--fix`` produces a line with a surrogate, the full
    ``analyzer.run(fix=True)`` call must:

      1. NOT raise (no internal-error traceback reaches the user).
      2. Record the path in ``result.failed_writes``.
      3. NOT emit RPY000 — the failure is a fix-replacement issue, not
         an internal analyzer bug. RPY000 is reserved for genuine
         exceptions in the analysis pipeline.
    """

    def test_surrogate_in_fix_replacement_recorded_in_failed_writes(self, tmp_path: Path) -> None:
        script = _make_fixable_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), fix=True, no_cache=True)
        _force_surrogate_in_fixed_lines(analyzer._pipeline)

        # Must not raise.
        result = analyzer.run(quiet=True)

        assert any(
            os.path.normcase(p) == os.path.normcase(str(script)) or p.endswith("script.rpy")
            for p in result.failed_writes
        ), f"failed_writes should contain script.rpy, got: {list(result.failed_writes)}"

    def test_surrogate_in_fix_replacement_does_not_emit_rpy000(self, tmp_path: Path) -> None:
        """Before the fix, the UnicodeEncodeError propagated up to
        ``_analyze_file``'s broad ``except Exception`` clause, which
        emitted a synthesized RPY000 'internal error' diagnostic. This
        was misleading: the analyzer itself didn't crash, the fix
        replacement was simply bad bytes. After the fix, the write
        failure is handled locally in ``_write_fixed_file`` and no
        RPY000 is emitted for it.

        (RPY000 should only appear for genuine internal analyzer bugs
        — a bad fix_replacement is a rule-output issue, not a crash.)
        """
        _make_fixable_project(tmp_path)
        analyzer = SenpyAnalyzer(str(tmp_path), fix=True, no_cache=True)
        _force_surrogate_in_fixed_lines(analyzer._pipeline)

        analyzer.run(quiet=True)

        rpy000 = [d for d in analyzer.diagnostics if d.code == "RPY000"]
        assert rpy000 == [], (
            "RPY000 should NOT be emitted for a UnicodeEncodeError on write — "
            "that's a fix-replacement issue, not an internal analyzer bug. "
            f"Got RPY000: {[(d.code, d.message) for d in rpy000]}"
        )

    def test_surrogate_does_not_abort_other_files_in_same_run(self, tmp_path: Path) -> None:
        """A surrogate-induced write failure on one file must NOT prevent
        other files in the same run from being analyzed and fixed.

        Mirrors ``test_fix_does_not_raise_on_oserror`` in
        ``test_analyzer_fix_failed_writes.py``.
        """
        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        # File A: contains a tab (fixable); will get the surrogate injected.
        script_a = game / "a_script.rpy"
        script_a.write_text("label a:\n\t$x=1\n\treturn\n", encoding="utf-8")
        # File B: also contains a tab; should be fixed normally.
        script_b = game / "b_script.rpy"
        script_b.write_text("label b:\n\t$y=2\n\treturn\n", encoding="utf-8")

        analyzer = SenpyAnalyzer(str(tmp_path), fix=True, no_cache=True)
        # Inject surrogate ONLY into writes for script_a.
        original_write = analyzer._pipeline._write_fixed_file

        def _wrap(file_path: str, lines: list[str]) -> None:
            if os.path.normcase(file_path) == os.path.normcase(str(script_a)):
                original_write(file_path, list(lines) + ["\udc80 bad\n"])
            else:
                original_write(file_path, lines)

        analyzer._pipeline._write_fixed_file = _wrap  # type: ignore[method-assign]

        result = analyzer.run(quiet=True)

        # script_a must be in failed_writes.
        assert any(
            os.path.normcase(p) == os.path.normcase(str(script_a)) or p.endswith("a_script.rpy")
            for p in result.failed_writes
        ), f"script_a missing from failed_writes: {list(result.failed_writes)}"
        # script_b must NOT be in failed_writes (it was written cleanly).
        assert not any(
            os.path.normcase(p) == os.path.normcase(str(script_b)) or p.endswith("b_script.rpy")
            for p in result.failed_writes
        ), (
            f"script_b should have written cleanly, but is in failed_writes: "
            f"{list(result.failed_writes)}"
        )
        # And script_b on disk should now be fixed (spaces, not tabs).
        b_after = script_b.read_text(encoding="utf-8")
        assert (
            "\t" not in b_after
        ), f"script_b should have been fixed (no tabs remaining), got: {b_after!r}"
