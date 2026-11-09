"""Tests for LSP references using snapshot, not live analyzer (P1-7).

``references`` in ``senpy/lsp/handlers/navigation.py`` (lines 740-752)
read ``server_mod._active_analyzer.labels`` and
``_active_analyzer.jump_sources`` (live analyzer state). But after
``did_change → analyze_file_only``, the live analyzer's label registry
is purged and rebuilt for ONLY the edited file — labels from other
files disappear from the live registry until the next full analysis.

Meanwhile, ``_symbol_snapshot`` is refreshed on ``did_open``,
``did_save``, and ``did_change_watched_files`` — it retains labels from
all files across an ``analyze_file_only`` cycle. Other handlers
(``rename``, ``prepare_rename``, ``incoming_calls``, ``outgoing_calls``,
``workspace_symbol``) already use the snapshot.

The fix: replace ``_active_analyzer.labels`` →
``_symbol_snapshot["labels"]`` and ``_active_analyzer.jump_sources`` →
``_symbol_snapshot["jump_sources"]`` in the references handler.

This test module reproduces the bug: a multi-file project where file A
jumps to a label in file B. After editing file A (simulating
``analyze_file_only``), references on the label must still find the
jump site in file A. Before the fix, the live registry lost file B's
label and references returned an empty list.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from lsprotocol import types as lsp

from senpy.core.analyzer import SenpyAnalyzer
from senpy.lsp import server as server_mod
from senpy.lsp.handlers.navigation import references
from tests._helpers.lsp import MockDocument, MockWorkspace


def _make_ref_params(
    uri: str, line: int, char: int, include_decl: bool = True
) -> lsp.ReferenceParams:
    """Build ReferenceParams for the given position."""
    return lsp.ReferenceParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        position=lsp.Position(line=line, character=char),
        context=lsp.ReferenceContext(include_declaration=include_decl),
    )


def _setup_multi_file_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a 2-file project where file_a.rpy jumps to a label in file_b.rpy.

    Returns (project_root, file_a_path, file_b_path).
    """
    game = tmp_path / "game"
    game.mkdir(parents=True, exist_ok=True)

    # file_a.rpy: jumps to `target_label` which is defined in file_b.rpy.
    file_a = game / "file_a.rpy"
    file_a.write_text(
        'label start:\n    "Hello"\n    jump target_label\n    return\n',
        encoding="utf-8",
    )

    # file_b.rpy: defines `target_label` and jumps back to `start`.
    file_b = game / "file_b.rpy"
    file_b.write_text(
        'label target_label:\n    "In target"\n    jump start\n    return\n',
        encoding="utf-8",
    )

    return tmp_path, file_a, file_b


def _initialize_lsp(project_root: Path) -> SenpyAnalyzer:
    """Initialize the LSP server with a fresh analyzer over the project."""
    analyzer = SenpyAnalyzer(str(project_root))
    analyzer.run(quiet=True)
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    server_mod._refresh_symbol_snapshot()
    return analyzer


class TestReferencesUsesSnapshotNotLiveAnalyzer:
    """references must use _symbol_snapshot, not _active_analyzer (live)."""

    def test_references_finds_label_after_analyze_file_only(self, tmp_path: Path):
        """references on `target_label` must find jump sites in file_a.rpy.

        Scenario:
          1. Full analysis — snapshot + live both have all labels.
          2. Simulate `analyze_file_only` on file_a.rpy: the live analyzer's
             label registry is rebuilt for file_a only — `target_label`
             (defined in file_b.rpy) disappears from the live registry.
             But `_symbol_snapshot` retains it.
          3. references on `target_label` must still return the jump site
             in file_a.rpy (line 3: `jump target_label`).

        Before P1-7: references read `_active_analyzer.labels` → after
        analyze_file_only, `target_label` was not in the live registry →
        references returned None (no locations). The user saw "No references
        found" even though file_a.rpy clearly jumps to target_label.
        """
        project_root, file_a, file_b = _setup_multi_file_project(tmp_path)
        _initialize_lsp(project_root)

        # Sanity: target_label is in the snapshot (full analysis ran).
        assert (
            "target_label" in server_mod._symbol_snapshot["labels"]
        ), "Test setup: target_label must be in snapshot after full analysis."
        # And in jump_sources (file_a.rpy jumps to it).
        assert (
            "target_label" in server_mod._symbol_snapshot["jump_sources"]
        ), "Test setup: target_label must be in jump_sources after full analysis."

        # Simulate analyze_file_only on file_a.rpy: purge labels NOT in file_a
        # from the live analyzer. This mimics what happens after did_change —
        # the live registry is rebuilt for the edited file only.
        analyzer = server_mod._active_analyzer
        labels_to_purge = [
            name for name, lbl in analyzer.labels.items() if lbl.file_path != str(file_a)
        ]
        for name in labels_to_purge:
            del analyzer.labels[name]

        # Verify the bug scenario: target_label is gone from live labels
        # but still in snapshot.
        assert "target_label" not in analyzer.labels, (
            "Test setup: target_label must be purged from live labels "
            "to simulate analyze_file_only on file_a.rpy."
        )
        assert "target_label" in server_mod._symbol_snapshot["labels"], (
            "Test setup: target_label must still be in snapshot "
            "(snapshot is not purged by analyze_file_only)."
        )

        # Now call references on `target_label` from file_b.rpy.
        # Cursor on the label declaration line (line 0: "label target_label:").
        # Use _path_to_uri (not f"file://{file_b}") — the server's helper
        # produces the canonical file URI (file:///C:/... on Windows,
        # file:///tmp/... on POSIX). Hardcoding f"file://{path}" breaks on
        # Windows because it produces file://C:\... (no third slash,
        # backslashes) which does not match the URIs the server returns.
        uri_b = server_mod._path_to_uri(str(file_b))
        script_b = file_b.read_text(encoding="utf-8")
        doc = MockDocument(uri_b, script_b)
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        # Cursor on "target_label" in "label target_label:" (line 0, char 7).
        params = _make_ref_params(uri_b, line=0, char=10)

        result = references(mock_ls, params)

        # references MUST find the jump site in file_a.rpy.
        # Before P1-7: result was None or empty (live registry lost target_label).
        assert result, (
            "references on target_label returned no locations even though "
            "file_a.rpy jumps to it. The handler is reading the live analyzer "
            "registry (which was purged by analyze_file_only) instead of the "
            "snapshot. Replace _active_analyzer.labels with _symbol_snapshot['labels']."
        )

        # Verify the jump site in file_a.rpy is in the results.
        # Use _path_to_uri for the same canonical-URI reason.
        file_a_uri = server_mod._path_to_uri(str(file_a))
        uris_in_result = {loc.uri for loc in result}
        assert file_a_uri in uris_in_result, (
            f"references must include file_a.rpy (which jumps to target_label). "
            f"Got URIs: {uris_in_result}"
        )

    def test_references_includes_declaration_when_requested(self, tmp_path: Path):
        """references with include_declaration=True must include the label decl.

        Sanity test: the declaration (label target_label: in file_b.rpy)
        must be in the results when context.include_declaration is True.
        This guards against the fix accidentally dropping the declaration.
        """
        project_root, file_a, file_b = _setup_multi_file_project(tmp_path)
        _initialize_lsp(project_root)

        uri_b = server_mod._path_to_uri(str(file_b))
        script_b = file_b.read_text(encoding="utf-8")
        doc = MockDocument(uri_b, script_b)
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        # Cursor on "target_label" in "label target_label:" (line 0, char 10).
        params = _make_ref_params(uri_b, line=0, char=10, include_decl=True)

        result = references(mock_ls, params)
        assert result, "references must return locations for target_label."

        # The declaration (file_b.rpy, line 0) must be in the results.
        file_b_uri = server_mod._path_to_uri(str(file_b))
        decl_locations = [
            loc for loc in result if loc.uri == file_b_uri and loc.range.start.line == 0
        ]
        assert decl_locations, (
            f"references with include_declaration=True must include the label "
            f"declaration (file_b.rpy line 0). Got: {[(loc.uri, loc.range.start.line) for loc in result]}"
        )

    def test_references_excludes_declaration_when_not_requested(self, tmp_path: Path):
        """references with include_declaration=False must exclude the label decl.

        Sanity test: only the jump sites (file_a.rpy) must be in the results
        when context.include_declaration is False.
        """
        project_root, file_a, file_b = _setup_multi_file_project(tmp_path)
        _initialize_lsp(project_root)

        uri_b = server_mod._path_to_uri(str(file_b))
        script_b = file_b.read_text(encoding="utf-8")
        doc = MockDocument(uri_b, script_b)
        mock_ls = MagicMock()
        mock_ls.workspace = MockWorkspace(doc)

        params = _make_ref_params(uri_b, line=0, char=10, include_decl=False)

        result = references(mock_ls, params)
        assert result, "references must return jump site locations."

        file_b_uri = server_mod._path_to_uri(str(file_b))
        decl_locations = [
            loc for loc in result if loc.uri == file_b_uri and loc.range.start.line == 0
        ]
        assert not decl_locations, (
            f"references with include_declaration=False must NOT include the "
            f"declaration. Got decl locations: {decl_locations}"
        )
