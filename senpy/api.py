"""senpy.api — explicitly public API module for plugin developers and library users.

SEMVER CONTRACT
---------------

This module is the STABLE public contract. The following public names
are covered by the semver guarantee — their presence, signature, and
observable behavior MUST stay backward-compatible within the same
major version:

    Public names (defined or re-exported here):
        - Diagnostic           — dataclass; its field names and types
                                 are part of the contract.
        - AnalysisResult       — dataclass; its field names and types
                                 are part of the contract.
        - Location             — dataclass (line: int, character: int).
        - RULE_SEVERITY        — dict[str, str] mapping rule code to
                                 severity ("ERROR" / "WARNING" / "INFO" / "HINT").
        - analyze_code(code, config=None) — high-level one-liner API. The
                                 optional ``config`` dict follows the
                                 ``senpy.toml [tool.senpy]`` schema
                                 (see function docstring for fields).

Allowed within a minor version bump (no major bump required):

    - Adding new optional parameters to public functions, as long as
      the default preserves existing call-site behavior.
    - Adding new public names to ``__all__``.
    - Performance improvements that do not change observable behavior.
    - Bug fixes that change behavior only when the previous behavior
      was demonstrably wrong (false positive, crash, wrong column, etc.).

Breaking changes (require major version bump, 1.x → 2.0):

    - Removing or renaming a public name.
    - Changing a public function's signature in a way that breaks
      existing call sites (mandatory parameter added, parameter
      reordered, return type changed).
    - Changing the type or documented semantics of a public dataclass
      field.
    - Changing the documented behavior of a public function in a way
      that is not a bug fix.

When a breaking change is unavoidable, the minor series BEFORE the
major bump MUST emit ``DeprecationWarning`` for at least one release,
and ``CHANGELOG.md`` MUST have a ``### Breaking Changes`` section in
the major version entry with a migration guide.

Internal modules (``senpy.core.*``, ``senpy.rules.*``, ``senpy.lsp.*``,
``senpy.cli.*``, ``senpy.formats.*``, ``senpy.domain.*``,
``senpy.plugins.*``) are NOT covered by this contract and may change
between any versions. External code that imports from these modules
does so at its own risk.

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

The ``from senpy.api import *`` works — ``__all__`` lists all public names.

Status (0.9.x):
    Senpy is in feature freeze until 1.0. The public names listed above
    are expected to remain frozen as-is through 1.0 — no breaking changes
    to them in any 0.9.x release. See README.md "Status" section.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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


def analyze_code(code: str, config: dict[str, Any] | None = None) -> list[Diagnostic]:
    """Analyze a snippet of .rpy code and return diagnostics.

    This is the canonical high-level API for external code (plugins, scripts,
    notebooks, CI integrations). It's a thin wrapper around SenpyAnalyzer
    that handles temp file setup, config loading, and cleanup.

    Args:
        code: .rpy source code as a string. May be empty.
        config: Optional configuration dict following the same schema
            as ``senpy.toml [tool.senpy]``. When passed, this dict is
            used directly (no filesystem lookup for ``senpy.toml``
            happens). When ``None`` (default), Senpy searches for
            ``senpy.toml`` / ``pyproject.toml`` in the temp project
            directory (which is empty by construction, so in practice
            defaults apply).

            Supported fields — see ``senpy.core.config.SenpyConfig`` for
            the canonical Pydantic schema (note: ``SenpyConfig`` itself
            is NOT part of the frozen public API yet; only the dict
            schema is, mirroring ``senpy.toml``):

              Analyzer-affecting (observable in the returned diagnostics):

                strict: bool                  — promote all diagnostics to ERROR
                severity: dict[str, str]       — per-rule severity overrides
                                               (e.g. {"RPY104": "ERROR"})
                additional_builtins: list[str] — third-party Ren'Py namespaces
                                               to treat as declared (e.g. ["iap"])
                additional_actions: list[str] — third-party screen Action classes
                                               (e.g. ["MyCustomAction"])
                enable_plugins: bool          — opt-in plugin rule execution

              CLI-layer only (ignored by ``analyze_code`` — these fields
              are applied by the CLI's ``filter_diagnostics`` step AFTER
              ``analyzer.run()``, so passing them via ``config`` here has
              no effect on the returned list):

                ignore: list[str]              — rule codes to suppress globally
                select: list[str]              — rule codes whitelist
                extend_select: list[str]       — additional whitelist codes
                extend_ignore: list[str]       — additional suppressed codes
                max_errors: int               — per-file diagnostic cap
                info: bool                    — show INFO-severity diagnostics
                errors_only: bool             — show only ERROR-severity
                tsundere: bool                — alternate output tone

            To filter diagnostics programmatically, filter the returned
            list in caller code (``[d for d in diags if d.code not in
            ignore_set]``). A future minor release may promote ``ignore``
            to analyzer-level; that would be a behavior change for
            callers that already filter post-hoc, so it's deferred.

            Unknown fields are ignored (forward-compat). Invalid types
            (e.g. ``strict = "yes"``) surface as a logged WARNING and
            fall back to defaults.

    Returns:
        List of Diagnostic objects. Empty list if no issues found.
        Never returns None.

    Example:
        >>> from senpy.api import analyze_code
        >>> diags = analyze_code('label start:\\n    "Hello, [unknown]!"\\n    return\\n')
        >>> [d.code for d in diags]
        ['RPY101']

        >>> # Programmatic severity override without writing senpy.toml:
        >>> diags = analyze_code(code, config={"severity": {"RPY104": "ERROR"}})

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

        analyzer = SenpyAnalyzer(tmp_dir, no_cache=True, config=config)
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
