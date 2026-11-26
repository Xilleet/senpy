"""base — extracted from checkers.py (Phase 2, 0.5.4).

ISP Protocol split: BaseChecker type-hints analyzer via the
DiagnosticSinkAndSymbols Protocol (intersection of DiagnosticSink and
SymbolProvider). At runtime, SenpyAnalyzer is passed directly — it
implements the Protocol. Subclasses that need AssetProvider or
FlowProvider declare that in their own type hints.

See ``senpy/core/protocols.py`` for the Protocol definitions and
``tests/test_protocols_runtime.py`` for the runtime ``isinstance``
contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from senpy.core.scope import ScopeStack
from senpy.rules.flow import FlowBranch

if TYPE_CHECKING:
    from senpy.core.protocols import DiagnosticSinkAndSymbols


class IfBlockContext:
    """Context of an active if/elif/else block in control flow analysis.

    ``current_branch`` is non-Optional: an IfBlockContext is always created
    with an initial ``if`` branch (the elif/else cases mutate ``current_branch``
    on an already-existing context, never create a context without one).
    This removes the need for ``# type: ignore[union-attr]`` markers at
    8 ``current_branch`` access sites in ``state.py``.
    """

    def __init__(self, indent: int, line: int, initial_branch: FlowBranch):
        self.indent = indent
        self.line = line
        self.branches: list[FlowBranch] = [initial_branch]
        self.current_branch: FlowBranch = initial_branch


class BaseChecker:
    """Base class for line-by-line checkers.

    The analyzer parameter is typed as DiagnosticSinkAndSymbols — the
    intersection of DiagnosticSink (for ``_add_diagnostic`` /
    ``_get_utf16_range`` / ``fix`` / ``fixable_count`` / ``fixed_count``)
    and SymbolProvider (for ``variables`` / ``labels`` / ``screens`` /
    ``transforms`` / ``images`` / ``user_symbols`` / ``declared_symbols``
    / ``referenced_labels`` / ``has_dynamic_jumps`` /
    ``missing_defaults``). At runtime, SenpyAnalyzer is passed — it
    implements both halves.

    Subclasses that need additional Protocols (AssetProvider for
    AssetChecker, FlowProvider for StateChecker) declare that via their
    own ``__init__`` signature.
    """

    def __init__(self, analyzer: DiagnosticSinkAndSymbols):
        self.analyzer = analyzer

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
        """Returns (next_idx, whether_file_was_modified).

        Signature unified with StateChecker.check_line. The
        ``next_idx`` parameter was added to match StateChecker (which
        needs it for multi-line statement handling). BaseChecker ignores
        it and returns the passed-in next_idx unchanged. The return type
        is ``tuple[int, bool]`` (was ``tuple[str, bool]`` — the first
        element was never used by callers, they used next_idx from
        StateChecker).
        """
        return next_idx, False
