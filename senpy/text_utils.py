"""Senpy text utilities — functions with no dependencies on the analyzer.

Extracted into a separate module in Phase 1.3 (0.5.3) to break the circular
dependencies:
    - checkers.py → analyzer._strip_comment
    - flow.py → analyzer._strip_comment

Previously _strip_comment lived in analyzer.py, and checkers/flow did a lazy
import `from senpy.core.analyzer import _strip_comment` inside their methods. This
created a cycle (although through a runtime import, not a top-level one).

Now _strip_comment is in this module (senpy/text_utils.py), everyone depends
on it one-directionally:
    analyzer.py → senpy.text_utils
    checkers.py → senpy.text_utils
    flow.py → senpy.text_utils

For backward compatibility _strip_comment is re-exported from analyzer.py
(the old import `from senpy.core.analyzer import _strip_comment` keeps working).

Public API:
    _strip_comment(line: str) -> str
    suggest_similar(target, candidates, cutoff) -> str
"""

from __future__ import annotations

import difflib

from senpy.core.constants import SUGGESTION_CUTOFF


def _strip_comment(line: str) -> str:
    """Strips a comment (#) without breaking hex colors, escaped quotes (\\") and triple quotes.

    Algorithm:
    1. If '#' is not in the line — return as is.
    2. Walk character by character, tracking state:
       - Inside single/double quotes — '#' is not counted as a comment.
       - Inside triple quotes (''' or \"\"\") — same.
       - An escaped character (\\X) — skip 2 characters.
       - '#' outside strings — start of the comment, truncate.
    3. If we reached the end — the line has no comment, return as is.

    This matters for Ren'Py, where:
      - '#ffffff' — a hex color, not a comment
      - '"# not a comment"' — '#' inside a string, not a comment
      - 'label start: # comment' — '#' after code, a comment

    Args:
        line: The original line (may contain # anywhere).

    Returns:
        The line with the comment stripped (if there was one). Trailing spaces
        are left untouched — that's the caller's job.
    """
    if "#" not in line:
        return line

    in_quote = None
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "\\":
            i += 2
            continue
        if in_quote in ('"""', "'''"):
            if line[i : i + 3] == in_quote:
                in_quote = None
                i += 3
                continue
            i += 1
            continue
        if in_quote:
            if ch == in_quote:
                in_quote = None
            i += 1
            continue
        if line[i : i + 3] in ('"""', "'''"):
            in_quote = line[i : i + 3]
            i += 3
            continue
        if ch in ('"', "'"):
            in_quote = ch
            i += 1
            continue
        if ch == "#":
            return line[:i]
        i += 1
    return line


def suggest_similar(
    target: str,
    candidates: list[str] | set[str],
    cutoff: float = SUGGESTION_CUTOFF,
) -> str:
    """Return a "did you mean '...'?" hint string, or "" if no close match.

    Uses ``difflib.get_close_matches`` with ``n=1``. The cutoff threshold
    defaults to ``SUGGESTION_CUTOFF`` (0.6), but callers that need a stricter
    match (e.g. base-tag suggestion at 0.7) can pass their own.

    This replaces the old ``suggest_similar_symbol`` in ``text_tags.py``,
    which was hardcoded to 0.6 and only accepted ``set[str]``. The
    generalized version accepts any iterable of strings.

    Args:
        target: The misspelled / unknown identifier.
        candidates: The list or set of valid names to match against.
        cutoff: Minimum similarity ratio (0.0–1.0). Default 0.6.

    Returns:
        ``" (did you mean 'foo' ?)"`` if a match was found, ``""`` otherwise.
    """
    matches = difflib.get_close_matches(target, list(candidates), n=1, cutoff=cutoff)
    if matches:
        return f" (did you mean '{matches[0]}' ?)"
    return ""


def suggest_match(
    target: str,
    candidates: list[str] | set[str],
    cutoff: float = SUGGESTION_CUTOFF,
) -> str | None:
    """Return the closest match string, or None if no close match.

    Unlike ``suggest_similar`` (which returns a formatted hint string),
    this returns the raw match name — useful when the caller needs to
    build a QuickFix ``fix_replacement`` from the match.

    Args:
        target: The misspelled / unknown identifier.
        candidates: The list or set of valid names to match against.
        cutoff: Minimum similarity ratio (0.0–1.0). Default 0.6.

    Returns:
        The closest match string, or ``None`` if no match was found.
    """
    matches = difflib.get_close_matches(target, list(candidates), n=1, cutoff=cutoff)
    return matches[0] if matches else None
