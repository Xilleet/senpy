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
        from senpy.text_utils import _strip_comment  # Фаза 1.3: вынесено в text_utils
        stripped = clean_line.strip()
        line_indent = len(raw_line) - len(raw_line.lstrip(" "))
        is_in_screen = scope_stack.current_screen_name() is not None

        if line_indent == 0 and stripped.startswith(("screen ", "style ", "init ", "transform ")):
            self.in_label_context = False

        # RPY308: Проверка на падение сюжета (fallthrough) перед меткой
        m_label = RE_LABEL.match(clean_line)
        if m_label:
            raw_lbl = m_label.group(1)
            if not raw_lbl.startswith("."):
                self.current_global_label = raw_lbl
            if self.in_label_context and idx > 0:
                prev_idx = idx - 1
                while prev_idx >= 0 and not lines[prev_idx].strip():
                    prev_idx -= 1
                if prev_idx >= 0:
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
            self.in_label_context = True

        # RPY302 & RPY306: Переходы jump и call (проверяем по self.analyzer.labels)
        m_jump = RE_JUMP_CALL.match(stripped) if stripped.startswith(("jump ", "call ")) else None
        if m_jump:
            cmd_type, raw_target = m_jump.group(1), m_jump.group(2)
            if raw_target == "expression":
                self.analyzer.has_dynamic_jumps = True
            else:
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
                    # 1. RPY310: Проверка сигнатуры аргументов вызова метки
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

                    # 2. RPY306: Проверка наличия пути к return
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

        # RPY302: Переходы через UI Actions и Python (Jump, Call, renpy.jump, renpy.call)
        if any(kw in stripped for kw in ("Jump", "Call", "renpy.jump", "renpy.call")):
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

        # RPY305: Неэкранированные кавычки в диалоге
        first_token = stripped.split()[0] if stripped.split() else ""
        if (
            self.in_label_context
            and not is_in_screen
            and first_token not in NON_DIALOGUE_STATEMENTS
        ):
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

        return raw_line, False
