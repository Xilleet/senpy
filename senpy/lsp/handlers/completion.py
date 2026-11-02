"""LSP handlers: completion.

Вынесено из senpy/lsp/server.py в 0.6.0-5 (Фаза 5).

Handler'ы:
  - completions        ← TEXT_DOCUMENT_COMPLETION

Все функции принимают (ls, params) и обращаются к shared state через
server_mod._X (lazy import разрывает цикл импортов).
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from senpy.core.logging import get_logger

if TYPE_CHECKING:
    try:
        from pygls.lsp.server import LanguageServer
    except ImportError:
        from pygls.server import LanguageServer

from lsprotocol import types as lsp

_logger = get_logger("lsp.completion")


def _get_server_mod():
    """Ленивый доступ к senpy.lsp.server, разрывает цикл импортов."""
    from senpy.lsp import server

    return server


def completions(ls: LanguageServer, params: lsp.CompletionParams) -> lsp.CompletionList:
    """Контекстный автокомплит для меток, спрайтов и экранов."""
    server_mod = _get_server_mod()
    items: list[lsp.CompletionItem] = []
    if server_mod._active_analyzer is None or not server_mod._is_initialized:
        _logger.debug(
            "[completions] NOT INITIALIZED: analyzer=%s, init=%s",
            server_mod._active_analyzer is not None,
            server_mod._is_initialized,
        )
        return lsp.CompletionList(is_incomplete=False, items=items)

    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc:
        _logger.debug("[completions] no doc")
        return lsp.CompletionList(is_incomplete=False, items=items)

    if params.position.line >= len(doc.lines):
        _logger.debug(
            "[completions] line %s out of range (doc has %s lines)",
            params.position.line,
            len(doc.lines),
        )
        return lsp.CompletionList(is_incomplete=False, items=items)

    line = doc.lines[params.position.line]
    prefix = line[: params.position.character].lstrip()
    _log_completion_request(prefix, server_mod)

    items = _collect_completion_items(prefix=prefix, server_mod=server_mod)

    _logger.debug(
        "[completions] RETURN %d items (prefix=%r, snapshot_labels=%d)",
        len(items),
        prefix,
        len(server_mod._symbol_snapshot["labels"]),
    )
    return lsp.CompletionList(is_incomplete=False, items=items)


def _collect_completion_items(*, prefix: str, server_mod) -> list[lsp.CompletionItem]:
    """Dispatch on `prefix` to the appropriate completion branch.

    Branches (in priority order):
        1. `jump X` / `call X`         → label names (snapshot, skip private `_`).
        2. `show screen X` / `call screen X` / `use X` → screen names.
        3. `show X` / `scene X`:
            a. `... at X`             → built-in positions + user transforms.
            b. 1 token (only `show`)   → first tag of every declared image.
            c. ≥2 tokens (`show sayori X`) → known attributes for the base tag.
    """
    if prefix.startswith(("jump ", "call ")):
        return _complete_labels(server_mod)

    if prefix.startswith(("show screen ", "call screen ", "use ")):
        return _complete_screens(server_mod)

    if prefix.startswith(("show ", "scene ")):
        return _complete_show_scene(prefix=prefix, server_mod=server_mod)

    return []


def _complete_labels(server_mod) -> list[lsp.CompletionItem]:
    """Branch 1: labels for `jump X` / `call X`. Skip labels starting with `_`."""
    items: list[lsp.CompletionItem] = []
    for label_name, lbl in sorted(server_mod._symbol_snapshot["labels"].items()):
        if label_name.startswith("_"):
            continue
        items.append(
            lsp.CompletionItem(
                label=label_name,
                kind=lsp.CompletionItemKind.Reference,
                detail=f"Label ({os.path.basename(lbl.file_path)}:{lbl.line_number})",
            )
        )
    return items


def _complete_screens(server_mod) -> list[lsp.CompletionItem]:
    """Branch 2: screens for `show screen X` / `call screen X` / `use X`."""
    items: list[lsp.CompletionItem] = []
    for screen_name, scr in sorted(server_mod._symbol_snapshot["screens"].items()):
        items.append(
            lsp.CompletionItem(
                label=screen_name,
                kind=lsp.CompletionItemKind.Interface,
                detail=f"Screen ({os.path.basename(scr.file_path)}:{scr.line_number})",
            )
        )
    return items


# Built-in positions available after `show X at ...` / `scene X at ...`.
_STANDARD_POSITIONS = (
    "center",
    "truecenter",
    "left",
    "right",
    "top",
    "topleft",
    "topright",
    "offscreenleft",
    "offscreenright",
    "reset",
    "default",
)


def _complete_show_scene(*, prefix: str, server_mod) -> list[lsp.CompletionItem]:
    """Branch 3: `show X` / `scene X` — positions, transforms, sprite tags, attributes."""
    if " at " in prefix or prefix.endswith(" at"):
        return _complete_positions_and_transforms(server_mod)
    return _complete_sprite_tokens(prefix=prefix, server_mod=server_mod)


def _complete_positions_and_transforms(server_mod) -> list[lsp.CompletionItem]:
    """Branch 3a: built-in positions + user transforms (after `at`)."""
    items: list[lsp.CompletionItem] = [
        lsp.CompletionItem(
            label=pos, kind=lsp.CompletionItemKind.EnumMember, detail="Position (Built-in)"
        )
        for pos in _STANDARD_POSITIONS
    ]
    for trans_name, trans_sym in sorted(server_mod._symbol_snapshot["transforms"].items()):
        items.append(
            lsp.CompletionItem(
                label=trans_name,
                kind=lsp.CompletionItemKind.Function,
                detail=f"Transform ({os.path.basename(trans_sym.file_path)}:{trans_sym.line_number})",
            )
        )
    return items


def _complete_sprite_tokens(*, prefix: str, server_mod) -> list[lsp.CompletionItem]:
    """Branch 3b/c: sprite tags (when only `show`) or attributes (when `show <tag> <attr>`)."""
    tokens = prefix.split()
    # 3b: 1 token (just `show`) or 2 tokens without trailing space (typing the tag).
    if len(tokens) == 1 or (len(tokens) == 2 and not prefix.endswith(" ")):
        return _complete_sprite_tags(server_mod)

    # 3c: ≥2 tokens → attributes for the base tag.
    if len(tokens) >= 2:
        base_tag = tokens[1]
        return _complete_sprite_attributes(base_tag=base_tag, server_mod=server_mod)

    return []


def _complete_sprite_tags(server_mod) -> list[lsp.CompletionItem]:
    """Branch 3b: first tag of every declared image (e.g. `sayori`, `bg`)."""
    items: list[lsp.CompletionItem] = []
    all_tags = {img.split()[0] for img in server_mod._symbol_snapshot["images"]}
    for tag in sorted(all_tags):
        items.append(
            lsp.CompletionItem(label=tag, kind=lsp.CompletionItemKind.Class, detail="Sprite Tag")
        )
    return items


def _complete_sprite_attributes(*, base_tag: str, server_mod) -> list[lsp.CompletionItem]:
    """Branch 3c: known attributes for `base_tag` (e.g. `happy`, `mad` for `sayori`).

    Uses the snapshot for image list (analyze_file_only may have cleared
    labels from other files), but `valid_images` from the live analyzer
    (which is NOT cleared). The `_get_tag_known_attributes` helper on the
    analyzer returns the union of declared attributes + auto-discovered ones.
    """
    items: list[lsp.CompletionItem] = []
    all_valid = server_mod._active_analyzer.valid_images.union(
        server_mod._symbol_snapshot["images"]
    )
    attrs = server_mod._active_analyzer._get_tag_known_attributes(base_tag, all_valid)
    for attr in sorted(attrs):
        items.append(
            lsp.CompletionItem(
                label=attr,
                kind=lsp.CompletionItemKind.EnumMember,
                detail=f"Attribute for '{base_tag}'",
            )
        )
    return items


def _log_completion_request(prefix: str, server_mod) -> None:
    """UX DEBUG: log what we received + snapshot state. Called once per request."""
    _logger.debug(
        "[completions] prefix=%r, snapshot_labels=%d, live_labels=%d, "
        "snapshot_images=%d, snapshot_screens=%d, snapshot_transforms=%d",
        prefix,
        len(server_mod._symbol_snapshot["labels"]),
        len(server_mod._active_analyzer.labels),
        len(server_mod._symbol_snapshot["images"]),
        len(server_mod._symbol_snapshot["screens"]),
        len(server_mod._symbol_snapshot["transforms"]),
    )


# =============================================================================
# textDocument/signatureHelp — parameter hints for call/use
# =============================================================================
# When user types `call my_label(` and cursor is inside parens, VS Code calls
# signatureHelp to display the parameter list.
#
# Returns SignatureHelp with:
#   - signatures[0].label: "my_label(name, age=18)" — full signature text
#   - signatures[0].parameters: list of ParameterInformation
#   - activeSignature: 0 (we only return one signature per call)
#   - activeParameter: index of parameter cursor is on (based on comma count)

# Regex to find `call NAME(` or `use NAME(` patterns
_RE_CALL_USE = re.compile(r"\b(?:call|use)\s+([a-zA-Z_][a-zA-Z0-9_\.]*)\s*\(")


def _count_active_parameter(line: str, cursor_pos: int, paren_start: int) -> int:
    """Count commas between opening paren and cursor — that's the active param index.

    `call f(a, b, c)` with cursor after `b` (between b and c):
    - paren_start = position of `(`
    - cursor_pos = position after `b, ` (before `c`)
    - count commas in line[paren_start+1:cursor_pos] = 1 → activeParameter = 1
    """
    if cursor_pos <= paren_start:
        return 0
    segment = line[paren_start + 1 : cursor_pos]
    # Count commas NOT inside nested parens/brackets
    depth = 0
    comma_count = 0
    for ch in segment:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            comma_count += 1
    return comma_count


def signature_help(ls: LanguageServer, params: lsp.SignatureHelpParams) -> lsp.SignatureHelp | None:
    """Provide parameter hints for call label(...) / use screen(...).

    Returns None if:
        - Analyzer not initialized
        - Cursor not inside call/use parens
        - Target label/screen not found

    Returns SignatureHelp with single SignatureInformation otherwise.
    """
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
    cursor_pos = params.position.character

    # Phase 1: locate the call/use pattern with the cursor inside the parens.
    target_name, paren_start = _find_call_use_target(line=line, cursor_pos=cursor_pos)
    if target_name is None:
        return None

    # Phase 2: look up the target symbol (label or screen).
    symbol = _lookup_call_target(target_name=target_name, server_mod=server_mod)
    if symbol is None:
        return None

    # Phase 3: build the SignatureInformation (label + parameters).
    # NB: labels without parameters still produce a `SignatureHelp` with
    # an empty parameter list (label "name()") — see
    # `test_signature_help_for_label_without_params`.
    sig_info = _build_signature_info(target_name=target_name, symbol=symbol)

    # Phase 4: highlight the parameter the cursor is currently on.
    active_param = _count_active_parameter(line, cursor_pos, paren_start)
    if active_param >= len(sig_info.parameters):
        active_param = max(0, len(sig_info.parameters) - 1)

    return lsp.SignatureHelp(
        signatures=[sig_info],
        active_signature=0,
        active_parameter=active_param,
    )


def _find_call_use_target(*, line: str, cursor_pos: int) -> tuple[str | None, int]:
    """Locate a `call/use NAME(` pattern whose parens contain the cursor.

    Returns `(target_name, paren_start)` if found, or `(None, -1)` if no
    `call`/`use` pattern on this line has the cursor inside its parens.

    `target_name` is the (un-dotted) name after `call`/`use`. `paren_start`
    is the 0-based index of the `(` — used by the caller to compute the
    active parameter via `_count_active_parameter`.
    """
    for m in _RE_CALL_USE.finditer(line):
        if m.end() - 1 > cursor_pos:
            # cursor is before the opening paren — skip this match
            continue
        paren_start = m.end() - 1
        close_pos = line.find(")", cursor_pos)
        if close_pos == -1:
            close_pos = len(line)
        if paren_start <= cursor_pos <= close_pos:
            return m.group(1), paren_start
    return None, -1


def _lookup_call_target(*, target_name: str, server_mod):
    """Look up `target_name` (after dot-stripping) as a label or screen.

    Uses the symbol snapshot first (cross-file stable), with a fallback
    to the live analyzer (for the brief window between `did_change` and
    the next snapshot refresh).

    Returns the label/screen symbol, or None if neither exists.
    """
    # Handle dotted names (label.sublabel) — take the last part for lookup.
    if "." in target_name:
        target_name = target_name.split(".")[-1]

    labels = server_mod._symbol_snapshot.get("labels", {})
    screens = server_mod._symbol_snapshot.get("screens", {})

    # Fallback: if not in snapshot, check analyzer directly (test scenarios,
    # or immediately after did_change before snapshot refresh).
    if target_name not in labels and server_mod._active_analyzer is not None:
        labels = server_mod._active_analyzer.labels
    if target_name not in screens and server_mod._active_analyzer is not None:
        screens = server_mod._active_analyzer.screens

    if target_name in labels:
        return labels[target_name]
    if target_name in screens:
        return screens[target_name]
    return None


def _build_signature_info(*, target_name: str, symbol) -> lsp.SignatureInformation:
    """Build a `SignatureInformation` for `call NAME(...)` / `use NAME(...)`.

    Returns a `SignatureInformation` even when the symbol has no
    parameters — the label will be `NAME()` with an empty `parameters`
    list. The original behavior (preserved by
    `test_signature_help_for_label_without_params`) was to return a
    non-None `SignatureHelp` in this case, so we never return None here.

    Default values are not shown because `SignatureInfo` only stores
    param names, not defaults.
    """
    sig = symbol.signature
    pos_names = sig.pos_names if (sig and sig.has_params) else []

    # Build "name(param1, param2)" style — names only, no defaults.
    params_str = ", ".join(pos_names)
    sig_label = f"{target_name}({params_str})"

    param_infos = [lsp.ParameterInformation(label=name) for name in pos_names]
    return lsp.SignatureInformation(
        label=sig_label,
        parameters=param_infos,
    )
