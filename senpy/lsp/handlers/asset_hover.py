"""Image / audio / video hover preview.

This module is the asset-hover half of the LSP `textDocument/hover` handler.
It is split out of `senpy/lsp/handlers/hover.py` for the same reason the
other handlers were split in 0.6.0-6: hover.py was already 167 lines and
adding three new hover branches (image, audio, video) inline would have
pushed it past the readability threshold.

Public entry points:
  - build_image_hover(line, col)            → lsp.Hover | None
  - build_audio_hover(line, col)            → lsp.Hover | None

The video case is dispatched from inside build_image_hover: when the
resolved file has a video extension, we render a "Play in default app"
command URI instead of an inline preview (VS Code's image viewer cannot
decode WebM/MP4).

Algorithm adapted from renpy-magic (MIT, Copyright (c) 2026 Allure
Diffusion). The data flow is:

    show/scene/hide | play music/sound/voice/audio | define audio.X
        ↓
    line regex match → asset name
        ↓
    AssetManager.resolve_{image,audio}_path(name) → disk path
        ↓
    image_size.markdown_size_param(path) → "|width=W" or "|height=H"
        ↓
    MarkupContent(markdown, "![name](file://...|width=W)" or "[Play](command:...)")

Caching strategy: image_path is extracted at index time and stored on
ImageSymbol; audio aliases are registered at index time via
AssetManager.register_audio_alias. Hover never re-reads source files.
"""

from __future__ import annotations

import os
import re

from lsprotocol import types as lsp

from senpy.domain.image_size import markdown_size_param

# Triggers: `show NAME attrs`, `scene NAME attrs`. We do not include `hide`
# in the image-hover trigger list because renpy-magic's own regex omits it
# (hide references are about dismissing, not displaying — previewing the
# asset is less useful there). We DO still suppress variable-hover inside
# hide tokens via the early-return in hover.py (the existing behavior).
_RE_SHOW_SCENE = re.compile(
    r"^\s*(show|scene)\s+(.+?)(?:\s+(?:at|with|as|behind|onlayer|zorder)\b|$)"
)
_RE_PLAY_QUEUE = re.compile(
    r"""^\s*(?:play|queue)\s+(?:music|sound|voice|audio)\s+(["']?)([a-zA-Z_][\w]*)\1"""
)
_RE_DEFINE_AUDIO = re.compile(r"^\s*define\s+audio\.([a-zA-Z_][\w]*)\s*=")
_RE_AUDIO_QUOTED_REF = re.compile(r"""["']([a-zA-Z_][\w]*)["']""")


def _get_server_mod():
    """Lazy access to senpy.lsp.server (breaks the import cycle)."""
    from senpy.lsp import server

    return server


def _path_to_file_uri(path: str) -> str:
    """Convert an absolute filesystem path to a `file://` URI."""
    from pathlib import Path

    return Path(os.path.abspath(path)).as_uri()


def _format_bytes(size: int) -> str:
    """Human-readable file size for hover metadata line."""
    n: float = size
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _resolve_image_disk_path(image_name: str) -> str | None:
    """Resolve a Ren'Py image reference (e.g. ``"eileen happy"``) to a disk
    path. Tries the ImageSymbol.image_path field first (for explicit
    ``image name = "file"`` declarations), then falls back to AssetManager
    auto-discovery.
    """
    server_mod = _get_server_mod()
    # state access via _lsp_server.active_analyzer property
    # (delegates to module global _active_analyzer).
    analyzer = server_mod._lsp_server.active_analyzer
    if analyzer is None:
        return None

    # 1. Explicit image declaration with a literal path.
    img_sym = analyzer.images.get(image_name)
    if img_sym is not None and img_sym.image_path:
        # image_path is relative to game/. Resolve to absolute via project root.
        candidate = _resolve_relative_to_game(img_sym.image_path, analyzer.project_path)
        if candidate and os.path.exists(candidate):
            return candidate

    # 2. Auto-discovery via AssetManager.
    return analyzer.assets.resolve_image_path(image_name)


def _resolve_relative_to_game(rel: str, project_path: str) -> str | None:
    """Try a few candidate absolute paths for a game/-relative reference.

    Resolves ``rel`` against ``project_path/game`` and ``project_path``,
    then verifies the resolved real path is still inside one of those
    roots. This blocks path-traversal payloads (``images/../../secret``,
    symlinks pointing outside the project, absolute paths that
    ``os.path.join`` would silently accept) — without it, hovering over a
    malicious ``image`` declaration disclosed the size and path of
    arbitrary files outside the project (info disclosure).

    The existing ``lstrip("./")`` accidentally neutralises payloads that
    START with ``.`` or ``/`` (e.g. ``../../etc/passwd`` → ``etc/passwd``,
    ``/etc/passwd`` → ``etc/passwd``), but a payload with a non-dot prefix
    like ``images/../../secret`` slips through. The realpath+commonpath
    check is the real defence.
    """
    rel = rel.replace("\\", "/").lstrip("./")
    game_root = os.path.realpath(os.path.join(project_path, "game"))
    proj_root = os.path.realpath(project_path)
    for base in (game_root, proj_root):
        candidate = os.path.realpath(os.path.join(base, rel))
        try:
            # commonpath returns the longest common sub-path of both args.
            # If candidate is inside base, commonpath == base. If candidate
            # escaped base via ``..`` or a symlink, commonpath != base.
            if os.path.commonpath([candidate, base]) == base and os.path.exists(candidate):
                return candidate
        except ValueError:
            # On Windows, commonpath raises ValueError when the two paths
            # are on different drives (e.g. C:\\project vs D:\\file).
            # That's a definite escape — skip this base.
            continue
    return None


def build_image_hover(line: str, col: int) -> lsp.Hover | None:
    """Build an image-preview hover for a `show`/`scene` line.

    Returns None if the cursor is not over the image-name token, or if no
    matching file is on disk.
    """
    m = _RE_SHOW_SCENE.match(line)
    if m is None:
        return None
    image_name = m.group(2).strip()
    if not image_name:
        return None

    # Cursor must be inside the image-name token span.
    span_start = m.start(2)
    span_end = m.end(2)
    if not (span_start <= col <= span_end):
        return None

    disk_path = _resolve_image_disk_path(image_name)
    if disk_path is None:
        return None

    file_uri = _path_to_file_uri(disk_path)
    server_mod = _get_server_mod()
    # state access via _lsp_server.active_analyzer property
    # (delegates to module global _active_analyzer).
    analyzer = server_mod._lsp_server.active_analyzer

    # Video: VS Code's image viewer cannot decode WebM/MP4. Render a
    # command URI that opens the file in the OS default app.
    if analyzer is not None and analyzer.assets.is_video_file(disk_path):
        return _build_video_hover(image_name, disk_path, file_uri)

    # Image: inline markdown preview with sizing.
    size_param = markdown_size_param(disk_path)
    size_suffix = f" {size_param}" if size_param else ""
    basename = os.path.basename(disk_path)
    try:
        size_bytes = os.path.getsize(disk_path)
        meta_line = f"*{basename} · {_format_bytes(size_bytes)}*\n\n"
    except OSError:
        meta_line = f"*{basename}*\n\n"

    content = f"**Image** — `{image_name}`\n\n{meta_line}![{image_name}]({file_uri}{size_suffix})"
    return lsp.Hover(contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=content))


def _build_video_hover(name: str, disk_path: str, file_uri: str) -> lsp.Hover:
    """Build a "Play in default app" hover for a video file."""
    basename = os.path.basename(disk_path)
    try:
        size_bytes = os.path.getsize(disk_path)
        meta_line = f"*{basename} · {_format_bytes(size_bytes)}*\n\n"
    except OSError:
        meta_line = f"*{basename}*\n\n"

    # command: URIs let VS Code invoke a registered command with arguments.
    # senpy.openExternal (registered in senpy-vscode/src/extension.ts) opens
    # the file via the OS default application. The argument is the file URI
    # itself, URL-encoded as JSON to survive Markdown link parsing.
    import json
    from urllib.parse import quote

    arg = json.dumps(file_uri)
    cmd_uri = f"command:senpy.openExternal?{quote(arg)}"

    content = f"**Video** — `{name}`\n\n{meta_line}▶ [Play video in default app]({cmd_uri})"
    return lsp.Hover(contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=content))


def build_audio_hover(line: str, col: int) -> lsp.Hover | None:
    """Build an audio-preview hover for a `play`/`queue`/`define audio.X`
    line.

    Returns None if the cursor is not over the audio name, or if no matching
    file is on disk.
    """
    server_mod = _get_server_mod()
    # state access via _lsp_server.active_analyzer property
    # (delegates to module global _active_analyzer).
    analyzer = server_mod._lsp_server.active_analyzer
    if analyzer is None:
        return None

    # Case 1: `play music NAME` / `queue sound NAME`
    audio_name: str | None = None
    span: tuple[int, int] | None = None
    m = _RE_PLAY_QUEUE.match(line)
    if m is not None:
        audio_name = m.group(2)
        span = (m.start(2), m.end(2))
    else:
        # Case 2: `define audio.NAME = "..."` — hover over NAME or the
        # quoted string both resolve to the same file.
        m2 = _RE_DEFINE_AUDIO.match(line)
        if m2 is not None:
            audio_name = m2.group(1)
            span = (m2.start(1), m2.end(1))
            # If cursor is inside the quoted string, also accept it.
            quoted = _RE_AUDIO_QUOTED_REF.search(line)
            if quoted is not None and quoted.start(1) <= col <= quoted.end(1):
                span = (quoted.start(1), quoted.end(1))

    if audio_name is None or span is None:
        return None
    if not (span[0] <= col <= span[1]):
        return None

    disk_path = analyzer.assets.resolve_audio_path(audio_name)
    if disk_path is None:
        return None

    file_uri = _path_to_file_uri(disk_path)
    basename = os.path.basename(disk_path)
    try:
        size_bytes = os.path.getsize(disk_path)
        meta_line = f"*{basename} · {_format_bytes(size_bytes)}*\n\n"
    except OSError:
        meta_line = f"*{basename}*\n\n"

    content = f"**Audio** — `{audio_name}`\n\n{meta_line}▶ [Play audio]({file_uri})"
    return lsp.Hover(contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=content))
