"""FMT-COLON-SPACING: remove space before colons that open blocks.

Rule: in CODE statements, normalize colon spacing:
    if x :        →  if x:
    def f() :     →  def f():
    label start : →  label start:
    menu :        →  menu:

Colons NOT touched:
    - Dict literal colons: {1:2} — no space anyway, formatter shouldn't add
    - Slice colons: a[1:2] — no space
    - String contents: 'a:b' — preserved
    - Dialogue lines (start with " or '): NOT touched
    - Skip blocks: NOT touched

Block-opening colons are detected by context: they appear after:
    - if/elif/else conditions
    - def function signatures
    - label declarations
    - menu keyword
    - python/init python blocks
    - for/while loops
    - with/try/except/finally
    - class declarations
    - Ren'Py screen declarations

Simplification: we just match " :" before newline OR before #comment, when
the line is not dialogue. This catches the common case "if x :" → "if x:".
"""

from __future__ import annotations

import re

from senpy.formatter.core import FormatConfig, FormatContext, register_rule
from senpy.formatter.rules.op_spacing import _split_by_strings, _is_dialogue_line

# Pattern: space before colon, where colon is followed by end-of-line or # comment.
# Match: (non-space) (one or more spaces) (:) (end of line OR # comment)
# Replace: \1: (no space before colon)
# Use lookahead to check what's after colon.
_RE_SPACE_BEFORE_COLON = re.compile(
    r"(?<=\S)"        # left: non-space char (the word before colon)
    r"\s+"            # one or more spaces
    r":"              # the colon
    r"(?=\s*$|\s*#)"  # right: end of line (with optional comment) — block opener
)


@register_rule("FMT-COLON-SPACING")
def normalize_colon_spacing(
    contexts: list[FormatContext], config: FormatConfig
) -> list[FormatContext]:
    """Remove space before colons that open blocks (if x : → if x:).

    - " :" before block opener (end of line or comment): removed
    - Dict colons {a:1}: NOT touched (no space before anyway)
    - Slice colons a[1:2]: NOT touched (no space before anyway)
    - String contents NOT touched
    - Dialogue lines NOT touched
    - Skip blocks NOT touched
    """
    for ctx in contexts:
        if ctx.skip:
            continue
        if _is_dialogue_line(ctx.raw):
            continue

        # Split line by string literals — only process code segments
        segments = _split_by_strings(ctx.raw)
        new_parts = []
        for segment_text, is_string in segments:
            if is_string:
                new_parts.append(segment_text)
            else:
                # Remove space before block-opening colon
                segment_text = _RE_SPACE_BEFORE_COLON.sub(":", segment_text)
                new_parts.append(segment_text)
        ctx.raw = "".join(new_parts)
    return contexts
