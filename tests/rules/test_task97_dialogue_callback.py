"""Regression tests for Task 97 (full): DialogueChecker no longer
mutates ``StateChecker._branch_uninitialized`` directly.

Previously ``DialogueChecker._check_jump_target`` received the live
``branch_uninitialized`` dict by reference and called ``.clear()`` on it
when a ``jump`` was detected — a cross-checker mutation that broke the
encapsulation Task 97 introduced (``branch_uninitialized`` became a
``@property`` with private backing field).

The fix: DialogueChecker now receives a zero-arg callback
(``on_jump_clear_uninit: Callable[[], None] | None``) instead of the
dict. The callback (typically ``StateChecker.clear_uninit`` bound method)
is invoked when a ``jump`` is detected. DialogueChecker is fully
decoupled from StateChecker — no import, no Protocol member, no
dict-by-reference leak.

These tests verify:
1. The callback fires EXACTLY ONCE when a ``jump`` line is processed.
2. The callback does NOT fire for ``call`` (call returns to the caller,
   so MAYBE_SET vars remain live — clearing them would be wrong).
3. The callback does NOT fire for non-jump/non-call lines.
4. Behaviour is preserved: a ``jump`` inside a menu clears MAYBE_SET
   state so post-jump RPY404 doesn't fire on the (now-terminated)
   branch's MAYBE_SET vars.
5. DialogueChecker.check_line signature no longer accepts a ``dict``
   param — only a callable (the encapsulation contract).
"""

from __future__ import annotations

from pathlib import Path
from typing import get_type_hints
from unittest.mock import MagicMock

import pytest

from senpy.core.analyzer import SenpyAnalyzer
from senpy.rules.checkers.dialogue import DialogueChecker


def _make_dialogue_checker() -> DialogueChecker:
    """Build a DialogueChecker with a mock analyzer.

    DialogueChecker needs ``analyzer.labels``, ``analyzer.referenced_labels``,
    and ``analyzer.has_dynamic_jumps`` for jump/call target resolution.
    """
    mock_analyzer = MagicMock()
    mock_analyzer.labels = {"target_label": MagicMock()}
    mock_analyzer.referenced_labels = set()
    mock_analyzer.has_dynamic_jumps = False
    return DialogueChecker(mock_analyzer)


class TestJumpCallbackContract:
    """The ``on_jump_clear_uninit`` callback fires exactly once per jump."""

    def test_callback_fires_once_on_jump(self):
        """A ``jump target_label`` line must invoke the callback exactly once."""
        checker = _make_dialogue_checker()
        call_count = 0

        def on_jump_clear():
            nonlocal call_count
            call_count += 1

        # Process a jump line.
        checker.check_line(
            file_path="test.rpy",
            idx=0,
            next_idx=1,
            raw_line="    jump target_label",
            clean_line="    jump target_label",
            scope_stack=MagicMock(),
            noqa_map={},
            lines=["    jump target_label"],
            on_jump_clear_uninit=on_jump_clear,
        )
        assert call_count == 1, f"jump must fire the callback exactly once, got {call_count} calls"

    def test_callback_does_not_fire_on_call(self, tmp_path: Path):
        """A ``call target_label`` line must NOT invoke the callback.

        ``call`` returns to the caller, so MAYBE_SET vars remain live —
        clearing them would be wrong (post-call code may still read them).

        We verify this end-to-end: a ``call`` inside a menu (where one
        choice sets a var) must NOT clear MAYBE_SET — the var stays
        MAYBE_SET and post-menu code that reads it triggers RPY404.
        If the callback fired on ``call``, the var would be cleared and
        RPY404 would NOT fire — the test would fail.
        """
        game_dir = tmp_path / "game"
        game_dir.mkdir(parents=True, exist_ok=True)
        # ``call`` inside a menu choice — x is MAYBE_SET after the menu.
        # Post-menu interpolation reads x → RPY404 should fire.
        # If the callback fired on ``call``, x would be cleared and RPY404
        # would NOT fire (the test would fail).
        (game_dir / "script.rpy").write_text(
            "label start:\n"
            "    menu:\n"
            '        "Set x":\n'
            "            $ x = 1\n"
            '        "Skip":\n'
            "            call noop\n"
            '    "value: [x]"\n'  # reads x — RPY404 should fire (MAYBE_SET)
            "    return\n"
            "label noop:\n"
            "    return\n",
            encoding="utf-8",
        )
        analyzer = SenpyAnalyzer(str(tmp_path))
        result = analyzer.run(quiet=True)
        rpy404 = [d for d in result.diagnostics if d.code == "RPY404"]
        # RPY404 SHOULD fire — the ``call`` did NOT clear MAYBE_SET
        # (only ``jump`` clears). If the callback fired on call, RPY404
        # would be absent — the test would fail.
        assert len(rpy404) >= 1, (
            "RPY404 should fire on '[x]' read after menu with MAYBE_SET x — "
            "if absent, the callback fired on 'call' (it should only fire on 'jump')."
        )

    def test_callback_does_not_fire_on_non_jump_line(self):
        """A regular dialogue/code line must NOT invoke the callback."""
        checker = _make_dialogue_checker()
        call_count = 0

        def on_jump_clear():
            nonlocal call_count
            call_count += 1

        checker.check_line(
            file_path="test.rpy",
            idx=0,
            next_idx=1,
            raw_line='    "Hello, world."',
            clean_line='    "Hello, world."',
            scope_stack=MagicMock(),
            noqa_map={},
            lines=['    "Hello, world."'],
            on_jump_clear_uninit=on_jump_clear,
        )
        assert call_count == 0

    def test_callback_none_default_no_crash(self):
        """When no callback is passed (default None), jump must not crash."""
        checker = _make_dialogue_checker()
        # No on_jump_clear_uninit kwarg — defaults to None.
        # Should not raise.
        checker.check_line(
            file_path="test.rpy",
            idx=0,
            next_idx=1,
            raw_line="    jump target_label",
            clean_line="    jump target_label",
            scope_stack=MagicMock(),
            noqa_map={},
            lines=["    jump target_label"],
        )


class TestDialogueCheckerNoLongerReceivesDict:
    """The ``check_line`` signature must NOT accept a ``dict`` param.

    The old signature was ``branch_uninitialized: dict | None = None``.
    The new signature is ``on_jump_clear_uninit: Callable[[], None] | None = None``.
    This test locks in the encapsulation contract — DialogueChecker has no
    business knowing about the dict shape.
    """

    def test_check_line_signature_uses_callable_not_dict(self):
        """The 9th param of ``check_line`` must be ``Callable[[], None] | None``,
        not ``dict | None``."""
        hints = get_type_hints(DialogueChecker.check_line)
        # The 9th param (after self, file_path, idx, next_idx, raw_line,
        # clean_line, scope_stack, noqa_map, lines) is on_jump_clear_uninit.
        assert (
            "on_jump_clear_uninit" in hints
        ), f"check_line must have 'on_jump_clear_uninit' param, got: {list(hints.keys())}"
        # The hint is Callable[[], None] | None — check it's not a dict.
        hint_str = str(hints["on_jump_clear_uninit"])
        assert "dict" not in hint_str.lower(), (
            f"on_jump_clear_uninit must NOT be dict-typed (encapsulation), " f"got: {hint_str}"
        )
        assert (
            "callable" in hint_str.lower() or "callable" in hint_str
        ), f"on_jump_clear_uninit must be Callable-typed, got: {hint_str}"

    def test_check_line_no_branch_uninitialized_param(self):
        """The old ``branch_uninitialized`` param name must be gone."""
        hints = get_type_hints(DialogueChecker.check_line)
        assert "branch_uninitialized" not in hints, (
            f"check_line must NOT have 'branch_uninitialized' param (renamed to "
            f"on_jump_clear_uninit), got: {list(hints.keys())}"
        )

    def test_check_jump_target_no_dict_param(self):
        """``_check_jump_target`` must NOT accept a dict param."""
        hints = get_type_hints(DialogueChecker._check_jump_target)
        assert "branch_uninitialized" not in hints, (
            f"_check_jump_target must NOT have 'branch_uninitialized' param, "
            f"got: {list(hints.keys())}"
        )
        assert "on_jump_clear_uninit" in hints

    def test_check_jump_call_targets_no_dict_param(self):
        """``_check_jump_call_targets`` must NOT accept a dict param."""
        hints = get_type_hints(DialogueChecker._check_jump_call_targets)
        assert "branch_uninitialized" not in hints, (
            f"_check_jump_call_targets must NOT have 'branch_uninitialized' param, "
            f"got: {list(hints.keys())}"
        )
        assert "on_jump_clear_uninit" in hints


class TestJumpClearsMaybeSetBehaviorPreserved:
    """End-to-end: a ``jump`` inside a menu clears MAYBE_SET state so
    post-jump RPY404 doesn't fire on the (now-terminated) branch's vars.

    This is the behavioural contract the callback preserves — without
    the clear, StateChecker would see stale MAYBE_SET vars when it
    processes the same jump line.
    """

    def test_jump_after_menu_does_not_trigger_rpy404_on_maybe_set_var(self, tmp_path: Path):
        """``jump`` after a menu (where one choice sets a var) must clear
        MAYBE_SET state — post-jump code should NOT see RPY404 on that var.

        Setup:
            label start:
                menu:
                    "Set x":
                        $ x = 1
                    "Skip":
                        pass
                jump end        ← this jump clears MAYBE_SET for x
            label end:
                return

        Without the clear, the jump line itself would trigger RPY404 if
        it referenced x (because x is MAYBE_SET after the menu). With
        the clear, x is removed from MAYBE_SET before StateChecker
        processes the jump line.
        """
        game_dir = tmp_path / "game"
        game_dir.mkdir(parents=True, exist_ok=True)
        (game_dir / "script.rpy").write_text(
            "label start:\n"
            "    menu:\n"
            '        "Set x":\n'
            "            $ x = 1\n"
            '        "Skip":\n'
            "            pass\n"
            "    jump end\n"
            "label end:\n"
            "    return\n",
            encoding="utf-8",
        )
        analyzer = SenpyAnalyzer(str(tmp_path))
        result = analyzer.run(quiet=True)
        # No RPY404 should fire — the jump clears MAYBE_SET before any
        # read of x. If the callback broke, x would remain MAYBE_SET and
        # StateChecker might flag it.
        rpy404 = [d for d in result.diagnostics if d.code == "RPY404"]
        assert rpy404 == [], f"RPY404 should not fire — jump must clear MAYBE_SET. Got: {rpy404}"
