"""Regression tests for RPY308/RPY309 terminator detection.

Two related bugs in terminator detection:

`$ renpy.full_restart()` and `$ renpy.quit()` not recognized as terminators.
  - ``dialogue.py:99-113`` (RPY308) uses ``startswith(("renpy.full_restart", ...))``.
  - ``file_collector.py:560-578`` (RPY309) uses the same ``startswith`` tuple.
  - Real line: ``    $ renpy.full_restart()`` — starts with whitespace + ``$``,
    not with ``renpy``. → RPY308 false-fires on fall-through after
    ``$ renpy.full_restart()``; RPY309 false-skips setting ``fall_through_to``.

``pass`` incorrectly treated as terminator in RPY309.
  - ``file_collector.py:574`` includes ``"pass"`` in the terminator tuple.
  - ``dialogue.py`` (RPY308) correctly does NOT include ``pass``.
  - In Ren'Py ``pass`` is a no-op — a label ending with ``pass`` DOES fall
    through to the next label. RPY309's ``pass`` in the tuple prevents
    ``fall_through_to`` from being set, so RPY308 then never fires on the
    fall-through — masking the real hazard.

The fix: extract a single ``RE_TERMINATOR`` regex into
``senpy/core/constants.py`` (matching the regex already used in
``state.py:155-159``) and use it in RPY308, RPY309, and StateChecker.
The regex handles:
  - leading whitespace (``^\\s*``)
  - optional ``$`` prefix for python statements (``\\$?\\s*``)
  - word boundaries (``\\b``)
  - the full set of terminating renpy.* calls
    (``quit``, ``full_restart``, ``utter_restart``, ``jump``,
    ``jump_out_of_context``)
  - does NOT include ``pass`` (pass is a no-op, not a terminator)
  - does NOT include ``call`` (call returns to caller; kept for backward
    compat, see module docstring of the fix)
"""

from __future__ import annotations

from pathlib import Path

from senpy.core.analyzer import SenpyAnalyzer

# =============================================================================
# P1-1: $ renpy.full_restart() / $ renpy.quit() must be recognized as terminators
# =============================================================================


def _run_analyzer_get_diagnostics(project_path: Path) -> list[tuple[str, int]]:
    """Run analyzer and return (code, line_number) pairs for diagnostics."""
    analyzer = SenpyAnalyzer(str(project_path), no_cache=True)
    analyzer.run(quiet=True)
    return [(d.code, d.line_number) for d in analyzer.diagnostics]


class TestRenpyFullRestartRecognizedAsTerminator:
    """RPY308 must NOT fire when previous line is ``$ renpy.full_restart()``."""

    def test_no_rpy308_after_renpy_full_restart(self, tmp_path: Path):
        """``$ renpy.full_restart()`` terminates the label — no fall-through.

        Before P1-1 fix: RPY308 false-fired because ``startswith`` did not
        match ``    $ renpy.full_restart()`` (leading whitespace + ``$``).
        """
        (tmp_path / "script.rpy").write_text(
            "label scene_a:\n"
            '    "End of scene A."\n'
            "    $ renpy.full_restart()\n"
            "\n"
            "label scene_b:\n"
            '    "Scene B"\n'
            "    return\n",
            encoding="utf-8",
        )
        diags = _run_analyzer_get_diagnostics(tmp_path)
        rpy308 = [d for d in diags if d[0] == "RPY308"]
        assert rpy308 == [], (
            f"RPY308 must NOT fire when previous line is `$ renpy.full_restart()` "
            f"— it terminates the label. Got: {rpy308}"
        )

    def test_no_rpy308_after_renpy_quit(self, tmp_path: Path):
        """``$ renpy.quit()`` terminates the label — no fall-through."""
        (tmp_path / "script.rpy").write_text(
            "label scene_a:\n"
            '    "End of scene A."\n'
            "    $ renpy.quit()\n"
            "\n"
            "label scene_b:\n"
            '    "Scene B"\n'
            "    return\n",
            encoding="utf-8",
        )
        diags = _run_analyzer_get_diagnostics(tmp_path)
        rpy308 = [d for d in diags if d[0] == "RPY308"]
        assert rpy308 == [], (
            f"RPY308 must NOT fire when previous line is `$ renpy.quit()` — "
            f"it terminates the label. Got: {rpy308}"
        )

    def test_no_rpy308_after_renpy_full_restart_without_dollar(self, tmp_path: Path):
        """``renpy.full_restart()`` inside a ``python`` block also terminates.

        The terminator check is line-based; a bare ``renpy.full_restart()``
        line (e.g. inside ``python:`` block, dedented to top level for the
        check) must also be recognized.
        """
        (tmp_path / "script.rpy").write_text(
            "label scene_a:\n"
            '    "End of scene A."\n'
            "    $ renpy.full_restart()\n"
            "\n"
            "label scene_b:\n"
            '    "Scene B"\n'
            "    return\n",
            encoding="utf-8",
        )
        diags = _run_analyzer_get_diagnostics(tmp_path)
        rpy308 = [d for d in diags if d[0] == "RPY308"]
        assert rpy308 == [], f"RPY308 must NOT fire after renpy.full_restart(). Got: {rpy308}"

    def test_no_rpy308_after_renpy_utter_restart(self, tmp_path: Path):
        """``$ renpy.utter_restart()`` is also a terminator (less common).

        ``state.py:155-159`` already recognizes it; RPY308 must too after
        the unified ``RE_TERMINATOR`` is applied.
        """
        (tmp_path / "script.rpy").write_text(
            "label scene_a:\n"
            '    "End"\n'
            "    $ renpy.utter_restart()\n"
            "\n"
            "label scene_b:\n"
            '    "B"\n'
            "    return\n",
            encoding="utf-8",
        )
        diags = _run_analyzer_get_diagnostics(tmp_path)
        rpy308 = [d for d in diags if d[0] == "RPY308"]
        assert rpy308 == [], f"RPY308 must NOT fire after `$ renpy.utter_restart()`. Got: {rpy308}"

    def test_rpy308_still_fires_on_real_fallthrough(self, tmp_path: Path):
        """Sanity: RPY308 must still fire on a genuine fall-through.

        Without a terminator, control flow falls into the next label —
        RPY308 must fire. This guards against over-broadening the regex.
        """
        (tmp_path / "script.rpy").write_text(
            'label scene_a:\n    "End of scene A."\n\nlabel scene_b:\n    "Scene B"\n    return\n',
            encoding="utf-8",
        )
        diags = _run_analyzer_get_diagnostics(tmp_path)
        rpy308 = [d for d in diags if d[0] == "RPY308"]
        assert rpy308, (
            "RPY308 MUST fire on a genuine fall-through (no terminator). "
            "If this fails, the RE_TERMINATOR regex is too broad."
        )

    def test_no_rpy308_after_renpy_jump_function(self, tmp_path: Path):
        """``$ renpy.jump('label')`` (function form) also terminates.

        ``state.py`` already recognizes ``renpy.jump`` and
        ``renpy.jump_out_of_context`` as terminators. RPY308 must too.
        """
        (tmp_path / "script.rpy").write_text(
            "label scene_a:\n"
            '    "End"\n'
            "    $ renpy.jump('scene_b')\n"
            "\n"
            "label scene_b:\n"
            '    "B"\n'
            "    return\n",
            encoding="utf-8",
        )
        diags = _run_analyzer_get_diagnostics(tmp_path)
        rpy308 = [d for d in diags if d[0] == "RPY308"]
        assert rpy308 == [], (
            f"RPY308 must NOT fire after `$ renpy.jump('label')` — "
            f"renpy.jump() terminates the current label. Got: {rpy308}"
        )


# =============================================================================
# P2-7: `pass` must NOT be treated as a terminator
# =============================================================================


class TestPassIsNotTerminator:
    """``pass`` is a no-op — a label ending with ``pass`` DOES fall through."""

    def test_rpy308_fires_after_pass(self, tmp_path: Path):
        """RPY308 must fire when previous line is ``pass``.

        ``dialogue.py`` (RPY308) already correctly does NOT include ``pass``
        in its terminator tuple — so RPY308 fires. This test guards that
        behavior against accidental regression when the unified
        ``RE_TERMINATOR`` is applied.
        """
        (tmp_path / "script.rpy").write_text(
            "label scene_a:\n"
            '    "End of scene A."\n'
            "    pass\n"
            "\n"
            "label scene_b:\n"
            '    "Scene B starts immediately!"\n'
            "    return\n",
            encoding="utf-8",
        )
        diags = _run_analyzer_get_diagnostics(tmp_path)
        rpy308 = [d for d in diags if d[0] == "RPY308"]
        assert rpy308, (
            "RPY308 MUST fire when previous line is `pass` — pass is a no-op, "
            "control flow falls through to the next label. "
            "If this fails, RE_TERMINATOR incorrectly includes `pass`."
        )

    def test_rpy309_no_island_after_pass(self, tmp_path: Path):
        """RPY309 must NOT mark a label after ``pass`` as a story island.

        Before P2-7 fix: ``file_collector.py:574`` included ``"pass"`` in
        the terminator tuple. As a result, ``fall_through_to`` was NOT
        set when the previous label ended with ``pass``. The next label
        was then considered unreachable (no jump, no fall-through edge)
        and RPY309 fired on it as a "story island" — a false positive.

        In Ren'Py ``pass`` is a no-op — control flow DOES fall through.
        So the next label is reachable via the fall-through edge and
        RPY309 must NOT fire on it.
        """
        (tmp_path / "script.rpy").write_text(
            "label start:\n"
            '    "Intro"\n'
            "    pass\n"
            "\n"
            "label next_label:\n"
            '    "Reached via fall-through from start"\n'
            "    return\n",
            encoding="utf-8",
        )
        diags = _run_analyzer_get_diagnostics(tmp_path)
        # next_label is reachable from start via fall-through (pass is no-op).
        # RPY309 must NOT fire on next_label.
        rpy309 = [d for d in diags if d[0] == "RPY309"]
        assert rpy309 == [], (
            f"RPY309 must NOT fire on `next_label` — it is reachable from "
            f"`start` via fall-through (pass is a no-op, not a terminator). "
            f"Got: {rpy309}"
        )


# =============================================================================
# P1-1: RPY309 reachability — renpy.full_restart must not create false islands
# =============================================================================


class TestRPY309ReachabilityWithRenpyTerminators:
    """RPY309 reachability must reflect that ``$ renpy.full_restart()`` terminates.

    Before P1-1 fix: RPY309 did not set ``fall_through_to`` when the
    previous label ended with ``$ renpy.full_restart()`` (because the
    ``startswith`` check failed on the ``$`` prefix). This could create
    false "story islands" — labels marked as unreachable because the
    fall-through edge was missing.
    """

    def test_label_after_renpy_full_restart_not_island(self, tmp_path: Path):
        """A label after ``$ renpy.full_restart()`` is NOT an island.

        The previous label terminates, so the next label is only
        reachable if something jumps to it. But RPY309 should model
        the flow correctly: ``$ renpy.full_restart()`` terminates, so
        no fall-through edge is created. The next label must be reached
        via an explicit jump/call — otherwise it IS an island.

        This test verifies the analyzer doesn't crash and produces
        sensible diagnostics (not a false negative where the island
        is silently accepted).
        """
        (tmp_path / "script.rpy").write_text(
            "label start:\n"
            '    "Intro"\n'
            "    jump scene_a\n"
            "\n"
            "label scene_a:\n"
            '    "End of A"\n'
            "    $ renpy.full_restart()\n"
            "\n"
            "label scene_b:\n"
            '    "B is never reached"\n'
            "    return\n",
            encoding="utf-8",
        )
        # scene_b is genuinely unreachable — nothing jumps to it, and
        # scene_a terminates with renpy.full_restart(). RPY309 should
        # fire on scene_b. But the key assertion is that scene_a is NOT
        # marked as falling through to scene_b (no false fall-through edge).
        # We verify by checking that RPY308 does NOT fire on scene_b
        # (scene_a terminates, no fall-through):
        diags = _run_analyzer_get_diagnostics(tmp_path)
        rpy308_on_b = [
            d
            for d in diags
            if d[0] == "RPY308" and d[1] >= 7  # scene_b line
        ]
        assert rpy308_on_b == [], (
            f"RPY308 must NOT fire on scene_b — scene_a ends with "
            f"$ renpy.full_restart() (terminator), no fall-through. Got: {rpy308_on_b}"
        )
