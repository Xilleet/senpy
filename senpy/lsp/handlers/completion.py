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

if TYPE_CHECKING:
    try:
        from pygls.lsp.server import LanguageServer
    except ImportError:
        from pygls.server import LanguageServer

from lsprotocol import types as lsp


def _get_server_mod():
    """Ленивый доступ к senpy.lsp.server, разрывает цикл импортов."""
    from senpy.lsp import server
    return server


def completions(ls: LanguageServer, params: lsp.CompletionParams) -> lsp.CompletionList:
    server_mod = _get_server_mod()
    """Контекстный автокомплит для меток, спрайтов и экранов."""
    items: list[lsp.CompletionItem] = []
    if server_mod._active_analyzer is None or not server_mod._is_initialized:
        ls.show_message_log(
            f"[completions] NOT INITIALIZED: analyzer={server_mod._active_analyzer is not None}, "
            f"init={server_mod._is_initialized}"
        )
        return lsp.CompletionList(is_incomplete=False, items=items)

    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc:
        ls.show_message_log("[completions] no doc")
        return lsp.CompletionList(is_incomplete=False, items=items)

    if params.position.line >= len(doc.lines):
        ls.show_message_log(
            f"[completions] line {params.position.line} out of range "
            f"(doc has {len(doc.lines)} lines)"
        )
        return lsp.CompletionList(is_incomplete=False, items=items)

    line = doc.lines[params.position.line]
    prefix = line[: params.position.character].lstrip()

    # UX-EXT-5 DEBUG: log what we receive + snapshot state
    ls.show_message_log(
        f"[completions] prefix={prefix!r}, "
        f"snapshot_labels={len(server_mod._symbol_snapshot['labels'])}, "
        f"live_labels={len(server_mod._active_analyzer.labels)}, "
        f"snapshot_images={len(server_mod._symbol_snapshot['images'])}, "
        f"snapshot_screens={len(server_mod._symbol_snapshot['screens'])}, "
        f"snapshot_transforms={len(server_mod._symbol_snapshot['transforms'])}"
    )

    # 1. Автокомплит меток для jump / call
    if prefix.startswith(("jump ", "call ")):
        # UX-EXT-5: используем snapshot, не server_mod._active_analyzer.labels,
        # потому что analyze_file_only очищает labels из других файлов.
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

    # 2. Автокомплит экранов для show screen / call screen / use
    elif prefix.startswith(("show screen ", "call screen ", "use ")):
        for screen_name, scr in sorted(server_mod._symbol_snapshot["screens"].items()):
            items.append(
                lsp.CompletionItem(
                    label=screen_name,
                    kind=lsp.CompletionItemKind.Interface,
                    detail=f"Screen ({os.path.basename(scr.file_path)}:{scr.line_number})",
                )
            )

    # 3. Автокомплит спрайтов, атрибутов и трансформаций для show / scene
    elif prefix.startswith(("show ", "scene ")):
        if " at " in prefix or prefix.endswith(" at"):
            standard_positions = [
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
            ]
            for pos in standard_positions:
                items.append(
                    lsp.CompletionItem(
                        label=pos,
                        kind=lsp.CompletionItemKind.EnumMember,
                        detail="Position (Built-in)",
                    )
                )
            for trans_name, trans_sym in sorted(server_mod._symbol_snapshot["transforms"].items()):
                items.append(
                    lsp.CompletionItem(
                        label=trans_name,
                        kind=lsp.CompletionItemKind.Function,
                        detail=f"Transform ({os.path.basename(trans_sym.file_path)}:{trans_sym.line_number})",
                    )
                )
        else:
            tokens = prefix.split()
            if len(tokens) == 1 or (len(tokens) == 2 and not prefix.endswith(" ")):
                all_tags = {img.split()[0] for img in server_mod._symbol_snapshot["images"]}
                for tag in sorted(all_tags):
                    items.append(
                        lsp.CompletionItem(
                            label=tag,
                            kind=lsp.CompletionItemKind.Class,
                            detail="Sprite Tag",
                        )
                    )
            elif len(tokens) >= 2:
                base_tag = tokens[1]
                # UX-EXT-5: используем snapshot для images, но valid_images
                # берём из server_mod._active_analyzer (он не чистится analyze_file_only).
                all_valid = server_mod._active_analyzer.valid_images.union(server_mod._symbol_snapshot["images"])
                attrs = server_mod._active_analyzer._get_tag_known_attributes(base_tag, all_valid)
                for attr in sorted(attrs):
                    items.append(
                        lsp.CompletionItem(
                            label=attr,
                            kind=lsp.CompletionItemKind.EnumMember,
                            detail=f"Attribute for '{base_tag}'",
                        )
                    )

    # UX-EXT-5 DEBUG: log result
    ls.show_message_log(
        f"[completions] RETURN {len(items)} items "
        f"(prefix={prefix!r}, snapshot_labels={len(server_mod._symbol_snapshot['labels'])})"
    )

    return lsp.CompletionList(is_incomplete=False, items=items)


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
    segment = line[paren_start + 1:cursor_pos]
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


def signature_help(
    ls: LanguageServer, params: lsp.SignatureHelpParams
) -> lsp.SignatureHelp | None:
    """LSP-6: Provide parameter hints for call label(...) / use screen(...).

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

    # Find call/use pattern on this line, with cursor inside the parens
    match = None
    paren_start = -1
    for m in _RE_CALL_USE.finditer(line):
        # Check if cursor is after the opening paren
        if m.end() - 1 <= cursor_pos:  # cursor is at or after the `(`
            # Find closing paren
            paren_start = m.end() - 1
            # Find closing paren after cursor
            close_pos = line.find(")", cursor_pos)
            if close_pos == -1:
                close_pos = len(line)
            if paren_start <= cursor_pos <= close_pos:
                match = m
                break
    else:
        return None  # no call/use pattern with cursor inside

    if match is None:
        return None

    target_name = match.group(1)
    # Handle dotted names (label.sublabel) — take the last part for lookup
    if "." in target_name:
        target_name = target_name.split(".")[-1]

    # Look up in labels and screens (snapshot for cross-file stability,
    # fallback to analyzer for cases where snapshot is not yet refreshed)
    labels = server_mod._symbol_snapshot.get("labels", {})
    screens = server_mod._symbol_snapshot.get("screens", {})
    # Fallback: if not in snapshot, check analyzer directly (test scenarios,
    # or immediately after did_change before snapshot refresh)
    if target_name not in labels and server_mod._active_analyzer is not None:
        labels = server_mod._active_analyzer.labels
    if target_name not in screens and server_mod._active_analyzer is not None:
        screens = server_mod._active_analyzer.screens

    symbol = None
    is_label = False
    if target_name in labels:
        symbol = labels[target_name]
        is_label = True
    elif target_name in screens:
        symbol = screens[target_name]
    else:
        return None  # unknown label/screen

    # Build signature label
    sig = symbol.signature
    if sig and sig.has_params:
        # Build "name(param1, param2=default)" style
        param_parts = []
        for i, name in enumerate(sig.pos_names):
            param_parts.append(name)
        # Note: we don't have default values in SignatureInfo, only names
        # So we just show names. If we had defaults, we'd append "=default"
        params_str = ", ".join(param_parts)
    else:
        params_str = ""

    sig_label = f"{target_name}({params_str})"

    # Build ParameterInformation list
    param_infos: list[lsp.ParameterInformation] = []
    if sig and sig.has_params:
        for name in sig.pos_names:
            param_infos.append(lsp.ParameterInformation(label=name))

    sig_info = lsp.SignatureInformation(
        label=sig_label,
        parameters=param_infos,
    )

    # Calculate active parameter (which param cursor is on)
    active_param = _count_active_parameter(line, cursor_pos, paren_start)
    if active_param >= len(param_infos):
        active_param = max(0, len(param_infos) - 1)

    return lsp.SignatureHelp(
        signatures=[sig_info],
        active_signature=0,
        active_parameter=active_param,
    )
