"""Formatter rules. Each rule is a pure function decorated with @register_rule.

Importing this module registers all rules via side effect.
Rules are applied in import order (which is registration order).
"""

from __future__ import annotations

# Import order MATTERS — rules are applied in registration order:
# 1. FMT-INDENT (tab → spaces) — must be first, other rules rely on indent
# 2. FMT-BLANK-LINES — collapse before strip
# 3. FMT-TRAILING-WS — strip trailing whitespace
# 4. FMT-EOF-NEWLINE — ensure final newline (must be last)
from senpy.formatter.rules import indent, whitespace  # noqa: F401
