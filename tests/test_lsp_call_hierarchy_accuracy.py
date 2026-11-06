"""TDD tests for Call Hierarchy accuracy in `senpy/lsp/handlers/navigation.py`.

Two RND bugs covered here, both in the same file:

**B14 (outgoing_calls from_ranges)**: VS Code Call Hierarchy highlights the
*source label's declaration line* instead of the actual `jump`/`call`
statement. The LSP spec says ``CallHierarchyOutgoingCall.from_ranges``
should point at where the call happens in the source code — not where
the enclosing label is declared.

**B13 (incoming_calls O(N²))**: ``incoming_calls`` scans every label in
the project for each jump source, giving O(N·M) per request. The fix
builds a per-file index of labels at snapshot-creation time so the
containing-label lookup is O(log N) per jump site.

Both bugs share the same data structure (a per-file label index in
``_symbol_snapshot``) and the same file (``navigation.py``), so they
ship as one logical unit.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from lsprotocol import types as lsp

import senpy.lsp.server as server_mod
from senpy.core.symbols import LabelSymbol


@pytest.fixture
def clean_lsp_state():
    """Save + clear LSP module state so each test starts from a known baseline.

    The existing call-hierarchy tests in test_0_6_0_subprint_3b.py set
    ``_active_analyzer`` and ``_is_initialized`` but never touch
    ``_symbol_snapshot`` — so if an earlier test populated the snapshot,
    later tests would read stale labels. This fixture explicitly clears
    the snapshot so the test's setup is authoritative.
    """
    saved_analyzer = server_mod._active_analyzer
    saved_init = server_mod._is_initialized
    saved_snapshot = dict(server_mod._symbol_snapshot)
    server_mod._active_analyzer = MagicMock()
    server_mod._is_initialized = True
    # Reset the snapshot to an empty baseline — the handler under test
    # will fall back to _active_analyzer.* when the snapshot is empty.
    for key in list(server_mod._symbol_snapshot.keys()):
        val = server_mod._symbol_snapshot[key]
        if isinstance(val, (dict, set)):
            val.clear()
    yield server_mod
    server_mod._active_analyzer = saved_analyzer
    server_mod._is_initialized = saved_init
    server_mod._symbol_snapshot.clear()
    server_mod._symbol_snapshot.update(saved_snapshot)


# =============================================================================
# outgoing_calls from_ranges must point at the jump line
# =============================================================================


class TestOutgoingCallsJumpLine:
    """outgoing_calls must return from_ranges at the actual jump/call line,
    not at the source label's declaration line.
    """

    def test_outgoing_from_ranges_points_at_jump_line(self, clean_lsp_state):
        """Single jump from line 3 of `source` to `dest` → from_ranges[0]
        must be line 3 (0-indexed: 2), NOT line 1 (the `label source:` line).
        """
        from senpy.lsp.handlers.navigation import outgoing_calls

        # source label at line 1, jump to dest at line 3
        # dest label at line 10
        # jump_sources[dest] = [(source_file, 3)] — the jump is at line 3
        clean_lsp_state._active_analyzer.labels = {
            "source": LabelSymbol(
                name="source",
                file_path="/test.rpy",
                line_number=1,
                code_line="label source:",
                outgoing_jumps={"dest"},
            ),
            "dest": LabelSymbol(
                name="dest",
                file_path="/test.rpy",
                line_number=10,
                code_line="label dest:",
            ),
        }
        clean_lsp_state._active_analyzer.jump_sources = {
            "dest": [("/test.rpy", 3)],
        }

        mock_ls = MagicMock()
        item = lsp.CallHierarchyItem(
            name="source",
            kind=lsp.SymbolKind.Function,
            uri="file:///test.rpy",
            range=lsp.Range(start=lsp.Position(0, 0), end=lsp.Position(0, 10)),
            selection_range=lsp.Range(start=lsp.Position(0, 6), end=lsp.Position(0, 12)),
        )
        params = lsp.CallHierarchyOutgoingCallsParams(item=item)
        result = outgoing_calls(mock_ls, params)

        assert len(result) == 1, f"Expected 1 outgoing call to dest, got {len(result)}"
        call = result[0]
        assert call.to.name == "dest"
        assert len(call.from_ranges) >= 1, "from_ranges must not be empty"
        # The jump was at line 3 → 0-indexed line 2. Pre-fix code returned
        # line 0 (the `label source:` declaration line) — wrong.
        assert call.from_ranges[0].start.line == 2, (
            f"from_ranges.start.line = {call.from_ranges[0].start.line}, "
            "expected 2 (the jump line, 0-indexed). Pre-fix code returns 0 "
            "(the source label declaration line) — VS Code would highlight "
            "`label source:` instead of `jump dest`."
        )

    def test_outgoing_from_ranges_multiple_jumps_to_same_target(self, clean_lsp_state):
        """If source jumps to dest twice (lines 3 and 7), from_ranges must
        contain BOTH jump lines — one entry per call site.
        """
        from senpy.lsp.handlers.navigation import outgoing_calls

        clean_lsp_state._active_analyzer.labels = {
            "source": LabelSymbol(
                name="source",
                file_path="/test.rpy",
                line_number=1,
                code_line="label source:",
                outgoing_jumps={"dest"},
            ),
            "dest": LabelSymbol(
                name="dest",
                file_path="/test.rpy",
                line_number=20,
                code_line="label dest:",
            ),
        }
        # Two jumps from source's file to dest: at lines 3 and 7
        clean_lsp_state._active_analyzer.jump_sources = {
            "dest": [("/test.rpy", 3), ("/test.rpy", 7)],
        }

        mock_ls = MagicMock()
        item = lsp.CallHierarchyItem(
            name="source",
            kind=lsp.SymbolKind.Function,
            uri="file:///test.rpy",
            range=lsp.Range(start=lsp.Position(0, 0), end=lsp.Position(0, 10)),
            selection_range=lsp.Range(start=lsp.Position(0, 6), end=lsp.Position(0, 12)),
        )
        params = lsp.CallHierarchyOutgoingCallsParams(item=item)
        result = outgoing_calls(mock_ls, params)

        assert len(result) == 1
        call = result[0]
        assert call.to.name == "dest"
        # LSP spec: "There can be multiple ranges if the same target is
        # called multiple times from the same source."
        jump_lines = sorted(r.start.line for r in call.from_ranges)
        assert jump_lines == [2, 6], (
            f"Expected from_ranges lines [2, 6] (jumps at lines 3 and 7, "
            f"0-indexed), got {jump_lines}"
        )

    def test_outgoing_falls_back_to_label_range_when_jump_line_unknown(self, clean_lsp_state):
        """If jump_sources has no entry for the target (e.g. dynamic jump
        via renpy.jump() in a string), outgoing_calls must still return a
        from_range — falling back to the source label's declaration line.
        Graceful degradation, not a crash.
        """
        from senpy.lsp.handlers.navigation import outgoing_calls

        clean_lsp_state._active_analyzer.labels = {
            "source": LabelSymbol(
                name="source",
                file_path="/test.rpy",
                line_number=1,
                code_line="label source:",
                outgoing_jumps={"dest"},
            ),
            "dest": LabelSymbol(
                name="dest",
                file_path="/test.rpy",
                line_number=10,
                code_line="label dest:",
            ),
        }
        # No jump_sources entry for "dest" — simulate dynamic jump
        clean_lsp_state._active_analyzer.jump_sources = {}

        mock_ls = MagicMock()
        item = lsp.CallHierarchyItem(
            name="source",
            kind=lsp.SymbolKind.Function,
            uri="file:///test.rpy",
            range=lsp.Range(start=lsp.Position(0, 0), end=lsp.Position(0, 10)),
            selection_range=lsp.Range(start=lsp.Position(0, 6), end=lsp.Position(0, 12)),
        )
        params = lsp.CallHierarchyOutgoingCallsParams(item=item)
        result = outgoing_calls(mock_ls, params)

        assert len(result) == 1
        call = result[0]
        assert call.to.name == "dest"
        assert len(call.from_ranges) == 1
        # Fallback: source label declaration line (0-indexed)
        assert call.from_ranges[0].start.line == 0


# =============================================================================
# incoming_calls uses a per-file label index (O(N) → O(log N))
# =============================================================================


class TestIncomingCallsPerFileIndex:
    """incoming_calls must use a per-file index of labels instead of scanning
    every label in the project for each jump source.

    The index is built in ``_refresh_symbol_snapshot`` and stored as
    ``_symbol_snapshot["labels_by_file"]`` — ``dict[file_path, list[(name, line)]]``
    sorted by line_number.
    """

    def test_symbol_snapshot_includes_labels_by_file_index(self, clean_lsp_state, tmp_path: Path):
        """``_refresh_symbol_snapshot`` must populate ``labels_by_file`` in
        the snapshot. Pre-fix code does not build this index.
        """
        from senpy.core.analyzer import SenpyAnalyzer

        # Build a real analyzer with a 2-file project so the snapshot has
        # real labels to index.
        game_dir = tmp_path / "game"
        game_dir.mkdir(parents=True)
        (game_dir / "a.rpy").write_text("label alpha:\n    jump beta\n", encoding="utf-8")
        (game_dir / "b.rpy").write_text("label beta:\n    return\n", encoding="utf-8")
        analyzer = SenpyAnalyzer(str(tmp_path))
        analyzer.run(quiet=True)
        clean_lsp_state._active_analyzer = analyzer

        server_mod._refresh_symbol_snapshot()

        assert "labels_by_file" in server_mod._symbol_snapshot, (
            "_symbol_snapshot must include 'labels_by_file' — a per-file "
            "index of labels for O(log N) containing-label lookup in "
            "incoming_calls. Pre-fix code scans all labels per jump source."
        )
        index = server_mod._symbol_snapshot["labels_by_file"]
        assert isinstance(index, dict)
        # Both files must be present in the index
        indexed_files = {Path(p).name for p in index}
        assert "a.rpy" in indexed_files, f"a.rpy missing from index: {indexed_files}"
        assert "b.rpy" in indexed_files, f"b.rpy missing from index: {indexed_files}"
        # Each file's labels must be sorted by line_number
        for file_path, labels_in_file in index.items():
            lines = [line for _, line in labels_in_file]
            assert lines == sorted(
                lines
            ), f"labels_by_file[{file_path}] is not sorted by line_number: {lines}"

    def test_incoming_calls_finds_correct_containing_label_with_multiple_labels_in_file(
        self, clean_lsp_state
    ):
        """incoming_calls must return the label that *contains* the jump line,
        not just any label in the same file.

        Setup: file.rpy has label_a at line 1, label_b at line 10, label_c
        at line 20. A jump to ``target`` happens at line 15 (inside label_b).
        incoming_calls(target) must return label_b as the caller — not
        label_a (which also has line_number <= 15) and not label_c (which
        starts after line 15).

        This test passes with the current O(N²) code too — it is a
        regression guard ensuring the per-file index refactor preserves
        correctness.
        """
        from senpy.lsp.handlers.navigation import incoming_calls

        clean_lsp_state._active_analyzer.labels = {
            "target": LabelSymbol(
                name="target", file_path="/other.rpy", line_number=1, code_line="label target:"
            ),
            "label_a": LabelSymbol(
                name="label_a", file_path="/test.rpy", line_number=1, code_line="label label_a:"
            ),
            "label_b": LabelSymbol(
                name="label_b", file_path="/test.rpy", line_number=10, code_line="label label_b:"
            ),
            "label_c": LabelSymbol(
                name="label_c", file_path="/test.rpy", line_number=20, code_line="label label_c:"
            ),
        }
        # Jump to target happens at line 15 — inside label_b
        clean_lsp_state._active_analyzer.jump_sources = {
            "target": [("/test.rpy", 15)],
        }

        mock_ls = MagicMock()
        item = lsp.CallHierarchyItem(
            name="target",
            kind=lsp.SymbolKind.Function,
            uri="file:///other.rpy",
            range=lsp.Range(start=lsp.Position(0, 0), end=lsp.Position(0, 10)),
            selection_range=lsp.Range(start=lsp.Position(0, 6), end=lsp.Position(0, 12)),
        )
        params = lsp.CallHierarchyIncomingCallsParams(item=item)
        result = incoming_calls(mock_ls, params)

        assert len(result) == 1
        call = result[0]
        assert call.from_.name == "label_b", (
            f"Expected label_b (jump at line 15 is inside label_b's range "
            f"10..19), got {call.from_.name}"
        )

    def test_incoming_calls_from_ranges_points_at_jump_line(self, clean_lsp_state):
        """incoming_calls from_ranges must point at the actual jump line,
        not at the containing label's declaration line.

        Same bug class as T-013 outgoing_calls, but for the incoming
        direction. The current code already does this correctly (line 882
        uses ``caller_line``), so this test is a regression guard.
        """
        from senpy.lsp.handlers.navigation import incoming_calls

        clean_lsp_state._active_analyzer.labels = {
            "target": LabelSymbol(
                name="target", file_path="/other.rpy", line_number=1, code_line="label target:"
            ),
            "caller": LabelSymbol(
                name="caller", file_path="/test.rpy", line_number=1, code_line="label caller:"
            ),
        }
        # Jump to target at line 5 — inside caller (which starts at line 1)
        clean_lsp_state._active_analyzer.jump_sources = {
            "target": [("/test.rpy", 5)],
        }

        mock_ls = MagicMock()
        item = lsp.CallHierarchyItem(
            name="target",
            kind=lsp.SymbolKind.Function,
            uri="file:///other.rpy",
            range=lsp.Range(start=lsp.Position(0, 0), end=lsp.Position(0, 10)),
            selection_range=lsp.Range(start=lsp.Position(0, 6), end=lsp.Position(0, 12)),
        )
        params = lsp.CallHierarchyIncomingCallsParams(item=item)
        result = incoming_calls(mock_ls, params)

        assert len(result) == 1
        call = result[0]
        assert call.from_.name == "caller"
        assert len(call.from_ranges) == 1
        # Jump was at line 5 → 0-indexed line 4
        assert call.from_ranges[0].start.line == 4, (
            f"incoming_calls from_ranges must point at the jump line (4), "
            f"got {call.from_ranges[0].start.line}"
        )
