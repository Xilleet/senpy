"""DiagnosticSink — Protocol for objects capable of accepting diagnostics.

Extracted into a separate module in Phase 1.3 (0.5.3) to break the circular
dependency analyzer ↔ checkers.

Previously BaseChecker.__init__ took analyzer: SenpyAnalyzer — this
forced checkers.py to import senpy.analyzer, which created a cycle:
    analyzer.py → checkers.py → analyzer.py

Now BaseChecker.__init__ takes analyzer: DiagnosticSink (Protocol).
SenpyAnalyzer implements this Protocol, but the checkers depend only on the
Protocol, not on the concrete class. This breaks the import cycle.

In Phase 1.3 DiagnosticSink contains only the methods related to diagnostics:
    - _add_diagnostic(diag, noqa_map)
    - _get_utf16_range(raw_line, name)
    - fixable_count, fixed_count, fix (attributes)

Access to symbols (screens, labels, variables, ...) still goes through
self.analyzer for now — this will be broken out in 0.5.5 (when _collect_symbols
is split into a separate SymbolRegistry).

Public API:
    DiagnosticSink  — Protocol (typing only, not instantiated)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from senpy.core.models import Diagnostic


@runtime_checkable
class DiagnosticSink(Protocol):
    """Protocol for objects capable of accepting diagnostics and applying QuickFix.

    SenpyAnalyzer implements this Protocol. The checkers (BaseChecker and its
    subclasses) depend only on the Protocol, not on the concrete SenpyAnalyzer class.

    This allows:
    1. Breaking the circular import analyzer ↔ checkers.
    2. Testing the checkers with mock objects (in the future).
    3. Creating alternative DiagnosticSink implementations (for example, for
      batch processing without a full SenpyAnalyzer).

    Minimal contract (Phase 1.3):
        - _add_diagnostic(diag, noqa_map) — add a diagnostic
        - _get_utf16_range(raw_line, name) — compute the UTF-16 range for QuickFix
        - fixable_count: int — counter of fixable errors
        - fixed_count: int — counter of fixed errors
        - fix: bool — flag of the autofix mode

    In 0.5.5 (when _collect_symbols is split) a SymbolProvider Protocol will be
    added for access to symbols (screens, labels, ...).
    """

    # Attributes (instance variables)
    fixable_count: int
    fixed_count: int
    fix: bool

    def _add_diagnostic(self, diag: Diagnostic, noqa_map: dict[int, set[str] | None]) -> None:
        """Add a diagnostic to the list of found errors.

        Args:
            diag: Diagnostic object with information about the error.
            noqa_map: Map line number → set of suppressed rules (for # noqa).
        """
        ...

    def _get_utf16_range(self, raw_line: str, name: str) -> tuple[int, int]:
        """Returns the (start, end) UTF-16 position of the name in the line.

        Used to compute QuickFix ranges in LSP/CLI.

        Args:
            raw_line: Original line from the file.
            name: Name (variable/label/screen/...) to find the position of.

        Returns:
            Tuple (start_char, end_char) — positions in UTF-16 code units.
        """
        ...
