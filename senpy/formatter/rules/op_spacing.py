"""FMT-OP-SPACING: normalize spacing around binary operators in CODE statements.

Rule: in CODE lines (starting with $, python:, init python:, if/elif/else,
while/for, return, etc.), normalize spaces around binary operators:

    $ x=1+2     →  $ x = 1 + 2
    $ y =3*4-5  →  $ y = 3 * 4 - 5
    $ z+=1      →  $ z += 1

Unary operators are preserved (no space after):
    $ x = -5    →  $ x = -5   (NOT "$ x = - 5")
    $ y = +x    →  $ y = +x

String contents are NOT touched — spacing inside "..." or '...' is preserved.
Dialogue lines (first non-whitespace char is " or ') are NOT touched.

Skip: lines inside `# senpy: format off` blocks are NOT touched.

Operator list:
    = == != < > <= >=
    + - * / % // **
    += -= *= /= //= **= %=
    << >> & | ^ ~
    -> (arrow, Python 3.10+)

NOT touched (unary or non-binary-context):
    -5  +x  ~x  (unary minus/plus/tilde)
    ** (only when used as binary power, see _is_unary_position)
"""

from __future__ import annotations

import re

from senpy.formatter.core import FormatConfig, FormatContext, register_rule

# Binary operators (longest first, so ** matches before *).
# Each entry is a plain string (NOT raw) — re.escape() handles escaping.
# This prevents double-escaping when r"\+=" goes through re.escape().
_BINARY_OPS = [
    # Augmented assignments (longest first)
    "**=", "//=", ">>=", "<<=",
    "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=",
    # Comparison
    "==", "!=", "<=", ">=",
    # Shift / bitwise
    "<<", ">>",
    # Arithmetic
    "//", "**",
    "+", "-", "*", "/", "%",
    # Bitwise single
    "&", "|", "^",
    # Assignment (last — shortest)
    "=",
]

# Build a single regex that matches any binary op with surrounding whitespace.
# Pattern: (\S)\s*(OP)\s*(\S)  — needs non-space on both sides (binary, not unary).
# But this is naive — see _process_code_segment for the actual approach.

# For each binary op, build pattern: (non-space) (op with optional spaces) (non-space)
# Replacement: \1 OP \2 (single space around)
_OP_PATTERNS: list[tuple[re.Pattern, str]] = []
for op in _BINARY_OPS:
    # Match: (non-space char) (0+ spaces) (op) (0+ spaces) (non-space char)
    # Use lookahead/lookbehind to avoid consuming the boundary chars.
    # Negative lookbehind for start of string or another operator/space.
    # Pattern: (?<=\S)(\s*)(op)(\s*)(?=\S)
    # But we need to also handle "op" preceded by space (like x = 1) —
    # in that case we want exactly 1 space, not 0.
    #
    # Simpler approach: match the operator with surrounding whitespace,
    # require word char or ) ] } on left, word char or digit or ( [ { on right.
    # Replace with " OP " (single space).
    escaped_op = re.escape(op)
    pattern = re.compile(
        r"(?<=[\w\)\]\}])"   # left boundary: word char or closing bracket
        r"\s*"
        rf"({escaped_op})"   # the operator (escaped, captured)
        r"\s*"
        r"(?=[\w\(\'\"\{\[])"  # right boundary: word char, opening bracket, or quote
    )
    _OP_PATTERNS.append((pattern, op))


def _is_dialogue_line(raw: str) -> bool:
    """A line is dialogue if its first non-whitespace char is " or '."""
    stripped = raw.lstrip(" \t")
    if not stripped:
        return False
    return stripped[0] in ('"', "'")


def _process_code_segment(segment: str) -> str:
    """Apply binary operator spacing to a code segment (no strings/comments).

    Strategy: iterate over binary ops from longest to shortest. For each op,
    find all occurrences surrounded by valid boundaries, normalize to single
    space around.
    """
    result = segment
    for pattern, op in _OP_PATTERNS:
        # Replace each match: ensure exactly 1 space before and after op.
        # The pattern captures the op itself; surrounding whitespace is consumed
        # by lookbehind/lookahead (but not captured).
        # Use a function replacement to control spacing precisely.
        def _replace(match, op=op):
            return f" {op} "
        result = pattern.sub(_replace, result)
    return result


def _split_by_strings(line: str) -> list[tuple[str, bool]]:
    """Split a line into segments: (text, is_string).

    is_string=True means the segment is inside a string literal — NOT touched.
    is_string=False means it's code — operator spacing applies.

    Handles:
    - Double-quoted strings "..."
    - Single-quoted strings '...'
    - Triple-quoted strings \"\"\"...\"\"\" and '''...'''
    - Escape sequences \\" \\' \\\\ (don't end string)
    """
    segments: list[tuple[str, bool]] = []
    i = 0
    n = len(line)
    current_code = ""

    while i < n:
        ch = line[i]

        # Check for triple-quoted string
        if line[i:i + 3] in ('"""', "'''"):
            if current_code:
                segments.append((current_code, False))
                current_code = ""
            quote = line[i:i + 3]
            end = line.find(quote, i + 3)
            if end == -1:
                # Unterminated triple-quote — take rest of line
                segments.append((line[i:], True))
                i = n
            else:
                segments.append((line[i:end + 3], True))
                i = end + 3
            continue

        # Check for single/double-quoted string
        if ch in ('"', "'"):
            if current_code:
                segments.append((current_code, False))
                current_code = ""
            # Find matching close quote (respecting escapes)
            j = i + 1
            while j < n:
                if line[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if line[j] == ch:
                    break
                j += 1
            if j < n:
                segments.append((line[i:j + 1], True))
                i = j + 1
            else:
                # Unterminated string — take rest of line
                segments.append((line[i:], True))
                i = n
            continue

        # Regular code char
        current_code += ch
        i += 1

    if current_code:
        segments.append((current_code, False))

    return segments


@register_rule("FMT-OP-SPACING")
def normalize_operator_spacing(
    contexts: list[FormatContext], config: FormatConfig
) -> list[FormatContext]:
    """Normalize spacing around binary operators in code statements.

    - Binary operators get exactly 1 space on each side: x = 1 + 2
    - Unary operators preserved: x = -5 (NOT x = - 5)
    - String contents NOT touched
    - Dialogue lines (start with " or ') NOT touched
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
                new_parts.append(_process_code_segment(segment_text))
        ctx.raw = "".join(new_parts)
    return contexts
