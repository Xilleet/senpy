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
    strip_string_literals(line: str) -> str
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


def strip_string_literals(line: str) -> str:
    """Mask the *content* of string literals with spaces, preserving column positions.

    Returns a copy of ``line`` where every character inside a ``"..."`` or
    ``'...'`` literal is replaced with a space (one space per source
    character). The quote characters themselves, escape backslashes, and
    every character outside string literals are preserved verbatim.

    Why this exists:
        Several checkers do a substring check or regex scan on an
        arbitrary Ren'Py line and accidentally match text that lives
        inside a string literal — dialogue text, Python string constants,
        image names. This produces false positives where a diagnostic
        fires on a line like ``"The Jump('foo') action is documented
        here."`` or ``text "Press Show('x') to continue."``.

        Applying this helper before the substring check guarantees that
        literal contents are invisible to the matcher, while column
        positions of code outside literals stay intact (so ``_get_utf16_range``
        on the masked line still returns correct offsets for code tokens).

    Contract:
        - Length of the returned string equals length of the input.
        - Quote characters and escape backslashes are preserved.
        - An unclosed literal is handled defensively: every character
          from the opening quote to end of line is masked, no exception.
        - Triple-quoted strings (``\"\"\"``, ``'''``) are recognised.
        - A line with no quotes is returned unchanged (cheap fast-path).

    Args:
        line: A single Ren'Py source line (already comment-stripped is
            fine — comments are not affected by this helper).

    Returns:
        The line with literal contents replaced by spaces.

    Examples:
        >>> strip_string_literals('jump start')
        'jump start'
        >>> strip_string_literals('action Jump("foo")')
        'action Jump("   ")'
        >>> strip_string_literals('e "Use renpy.jump() here."')
        'e "                       "'
    """
    if '"' not in line and "'" not in line:
        return line

    out = list(line)
    n = len(line)
    in_quote: str | None = None
    i = 0
    while i < n:
        ch = line[i]
        if ch == "\\":
            # Escaped char: keep both backslash and the next char verbatim.
            i += 2
            continue
        if in_quote in ('"""', "'''"):
            if line[i : i + 3] == in_quote:
                # Closing triple quote — preserve the quote chars, exit literal.
                in_quote = None
                i += 3
                continue
            # Inside triple-quoted literal — mask with space, preserve newline.
            if ch != "\n":
                out[i] = " "
            i += 1
            continue
        if in_quote:
            if ch == in_quote:
                # Closing single quote — preserve, exit literal.
                in_quote = None
                i += 1
                continue
            # Inside single-quoted literal — mask with space, preserve newline.
            if ch != "\n":
                out[i] = " "
            i += 1
            continue
        # Not inside a literal.
        if line[i : i + 3] in ('"""', "'''"):
            in_quote = line[i : i + 3]
            i += 3
            continue
        if ch in ('"', "'"):
            in_quote = ch
            i += 1
            continue
        i += 1
    # If in_quote is still set here, the literal was unclosed — every char
    # between the opening quote and end of line has already been masked
    # in the loop above. That is the documented defensive behaviour.
    return "".join(out)


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


def _count_bracket_delta(s: str) -> int:
    """Counts the bracket balance of (, [, { outside string literals."""
    if not any(c in s for c in "()[]{}"):
        return 0

    delta = 0
    in_quote = None
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "\\":
            i += 2
            continue
        if in_quote in ('"""', "'''"):
            if s[i : i + 3] == in_quote:
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
        if s[i : i + 3] in ('"""', "'''"):
            in_quote = s[i : i + 3]
            i += 3
            continue
        if ch in ('"', "'"):
            in_quote = ch
            i += 1
            continue
        if ch in "([{":
            delta += 1
        elif ch in ")]}":
            delta -= 1
        i += 1
    return delta


def _get_logical_line(lines: list[str], idx: int) -> tuple[int, str, str]:
    """
    Joins multi-line constructs (line continuation via '\\' or unclosed brackets).
    Returns (next_idx, raw_line, clean_line).
    Fault-tolerant: prevents cascading file swallowing on unclosed brackets.
    """
    first_raw = lines[idx]
    first_clean = _strip_comment(first_raw)
    stripped = first_clean.strip()

    bracket_depth = _count_bracket_delta(first_clean)
    ends_with_backslash = stripped.endswith("\\")

    # The line needs joining ONLY if there is an explicit '\' continuation or an unclosed bracket outside quotes
    if not ends_with_backslash and bracket_depth <= 0:
        return idx + 1, first_raw, first_clean

    raw_parts = [first_raw]
    clean_parts = [first_clean]
    curr_idx = idx

    max_lookahead = 50  # Protection against infinite line swallowing
    lookahead_count = 0

    while curr_idx + 1 < len(lines):
        clean_stripped = clean_parts[-1].rstrip()
        ends_with_backslash = clean_stripped.endswith("\\")
        if not ends_with_backslash and bracket_depth <= 0:
            break

        lookahead_count += 1
        if lookahead_count > max_lookahead:
            break

        peek_raw = lines[curr_idx + 1]
        peek_clean = _strip_comment(peek_raw).strip()

        # Block boundary: if there is no explicit backslash '\', and the next line is
        # a new top-level keyword construct (label, screen, init, define, default, transform, image, style, layeredimage),
        # force-stop so we don't swallow another scene on a broken bracket.
        peek_indent = len(peek_raw) - len(peek_raw.lstrip(" "))
        if (
            not ends_with_backslash
            and peek_indent == 0
            and peek_clean.startswith(
                (
                    "label ",
                    "screen ",
                    "init ",
                    "define ",
                    "default ",
                    "transform ",
                    "image ",
                    "style ",
                    "layeredimage ",
                )
            )
        ):
            break

        curr_idx += 1
        next_raw = lines[curr_idx]
        next_clean = _strip_comment(next_raw)

        raw_parts.append(next_raw)
        clean_parts.append(next_clean)
        bracket_depth += _count_bracket_delta(next_clean)

    if len(raw_parts) == 1:
        return idx + 1, first_raw, first_clean

    cleaned_tokens = []
    for p in clean_parts:
        c = p.strip()
        if c.endswith("\\"):
            c = c[:-1].strip()
        if c:
            cleaned_tokens.append(c)

    indent = len(clean_parts[0]) - len(clean_parts[0].lstrip())
    joined_clean = (" " * indent) + " ".join(cleaned_tokens)
    return curr_idx + 1, "".join(raw_parts), joined_clean
