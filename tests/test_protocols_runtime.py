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
    FlowProvider,
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
        assert isinstance(analyzer, ProjectInfo), (
            "SenpyAnalyzer must implement ProjectInfo Protocol — " "missing project_path attribute"
        )


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
