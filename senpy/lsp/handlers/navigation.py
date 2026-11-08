"""LSP handlers: navigation (definition, references, rename, document_symbols).

Extracted from senpy/lsp/server.py in 0.6.0-4 (Phase 5).

Handlers:
  - definition        ← TEXT_DOCUMENT_DEFINITION (F12)
  - references        ← TEXT_DOCUMENT_REFERENCES (Shift+F12)
  - document_symbols  ← TEXT_DOCUMENT_DOCUMENT_SYMBOL (Ctrl+Shift+O, Breadcrumbs)
  - prepare_rename    ← TEXT_DOCUMENT_PREPARE_RENAME (F2 preview)
  - rename            ← TEXT_DOCUMENT_RENAME (F2 apply)

All functions accept (ls, params) and access shared state via
server_mod._X (lazy import breaks the import cycle).
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    try:
        from pygls.lsp.server import LanguageServer
    except ImportError:
        from pygls.server import LanguageServer  # type: ignore[attr-defined, no-redef]

from lsprotocol import types as lsp

from senpy.core.constants import CLAUSE_KEYWORDS


def _get_server_mod():
    """Lazy access to senpy.lsp.server, breaks the import cycle.

    All accesses to shared state (_active_analyzer, _is_initialized, ...)
    go through server_mod = _get_server_mod() at the start of each function.
    """
    from senpy.lsp import server

    return server


def definition(ls: LanguageServer, params: lsp.DefinitionParams) -> lsp.Location | None:
    """Native F12 navigation to labels, screens, variables, sprites and asset files."""
    server_mod = _get_server_mod()
    if server_mod._active_analyzer is None or not server_mod._is_initialized:
        return None

    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc or not doc.lines:
        return None

    line_idx = params.position.line
    if line_idx >= len(doc.lines):
        return None

    line = doc.lines[line_idx]
    col = params.position.character
    stripped = line.strip()

    # Phase 1: click inside a quoted string → resolve as a media file path.
    quoted_loc = _resolve_quoted_path(line=line, col=col, server_mod=server_mod)
    if quoted_loc is not None:
        return quoted_loc

    # Phase 2: click on a sprite/bg token in show/scene/hide lines.
    if stripped.startswith(("show ", "scene ", "hide ")):
        scene_loc = _resolve_show_scene_token(
            line=line, col=col, stripped=stripped, server_mod=server_mod
        )
        if scene_loc is not None:
            return scene_loc

    # Phase 3: identifier lookup — label, screen, variable, image, transform.
    word = _word_at_position(line, col)
    if word is None:
        return None

    return _resolve_symbol(word=word, server_mod=server_mod)


def _word_at_position(line: str, col: int) -> str | None:
    r"""Return the dotted-identifier at the given column (regex `[^\W\d][\w\.]*`)."""
    for m in re.finditer(r"[^\W\d][\w\.]*", line):
        if m.start() <= col <= m.end():
            return m.group(0)
    return None


def _resolve_quoted_path(*, line: str, col: int, server_mod) -> lsp.Location | None:
    """Phase 1: if the cursor is inside a quoted string, try to resolve it
    as a media-file path (relative to `game/` or as a basename match).
    """
    for qm in re.finditer(r'("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')', line):
        if not (qm.start() <= col <= qm.end()):
            continue
        raw_path = qm.group(0)[1:-1].strip()
        norm_q = raw_path.replace("\\", "/").lower()
        norm_q = re.sub(r"^<[^>]+>\s*", "", norm_q)
        base_q = os.path.basename(norm_q)

        for rel_path, full_path in server_mod._active_analyzer.media_disk_files.items():
            clean_rel = rel_path.removeprefix("game/")
            if rel_path == norm_q or clean_rel == norm_q or os.path.basename(rel_path) == base_q:
                return lsp.Location(
                    uri=server_mod._path_to_uri(full_path),
                    range=lsp.Range(start=lsp.Position(0, 0), end=lsp.Position(0, 0)),
                )
    return None


def _resolve_show_scene_token(
    *, line: str, col: int, stripped: str, server_mod
) -> lsp.Location | None:
    """Phase 2: click on a sprite/bg token inside `show X` / `scene X` / `hide X`.

    First try to resolve the full image tag (e.g. `sayori happy`) as a
    declared `image`. If not found, try the base tag (e.g. `sayori`).
    If neither is a declared image, fall back to a media-file path match
    (e.g. `images/sayori/happy.png` tokenized as `sayori happy`).
    """
    parts = stripped.split()[1:]
    img_tokens: list[str] = []
    for p in parts:
        clean_p = p.rstrip(":")
        if clean_p in CLAUSE_KEYWORDS:
            break
        img_tokens.append(clean_p)
        if p.endswith(":"):
            break

    if not img_tokens:
        return None

    full_tag = " ".join(img_tokens)
    base_tag = img_tokens[0]
    tag_start = line.find(base_tag)
    tag_end = tag_start + len(full_tag) if tag_start != -1 else -1

    if tag_start == -1 or not (tag_start <= col <= tag_end):
        return None

    # Try declared images first (full_tag, then base_tag).
    for candidate in (full_tag, base_tag):
        if candidate in server_mod._active_analyzer.images:
            img = server_mod._active_analyzer.images[candidate]
            return _location_at_symbol_line(server_mod, img, len(candidate))

    # Fall back to media-file path matching (auto-discovered images).
    for candidate in (full_tag, base_tag):
        cand_norm = candidate.lower()
        for rel_path, full_path in server_mod._active_analyzer.media_disk_files.items():
            clean_rel = rel_path.removeprefix("game/")
            clean_no_ext = os.path.splitext(clean_rel)[0]
            tokenized = clean_no_ext.removeprefix("images/").replace("/", " ").replace("_", " ")
            if tokenized == cand_norm or os.path.basename(clean_no_ext) == cand_norm:
                return lsp.Location(
                    uri=server_mod._path_to_uri(full_path),
                    range=lsp.Range(start=lsp.Position(0, 0), end=lsp.Position(0, 0)),
                )

    return None


def _resolve_symbol(*, word: str, server_mod) -> lsp.Location | None:
    """Phase 3: identifier lookup across label / screen / variable /
    image / transform registries.

    Returns the first matching `lsp.Location`, or `None` if the word is
    not a declared symbol of any kind.
    """
    analyzer = server_mod._active_analyzer

    if word in analyzer.labels:
        lbl = analyzer.labels[word]
        return _location_at_symbol_line(server_mod, lbl, len(word))

    if word in analyzer.screens:
        scr = analyzer.screens[word]
        return _location_at_symbol_line(server_mod, scr, len(word))

    # Variables support dotted access: `player.name` → look up `name`.
    target_var = word if word in analyzer.variables else word.split(".")[-1]
    if target_var in analyzer.variables:
        var = analyzer.variables[target_var]
        return _location_at_symbol_line(server_mod, var, len(target_var))

    if word in analyzer.images:
        img = analyzer.images[word]
        return _location_at_symbol_line(server_mod, img, len(word))

    if word in analyzer.transforms:
        trans = analyzer.transforms[word]
        return _location_at_symbol_line(server_mod, trans, len(word))

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


def rename(ls: LanguageServer, params: lsp.RenameParams) -> lsp.WorkspaceEdit | None:
    server_mod = _get_server_mod()
    """Label rename: updates the declaration + all jump/call references."""
    if server_mod._active_analyzer is None or not server_mod._is_initialized:
        return None

    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc or not doc.lines:
        return None

    line_idx = params.position.line
    if line_idx >= len(doc.lines):
        return None

    line = doc.lines[line_idx]
    col = params.position.character

    # Extract the word under the cursor
    word = None
    for m in re.finditer(r"[a-zA-Z_][a-zA-Z0-9_\.]*", line):
        if m.start() <= col <= m.end():
            word = m.group(0)
            break

    if not word:
        return None

    new_name = params.new_name

    # rename for labels, variables, transforms, screens.
    # use the snapshot, not server_mod._active_analyzer.labels —
    # analyze_file_only clears labels from other files.
    if word in server_mod._symbol_snapshot["labels"]:
        # Existing logic for labels (via jump_sources reverse index)
        return _rename_label(server_mod, word, new_name)
    elif word in server_mod._symbol_snapshot["variables"]:
        return _rename_symbol_via_text_search(server_mod, word, new_name, "variables")
    elif word in server_mod._symbol_snapshot["transforms"]:
        return _rename_symbol_via_text_search(server_mod, word, new_name, "transforms")
    elif word in server_mod._symbol_snapshot["screens"]:
        return _rename_symbol_via_text_search(server_mod, word, new_name, "screens")

    return None


def _rename_label(server_mod, word: str, new_name: str) -> lsp.WorkspaceEdit | None:
    """Rename for a label: updates the declaration + all jump/call references.

    Uses the jump_sources reverse index from the analyzer — more precise than
    text search (does not catch false positives in strings/comments).
    """
    changes: dict[str, list[lsp.TextEdit]] = {}

    # 1. Declaration (label X:)
    lbl = server_mod._symbol_snapshot["labels"][word]
    lbl_uri = server_mod._path_to_uri(lbl.file_path)
    lbl_line = max(0, lbl.line_number - 1)  # 0-based

    # Read the line to find the exact position of the word
    try:
        with open(lbl.file_path, encoding="utf-8") as f:
            file_lines = f.readlines()
        if lbl_line < len(file_lines):
            lbl_content = file_lines[lbl_line]
            # Find the position of the word in the line
            word_start = lbl_content.find(word)
            if word_start >= 0:
                word_start_utf16 = len(lbl_content[:word_start].encode("utf-16-le")) // 2
                word_end_utf16 = word_start_utf16 + len(word.encode("utf-16-le")) // 2
                changes.setdefault(lbl_uri, []).append(
                    lsp.TextEdit(
                        range=lsp.Range(
                            start=lsp.Position(line=lbl_line, character=word_start_utf16),
                            end=lsp.Position(line=lbl_line, character=word_end_utf16),
                        ),
                        new_text=new_name,
                    )
                )
    except OSError:
        pass

    # 2. All jump/call references (from jump_sources)
    # UX: also from the snapshot, to get references from all files.
    for ref_path, ref_line in server_mod._symbol_snapshot["jump_sources"].get(word, []):
        ref_uri = server_mod._path_to_uri(ref_path)
        ref_line_0 = max(0, ref_line - 1)  # 0-based

        # Read the line to find the exact position of the word
        try:
            with open(ref_path, encoding="utf-8") as f:
                ref_lines = f.readlines()
            if ref_line_0 < len(ref_lines):
                ref_content = ref_lines[ref_line_0]
                # Find the position of the word in the line
                word_start = ref_content.find(word)
                if word_start >= 0:
                    word_start_utf16 = len(ref_content[:word_start].encode("utf-16-le")) // 2
                    word_end_utf16 = word_start_utf16 + len(word.encode("utf-16-le")) // 2
                    changes.setdefault(ref_uri, []).append(
                        lsp.TextEdit(
                            range=lsp.Range(
                                start=lsp.Position(line=ref_line_0, character=word_start_utf16),
                                end=lsp.Position(line=ref_line_0, character=word_end_utf16),
                            ),
                            new_text=new_name,
                        )
                    )
        except OSError:
            pass

    if not changes:
        return None

    return lsp.WorkspaceEdit(changes=changes)


# =============================================================================
# helpers: rename for variables/transforms/screens via text search
# =============================================================================

# Regex template to find occurrences of a word as a whole-word (not part of another name).
# Boundaries: not alphanumeric/underscore on either side.
# Example: for "player_gold" it should not match "player_gold_count" or "my_player_gold".
_WORD_BOUNDARY_TEMPLATE = r"(?<![A-Za-z0-9_])({})(?![A-Za-z0-9_])"


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
    if server_mod._active_analyzer is None:
        return []

    project_path = server_mod._active_analyzer.project_path
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


def _rename_symbol_via_text_search(
    server_mod, word: str, new_name: str, symbol_kind: str
) -> lsp.WorkspaceEdit | None:
    """Rename a variable/transform/screen via text search across all .rpy files.

    For variables/transforms/screens there is no reverse index (like jump_sources
    for labels). We use text search — all whole-word occurrences of the word in
    .rpy files of the project are replaced with `new_name`.
    """
    occurrences = _find_text_occurrences_in_project(server_mod, word)
    if not occurrences:
        return None

    # Filter occurrences by symbol_kind so a variable rename does NOT
    # touch label declarations, jump targets, screen actions, or
    # natural-language mentions in dialogue that happen to share the
    # same textual token. Same for transforms and screens — only real
    # references of the requested kind survive the filter.
    occurrences = _filter_occurrences_by_kind(occurrences, word, symbol_kind)
    if not occurrences:
        return None

    changes: dict[str, list[lsp.TextEdit]] = {}
    word_len_utf16 = len(word.encode("utf-16-le")) // 2

    for fpath, line_idx, col_utf16 in occurrences:
        uri = server_mod._path_to_uri(fpath)
        changes.setdefault(uri, []).append(
            lsp.TextEdit(
                range=lsp.Range(
                    start=lsp.Position(line=line_idx, character=col_utf16),
                    end=lsp.Position(line=line_idx, character=col_utf16 + word_len_utf16),
                ),
                new_text=new_name,
            )
        )

    if not changes:
        return None

    return lsp.WorkspaceEdit(changes=changes)


def references(ls: LanguageServer, params: lsp.ReferenceParams) -> list[lsp.Location] | None:
    server_mod = _get_server_mod()
    """Find References: all static jump/call references to the label under the cursor."""
    if server_mod._active_analyzer is None or not server_mod._is_initialized:
        return None

    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc or not doc.lines:
        return None

    line_idx = params.position.line
    if line_idx >= len(doc.lines):
        return None

    line = doc.lines[line_idx]
    col = params.position.character

    # Same word extractor as in definition/hover
    word = None
    for m in re.finditer(r"[a-zA-Z_][a-zA-Z0-9_\.]*", line):
        if m.start() <= col <= m.end():
            word = m.group(0)
            break

    if not word:
        return None

    locations: list[lsp.Location] = []

    # references for labels: use _symbol_snapshot, not _active_analyzer.
    # After did_change → analyze_file_only, the live analyzer's label
    # registry is rebuilt for the edited file only — labels from other
    # files disappear from the live registry. _symbol_snapshot is
    # refreshed on did_open / did_save / did_change_watched_files and
    # retains labels from all files. Other handlers (rename,
    # prepare_rename, incoming_calls, outgoing_calls, workspace_symbol)
    # already use the snapshot — references must be consistent (P1-7).
    snapshot = server_mod._symbol_snapshot
    if word in snapshot["labels"]:
        if params.context.include_declaration:
            lbl = snapshot["labels"][word]
            locations.append(
                lsp.Location(
                    uri=server_mod._path_to_uri(lbl.file_path),
                    range=lsp.Range(
                        start=lsp.Position(line=max(0, lbl.line_number - 1), character=0),
                        end=lsp.Position(line=max(0, lbl.line_number - 1), character=len(word)),
                    ),
                )
            )
        for ref_path, ref_line in snapshot["jump_sources"].get(word, []):
            locations.append(
                lsp.Location(
                    uri=server_mod._path_to_uri(ref_path),
                    range=lsp.Range(
                        start=lsp.Position(line=max(0, ref_line - 1), character=0),
                        end=lsp.Position(line=max(0, ref_line - 1), character=len(word)),
                    ),
                )
            )
        return locations

    # references for variables/transforms/screens via text search.
    # They have no reverse index (like jump_sources for labels), so we use
    # _find_text_occurrences_in_project — a whole-word grep across all .rpy files.
    if (
        word in server_mod._symbol_snapshot["variables"]
        or word in server_mod._symbol_snapshot["transforms"]
        or word in server_mod._symbol_snapshot["screens"]
    ):
        return _references_via_text_search(server_mod, word, params.context.include_declaration)

    return None


def _references_via_text_search(
    server_mod, word: str, include_declaration: bool
) -> list[lsp.Location]:
    """helper: references for variables/transforms/screens.

    Uses _find_text_occurrences_in_project. If include_declaration=False,
    excludes the first location (the declaration) — it is identified via the snapshot.
    """
    occurrences = _find_text_occurrences_in_project(server_mod, word)
    if not occurrences:
        return []

    # If the declaration should not be included — find it via the snapshot and exclude it.
    declaration_loc: tuple[str, int] | None = None  # (file_path, line_idx_0based)
    for kind in ("variables", "transforms", "screens"):
        sym = server_mod._symbol_snapshot[kind].get(word)
        if sym is not None:
            declaration_loc = (sym.file_path, max(0, sym.line_number - 1))
            break

    locations: list[lsp.Location] = []
    word_len_utf16 = len(word.encode("utf-16-le")) // 2

    for fpath, line_idx, col_utf16 in occurrences:
        if (
            not include_declaration
            and declaration_loc is not None
            and fpath == declaration_loc[0]
            and line_idx == declaration_loc[1]
        ):
            continue
        locations.append(
            lsp.Location(
                uri=server_mod._path_to_uri(fpath),
                range=lsp.Range(
                    start=lsp.Position(line=line_idx, character=col_utf16),
                    end=lsp.Position(line=line_idx, character=col_utf16 + word_len_utf16),
                ),
            )
        )

    return locations


def document_symbols(
    ls: LanguageServer, params: lsp.DocumentSymbolParams
) -> list[lsp.DocumentSymbol]:
    """Builds the native symbol tree for Outline (Structure), Breadcrumbs and Ctrl+Shift+O."""
    server_mod = _get_server_mod()
    if server_mod._active_analyzer is None:
        return []

    uri = params.text_document.uri
    file_path = server_mod._uri_to_path(uri)
    norm_path = server_mod._normalize_path(file_path)  # P0-6: unified normalization

    scope = server_mod._active_analyzer.file_scopes.get(norm_path)
    if not scope:
        server_mod._active_analyzer._collect_symbols(file_path)
        scope = server_mod._active_analyzer.file_scopes.get(norm_path)
    if not scope:
        return []

    doc = ls.workspace.get_text_document(uri)
    lines = doc.lines if doc and doc.lines else []
    total_lines = len(lines) if lines else 1000

    raw_entries = _collect_symbol_entries(scope)
    raw_entries.sort(key=lambda x: x[0])
    return _build_document_symbols(raw_entries=raw_entries, lines=lines, total_lines=total_lines)


# A "raw entry" before it becomes a DocumentSymbol:
#   (start_line, name, kind, detail, is_block)
# `is_block` = True means the symbol's range should extend to the start of
# the next block entry (or end-of-file) — used for labels, screens, etc.
# that own a body. False means the range is a single line (variables, plain images).
RawSymbolEntry = tuple[int, str, "lsp.SymbolKind", str, bool]


def _collect_symbol_entries(scope) -> list[RawSymbolEntry]:
    """Collect every declared symbol in `scope` into a flat list of raw entries.

    Order: labels → screens → images → transforms → variables. The caller
    sorts by `start_line` before building the final DocumentSymbols.
    """
    entries: list[RawSymbolEntry] = []
    entries.extend(_collect_label_symbols(scope))
    entries.extend(_collect_screen_symbols(scope))
    entries.extend(_collect_image_symbols(scope))
    entries.extend(_collect_transform_symbols(scope))
    entries.extend(_collect_variable_symbols(scope))
    return entries


def _collect_label_symbols(scope) -> list[RawSymbolEntry]:
    """Labels (skip names starting with `_`). Treated as blocks (own a body)."""
    entries: list[RawSymbolEntry] = []
    for name, sym in scope.labels.items():
        if name.startswith("_"):
            continue
        entries.append((max(0, sym.line_number - 1), name, lsp.SymbolKind.Function, "Label", True))
    return entries


def _collect_screen_symbols(scope) -> list[RawSymbolEntry]:
    """Screens. Treated as blocks."""
    entries: list[RawSymbolEntry] = []
    for name, sym in scope.screens.items():
        entries.append(
            (max(0, sym.line_number - 1), name, lsp.SymbolKind.Interface, "Screen", True)
        )
    return entries


def _collect_image_symbols(scope) -> list[RawSymbolEntry]:
    """Images. Layered images are blocks (own an ATL body), plain images are not."""
    entries: list[RawSymbolEntry] = []
    for name, sym in scope.images.items():
        if sym.is_layered:
            entries.append(
                (max(0, sym.line_number - 1), name, lsp.SymbolKind.Class, "Layered Image", True)
            )
        else:
            entries.append(
                (max(0, sym.line_number - 1), name, lsp.SymbolKind.Field, "Image", False)
            )
    return entries


def _collect_transform_symbols(scope) -> list[RawSymbolEntry]:
    """ATL transforms. Treated as blocks (own an ATL body)."""
    entries: list[RawSymbolEntry] = []
    for name, sym in scope.transforms.items():
        entries.append(
            (max(0, sym.line_number - 1), name, lsp.SymbolKind.Function, "Transform", True)
        )
    return entries


def _collect_variable_symbols(scope) -> list[RawSymbolEntry]:
    """Variables (`default`) and constants (`define`). Skip `_`-prefixed and Character definitions.

    Treated as single-line entries (no body to span).
    """
    entries: list[RawSymbolEntry] = []
    for name, sym in scope.variables.items():
        if name.startswith("_") or sym.is_character:
            continue
        kind = lsp.SymbolKind.Constant if sym.is_constant else lsp.SymbolKind.Variable
        detail = "Constant (define)" if sym.is_constant else "Variable (default)"
        entries.append((max(0, sym.line_number - 1), name, kind, detail, False))
    return entries


def _build_document_symbols(
    *,
    raw_entries: list[RawSymbolEntry],
    lines: list[str],
    total_lines: int,
) -> list[lsp.DocumentSymbol]:
    """Convert sorted `raw_entries` into LSP DocumentSymbols.

    For block entries (label/screen/transform/layered-image), the range
    extends to the start of the next block entry (or end-of-file). For
    non-block entries (variable/plain image), the range is a single line.

    The selection range (the highlighted region VS Code uses for "Go to
    Symbol") is just the identifier at the start of the line.
    """
    symbols: list[lsp.DocumentSymbol] = []
    for i, (start_line, name, kind, detail, is_block) in enumerate(raw_entries):
        line_text = lines[start_line] if start_line < len(lines) else ""
        col_idx = line_text.find(name)
        start_char = max(0, col_idx) if col_idx != -1 else 0

        if is_block:
            next_block = next((e for e in raw_entries[i + 1 :] if e[4]), None)
            end_line = (
                max(start_line, next_block[0] - 1)
                if next_block
                else max(start_line, total_lines - 1)
            )
        else:
            end_line = start_line

        end_char = len(lines[end_line].rstrip()) if end_line < len(lines) else 0

        symbols.append(
            lsp.DocumentSymbol(
                name=name,
                kind=kind,
                range=lsp.Range(
                    start=lsp.Position(line=start_line, character=0),
                    end=lsp.Position(line=end_line, character=end_char),
                ),
                selection_range=lsp.Range(
                    start=lsp.Position(line=start_line, character=start_char),
                    end=lsp.Position(line=start_line, character=start_char + len(name)),
                ),
                detail=detail,
            )
        )
    return symbols


def prepare_rename(
    ls: LanguageServer, params: lsp.PrepareRenameParams
) -> lsp.Range | lsp.PrepareRenameResult | None:
    server_mod = _get_server_mod()
    """Returns the Range of the word under the cursor for preview before rename."""
    if server_mod._active_analyzer is None or not server_mod._is_initialized:
        return None

    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc or not doc.lines:
        return None

    line_idx = params.position.line
    if line_idx >= len(doc.lines):
        return None

    line = doc.lines[line_idx]
    col = params.position.character

    # Find the word under the cursor (same rule as in rename)
    for m in re.finditer(r"[a-zA-Z_][a-zA-Z0-9_\.]*", line):
        if m.start() <= col <= m.end():
            word = m.group(0)
            # Eligibility: prepare_rename must return a Range for any symbol
            # type that rename() supports. rename() handles labels (via
            # _rename_label) and variables/transforms/screens (via
            # _rename_symbol_via_text_search). If the word is in any of
            # these snapshot sets, return its Range — VS Code then starts
            # the F2 session and calls rename().
            #
            # Previously this only checked labels — F2 silently did
            # nothing on variables/transforms/screens (P1-6 bug).
            #
            # UX: use the snapshot, not server_mod._active_analyzer.*,
            # so F2 works even after did_change (analyze_file_only).
            snapshot = server_mod._symbol_snapshot
            if (
                word in snapshot["labels"]
                or word in snapshot["variables"]
                or word in snapshot["transforms"]
                or word in snapshot["screens"]
            ):
                # Return the Range of the word. pygls/lsprotocol accepts a Range
                # or PrepareRenameResult(placeholder=...). A Range is enough.
                # UTF-16 positions for VS Code compatibility.
                start_utf16 = len(line[: m.start()].encode("utf-16-le")) // 2
                end_utf16 = start_utf16 + len(word.encode("utf-16-le")) // 2
                return lsp.Range(
                    start=lsp.Position(line=line_idx, character=start_utf16),
                    end=lsp.Position(line=line_idx, character=end_utf16),
                )
            # The word exists but is not a rename-able symbol — return None
            # ("can't rename here"). This includes words inside strings,
            # comments, and keywords that are not symbol names.
            return None

    # No word under the cursor
    return None


# =============================================================================
# textDocument/prepareCallHierarchy + incomingCalls + outgoingCalls
# =============================================================================
# Right-click on label → "Find Callers" / "Find References".
#
# Pipeline:
#   1. prepareCallHierarchy(item under cursor) → list[CallHierarchyItem]
#   2. callHierarchy/incomingCalls(item) → list[CallHierarchyIncomingCall] (who calls this?)
#   3. callHierarchy/outgoingCalls(item) → list[CallHierarchyOutgoingCall] (where does this go?)
#
# Sources:
#   - server_mod._symbol_snapshot["labels"] for label lookup
#   - server_mod._symbol_snapshot["jump_sources"] for incoming calls (who jumps to this label)
#   - LabelSymbol.outgoing_jumps for outgoing calls (where this label jumps to)


def prepare_call_hierarchy(
    ls: LanguageServer, params: lsp.CallHierarchyPrepareParams
) -> list[lsp.CallHierarchyItem]:
    """Return CallHierarchyItem for label under cursor.

    Returns empty list if cursor is not on a label declaration or reference.
    """
    server_mod = _get_server_mod()
    if server_mod._active_analyzer is None or not server_mod._is_initialized:
        return []

    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc or not doc.lines:
        return []

    line_idx = params.position.line
    if line_idx >= len(doc.lines):
        return []

    line = doc.lines[line_idx]
    col = params.position.character

    # Find word under cursor
    word = None
    for m in re.finditer(r"[a-zA-Z_][a-zA-Z0-9_\.]*", line):
        if m.start() <= col <= m.end():
            word = m.group(0)
            break

    if not word:
        return []

    # Check if word is a label (in snapshot, with fallback to analyzer)
    labels = server_mod._symbol_snapshot.get("labels", {})
    if word not in labels and server_mod._active_analyzer is not None:
        labels = server_mod._active_analyzer.labels
    if word not in labels:
        return []

    label = labels[word]
    # Build CallHierarchyItem
    return [
        lsp.CallHierarchyItem(
            name=word,
            kind=lsp.SymbolKind.Function,  # labels are like functions
            uri=server_mod._path_to_uri(label.file_path),
            range=lsp.Range(
                start=lsp.Position(line=max(0, label.line_number - 1), character=0),
                end=lsp.Position(line=max(0, label.line_number - 1), character=len(line.rstrip())),
            ),
            selection_range=lsp.Range(
                start=lsp.Position(line=max(0, label.line_number - 1), character=0),
                end=lsp.Position(line=max(0, label.line_number - 1), character=len(word)),
            ),
        )
    ]


def incoming_calls(
    ls: LanguageServer, params: lsp.CallHierarchyIncomingCallsParams
) -> list[lsp.CallHierarchyIncomingCall]:
    """Find all labels that call/jump to the given label.

    Uses jump_sources reverse index from analyzer snapshot.
    """
    server_mod = _get_server_mod()
    if server_mod._active_analyzer is None or not server_mod._is_initialized:
        return []

    target_name = params.item.name
    labels = server_mod._symbol_snapshot.get("labels", {})
    jump_sources = server_mod._symbol_snapshot.get("jump_sources", {})
    labels_by_file = server_mod._symbol_snapshot.get("labels_by_file", {})
    # Fallback: if not in snapshot, check analyzer directly
    if not jump_sources and server_mod._active_analyzer is not None:
        jump_sources = server_mod._active_analyzer.jump_sources
    if not labels and server_mod._active_analyzer is not None:
        labels = server_mod._active_analyzer.labels
    # Build labels_by_file on-the-fly if the snapshot is stale or empty —
    # keeps the handler correct even before the first _refresh_symbol_snapshot.
    if not labels_by_file and labels:
        labels_by_file = {}
        for name, lbl in labels.items():
            labels_by_file.setdefault(lbl.file_path, []).append((name, lbl.line_number))
        for file_labels in labels_by_file.values():
            file_labels.sort(key=lambda item: item[1])

    incoming: list[lsp.CallHierarchyIncomingCall] = []

    # jump_sources maps: target_label → list of (file_path, line_number)
    for caller_path, caller_line in jump_sources.get(target_name, []):
        # Find the label that contains this call site using the per-file
        # index — O(labels_in_file) instead of O(all_labels). The index
        # is sorted by line_number, so the last entry with line <= caller_line
        # is the containing label.
        caller_label = None
        caller_name = "<anonymous>"
        for name, line in labels_by_file.get(caller_path, []):
            if line <= caller_line:
                caller_label = labels.get(name)
                caller_name = name
            else:
                break  # sorted — no more labels <= caller_line

        if caller_label is None:
            # Fallback: use the file/line without a label name
            caller_name = "<anonymous>"
            caller_label_uri = server_mod._path_to_uri(caller_path)
            caller_range = lsp.Range(
                start=lsp.Position(line=max(0, caller_line - 1), character=0),
                end=lsp.Position(line=max(0, caller_line - 1), character=80),
            )
        else:
            caller_label_uri = server_mod._path_to_uri(caller_label.file_path)
            caller_range = lsp.Range(
                start=lsp.Position(line=max(0, caller_label.line_number - 1), character=0),
                end=lsp.Position(line=max(0, caller_label.line_number - 1), character=80),
            )

        # Build the caller's CallHierarchyItem
        caller_item = lsp.CallHierarchyItem(
            name=caller_name,
            kind=lsp.SymbolKind.Function,
            uri=caller_label_uri,
            range=caller_range,
            selection_range=caller_range,
        )

        # fromRanges: where the call happens (the line with jump/call)
        call_range = lsp.Range(
            start=lsp.Position(line=max(0, caller_line - 1), character=0),
            end=lsp.Position(line=max(0, caller_line - 1), character=80),
        )

        incoming.append(
            lsp.CallHierarchyIncomingCall(
                from_=caller_item,
                from_ranges=[call_range],
            )
        )

    return incoming


def outgoing_calls(
    ls: LanguageServer, params: lsp.CallHierarchyOutgoingCallsParams
) -> list[lsp.CallHierarchyOutgoingCall]:
    """Find all labels that this label jumps/calls to.

    Uses LabelSymbol.outgoing_jumps from analyzer snapshot.
    """
    server_mod = _get_server_mod()
    if server_mod._active_analyzer is None or not server_mod._is_initialized:
        return []

    source_name = params.item.name
    labels = server_mod._symbol_snapshot.get("labels", {})
    jump_sources = server_mod._symbol_snapshot.get("jump_sources", {})
    labels_by_file = server_mod._symbol_snapshot.get("labels_by_file", {})
    # Fallback: if not in snapshot, check analyzer directly
    if source_name not in labels and server_mod._active_analyzer is not None:
        labels = server_mod._active_analyzer.labels
    if not jump_sources and server_mod._active_analyzer is not None:
        jump_sources = server_mod._active_analyzer.jump_sources
    if not labels_by_file and labels:
        labels_by_file = {}
        for name, lbl in labels.items():
            labels_by_file.setdefault(lbl.file_path, []).append((name, lbl.line_number))
        for file_labels in labels_by_file.values():
            file_labels.sort(key=lambda item: item[1])

    if source_name not in labels:
        return []

    source_label = labels[source_name]
    # Determine the source label's body range: [source_label.line_number + 1,
    # next_label_line_in_same_file). Jumps inside this range belong to source.
    # Without this bound, a jump to the same target from a LATER label in the
    # same file would be misattributed to source.
    source_end_line = float("inf")
    for _name, line in labels_by_file.get(source_label.file_path, []):
        if line > source_label.line_number:
            source_end_line = line
            break  # sorted — first label after source is the next sibling

    outgoing: list[lsp.CallHierarchyOutgoingCall] = []

    # outgoing_jumps is a set of target label names
    for target_name in source_label.outgoing_jumps:
        if target_name not in labels:
            continue  # target doesn't exist (will be flagged by RPY302)

        target_label = labels[target_name]
        target_item = lsp.CallHierarchyItem(
            name=target_name,
            kind=lsp.SymbolKind.Function,
            uri=server_mod._path_to_uri(target_label.file_path),
            range=lsp.Range(
                start=lsp.Position(line=max(0, target_label.line_number - 1), character=0),
                end=lsp.Position(line=max(0, target_label.line_number - 1), character=80),
            ),
            selection_range=lsp.Range(
                start=lsp.Position(line=max(0, target_label.line_number - 1), character=0),
                end=lsp.Position(
                    line=max(0, target_label.line_number - 1), character=len(target_name)
                ),
            ),
        )

        # fromRanges: where the call happens in the source label's body.
        # jump_sources maps target → list of (file, line) for every jump to
        # that target across the project. Filter to entries that originate
        # from THIS source label's body (same file, line between source
        # declaration and the next sibling label). Each matching entry
        # becomes one Range in from_ranges — the LSP spec explicitly allows
        # multiple ranges when the same target is called multiple times.
        jump_lines = [
            line
            for file_path, line in jump_sources.get(target_name, [])
            if file_path == source_label.file_path
            and source_label.line_number < line < source_end_line
        ]

        if jump_lines:
            from_ranges = [
                lsp.Range(
                    start=lsp.Position(line=max(0, line - 1), character=0),
                    end=lsp.Position(line=max(0, line - 1), character=80),
                )
                for line in jump_lines
            ]
        else:
            # Fallback: jump line not tracked (dynamic jump via
            # renpy.jump() in a string, or jump_sources not populated).
            # Fall back to the source label's declaration line rather
            # than dropping the outgoing call entirely — the user still
            # sees that source calls target, even if the exact line is
            # unknown.
            from_ranges = [
                lsp.Range(
                    start=lsp.Position(line=max(0, source_label.line_number - 1), character=0),
                    end=lsp.Position(line=max(0, source_label.line_number - 1), character=80),
                )
            ]

        outgoing.append(
            lsp.CallHierarchyOutgoingCall(
                to=target_item,
                from_ranges=from_ranges,
            )
        )

    return outgoing
