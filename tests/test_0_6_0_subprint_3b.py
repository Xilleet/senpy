"""Tests for 0.6.0 Под-спринт 3b (Заход 2): LSP killer-features part 2.

LSP-6: textDocument/signatureHelp — подсказки параметров для call label(...) и use screen(...).
       Когда пишешь `call my_label(` — VS Code показывает (name, age=18) из сигнатуры label'а.

LSP-5: textDocument/prepareCallHierarchy — «кто вызывает этот label?» + «куда ведёт?».
       Правый клик на label → «Find Callers» → видишь все jump/call к этому label'у.
       Killer для VN — навигация по графу вызовов.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# Reuse mocks from 3a test file
from test_0_6_0_subprint_3a import MockDocument, MockWorkspace  # noqa: E402


# =============================================================================
# LSP-6: textDocument/signatureHelp
# =============================================================================


class TestSignatureHelpHandler:
    """LSP-6: signatureHelp shows parameter hints for call label(...) / use screen(...).

    When user types `call my_label(` and the cursor is inside the parens,
    VS Code calls signatureHelp to display the parameter list.

    Returns SignatureHelp with:
        signatures: list[SignatureInformation]
            - label: full signature (e.g. "my_label(name, age=18)")
            - parameters: list[ParameterInformation]
        activeSignature: index of active signature (0 for single)
        activeParameter: index of parameter cursor is on

    Sources:
        - LabelSymbol.signature (SignatureInfo with pos_names)
        - ScreenSymbol.signature (same)
    """

    def test_signature_help_function_exists(self):
        """signature_help() must be importable from handlers."""
        from senpy.lsp.handlers.completion import signature_help
        assert callable(signature_help)

    def test_signature_help_returns_none_when_no_analyzer(self):
        """Without analyzer, signature_help returns None."""
        from senpy.lsp.handlers.completion import signature_help
        from lsprotocol import types as lsp
        from senpy.lsp import server as server_mod

        # Save and clear state
        original_analyzer = server_mod._active_analyzer
        original_init = server_mod._is_initialized
        server_mod._active_analyzer = None
        server_mod._is_initialized = False

        try:
            mock_doc = MockDocument(
                "file:///test.rpy",
                "call my_label()\n"
            )
            mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
            mock_ls = MagicMock()
            mock_ls.workspace = mock_workspace

            params = lsp.SignatureHelpParams(
                text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy"),
                position=lsp.Position(line=0, character=15),  # inside parens
            )
            result = signature_help(mock_ls, params)
            assert result is None
        finally:
            server_mod._active_analyzer = original_analyzer
            server_mod._is_initialized = original_init

    def test_signature_help_returns_none_for_non_call_line(self):
        """signature_help returns None if line doesn't contain call/use."""
        from senpy.lsp.handlers.completion import signature_help
        from lsprotocol import types as lsp
        from senpy.lsp import server as server_mod

        # Set up minimal analyzer mock
        mock_analyzer = MagicMock()
        mock_analyzer.labels = {}
        mock_analyzer.screens = {}
        original_analyzer = server_mod._active_analyzer
        original_init = server_mod._is_initialized
        server_mod._active_analyzer = mock_analyzer
        server_mod._is_initialized = True

        try:
            mock_doc = MockDocument(
                "file:///test.rpy",
                '    "This is dialogue, not a call"\n'
            )
            mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
            mock_ls = MagicMock()
            mock_ls.workspace = mock_workspace

            params = lsp.SignatureHelpParams(
                text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy"),
                position=lsp.Position(line=0, character=10),
            )
            result = signature_help(mock_ls, params)
            assert result is None
        finally:
            server_mod._active_analyzer = original_analyzer
            server_mod._is_initialized = original_init

    def test_signature_help_for_call_label(self):
        """`call my_label(name, age)` → SignatureHelp with label's signature."""
        from senpy.lsp.handlers.completion import signature_help
        from lsprotocol import types as lsp
        from senpy.lsp import server as server_mod
        from senpy.core.symbols import LabelSymbol
        from senpy.core.signature import SignatureInfo

        # Mock analyzer with a label that has a signature
        mock_analyzer = MagicMock()
        mock_label = LabelSymbol(
            name="my_label",
            file_path="/test.rpy",
            line_number=1,
            code_line="label my_label(name, age=18):",
            signature=SignatureInfo(
                min_args=1,
                max_args=2,
                has_params=True,
                pos_names=["name", "age"],
                required_names={"name"},
                all_names={"name", "age"},
            ),
        )
        mock_analyzer.labels = {"my_label": mock_label}
        mock_analyzer.screens = {}
        original_analyzer = server_mod._active_analyzer
        original_init = server_mod._is_initialized
        server_mod._active_analyzer = mock_analyzer
        server_mod._is_initialized = True

        try:
            mock_doc = MockDocument(
                "file:///test.rpy",
                "call my_label()\n"  # cursor inside parens
            )
            mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
            mock_ls = MagicMock()
            mock_ls.workspace = mock_workspace

            params = lsp.SignatureHelpParams(
                text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy"),
                position=lsp.Position(line=0, character=15),  # inside ()
            )
            result = signature_help(mock_ls, params)

            assert result is not None, "Expected SignatureHelp for call my_label()"
            assert isinstance(result, lsp.SignatureHelp)
            assert len(result.signatures) >= 1
            sig = result.signatures[0]
            # Label should contain the label name and parameters
            assert "my_label" in sig.label
            assert "name" in sig.label
        finally:
            server_mod._active_analyzer = original_analyzer
            server_mod._is_initialized = original_init

    def test_signature_help_for_use_screen(self):
        """`use my_screen(arg1, arg2)` → SignatureHelp with screen's signature."""
        from senpy.lsp.handlers.completion import signature_help
        from lsprotocol import types as lsp
        from senpy.lsp import server as server_mod
        from senpy.core.symbols import ScreenSymbol
        from senpy.core.signature import SignatureInfo

        mock_analyzer = MagicMock()
        mock_screen = ScreenSymbol(
            name="my_screen",
            file_path="/test.rpy",
            line_number=1,
            signature=SignatureInfo(
                min_args=1,
                max_args=2,
                has_params=True,
                pos_names=["title", "width"],
                required_names={"title"},
                all_names={"title", "width"},
            ),
        )
        mock_analyzer.labels = {}
        mock_analyzer.screens = {"my_screen": mock_screen}
        original_analyzer = server_mod._active_analyzer
        original_init = server_mod._is_initialized
        server_mod._active_analyzer = mock_analyzer
        server_mod._is_initialized = True

        try:
            mock_doc = MockDocument(
                "file:///test.rpy",
                "use my_screen()\n"
            )
            mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
            mock_ls = MagicMock()
            mock_ls.workspace = mock_workspace

            params = lsp.SignatureHelpParams(
                text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy"),
                position=lsp.Position(line=0, character=15),
            )
            result = signature_help(mock_ls, params)

            assert result is not None
            assert len(result.signatures) >= 1
            sig = result.signatures[0]
            assert "my_screen" in sig.label
            assert "title" in sig.label
        finally:
            server_mod._active_analyzer = original_analyzer
            server_mod._is_initialized = original_init

    def test_signature_help_for_label_without_params(self):
        """`call simple_label()` where label has no params → still returns help (empty params)."""
        from senpy.lsp.handlers.completion import signature_help
        from lsprotocol import types as lsp
        from senpy.lsp import server as server_mod
        from senpy.core.symbols import LabelSymbol
        from senpy.core.signature import SignatureInfo

        mock_analyzer = MagicMock()
        mock_label = LabelSymbol(
            name="simple_label",
            file_path="/test.rpy",
            line_number=1,
            code_line="label simple_label:",
            signature=SignatureInfo(has_params=False),  # no params
        )
        mock_analyzer.labels = {"simple_label": mock_label}
        mock_analyzer.screens = {}
        original_analyzer = server_mod._active_analyzer
        original_init = server_mod._is_initialized
        server_mod._active_analyzer = mock_analyzer
        server_mod._is_initialized = True

        try:
            mock_doc = MockDocument(
                "file:///test.rpy",
                "call simple_label()\n"
            )
            mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
            mock_ls = MagicMock()
            mock_ls.workspace = mock_workspace

            params = lsp.SignatureHelpParams(
                text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy"),
                position=lsp.Position(line=0, character=20),
            )
            result = signature_help(mock_ls, params)

            assert result is not None
            assert len(result.signatures) >= 1
            # Should show simple_label() with no parameters
            sig = result.signatures[0]
            assert "simple_label" in sig.label
        finally:
            server_mod._active_analyzer = original_analyzer
            server_mod._is_initialized = original_init

    def test_signature_help_for_unknown_label(self):
        """`call nonexistent_label()` → returns None (label not found)."""
        from senpy.lsp.handlers.completion import signature_help
        from lsprotocol import types as lsp
        from senpy.lsp import server as server_mod

        mock_analyzer = MagicMock()
        mock_analyzer.labels = {}  # no labels
        mock_analyzer.screens = {}
        original_analyzer = server_mod._active_analyzer
        original_init = server_mod._is_initialized
        server_mod._active_analyzer = mock_analyzer
        server_mod._is_initialized = True

        try:
            mock_doc = MockDocument(
                "file:///test.rpy",
                "call nonexistent_label()\n"
            )
            mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
            mock_ls = MagicMock()
            mock_ls.workspace = mock_workspace

            params = lsp.SignatureHelpParams(
                text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy"),
                position=lsp.Position(line=0, character=25),
            )
            result = signature_help(mock_ls, params)
            assert result is None
        finally:
            server_mod._active_analyzer = original_analyzer
            server_mod._is_initialized = original_init

    def test_signature_help_active_parameter_tracking(self):
        """`call my_label(arg1, |arg2)` — cursor on 2nd param → activeParameter=1."""
        from senpy.lsp.handlers.completion import signature_help
        from lsprotocol import types as lsp
        from senpy.lsp import server as server_mod
        from senpy.core.symbols import LabelSymbol
        from senpy.core.signature import SignatureInfo

        mock_analyzer = MagicMock()
        mock_label = LabelSymbol(
            name="my_label",
            file_path="/test.rpy",
            line_number=1,
            code_line="label my_label(a, b, c):",
            signature=SignatureInfo(
                min_args=3,
                max_args=3,
                has_params=True,
                pos_names=["a", "b", "c"],
                required_names={"a", "b", "c"},
                all_names={"a", "b", "c"},
            ),
        )
        mock_analyzer.labels = {"my_label": mock_label}
        mock_analyzer.screens = {}
        original_analyzer = server_mod._active_analyzer
        original_init = server_mod._is_initialized
        server_mod._active_analyzer = mock_analyzer
        server_mod._is_initialized = True

        try:
            # call my_label(arg1, arg2) — cursor after the comma, before arg2
            mock_doc = MockDocument(
                "file:///test.rpy",
                "call my_label(arg1, arg2)\n"
            )
            mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
            mock_ls = MagicMock()
            mock_ls.workspace = mock_workspace

            # Find position of comma (between arg1 and arg2)
            line = mock_doc.lines[0]
            comma_pos = line.index(",")  # position of comma
            cursor_pos = comma_pos + 2  # after ", "

            params = lsp.SignatureHelpParams(
                text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy"),
                position=lsp.Position(line=0, character=cursor_pos),
            )
            result = signature_help(mock_ls, params)

            assert result is not None
            # activeParameter should be 1 (second parameter, 0-indexed)
            assert result.active_parameter == 1, (
                f"Expected active_parameter=1 (on 2nd param), got {result.active_parameter}"
            )
        finally:
            server_mod._active_analyzer = original_analyzer
            server_mod._is_initialized = original_init


# =============================================================================
# LSP-5: textDocument/prepareCallHierarchy
# =============================================================================


class TestPrepareCallHierarchyHandler:
    """LSP-5: prepareCallHierarchy returns CallHierarchyItem for label under cursor.

    Right-click on label → "Find Callers" / "Find References".
    First, VS Code calls prepareCallHierarchy to get a CallHierarchyItem.
    Then it calls callHierarchy/incomingCalls (callers) or
    callHierarchy/outgoingCalls (callees).
    """

    def test_prepare_call_hierarchy_function_exists(self):
        """prepare_call_hierarchy() must be importable from handlers."""
        from senpy.lsp.handlers.navigation import prepare_call_hierarchy
        assert callable(prepare_call_hierarchy)

    def test_prepare_call_hierarchy_returns_list(self):
        """prepare_call_hierarchy() returns list[CallHierarchyItem] (possibly empty)."""
        from senpy.lsp.handlers.navigation import prepare_call_hierarchy
        from lsprotocol import types as lsp
        from senpy.lsp import server as server_mod

        mock_analyzer = MagicMock()
        mock_analyzer.labels = {}
        original_analyzer = server_mod._active_analyzer
        original_init = server_mod._is_initialized
        server_mod._active_analyzer = mock_analyzer
        server_mod._is_initialized = True

        try:
            mock_doc = MockDocument(
                "file:///test.rpy",
                "label start:\n    return\n"
            )
            mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
            mock_ls = MagicMock()
            mock_ls.workspace = mock_workspace

            params = lsp.CallHierarchyPrepareParams(
                text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy"),
                position=lsp.Position(line=0, character=6),
            )
            result = prepare_call_hierarchy(mock_ls, params)
            assert isinstance(result, list)
        finally:
            server_mod._active_analyzer = original_analyzer
            server_mod._is_initialized = original_init

    def test_prepare_call_hierarchy_finds_label(self):
        """Cursor on `label start:` → returns CallHierarchyItem for 'start'."""
        from senpy.lsp.handlers.navigation import prepare_call_hierarchy
        from lsprotocol import types as lsp
        from senpy.lsp import server as server_mod
        from senpy.core.symbols import LabelSymbol

        mock_analyzer = MagicMock()
        mock_label = LabelSymbol(
            name="start",
            file_path="/test.rpy",
            line_number=1,
            code_line="label start:",
        )
        mock_analyzer.labels = {"start": mock_label}
        original_analyzer = server_mod._active_analyzer
        original_init = server_mod._is_initialized
        server_mod._active_analyzer = mock_analyzer
        server_mod._is_initialized = True

        try:
            mock_doc = MockDocument(
                "file:///test.rpy",
                "label start:\n    return\n"
            )
            mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc}, root_path="/")
            mock_ls = MagicMock()
            mock_ls.workspace = mock_workspace

            params = lsp.CallHierarchyPrepareParams(
                text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy"),
                position=lsp.Position(line=0, character=7),  # on "start"
            )
            result = prepare_call_hierarchy(mock_ls, params)

            assert len(result) >= 1, f"Expected 1 item, got {len(result)}"
            item = result[0]
            assert item.name == "start"
            assert item.kind == lsp.SymbolKind.Function  # labels are like functions
        finally:
            server_mod._active_analyzer = original_analyzer
            server_mod._is_initialized = original_init

    def test_prepare_call_hierarchy_returns_empty_for_non_label(self):
        """Cursor on a non-label word → returns empty list."""
        from senpy.lsp.handlers.navigation import prepare_call_hierarchy
        from lsprotocol import types as lsp
        from senpy.lsp import server as server_mod

        mock_analyzer = MagicMock()
        mock_analyzer.labels = {}
        original_analyzer = server_mod._active_analyzer
        original_init = server_mod._is_initialized
        server_mod._active_analyzer = mock_analyzer
        server_mod._is_initialized = True

        try:
            mock_doc = MockDocument(
                "file:///test.rpy",
                '    "This is dialogue"\n'
            )
            mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
            mock_ls = MagicMock()
            mock_ls.workspace = mock_workspace

            params = lsp.CallHierarchyPrepareParams(
                text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy"),
                position=lsp.Position(line=0, character=10),
            )
            result = prepare_call_hierarchy(mock_ls, params)
            assert result == []
        finally:
            server_mod._active_analyzer = original_analyzer
            server_mod._is_initialized = original_init


class TestIncomingCallsHandler:
    """LSP-5 part 2: callHierarchy/incomingCalls — who calls this label?

    Returns list[CallHierarchyIncomingCall], each containing:
        from: CallHierarchyItem (the caller label)
        fromRanges: list[Range] (where the call happens)
    """

    def test_incoming_calls_function_exists(self):
        """incoming_calls() must be importable from handlers."""
        from senpy.lsp.handlers.navigation import incoming_calls
        assert callable(incoming_calls)

    def test_incoming_calls_returns_list(self):
        """incoming_calls() returns list[CallHierarchyIncomingCall]."""
        from senpy.lsp.handlers.navigation import incoming_calls
        from lsprotocol import types as lsp
        from senpy.lsp import server as server_mod
        from senpy.core.symbols import LabelSymbol

        mock_analyzer = MagicMock()
        # 'target' is called by 'caller1' at line 5
        mock_analyzer.labels = {
            "target": LabelSymbol(name="target", file_path="/test.rpy", line_number=1, code_line="label target:"),
            "caller1": LabelSymbol(name="caller1", file_path="/test.rpy", line_number=5, code_line="label caller1:"),
        }
        mock_analyzer.jump_sources = {"target": [("/test.rpy", 5)]}
        original_analyzer = server_mod._active_analyzer
        original_init = server_mod._is_initialized
        server_mod._active_analyzer = mock_analyzer
        server_mod._is_initialized = True

        try:
            mock_ls = MagicMock()
            mock_ls.workspace = MockWorkspace({}, root_path="/")

            item = lsp.CallHierarchyItem(
                name="target",
                kind=lsp.SymbolKind.Function,
                uri="file:///test.rpy",
                range=lsp.Range(start=lsp.Position(0, 0), end=lsp.Position(0, 10)),
                selection_range=lsp.Range(start=lsp.Position(0, 6), end=lsp.Position(0, 12)),
            )
            params = lsp.CallHierarchyIncomingCallsParams(item=item)
            result = incoming_calls(mock_ls, params)

            assert isinstance(result, list)
            assert len(result) >= 1, f"Expected at least 1 incoming call, got {len(result)}"
            call = result[0]
            assert call.from_.name == "caller1"
        finally:
            server_mod._active_analyzer = original_analyzer
            server_mod._is_initialized = original_init


class TestOutgoingCallsHandler:
    """LSP-5 part 3: callHierarchy/outgoingCalls — where does this label jump/call to?

    Returns list[CallHierarchyOutgoingCall], each containing:
        to: CallHierarchyItem (the callee label)
        fromRanges: list[Range] (where the call happens in source label)
    """

    def test_outgoing_calls_function_exists(self):
        """outgoing_calls() must be importable from handlers."""
        from senpy.lsp.handlers.navigation import outgoing_calls
        assert callable(outgoing_calls)

    def test_outgoing_calls_returns_list(self):
        """outgoing_calls() returns list[CallHierarchyOutgoingCall]."""
        from senpy.lsp.handlers.navigation import outgoing_calls
        from lsprotocol import types as lsp
        from senpy.lsp import server as server_mod
        from senpy.core.symbols import LabelSymbol

        mock_analyzer = MagicMock()
        # 'source' calls 'dest1' and 'dest2'
        source_label = LabelSymbol(
            name="source",
            file_path="/test.rpy",
            line_number=1,
            code_line="label source:",
            outgoing_jumps={"dest1", "dest2"},
        )
        mock_analyzer.labels = {
            "source": source_label,
            "dest1": LabelSymbol(name="dest1", file_path="/test.rpy", line_number=10, code_line="label dest1:"),
            "dest2": LabelSymbol(name="dest2", file_path="/test.rpy", line_number=20, code_line="label dest2:"),
        }
        original_analyzer = server_mod._active_analyzer
        original_init = server_mod._is_initialized
        server_mod._active_analyzer = mock_analyzer
        server_mod._is_initialized = True

        try:
            mock_ls = MagicMock()
            mock_ls.workspace = MockWorkspace({}, root_path="/")

            item = lsp.CallHierarchyItem(
                name="source",
                kind=lsp.SymbolKind.Function,
                uri="file:///test.rpy",
                range=lsp.Range(start=lsp.Position(0, 0), end=lsp.Position(0, 10)),
                selection_range=lsp.Range(start=lsp.Position(0, 6), end=lsp.Position(0, 12)),
            )
            params = lsp.CallHierarchyOutgoingCallsParams(item=item)
            result = outgoing_calls(mock_ls, params)

            assert isinstance(result, list)
            assert len(result) >= 2, f"Expected 2 outgoing calls, got {len(result)}"
            callee_names = {call.to.name for call in result}
            assert "dest1" in callee_names
            assert "dest2" in callee_names
        finally:
            server_mod._active_analyzer = original_analyzer
            server_mod._is_initialized = original_init
