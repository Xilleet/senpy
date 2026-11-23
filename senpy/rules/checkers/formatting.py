"""formatting — extracted from checkers.py (Phase 2, 0.5.4)."""

from __future__ import annotations

from senpy.core.constants import (
    SMART_QUOTES,
)
from senpy.core.models import Diagnostic
from senpy.core.scope import ScopeStack
from senpy.rules.base import BaseChecker
from senpy.text_utils import strip_string_literals


class FormattingChecker(BaseChecker):
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
        file_modified = False
        new_raw_line = raw_line
        stripped = clean_line.strip()

        # RPY107: Check for deprecated Ren'Py API
        for d in self.analyzer.deprecated.check_line(new_raw_line, idx + 1, file_path):
            self.analyzer._add_diagnostic(d, noqa_map)

        # RPY001: Check for tabs in indentation
        leading_ws = new_raw_line[: len(new_raw_line) - len(new_raw_line.lstrip())]
        if "\t" in leading_ws:
            self.analyzer.fixable_count += 1
            if self.analyzer.fix:
                fixed_leading = leading_ws.replace("\t", "    ")
                new_raw_line = fixed_leading + new_raw_line[len(leading_ws) :]
                lines[idx] = new_raw_line
                file_modified = True
                self.analyzer.fixed_count += 1
            else:
                start_c, end_c = 0, len(leading_ws.encode("utf-16-le")) // 2
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=idx + 1,
                        line_content=new_raw_line.rstrip(),
                        code="RPY001",
                        message="Tab character ('\\t') used in indentation. Ren'Py requires 4 spaces per indent level.",
                        col=start_c,
                        end_col=end_c,
                        fix_title="Replace tabs with 4 spaces",
                        fix_replacement=leading_ws.replace("\t", "    "),
                        fix_start_col=start_c,
                        fix_end_col=end_c,
                    ),
                    noqa_map,
                )

        # RPY002: Curly/typographic quotes in code
        #
        # String-literal masking: the detection and the
        # fix must only consider smart quotes that live OUTSIDE string
        # literals. A line like ``$ greeting = "He said «hello»"`` is
        # valid Python — the smart quotes are string content, not a
        # quoting bug. Without masking, RPY002 fired on this line and
        # ``--fix`` replaced ``«``/``»`` with ``"`` producing
        # ``$ greeting = "He said "hello""`` — a Python SyntaxError.
        #
        # ``masked`` is the line with string-literal contents replaced
        # by spaces (column positions preserved). Smart quotes inside a
        # literal are spaces in ``masked`` and so invisible to the
        # detection check. The fix replacement is built character-by-
        # character: when a smart quote is at position ``i`` and
        # ``masked[i]`` is the same character (i.e. the quote is
        # outside a string literal), it is replaced; otherwise the
        # original character is kept.
        masked = strip_string_literals(clean_line)
        if any(q in masked for q in SMART_QUOTES) and (
            stripped.startswith(("$", "if ", "elif ", "default ", "define "))
            or (
                scope_stack.current_screen_name() is not None
                and not stripped.startswith(("text ", "textbutton "))
            )
        ):
            self.analyzer.fixable_count += 1
            if self.analyzer.fix:
                # Build the fixed line character-by-character: replace
                # smart quotes only where ``masked`` confirms they are
                # outside a string literal. Smart quotes inside a
                # literal are spaces in ``masked`` and so survive intact.
                masked_raw = strip_string_literals(new_raw_line)
                fixed_chars = []
                for i, c in enumerate(new_raw_line):
                    if c in SMART_QUOTES and i < len(masked_raw) and masked_raw[i] == c:
                        fixed_chars.append(SMART_QUOTES[c])
                    else:
                        fixed_chars.append(c)
                fixed_l = "".join(fixed_chars)
                lines[idx] = fixed_l
                new_raw_line = fixed_l
                file_modified = True
                self.analyzer.fixed_count += 1
            else:
                # Replacement is the entire fixed line (smart quotes
                # outside string literals replaced), WITHOUT the trailing
                # newline — LSP editors manage line endings separately,
                # and including `\n` here would create a spurious empty
                # line after the fix.
                # Range must cover the entire line too — otherwise the LSP
                # handler falls back to lsp_diag.range (typically
                # `[indent, end_of_line)`) and the indent ends up duplicated:
                # the editor preserves the leading indent that lives outside
                # the range, then prepends the indent included in the
                # replacement.
                line_no_newline = new_raw_line.rstrip("\r\n")
                masked_no_newline = strip_string_literals(line_no_newline)
                replacement_line = "".join(
                    SMART_QUOTES.get(c, c)
                    if (
                        c in SMART_QUOTES
                        and i < len(masked_no_newline)
                        and masked_no_newline[i] == c
                    )
                    else c
                    for i, c in enumerate(line_no_newline)
                )
                line_utf16_len = len(line_no_newline.encode("utf-16-le")) // 2
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=idx + 1,
                        line_content=stripped,
                        code="RPY002",
                        message="Smart/curly quotes (“ ” ‘ ’ « ») detected in code statement. Will cause Python SyntaxError.",
                        fix_title="Replace smart quotes with standard quotes",
                        fix_replacement=replacement_line,
                        fix_start_col=0,
                        fix_end_col=line_utf16_len,
                    ),
                    noqa_map,
                )

        return next_idx, file_modified
