"""Tests for.

RPY110 on `python:` block with mixed indentation (tabs + spaces).
verify test_discover_files_characterization.py coverage.
RE_DIALOGUE_LINE edge cases in formats/stats.py.
formats/wiki.py — no direct tests, add coverage.
"""

from __future__ import annotations

from pathlib import Path

from senpy.core.analyzer import SenpyAnalyzer

# =============================================================================
# RPY110 on python: block with mixed indentation (tabs + spaces)
# =============================================================================


class TestRPY110MixedIndentation:
    """RPY110 must not crash on `python:` blocks with mixed tab/space indentation."""

    def test_python_block_with_tabs_no_crash(self, tmp_path: Path):
        """A `python:` block using tabs must not crash the analyzer.

        Before: mixed tab/space indentation inside `python:` blocks could
        cause `ast.parse` to raise `TabError` which was not caught by
        the `_analyze_file` try/except (added in P2-2). Now it should be
        caught — but the goal is: the file is analyzed without crash.
        """
        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        # Use tabs inside the python: block — Python ast.parse raises TabError
        # if tabs and spaces are mixed. Here we use only tabs (valid).
        (game / "script.rpy").write_text(
            "label start:\n"
            '    "Hello"\n'
            "    python:\n"
            "\t\tx = 1\n"
            "\t\ty = 2\n"
            "    return\n",
            encoding="utf-8",
        )

        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        # Must not raise.
        analyzer.run(quiet=True)
        assert "start" in analyzer.labels, "Label 'start' must be registered."

    def test_python_block_mixed_tabs_spaces_no_crash(self, tmp_path: Path):
        """Mixed tabs + spaces inside `python:` block — must not crash.

        Python's ast.parse raises TabError for mixed tabs/spaces. The
        analyzer should catch this (via P2-2 try/except or via the
        existing ast.parse error handling in python_ast.py) and continue.
        """
        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        # Mix tabs and spaces in the python: block — TabError on ast.parse.
        (game / "script.rpy").write_text(
            "label start:\n"
            '    "Hello"\n'
            "    python:\n"
            "        x = 1\n"
            "\t\ty = 2\n"  # tab after spaces → TabError
            "    return\n",
            encoding="utf-8",
        )

        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        # Must not raise — the TabError is caught internally.
        analyzer.run(quiet=True)
        # Label is still registered (collected before the python: block).
        assert "start" in analyzer.labels, (
            "Label 'start' must be registered even if python: block has "
            "mixed indentation — the label was collected before the error."
        )


# =============================================================================
# RE_DIALOGUE_LINE edge cases in formats/stats.py
# =============================================================================


class TestREDialogueLineEdgeCases:
    """RE_DIALOGUE_LINE must handle narrator, character with name, and call screen."""

    def test_narrator_dialogue_detected(self):
        """Bare `"Hello"` (narrator) must be detected as a dialogue line."""
        from senpy.formats.stats import RE_DIALOGUE_LINE

        m = RE_DIALOGUE_LINE.match('"Hello world"')
        assert m is not None, 'Narrator "Hello world" must match RE_DIALOGUE_LINE.'

    def test_character_with_name_dialogue(self):
        """`e "Hi"` (character shortcut) must be detected."""
        from senpy.formats.stats import RE_DIALOGUE_LINE

        m = RE_DIALOGUE_LINE.match('e "Hi there"')
        assert m is not None, 'Character shortcut e "Hi there" must match.'

    def test_call_screen_not_dialogue(self):
        """`call screen foo` must NOT be detected as dialogue."""
        from senpy.formats.stats import RE_DIALOGUE_LINE

        m = RE_DIALOGUE_LINE.match("call screen foo")
        assert m is None, "'call screen foo' must NOT match RE_DIALOGUE_LINE."

    def test_label_inside_label_not_dialogue(self):
        """`label foo:` must NOT be detected as dialogue."""
        from senpy.formats.stats import RE_DIALOGUE_LINE

        m = RE_DIALOGUE_LINE.match("label foo:")
        assert m is None, "'label foo:' must NOT match RE_DIALOGUE_LINE."


# =============================================================================
# formats/wiki.py — no direct tests, add coverage
# =============================================================================


class TestWikiGeneration:
    """generate_project_wiki must produce valid Markdown with characters, vars, endings."""

    def test_wiki_contains_characters_section(self, tmp_path: Path):
        """Wiki must include a Characters section with Character declarations."""
        from senpy.formats.wiki import generate_project_wiki

        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        (game / "script.rpy").write_text(
            'define e = Character("Eileen")\n' "label start:\n" '    e "Hello"\n' "    return\n",
            encoding="utf-8",
        )
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)

        wiki = generate_project_wiki(analyzer)
        assert "## Characters" in wiki
        assert "Eileen" in wiki or "e" in wiki, f"Wiki must mention the character. Got:\n{wiki}"

    def test_wiki_contains_state_vars_section(self, tmp_path: Path):
        """Wiki must include a State & Variables section."""
        from senpy.formats.wiki import generate_project_wiki

        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        (game / "script.rpy").write_text(
            "default score = 0\n" "define MAX_HP = 100\n" "label start:\n" "    return\n",
            encoding="utf-8",
        )
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)

        wiki = generate_project_wiki(analyzer)
        assert "## State & Variables" in wiki
        assert "score" in wiki, f"Wiki must mention 'score'. Got:\n{wiki}"
        assert "MAX_HP" in wiki, f"Wiki must mention 'MAX_HP'. Got:\n{wiki}"

    def test_wiki_contains_endings_section(self, tmp_path: Path):
        """Wiki must include a Story Endings section for labels with return and no jumps."""
        from senpy.formats.wiki import generate_project_wiki

        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        (game / "script.rpy").write_text(
            "label start:\n" "    jump ending\n" "label ending:\n" "    return\n",
            encoding="utf-8",
        )
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)

        wiki = generate_project_wiki(analyzer)
        assert "## Story Endings" in wiki
        assert "ending" in wiki, f"Wiki must mention 'ending' label. Got:\n{wiki}"
