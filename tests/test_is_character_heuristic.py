"""Tests for RPY701 is_character heuristic.

``file_collector.py:353`` used a loose substring check:
``is_char = "Character" in clean or "DynamicCharacter" in clean``.
This matches any line containing "Character" as a substring — including
function names like ``NotCharacterRelated()``, string literals like
``"Some Character string"``, and comments. The result: RPY701 (unused
define) skipped these false-positive "characters", producing false
negatives (genuinely unused constants were not reported).

The fix replaces the substring check with a regex that requires
``Character`` or ``DynamicCharacter`` to appear as a function CALL
followed by ``(`` — the actual Ren'Py character-definition pattern:
``define x = Character("Alice")``.
"""

from __future__ import annotations

from pathlib import Path

from senpy.core.analyzer import SenpyAnalyzer


def _run_analyzer(project_path: Path) -> list[tuple[str, str]]:
    """Run analyzer and return (code, message) pairs."""
    analyzer = SenpyAnalyzer(str(project_path), no_cache=True)
    analyzer.run(quiet=True)
    return [(d.code, d.message) for d in analyzer.diagnostics]


class TestIsCharacterHeuristic:
    """is_character must only be True for actual Character/DynamicCharacter calls."""

    def test_real_character_is_character_true(self, tmp_path: Path):
        """define x = Character('Alice') → is_character=True (correct, no RPY701)."""
        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        (game / "script.rpy").write_text(
            'define x = Character("Alice")\nlabel start:\n    return\n',
            encoding="utf-8",
        )
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        var = analyzer.variables.get("x")
        assert var is not None, "x must be registered as a variable."
        assert var.is_character is True, (
            "define x = Character('Alice') must set is_character=True — "
            "this is a real character definition."
        )
        # RPY701 must NOT fire (characters are excluded from unused-define check).
        rpy701 = [d for d in analyzer.diagnostics if d.code == "RPY701"]
        assert rpy701 == [], f"RPY701 must NOT fire on a Character definition. Got: {rpy701}"

    def test_dynamic_character_is_character_true(self, tmp_path: Path):
        """define x = DynamicCharacter('Alice') → is_character=True."""
        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        (game / "script.rpy").write_text(
            'define x = DynamicCharacter("Alice")\nlabel start:\n    return\n',
            encoding="utf-8",
        )
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        var = analyzer.variables.get("x")
        assert var is not None
        assert (
            var.is_character is True
        ), "define x = DynamicCharacter('Alice') must set is_character=True."

    def test_not_character_related_function_is_character_false(self, tmp_path: Path):
        """define w = NotCharacterRelated() → is_character=False (substring false positive).

        Before P2-6: 'Character' is a substring of 'NotCharacterRelated' →
        is_character=True → RPY701 skipped the unused define (false negative).
        After P2-6: regex requires Character( call — NotCharacterRelated( does
        not match → is_character=False → RPY701 fires correctly.
        """
        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        (game / "script.rpy").write_text(
            "define w = NotCharacterRelated()\nlabel start:\n    return\n",
            encoding="utf-8",
        )
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        var = analyzer.variables.get("w")
        assert var is not None, "w must be registered as a variable."
        assert var.is_character is False, (
            f"define w = NotCharacterRelated() must set is_character=False — "
            f"'Character' is a substring of 'NotCharacterRelated' but this is NOT "
            f"a character definition. Before P2-6: is_character=True (false). "
            f"Got is_character={var.is_character}."
        )
        # RPY701 must fire (w is unused, not a character).
        rpy701 = [d for d in analyzer.diagnostics if d.code == "RPY701"]
        assert rpy701, (
            "RPY701 must fire on 'define w = NotCharacterRelated()' — it is "
            "unused and NOT a character definition. Before P2-6: RPY701 was "
            "skipped (false negative) because 'Character' substring matched."
        )

    def test_string_literal_with_character_is_character_false(self, tmp_path: Path):
        """define x = 'Some Character string' → is_character=False.

        String literals containing 'Character' must not be treated as
        character definitions. Before P2-6: substring match on the raw
        line caught 'Character' inside the string → false is_character=True.
        """
        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        (game / "script.rpy").write_text(
            'define x = "Some Character string"\nlabel start:\n    return\n',
            encoding="utf-8",
        )
        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)
        var = analyzer.variables.get("x")
        # x may or may not be registered (depends on RE_DEFINE matching),
        # but if it is, is_character must be False.
        if var is not None:
            assert var.is_character is False, (
                f"define x = 'Some Character string' must set is_character=False — "
                f"'Character' is inside a string literal, not a function call. "
                f"Got is_character={var.is_character}."
            )
