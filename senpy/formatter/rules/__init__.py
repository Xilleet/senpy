"""Formatter rules. Each rule is a pure function decorated with @register_rule.

Importing this module registers all rules via side effect.
Rules are applied in import order (which is registration order).
"""

from __future__ import annotations

from senpy.formatter.rules import indent, whitespace  # noqa: F401
