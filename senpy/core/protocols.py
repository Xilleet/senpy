"""ISP Protocols — Interface Segregation Principle split of DiagnosticSink.

Replaces the single DiagnosticSink Protocol (which was too narrow — only
diagnostics methods) with several focused Protocols. Each checker declares
which Protocols it needs, enabling:

  1. Clear dependency contracts (no analyzer._* leaking)
  2. Testability (mock only what the checker needs)
  3. Future: alternative implementations (e.g. SymbolTable standalone)

Protocols:
  - DiagnosticSink — diagnostics: _add_diagnostic, _get_utf16_range, fix, fixable_count, fixed_count, diagnostics
                   plus shared mutable analyzer state: total_lines, in_memory_files,
                   file_scopes, _stage1_lines, _noqa_maps, deprecated, _additional_actions,
                   _emit_encoding_error
  - SymbolProvider — symbol access: variables, labels, screens, transforms, images, user_symbols, declared_symbols, referenced_labels, has_dynamic_jumps, missing_defaults
                   plus flow-graph registries: jump_sources, screen_action_jumps, used_screens,
                   screen_uses, defined_audio_map, registered_audio_channels
  - AssetProvider — asset access: _mark_asset_used, _get_tag_known_attributes, known_assets, valid_images, audio_dir_files
  - FlowProvider — flow/checker delegation: _analyze_menu_flow, _can_reach_return, _check_cfg_condition, _check_cfg_interpolations, _check_condition, _check_python_ast, _check_screen_mutation, _clear_safe_cfg_vars, _consume_block, _scan_python_assets
  - NoqaMapProvider — per-file noqa directive lookup for cross-file rules
  - ProjectInfo — project metadata: project_path

SenpyAnalyzer implements ALL Protocols (it's the concrete class).
Each checker __init__ takes only the Protocols it needs.

Type-narrowing notes
--------------------
SenpyAnalyzer exposes its symbol registries as ``@property`` (read-only)
delegating to an internal ``SymbolTable`` instance. To satisfy the
Protocols below, every read-only registry is declared here as a
``@property`` rather than a settable class-level annotation — otherwise
mypy treats the Protocol member as "settable variable" and complains
that the analyzer's read-only property is "got read-only attribute".

Three analyzer properties (``declared_symbols``, ``has_dynamic_jumps``,
``registered_audio_channels``) have both getter and setter — those are
declared here with ``@property`` + ``@xxx.setter`` so callers that
assign (e.g. ``self.analyzer.has_dynamic_jumps = True``) type-check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from senpy.core.models import Diagnostic, FileScope
    from senpy.core.symbols import (
        ImageSymbol,
        LabelSymbol,
        ScreenSymbol,
        TransformSymbol,
        VariableSymbol,
    )
    from senpy.rules.deprecated import DeprecationChecker


@runtime_checkable
class DiagnosticSink(Protocol):
    """Accepts diagnostics and manages severity/fix counters.

    Also exposes the small set of shared mutable analyzer state that line
    checkers read or write while emitting diagnostics: ``total_lines``
    (incremented per file), ``in_memory_files`` (read by translation
    checker), ``file_scopes`` / ``_stage1_lines`` (read by cross-file
    dead-code rules), ``_noqa_maps`` (written by translation checker,
    read by NoqaMapProvider), ``deprecated`` (Ren'Py deprecation scanner
    used by FormattingChecker), and ``_additional_actions`` (user-extended
    screen actions from ``senpy.toml`` used by ScreenChecker).
    """

    diagnostics: list[Diagnostic]
    fix: bool
    fixable_count: int
    fixed_count: int
    total_lines: int
    in_memory_files: dict[str, str]
    file_scopes: dict[str, FileScope]
    _stage1_lines: dict[str, list[str]]
    _noqa_maps: dict[str, dict[int, set[str] | None]]
    _additional_actions: set[str]
    deprecated: DeprecationChecker

    def _add_diagnostic(self, diag: Diagnostic, noqa_map: dict[int, set[str] | None]) -> None: ...

    def _get_utf16_range(self, line: str, sub: str | None = None) -> tuple[int, int]: ...

    def _emit_encoding_error(self, file_path: str, err: UnicodeDecodeError) -> None: ...


@runtime_checkable
class SymbolProvider(Protocol):
    """Read-only access to symbol registries.

    Includes the flow-graph registries (``jump_sources``,
    ``screen_action_jumps``, ``used_screens``, ``screen_uses``) and the
    audio registries (``defined_audio_map``, ``registered_audio_channels``)
    because several cross-file rules (``dead_code.py``, ``translation.py``)
    and the flow analyzer read them through this Protocol via the
    ``DiagnosticSinkAndSymbols`` / ``DiagnosticSinkAndSymbolsAndNoqa``
    intersections.
    """

    # --- Read-only registries (analyzer exposes them as @property) ---
    @property
    def variables(self) -> dict[str, VariableSymbol]: ...

    @property
    def labels(self) -> dict[str, LabelSymbol]: ...

    @property
    def screens(self) -> dict[str, ScreenSymbol]: ...

    @property
    def transforms(self) -> dict[str, TransformSymbol]: ...

    @property
    def images(self) -> dict[str, ImageSymbol]: ...

    @property
    def user_symbols(self) -> set[str]: ...

    @property
    def referenced_labels(self) -> set[str]: ...

    @property
    def missing_defaults(self) -> dict[str, str]: ...

    @property
    def jump_sources(self) -> dict[str, list[tuple[str, int]]]: ...

    @property
    def screen_action_jumps(self) -> dict[str, set[str]]: ...

    @property
    def used_screens(self) -> set[str]: ...

    @property
    def screen_uses(self) -> dict[str, set[str]]: ...

    @property
    def defined_audio_map(self) -> dict[str, str]: ...

    # --- Read-write registries (analyzer has both getter and setter) ---
    @property
    def declared_symbols(self) -> set[str]: ...

    @declared_symbols.setter
    def declared_symbols(self, value: set[str]) -> None: ...

    @property
    def registered_audio_channels(self) -> set[str]: ...

    @registered_audio_channels.setter
    def registered_audio_channels(self, value: set[str]) -> None: ...

    @property
    def has_dynamic_jumps(self) -> bool: ...

    @has_dynamic_jumps.setter
    def has_dynamic_jumps(self, value: bool) -> None: ...


@runtime_checkable
class AssetProvider(Protocol):
    """Asset discovery and marking.

    Note: ``defined_audio_map`` and ``registered_audio_channels`` were
    moved to ``SymbolProvider`` because cross-file rules that accept
    ``DiagnosticSinkAndSymbolsAndNoqa`` (without ``AssetProvider``) also
    need them. They remain accessible to ``AssetChecker`` via the
    ``DiagnosticSinkAndSymbolsAndAsset`` intersection.
    """

    @property
    def known_assets(self) -> set[str]: ...

    @property
    def valid_images(self) -> set[str]: ...

    @property
    def audio_dir_files(self) -> dict[str, str]: ...

    def _mark_asset_used(self, asset_ref: str) -> None: ...

    def _get_tag_known_attributes(self, base_tag: str, all_valid: set[str]) -> set[str]: ...


@runtime_checkable
class FlowProvider(Protocol):
    """Delegation to flow/python_ast checkers."""

    def _analyze_menu_flow(
        self,
        lines: list[str],
        start_idx: int,
        menu_indent: int,
        file_path: str = "",
        noqa_map: dict | None = None,
        already_guaranteed: set[str] | None = None,
    ) -> tuple[int, dict[str, tuple[str, ...]], set[str], bool]: ...

    def _can_reach_return(self, label_name: str, visited: set[str] | None = None) -> bool: ...

    def _check_cfg_condition(
        self,
        file_path: str,
        line_idx: int,
        line_content: str,
        expr: str,
        branch_uninitialized: dict,
        noqa_map: dict,
    ) -> None: ...

    def _check_cfg_interpolations(
        self,
        file_path: str,
        line_idx: int,
        line_content: str,
        branch_uninitialized: dict[str, tuple[str, ...]],
        noqa_map: dict,
    ) -> None: ...

    def _check_condition(
        self,
        file_path: str,
        line_idx: int,
        line_content: str,
        expr: str,
        screen_name: str | None,
        screen_local_symbols: set[str],
        noqa_map: dict,
    ) -> None: ...

    def _check_python_ast(
        self,
        py_code: str,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None = None,
    ) -> None: ...

    def _check_screen_mutation(
        self,
        py_code: str,
        file_path: str,
        line_idx: int,
        line_content: str,
        screen_name: str | None,
        screen_local_symbols: set[str],
        noqa_map: dict,
        lines: list[str] | None = None,
    ) -> None: ...

    def _clear_safe_cfg_vars(self, py_code: str, branch_uninitialized: dict) -> None: ...

    def _consume_block(
        self, lines: list[str], start_idx: int, header_indent: int
    ) -> tuple[int, list[str]]: ...

    def _scan_python_assets(self, code_lines: list[str] | str) -> None: ...


@runtime_checkable
class NoqaMapProvider(Protocol):
    """Per-file ``# noqa`` directive lookup for cross-file rules.

    Cross-file rules (RPY701-707, RPY802) emit diagnostics whose
    ``file_path`` and ``line_number`` point at the declaration line of
    a symbol in a file that has already been analysed (and whose
    ``noqa_map`` is therefore no longer on the call stack). These rules
    look up the per-file directive map via ``_get_noqa_map_for_file``
    and emit the diagnostic through ``_add_diagnostic_by_file`` so that
    inline ``# noqa: RPYxxx`` directives on the declaration line are
    honoured the same way as built-in per-line checkers honour them
    through ``_add_diagnostic``.

    SenpyAnalyzer populates its ``_noqa_maps`` dict during
    ``AnalysisPipeline._analyze_file`` and ``analyze_tl_file``.
    """

    def _get_noqa_map_for_file(self, file_path: str) -> dict[int, set[str] | None]:
        """Return the ``# noqa`` directive map for ``file_path``.

        Returns an empty dict if the file was never analysed (e.g. a
        brand new file, or a file that was skipped due to a Tier 2
        cache hit). Cross-file rules use this to honour inline
        suppression directives on the declaration line of the symbol
        they fire on.
        """
        ...

    def _add_diagnostic_by_file(self, diag: Diagnostic) -> None:
        """Emit a diagnostic for a specific file, honouring its noqa map.

        Looks up the per-file ``noqa_map`` populated during
        ``_analyze_file`` and delegates to ``_add_diagnostic``. If the
        target file was never analysed, the diagnostic is still emitted
        — ``# noqa`` suppression is a best-effort convenience, not a
        hard contract.
        """
        ...


@runtime_checkable
class ProjectInfo(Protocol):
    """Project-level metadata."""

    project_path: str


# =============================================================================
# Intersection Protocols — convenience compositions for checker __init__.
# =============================================================================


class DiagnosticSinkAndSymbols(DiagnosticSink, SymbolProvider, Protocol):
    """Intersection of DiagnosticSink and SymbolProvider.

    Most built-in line checkers (FormattingChecker, ScreenChecker,
    AssetChecker, DialogueChecker, StateChecker) need both: they emit
    diagnostics via ``_add_diagnostic`` / ``_get_utf16_range`` (the
    DiagnosticSink half) AND read symbol registries like
    ``analyzer.labels`` / ``analyzer.screens`` / ``analyzer.variables``
    (the SymbolProvider half).

    Declared as a single named Protocol so that checker ``__init__``
    signatures can take a single typed parameter instead of being forced
    to type it as ``Any`` (which is what the previous compromise did —
    see CHANGELOG Phase 2a). Multiple-inheritance composition of two
    ``Protocol`` classes produces a structural intersection that
    ``@runtime_checkable`` can verify with ``isinstance``.

    SenpyAnalyzer implements this Protocol because it implements both
    halves individually.
    """


class DiagnosticSinkAndSymbolsAndFlow(DiagnosticSink, SymbolProvider, FlowProvider, Protocol):
    """Intersection of DiagnosticSink, SymbolProvider and FlowProvider.

    Used by ``StateChecker`` — it emits diagnostics (DiagnosticSink),
    reads symbol registries (SymbolProvider) AND delegates to flow /
    python_ast helpers like ``_check_cfg_condition`` /
    ``_analyze_menu_flow`` (FlowProvider). StateChecker is the only
    per-line checker that needs FlowProvider; the other four
    (FormattingChecker, ScreenChecker, AssetChecker, DialogueChecker)
    can use the narrower ``DiagnosticSinkAndSymbols``.
    """


class DiagnosticSinkAndSymbolsAndNoqa(DiagnosticSink, SymbolProvider, NoqaMapProvider, Protocol):
    """Intersection of DiagnosticSink, SymbolProvider and NoqaMapProvider.

    Used by cross-file rules (``dead_code.py``, ``translation.py``'s
    ``_check_rpy802_cross_language``) that emit diagnostics through
    ``_add_diagnostic_by_file`` (NoqaMapProvider) for declaration lines
    in files that have already been analysed. The NoqaMapProvider half
    lets the rule honour ``# noqa: RPYxxx`` directives on the
    declaration line without re-threading the per-file ``noqa_map``
    through the call stack.
    """


class DiagnosticSinkAndSymbolsAndAsset(DiagnosticSink, SymbolProvider, AssetProvider, Protocol):
    """Intersection of DiagnosticSink, SymbolProvider and AssetProvider.

    Used by ``AssetChecker`` — it emits diagnostics (DiagnosticSink),
    reads symbol registries (SymbolProvider) AND uses
    ``AssetProvider`` members like ``_mark_asset_used`` /
    ``valid_images`` / ``_get_tag_known_attributes`` / ``known_assets``
    / ``audio_dir_files``.
    """


class FullAnalyzer(
    DiagnosticSink,
    SymbolProvider,
    AssetProvider,
    FlowProvider,
    NoqaMapProvider,
    ProjectInfo,
    Protocol,
):
    """Intersection of every Protocol SenpyAnalyzer implements.

    Used by callers that need the whole analyzer surface in one typed
    parameter (e.g. ``PythonAstChecker``, ``StoryFlowAnalyzer``).
    Equivalent to the old ``analyzer: SenpyAnalyzer`` concrete type
    hint, but expressed structurally so that a future test double only
    has to satisfy the Protocol surface rather than inherit from
    ``SenpyAnalyzer``.
    """
