"""Shared helpers for LSP navigation handlers.

Extracted from senpy/lsp/handlers/navigation.py.
Contains: _get_server_mod, _word_at_position, _location_at_symbol_line,
_find_text_occurrences_in_project, _get_ignored_dirs, occurrence predicates,
_filter_occurrences_by_kind.

Used by: definition.py, references.py, rename.py, call_hierarchy.py.
"""

from __future__ import annotations

import os
import re

from lsprotocol import types as lsp

_WORD_BOUNDARY_TEMPLATE = r"(?<![A-Za-z0-9_])({})(?![A-Za-z0-9_])"


def _get_server_mod():
    """Lazy access to senpy.lsp.server, breaks the import cycle.

    All accesses to shared state (_active_analyzer, _is_initialized, ...)
    go through server_mod = _get_server_mod() at the start of each function.
    """
    from senpy.lsp import server

    return server


def _word_at_position(line: str, col: int) -> str | None:
    r"""Return the dotted-identifier at the given column (regex `[^\W\d][\w\.]*`)."""
    for m in re.finditer(r"[^\W\d][\w\.]*", line):
        if m.start() <= col <= m.end():
            return m.group(0)
    return None


def _location_at_symbol_line(server_mod, sym, name_length: int) -> lsp.Location:
    """Build a `lsp.Location` for a symbol declaration at its line + column 0.

    `name_length` is the length of the identifier to highlight (used as
    the end character of the range — start is always column 0).

    The line number is 1-based in the symbol table, 0-based in LSP —
    we subtract 1, clamping to 0 to avoid negative positions.
    """
    decl_line = max(0, sym.line_number - 1)
    return lsp.Location(
        uri=server_mod._path_to_uri(sym.file_path),
        range=lsp.Range(
            start=lsp.Position(line=decl_line, character=0),
            end=lsp.Position(line=decl_line, character=name_length),
        ),
    )


def _find_text_occurrences_in_project(server_mod, word: str) -> list[tuple[str, int, int]]:
    """Find all text occurrences of `word` as a whole-word in all .rpy files of the project.

    Returns a list of (file_path, line_idx_0based, col_utf16).

    Used for rename/references of variables/transforms/screens, which do not
    have a reverse index (unlike labels with jump_sources).

    NB: May catch false positives in string literals and comments
    (e.g., `$ x = 'player_gold'`). This is a trade-off — accurate analysis would
    require AST traversal of all .rpy files, which is slow. For rename/references
    text search is acceptable: the user sees all occurrences and can cancel.
    """
    # Phase 3.3c-e: state via _lsp_server.<attr>.
    lsp_server = server_mod._lsp_server
    if lsp_server.active_analyzer is None:
        return []

    project_path = lsp_server.active_analyzer.project_path
    occurrences: list[tuple[str, int, int]] = []
    pattern = re.compile(_WORD_BOUNDARY_TEMPLATE.format(re.escape(word)))

    for root, _, files in os.walk(project_path, followlinks=False):
        # Skip internal directories
        dirs_skip = [d for d in _get_ignored_dirs() if d in root.split(os.sep)]
        if dirs_skip:
            continue
        for fname in files:
            if not fname.endswith(".rpy"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except OSError:
                continue

            for line_idx, line in enumerate(lines):
                for m in re.finditer(pattern, line):
                    col_utf16 = len(line[: m.start()].encode("utf-16-le")) // 2
                    occurrences.append((fpath, line_idx, col_utf16))

    return occurrences


def _get_ignored_dirs() -> set[str]:
    """List of directories that should not be traversed."""
    from senpy.core.constants import IGNORED_DIRS

    return set(IGNORED_DIRS) if IGNORED_DIRS else {".senpy_cache", "tl", "cache"}


def _is_variable_occurrence(line: str, col: int, word_len: int) -> bool:
    """Decide if the whole-word match at ``line[col:col+word_len]`` is a
    real variable reference, not a label declaration, jump target, or
    natural-language mention in dialogue.

    A match is a real variable reference when one of these holds:

      1. The line starts with ``$`` (a single-line Python statement) and
         the match is after the ``$`` prefix — e.g. ``$ score = 100``.
      2. The line is inside a ``python:`` block (heuristic: the line
         starts with ``$ `` OR is a Python-looking assignment / expression
         at body indent — we accept any line that does NOT match the
         other categories below).
      3. The match is inside a Ren'Py string interpolation
         ``[var]`` — i.e. the character immediately before the match
         is ``[`` or the match is preceded by a word boundary inside
         a quoted string AND the character after is ``]`` or ``[``.

    A match is NOT a variable reference when:

      * The line is a label declaration: starts with ``label `` and the
        match is the label name (followed by ``:`` or `` (``).
      * The line is a jump/call statement: starts with ``jump `` or
        ``call `` and the match is the target.
      * The line is a screen declaration: starts with ``screen ``.
      * The line is a transform declaration: starts with ``transform ``.
      * The match lives inside a plain dialogue string and is NOT part
        of a ``[var]`` interpolation — i.e. natural-language mention.

    The function is conservative: when in doubt, it returns ``True``
    (keep the edit) so that legitimate variable renames are not lost.
    The false-positive cases above are the explicit ones the contract
    forbids.
    """
    stripped = line.lstrip()
    indent = len(line) - len(stripped)
    # Local position of the match within the stripped line.
    local_col = col - indent
    if local_col < 0:
        local_col = 0

    # 1. Label / screen / transform declarations — match the declared name.
    #    Examples: `label score:`, `screen score():`, `transform score:`.
    for kw in ("label ", "screen ", "transform "):
        if stripped.startswith(kw):
            # Declaration line — never rename variables here, regardless
            # of where the match is on the line.
            return False

    # 2. Jump / call statement — the target is a label, not a variable.
    if stripped.startswith("jump ") or stripped.startswith("call "):
        # The match is the jump/call target — never rename variables here.
        return False

    # 3. `show screen X` / `call screen X` — screen reference, not variable.
    if stripped.startswith("show screen ") or stripped.startswith("call screen "):
        return False

    # 4. `use X` inside a screen — screen reference, not variable.
    if stripped.startswith("use "):
        return False

    # 5. Show / scene statements with `at`/`with`/`as` — transform refs.
    #    `show bg at score` would rename a transform `score`, not a variable.
    #    But this is a false positive only for variable rename; transform
    #    rename is allowed. We approximate: if the line is a `show`/`scene`
    #    statement and the match is in the `at`/`with` clause, treat as
    #    not-a-variable.
    if stripped.startswith(("show ", "scene ")):
        # Check if `at`/`with` appears BEFORE the match position.
        prefix = stripped[:local_col]
        if " at " in prefix or " with " in prefix or " as " in prefix:
            return False

    # 6. String interpolation `[var]` — IS a variable reference.
    #    `"...Your score is [score]."` — keep.
    #
    # We detect this by scanning FORWARD from the line start: track
    # whether we are inside a quoted string, and inside `[...]` interpolation
    # within that string. If the match starts inside `[...]`, keep it.
    in_string: str | None = None
    in_interp = False
    i = 0
    while i < col:
        ch = line[i]
        if in_string:
            if ch == "\\":
                # Skip the next char (escape sequence).
                i += 2
                continue
            if in_interp:
                if ch == "]":
                    in_interp = False
                i += 1
                continue
            if ch == "[":
                in_interp = True
                i += 1
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue
        if ch in ('"', "'"):
            in_string = ch
            in_interp = False
        i += 1
    if in_interp:
        # The match starts inside a `[...]` interpolation — IS a variable reference.
        return True

    # If we are inside a string but NOT in interpolation, the match is a
    # natural-language mention — drop it.
    if in_string is not None:
        return False

    # 7. Plain dialogue line (starts with `"` or `e "..."`) — match is
    #    natural-language mention, NOT interpolation (case 6 handled it).
    #    This catches dialogue whose opening quote is on an earlier line
    #    (multi-line dialogue) — for those `in_string` would be True
    #    after the scan and we'd return False above. Here we catch the
    #    degenerate case where the match is on a line that does NOT
    #    contain a quote at all (e.g. a continuation line of a triple-
    #    quoted string). We approximate: if the line starts with `"` or
    #    `e "`-style speaker prefix, treat as dialogue.
    is_dialogue = stripped.startswith(('"', "'")) or bool(
        re.match(r'^[A-Za-z_]\w*\s+["\']', stripped)
    )
    return not is_dialogue


def _is_transform_occurrence(line: str, col: int, word_len: int) -> bool:
    """Decide if a whole-word match is a transform reference, not a
    variable, label, or screen.

    Transform references appear:
      - In `show`/`scene` statements after `at` / `with` / `as`.
      - As the declared name in `transform X:`.
      - Inside `at X(...)` chains.

    Conservative: when in doubt, return ``True``.
    """
    stripped = line.lstrip()
    indent = len(line) - len(stripped)
    local_col = max(0, col - indent)

    # `transform X:` declaration — IS a transform occurrence.
    if stripped.startswith("transform ") and local_col >= len("transform "):
        return True

    # `show ... at X` / `with X` / `as X` — IS a transform occurrence.
    if stripped.startswith(("show ", "scene ")):
        prefix = stripped[:local_col]
        if " at " in prefix or " with " in prefix or " as " in prefix:
            return True

    # Label / jump / screen declarations — NOT transform occurrences.
    if stripped.startswith(("label ", "screen ", "jump ", "call ", "use ")):
        return False

    # Plain dialogue — NOT a transform occurrence.
    return not (
        stripped.startswith(('"', "'")) or bool(re.match(r'^[A-Za-z_]\w*\s+["\']', stripped))
    )


def _is_screen_occurrence(line: str, col: int, word_len: int) -> bool:
    """Decide if a whole-word match is a screen reference, not a
    variable, label, or transform.

    Screen references appear:
      - In `use X(...)` statements.
      - In `show screen X` / `call screen X`.
      - In `Show("X")` / `ShowMenu("X")` / `Hide("X")` screen actions.

    Conservative: when in doubt, return ``True``.
    """
    stripped = line.lstrip()
    indent = len(line) - len(stripped)
    local_col = max(0, col - indent)

    # `screen X(...)` declaration — IS a screen occurrence.
    if stripped.startswith("screen ") and local_col >= len("screen "):
        return True

    # `use X(...)` / `show screen X` / `call screen X` — IS a screen.
    if stripped.startswith(("use ", "show screen ", "call screen ")):
        return True

    # `Show("X")` / `ShowMenu("X")` / `Hide("X")` screen actions.
    # We rely on the masked-line approach: the call to Show must be
    # outside a string literal. If the match is the string-literal
    # argument of Show/ShowMenu/Hide, the literal content is the screen
    # name — but our text search matches the name token, not the call.
    # Conservative: do not treat as screen.
    if re.search(r"\b(?:Show|ShowMenu|Hide)\s*\(", stripped):
        # If the match is INSIDE the quoted argument of a Show() call,
        # we keep it. Otherwise drop.
        # Walk forward from col: if a `(` appears before any `"`/`'`,
        # this is a code-level Show call and the next `"..."` is the
        # screen name — keep.
        # This is approximate; we conservatively keep all Show() lines.
        return True

    # Label / jump / call (without `screen`) / transform — NOT screen.
    if stripped.startswith(("label ", "jump ", "call ", "transform ")):
        return False

    # Plain dialogue — NOT a screen occurrence.
    return not (
        stripped.startswith(('"', "'")) or bool(re.match(r'^[A-Za-z_]\w*\s+["\']', stripped))
    )


def _filter_occurrences_by_kind(
    occurrences: list[tuple[str, int, int]],
    word: str,
    symbol_kind: str,
) -> list[tuple[str, int, int]]:
    """Filter raw text-search occurrences down to those that are real
    references of the requested ``symbol_kind``.

    Reads each source line and asks the kind-specific predicate whether
    the match is a real reference. Lines that cannot be read are kept
    conservatively (no information loss).
    """
    if symbol_kind == "labels":
        # Labels use the dedicated reverse-index path (`_rename_label`),
        # not text search. Nothing to filter.
        return occurrences

    # Group occurrences by file to amortise disk reads.
    by_file: dict[str, list[tuple[int, int]]] = {}
    for fpath, line_idx, col_utf16 in occurrences:
        by_file.setdefault(fpath, []).append((line_idx, col_utf16))

    word_len_utf16 = len(word.encode("utf-16-le")) // 2

    predicate = {
        "variables": _is_variable_occurrence,
        "transforms": _is_transform_occurrence,
        "screens": _is_screen_occurrence,
    }.get(symbol_kind)

    if predicate is None:
        return occurrences

    kept: list[tuple[str, int, int]] = []
    for fpath, items in by_file.items():
        try:
            with open(fpath, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            # Cannot read — keep all occurrences conservatively.
            for line_idx, col_utf16 in items:
                kept.append((fpath, line_idx, col_utf16))
            continue

        for line_idx, col_utf16 in items:
            if line_idx >= len(lines):
                kept.append((fpath, line_idx, col_utf16))
                continue
            line = lines[line_idx]
            if predicate(line, col_utf16, word_len_utf16):
                kept.append((fpath, line_idx, col_utf16))

    return kept
