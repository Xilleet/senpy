"""Senpy formatter — opinionated .rpy code formatter (Black-style).
...docstring...
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
