"""Tests for 0.6.0 Под-спринт 3 (Заход 1): LSP killer-features.

LSP-1: textDocument/documentColor + textDocument/colorPresentation
       Hex colors (#ffffff, #ff0000ff) in .rpy as color swatches in VS Code.
       Killer feature for VN — lots of colors in {color=#...} tags and Solid("#...").

LSP-2: textDocument/formatting + textDocument/rangeFormatting
       Integrate formatter (from Под-спринт 1) into VS Code via LSP.
       Now Shift+Alt+F in VS Code formats .rpy files through Senpy.

Architecture follows existing pattern:
- server.py: thin @server.feature dispatchers (like folding_range, document_highlight)
- handlers/<name>.py: actual implementation
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# =============================================================================
# Mock helpers (reuse from test_lsp.py — minimal versions for this test file)
# =============================================================================


class MockDocument:
    """Minimal mock of pygls TextDocument for testing."""

    def __init__(self, uri: str, source: str):
        self.uri = uri
        self._source = source
        # Split into lines, preserve newlines
        self.lines = source.splitlines(keepends=True)

    @property
    def source(self) -> str:
        return self._source

    def __len__(self) -> int:
        return len(self.lines)


class MockWorkspace:
    """Minimal mock of pygls Workspace."""

    def __init__(self, documents: dict[str, MockDocument] | None = None,
                 root_path: str | None = None):
        self._documents = documents or {}
        self.root_path = root_path

    def get_text_document(self, uri: str) -> MockDocument | None:
        return self._documents.get(uri)


# =============================================================================
# LSP-1: textDocument/documentColor
# =============================================================================


class TestDocumentColorHandler:
    """LSP-1: documentColor handler returns ColorInformation[] for hex colors.

    VS Code displays color swatches next to color literals. Clicking opens
    a color picker that updates the literal.

    Sources of colors in .rpy:
        1. {color=#ffffff}text{/color} tags in dialogue
        2. Solid("#ff0000") in screen definitions
        3. Color("#00ff00") in transforms
        4. Hex literals in init python: color = "#abcdef"

    Returns ColorInformation[] with:
        range: position of the color literal (UTF-16, like all LSP ranges)
        color: LSP Color object (red, green, blue, alpha — all 0.0-1.0)
    """

    def test_document_color_function_exists(self):
        """document_color() function must be importable from handlers."""
        from senpy.lsp.handlers.diagnostics import document_color
        assert callable(document_color)

    def test_document_color_returns_list(self):
        """document_color() returns a list (possibly empty)."""
        from senpy.lsp.handlers.diagnostics import document_color
        from lsprotocol import types as lsp

        mock_doc = MockDocument(
            "file:///test.rpy",
            'label start:\n    "Hello"\n    return\n'  # no colors
        )
        mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
        mock_ls = MagicMock()
        mock_ls.workspace = mock_workspace

        params = lsp.DocumentColorParams(
            text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy")
        )
        result = document_color(mock_ls, params)
        assert isinstance(result, list)

    def test_document_color_finds_hex_color_in_dialogue_tag(self):
        """{color=#ff0000} in dialogue → ColorInformation with red=1.0."""
        from senpy.lsp.handlers.diagnostics import document_color
        from lsprotocol import types as lsp

        mock_doc = MockDocument(
            "file:///test.rpy",
            'label start:\n    "Hello {color=#ff0000}world{/color}!"\n    return\n'
        )
        mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
        mock_ls = MagicMock()
        mock_ls.workspace = mock_workspace

        params = lsp.DocumentColorParams(
            text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy")
        )
        result = document_color(mock_ls, params)

        assert len(result) >= 1, f"Expected at least 1 color, got {len(result)}"
        color_info = result[0]
        assert hasattr(color_info, "range")
        assert hasattr(color_info, "color")
        # #ff0000 = red 255, green 0, blue 0, alpha 255
        # LSP Color uses 0.0-1.0 floats
        assert abs(color_info.color.red - 1.0) < 0.01, f"Red should be 1.0, got {color_info.color.red}"
        assert abs(color_info.color.green - 0.0) < 0.01
        assert abs(color_info.color.blue - 0.0) < 0.01
        # alpha defaults to 1.0 if not specified
        assert abs(color_info.color.alpha - 1.0) < 0.01

    def test_document_color_finds_solid_color_call(self):
        """Solid("#00ff00") in screen → ColorInformation with green=1.0."""
        from senpy.lsp.handlers.diagnostics import document_color
        from lsprotocol import types as lsp

        mock_doc = MockDocument(
            "file:///test.rpy",
            'screen test():\n    add Solid("#00ff00")\n'
        )
        mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
        mock_ls = MagicMock()
        mock_ls.workspace = mock_workspace

        params = lsp.DocumentColorParams(
            text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy")
        )
        result = document_color(mock_ls, params)

        assert len(result) >= 1
        green_info = next(
            (ci for ci in result if abs(ci.color.green - 1.0) < 0.01),
            None
        )
        assert green_info is not None, "Expected a green color (#00ff00) in results"

    def test_document_color_handles_alpha_channel(self):
        """#ff0000ff (8 hex digits, last = alpha) → alpha=1.0."""
        from senpy.lsp.handlers.diagnostics import document_color
        from lsprotocol import types as lsp

        mock_doc = MockDocument(
            "file:///test.rpy",
            'label start:\n    "Test {color=#ff0000ff}text{/color}"\n'
        )
        mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
        mock_ls = MagicMock()
        mock_ls.workspace = mock_workspace

        params = lsp.DocumentColorParams(
            text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy")
        )
        result = document_color(mock_ls, params)

        assert len(result) >= 1
        # alpha=ff = 1.0
        assert abs(result[0].color.alpha - 1.0) < 0.01

    def test_document_color_handles_half_alpha(self):
        """#ff000080 (alpha=80=128) → alpha=128/255≈0.502."""
        from senpy.lsp.handlers.diagnostics import document_color
        from lsprotocol import types as lsp

        mock_doc = MockDocument(
            "file:///test.rpy",
            'label start:\n    "Test {color=#ff000080}text{/color}"\n'
        )
        mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
        mock_ls = MagicMock()
        mock_ls.workspace = mock_workspace

        params = lsp.DocumentColorParams(
            text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy")
        )
        result = document_color(mock_ls, params)

        assert len(result) >= 1
        # alpha=80 hex = 128 decimal = 128/255 ≈ 0.502
        assert abs(result[0].color.alpha - 0.502) < 0.01

    def test_document_color_skips_comments(self):
        """#ffffff in a # comment should NOT be detected as color."""
        from senpy.lsp.handlers.diagnostics import document_color
        from lsprotocol import types as lsp

        mock_doc = MockDocument(
            "file:///test.rpy",
            '# This is a comment with #ffffff in it\nlabel start:\n    "Hi"\n'
        )
        mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
        mock_ls = MagicMock()
        mock_ls.workspace = mock_workspace

        params = lsp.DocumentColorParams(
            text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy")
        )
        result = document_color(mock_ls, params)

        # Should find 0 colors (the #ffffff in comment is not a color literal)
        assert result == [], f"Comment #ffffff should not be detected as color: {result}"

    def test_document_color_range_points_to_color_literal(self):
        """ColorInformation.range should point to the #ffffff literal itself,
        not the surrounding tag or string."""
        from senpy.lsp.handlers.diagnostics import document_color
        from lsprotocol import types as lsp

        mock_doc = MockDocument(
            "file:///test.rpy",
            '    "Hello {color=#ff0000}world{/color}!"\n'
        )
        mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
        mock_ls = MagicMock()
        mock_ls.workspace = mock_workspace

        params = lsp.DocumentColorParams(
            text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy")
        )
        result = document_color(mock_ls, params)

        assert len(result) >= 1
        color_info = result[0]
        # Range start should be at the # character of #ff0000
        line_idx = color_info.range.start.line
        start_char = color_info.range.start.character
        end_char = color_info.range.end.character

        # Extract the matched text from the line
        line_text = mock_doc.lines[line_idx]
        matched_text = line_text[start_char:end_char]
        assert matched_text == "#ff0000", (
            f"Range should point to '#ff0000', got {matched_text!r}"
        )

    def test_document_color_handles_multiple_colors_in_file(self):
        """Multiple colors in file → multiple ColorInformation entries."""
        from senpy.lsp.handlers.diagnostics import document_color
        from lsprotocol import types as lsp

        mock_doc = MockDocument(
            "file:///test.rpy",
            'label start:\n'
            '    "Red {color=#ff0000}R{/color}"\n'
            '    "Green {color=#00ff00}G{/color}"\n'
            '    "Blue {color=#0000ff}B{/color}"\n'
            '    return\n'
        )
        mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
        mock_ls = MagicMock()
        mock_ls.workspace = mock_workspace

        params = lsp.DocumentColorParams(
            text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy")
        )
        result = document_color(mock_ls, params)

        assert len(result) == 3, f"Expected 3 colors, got {len(result)}"
        # Each color should be different
        reds = [ci for ci in result if abs(ci.color.red - 1.0) < 0.01]
        greens = [ci for ci in result if abs(ci.color.green - 1.0) < 0.01]
        blues = [ci for ci in result if abs(ci.color.blue - 1.0) < 0.01]
        assert len(reds) == 1
        assert len(greens) == 1
        assert len(blues) == 1


class TestColorPresentationHandler:
    """LSP-1 part 2: colorPresentation returns ColorPresentation[] for edits.

    When user picks a new color in VS Code's color picker, VS Code calls
    colorPresentation to get the text representation of the new color.

    For Senpy, we return the new color as "#rrggbb" or "#rrggbbaa" format,
    matching what was originally in the file.
    """

    def test_color_presentation_function_exists(self):
        from senpy.lsp.handlers.diagnostics import color_presentation
        assert callable(color_presentation)

    def test_color_presentation_returns_list(self):
        """color_presentation() returns list[ColorPresentation]."""
        from senpy.lsp.handlers.diagnostics import color_presentation
        from lsprotocol import types as lsp

        mock_doc = MockDocument(
            "file:///test.rpy",
            '    "Test {color=#ff0000}text{/color}"\n'
        )
        mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
        mock_ls = MagicMock()
        mock_ls.workspace = mock_workspace

        params = lsp.ColorPresentationParams(
            text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy"),
            color=lsp.Color(red=1.0, green=0.0, blue=0.0, alpha=1.0),
            range=lsp.Range(
                start=lsp.Position(line=0, character=18),  # position of #ff0000
                end=lsp.Position(line=0, character=25),
            ),
        )
        result = color_presentation(mock_ls, params)
        assert isinstance(result, list)
        assert len(result) >= 1
        # The label should be the hex color string
        presentation = result[0]
        assert hasattr(presentation, "label")
        assert "#ff0000" in presentation.label.lower()


# =============================================================================
# LSP-2: textDocument/formatting + rangeFormatting
# =============================================================================


class TestFormattingHandler:
    """LSP-2: textDocument/formatting integrates Senpy formatter into VS Code.

    VS Code calls this on Shift+Alt+F ("Format Document").
    Returns TextEdit[] that replaces the entire document with formatted version.

    Uses senpy.formatter.Formatter (from Под-спринт 1) to format the code.
    """

    def test_formatting_function_exists(self):
        """formatting() function must be importable from handlers."""
        from senpy.lsp.handlers.diagnostics import formatting
        assert callable(formatting)

    def test_formatting_returns_list_of_text_edits(self):
        """formatting() returns list[TextEdit] (possibly empty if no changes)."""
        from senpy.lsp.handlers.diagnostics import formatting
        from lsprotocol import types as lsp

        # Already-formatted code → no changes needed → empty list
        mock_doc = MockDocument(
            "file:///test.rpy",
            'label start:\n    "Hello"\n    return\n'
        )
        mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
        mock_ls = MagicMock()
        mock_ls.workspace = mock_workspace

        params = lsp.DocumentFormattingParams(
            text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy"),
            options=lsp.FormattingOptions(tab_size=4, insert_spaces=True),
        )
        result = formatting(mock_ls, params)
        assert isinstance(result, list)

    def test_formatting_fixes_indentation(self):
        """Tab-indented code → TextEdit replacing with 4-space indented code."""
        from senpy.lsp.handlers.diagnostics import formatting
        from lsprotocol import types as lsp

        # Code with tabs (should be 4 spaces)
        mock_doc = MockDocument(
            "file:///test.rpy",
            'label start:\n\t"Hello"\n\treturn\n'  # tabs, not spaces
        )
        mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
        mock_ls = MagicMock()
        mock_ls.workspace = mock_workspace

        params = lsp.DocumentFormattingParams(
            text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy"),
            options=lsp.FormattingOptions(tab_size=4, insert_spaces=True),
        )
        result = formatting(mock_ls, params)

        # Should return at least 1 TextEdit
        assert len(result) >= 1, "Expected TextEdit for tab→spaces fix"
        # The edit should replace the whole document (simpler approach)
        # OR contain individual edits. We accept either, just check it's non-empty.
        edit = result[0]
        assert hasattr(edit, "range")
        assert hasattr(edit, "new_text")

    def test_formatting_fixes_smart_quotes_in_code(self):
        """Smart quotes in code → TextEdit with straight quotes."""
        from senpy.lsp.handlers.diagnostics import formatting
        from lsprotocol import types as lsp

        mock_doc = MockDocument(
            "file:///test.rpy",
            '$ status = \u201cactive\u201d\n'  # smart quotes in code
        )
        mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
        mock_ls = MagicMock()
        mock_ls.workspace = mock_workspace

        params = lsp.DocumentFormattingParams(
            text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy"),
            options=lsp.FormattingOptions(tab_size=4, insert_spaces=True),
        )
        result = formatting(mock_ls, params)

        # Should produce an edit (smart quotes need fixing)
        assert len(result) >= 1
        # Check that new_text contains straight quotes (not smart)
        all_new_text = "".join(e.new_text for e in result)
        assert "\u201c" not in all_new_text, "Smart quote should be replaced"
        assert "\u201d" not in all_new_text

    def test_formatting_preserves_dialogue_smart_quotes(self):
        """Smart quotes in dialogue (line starts with ") should be PRESERVED."""
        from senpy.lsp.handlers.diagnostics import formatting
        from lsprotocol import types as lsp

        mock_doc = MockDocument(
            "file:///test.rpy",
            '    "She said \u201chello\u201d to him."\n'  # dialogue with smart quotes
        )
        mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
        mock_ls = MagicMock()
        mock_ls.workspace = mock_workspace

        params = lsp.DocumentFormattingParams(
            text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy"),
            options=lsp.FormattingOptions(tab_size=4, insert_spaces=True),
        )
        result = formatting(mock_ls, params)

        # If there are edits, they should NOT replace the smart quotes in dialogue
        if result:
            all_new_text = "".join(e.new_text for e in result)
            # Smart quotes should still be there (dialogue preserves them)
            assert "\u201c" in all_new_text or "\u201c" not in "".join(
                mock_doc.lines[line] if 0 <= line < len(mock_doc.lines) else ""
                for line in range(len(mock_doc.lines))
            ), "Dialogue smart quotes should be preserved"

    def test_formatting_idempotent(self):
        """Already-formatted code → no TextEdits (or empty list)."""
        from senpy.lsp.handlers.diagnostics import formatting
        from lsprotocol import types as lsp
        from senpy.formatter import Formatter, FormatConfig

        # Format once to get clean version
        fmt = Formatter(FormatConfig())
        clean_code = fmt.format_code('label start:\n\t"Hello"\n\treturn\n')

        mock_doc = MockDocument("file:///test.rpy", clean_code)
        mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
        mock_ls = MagicMock()
        mock_ls.workspace = mock_workspace

        params = lsp.DocumentFormattingParams(
            text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy"),
            options=lsp.FormattingOptions(tab_size=4, insert_spaces=True),
        )
        result = formatting(mock_ls, params)

        # Already formatted → no changes needed → empty list OR
        # TextEdit that replaces whole doc with identical content.
        # We accept both, but if non-empty, the new_text should equal original.
        if result:
            new_content = result[0].new_text
            # If it's a whole-document replace, new_content should == clean_code
            assert new_content == clean_code, (
                "Already-formatted code should not produce different edits"
            )


class TestRangeFormattingHandler:
    """LSP-2 part 2: textDocument/rangeFormatting formats selected range only.

    VS Code calls this on Ctrl+K Ctrl+F ("Format Selection").
    Currently we accept the handler exists; full range formatting is a
    stretch goal (can return same as formatting() for now — format whole doc).
    """

    def test_range_formatting_function_exists(self):
        """range_formatting() function must be importable from handlers."""
        from senpy.lsp.handlers.diagnostics import range_formatting
        assert callable(range_formatting)

    def test_range_formatting_returns_list(self):
        """range_formatting() returns list[TextEdit] (possibly empty)."""
        from senpy.lsp.handlers.diagnostics import range_formatting
        from lsprotocol import types as lsp

        mock_doc = MockDocument(
            "file:///test.rpy",
            'label start:\n    "Hello"\n    return\n'
        )
        mock_workspace = MockWorkspace({"file:///test.rpy": mock_doc})
        mock_ls = MagicMock()
        mock_ls.workspace = mock_workspace

        params = lsp.DocumentRangeFormattingParams(
            text_document=lsp.TextDocumentIdentifier(uri="file:///test.rpy"),
            range=lsp.Range(
                start=lsp.Position(line=0, character=0),
                end=lsp.Position(line=2, character=0),
            ),
            options=lsp.FormattingOptions(tab_size=4, insert_spaces=True),
        )
        result = range_formatting(mock_ls, params)
        assert isinstance(result, list)
