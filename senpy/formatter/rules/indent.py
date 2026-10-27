"""FMT-INDENT: tab → spaces, normalize mixed tab/space indents.

Rule: convert all leading whitespace to spaces, rounded down to
multiple of config.indent_size (default 4).

Examples:
    \\t"Hello"  →  4 spaces + "Hello"
    \\t\\t$ x = 1  →  8 spaces + $ x = 1
      \\t"Mixed"  →  4 spaces + "Mixed" (2 spaces + 1 tab = 4 after expandtabs(4))
    3 spaces + "x"  →  0 spaces + "x" (3 < 4, rounds down to 0)

Skip: lines inside `# senpy: format off` blocks are NOT touched.
"""

from __future__ import annotations

from senpy.formatter.core import FormatConfig, FormatContext, register_rule


@register_rule("FMT-INDENT")
def normalize_indent(contexts: list[FormatContext], config: FormatConfig) -> list[FormatContext]:
    """Normalize leading whitespace: tab → spaces, round down to indent_size."""
    for ctx in contexts:
        if ctx.skip:
            continue
        raw = ctx.raw
        stripped = raw.lstrip(" \t")
        leading = raw[: len(raw) - len(stripped)]
        leading_expanded = leading.expandtabs(config.indent_size)
        n_spaces = len(leading_expanded)
        normalized_count = (n_spaces // config.indent_size) * config.indent_size
        ctx.raw = " " * normalized_count + stripped
        ctx.indent = normalized_count
    return contexts
