"""senpy.api — explicitly public API module for plugin developers and library users.

This module is the STABLE public contract. Internal modules (senpy.core.*,
senpy.rules.*, senpy.lsp.*, etc.) may change between minor versions, but
senpy.api MUST stay backward-compatible within the same major version.

What's here:
    - Diagnostic, RULE_SEVERITY, AnalysisResult — re-exported from core.models
    - Location — simple dataclass for line:col positions
    - analyze_code(code: str) -> list[Diagnostic] — high-level one-liner API

Why this module exists (0.6.0):
    Before 0.6.0, plugin developers had to import from senpy.core.models,
    senpy.core.analyzer, etc. — these are internal modules subject to
    refactoring. With senpy.api, plugin developers have ONE stable import:

        from senpy.api import Diagnostic, analyze_code, RULE_SEVERITY

    If we restructure senpy.core.* (we did this in 0.5.5), senpy.api re-exports
    are updated, and plugin code keeps working.

Migration guide:
    OLD (still works, but deprecated):
        from senpy import SenpyAnalyzer, Diagnostic, RULE_SEVERITY

    NEW (recommended for new code):
        from senpy.api import Diagnostic, RULE_SEVERITY, analyze_code

The `from senpy.api import *` works — __all__ lists all public names.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

# Re-exports — these are the stable public API. They MUST NOT change between
# minor versions. Major version bumps are allowed to break them (with a
# migration guide in CHANGELOG.md).
from senpy.core.models import (
    RULE_SEVERITY,
    AnalysisResult,
    Diagnostic,
)

if TYPE_CHECKING:
    pass  # for future type-only imports


# =============================================================================
# Public dataclasses
# =============================================================================


@dataclass
class Location:
    """A line:character position in a source file.

    Used by plugins to report diagnostics at specific positions.

    Attributes:
        line: 1-based line number (matches Ren'Py convention and IDE display)
        character: 0-based character offset within the line (LSP convention)
    """

    line: int
    character: int


# =============================================================================
# High-level API functions
# =============================================================================


def analyze_code(code: str) -> list[Diagnostic]:
    """Analyze a snippet of .rpy code and return diagnostics.

    This is the canonical high-level API for external code (plugins, scripts,
    notebooks, CI integrations). It's a thin wrapper around SenpyAnalyzer
    that handles temp file setup, config loading, and cleanup.

    Args:
        code: .rpy source code as a string. May be empty.

    Returns:
        List of Diagnostic objects. Empty list if no issues found.
        Never returns None.

    Example:
        >>> from senpy.api import analyze_code
        >>> diags = analyze_code('label start:\\n    "Hello, [unknown]!"\\n    return\\n')
        >>> [d.code for d in diags]
        ['RPY101']

    Note:
        For analyzing files on disk, use SenpyAnalyzer directly:
            from senpy import SenpyAnalyzer
            analyzer = SenpyAnalyzer("/path/to/game")
            result = analyzer.run()
    """
    # Empty or whitespace-only input: no diagnostics
    if not code or not code.strip():
        return []

    import os
    import tempfile

    from senpy.core.analyzer import SenpyAnalyzer

    # Create a temp directory that looks like a Ren'Py project structure:
    # tmp_dir/game/script.rpy — so SenpyAnalyzer picks it up via _get_rpy_files
    with tempfile.TemporaryDirectory(prefix="senpy_api_") as tmp_dir:
        game_dir = os.path.join(tmp_dir, "game")
        os.makedirs(game_dir, exist_ok=True)
        script_path = os.path.join(game_dir, "script.rpy")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        analyzer = SenpyAnalyzer(tmp_dir, no_cache=True)
        result = analyzer.run(quiet=True)

    return list(result.diagnostics)


# =============================================================================
# __all__ — explicit public API
# =============================================================================

__all__ = [
    # Dataclasses
    "Diagnostic",
    "AnalysisResult",
    "Location",
    # Constants
    "RULE_SEVERITY",
    # Functions
    "analyze_code",
]
