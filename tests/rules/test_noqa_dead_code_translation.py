"""Regression tests for noqa suppression in dead_code and translation rules.

These rules historically wrote to ``analyzer.diagnostics.append(...)`` directly,
bypassing ``_add_diagnostic(diag, noqa_map)``. As a result ``# noqa: RPY704``
and similar directives were silently ignored — the user thought they had
suppressed the diagnostic, but it still fired.

Each test:
  1. Builds a project where the rule would normally fire.
  2. Adds a ``# noqa: RPYxxx`` directive on the offending line.
  3. Runs the analyzer.
  4. Asserts that the corresponding diagnostic is NOT in the result.

The companion test on the un-suppressed case (same fixture without noqa)
lives in the per-rule fixtures under ``tests/fixtures/rules/`` — these
tests verify only the suppression path.
"""

from __future__ import annotations

from pathlib import Path

from senpy.core.analyzer import SenpyAnalyzer


def _run(code: str, tmp_path: Path, *, filename: str = "script.rpy"):
    """Write code into a tmp game/ directory and run the analyzer quietly."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / filename).write_text(code, encoding="utf-8")
    analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
    return analyzer.run(quiet=True)


# =============================================================================
# Dead-code rules (RPY701..RPY707) — senpy/rules/dead_code.py
# =============================================================================


def test_noqa_suppresses_rpy701_unused_define(tmp_path: Path):
    """``# noqa: RPY701`` must suppress the unused-define hint."""
    code = "define UNUSED_CONST = 42  # noqa: RPY701\nlabel start:\n    return\n"
    result = _run(code, tmp_path)
    assert not any(
        d.code == "RPY701" for d in result.diagnostics
    ), "RPY701 fired despite `# noqa: RPY701` on the declaration line"


def test_noqa_suppresses_rpy704_unused_default(tmp_path: Path):
    """``# noqa: RPY704`` must suppress the unused-default-variable hint.

    Default variables are a very common dead-code candidate (declared but
    never read), so the ability to suppress RPY704 inline is the most
    user-impactful case of this bug class.
    """
    code = "default unused_var = 0  # noqa: RPY704\nlabel start:\n    return\n"
    result = _run(code, tmp_path)
    assert not any(
        d.code == "RPY704" for d in result.diagnostics
    ), "RPY704 fired despite `# noqa: RPY704` on the declaration line"


def test_noqa_suppresses_rpy703_unused_screen(tmp_path: Path):
    """``# noqa: RPY703`` must suppress the unused-screen hint."""
    code = (
        "screen unused_screen():  # noqa: RPY703\n"
        '    text "never shown"\n'
        "label start:\n"
        "    return\n"
    )
    result = _run(code, tmp_path)
    assert not any(
        d.code == "RPY703" for d in result.diagnostics
    ), "RPY703 fired despite `# noqa: RPY703` on the declaration line"


def test_noqa_suppresses_rpy702_unused_transform(tmp_path: Path):
    """``# noqa: RPY702`` must suppress the unused-transform hint."""
    code = (
        "transform unused_transform():  # noqa: RPY702\n    xoffset 100\nlabel start:\n    return\n"
    )
    result = _run(code, tmp_path)
    assert not any(
        d.code == "RPY702" for d in result.diagnostics
    ), "RPY702 fired despite `# noqa: RPY702` on the declaration line"


# =============================================================================
# Translation rules — senpy/rules/checkers/translation.py
# =============================================================================


def test_noqa_suppresses_rpy801_duplicate_translation_string(tmp_path: Path):
    """``# noqa: RPY801`` must suppress the duplicate-translation-string warning.

    The diagnostic is emitted on the second (duplicate) `old "..."` line, so
    the noqa directive must be placed there.
    """
    game_dir = tmp_path / "game"
    tl_dir = game_dir / "tl" / "english"
    tl_dir.mkdir(parents=True, exist_ok=True)

    tl_code = (
        "translate english start_a1b2c3d4:\n"
        '    old "Hello"\n'
        '    new "Hello"\n'
        "translate english start_e5f6g7h8:\n"
        '    old "Hello"  # noqa: RPY801\n'
        '    new "Hello"\n'
    )
    (tl_dir / "common.rpy").write_text(tl_code, encoding="utf-8")

    # Need at least a script.rpy so the project is non-empty.
    (game_dir / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
    result = analyzer.run(quiet=True)

    assert not any(
        d.code == "RPY801" for d in result.diagnostics
    ), "RPY801 fired despite `# noqa: RPY801` on the offending old line"


def test_noqa_suppresses_rpy603_empty_translation_string(tmp_path: Path):
    """``# noqa: RPY603`` must suppress the empty-translation-string warning.

    The diagnostic is emitted on the `new ""` line, so the noqa directive
    must be placed there.
    """
    game_dir = tmp_path / "game"
    tl_dir = game_dir / "tl" / "english"
    tl_dir.mkdir(parents=True, exist_ok=True)

    tl_code = 'translate english start_a1b2c3d4:\n    old "Hello"\n    new ""  # noqa: RPY603\n'
    (tl_dir / "common.rpy").write_text(tl_code, encoding="utf-8")
    (game_dir / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
    result = analyzer.run(quiet=True)

    assert not any(
        d.code == "RPY603" for d in result.diagnostics
    ), "RPY603 fired despite `# noqa: RPY603` on the offending line"
