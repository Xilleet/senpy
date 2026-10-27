"""Whitespace rules: trailing-WS, EOF-newline, blank-lines.

FMT-TRAILING-WS: strip trailing whitespace from each line, preserve newline.
FMT-EOF-NEWLINE: ensure exactly one \\n at end of file (no more, no less).
FMT-BLANK-LINES: collapse 3+ consecutive blank lines to max_blank_lines (default 2).
                 Also strip leading blank lines at start of file.

Order: blank-lines → trailing-WS → EOF-newline (last).
"""

from __future__ import annotations

from senpy.formatter.core import FormatConfig, FormatContext, register_rule


@register_rule("FMT-BLANK-LINES")
def collapse_blank_lines(
    contexts: list[FormatContext], config: FormatConfig
) -> list[FormatContext]:
    """Collapse 3+ consecutive blank lines to max_blank_lines. Strip leading blanks."""
    result: list[FormatContext] = []
    blank_count = 0
    for ctx in contexts:
        if ctx.skip:
            result.append(ctx)
            continue
        # A line is "blank" if it's only whitespace + newline
        is_blank = ctx.raw.strip() == ""
        if is_blank:
            blank_count += 1
            if blank_count <= config.max_blank_lines:
                result.append(ctx)
            # else: skip (collapse)
        else:
            blank_count = 0
            result.append(ctx)
    # Strip leading blank lines at start of file
    while result and result[0].raw.strip() == "" and not result[0].skip:
        result.pop(0)
    return result


@register_rule("FMT-TRAILING-WS")
def strip_trailing_whitespace(
    contexts: list[FormatContext], config: FormatConfig
) -> list[FormatContext]:
    """Strip trailing whitespace from each line, preserving newline."""
    for ctx in contexts:
        if ctx.skip:
            continue
        raw = ctx.raw
        # Preserve line ending (\n or \r\n), strip spaces/tabs before it
        if raw.endswith("\r\n"):
            ctx.raw = raw.rstrip(" \t\r\n") + "\r\n"
        elif raw.endswith("\n"):
            ctx.raw = raw.rstrip(" \t\n") + "\n"
        else:
            # Last line without newline — strip trailing ws, FMT-EOF-NEWLINE will add \n
            ctx.raw = raw.rstrip(" \t")
    return contexts


@register_rule("FMT-EOF-NEWLINE")
def ensure_eof_newline(contexts: list[FormatContext], config: FormatConfig) -> list[FormatContext]:
    """Ensure exactly one \\n at end of file. Must be LAST rule."""
    if not contexts:
        return contexts
    last = contexts[-1]
    # Strip all trailing newlines, then add exactly one \n
    # (preserve \r\n if file was using CRLF — detect by checking if last non-empty
    # line ended with \r\n; for MVP we just use \n)
    last.raw = last.raw.rstrip("\r\n") + "\n"
    return contexts
