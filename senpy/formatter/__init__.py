"""Senpy formatter — opinionated .rpy code formatter (Black-style).

Philosophy: separate from lint (which finds errors), formatter
unifies style. Idempotent, low-risk, Ren'Py-specific.

MVP (0.5.0): 3 rules
- FMT-INDENT: tab → 4 spaces, normalize mixed tab/space indents
- FMT-TRAILING-WS: strip trailing whitespace
- FMT-EOF-NEWLINE: ensure exactly one \\n at end of file

Plus FMT-BLANK-LINES: collapse 3+ consecutive blank lines to 2.

Architecture (see canonical-report Part 3):
    Formatter.format_code(code) → str
        ↓
    1. Build FormatContext per line (scope detection)
    2. Apply rules in order (each rule is pure function)
    3. Emit formatted text

Skip directives:
    # senpy: format off
    ... (not touched)
    # senpy: format on

    $ x = 1   # senpy: format skip   (single line)

Idempotency contract: format(format(x)) == format(x)
This is tested in tests/test_formatter_idempotency.py.
"""

from __future__ import annotations

from senpy.formatter import rules  # noqa: F401  — registers rules via @register_rule
from senpy.formatter.core import (
    FormatConfig,
    FormatContext,
    Formatter,
    register_rule,
)

__all__ = ["Formatter", "FormatConfig", "FormatContext", "register_rule"]
