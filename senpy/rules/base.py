"""base — extracted from checkers.py (Phase 2, 0.5.4).

ISP Protocol split: BaseChecker type-hints analyzer via TYPE_CHECKING
Protocols. At runtime, SenpyAnalyzer is passed directly — it implements
all Protocols. The type hints document which Protocols each checker
actually needs, enabling future mock testing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from senpy.core.scope import ScopeStack
from senpy.rules.flow import FlowBranch

if TYPE_CHECKING:
    pass


class IfBlockContext:
    """Context of an active if/elif/else block in control flow analysis."""

    def __init__(self, indent: int, line: int):
        self.indent = indent
        self.line = line
        self.branches: list[FlowBranch] = []
        self.current_branch: FlowBranch | None = None


class BaseChecker:
    """Base class for line-by-line checkers.

    The analyzer parameter is typed as DiagnosticSink & SymbolProvider
    (intersection) under TYPE_CHECKING. At runtime, SenpyAnalyzer is
    passed — it implements both Protocols. Subclasses that need
    AssetProvider or FlowProvider declare that in their own type hints.
    """

    def __init__(self, analyzer: Any):
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
