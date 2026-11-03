"""base — extracted from checkers.py (Phase 2, 0.5.4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from senpy.core.scope import ScopeStack
from senpy.rules.flow import FlowBranch

if TYPE_CHECKING:
    from senpy.core.analyzer import SenpyAnalyzer


class IfBlockContext:
    """Context of an active if/elif/else block in control flow analysis."""

    def __init__(self, indent: int, line: int):
        self.indent = indent
        self.line = line
        self.branches: list[FlowBranch] = []
        self.current_branch: FlowBranch | None = None


class BaseChecker:
    def __init__(self, analyzer: SenpyAnalyzer):
        self.analyzer = analyzer

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
        """Returns (updated_line, whether_file_was_modified)."""
        return raw_line, False
