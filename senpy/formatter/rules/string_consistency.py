"""FMT-STRING-CONSISTENCY: normalize quote style of string literals in CODE.

Rule: in CODE lines (lines that are not dialogue), normalize the outer
quotes of single-line string literals to a consistent style:

    string_style = "double" (default, Ren'Py convention):
        $ x = 'hi'    →  $ x = "hi"
    string_style = "single":
        $ x = "hi"    →  $ x = 'hi'
    string_style = "preserve":
        no changes

NOT touched:
  - Dialogue lines (first non-whitespace char is ' or ")
  - Triple-quoted strings (\"\"\"...\"\"\" and '''...''')
  - Strings where conversion would require escaping the new outer
    quote inside the body (e.g. 'he said \"hi\"' has an unescaped
    double quote → can't safely convert to double-quoted without
    escaping the inner quote; we leave it alone for idempotency).
  - Lines inside `# senpy: format off` blocks.

Idempotency: the rule is idempotent because after one pass every
convertible string is already in the target style. Strings that were
skipped (due to inner quotes) stay skipped — their inner quotes
haven't changed.
"""

from __future__ import annotations

from senpy.formatter.core import FormatConfig, FormatContext, register_rule
from senpy.formatter.rules.op_spacing import _is_dialogue_line, _split_by_strings


def _has_unescaped(body: str, ch: str) -> bool:
    """True if `body` contains an unescaped occurrence of `ch`.

    Escaped = preceded by a backslash that is itself not escaped.
    """
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if c == "\\" and i + 1 < n:
            i += 2  # skip the escaped char
            continue
        if c == ch:
            return True
        i += 1
    return False


def _convert_string_literal(literal: str, target: str) -> str:
    """Convert a single-line string literal to the target quote style.

    `literal` is the full literal including the outer quotes
    (e.g. ``\"'hi'\"``). `target` is ``\"\"`` or ``\"'\"``.

    Returns the converted literal, or the original if conversion is
    unsafe (string has an unescaped target quote inside, or is a
    triple-quoted string, or is empty).
    """
    if len(literal) < 2:
        return literal
    # Skip triple-quoted strings.
    if literal[:3] in ('"""', "'''"):
        return literal
    open_q = literal[0]
    close_q = literal[-1]
    if open_q != close_q or open_q not in ('"', "'"):
        return literal  # not a string we recognize
    body = literal[1:-1]
    # If the body already contains an unescaped target quote, converting
    # would require escaping it — that breaks idempotency (the escaped
    # form would survive a second pass). Leave alone.
    if _has_unescaped(body, target):
        return literal
    if open_q == target:
        return literal  # already in target style
    return target + body + target


def _normalize_line(line: str, target: str | None) -> str:
    """Apply string-consistency to one code line.

    `target` is the desired outer quote (\" or '), or None for preserve.
    The line is split into (segment, is_string) pairs via _split_by_strings;
    only string segments are rewritten, and only single-line non-triple
    literals are converted.
    """
    if target is None:
        return line
    segments = _split_by_strings(line)
    out = []
    for text, is_string in segments:
        if not is_string:
            out.append(text)
            continue
        # The string segment is the full literal including quotes (or
        # the rest-of-line for unterminated strings). _convert_string_literal
        # handles single-line literals; anything else passes through.
        out.append(_convert_string_literal(text, target))
    return "".join(out)


@register_rule("FMT-STRING-CONSISTENCY")
def normalize_string_consistency(
    contexts: list[FormatContext], config: FormatConfig
) -> list[FormatContext]:
    """Normalize outer quotes of single-line string literals in code lines.

    - Default (string_style='double'): 'x' → \"x\" in code lines.
    - Dialogue lines (start with ' or \") are NOT touched.
    - Triple-quoted strings are NOT touched.
    - Strings with an unescaped target quote inside are NOT touched
      (would require escaping, breaking idempotency).
    - Skip blocks (# senpy: format off) are NOT touched.
    """
    if config.string_style == "preserve":
        return contexts
    target = '"' if config.string_style == "double" else "'"

    for ctx in contexts:
        if ctx.skip:
            continue
        if _is_dialogue_line(ctx.raw):
            continue
        new_raw = _normalize_line(ctx.raw, target)
        if new_raw != ctx.raw:
            ctx.raw = new_raw
    return contexts
