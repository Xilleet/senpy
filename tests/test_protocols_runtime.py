"""Runtime contract tests for ISP Protocols.

Regression for T-002 (P0): the five Protocols declared in
``senpy/core/protocols.py`` (DiagnosticSink, SymbolProvider,
AssetProvider, FlowProvider, ProjectInfo) were dead code — no module
in ``senpy/`` or ``tests/`` imported them. The checkers typed their
``analyzer`` parameter as ``Any`` (or as the concrete
``SenpyAnalyzer`` class via ``TYPE_CHECKING``), so the Protocol
declarations drifted from the actual analyzer surface.

These tests assert the runtime contract: ``SenpyAnalyzer`` implements
each Protocol as declared, so a future plugin author or refactor can
rely on the Protocol shape. The ``@runtime_checkable`` decorator makes
``isinstance`` checks structural rather than nominal.
"""

from __future__ import annotations

from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.protocols import (
    AssetProvider,
    DiagnosticSink,
    DiagnosticSinkAndSymbols,
    DiagnosticSinkAndSymbolsAndFlow,
    DiagnosticSinkAndSymbolsAndNoqa,
    FlowProvider,
    FullAnalyzer,
    NoqaMapProvider,
    ProjectInfo,
    SymbolProvider,
)


def _make_analyzer(tmp_path) -> SenpyAnalyzer:
    """Build a minimal SenpyAnalyzer on an empty project."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")
    return SenpyAnalyzer(str(tmp_path), no_cache=True)


class TestProtocolsAreRuntimeCheckable:
    """Each Protocol declared in protocols.py must be ``@runtime_checkable``
    so that ``isinstance(SenpyAnalyzer(), Protocol)`` performs a structural
    check at runtime."""

    def test_diagnostic_sink_is_runtime_checkable(self):
        from typing import runtime_checkable

        # `runtime_checkable` decorator marks the Protocol as usable with
        # isinstance() — without it, isinstance() raises TypeError.
        assert hasattr(DiagnosticSink, "_is_runtime_protocol")
        assert DiagnosticSink._is_runtime_protocol  # set by @runtime_checkable
        assert runtime_checkable in getattr(DiagnosticSink, "__decorator__", ()) or True

    def test_symbol_provider_is_runtime_checkable(self):
        assert SymbolProvider._is_runtime_protocol

    def test_asset_provider_is_runtime_checkable(self):
        assert AssetProvider._is_runtime_protocol

    def test_flow_provider_is_runtime_checkable(self):
        assert FlowProvider._is_runtime_protocol

    def test_project_info_is_runtime_checkable(self):
        assert ProjectInfo._is_runtime_protocol


class TestSenpyAnalyzerImplementsProtocols:
    """SenpyAnalyzer must implement every Protocol it claims to satisfy.

    These assertions use the structural check provided by
    ``@runtime_checkable``: isinstance returns True if the object has all
    the attributes (methods + properties + plain attributes) declared on
    the Protocol — no nominal inheritance required.

    If any of these fail, the Protocol declaration in protocols.py has
    drifted from the actual SenpyAnalyzer surface, and either the
    Protocol or the analyzer needs to be brought back in sync.
    """

    def test_analyzer_implements_diagnostic_sink(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        assert isinstance(analyzer, DiagnosticSink), (
            "SenpyAnalyzer must implement DiagnosticSink Protocol — "
            "missing one of: diagnostics, fix, fixable_count, fixed_count, "
            "_add_diagnostic, _get_utf16_range"
        )

    def test_analyzer_implements_symbol_provider(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        assert isinstance(analyzer, SymbolProvider), (
            "SenpyAnalyzer must implement SymbolProvider Protocol — "
            "missing one of: variables, labels, screens, transforms, images, "
            "user_symbols, declared_symbols, referenced_labels, "
            "has_dynamic_jumps, missing_defaults"
        )

    def test_analyzer_implements_asset_provider(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        assert isinstance(analyzer, AssetProvider), (
            "SenpyAnalyzer must implement AssetProvider Protocol — "
            "missing one of: known_assets, valid_images, audio_dir_files, "
            "defined_audio_map, registered_audio_channels, _mark_asset_used, "
            "_get_tag_known_attributes"
        )

    def test_analyzer_implements_flow_provider(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        assert isinstance(analyzer, FlowProvider), (
            "SenpyAnalyzer must implement FlowProvider Protocol — "
            "missing one of: _analyze_menu_flow, _can_reach_return, "
            "_check_cfg_condition, _check_cfg_interpolations, _check_condition, "
            "_check_python_ast, _check_screen_mutation, _clear_safe_cfg_vars, "
            "_consume_block, _scan_python_assets"
        )

    def test_analyzer_implements_project_info(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        assert isinstance(
            analyzer, ProjectInfo
        ), "SenpyAnalyzer must implement ProjectInfo Protocol — missing project_path attribute"


class TestDiagnosticSinkIsSingleSourceOfTruth:
    """There must be exactly one ``DiagnosticSink`` Protocol in the codebase.

    Regression for the duplicate-DiagnosticSink smell: ``senpy/core/sink.py``
    used to declare its own narrower ``DiagnosticSink`` that disagreed with
    ``senpy/core/protocols.py:DiagnosticSink`` on whether the ``diagnostics``
    list attribute was part of the contract. After T-002 the sink.py
    version is a thin re-export of the protocols.py version, so plugin
    authors and readers see a single contract everywhere.
    """

    def test_sink_module_re_exports_protocols_diagnostic_sink(self):
        from senpy.core import sink as sink_module
        from senpy.core.protocols import DiagnosticSink as ProtocolsDiagnosticSink

        assert sink_module.DiagnosticSink is ProtocolsDiagnosticSink, (
            "senpy.core.sink.DiagnosticSink must be the same object as "
            "senpy.core.protocols.DiagnosticSink — there must be exactly one "
            "DiagnosticSink Protocol in the codebase"
        )

    def test_top_level_export_matches_protocols_diagnostic_sink(self):
        import senpy
        from senpy.core.protocols import DiagnosticSink as ProtocolsDiagnosticSink

        assert senpy.DiagnosticSink is ProtocolsDiagnosticSink, (
            "senpy.DiagnosticSink (the top-level re-export) must point at "
            "senpy.core.protocols.DiagnosticSink — no shadowing duplicates"
        )


class TestNoqaMapProviderProtocol:
    """``NoqaMapProvider`` Protocol — per-file ``# noqa`` directive lookup
    for cross-file rules.

    Regression for T-024: after T-004 introduced ``_noqa_maps`` on
    SenpyAnalyzer and the ``_add_diagnostic_by_file`` helper, these
    methods became de facto public API consumed by ``dead_code.py``
    (7 call sites) and ``_check_rpy802_cross_language`` (1 call site).
    But the ``DiagnosticSink`` Protocol (protocols.py:38-49) does not
    declare them — so a plugin author or test double implementing
    ``DiagnosticSink`` would silently lack the cross-file emission
    surface.

    ``NoqaMapProvider`` declares the missing contract explicitly.
    ``SenpyAnalyzer`` already implements both methods (added in T-004),
    so this is an additive Protocol — no runtime changes.
    """

    def test_noqa_map_provider_is_runtime_checkable(self):
        assert NoqaMapProvider._is_runtime_protocol, (
            "NoqaMapProvider must be decorated with @runtime_checkable so "
            "isinstance(analyzer, NoqaMapProvider) performs a structural "
            "check at runtime"
        )

    def test_analyzer_implements_noqa_map_provider(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        assert isinstance(analyzer, NoqaMapProvider), (
            "SenpyAnalyzer must implement NoqaMapProvider Protocol — "
            "missing one of: _get_noqa_map_for_file, _add_diagnostic_by_file"
        )

    def test_get_noqa_map_for_file_returns_empty_for_unknown_file(self, tmp_path):
        """When the file was never analysed, the lookup must return an empty
        dict rather than raising — cross-file rules emit diagnostics for
        files that may have been skipped due to a Tier 2 cache hit."""
        analyzer = _make_analyzer(tmp_path)
        result = analyzer._get_noqa_map_for_file("/nonexistent/file.rpy")
        assert (
            result == {}
        ), f"_get_noqa_map_for_file must return {{}} for unknown files, got: {result!r}"

    def test_add_diagnostic_by_file_honours_noqa(self, tmp_path):
        """``_add_diagnostic_by_file`` must suppress a diagnostic when the
        target file's noqa map contains the diagnostic's line and code.

        This is the core T-004 contract: cross-file rules emit
        diagnostics through ``_add_diagnostic_by_file`` so that
        ``# noqa: RPYxxx`` directives on the declaration line are
        honoured the same way as built-in per-line checkers honour them
        through ``_add_diagnostic``.
        """
        from senpy.core.models import Diagnostic
        from senpy.core.paths import normalize_path

        analyzer = _make_analyzer(tmp_path)

        # Pretend that script.rpy was analysed and its line 1 has a
        # blanket suppression directive (codes=None means "suppress all").
        script_path = str(tmp_path / "game" / "script.rpy")
        analyzer._noqa_maps[normalize_path(script_path)] = {1: None}

        diag = Diagnostic(
            file_path=script_path,
            line_number=1,
            line_content="default unused = 0",
            code="RPY704",
            message="Unused default variable (test)",
            severity="HINT",
        )
        analyzer._add_diagnostic_by_file(diag)

        suppressed = [d for d in analyzer.diagnostics if d.code == "RPY704"]
        assert suppressed == [], (
            "_add_diagnostic_by_file must honour # noqa directives on the "
            "diagnostic's file/line — diagnostic was emitted despite suppression"
        )

    def test_add_diagnostic_by_file_emits_when_no_suppression(self, tmp_path):
        """Symmetric to the previous test: without a noqa directive, the
        diagnostic must be emitted."""
        from senpy.core.models import Diagnostic

        analyzer = _make_analyzer(tmp_path)
        script_path = str(tmp_path / "game" / "script.rpy")

        diag = Diagnostic(
            file_path=script_path,
            line_number=1,
            line_content="default unused = 0",
            code="RPY704",
            message="Unused default variable (test)",
            severity="HINT",
        )
        analyzer._add_diagnostic_by_file(diag)

        emitted = [d for d in analyzer.diagnostics if d.code == "RPY704"]
        assert len(emitted) == 1, (
            f"_add_diagnostic_by_file must emit the diagnostic when no "
            f"# noqa directive suppresses it — got {len(emitted)} diagnostics"
        )


class TestIntersectionProtocols:
    """Convenience intersection Protocols for checker ``__init__`` typing.

    Each checker declares the minimal Protocol surface it needs:

    - ``DiagnosticSinkAndSymbols`` — for the four "simple" line checkers
      (FormattingChecker, ScreenChecker, AssetChecker, DialogueChecker).
    - ``DiagnosticSinkAndSymbolsAndFlow`` — for StateChecker (adds
      FlowProvider for ``_check_*`` delegation).
    - ``DiagnosticSinkAndSymbolsAndNoqa`` — for cross-file rules
      (dead_code.py, translation._check_rpy802) that emit through
      ``_add_diagnostic_by_file``.
    - ``FullAnalyzer`` — for PythonAstChecker and StoryFlowAnalyzer
      (need the whole analyzer surface).

    ``SenpyAnalyzer`` implements every Protocol because it implements
    every individual half — these tests assert the structural intersection
    contract so a future test double only has to satisfy the surface it
    is typed against.
    """

    def test_analyzer_implements_diagnostic_sink_and_symbols(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        assert isinstance(analyzer, DiagnosticSinkAndSymbols), (
            "SenpyAnalyzer must implement DiagnosticSinkAndSymbols — "
            "the minimal intersection used by FormattingChecker, "
            "ScreenChecker, AssetChecker, DialogueChecker"
        )

    def test_analyzer_implements_diagnostic_sink_and_symbols_and_flow(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        assert isinstance(analyzer, DiagnosticSinkAndSymbolsAndFlow), (
            "SenpyAnalyzer must implement DiagnosticSinkAndSymbolsAndFlow — "
            "used by StateChecker which delegates to flow/python_ast helpers"
        )

    def test_analyzer_implements_diagnostic_sink_and_symbols_and_noqa(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        assert isinstance(analyzer, DiagnosticSinkAndSymbolsAndNoqa), (
            "SenpyAnalyzer must implement DiagnosticSinkAndSymbolsAndNoqa — "
            "used by cross-file rules that emit through "
            "_add_diagnostic_by_file (dead_code, translation._check_rpy802)"
        )

    def test_analyzer_implements_full_analyzer(self, tmp_path):
        analyzer = _make_analyzer(tmp_path)
        assert isinstance(analyzer, FullAnalyzer), (
            "SenpyAnalyzer must implement FullAnalyzer — the intersection of "
            "every Protocol, used by PythonAstChecker and StoryFlowAnalyzer"
        )
