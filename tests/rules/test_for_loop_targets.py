"""Tests for ``extract_for_targets`` — AST-based for-loop target extraction.

  Screen-language for-loop with tuple unpacking:
    ``for i, (music_file, music_name, music_title) in enumerate(music_list):``
    Previously the regex-based ``RE_FOR_LOOP`` only matched ``for x in ...``
    and silently dropped the tuple case, so RPY202 fired false positives on
    every subsequent ``if current_file == music_file:`` in the same screen.

  For-loop targets inside non-screen contexts (``init python:``,
    label body). Previously only screens got for-targets added to the
    scope; ``init python:`` / label body did not, so RPY103 fired on every
    subsequent ``if fn.lower()...:`` inside the same block.

Edge cases covered:
  - Single identifier: ``for x in ...:`` → {x}
  - Two identifiers: ``for k, v in ...:`` → {k, v}
  - Parens around tuple: ``for (a, b) in ...:`` → {a, b}
  - User case: ``for i, (a, b, c) in enumerate(...):`` → {i, a, b, c}
  - Star unpacking: ``for x, *rest in ...:`` → {x, rest}
  - List target: ``for [a, b] in ...:`` → {a, b}
  - Non-for-line: ``x = 1`` → {}
  - Truncated for-loop (no closing colon): gracefully returns {}
  - Syntax error in target expression: gracefully returns {}

The characterisation tests confirm the fix does not break the existing
``for x in items:`` screen-language path — that one keeps working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer
from senpy.text_utils import extract_for_targets


# =============================================================================
# 1. extract_for_targets — unit tests for every supported shape
# =============================================================================
class TestExtractForTargets:
    """Unit tests for the AST-based extractor."""

    def test_single_identifier(self) -> None:
        assert extract_for_targets("for x in items:") == {"x"}

    def test_two_identifiers(self) -> None:
        assert extract_for_targets("for k, v in d.items():") == {"k", "v"}

    def test_parens_around_tuple(self) -> None:
        assert extract_for_targets("for (a, b) in pairs:") == {"a", "b"}

    def test_user_case_tuple_unpacking(self) -> None:
        """The exact case from user feedback #2 — `for i, (music_file,
        music_name, music_title) in enumerate(music_list):`."""
        assert extract_for_targets(
            "for i, (music_file, music_name, music_title) in enumerate(music_list):"
        ) == {"i", "music_file", "music_name", "music_title"}

    def test_star_unpacking(self) -> None:
        """PEP 3132 extended iterable unpacking."""
        assert extract_for_targets("for x, *rest in items:") == {"x", "rest"}

    def test_list_target(self) -> None:
        assert extract_for_targets("for [a, b] in pairs:") == {"a", "b"}

    def test_nested_tuples(self) -> None:
        assert extract_for_targets("for (a, (b, c)) in nested:") == {"a", "b", "c"}

    def test_indented_line(self) -> None:
        """Ren'Py / Python source typically has leading whitespace."""
        assert extract_for_targets("    for x in items:") == {"x"}
        assert extract_for_targets("\t\tfor x in items:") == {"x"}

    def test_non_for_line_returns_empty(self) -> None:
        assert extract_for_targets("x = 1") == set()
        assert extract_for_targets("if x:") == set()
        assert extract_for_targets("label start:") == set()
        assert extract_for_targets("") == set()

    def test_truncated_for_loop_falls_back_gracefully(self) -> None:
        """A for-loop without closing `:` is incomplete syntax, but our
        extractor appends ``: pass`` as a fallback so it still parses.
        This is intentional — even truncated input shouldn't crash the
        caller; the target name is recoverable from the AST."""
        assert extract_for_targets("for x in items") == {"x"}

    def test_invalid_syntax_in_target_returns_empty(self) -> None:
        """Garbage in the target expression — return empty rather than
        raising SyntaxError up to the caller."""
        # `for 123 in ...` — starts with digit, invalid identifier
        assert extract_for_targets("for 123 in items:") == set()

    def test_does_not_match_format_string(self) -> None:
        """`format` starts with `for` but is not a for-loop — must not
        match."""
        assert extract_for_targets("formatted_string = format(x)") == set()

    def test_does_not_match_foreach(self) -> None:
        """`foreach` starts with `for` but is not a Python keyword —
        must not match."""
        assert extract_for_targets("foreach x in items:") == set()


# =============================================================================
# 2. B.2 — End-to-end: screen-language tuple unpacking
# =============================================================================
class TestScreenForTupleUnpacking:
    """The exact case from user feedback #2.

    `screen music_room():` with a tuple-unpacking for-loop inside, and
    a subsequent `if current_file == music_file:` must NOT fire RPY202
    on `music_file` (was: false positive before B.2)."""

    def test_tuple_unpacking_in_screen_no_rpy202(self, tmp_path: Path) -> None:
        project = tmp_path / "game"
        project.mkdir()
        (project / "script.rpy").write_text(
            "screen music_room():\n"
            "    viewport:\n"
            "        vbox:\n"
            "            for i, (music_file, music_name, music_title) in enumerate(music_list):\n"
            "                if current_file == music_file:\n"
            '                    text "Selected"\n'
            "                else:\n"
            '                    text "Not selected"\n'
            "label start:\n"
            '    "Hello"\n',
            encoding="utf-8",
        )
        a = SenpyAnalyzer(str(tmp_path))
        a.run(quiet=True)
        rpy202 = [d for d in a.diagnostics if d.code == "RPY202"]
        rpy202_music = [d for d in rpy202 if "music_file" in d.message]
        assert not rpy202_music, (
            f"RPY202 fired on `music_file` — should be silenced because "
            f"it's a tuple-unpacked for-loop target. Got: "
            f"{[d.message for d in rpy202_music]}"
        )

    def test_simple_for_loop_in_screen_still_works(self, tmp_path: Path) -> None:
        """Characterization: the existing simple-for-loop case (single
        identifier) must continue to work — no regression from B.2."""
        project = tmp_path / "game"
        project.mkdir()
        (project / "script.rpy").write_text(
            "screen list_items():\n"
            "    for item in items:\n"
            '        text f"[item]"\n'
            "label start:\n"
            '    "Hi"\n',
            encoding="utf-8",
        )
        a = SenpyAnalyzer(str(tmp_path))
        a.run(quiet=True)
        rpy202_item = [d for d in a.diagnostics if d.code == "RPY202" and "item" in d.message]
        assert not rpy202_item, (
            f"RPY202 fired on simple `for item in items:` — regression "
            f"in B.2 fix. Got: {[d.message for d in rpy202_item]}"
        )

    def test_star_unpacking_in_screen(self, tmp_path: Path) -> None:
        """Star unpacking also silences RPY202 (PEP 3132)."""
        project = tmp_path / "game"
        project.mkdir()
        (project / "script.rpy").write_text(
            "screen s():\n"
            "    for first, *rest in items:\n"
            '        text f"First: [first]"\n'
            "label start:\n"
            '    "Hi"\n',
            encoding="utf-8",
        )
        a = SenpyAnalyzer(str(tmp_path))
        a.run(quiet=True)
        rpy202 = [
            d
            for d in a.diagnostics
            if d.code == "RPY202" and ("first" in d.message or "rest" in d.message)
        ]
        assert not rpy202, (
            f"RPY202 fired on star-unpacked for-loop target. Got: " f"{[d.message for d in rpy202]}"
        )


# =============================================================================
# 3. D.2 — End-to-end: for-loop targets in init python / label body
# =============================================================================
class TestNonScreenForLoopTargets:
    """For-loop targets inside ``init python:`` or label body must be
    added to the local scope — same as ScreenChecker does inside
    screens. Without this, RPY103 fires on every reference to the loop
    variable."""

    def test_for_loop_in_init_python_no_rpy103(self, tmp_path: Path) -> None:
        """The exact case from user feedback #5.

        ``init python hide:`` with a ``for fn in renpy.loader.listdirfiles():``
        and subsequent ``if fn.lower().endswith(...)`` must not fire RPY103."""
        project = tmp_path / "game"
        project.mkdir()
        (project / "script.rpy").write_text(
            "init python hide:\n"
            "    def create_automatic_images():\n"
            "        for fn in renpy.loader.listdirfiles():\n"
            "            if fn.startswith('_'):\n"
            "                continue\n"
            "            shortfn = fn[:-4]\n"
            "            print(shortfn)\n"
            "label start:\n"
            '    "Hello"\n',
            encoding="utf-8",
        )
        a = SenpyAnalyzer(str(tmp_path))
        a.run(quiet=True)
        rpy103_fn = [d for d in a.diagnostics if d.code == "RPY103" and "'fn'" in d.message]
        assert not rpy103_fn, (
            f"RPY103 fired on `fn` — should be silenced because it's a "
            f"for-loop target in an init-python block. Got: "
            f"{[d.message for d in rpy103_fn]}"
        )

    def test_for_loop_in_label_body_no_rpy103(self, tmp_path: Path) -> None:
        """For-loop target inside a label body also registered."""
        project = tmp_path / "game"
        project.mkdir()
        (project / "script.rpy").write_text(
            "label start:\n"
            "    $ items = [1, 2, 3]\n"
            "    for it in items:\n"
            "        if it > 1:\n"
            "            pass\n",
            encoding="utf-8",
        )
        a = SenpyAnalyzer(str(tmp_path))
        a.run(quiet=True)
        rpy103_it = [d for d in a.diagnostics if d.code == "RPY103" and "'it'" in d.message]
        assert not rpy103_it, (
            f"RPY103 fired on `it` — should be silenced because it's a "
            f"for-loop target in a label body. Got: "
            f"{[d.message for d in rpy103_it]}"
        )

    def test_tuple_unpacking_in_init_python(self, tmp_path: Path) -> None:
        """Tuple unpacking in init python also works (B.2 + D.2 together)."""
        project = tmp_path / "game"
        project.mkdir()
        (project / "script.rpy").write_text(
            "init python:\n"
            "    for k, v in {'a': 1}.items():\n"
            "        if v > 0:\n"
            "            print(k)\n"
            "label start:\n"
            '    "Hi"\n',
            encoding="utf-8",
        )
        a = SenpyAnalyzer(str(tmp_path))
        a.run(quiet=True)
        rpy103 = [
            d
            for d in a.diagnostics
            if d.code == "RPY103" and ("'k'" in d.message or "'v'" in d.message)
        ]
        assert not rpy103, (
            f"RPY103 fired on tuple-unpacked for-loop targets in "
            f"init-python. Got: {[d.message for d in rpy103]}"
        )

    def test_for_loop_target_does_not_over_suppress(self, tmp_path: Path) -> None:
        """Characterization: registering for-loop targets in scope does
        NOT silence RPY103 for genuinely-undeclared variables that are
        NOT loop targets. We use a label body with a for-loop AND a
        separate top-level ``if undefined_var:`` — the for-loop adds
        ``x`` to the scope, but ``undefined_var`` is still undeclared,
        so RPY103 must fire on it."""
        project = tmp_path / "game"
        project.mkdir()
        (project / "script.rpy").write_text(
            "label start:\n"
            "    $ items = [1, 2, 3]\n"
            "    for x in items:\n"
            "        pass\n"
            "    if undefined_var:\n"
            "        pass\n",
            encoding="utf-8",
        )
        a = SenpyAnalyzer(str(tmp_path))
        a.run(quiet=True)
        rpy103_undefined = [
            d for d in a.diagnostics if d.code == "RPY103" and "undefined_var" in d.message
        ]
        # RPY103 should fire on `undefined_var` — it's never declared
        # anywhere, including not being a loop target. The for-loop fix
        # only adds `x` (the loop target), not `undefined_var`.
        assert rpy103_undefined, (
            "RPY103 did not fire on genuinely-undefined `undefined_var` — "
            "the for-loop fix over-suppressed."
        )
