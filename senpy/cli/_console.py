"""Shared Rich Console instance for CLI output.

Extracted from ``senpy.cli.main`` in 0.7.7 to break the circular import
``senpy.cli.format_dispatch -> senpy.cli.main -> senpy.cli.format_dispatch``
caught by ``scripts/check_cycles.py``.

The cycle was introduced when ``format_dispatch`` started importing
``console`` from ``main`` to route its styled output through Rich.
``main`` already lazily imports ``format_dispatch`` inside
``_dispatch_format`` (the back-compat wrapper), so the edge
``main -> format_dispatch`` exists statically even though the runtime
import is deferred. Adding the reverse edge ``format_dispatch -> main``
closed the cycle.

Moving ``console`` (and the stream reconfiguration that must run before
it is constructed) into this third module lets both ``main`` and
``format_dispatch`` depend on a leaf module with no senpy.cli.* imports
of its own. The import graph becomes:

    senpy.cli.main            -> senpy.cli._console
    senpy.cli.format_dispatch -> senpy.cli._console
    senpy.cli._console        -> (rich, stdlib only)

``main`` keeps its ``_ReplaceConsole`` context manager and its
``global console`` rebinding — the ``console`` name imported here is a
module-level binding in ``main``, so ``global console`` in
``_ReplaceConsole.__enter__`` / ``__exit__`` still rebinds ``main``'s
local binding, exactly as before. Modules that import ``console`` from
``_console`` (e.g. ``format_dispatch``) keep their own binding and are
not affected by the swap — which is correct, because ``senpy format``
never runs inside the ``--output-file`` redirect block that uses
``_ReplaceConsole``.
"""

from __future__ import annotations

import sys

from rich.console import Console

# Pipes (VS Code extension, >file, CI) always receive utf-8: the default
# Windows pipe encoding is locale (cp1251) -> UnicodeEncodeError on ✔/(//∇//)
# and mojibake for Cyrillic (Node decodes the pipe as utf8). Interactive
# console is not touched: rich writes through WriteConsoleW there (Unicode-safe).
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and not _stream.isatty() and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

# The Windows legacy renderer in rich crashes on a stdout pipe (WriteConsoleW on
# an invalid handle): disable it when the output is not an interactive terminal.
# In a live console (isatty=True) the behavior is unchanged.
console = Console(legacy_windows=sys.stdout.isatty())

__all__ = ["console"]
