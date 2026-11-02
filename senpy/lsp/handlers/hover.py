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
    """Семантические подсказки при наведении курсора на переменные, метки и экраны."""
    server_mod = _get_server_mod()
    if server_mod._active_analyzer is None or not server_mod._is_initialized:
        return None

    doc = ls.workspace.get_text_document(params.text_document.uri)
    if not doc or not doc.lines:
        return None

    # P0-5: guard от IndexError при out-of-range line. Аналогичный guard есть
    # в definition() и references(), но в hover его не было. Это приводило к
    # падению сервера при hover в первые миллисекунды после did_change, когда
    # doc.lines ещё не обновился, либо при невалидном position от клиента.
    line_idx = params.position.line
    if line_idx >= len(doc.lines):
        return None

    line = doc.lines[line_idx]
    col = params.position.character
    stripped_line = line.strip()

    # Try asset hovers first (image / audio) — they suppress the variable
    # hover when the cursor is on a sprite/audio token.
    asset_hover = _try_asset_hover(line=line, col=col, stripped_line=stripped_line)
    if asset_hover is _SUPPRESS_HOVER:
        # Cursor is on an asset token that didn't produce a preview (e.g.
        # `hide sayori` or `show sayori <missing-attr>`). Suppress the
        # variable hover to avoid `define <attr> = Character(...)` noise.
        return None
    if asset_hover is not None:
        return asset_hover

    word = _word_at_position(line, col)
    if word is None:
        return None

    # Try Ren'Py API documentation first (config.*, gui.*, renpy.*, ...).
    api_hover = _hover_api_doc(word)
    if api_hover is not None:
        return api_hover

    # Then user-defined symbols: variable → label → screen.
    return (
        _hover_variable(word, server_mod)
        or _hover_label(word, server_mod)
        or _hover_screen(word, server_mod)
    )


def _word_at_position(line: str, col: int) -> str | None:
    r"""Return the dotted-identifier word at the given column, or None.

    Matches `[^\W\d][\w\.]*` (a Python-ish identifier with dots, not starting
    with a digit). This is the same regex the original `hover` used.
    """
    for m in re.finditer(r"[^\W\d][\w\.]*", line):
        if m.start() <= col <= m.end():
            return m.group(0)
    return None


def _try_asset_hover(*, line: str, col: int, stripped_line: str) -> lsp.Hover | None | object:
    """Try image (show/scene/hide) and audio (play/queue/define audio) hovers.

    Returns:
        - `lsp.Hover` if a real asset preview was produced.
        - `_SUPPRESS_HOVER` (sentinel) if the cursor is on an asset-context
          token that did not produce a preview. The caller treats this as
          "suppress the symbol hover" — e.g. `hide sayori` should NOT show
          `define sayori = Character(...)`.
        - `None` if the line is not an asset line at all — fall through to
          symbol hover.
    """
    if stripped_line.startswith(("show ", "scene ", "hide ")):
        return _hover_image_token(line=line, col=col, stripped_line=stripped_line)

    if _is_audio_line(stripped_line):
        from senpy.lsp.handlers.asset_hover import build_audio_hover

        # Audio hover either resolves to a real preview, or falls through
        # to the variable hover (e.g. user hovering a real variable named
        # `music`). So return the audio hover only if it's not None.
        return build_audio_hover(line, col)

    return None  # Not an asset line — fall through to symbol hover.


_SUPPRESS_HOVER = object()  # sentinel: "cursor on asset token, suppress symbol hover"


def _hover_image_token(*, line: str, col: int, stripped_line: str) -> lsp.Hover | None | object:
    """Handle hover on `show`/`scene`/`hide` image tokens.

    Returns:
        - `lsp.Hover` if `build_image_hover` produced a preview (show/scene
          only — `hide` doesn't preview).
        - `_SUPPRESS_HOVER` (sentinel) if the cursor is on an image
          token but no preview was produced. This tells the caller to
          suppress the variable hover (so `show sayori happy` doesn't
          trigger `define happy = Character(...)`).
        - `None` if the cursor is not on an image token at all —
          fall through to symbol hover.
    """
    parts = stripped_line.split()[1:]
    img_tokens: list[str] = []
    from senpy.core.constants import CLAUSE_KEYWORDS

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
        return None  # cursor not on the image tag

    if stripped_line.startswith(("show ", "scene ")):
        from senpy.lsp.handlers.asset_hover import build_image_hover

        image_hover = build_image_hover(line, col)
        if image_hover is not None:
            return image_hover
    # Either: cursor on a hide token, or image not on disk. Either way,
    # suppress the variable hover to avoid showing `define happy = ...`
    # when the user hovers over `show sayori happy`.
    return _SUPPRESS_HOVER


def _is_audio_line(stripped_line: str) -> bool:
    """Return True if `stripped_line` is `play X NAME`, `queue X NAME`, or
    `define audio.NAME = "..."`.
    """
    stripped_lower = stripped_line.lower()
    if stripped_lower.startswith(("play ", "queue ")) and any(
        stripped_lower.startswith(f"{kw} {ch} ")
        for kw in ("play", "queue")
        for ch in ("music", "sound", "voice", "audio")
    ):
        return True
    return bool(stripped_lower.startswith("define audio."))


def _hover_api_doc(word: str) -> lsp.Hover | None:
    """Try Ren'Py API documentation hover for `word` (config.*, gui.*, ...)."""
    api_content = get_renpy_api_hover(word)
    if not api_content:
        return None
    return lsp.Hover(contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=api_content))


def _hover_variable(word: str, server_mod) -> lsp.Hover | None:
    """Try hover for a `define`/`default` variable.

    Resolves dotted access (`player.name` → look up `name`) against the
    snapshot. Returns None if `word` is not a declared variable.
    """
    variables = server_mod._symbol_snapshot["variables"]
    target_var = word if word in variables else word.split(".")[-1]
    if target_var not in variables:
        return None

    var = variables[target_var]
    fname = os.path.basename(var.file_path)
    kind = "Constant (`define`)" if var.is_constant else "Variable (`default`)"
    # UX: clickable Markdown link to file:// URI with #L<line> anchor.
    # VS Code opens the file at the right line on click in the hover card.
    decl_uri = server_mod._path_to_uri(var.file_path)
    content = (
        f"**Ren'Py {kind}** — `{target_var}`\n\n"
        f"*Declared at [`{fname}:{var.line_number}`]({decl_uri}#L{var.line_number})*\n"
        f"```renpy\n{var.code_line}\n```"
    )
    return lsp.Hover(contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=content))


def _hover_label(word: str, server_mod) -> lsp.Hover | None:
    """Try hover for a label, including clickable jump-target links."""
    labels = server_mod._symbol_snapshot["labels"]
    if word not in labels:
        return None

    lbl = labels[word]
    fname = os.path.basename(lbl.file_path)
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
        jump_links = []
        for j in sorted(lbl.outgoing_jumps)[:4]:
            if j in labels:
                target = labels[j]
                target_uri = server_mod._path_to_uri(target.file_path)
                jump_links.append(f"[`{j}`]({target_uri}#L{target.line_number})")
            else:
                # Label not found (might be RPY302 broken jump) — just show as code
                jump_links.append(f"`{j}`")
        status.append(f"➔ Jumps to: {', '.join(jump_links)}")
    if status:
        info_lines.append("\n" + " • ".join(status))

    return lsp.Hover(
        contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value="\n".join(info_lines))
    )


def _hover_screen(word: str, server_mod) -> lsp.Hover | None:
    """Try hover for a screen declaration."""
    screens = server_mod._symbol_snapshot["screens"]
    if word not in screens:
        return None

    scr = screens[word]
    fname = os.path.basename(scr.file_path)
    decl_uri = server_mod._path_to_uri(scr.file_path)
    content = (
        f"**Ren'Py Screen** — `{word}`\n\n"
        f"*Declared at [`{fname}:{scr.line_number}`]({decl_uri}#L{scr.line_number})*"
    )
    return lsp.Hover(contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=content))
