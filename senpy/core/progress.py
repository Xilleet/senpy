"""Progress bar utilities for Senpy CLI.

Provides a single ``progress_print`` function for inline progress
indicators (e.g. "[1/2] Collecting symbols..."). The pattern
``print(msg.ljust(75), end="", flush=True)`` was duplicated in 4
places across ``analyzer.py`` and ``cli/unrpyc.py``.
"""

from __future__ import annotations


def progress_print(msg: str, width: int = 75) -> None:
    """Print a progress message inline, overwriting the previous line.

    The message is left-justified to ``width`` characters and printed
    with ``end=""`` and ``flush=True`` so the terminal shows it
    immediately without a newline (the next progress_print call will
    overwrite it via carriage return from the terminal).

    Args:
        msg: The progress message (e.g. "[1/2] Analyzing: script.rpy").
        width: Padding width in characters. Default 75.
    """
    print(msg.ljust(width), end="", flush=True)
