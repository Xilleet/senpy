"""FMT-QUOTES: smart/curly quotes → straight quotes in CODE statements.

Rule: in CODE lines (lines starting with $, python:, init python:, if/elif/else,
while/for, return, jump, call, etc.), replace smart/curly quotes with straight:

    “ ” → "       (U+201C, U+201D)
    ‘ ’ → '       (U+2018, U+2019)
    « » → "       (U+00AB, U+00BB) — Russian/French guillemets

Dialogue lines (first non-whitespace char is " or ') are PRESERVED — smart
quotes in dialogue are stylistic and should not be touched.

Skip: lines inside `# senpy: format off` blocks are NOT touched.
"""

from __future__ import annotations

from senpy.formatter.core import FormatConfig, FormatContext, register_rule

# Smart quote → straight quote mapping
_SMART_QUOTE_MAP = {
    "\u201c": '"',  # LEFT DOUBLE QUOTATION MARK
    "\u201d": '"',  # RIGHT DOUBLE QUOTATION MARK
    "\u2018": "'",  # LEFT SINGLE QUOTATION MARK
    "\u2019": "'",  # RIGHT SINGLE QUOTATION MARK
    "\u00ab": '"',  # LEFT-POINTING DOUBLE ANGLE QUOTATION MARK (guillemet «)
    "\u00bb": '"',  # RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK (guillemet »)
}

# Lines that are DIALOGUE (preserve smart quotes):
#   - First non-whitespace char is " or ' (Ren'Py dialogue convention)
#   - Empty/comment-only lines: not dialogue, but no smart quotes anyway
# We detect this by checking ctx.raw after indent stripping.


def _is_dialogue_line(raw: str) -> bool:
    """A line is dialogue if its first non-whitespace char is " or '.

    In Ren'Py, dialogue lines start with " or ' (single-line strings) — these
    are display text where smart quotes are stylistic.
    """
    stripped = raw.lstrip(" \t")
    if not stripped:
        return False
    return stripped[0] in ('"', "'")


@register_rule("FMT-QUOTES")
def normalize_quotes_in_code(
    contexts: list[FormatContext], config: FormatConfig
) -> list[FormatContext]:
    """Replace smart/curly quotes with straight quotes in code statements.

    Dialogue lines (starting with " or ') are PRESERVED.
    Skip blocks are NOT touched.
    """
    for ctx in contexts:
        if ctx.skip:
            continue
        # Dialogue lines preserve smart quotes (stylistic choice)
        if _is_dialogue_line(ctx.raw):
            continue
        # Code line: replace smart quotes
        new_raw = ctx.raw
        for smart, straight in _SMART_QUOTE_MAP.items():
            if smart in new_raw:
                new_raw = new_raw.replace(smart, straight)
        ctx.raw = new_raw
    return contexts
