"""LSP handlers: diagnostics.

Вынесено из senpy/lsp/server.py в 0.6.0-7 (Фаза 5).

Handler'ы:
  - code_action        ← TEXT_DOCUMENT_CODE_ACTION

Все функции принимают (ls, params) и обращаются к shared state через
server_mod._X (lazy import разрывает цикл импортов).
"""
from __future__ import annotations

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


def code_action(ls: LanguageServer, params: lsp.CodeActionParams) -> list[lsp.CodeAction]:
    server_mod = _get_server_mod()
    actions: list[lsp.CodeAction] = []
    try:
        uri = params.text_document.uri
        # P0-6: единая нормализация через server_mod._normalize_path (с os.path.abspath),
        # как и во всех остальных местах. Раньше тут было os.path.normcase()
        # без abspath, из-за чего lookup промахивался и срабатывал
        # basename-fallback, который в multi-module проектах мог выбрать
        # QuickFix из неправильного файла.
        norm_path = server_mod._normalize_path(server_mod._uri_to_path(uri))

        diags_for_file = server_mod._latest_diagnostics_by_path.get(norm_path)
        # P0-6: basename-fallback УБРАН. Если diagnostics для файла не найдены
        # через точный путь — возвращаем пустой список, как и должно быть.
        # Если lookup промахивается, это баг в нормализации, его надо чинить
        # в server_mod._normalize_path, а не обходить небезопасным угадыванием по basename.
        if not diags_for_file:
            return actions

        cursor_start = params.range.start.line
        cursor_end = params.range.end.line
        context_codes = {d.code for d in (params.context.diagnostics or []) if d.code}

        for diag, lsp_diag in diags_for_file:
            diag_line = max(0, diag.line_number - 1)
            is_on_cursor_line = cursor_start <= diag_line <= cursor_end
            is_in_context = diag.code in context_codes

            if not (is_on_cursor_line or is_in_context):
                continue

            if not (diag.fix_title and diag.fix_replacement):
                continue

            fix_start = getattr(diag, "fix_start_col", None)
            fix_end = getattr(diag, "fix_end_col", None)

            if fix_start is not None and fix_end is not None:
                edit_range = lsp.Range(
                    start=lsp.Position(line=diag_line, character=fix_start),
                    end=lsp.Position(line=diag_line, character=fix_end),
                )
            elif diag.code == "RPY301":
                raw = diag.line_content
                q_pos = max(raw.rfind('"'), raw.rfind("'"))
                ins_char = (
                    len(raw[:q_pos].encode("utf-16-le")) // 2
                    if q_pos != -1
                    else lsp_diag.range.end.character
                )
                edit_range = lsp.Range(
                    start=lsp.Position(line=diag_line, character=ins_char),
                    end=lsp.Position(line=diag_line, character=ins_char),
                )
            else:
                edit_range = lsp_diag.range

            action = lsp.CodeAction(
                title=f"Senpy: {diag.fix_title}",
                kind=lsp.CodeActionKind.QuickFix,
                diagnostics=[lsp_diag],
                is_preferred=True,
                edit=lsp.WorkspaceEdit(
                    changes={
                        uri: [
                            lsp.TextEdit(
                                range=edit_range,
                                new_text=diag.fix_replacement,
                            )
                        ]
                    }
                ),
            )
            actions.append(action)

    except (KeyError, IndexError, ValueError, AttributeError) as e:
        ls.show_message_log(f"Error in code_action: {e}")

    return actions
