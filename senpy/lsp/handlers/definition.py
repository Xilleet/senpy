"""LSP handler: textDocument/definition (F12).

Extracted from senpy/lsp/handlers/navigation.py.
Resolves cursor position → definition location for labels, screens,
transforms, variables, images, and quoted asset paths.
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
from senpy.lsp.handlers._shared import (
    _get_server_mod,
    _location_at_symbol_line,
    _word_at_position,
)


def definition(ls: LanguageServer, params: lsp.DefinitionParams) -> lsp.Location | None:
    """Native F12 navigation to labels, screens, variables, sprites and asset files."""
    server_mod = _get_server_mod()
    # Phase 3.3c-e: state via _lsp_server.<attr>.
    lsp_server = server_mod._lsp_server
    if lsp_server.active_analyzer is None or not lsp_server.is_initialized:
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


def _resolve_quoted_path(*, line: str, col: int, server_mod) -> lsp.Location | None:
    """Phase 1: if the cursor is inside a quoted string, try to resolve it
    as a media-file path (relative to `game/` or as a basename match).
    """
    # Phase 3.3c-e: state via _lsp_server.<attr>.
    lsp_server = server_mod._lsp_server
    for qm in re.finditer(r'("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')', line):
        if not (qm.start() <= col <= qm.end()):
            continue
        raw_path = qm.group(0)[1:-1].strip()
        norm_q = raw_path.replace("\\", "/").lower()
        norm_q = re.sub(r"^<[^>]+>\s*", "", norm_q)
        base_q = os.path.basename(norm_q)

        for rel_path, full_path in lsp_server.active_analyzer.media_disk_files.items():
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
    # Phase 3.3c-e: state via _lsp_server.<attr>.
    lsp_server = server_mod._lsp_server
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
        if candidate in lsp_server.active_analyzer.images:
            img = lsp_server.active_analyzer.images[candidate]
            return _location_at_symbol_line(server_mod, img, len(candidate))

    # Fall back to media-file path matching (auto-discovered images).
    for candidate in (full_tag, base_tag):
        cand_norm = candidate.lower()
        for rel_path, full_path in lsp_server.active_analyzer.media_disk_files.items():
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
    # Phase 3.3c-e: state via _lsp_server.<attr>.
    lsp_server = server_mod._lsp_server
    analyzer = lsp_server.active_analyzer

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
