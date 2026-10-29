"""Rule base class + RuleMeta + RuleContext.

This is the foundation for plugin-based lint rules. Plugin developers
subclass Rule and implement check() to return Diagnostics.

Architecture (ESLint-inspired):
    - RuleMeta: declarative metadata about a rule (code, docs, severity, etc.)
    - RuleContext: data passed to Rule.check() (file_path, lines, symbols)
    - Rule: base class with check() method to override

This is SEPARATE from the existing senpy.rules.checkers.BaseChecker:
    - BaseChecker: per-line checker, used internally by SenpyAnalyzer
    - Rule: per-file/per-project checker, used by plugin developers

The two systems coexist. Existing built-in rules continue to use BaseChecker.
New plugin rules use Rule. Eventually (0.7.0+) built-in rules may migrate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from senpy.api import Diagnostic


# =============================================================================
# Constants
# =============================================================================

# Valid severity levels (matches RULE_SEVERITY in core/models.py)
_VALID_SEVERITIES = ("ERROR", "WARNING", "HINT", "INFO")

# Rule code pattern: RPY + 3 digits (matches existing rules RPY001..RPY703)
_RE_RULE_CODE = re.compile(r"^RPY\d{3}$")


# =============================================================================
# RuleMeta dataclass
# =============================================================================


@dataclass
class RuleMeta:
    """Metadata for a lint rule (ESLint-style).

    Required fields:
        code: Rule code, must match RPY\\d{3} pattern (e.g. "RPY901")
        docs: Human-readable description of what the rule detects
        severity: One of ERROR, WARNING, HINT, INFO

    Optional fields:
        fixable: True if rule provides fix_replacement in Diagnostics
        schema: JSON schema for rule configuration options (None = no options)
        tags: List of tags for filtering (e.g. ["performance", "rollback-safety"])
        deprecated: True if rule is deprecated and will be removed
        replaced_by: Code of replacement rule (e.g. "RPY100" supersedes "RPY099")

    Example:
        meta = RuleMeta(
            code="RPY901",
            docs="Detect hard-coded dialogue strings without _() for translation",
            severity="WARNING",
            fixable=False,
            tags=["translations", "accessibility"],
        )
    """

    code: str
    docs: str
    severity: str

    # Optional fields with defaults
    fixable: bool = False
    schema: dict[str, Any] | None = None
    tags: list[str] = field(default_factory=list)
    deprecated: bool = False
    replaced_by: str | None = None

    def __post_init__(self):
        """Validate fields after dataclass init."""
        # Validate code format
        if not _RE_RULE_CODE.match(self.code):
            raise ValueError(
                f"RuleMeta.code must match RPY\\d{{3}} pattern (e.g. 'RPY901'), "
                f"got: {self.code!r}"
            )
        # Validate severity
        if self.severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"RuleMeta.severity must be one of {_VALID_SEVERITIES}, "
                f"got: {self.severity!r}"
            )
        # Validate replaced_by format if set
        if self.replaced_by is not None and not _RE_RULE_CODE.match(self.replaced_by):
            raise ValueError(
                f"RuleMeta.replaced_by must match RPY\\d{{3}} pattern, "
                f"got: {self.replaced_by!r}"
            )


# =============================================================================
# RuleContext dataclass
# =============================================================================


@dataclass
class RuleContext:
    """Context passed to Rule.check() method.

    Provides everything a plugin rule needs to analyze a file:
        file_path: Path to .rpy file being analyzed
        lines: List of raw lines (with newlines) from the file
        symbols: Dict of all symbols in the project (labels, screens, etc.)
                 Structure: {"labels": {name: {...}}, "screens": {...}, ...}

    Future extensions (not breaking — added as optional fields):
        analyzer: Reference to SenpyAnalyzer for advanced queries
        config: Rule-specific configuration from senpy.toml
    """

    file_path: str
    lines: list[str]
    symbols: dict[str, Any]

    # Optional fields (may be None for simple contexts)
    analyzer: Any = None  # SenpyAnalyzer instance, if available
    config: dict[str, Any] | None = None  # rule-specific config


# =============================================================================
# Rule base class
# =============================================================================


class Rule:
    """Base class for lint rules. Subclass and implement check().

    See module docstring for usage example.

    Contract:
        1. Set `meta = RuleMeta(...)` as class attribute
        2. Override `def check(self, ctx: RuleContext) -> list[Diagnostic]`
        3. Return list of Diagnostic objects (empty if no issues)

    The base check() raises NotImplementedError to enforce override.
    """

    meta: RuleMeta | None = None

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        """Analyze ctx and return list of Diagnostics.

        Override this method in subclass. Base implementation raises
        NotImplementedError to enforce override.

        Args:
            ctx: RuleContext with file_path, lines, symbols

        Returns:
            List of Diagnostic objects. Empty list if no issues found.
            Never returns None.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__}.check() must be overridden. "
            f"Subclass Rule and implement check(self, ctx) -> list[Diagnostic]."
        )

    def __repr__(self) -> str:
        code = self.meta.code if self.meta else "<no meta>"
        return f"<{self.__class__.__name__} code={code!r}>"
