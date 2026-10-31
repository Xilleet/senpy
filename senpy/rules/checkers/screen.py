"""screen — extracted from checkers.py (Фаза 2, 0.5.4)."""

from __future__ import annotations

import difflib
import re

from senpy.core.constants import (
    BUILTIN_ACTIONS,
    BUILTIN_SCREENS,
    RE_BUTTON_LINE,
    RE_DEFAULT,
    RE_FOR_LOOP,
    RE_SCREEN_CALL,
    SCREEN_LOCAL_IGNORE,
)
from senpy.core.models import Diagnostic
from senpy.core.scope import ScopeStack
from senpy.core.signature import validate_call_arguments
from senpy.rules.base import BaseChecker


class ScreenChecker(BaseChecker):
    def check_line(
        self,
        file_path: str,
        idx: int,
        raw_line: str,
        clean_line: str,
        scope_stack: ScopeStack,
        noqa_map: dict[int, set[str] | None],
        lines: list[str],
    ) -> tuple[str, bool]:
        stripped = clean_line.strip()
        is_in_screen = scope_stack.current_screen_name() is not None

        if is_in_screen:
            m_def = RE_DEFAULT.match(stripped)
            if m_def:
                scope_stack.add_symbol(m_def.group(1))

            m_for = RE_FOR_LOOP.match(stripped)
            if m_for:
                scope_stack.add_symbol(m_for.group(1))

            self._check_screen_variable_actions(
                file_path, idx, raw_line, stripped, scope_stack, noqa_map
            )
            self._check_screen_action_targets(
                file_path, idx, raw_line, stripped, noqa_map
            )
            self._check_screen_buttons(
                file_path, idx, raw_line, stripped, noqa_map
            )

        self._check_screen_call_targets(
            file_path, idx, raw_line, stripped, noqa_map
        )

        return raw_line, False

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
        if "SetVariable" not in stripped and "ToggleVariable" not in stripped:
            return

        for m_var_act in re.finditer(
            r'\b(SetVariable|ToggleVariable)\s*\(\s*["\']([^\W\d]\w*)["\']', stripped
        ):
            act_name = m_var_act.group(1)
            target_var = m_var_act.group(2)
            local_syms = scope_stack.get_local_symbols()

            # RPY208: Using global SetVariable/ToggleVariable on screen-local variable
            if target_var in local_syms and target_var not in SCREEN_LOCAL_IGNORE:
                correct_act = (
                    "SetScreenVariable"
                    if act_name == "SetVariable"
                    else "ToggleScreenVariable"
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
        if not any(act in stripped for act in ("Show", "ShowMenu", "Hide")):
            return

        for m_scr_act in re.finditer(
            r'\b(?:Show|ShowMenu|Hide)\s*\(\s*["\']([^\W\d]\w*)["\']', stripped
        ):
            target_scr = m_scr_act.group(1)
            if (
                target_scr not in self.analyzer.screens
                and target_scr not in BUILTIN_SCREENS
            ):
                all_screens = list(self.analyzer.screens.keys()) + list(BUILTIN_SCREENS)
                matches = difflib.get_close_matches(
                    target_scr, all_screens, n=1, cutoff=0.6
                )
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
            if fn_name not in BUILTIN_ACTIONS:
                start_c, end_c = self.analyzer._get_utf16_range(
                    raw_line, f"action {fn_name}("
                )
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=idx + 1,
                        line_content=stripped,
                        code="RPY206",
                        message=f"Direct function call '{fn_name}()' in action. It executes immediately during screen render! Use 'action Function({fn_name}, ...)' instead.",
                        col=start_c,
                        end_col=end_c,
                        fix_title=f"Wrap with Function({fn_name})",
                        fix_replacement=f"Function({fn_name})",
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
        if (
            screen_target in self.analyzer.screens
            and self.analyzer.screens[screen_target].signature
        ):
            sig = self.analyzer.screens[screen_target].signature
            m_scr_args = re.search(
                r"\b(?:show\s+screen|call\s+screen|use)\s+[^\W\d]\w*\s*(?:\((.*?)\))?", stripped
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
                        message=f"Invalid parameters in screen '{screen_target}': {err_msg}. Causes runtime Exception.",
                        severity="ERROR",
                    ),
                    noqa_map,
                )
