"""screen — extracted from checkers.py (Phase 2, 0.5.4)."""

from __future__ import annotations

import difflib
import re

from senpy.core.constants import (
    BUILTIN_ACTIONS,
    BUILTIN_SCREENS,
    RE_BUTTON_LINE,
    RE_DEFAULT,
    RE_SCREEN_CALL,
    SCREEN_LOCAL_IGNORE,
)
from senpy.core.models import Diagnostic
from senpy.core.scope import ScopeStack
from senpy.core.signature import validate_call_arguments
from senpy.rules.base import BaseChecker
from senpy.text_utils import extract_for_targets, strip_string_literals


class ScreenChecker(BaseChecker):
    def check_line(
        self,
        file_path: str,
        idx: int,
        next_idx: int,
        raw_line: str,
        clean_line: str,
        scope_stack: ScopeStack,
        noqa_map: dict[int, set[str] | None],
        lines: list[str],
    ) -> tuple[int, bool]:
        stripped = clean_line.strip()
        is_in_screen = scope_stack.current_screen_name() is not None

        if is_in_screen:
            m_def = RE_DEFAULT.match(stripped)
            if m_def:
                scope_stack.add_symbol(m_def.group(1))

            # Add every loop-target name to the local scope, not just
            # the first one. ``RE_FOR_LOOP`` (regex) only matched
            # ``for x in ...`` and silently dropped tuple unpacking like
            # ``for i, (a, b, c) in enumerate(...)`` — causing RPY202
            # false positives on subsequent ``if a == b:`` in the same
            # screen. AST extraction covers every Python for-target shape.
            for target_name in extract_for_targets(stripped):
                scope_stack.add_symbol(target_name)

            self._check_screen_variable_actions(
                file_path, idx, raw_line, stripped, scope_stack, noqa_map
            )
            self._check_screen_action_targets(file_path, idx, raw_line, stripped, noqa_map)
            self._check_screen_buttons(file_path, idx, raw_line, stripped, noqa_map)

        self._check_screen_call_targets(file_path, idx, raw_line, stripped, noqa_map)

        return next_idx, False

    def _check_screen_variable_actions(
        self,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        scope_stack: ScopeStack,
        noqa_map: dict[int, set[str] | None],
    ) -> None:
        """RPY202 & RPY208: Check SetVariable/ToggleVariable screen actions."""
        # Mask string-literal contents before substring/regex matching so
        # that dialogue text mentioning `SetVariable('foo', 1)` cannot
        # trigger false positives (see `strip_string_literals` docstring).
        # Per-match filtering drops any match that lands inside a string
        # literal, preserving real action calls.
        masked = strip_string_literals(stripped)
        if "SetVariable" not in masked and "ToggleVariable" not in masked:
            return

        for m_var_act in re.finditer(
            r'\b(SetVariable|ToggleVariable)\s*\(\s*["\']([^\W\d]\w*)["\']', stripped
        ):
            # Drop matches that begin inside a string literal — they are
            # dialogue/Python text mentions, not real screen actions.
            if m_var_act.start() < len(masked) and masked[m_var_act.start()] == " ":
                continue
            act_name = m_var_act.group(1)
            target_var = m_var_act.group(2)
            local_syms = scope_stack.get_local_symbols()

            # RPY208: Using global SetVariable/ToggleVariable on screen-local variable
            if target_var in local_syms and target_var not in SCREEN_LOCAL_IGNORE:
                correct_act = (
                    "SetScreenVariable" if act_name == "SetVariable" else "ToggleScreenVariable"
                )
                start_c, end_c = self.analyzer._get_utf16_range(raw_line, act_name)
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=idx + 1,
                        line_content=stripped,
                        code="RPY208",
                        message=(
                            f"Screen action '{act_name}' targets screen-local variable '{target_var}'. "
                            f"This leaks into the global store instead of updating the screen! "
                            f"Use '{correct_act}' instead."
                        ),
                        severity="ERROR",
                        col=start_c,
                        end_col=end_c,
                        fix_title=f"Replace '{act_name}' with '{correct_act}'",
                        fix_replacement=correct_act,
                        fix_start_col=start_c,
                        fix_end_col=end_c,
                    ),
                    noqa_map,
                )

            elif (
                target_var not in self.analyzer.declared_symbols
                and target_var not in self.analyzer.user_symbols
                and target_var not in local_syms
                and not target_var.startswith("_")
            ):
                matches = difflib.get_close_matches(
                    target_var, list(self.analyzer.user_symbols), n=1, cutoff=0.6
                )
                hint = f" (did you mean '{matches[0]}' ?)" if matches else ""
                start_c, end_c = self.analyzer._get_utf16_range(raw_line, target_var)
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=idx + 1,
                        line_content=stripped,
                        code="RPY202",
                        message=(
                            f"Screen action references undeclared variable '{target_var}'{hint}. "
                            "Variable must be declared with 'default' at top-level to ensure save persistence."
                        ),
                        severity="WARNING",
                        col=start_c,
                        end_col=end_c,
                        fix_title=f"Change to '{matches[0]}'" if matches else None,
                        fix_replacement=matches[0] if matches else None,
                    ),
                    noqa_map,
                )

    def _check_screen_action_targets(
        self,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        noqa_map: dict[int, set[str] | None],
    ) -> None:
        """RPY204: Check Show/ShowMenu/Hide screen actions for non-existent screens."""
        # Mask string-literal contents before substring/regex matching so
        # that dialogue text mentioning `Show('foo')` cannot trigger false
        # positives. Per-match filtering drops matches inside literals,
        # preserving real action calls.
        masked = strip_string_literals(stripped)
        if not any(act in masked for act in ("Show", "ShowMenu", "Hide")):
            return

        for m_scr_act in re.finditer(
            r'\b(?:Show|ShowMenu|Hide)\s*\(\s*["\']([^\W\d]\w*)["\']', stripped
        ):
            # Drop matches that begin inside a string literal.
            if m_scr_act.start() < len(masked) and masked[m_scr_act.start()] == " ":
                continue
            target_scr = m_scr_act.group(1)
            if target_scr not in self.analyzer.screens and target_scr not in BUILTIN_SCREENS:
                all_screens = list(self.analyzer.screens.keys()) + list(BUILTIN_SCREENS)
                matches = difflib.get_close_matches(target_scr, all_screens, n=1, cutoff=0.6)
                hint = f" (did you mean '{matches[0]}' ?)" if matches else ""
                start_c, end_c = self.analyzer._get_utf16_range(raw_line, target_scr)
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=idx + 1,
                        line_content=stripped,
                        code="RPY204",
                        message=f"Screen action references non-existent screen '{target_scr}'{hint}. Causes runtime ScriptError.",
                        severity="ERROR",
                        col=start_c,
                        end_col=end_c,
                        fix_title=f"Change to '{matches[0]}'" if matches else None,
                        fix_replacement=matches[0] if matches else None,
                    ),
                    noqa_map,
                )

    def _check_screen_buttons(
        self,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        noqa_map: dict[int, set[str] | None],
    ) -> None:
        """RPY203 & RPY206: Check button lines for missing action and direct function calls."""
        m_btn = RE_BUTTON_LINE.match(stripped)
        if not m_btn:
            return

        # RPY203: button without action
        if not stripped.endswith(":") and not re.search(r"\baction\b", stripped):
            btn_word = m_btn.group(1)
            start_c, end_c = self.analyzer._get_utf16_range(raw_line, btn_word)
            self.analyzer._add_diagnostic(
                Diagnostic(
                    file_path=file_path,
                    line_number=idx + 1,
                    line_content=stripped,
                    code="RPY203",
                    message=f"{btn_word.capitalize()} is missing an 'action' argument and will not respond to clicks.",
                    col=start_c,
                    end_col=end_c,
                ),
                noqa_map,
            )
        # RPY206: direct function call in action with parentheses
        m_act = re.search(r"\baction\s+([^\W\d]\w*)\s*\(", stripped)
        if m_act:
            fn_name = m_act.group(1)
            # BUILTIN_ACTIONS is the shipped Ren'Py action library (a
            # frozenset in senpy/core/renpy_builtins.py). The analyzer
            # also holds user-extended actions from
            # `senpy.toml [tool.senpy].additional_actions` so third-party
            # / custom Action classes are not flagged. We build the
            # effective set per-line — a set union of two frozensets is
            # cheap and avoids caching concerns across analyzer lifetime.
            effective_actions = BUILTIN_ACTIONS | self.analyzer._additional_actions
            if fn_name not in effective_actions:
                # Find the matching closing paren of the call so the
                # QuickFix range covers `action myfunc(arg1, arg2)` as a
                # whole, not just `action myfunc(`. Without this, the LSP
                # TextEdit replaces only the prefix and leaves `arg1, arg2)`
                # dangling after the replacement — broken Ren'Py screen code.
                paren_open_pos = m_act.end() - 1  # index of '(' in stripped
                depth = 1
                i = paren_open_pos + 1
                while i < len(stripped) and depth > 0:
                    if stripped[i] == "(":
                        depth += 1
                    elif stripped[i] == ")":
                        depth -= 1
                    i += 1
                if depth == 0:
                    close_paren_pos = i - 1  # index of matching ')'
                else:
                    # Unclosed call — fall back to end of stripped content.
                    close_paren_pos = len(stripped) - 1
                args_content = stripped[paren_open_pos + 1 : close_paren_pos].strip()
                # Build the full call substring to locate it in raw_line
                # (raw_line and stripped differ by leading indent and any
                # trailing comment, but the call expression itself is the
                # same in both).
                full_call_substring = stripped[m_act.start() : close_paren_pos + 1]
                start_c, end_c = self.analyzer._get_utf16_range(raw_line, full_call_substring)
                # Replacement keeps the `action ` prefix and wraps the call
                # in `Function(...)`, preserving the original args. If args
                # are empty (`myfunc()`), the replacement is `action Function(myfunc)`.
                if args_content:
                    replacement = f"action Function({fn_name}, {args_content})"
                    fix_title = f"Wrap with Function({fn_name}, ...)"
                else:
                    replacement = f"action Function({fn_name})"
                    fix_title = f"Wrap with Function({fn_name})"
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=idx + 1,
                        line_content=stripped,
                        code="RPY206",
                        message=f"Direct function call '{fn_name}()' in action. It executes immediately during screen render! Use 'action Function({fn_name}, ...)' instead.",
                        col=start_c,
                        end_col=end_c,
                        fix_title=fix_title,
                        fix_replacement=replacement,
                        fix_start_col=start_c,
                        fix_end_col=end_c,
                    ),
                    noqa_map,
                )

    def _check_screen_call_targets(
        self,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        noqa_map: dict[int, set[str] | None],
    ) -> None:
        """RPY204 & RPY207: Check 'show screen'/'call screen'/'use' for non-existent
        screens and argument mismatches."""
        m_scr = (
            RE_SCREEN_CALL.match(stripped)
            if stripped.startswith(("show screen", "call screen", "use "))
            else None
        )
        if not m_scr:
            return

        screen_target = m_scr.group(1)

        # RPY204: non-existent screen
        if screen_target not in self.analyzer.screens and screen_target not in BUILTIN_SCREENS:
            all_screens = list(self.analyzer.screens.keys()) + list(BUILTIN_SCREENS)
            matches = difflib.get_close_matches(screen_target, all_screens, n=1, cutoff=0.6)
            hint = f" (did you mean '{matches[0]}' ?)" if matches else ""
            start_c, end_c = self.analyzer._get_utf16_range(raw_line, screen_target)
            self.analyzer._add_diagnostic(
                Diagnostic(
                    file_path=file_path,
                    line_number=idx + 1,
                    line_content=stripped,
                    code="RPY204",
                    message=f"Screen '{screen_target}' is not declared in project{hint}. Causes runtime ScriptError.",
                    col=start_c,
                    end_col=end_c,
                ),
                noqa_map,
            )

        # RPY207: argument mismatch
        # Bind signature to a local before the truthiness check so the
        # narrowing carries through to ``validate_call_arguments`` below —
        # re-accessing ``self.analyzer.screens[screen_target].signature``
        # would yield ``SignatureInfo | None`` again.
        if screen_target in self.analyzer.screens:
            sig = self.analyzer.screens[screen_target].signature
            if sig is not None:
                m_scr_args = re.search(
                    r"\b(?:show\s+screen|call\s+screen|use)\s+[^\W\d]\w*\s*(?:\((.*?)\))?",
                    stripped,
                )
                scr_args = (
                    m_scr_args.group(1) if m_scr_args and m_scr_args.group(1) is not None else None
                )
                err_msg = validate_call_arguments(sig, scr_args)
                if err_msg:
                    self.analyzer._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=idx + 1,
                            line_content=stripped,
                            code="RPY207",
                            message=(
                                f"Invalid parameters in screen '{screen_target}': {err_msg}. "
                                "Causes runtime Exception."
                            ),
                            severity="ERROR",
                        ),
                        noqa_map,
                    )
