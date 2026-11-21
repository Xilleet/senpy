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
    """A single lint finding emitted by a rule.

    Carries both the location of the finding (file, line, columns) and an
    optional quick-fix payload used by ``--fix`` and LSP ``textDocument/codeAction``.
    ``severity`` is normally populated by ``_apply_severity`` after the rule
    emits the diagnostic (rule itself may leave it None).

    Field groups:
      - Identification: ``code`` (e.g. "RPY104"), ``message``, ``severity``.
      - Location: ``file_path``, ``line_number`` (1-based), ``line_content``
        (raw source line — used by renderers and LSP snippet), ``col`` / ``end_col``
        (0-based byte offsets into ``line_content``; 0/0 = whole-line / unset).
      - Quick-fix: ``fix_title`` (label for the Code Action), ``fix_replacement``
        (new text), ``fix_start_col`` / ``fix_end_col`` (0-based byte offsets into
        ``line_content`` to replace with ``fix_replacement``). All four are
        optional — a diagnostic may be unfixable.
    """

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
    failed_writes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FileScope:
    """Per-file state collected during Stage 1 (``_collect_symbols``).

    Two parallel models coexist:
      - ``user_symbols`` / ``declared_symbols``: flat sets of identifier names
        seen as "declared" in this file. ``user_symbols`` = names declared via
        user code (``default`` / ``define`` / ``label`` / ``screen`` / ``transform`` /
        ``image`` / loop targets / ``$`` assignments / params). ``declared_symbols``
        = ``user_symbols`` PLUS Ren'Py built-in namespaces (``renpy``, ``config``,
        ``persistent``, …) PLUS user-extended ``additional_builtins``. Rules that
        decide "is this name declared?" read ``declared_symbols``; rules that
        decide "is this name a USER symbol?" (e.g. for merge_flow_branches)
        read ``user_symbols``. Mixing the two caused divergent filters in
        RPY401 vs RPY404 — a known historical bug class.
      - The typed registries (``variables`` / ``labels`` / ``screens`` / ``images`` /
        ``transforms``): full ``*Symbol`` objects, keyed by name. ``jump_sources`` /
        ``screen_action_jumps`` / ``used_screens`` / ``screen_uses`` are derived
        cross-reference indexes.
    """

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

    # Per-file flag: True if this file contains any dynamic-jump construct
    # (`renpy.jump(...)`, `renpy.call(...)`, `jump expression`, `call
    # expression`). Aggregated into `SymbolTable.has_dynamic_jumps` during
    # `_collect_all_symbols` (cold) and `rebuild_from_scopes` (warm). On
    # Tier 1 cache hit, the FileScope is restored from disk, and this
    # flag is what allows `has_dynamic_jumps` to be re-aggregated without
    # re-running `_collect_misc`. Without it, warm runs would lose the
    # flag and RPY701-707 would re-fire on suppressed code.
    has_dynamic_jumps: bool = False


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
