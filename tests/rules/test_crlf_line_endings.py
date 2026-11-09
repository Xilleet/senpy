"""Regression test for CRLF line endings in ``init python:`` blocks.

``textwrap.dedent`` has a long-standing limitation: it treats ``\\r``
(carriage return) as a non-whitespace character when computing the
common leading whitespace. On Windows, files opened with ``newline=""
(which ``file_collector.py`` does to preserve original line endings)
keep ``\\r\\n`` — and when the joined block lines are fed to
``textwrap.dedent``, the ``\\r``-only lines (empty lines on CRLF) make
the common margin collapse to ``''``, so nothing gets dedented.
``ast.parse`` then fails with "unexpected indent" and every
init-python-dependent check (RPY109, RPY110, RPY502 dynamic
``renpy.image()`` extraction, etc.) silently skips the block.

The fix is ``senpy.text_utils.dedent_python`` which normalizes
``\\r\\n`` / ``\\r`` to ``\\n`` before calling ``textwrap.dedent``.

This test:
  1. Directly verifies ``dedent_python`` strips common indentation
     from CRLF input (where raw ``textwrap.dedent`` fails).
  2. Creates a CRLF fixture file and runs the full analyzer to verify
     no false RPY110 / RPY502.

Originally failed on Windows CI (Python 3.11/3.12/3.13) — see
corpus_findings/findings.md F8 reproduction. The unit test (step 1)
catches the bug on ALL platforms because it feeds CRLF directly to the
helper without going through ``open()``.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from senpy.core.analyzer import SenpyAnalyzer
from senpy.text_utils import dedent_python


def test_dedent_python_handles_crlf() -> None:
    """``dedent_python`` must strip common leading whitespace from CRLF
    input. Raw ``textwrap.dedent`` fails on CRLF (treats ``\\r`` as
    non-whitespace, so the common margin collapses to ``''`` and nothing
    is removed). This is the unit-level regression test that works on
    ALL platforms — no file I/O, no platform-dependent newline handling.
    """
    crlf_input = (
        '    # Comment\r\n    renpy.image("x", "y")\r\n\r\n    for f in [1]:\r\n        pass\r\n'
    )
    lf_input = crlf_input.replace("\r\n", "\n")

    # Control: textwrap.dedent works on LF.
    assert (
        textwrap.dedent(lf_input).lstrip().startswith("#")
    ), "textwrap.dedent should strip indent on LF input"

    # Control: textwrap.dedent FAILS on CRLF (this is the bug we're fixing).
    raw_dedented = textwrap.dedent(crlf_input)
    assert raw_dedented == crlf_input, (
        "textwrap.dedent should NOT strip indent on CRLF input "
        "(this is the known Python limitation we work around)"
    )

    # Fix: dedent_python strips indent on CRLF.
    fixed = dedent_python(crlf_input)
    assert fixed.lstrip().startswith(
        "#"
    ), f"dedent_python must strip common indent from CRLF input. Got: {fixed!r}"
    # The result should be identical to the LF version's dedent.
    assert fixed == textwrap.dedent(lf_input), (
        f"dedent_python(CRLF) must equal textwrap.dedent(LF). "
        f"Got: {fixed!r} vs {textwrap.dedent(lf_input)!r}"
    )


def test_init_python_block_with_crlf_line_endings(tmp_path: Path) -> None:
    """An ``init python:`` block written with CRLF line endings must
    parse correctly — no false RPY110, dynamic ``renpy.image()`` calls
    must be extracted so RPY502 does not fire on references.
    """
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)

    # Write the fixture with EXPLICIT CRLF line endings. We write bytes
    # directly to guarantee CRLF survives into the file regardless of
    # the platform's default line ending.
    fixture_content = (
        "init python:\r\n"
        '    renpy.image("bg_dynamic", "images/bg_dynamic.png")\r\n'
        "\r\n"
        "label start:\r\n"
        "    scene bg_dynamic\r\n"
        '    "Done."\r\n'
        "    return\r\n"
    )
    fixture_path = game_dir / "crlf_test.rpy"
    fixture_path.write_bytes(fixture_content.encode("utf-8"))

    # Verify the file actually has CRLF.
    assert b"\r\n" in fixture_path.read_bytes(), "Fixture must have CRLF line endings"

    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)

    # RPY110 (Python syntax error) must NOT fire — the init python
    # block must parse successfully after CRLF normalization.
    rpy110 = [d for d in result.diagnostics if d.code == "RPY110"]
    assert rpy110 == [], (
        f"RPY110 fired on CRLF init python block — dedent_python did not "
        f"normalize line endings. Got: {[d.message for d in rpy110]}"
    )

    # RPY502 (image not found) must NOT fire on `scene bg_dynamic` —
    # the dynamic renpy.image() call must have registered "bg_dynamic"
    # as a known image.
    rpy502 = [d for d in result.diagnostics if d.code == "RPY502"]
    assert rpy502 == [], (
        f"RPY502 fired on dynamically-registered image with CRLF line "
        f"endings — renpy.image() extraction missed the call because "
        f"ast.parse failed. Got: {[d.message for d in rpy502]}"
    )
