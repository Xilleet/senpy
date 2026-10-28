"""formatting — extracted from checkers.py (Фаза 2, 0.5.4)."""

from __future__ import annotations

from senpy.core.constants import (
    SMART_QUOTES,
)
from senpy.core.models import Diagnostic
from senpy.core.scope import ScopeStack
from senpy.rules.base import BaseChecker


class FormattingChecker(BaseChecker):
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
        file_modified = False
        new_raw_line = raw_line
        stripped = clean_line.strip()

        # RPY107: Проверка устаревшего API Ren'Py
        for d in self.analyzer.deprecated.check_line(new_raw_line, idx + 1, file_path):
            self.analyzer._add_diagnostic(d, noqa_map)

        # RPY001: Проверка табуляции в отступах
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

        # RPY002: Фигурные/типографские кавычки в коде
        if any(q in clean_line for q in SMART_QUOTES) and (
            stripped.startswith(("$", "if ", "elif ", "default ", "define "))
            or (
                scope_stack.current_screen_name() is not None
                and not stripped.startswith(("text ", "textbutton "))
            )
        ):
            self.analyzer.fixable_count += 1
            if self.analyzer.fix:
                fixed_l = new_raw_line
                for sq, aq in SMART_QUOTES.items():
                    fixed_l = fixed_l.replace(sq, aq)
                lines[idx] = fixed_l
                new_raw_line = fixed_l
                file_modified = True
                self.analyzer.fixed_count += 1
            else:
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=idx + 1,
                        line_content=stripped,
                        code="RPY002",
                        message="Smart/curly quotes (“ ” ‘ ’ « ») detected in code statement. Will cause Python SyntaxError.",
                        fix_title="Replace smart quotes with standard quotes",
                        fix_replacement="".join(SMART_QUOTES.get(c, c) for c in new_raw_line),
                    ),
                    noqa_map,
                )

        return new_raw_line, file_modified
