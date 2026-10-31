"""dialogue — extracted from checkers.py (Фаза 2, 0.5.4)."""

from __future__ import annotations

import difflib
import re

from senpy.core.constants import (
    NON_DIALOGUE_STATEMENTS,
    RE_JUMP_CALL,
    RE_LABEL,
)
from senpy.core.models import Diagnostic
from senpy.core.scope import ScopeStack
from senpy.core.signature import validate_call_arguments
from senpy.core.sink import DiagnosticSink
from senpy.rules.base import BaseChecker


class DialogueChecker(BaseChecker):
    """RPY3xx — Диалоги, проверка кавычек, переходов jump/call и падений в меток."""

    def __init__(self, analyzer: DiagnosticSink):
        super().__init__(analyzer)
        self.in_label_context = False
        self.current_global_label: str | None = None

    def reset(self) -> None:
        self.in_label_context = False
        self.current_global_label = None

    def check_line(
        self,
        file_path: str,
        idx: int,
        raw_line: str,
        clean_line: str,
        scope_stack: ScopeStack,
        noqa_map: dict[int, set[str] | None],
        lines: list[str],
        branch_uninitialized: dict | None = None,
    ) -> tuple[str, bool]:
        stripped = clean_line.strip()
        line_indent = len(raw_line) - len(raw_line.lstrip(" "))
        is_in_screen = scope_stack.current_screen_name() is not None

        if line_indent == 0 and stripped.startswith(("screen ", "style ", "init ", "transform ")):
            self.in_label_context = False

        # RPY308: Label fallthrough check
        m_label = RE_LABEL.match(clean_line)
        if m_label:
            raw_lbl = m_label.group(1)
            if not raw_lbl.startswith("."):
                self.current_global_label = raw_lbl
            self._check_label_fallthrough(file_path, idx, stripped, lines, m_label, noqa_map)
            self.in_label_context = True

        # RPY302, RPY306, RPY310: jump/call targets
        self._check_jump_call_targets(
            file_path, idx, raw_line, stripped, branch_uninitialized, noqa_map
        )

        # RPY302: Jump/Call via UI Actions and Python (renpy.jump, renpy.call)
        self._check_dynamic_jump_targets(file_path, idx, raw_line, stripped, noqa_map)

        # RPY305: Unescaped quotes in dialogue
        self._check_unescaped_quotes(file_path, idx, stripped, is_in_screen, noqa_map)

        return raw_line, False

    def _check_label_fallthrough(
        self,
        file_path: str,
        idx: int,
        stripped: str,
        lines: list[str],
        m_label,
        noqa_map: dict[int, set[str] | None],
    ) -> None:
        """RPY308: Check if label is preceded by fallthrough (no return/jump)."""
        from senpy.text_utils import _strip_comment

        if not self.in_label_context or idx <= 0:
            return

        prev_idx = idx - 1
        while prev_idx >= 0 and not lines[prev_idx].strip():
            prev_idx -= 1
        if prev_idx < 0:
            return

        prev_clean = _strip_comment(lines[prev_idx]).strip()
        if (
            prev_clean
            and not prev_clean.startswith(
                (
                    "return",
                    "jump ",
                    "jump\t",
                    "call ",
                    "call\t",
                    "renpy.full_restart",
                    "renpy.quit",
                )
            )
            and not prev_clean.endswith(":")
        ):
            self.analyzer._add_diagnostic(
                Diagnostic(
                    file_path=file_path,
                    line_number=idx + 1,
                    line_content=stripped,
                    code="RPY308",
                    message=f"Label '{m_label.group(1)}' is preceded by regular statements without 'return' or 'jump'. Control flow will unintentionally fall through.",
                    severity="WARNING",
                ),
                noqa_map,
            )

    def _check_jump_call_targets(
        self,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        branch_uninitialized: dict | None,
        noqa_map: dict[int, set[str] | None],
    ) -> None:
        """RPY302, RPY306, RPY310: Check jump/call targets for non-existent labels,
        return path, and argument validation."""
        m_jump = RE_JUMP_CALL.match(stripped) if stripped.startswith(("jump ", "call ")) else None
        if not m_jump:
            return

        cmd_type, raw_target = m_jump.group(1), m_jump.group(2)
        if raw_target == "expression":
            self.analyzer.has_dynamic_jumps = True
            return

        if raw_target.startswith("."):
            target_label = (
                f"{self.current_global_label}{raw_target}"
                if self.current_global_label
                else raw_target
            )
        else:
            target_label = raw_target

        self.analyzer.referenced_labels.add(target_label)

        # RPY302: non-existent label
        if target_label not in self.analyzer.labels:
            matches = difflib.get_close_matches(
                target_label, list(self.analyzer.labels.keys()), n=1, cutoff=0.6
            )
            best_match = matches[0] if matches else None
            hint = f" (did you mean '{best_match}' ?)" if best_match else ""
            start_c, end_c = self.analyzer._get_utf16_range(raw_line, raw_target)
            self.analyzer._add_diagnostic(
                Diagnostic(
                    file_path=file_path,
                    line_number=idx + 1,
                    line_content=stripped,
                    code="RPY302",
                    message=f"{cmd_type.capitalize()} to non-existent label '{raw_target}'{hint}. Causes ScriptError.",
                    col=start_c,
                    end_col=end_c,
                    fix_title=f"Change to '{best_match}'" if best_match else None,
                    fix_replacement=best_match,
                ),
                noqa_map,
            )

        if cmd_type == "jump" and branch_uninitialized is not None:
            branch_uninitialized.clear()
        elif cmd_type == "call":
            # RPY310: argument validation
            if (
                target_label in self.analyzer.labels
                and self.analyzer.labels[target_label].signature
            ):
                sig = self.analyzer.labels[target_label].signature
                m_args = re.search(
                    r"\bcall\s+(?!screen\b)[^\W\d]\w*\s*(?:\((.*?)\))?", stripped
                )
                call_args = (
                    m_args.group(1) if m_args and m_args.group(1) is not None else None
                )
                err_msg = validate_call_arguments(sig, call_args)
                if err_msg:
                    self.analyzer._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=idx + 1,
                            line_content=stripped,
                            code="RPY310",
                            message=f"Invalid arguments in 'call {target_label}': {err_msg}. Causes fatal TypeError.",
                            severity="ERROR",
                        ),
                        noqa_map,
                    )

            # RPY306: return path check
            if target_label in self.analyzer.labels and not self.analyzer._can_reach_return(
                target_label
            ):
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=idx + 1,
                        line_content=stripped,
                        code="RPY306",
                        message=f"Static analysis could not find a 'return' path from called label '{target_label}'. Verify that control flow returns correctly.",
                    ),
                    noqa_map,
                )

    def _check_dynamic_jump_targets(
        self,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        noqa_map: dict[int, set[str] | None],
    ) -> None:
        """RPY302: Check Jump/Call UI actions and renpy.jump/renpy.call for non-existent labels."""
        if not any(kw in stripped for kw in ("Jump", "Call", "renpy.jump", "renpy.call")):
            return

        for m_dyn in re.finditer(
            r'\b(?:Jump|Call|renpy\.jump|renpy\.call)\s*\(\s*["\']([^"\']+)["\']', stripped
        ):
            raw_target = m_dyn.group(1)
            if raw_target.startswith("."):
                target_label = (
                    f"{self.current_global_label}{raw_target}"
                    if self.current_global_label
                    else raw_target
                )
            else:
                target_label = raw_target

            self.analyzer.referenced_labels.add(target_label)
            if target_label not in self.analyzer.labels:
                matches = difflib.get_close_matches(
                    target_label, list(self.analyzer.labels.keys()), n=1, cutoff=0.6
                )
                best_match = matches[0] if matches else None
                hint = f" (did you mean '{best_match}' ?)" if best_match else ""
                start_c, end_c = self.analyzer._get_utf16_range(raw_line, raw_target)
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=idx + 1,
                        line_content=stripped,
                        code="RPY302",
                        message=f"Jump/Call action to non-existent label '{raw_target}'{hint}. Causes ScriptError.",
                        col=start_c,
                        end_col=end_c,
                        fix_title=f"Change to '{best_match}'" if best_match else None,
                        fix_replacement=best_match,
                    ),
                    noqa_map,
                )

    def _check_unescaped_quotes(
        self,
        file_path: str,
        idx: int,
        stripped: str,
        is_in_screen: bool,
        noqa_map: dict[int, set[str] | None],
    ) -> None:
        """RPY305: Check for unescaped quotes inside dialogue text."""
        first_token = stripped.split()[0] if stripped.split() else ""
        if (
            not self.in_label_context
            or is_in_screen
            or first_token in NON_DIALOGUE_STATEMENTS
        ):
            return

        unescaped_quotes = re.findall(r'(?<!\\)"', stripped)
        is_odd_quotes = len(unescaped_quotes) % 2 != 0
        has_inner_quotes = bool(
            re.search(r'(?<!\\)"[^"\\]*(?<!\\)"\s+[^\s"\'#]+.*(?<!\\)"', stripped)
        )
        if is_odd_quotes or has_inner_quotes:
            self.analyzer._add_diagnostic(
                Diagnostic(
                    file_path=file_path,
                    line_number=idx + 1,
                    line_content=stripped,
                    code="RPY305",
                    message="Unescaped quotes inside dialogue text. Use '\\\"' instead of '\"' to avoid syntax errors.",
                ),
                noqa_map,
            )
