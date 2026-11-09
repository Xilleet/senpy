"""Test: UTF-8 BOM handling (P3-B9).

Ren'Py lexer skips leading whitespace, but there's no test for files
that start with a UTF-8 BOM (``\\xef\\xbb\\xbf``). The analyzer should
handle this gracefully — either strip the BOM or treat it as whitespace.
"""

from __future__ import annotations

from pathlib import Path

from senpy.core.analyzer import SenpyAnalyzer


def test_utf8_bom_file_analyzed_without_error(tmp_path: Path):
    """A .rpy file starting with UTF-8 BOM must be analyzed without crash.

    The BOM (\\xef\\xbb\\xbf) appears before the first ``label`` statement.
    If the analyzer doesn't handle it, it may produce a spurious RPY100
    (encoding error) or skip the first line entirely.
    """
    game = tmp_path / "game"
    game.mkdir(parents=True, exist_ok=True)
    # Write a file with UTF-8 BOM prefix.
    bom = b"\xef\xbb\xbf"
    content = b'label start:\n    "Hello"\n    return\n'
    (game / "script.rpy").write_bytes(bom + content)

    analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
    analyzer.run(quiet=True)

    # Must NOT produce RPY100 (encoding error) — BOM is valid UTF-8.
    rpy100 = [d for d in analyzer.diagnostics if d.code == "RPY100"]
    assert rpy100 == [], f"UTF-8 BOM file must not trigger RPY100. Got: {rpy100}"
    # The label 'start' must be registered (first line not skipped).
    assert (
        "start" in analyzer.labels
    ), "Label 'start' must be registered — BOM should not cause the first line to be skipped."


def test_utf8_bom_file_no_bom_same_diagnostics(tmp_path: Path):
    """A file with BOM and without BOM must produce the same diagnostics."""
    game = tmp_path / "game"
    game.mkdir(parents=True, exist_ok=True)

    # Without BOM
    (game / "no_bom.rpy").write_text('label scene_a:\n    "Hello"\n    return\n', encoding="utf-8")
    # With BOM
    bom = b"\xef\xbb\xbf"
    content = b'label scene_b:\n    "Hello"\n    return\n'
    (game / "with_bom.rpy").write_bytes(bom + content)

    analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
    analyzer.run(quiet=True)

    # Both labels must be registered.
    assert "scene_a" in analyzer.labels, "no_bom.rpy label must be registered."
    assert "scene_b" in analyzer.labels, "with_bom.rpy label must be registered."
