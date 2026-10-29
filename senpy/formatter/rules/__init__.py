"""Formatter rules. Each rule is a pure function decorated with @register_rule.

Importing this module registers all rules via side effect.
Rules are applied in import order (which is registration order).

Order matters (see senpy/formatter/core.py module docstring for full rationale):
1. FMT-INDENT — tab → spaces, must be first (other rules rely on indent)
2. FMT-BLANK-LINES — collapse before strip
3. FMT-TRAILING-WS — strip trailing whitespace
4. FMT-QUOTES — smart quotes → straight (code only, not dialogue)
5. FMT-OP-SPACING — binary operators
6. FMT-COMMA-SPACING — after commas
7. FMT-COLON-SPACING — before colons
8. FMT-EOF-NEWLINE — final newline (must be last)
"""

from __future__ import annotations

# Import order = registration order = application order.
# Do NOT reorder without updating tests + module docstring above.
from senpy.formatter.rules import (  # noqa: F401
    colon_spacing,
    comma_spacing,
    indent,
    op_spacing,
    quotes,
    whitespace,
)
