"""FMT-COMMA-SPACING: ensure exactly one space after each comma in code.

Rule: in CODE statements, normalize comma spacing:
    f(a,b,c)       →  f(a, b, c)
    [1,2,3]        →  [1, 2, 3]
    {1:2,3:4}      →  {1:2, 3:4}
    f(a, b, c)     →  f(a, b, c)   (already correct, idempotent)
    f(a,)          →  f(a,)        (trailing comma kept, no space added)

String contents are NOT touched — commas inside "..." or '...' are preserved.
Dialogue lines (first non-whitespace char is " or ') are NOT touched.
Skip blocks are NOT touched.
"""

from __future__ import annotations

import re

from senpy.formatter.core import FormatConfig, FormatContext, register_rule
from senpy.formatter.rules.op_spacing import _is_dialogue_line, _split_by_strings

# Pattern: comma followed by 0+ spaces, then a non-space, non-newline, non-close-bracket char.
# Replace with: ", " (comma + single space).
# Trailing comma before ) ] } or newline: leave as-is (no space added).
# Use lookahead to avoid consuming the next char.
_RE_COMMA_NO_SPACE = re.compile(
    r",(?=\S)"        # comma immediately followed by non-space (no space after)
)
# But we need to NOT add space before ) ] } (closing brackets) — those are fine without space.
# Actually, Ren'Py/Python convention: f(a,) → f(a,) (no space before close paren).
# So: if comma is followed by ) ] } — leave as-is (no space added).
# Pattern: comma followed by closing bracket OR end of line — leave alone.
# Pattern: comma followed by other non-space char (word, quote, opening bracket) — add space.

_RE_COMMA_NEEDS_SPACE = re.compile(
    r",(?=[\w\'\"\(\[\{])"  # comma followed by word char, quote, or opening bracket
)


@register_rule("FMT-COMMA-SPACING")
def normalize_comma_spacing(
    contexts: list[FormatContext], config: FormatConfig
) -> list[FormatContext]:
    """Ensure exactly one space after each comma in code segments.

    - Comma followed by non-space char (word, quote, opening bracket): add space
    - Comma followed by space: leave (idempotent)
    - Comma followed by ) ] } or newline: leave (no space)
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
                # Add space after comma where needed
                segment_text = _RE_COMMA_NEEDS_SPACE.sub(", ", segment_text)
                new_parts.append(segment_text)
        ctx.raw = "".join(new_parts)
    return contexts
