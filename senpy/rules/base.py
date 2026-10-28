"""base — extracted from checkers.py (Фаза 2, 0.5.4)."""

from __future__ import annotations

from senpy.core.scope import ScopeStack
from senpy.core.sink import DiagnosticSink
from senpy.rules.flow import FlowBranch


class IfBlockContext:
    """Контекст активного блока if/elif/else в анализе потока управления."""

    def __init__(self, indent: int, line: int):
        self.indent = indent
        self.line = line
        self.branches: list[FlowBranch] = []
        self.current_branch: FlowBranch | None = None
class BaseChecker:
    def __init__(self, analyzer: DiagnosticSink):
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
        """Возвращает (обновленная_строка, был_ли_модифицирован_файл)."""
        return raw_line, False
