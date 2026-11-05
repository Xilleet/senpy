from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from senpy.rules.rules_info import RULES_DATABASE

if TYPE_CHECKING:
    from senpy.core.symbols import (
        ImageSymbol,
        LabelSymbol,
        ScreenSymbol,
        TransformSymbol,
        VariableSymbol,
    )


@dataclass(slots=True)
class Diagnostic:
    file_path: str
    line_number: int
    line_content: str
    code: str
    message: str
    severity: str | None = None
    col: int = 0
    end_col: int = 0
    fix_title: str | None = None
    fix_replacement: str | None = None
    fix_start_col: int | None = None
    fix_end_col: int | None = None


@dataclass(slots=True)
class AnalysisResult:
    diagnostics: list[Diagnostic]
    file_count: int
    total_lines: int
    fixed_count: int = 0
    fixable_count: int = 0


@dataclass(slots=True)
class FileScope:
    user_symbols: set[str] = field(default_factory=set)
    declared_symbols: set[str] = field(default_factory=set)
    defined_audio_map: dict[str, str] = field(default_factory=dict)
    registered_audio_channels: set[str] = field(default_factory=set)
    referenced_labels: set[str] = field(default_factory=set)

    # --- New clean object model ---
    variables: dict[str, VariableSymbol] = field(default_factory=dict)
    labels: dict[str, LabelSymbol] = field(default_factory=dict)
    screens: dict[str, ScreenSymbol] = field(default_factory=dict)
    images: dict[str, ImageSymbol] = field(default_factory=dict)
    transforms: dict[str, TransformSymbol] = field(default_factory=dict)

    jump_sources: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    screen_action_jumps: dict[str, set[str]] = field(default_factory=dict)
    used_screens: set[str] = field(default_factory=set)
    screen_uses: dict[str, set[str]] = field(default_factory=dict)


# RULE_SEVERITY is derived from RULES_DATABASE.
# Each rule's severity is declared once in senpy/rules/rules_info.py and
# re-exported here as a flat code→severity dict for callers that need
# O(1) lookup (e.g. AnalysisPipeline._apply_severity, sarif/gitlab/rdjson
# formatters, the `senpy.api` public surface).
#
# Previously this was a hand-maintained dict that drifted from
# RULES_DATABASE — four rules (RPY107, RPY303, RPY503, RPY504) silently
# disagreed between the two sources. Deriving it from RULES_DATABASE
# eliminates the drift permanently: a future contributor editing
# RULES_DATABASE updates both surfaces at once.
RULE_SEVERITY: dict[str, str] = {code: entry["severity"] for code, entry in RULES_DATABASE.items()}
