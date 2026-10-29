"""LSP handlers: hover.

Вынесено из senpy/lsp/server.py в 0.6.0-6 (Фаза 5).

Handler'ы:
  - hover              ← TEXT_DOCUMENT_HOVER

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

from senpy.domain.renpy_api import get_renpy_api_hover


def _get_server_mod():
    """Ленивый доступ к senpy.lsp.server, разрывает цикл импортов."""
    from senpy.lsp import server
    return server


def hover(ls: LanguageServer, params: lsp.HoverParams) -> lsp.Hover | None:
    server_mod = _get_server_mod()
    """Семантические подсказки при наведении курсора мыши на переменные, метки и экраны."""
    if server_mod._active_analyzer is None or not server_mod._is_initialized:
        return None

    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc or not doc.lines:
        return None

    # P0-5: guard от IndexError при out-of-range line. Аналогичный guard есть
    # в definition() (server.py:394) и references() (server.py:539), но в hover
    # его не было. Это приводило к падению сервера при hover в первые миллисекунды
    # после did_change, когда doc.lines ещё не обновился, либо при невалидном
    # position от клиента.
    line_idx = params.position.line
    if line_idx >= len(doc.lines):
        return None

    line = doc.lines[line_idx]
    col = params.position.character

    word = None
    for m in re.finditer(r"[^\W\d][\w\.]*", line):
        if m.start() <= col <= m.end():
            word = m.group(0)
            break

    if not word:
        return None

    api_content = get_renpy_api_hover(word)
    if api_content:
        return lsp.Hover(
            contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=api_content)
        )

    target_var = word if word in server_mod._symbol_snapshot["variables"] else word.split(".")[-1]
    if target_var in server_mod._symbol_snapshot["variables"]:
        var = server_mod._symbol_snapshot["variables"][target_var]
        fname = os.path.basename(var.file_path)
        kind = "Constant (`define`)" if var.is_constant else "Variable (`default`)"
        # UX-EXT-6: кликабельная Markdown-ссылка на file:// URI с #L<line> anchor.
        # VS Code откроет файл на нужной строке при клике в hover-карточке.
        decl_uri = server_mod._path_to_uri(var.file_path)
        content = (
            f"**Ren'Py {kind}** — `{target_var}`\n\n"
            f"*Declared at [`{fname}:{var.line_number}`]({decl_uri}#L{var.line_number})*\n"
            f"```renpy\n{var.code_line}\n```"
        )
        return lsp.Hover(contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=content))

    if word in server_mod._symbol_snapshot["labels"]:
        lbl = server_mod._symbol_snapshot["labels"][word]
        fname = os.path.basename(lbl.file_path)
        # UX-EXT-6: кликабельная ссылка на объявление
        decl_uri = server_mod._path_to_uri(lbl.file_path)
        info_lines = [
            f"**Ren'Py Label** — `{word}`\n\n"
            f"*Declared at [`{fname}:{lbl.line_number}`]({decl_uri}#L{lbl.line_number})*"
        ]
        info_lines.append(f"```renpy\n{lbl.code_line}\n```")

        status = []
        if lbl.has_return:
            status.append("✔ Has return")
        if lbl.outgoing_jumps:
            status.append(
                f"➔ Jumps to: {', '.join(f'`{j}`' for j in sorted(lbl.outgoing_jumps)[:4])}"
            )
        if status:
            info_lines.append("\n" + " • ".join(status))

        return lsp.Hover(
            contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value="\n".join(info_lines))
        )

    if word in server_mod._symbol_snapshot["screens"]:
        scr = server_mod._symbol_snapshot["screens"][word]
        fname = os.path.basename(scr.file_path)
        # UX-EXT-6: кликабельная ссылка на объявление
        decl_uri = server_mod._path_to_uri(scr.file_path)
        content = (
            f"**Ren'Py Screen** — `{word}`\n\n"
            f"*Declared at [`{fname}:{scr.line_number}`]({decl_uri}#L{scr.line_number})*"
        )
        return lsp.Hover(contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=content))

    return None
