"""Helper: simulate LSP TextEdit application for tests.

The QuickFix contract (per `senpy/lsp/handlers/diagnostics.py:code_action`):
    - If both `fix_start_col` and `fix_end_col` are set on the Diagnostic,
      the LSP edit range is `[diag_line, fix_start_col) .. [diag_line, fix_end_col)`.
    - Special-case RPY301 inserts at a position derived from the line.
    - Otherwise the LSP edit range falls back to `lsp_diag.range`, which
      `_create_lsp_diagnostic` computes as:
          if diag.end_col > diag.col:  [col, end_col)
          else:                        [indent, end_of_line)

This helper mirrors that fallback chain so tests can assert what the
user actually sees when they click "Senpy: <fix_title>" in VS Code.

The helper does not depend on LSP types — it works on plain Python strings
so it is fast and dependency-free.
"""

from __future__ import annotations


def _utf16_len(s: str) -> int:
    """Length of `s` in UTF-16 code units (what LSP character offsets count)."""
    return len(s.encode("utf-16-le")) // 2


def compute_lsp_edit_range(  # noqa: PLR0911 — branches mirror the LSP handler
    line: str,
    col: int,
    end_col: int,
    fix_start_col: int | None,
    fix_end_col: int | None,
    code: str,
) -> tuple[int, int]:
    """Return (start_char, end_char) — UTF-16 offsets on `line` — that the
    LSP `code_action` handler would compute for a Diagnostic with these
    fields. The range is what `TextEdit.range` will cover.

    Mirrors `senpy/lsp/handlers/diagnostics.py:code_action` lines 75-96 +
    `senpy/lsp/server.py:_create_lsp_diagnostic` lines 317-325.
    """
    if fix_start_col is not None and fix_end_col is not None:
        return fix_start_col, fix_end_col
    if code == "RPY301":
        # Insertion at the closing quote of the dialogue string.
        q_pos = max(line.rfind('"'), line.rfind("'"))
        ins_char = _utf16_len(line[:q_pos]) if q_pos != -1 else _utf16_len(line)
        return ins_char, ins_char
    # Fallback to lsp_diag.range, computed by _create_lsp_diagnostic.
    if end_col > col:
        return col, end_col
    raw_text = line
    indent = len(raw_text) - len(raw_text.lstrip())
    start_char = _utf16_len(raw_text[:indent])
    end_char = max(start_char + 1, _utf16_len(raw_text.rstrip()))
    return start_char, end_char


def apply_lsp_text_edit(
    line: str,
    replacement: str,
    start_char: int,
    end_char: int,
) -> str:
    """Apply an LSP `TextEdit` to `line` and return the resulting string.

    LSP character offsets are UTF-16 code unit counts, not Python code
    points. The helper converts back to Python indices before splicing.
    """
    # Convert UTF-16 offsets back to Python str indices by walking the
    # encoded form. This mirrors what an LSP editor does internally.
    encoded = line.encode("utf-16-le")
    start_byte = start_char * 2
    end_byte = end_char * 2
    if start_byte > len(encoded):
        start_byte = len(encoded)
    if end_byte > len(encoded):
        end_byte = len(encoded)
    if start_byte > end_byte:
        end_byte = start_byte
    prefix = encoded[:start_byte].decode("utf-16-le")
    suffix = encoded[end_byte:].decode("utf-16-le")
    return prefix + replacement + suffix


def apply_quickfix_to_line(
    line: str,
    *,
    code: str,
    col: int,
    end_col: int,
    fix_replacement: str,
    fix_start_col: int | None,
    fix_end_col: int | None,
) -> str:
    """Simulate the user clicking the QuickFix in VS Code.

    Returns the resulting text. For single-line replacements this is a
    single line; for insertions that contain newlines it is a multi-line
    string (exactly what the editor would produce).
    """
    start_char, end_char = compute_lsp_edit_range(
        line=line,
        col=col,
        end_col=end_col,
        fix_start_col=fix_start_col,
        fix_end_col=fix_end_col,
        code=code,
    )
    return apply_lsp_text_edit(line, fix_replacement, start_char, end_char)
