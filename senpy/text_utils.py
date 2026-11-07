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
import textwrap

from senpy.core.constants import SUGGESTION_CUTOFF


def dedent_python(code: str) -> str:
    """Normalize line endings to LF and then ``textwrap.dedent``.

    ``textwrap.dedent`` has a long-standing limitation: it treats ``\\r``
    (carriage return) as a non-whitespace character when computing the
    common leading whitespace. On Windows, files opened with
    ``newline=""`` preserve ``\\r\\n`` line endings — the joined block
    lines carry ``\\r`` at the end of each line. When ``\\r``-only lines
    (the empty lines between code, which on CRLF are ``\\r\\n``) are
    split by ``\\n``, they become ``\\r``. ``textwrap.dedent`` sees the
    ``\\r`` as a non-whitespace character at column 0, sets the common
    margin to ``''``, and removes nothing — leaving the code indented
    and causing ``ast.parse`` to fail with "unexpected indent".

    This helper normalizes ``\\r\\n`` and lone ``\\r`` to ``\\n`` before
    calling ``textwrap.dedent``, so the dedent works correctly on all
    platforms regardless of how the file was opened.
    """
    return textwrap.dedent(code.replace("\r\n", "\n").replace("\r", "\n"))


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


def _has_unclosed_string(s: str) -> bool:
    """Returns True if ``s`` opens a triple-quoted or single-quoted
    string literal that is not closed within ``s``.

    Used by :func:`_get_logical_line` to detect multi-line string
    constructs that must be joined with subsequent physical lines
    before being fed to ``ast.parse``. Without this, a ``$`` statement
    that opens a triple-quoted string on one line and closes it on a
    later line would be parsed as just the first physical line,
    producing a false RPY110 "Python syntax error" because the
    triple-quoted string is unclosed on that single line.
    """
    in_quote: str | None = None
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
        i += 1
    return in_quote is not None


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

    # The line needs joining ONLY if there is an explicit '\' continuation
    # OR an unclosed bracket outside quotes. We do NOT check for an
    # unclosed string on the first line, because a line like
    # ``Not all good times must come to an end."""`` (which CLOSES a
    # triple-quoted string opened on a previous line) would be
    # incorrectly detected as opening a new string — causing the joiner
    # to swallow every subsequent line until it finds another ``"""``.
    # The string state is tracked CUMULATIVELY in the joining loop
    # below (via ``inside_string = _has_unclosed_string(joined_so_far)``),
    # which correctly handles the case where the first line opens a
    # string inside an open bracket (e.g. ``$ x = _p("""`` — the ``(``
    # triggers joining, and the loop's cumulative string tracking
    # extends the join through the closing ``"""`` and ``)``).
    if not ends_with_backslash and bracket_depth <= 0:
        return idx + 1, first_raw, first_clean

    raw_parts = [first_raw]
    clean_parts = [first_clean]
    curr_idx = idx
    # Compute the initial inside_string state from the first line. This
    # is correct because we only reach here if bracket_depth > 0 or
    # ends_with_backslash — meaning the line opens a construct that
    # requires joining. The string state computed here is the state
    # AFTER processing the first line. If the first line opens a
    # triple-quoted string (e.g. ``$ x = _p("""``), inside_string will
    # be True, and the loop will continue joining until the string
    # closes (cumulative tracking in the loop body).
    inside_string = _has_unclosed_string(first_clean)

    max_lookahead = 50  # Protection against infinite line swallowing
    lookahead_count = 0

    while curr_idx + 1 < len(lines):
        clean_stripped = clean_parts[-1].rstrip()
        ends_with_backslash = clean_stripped.endswith("\\")
        # Continue joining while: explicit '\' continuation, OR unclosed
        # bracket, OR we're inside a multi-line string literal. The string
        # case must be checked on the accumulated content so far — we
        # recompute it from the joined clean parts each iteration.
        if not ends_with_backslash and bracket_depth <= 0 and not inside_string:
            break

        lookahead_count += 1
        if lookahead_count > max_lookahead:
            break

        peek_raw = lines[curr_idx + 1]
        peek_clean = _strip_comment(peek_raw).strip()

        # Block boundary: if there is no explicit backslash '\', we are NOT
        # inside a multi-line string, and the next line is a new top-level
        # keyword construct (label, screen, init, define, default,
        # transform, image, style, layeredimage), force-stop so we don't
        # swallow another scene on a broken bracket. When inside a string,
        # lines starting with these keywords are just string content — not
        # real block boundaries.
        peek_indent = len(peek_raw) - len(peek_raw.lstrip(" "))
        if (
            not ends_with_backslash
            and not inside_string
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
        # Recompute bracket_depth and inside_string from the JOINED content
        # so far. Per-line accumulation is wrong here: ``_count_bracket_delta``
        # treats each line as starting outside any string, so a line that
        # closes a multi-line string opened earlier (e.g. ``""")``) would
        # have its ``)`` masked by what the per-line scan thinks is an
        # open triple-quoted string. Recomputing on the joined content
        # gives the correct cumulative state.
        joined_so_far = "".join(clean_parts)
        bracket_depth = _count_bracket_delta(joined_so_far)
        inside_string = _has_unclosed_string(joined_so_far)

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
