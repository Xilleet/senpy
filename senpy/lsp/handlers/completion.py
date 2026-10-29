"""LSP handlers: completion.

Вынесено из senpy/lsp/server.py в 0.6.0-5 (Фаза 5).

Handler'ы:
  - completions        ← TEXT_DOCUMENT_COMPLETION

Все функции принимают (ls, params) и обращаются к shared state через
server_mod._X (lazy import разрывает цикл импортов).
"""
from __future__ import annotations

import os
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
