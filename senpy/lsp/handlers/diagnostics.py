"""LSP handlers: diagnostics.

Вынесено из senpy/lsp/server.py в 0.6.0-7 (Фаза 5).

Handler'ы:
  - code_action        ← TEXT_DOCUMENT_CODE_ACTION
  - document_color     ← TEXT_DOCUMENT_DOCUMENT_COLOR (LSP-1, 0.6.0 Под-спринт 3)
  - color_presentation ← TEXT_DOCUMENT_COLOR_PRESENTATION (LSP-1)
  - formatting         ← TEXT_DOCUMENT_FORMATTING (LSP-2)
  - range_formatting   ← TEXT_DOCUMENT_RANGE_FORMATTING (LSP-2)

Все функции принимают (ls, params) и обращаются к shared state через
server_mod._X (lazy import разрывает цикл импортов).
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    try:
        from pygls.lsp.server import LanguageServer
    except ImportError:
        from pygls.server import LanguageServer

from lsprotocol import types as lsp


def _get_server_mod():
    """Ленивый доступ к senpy.lsp.server, разрывает цикл импортов."""
    from senpy.lsp import server
    return server


def code_action(ls: LanguageServer, params: lsp.CodeActionParams) -> list[lsp.CodeAction]:
    server_mod = _get_server_mod()
    actions: list[lsp.CodeAction] = []
    try:
        uri = params.text_document.uri
        # P0-6: единая нормализация через server_mod._normalize_path (с os.path.abspath),
        # как и во всех остальных местах. Раньше тут было os.path.normcase()
        # без abspath, из-за чего lookup промахивался и срабатывал
        # basename-fallback, который в multi-module проектах мог выбрать
        # QuickFix из неправильного файла.
        norm_path = server_mod._normalize_path(server_mod._uri_to_path(uri))

        diags_for_file = server_mod._latest_diagnostics_by_path.get(norm_path)
        # P0-6: basename-fallback УБРАН. Если diagnostics для файла не найдены
        # через точный путь — возвращаем пустой список, как и должно быть.
        # Если lookup промахивается, это баг в нормализации, его надо чинить
        # в server_mod._normalize_path, а не обходить небезопасным угадыванием по basename.
        if not diags_for_file:
            return actions

        cursor_start = params.range.start.line
        cursor_end = params.range.end.line
        context_codes = {d.code for d in (params.context.diagnostics or []) if d.code}

        for diag, lsp_diag in diags_for_file:
            diag_line = max(0, diag.line_number - 1)
            is_on_cursor_line = cursor_start <= diag_line <= cursor_end
            is_in_context = diag.code in context_codes

            if not (is_on_cursor_line or is_in_context):
                continue

            if not (diag.fix_title and diag.fix_replacement):
                continue

            fix_start = getattr(diag, "fix_start_col", None)
            fix_end = getattr(diag, "fix_end_col", None)

            if fix_start is not None and fix_end is not None:
                edit_range = lsp.Range(
                    start=lsp.Position(line=diag_line, character=fix_start),
                    end=lsp.Position(line=diag_line, character=fix_end),
                )
            elif diag.code == "RPY301":
                raw = diag.line_content
                q_pos = max(raw.rfind('"'), raw.rfind("'"))
                ins_char = (
                    len(raw[:q_pos].encode("utf-16-le")) // 2
                    if q_pos != -1
                    else lsp_diag.range.end.character
                )
                edit_range = lsp.Range(
                    start=lsp.Position(line=diag_line, character=ins_char),
                    end=lsp.Position(line=diag_line, character=ins_char),
                )
            else:
                edit_range = lsp_diag.range

            action = lsp.CodeAction(
                title=f"Senpy: {diag.fix_title}",
                kind=lsp.CodeActionKind.QuickFix,
                diagnostics=[lsp_diag],
                is_preferred=True,
                edit=lsp.WorkspaceEdit(
                    changes={
                        uri: [
                            lsp.TextEdit(
                                range=edit_range,
                                new_text=diag.fix_replacement,
                            )
                        ]
                    }
                ),
            )
            actions.append(action)

    except (KeyError, IndexError, ValueError, AttributeError) as e:
        ls.show_message_log(f"Error in code_action: {e}")

    return actions


# =============================================================================
# textDocument/documentColor + colorPresentation
# =============================================================================
# VS Code displays color swatches next to hex color literals. Clicking opens
# a color picker that updates the literal.
#
# Sources of colors in .rpy:
#   1. {color=#ffffff}text{/color} tags in dialogue
#   2. Solid("#ff0000") in screen definitions
#   3. Color("#00ff00") in transforms
#   4. Hex literals in init python: color = "#abcdef"
#
# Regex matches #rrggbb (6 digits) or #rrggbbaa (8 digits) hex colors.
# IMPORTANT: must NOT match inside # comments (those are not color literals).

# Match #rrggbb or #rrggbbaa (case-insensitive)
_RE_HEX_COLOR = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")


def _strip_comment(line: str) -> str:
    """Strip # comment, respecting quotes (so # inside "..." is not a comment)."""
    if "#" not in line:
        return line
    in_quote = None
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "\\":
            i += 2
            continue
        if in_quote:
            if ch == in_quote:
                in_quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            in_quote = ch
            i += 1
            continue
        if ch == "#":
            return line[:i]
        i += 1
    return line


def _hex_to_lsp_color(hex_str: str) -> lsp.Color:
    """Convert #rrggbb or #rrggbbaa to LSP Color (0.0-1.0 floats).

    Args:
        hex_str: hex color WITHOUT leading # (e.g. "ff0000" or "ff0000ff")

    Returns:
        lsp.Color with red/green/blue/alpha in 0.0-1.0 range.
    """
    if len(hex_str) == 6:
        r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
        a = 255
    else:  # 8 digits (rrggbbaa)
        r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
        a = int(hex_str[6:8], 16)
    return lsp.Color(
        red=r / 255.0,
        green=g / 255.0,
        blue=b / 255.0,
        alpha=a / 255.0,
    )


def _color_to_hex(color: lsp.Color, with_alpha: bool = False) -> str:
    """Convert LSP Color back to #rrggbb or #rrggbbaa hex string."""
    r = max(0, min(255, round(color.red * 255)))
    g = max(0, min(255, round(color.green * 255)))
    b = max(0, min(255, round(color.blue * 255)))
    a = max(0, min(255, round(color.alpha * 255)))
    if with_alpha:
        return f"#{r:02x}{g:02x}{b:02x}{a:02x}"
    return f"#{r:02x}{g:02x}{b:02x}"


def document_color(
    ls: LanguageServer, params: lsp.DocumentColorParams
) -> list[lsp.ColorInformation]:
    """LSP-1: Find all hex color literals in the document.

    Returns ColorInformation[] with range pointing to the #rrggbb literal
    and color as LSP Color object (0.0-1.0 floats).

    Skips # comments (those are not color literals).
    """
    uri = params.text_document.uri
    doc = ls.workspace.get_text_document(uri)
    if not doc or not doc.lines:
        return []

    result: list[lsp.ColorInformation] = []

    for line_idx, line in enumerate(doc.lines):
        # Strip comment first — colors inside # are NOT color literals
        code_part = _strip_comment(line)

        for match in _RE_HEX_COLOR.finditer(code_part):
            hex_str = match.group(1)  # without leading #
            color = _hex_to_lsp_color(hex_str)

            # Range: position of the # character
            start_char = match.start()  # position of #
            end_char = match.end()  # position after last hex digit

            result.append(lsp.ColorInformation(
                range=lsp.Range(
                    start=lsp.Position(line=line_idx, character=start_char),
                    end=lsp.Position(line=line_idx, character=end_char),
                ),
                color=color,
            ))

    return result


def color_presentation(
    ls: LanguageServer, params: lsp.ColorPresentationParams
) -> list[lsp.ColorPresentation]:
    """LSP-1 part 2: Convert a Color back to text representation.

    When user picks a new color in VS Code's color picker, VS Code calls
    this to get the text to insert. We return the hex format matching
    what was originally in the file.
    """
    color = params.color

    # Detect if original had alpha (8 digits) or not (6 digits)
    # We can't know from params alone, so we return both options:
    # the #rrggbb version (most common) and #rrggbbaa (if alpha != 1.0)
    presentations: list[lsp.ColorPresentation] = []

    if abs(color.alpha - 1.0) < 0.005:
        # No alpha — use #rrggbb
        hex_str = _color_to_hex(color, with_alpha=False)
        presentations.append(lsp.ColorPresentation(label=hex_str))
    else:
        # Has alpha — use #rrggbbaa
        hex_str = _color_to_hex(color, with_alpha=True)
        presentations.append(lsp.ColorPresentation(label=hex_str))

    return presentations


# =============================================================================
# textDocument/formatting + rangeFormatting
# =============================================================================
# Integrates senpy.formatter (from Под-спринт 1) into VS Code.
# Shift+Alt+F in VS Code calls formatting() to format the whole document.
# Ctrl+K Ctrl+F calls range_formatting() for selected range only.

def formatting(
    ls: LanguageServer, params: lsp.DocumentFormattingParams
) -> list[lsp.TextEdit]:
    """LSP-2: Format the entire document using Senpy formatter.

    Returns list[TextEdit]. If no changes needed, returns empty list.
    Otherwise returns single TextEdit replacing whole document with
    formatted version.
    """
    from senpy.formatter import FormatConfig, Formatter

    uri = params.text_document.uri
    doc = ls.workspace.get_text_document(uri)
    if not doc:
        return []

    original = doc.source
    fmt = Formatter(FormatConfig())
    formatted = fmt.format_code(original, filename=uri)

    # If no changes, return empty list
    if formatted == original:
        return []

    # Replace whole document
    line_count = len(original.splitlines())
    return [
        lsp.TextEdit(
            range=lsp.Range(
                start=lsp.Position(line=0, character=0),
                end=lsp.Position(line=line_count, character=0),
            ),
            new_text=formatted,
        )
    ]


def range_formatting(
    ls: LanguageServer, params: lsp.DocumentRangeFormattingParams
) -> list[lsp.TextEdit]:
    """LSP-2 part 2: Format selected range only.

    For MVP, we format the whole document and return a single TextEdit
    replacing the entire file. This is acceptable — VS Code applies the
    edit and the user sees the formatted result. Proper range-only
    formatting is complex (need to preserve indentation context outside
    the range) and is a stretch goal.
    """
    from senpy.formatter import FormatConfig, Formatter

    uri = params.text_document.uri
    doc = ls.workspace.get_text_document(uri)
    if not doc:
        return []

    original = doc.source
    fmt = Formatter(FormatConfig())
    formatted = fmt.format_code(original, filename=uri)

    if formatted == original:
        return []

    line_count = len(original.splitlines())
    return [
        lsp.TextEdit(
            range=lsp.Range(
                start=lsp.Position(line=0, character=0),
                end=lsp.Position(line=line_count, character=0),
            ),
            new_text=formatted,
        )
    ]
