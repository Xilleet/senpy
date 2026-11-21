"""Progress bar utilities for Senpy CLI.

Provides a single ``progress_print`` function for inline progress
indicators (e.g. "[1/2] Collecting symbols..."). The pattern
``print(msg.ljust(75), end="", flush=True)`` was duplicated in 4
places across ``analyzer.py`` and ``cli/unrpyc.py``.
"""

from __future__ import annotations

import os
import sys


def progress_print(msg: str, width: int = 75) -> None:
    """Print a progress message inline, overwriting the previous line.

    The message is left-justified to ``width`` characters and printed
    with ``end=""`` and ``flush=True`` so the terminal shows it
    immediately without a newline (the next progress_print call will
    overwrite it via carriage return from the terminal).

    **LSP guard**: this function writes to stdout. In LSP mode stdout
    is the JSON-RPC transport — any stray byte corrupts the protocol
    and the editor drops the connection. We detect LSP mode via the
    ``SENPY_LSP=1`` environment variable (set by ``senpy/lsp/server.py``
    at startup) and silently no-op when set. This is defense-in-depth:
    ``progress_print`` is currently only called from CLI code paths,
    but a future plugin or test that imports the helper in LSP
    context must not break the protocol.

    Args:
        msg: The progress message (e.g. "[1/2] Analyzing: script.rpy").
        width: Padding width in characters. Default 75.
    """
    if os.environ.get("SENPY_LSP") == "1":
        return
    # Belt-and-suspenders: if stdout is not a TTY (piped, redirected,
    # or captured by an LSP transport that didn't set SENPY_LSP), skip
    # too — progress bars only make sense in an interactive terminal.
    if not sys.stdout.isatty():
        return
    print(msg.ljust(width), end="", flush=True)
