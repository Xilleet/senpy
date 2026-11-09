"""image / audio / video hover preview tests.

Covers the three asset-hover code paths added in :
  1. Image hover — `show eileen happy` returns Markdown with an inline
     `![eileen happy](file://...|width=W)` preview.
  2. Audio hover — `play music bgm_calm` returns Markdown with a
     `[Play audio](file://...)` link.
  3. Video hover — `image intro = "intro.webm"` resolves to a video file
     and the hover returns a `command:senpy.openExternal?...` link (VS
     Code's image viewer cannot decode WebM).
  4. Define-audio hover — `define audio.calm = "calm.ogg"` followed by
     `play music calm` resolves via the alias map.
  5. Suppression — `hide sayori` still suppresses variable hover (the
     pre behavior) without trying to preview an asset.

The unit-test for the lightweight image-size parser (PNG/JPEG/WEBP/GIF/BMP
header walkers) is also here, since it is exercised by the image hover.
"""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from lsprotocol import types as lsp

import senpy.lsp.server as server_mod
from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.file_collector import _extract_string_literal as _extract_string_literal_analyzer
from senpy.domain.image_size import (
    clamp_to_hover_box,
    get_image_size,
    markdown_size_param,
)

# Reuse the mock infra from test_lsp.py
from tests._helpers.lsp import MockDocument, MockWorkspace, setup_test_workspace
from tests._helpers.paths import (
    EXTENSION_TS,
    VSCODE_PACKAGE_JSON,
)

# =============================================================================
# Helpers
# =============================================================================


def _make_minimal_png(width: int, height: int) -> bytes:
    """Build a minimal valid 1x1-color PNG with the given dimensions in
    the IHDR. Used so the test does not need any external image assets.
    """
    sig = b"\x89PNG\r\n\x1a\n"
    # IHDR: 13-byte payload (width, height, bitdepth=8, colortype=2, ...)
    ihdr_payload = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    crc = 0  # tests don't need a valid CRC; parser doesn't verify it
    ihdr = struct.pack(">I", len(ihdr_payload)) + b"IHDR" + ihdr_payload + struct.pack(">I", crc)
    return sig + ihdr


def _make_minimal_jpeg(width: int, height: int) -> bytes:
    """Build a minimal JPEG byte stream with an SOF0 segment carrying the
    given width/height. Header parser walks markers — doesn't need pixel
    data.
    """
    soi = b"\xff\xd8"  # SOI
    # SOF0 marker: 0xFFC0, length=17 (incl. its own 2 bytes), precision=8,
    # height=H, width=W, components=3 (Y/Cb/Cr) each 0x11 0x00.
    sof_payload = struct.pack(">BHH", 8, height, width) + b"\x03\x11\x00\x11\x00\x11\x00"
    sof = b"\xff\xc0" + struct.pack(">H", len(sof_payload) + 2) + sof_payload
    return soi + sof


def _make_minimal_webp(width: int, height: int, chunk: bytes = b"VP8 ") -> bytes:
    """Build a minimal WEBP header. For VP8 (lossy) the width/height live
    at offset 26..30 as little-endian uint16. For VP8L/VP8X the layout
    differs — see senpy/domain/image_size.py.

    Layout: RIFF(4) + filesize(4) + WEBP(4) + chunk_id(4) + chunk_size(4)
    + chunk_payload. The parser keys off chunk_id and reads dimensions at
    fixed offsets within the chunk payload.
    """
    riff = b"RIFF"
    file_size = 0  # parser doesn't check
    webp_sig = b"WEBP"
    if chunk == b"VP8 ":
        # VP8 keyframe: 3 bytes frame tag + 3 bytes PSC (0x9D 0x01 0x2A)
        # + 2 bytes width-1 (LE 14-bit) + 2 bytes height-1. The parser
        # reads the 2 uint16s at file offset 26..30, which is payload
        # offset 6..10. We pad frame tag + PSC with 6 zero bytes.
        payload = b"\x00" * 6 + struct.pack("<HH", width - 1, height - 1)
    elif chunk == b"VP8L":
        # VP8L signature byte (0x2F), then 14 bits width-1, 14 bits height-1
        # packed little-endian-bit across 4 bytes.
        w = width - 1
        h = height - 1
        b0 = w & 0xFF
        b1 = ((w >> 8) & 0x3F) | ((h & 0x03) << 6)
        b2 = (h >> 2) & 0xFF
        b3 = (h >> 10) & 0x0F
        payload = b"\x2f" + bytes([b0, b1, b2, b3])
    elif chunk == b"VP8X":
        # VP8X: 1 byte flags, 3 bytes reserved, then 24-bit width-1, 24-bit
        # height-1 (little-endian byte order).
        w = width - 1
        h = height - 1
        payload = b"\x00\x00\x00\x00" + bytes(
            [
                w & 0xFF,
                (w >> 8) & 0xFF,
                (w >> 16) & 0xFF,
                h & 0xFF,
                (h >> 8) & 0xFF,
                (h >> 16) & 0xFF,
            ]
        )
    else:
        raise ValueError(f"unsupported chunk: {chunk!r}")
    body = chunk + struct.pack("<I", len(payload)) + payload
    return riff + struct.pack("<I", file_size) + webp_sig + body


def _make_minimal_gif(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00\x00\x00"


def _make_minimal_bmp(width: int, height: int) -> bytes:
    # BM, filesize=0, reserved=0, offset=54; BITMAPINFOHEADER (40 bytes).
    return (
        b"BM"
        + struct.pack("<I", 0)
        + struct.pack("<HH", 0, 0)
        + struct.pack("<I", 54)
        + struct.pack("<I", 40)
        + struct.pack("<i", width)
        + struct.pack("<i", height)
        + struct.pack("<HH", 1, 24)
        + struct.pack("<I", 0)
        + b"\x00" * 24
    )


def _setup_asset_workspace(
    tmp_path: Path, images: dict[str, bytes], audio: dict[str, bytes] | None = None
):
    """Create a test Ren'Py project with image and audio assets on disk.

    *images* maps a rel path (e.g. ``"images/eileen happy.png"``) to file
    bytes. A key starting with ``"decl:"`` means: write the file at the
    suffix path AND emit an explicit ``image NAME = "SUFFIX"`` declaration
    so ImageSymbol.image_path extraction is exercised. *audio* maps
    ``"audio/bgm_calm.ogg"`` to file bytes (audio bytes can be empty —
    the parser doesn't read audio headers).
    """
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)

    decl_image_lines: list[str] = []
    for rel, payload in images.items():
        if rel.startswith("decl:"):
            clean = rel.removeprefix("decl:")
            # Write the file at the clean path (no colon in filename).
            full = game_dir / clean
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_bytes(payload)
            # Emit `image NAME = "clean"` declaration.
            name = Path(clean).stem.replace("_", " ")
            decl_image_lines.append(f'image {name} = "{clean}"')
        else:
            full = game_dir / rel
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_bytes(payload)

    if audio:
        for rel, payload in audio.items():
            full = game_dir / rel
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_bytes(payload)

    script_lines = list(decl_image_lines)
    # Always include a start label so the analyzer has something to chew on.
    script_lines.append("label start:")
    script_lines.append("    return")
    (game_dir / "script.rpy").write_text("\n".join(script_lines) + "\n", encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)
    server_mod._active_analyzer = analyzer
    server_mod._is_initialized = True
    server_mod._refresh_symbol_snapshot()
    return analyzer


def _do_hover(uri: str, line: str, col: int) -> lsp.Hover | None:
    """Run the LSP hover handler on a synthetic single-line document."""
    doc = MockDocument(uri, line)
    mock_ls = MagicMock()
    mock_ls.workspace = MockWorkspace(doc)
    return server_mod.hover(
        mock_ls,
        lsp.HoverParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri),
            position=lsp.Position(line=0, character=col),
        ),
    )


# =============================================================================
# image_size.py — header parser unit tests
# =============================================================================


class TestImageSizeParser:
    """Direct unit tests for the lightweight PNG/JPEG/WEBP/GIF/BMP parser."""

    def test_png(self, tmp_path):
        p = tmp_path / "test.png"
        p.write_bytes(_make_minimal_png(800, 600))
        assert get_image_size(p) == (800, 600)

    def test_jpeg(self, tmp_path):
        p = tmp_path / "test.jpg"
        p.write_bytes(_make_minimal_jpeg(1024, 768))
        assert get_image_size(p) == (1024, 768)

    def test_webp_vp8(self, tmp_path):
        p = tmp_path / "test.webp"
        p.write_bytes(_make_minimal_webp(500, 400, b"VP8 "))
        assert get_image_size(p) == (500, 400)

    def test_webp_vp8l(self, tmp_path):
        p = tmp_path / "test_lossless.webp"
        p.write_bytes(_make_minimal_webp(300, 200, b"VP8L"))
        assert get_image_size(p) == (300, 200)

    def test_webp_vp8x(self, tmp_path):
        p = tmp_path / "test_ext.webp"
        p.write_bytes(_make_minimal_webp(1000, 500, b"VP8X"))
        assert get_image_size(p) == (1000, 500)

    def test_gif(self, tmp_path):
        p = tmp_path / "test.gif"
        p.write_bytes(_make_minimal_gif(320, 240))
        assert get_image_size(p) == (320, 240)

    def test_bmp(self, tmp_path):
        p = tmp_path / "test.bmp"
        p.write_bytes(_make_minimal_bmp(640, 480))
        assert get_image_size(p) == (640, 480)

    def test_unsupported_extension(self, tmp_path):
        p = tmp_path / "test.txt"
        p.write_bytes(b"not an image")
        assert get_image_size(p) is None

    def test_truncated_png(self, tmp_path):
        p = tmp_path / "trunc.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n")  # signature only, no IHDR
        assert get_image_size(p) is None

    def test_missing_file(self):
        # Should not raise; returns None.
        assert get_image_size("/nonexistent/path.png") is None


class TestClampToHoverBox:
    """Aspect-ratio-preserving clamp to 400x200."""

    def test_small_image_passthrough(self):
        # Smaller than 400x200 — no scaling.
        assert clamp_to_hover_box(100, 100) == (100, 100)

    def test_wide_image_clamped_by_width(self):
        # 800x100 → ratio 0.5 → 400x50.
        assert clamp_to_hover_box(800, 100) == (400, 50)

    def test_tall_image_clamped_by_height(self):
        # 100x400 → ratio 0.5 → 50x200.
        assert clamp_to_hover_box(100, 400) == (50, 200)

    def test_huge_image_uses_min_ratio(self):
        # 1600x800 → w_ratio=0.25, h_ratio=0.25 → 400x200.
        assert clamp_to_hover_box(1600, 800) == (400, 200)

    def test_zero_dimensions_fallback(self):
        assert clamp_to_hover_box(0, 0) == (400, 200)


class TestMarkdownSizeParam:
    """The `|width=W` / `|height=H` suffix builder."""

    def test_returns_empty_for_unsupported(self, tmp_path):
        p = tmp_path / "x.txt"
        p.write_bytes(b"")
        assert markdown_size_param(p) == ""

    def test_wide_image_emits_height(self, tmp_path):
        p = tmp_path / "x.png"
        p.write_bytes(_make_minimal_png(800, 100))
        # 800x100 → 400x50, width is binding (w < h after clamp? no, 400 > 50,
        # so width is the larger one). Our policy: emit width if w <= h.
        # Here 400 > 50, so we emit height.
        result = markdown_size_param(p)
        assert result.startswith("|")
        assert "50" in result

    def test_tall_image_emits_height(self, tmp_path):
        p = tmp_path / "x.png"
        p.write_bytes(_make_minimal_png(100, 800))
        # 100x800 → 25x200, w=25 < h=200, so emit width.
        result = markdown_size_param(p)
        assert result.startswith("|width=")


# =============================================================================
# _extract_string_literal — analyzer helper
# =============================================================================


class TestExtractStringLiteral:
    """ImageSymbol.image_path extraction via _extract_string_literal."""

    def test_double_quoted(self):
        assert _extract_string_literal_analyzer('"images/foo.png"') == "images/foo.png"

    def test_single_quoted(self):
        assert _extract_string_literal_analyzer("'images/bar.webp'") == "images/bar.webp"

    def test_in_transform_call(self):
        body = 'Transform("images/eileen.png", zoom=1.5)'
        assert _extract_string_literal_analyzer(body) == "images/eileen.png"

    def test_no_literal(self):
        assert _extract_string_literal_analyzer("some_python_expr(1, 2)") is None

    def test_empty(self):
        assert _extract_string_literal_analyzer("") is None
        assert _extract_string_literal_analyzer(None) is None

    def test_first_literal_wins(self):
        body = '"first.png" + "second.png"'
        assert _extract_string_literal_analyzer(body) == "first.png"

    def test_escaped_quote_inside(self):
        # `\"` inside a double-quoted string should not terminate it.
        body = r'"path/with\"escape.png"'
        # Our regex handles `\\.` so the escaped quote is consumed.
        result = _extract_string_literal_analyzer(body)
        assert result is not None
        assert "escape.png" in result


# =============================================================================
# Image hover — integration via server_mod.hover()
# =============================================================================


class TestImageHover:
    """End-to-end image hover tests through the public hover() entry point."""

    def test_show_with_image_on_disk_returns_preview(self, tmp_path):
        png = _make_minimal_png(800, 600)
        _setup_asset_workspace(
            tmp_path,
            images={"images/eileen happy.png": png},
        )
        uri = server_mod._path_to_uri(str(tmp_path / "game" / "script.rpy"))

        line = "    show eileen happy"
        # Cursor on "eileen" (col 9 = inside "eileen")
        hover = _do_hover(uri, line, 9)

        assert hover is not None
        content = hover.contents.value
        assert "**Image**" in content
        assert "eileen happy" in content
        # file:// URI should appear in the markdown image link
        assert "file://" in content
        # Sizing param present (PNG header was readable)
        assert "|" in content  # |width= or |height=
        # Image name should appear in the alt text
        assert "![eileen happy]" in content

    def test_scene_with_image(self, tmp_path):
        png = _make_minimal_png(640, 480)
        _setup_asset_workspace(tmp_path, images={"images/bg forest.png": png})
        uri = server_mod._path_to_uri(str(tmp_path / "game" / "script.rpy"))

        hover = _do_hover(uri, "    scene bg forest", 11)
        assert hover is not None
        assert "bg forest" in hover.contents.value

    def test_show_unknown_image_returns_none(self, tmp_path):
        # Image not on disk → no hover, fall through to None (which means
        # the LSP returns no tooltip for the show line).
        _setup_asset_workspace(tmp_path, images={})
        uri = server_mod._path_to_uri(str(tmp_path / "game" / "script.rpy"))

        hover = _do_hover(uri, "    show nonexistent_image", 9)
        # Returns None because: not in image_name_to_path, not in ImageSymbol.
        assert hover is None

    def test_hide_does_not_show_image_hover(self, tmp_path):
        # hide suppresses variable hover but does NOT preview (consistent
        # with renpy-magic's regex which excludes hide).
        png = _make_minimal_png(100, 100)
        _setup_asset_workspace(tmp_path, images={"images/eileen.png": png})
        uri = server_mod._path_to_uri(str(tmp_path / "game" / "script.rpy"))

        hover = _do_hover(uri, "    hide eileen", 9)
        assert hover is None

    def test_cursor_outside_image_token_returns_none(self, tmp_path):
        png = _make_minimal_png(100, 100)
        _setup_asset_workspace(tmp_path, images={"images/eileen.png": png})
        uri = server_mod._path_to_uri(str(tmp_path / "game" / "script.rpy"))

        # Cursor at col 0 — way before "show eileen".
        hover = _do_hover(uri, "    show eileen", 0)
        assert hover is None

    def test_image_declaration_with_literal_path(self, tmp_path):
        """ImageSymbol.image_path extraction — `image foo = "rel/path"`."""
        png = _make_minimal_png(200, 200)
        # Use the `decl:` prefix so _setup_asset_workspace emits an
        # `image foo = "images/foo.png"` declaration line.
        _setup_asset_workspace(tmp_path, images={"decl:images/foo.png": png})
        uri = server_mod._path_to_uri(str(tmp_path / "game" / "script.rpy"))

        # Show by the declared name.
        hover = _do_hover(uri, "    show foo", 9)
        assert hover is not None
        assert "foo" in hover.contents.value
        assert "file://" in hover.contents.value

    def test_image_with_attributes(self, tmp_path):
        png = _make_minimal_png(300, 300)
        _setup_asset_workspace(tmp_path, images={"images/eileen happy.png": png})
        uri = server_mod._path_to_uri(str(tmp_path / "game" / "script.rpy"))

        # `show eileen happy` — cursor over "happy" (col 16).
        # Hover should still resolve because "eileen happy" is the full
        # token, and our regex captures up to the first clause keyword.
        hover = _do_hover(uri, "    show eileen happy", 16)
        # Cursor on "happy" — full_tag is "eileen happy", span covers it.
        assert hover is not None
        assert "eileen happy" in hover.contents.value


# =============================================================================
# Audio hover
# =============================================================================


class TestAudioHover:
    """End-to-end audio hover tests."""

    def test_play_music_with_file_on_disk(self, tmp_path):
        _setup_asset_workspace(
            tmp_path,
            images={},
            audio={"audio/bgm_calm.ogg": b"\x00" * 32},  # bytes don't matter
        )
        uri = server_mod._path_to_uri(str(tmp_path / "game" / "script.rpy"))

        hover = _do_hover(uri, "    play music bgm_calm", 16)
        assert hover is not None
        content = hover.contents.value
        assert "**Audio**" in content
        assert "bgm_calm" in content
        assert "file://" in content
        assert "[Play audio]" in content

    def test_play_sound(self, tmp_path):
        _setup_asset_workspace(
            tmp_path,
            images={},
            audio={"audio/click.mp3": b"\x00" * 16},
        )
        uri = server_mod._path_to_uri(str(tmp_path / "game" / "script.rpy"))

        hover = _do_hover(uri, "    play sound click", 17)
        assert hover is not None
        assert "click" in hover.contents.value

    def test_queue_voice(self, tmp_path):
        _setup_asset_workspace(
            tmp_path,
            images={},
            audio={"audio/line01.ogg": b"\x00" * 16},
        )
        uri = server_mod._path_to_uri(str(tmp_path / "game" / "script.rpy"))

        hover = _do_hover(uri, "    queue voice line01", 17)
        assert hover is not None
        assert "line01" in hover.contents.value

    def test_define_audio_alias_then_play(self, tmp_path):
        """`define audio.X = "file.ogg"` registers X as an alias; hover
        over `play music X` resolves to the file."""
        _setup_asset_workspace(
            tmp_path,
            images={},
            audio={"audio/calm_track.ogg": b"\x00" * 16},
        )
        # Append a `define audio.calm = "audio/calm_track.ogg"` line.
        script_path = tmp_path / "game" / "script.rpy"
        original = script_path.read_text(encoding="utf-8")
        script_path.write_text(
            'define audio.calm = "audio/calm_track.ogg"\n' + original,
            encoding="utf-8",
        )
        # Re-run analyzer so the alias is registered.
        analyzer = SenpyAnalyzer(str(tmp_path))
        analyzer.run(quiet=True)
        server_mod._active_analyzer = analyzer
        server_mod._refresh_symbol_snapshot()

        uri = server_mod._path_to_uri(str(script_path))
        hover = _do_hover(uri, "    play music calm", 16)
        assert hover is not None
        assert "calm" in hover.contents.value
        assert "calm_track.ogg" in hover.contents.value  # basename appears in meta

    def test_play_unknown_audio_returns_none(self, tmp_path):
        _setup_asset_workspace(tmp_path, images={}, audio={})
        uri = server_mod._path_to_uri(str(tmp_path / "game" / "script.rpy"))

        hover = _do_hover(uri, "    play music nonexistent", 16)
        assert hover is None


# =============================================================================
# Video hover (command URI dispatch)
# =============================================================================


class TestVideoHover:
    """Video files route to a `command:senpy.openExternal?...` link."""

    def test_video_image_declaration(self, tmp_path):
        # Build a tiny .webm — content doesn't matter, we never decode it.
        # We use `decl:` so the analyzer emits `image intro = "intro.webm"`.
        _setup_asset_workspace(
            tmp_path,
            images={"decl:videos/intro.webm": b"\x1a\x45\xdf\xa3" + b"\x00" * 32},
        )
        uri = server_mod._path_to_uri(str(tmp_path / "game" / "script.rpy"))

        hover = _do_hover(uri, "    show intro", 9)
        assert hover is not None
        content = hover.contents.value
        assert "**Video**" in content
        assert "intro" in content
        # Command URI for opening in default app.
        assert "command:senpy.openExternal" in content
        assert "Play video" in content
        # Should NOT contain an inline markdown image preview.
        assert "![" not in content

    def test_video_mp4_via_show(self, tmp_path):
        # MP4 in images/ (rare but valid — Ren'Py can use movie displayables).
        _setup_asset_workspace(
            tmp_path,
            images={"images/intro.mp4": b"\x00\x00\x00 ftypisom" + b"\x00" * 32},
        )
        uri = server_mod._path_to_uri(str(tmp_path / "game" / "script.rpy"))

        hover = _do_hover(uri, "    show intro", 9)
        assert hover is not None
        assert "command:senpy.openExternal" in hover.contents.value


# =============================================================================
# Regression: existing hover behavior must still work
# =============================================================================


class TestExistingHoverRegression:
    """changes must not break existing hover paths."""

    def test_variable_hover_still_works(self, tmp_path):
        script_file, _ = setup_test_workspace(tmp_path)
        uri = server_mod._path_to_uri(str(script_file))

        hover = _do_hover(uri, "$ player_gold += 50", 4)
        assert hover is not None
        assert "player_gold" in hover.contents.value
        assert "default player_gold" in hover.contents.value

    def test_label_hover_still_works(self, tmp_path):
        script_file, _ = setup_test_workspace(tmp_path)
        uri = server_mod._path_to_uri(str(script_file))

        hover = _do_hover(uri, "jump forest_scene", 7)
        assert hover is not None
        assert "forest_scene" in hover.contents.value

    def test_renpy_api_hover_still_works(self, tmp_path):
        script_file, _ = setup_test_workspace(tmp_path)
        uri = server_mod._path_to_uri(str(script_file))

        hover = _do_hover(uri, "$ renpy.pause(1.5)", 8)
        assert hover is not None
        # API hover returns docstring content, not "Image"/"Audio" markers.
        assert "renpy.pause" in hover.contents.value


# =============================================================================
# VS Code extension: senpy.openExternal command registered
# =============================================================================


class TestVSCodeOpenExternalCommand:
    """The TypeScript extension must register `senpy.openExternal` so that
    `command:senpy.openExternal?...` markdown links in hover actually
    invoke something. Otherwise VS Code shows "command not found".
    """

    def test_command_registered_in_extension_ts(self):
        ext_ts = EXTENSION_TS
        assert ext_ts.exists()
        content = ext_ts.read_text(encoding="utf-8")
        assert "senpy.openExternal" in content, (
            "extension.ts must register 'senpy.openExternal' command — "
            " video hover emits command:senpy.openExternal?... links."
        )
        assert "vscode.env.openExternal" in content, (
            "extension.ts must call vscode.env.openExternal to actually "
            "open the file in the OS default app."
        )

    def test_command_listed_in_package_json(self):
        pkg = json.loads(
            (VSCODE_PACKAGE_JSON).read_text("utf-8")
        )
        commands = pkg.get("contributes", {}).get("commands", [])
        cmd_ids = {c.get("command") for c in commands}
        assert "senpy.openExternal" in cmd_ids, (
            "package.json contributes.commands must list 'senpy.openExternal' "
            "so VS Code knows the command exists (even if hidden from palette)."
        )


# =============================================================================
# _resolve_relative_to_game — path-traversal protection
# =============================================================================


class TestResolveRelativeToGameSecurity:
    """``_resolve_relative_to_game`` must reject paths that escape the
    project root via ``..`` segments.

    The function resolves a game-relative reference (e.g. the
    ``"file.png"`` in ``image bg = "file.png"``) to an absolute disk path.
    Before the fix, ``os.path.join(project, "game", "images/../../secret")``
    was accepted and ``os.path.exists`` confirmed the file — so hovering
    over a malicious ``image`` declaration disclosed the size and path of
    arbitrary files outside the project (info disclosure).

    Note on the existing ``lstrip("./")``: it accidentally neutralises
    payloads that START with ``.`` or ``/`` (e.g. ``../../etc/passwd`` →
    ``etc/passwd``, ``/etc/passwd`` → ``etc/passwd``). But a payload with
    a non-dot prefix like ``images/../../secret`` slips through — that is
    the real vector this test class covers.
    """

    def test_dotdot_traversal_returns_none(self, tmp_path: Path):
        """``images/../../secret.txt`` must NOT resolve to a file outside game/.

        PoC: a file ``secret.txt`` is created at the project root (outside
        ``game/``). The relative path ``images/../../secret.txt`` from
        ``game/images/`` (which exists) escapes up to the project root and
        resolves to ``secret.txt``. Without the fix, ``os.path.exists``
        confirms the file and the hover discloses its size and path.
        """
        from senpy.lsp.handlers.asset_hover import _resolve_relative_to_game

        game_dir = tmp_path / "game"
        images_dir = game_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        # Place a file OUTSIDE game/ but INSIDE tmp_path — the traversal
        # target. ``os.path.exists`` would return True for it without the fix.
        secret = tmp_path / "secret.txt"
        secret.write_text("outside game/", encoding="utf-8")

        result = _resolve_relative_to_game("images/../../secret.txt", str(tmp_path))
        assert result is None, (
            f"_resolve_relative_to_game resolved a path-traversal payload to "
            f"{result!r} — the hover would disclose the size and path of a "
            "file outside game/ (info disclosure)."
        )

    def test_normal_relative_path_resolves(self, tmp_path: Path):
        """A normal game-relative path (``images/bg.png``) must resolve.

        Regression guard: the traversal fix must NOT break the legitimate
        use case — every normal asset reference must still resolve.
        """
        from senpy.lsp.handlers.asset_hover import _resolve_relative_to_game

        game_dir = tmp_path / "game"
        images_dir = game_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        bg = images_dir / "bg.png"
        bg.write_bytes(b"\x89PNG\r\n\x1a\n")

        result = _resolve_relative_to_game("images/bg.png", str(tmp_path))
        assert result is not None, (
            "Normal game-relative path 'images/bg.png' did not resolve — "
            "the traversal fix broke the legitimate use case."
        )
        assert os.path.realpath(result) == os.path.realpath(str(bg))

    def test_path_in_project_root_resolves(self, tmp_path: Path):
        """A path at the project root (not under game/) must resolve too."""
        from senpy.lsp.handlers.asset_hover import _resolve_relative_to_game

        # The second candidate is os.path.join(project_path, rel).
        marker = tmp_path / "marker.txt"
        marker.write_text("root-level", encoding="utf-8")

        result = _resolve_relative_to_game("marker.txt", str(tmp_path))
        assert result is not None
        assert os.path.realpath(result) == os.path.realpath(str(marker))

    def test_leading_dot_slash_resolves(self, tmp_path: Path):
        """``./images/bg.png`` (with leading ``./``) must still resolve.

        The existing ``lstrip("./")`` behaviour strips the leading ``./``
        before joining — the traversal fix must preserve this.
        """
        from senpy.lsp.handlers.asset_hover import _resolve_relative_to_game

        game_dir = tmp_path / "game"
        images_dir = game_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        bg = images_dir / "bg.png"
        bg.write_bytes(b"\x89PNG\r\n\x1a\n")

        result = _resolve_relative_to_game("./images/bg.png", str(tmp_path))
        assert result is not None, (
            "Leading './images/bg.png' did not resolve — the traversal fix "
            "broke the lstrip('./') handling for normal relative paths."
        )

    def test_backslash_path_resolves(self, tmp_path: Path):
        """Backslash separators (Windows-style) must be normalised and resolve."""
        from senpy.lsp.handlers.asset_hover import _resolve_relative_to_game

        game_dir = tmp_path / "game"
        images_dir = game_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        bg = images_dir / "bg.png"
        bg.write_bytes(b"\x89PNG\r\n\x1a\n")

        # Windows-style separator — the function replaces \ with / before joining.
        result = _resolve_relative_to_game("images\\bg.png", str(tmp_path))
        assert result is not None, (
            "Backslash path 'images\\bg.png' did not resolve — the "
            "traversal fix broke backslash normalisation."
        )

    def test_dotdot_inside_project_does_not_escape(self, tmp_path: Path):
        """``images/../bg.png`` must resolve to ``game/bg.png`` (no escape).

        A ``..`` segment that stays inside the project is fine — the fix
        must only reject paths that escape the project root, not all
        ``..`` segments. The fix uses ``realpath`` which resolves ``..``
        before the containment check, so legitimate ``..`` segments
        that stay inside the project still work.
        """
        from senpy.lsp.handlers.asset_hover import _resolve_relative_to_game

        game_dir = tmp_path / "game"
        images_dir = game_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        bg = game_dir / "bg.png"
        bg.write_bytes(b"\x89PNG\r\n\x1a\n")

        result = _resolve_relative_to_game("images/../bg.png", str(tmp_path))
        assert result is not None, (
            "Path 'images/../bg.png' did not resolve — the fix is too "
            "strict and rejects legitimate ``..`` segments that stay "
            "inside the project root."
        )
        assert os.path.realpath(result) == os.path.realpath(str(bg))

    def test_symlink_escape_returns_none(self, tmp_path: Path):
        """A symlink that points outside the project must NOT resolve.

        Symlinks bypass simple string-based ``..`` checks. The fix uses
        ``os.path.realpath`` (which follows symlinks) before the
        containment check — so a symlink to a file outside the project
        is rejected.
        """
        import sys

        if sys.platform == "win32":
            pytest.skip("Symlink semantics differ on Windows; tested on POSIX.")

        from senpy.lsp.handlers.asset_hover import _resolve_relative_to_game

        # Create a real file OUTSIDE the project that the symlink will target.
        outside = tmp_path.parent / "senpy_outside_target.txt"
        try:
            outside.write_text("outside", encoding="utf-8")
        except OSError:
            pytest.skip("Cannot create file outside tmp_path in this environment.")

        try:
            game_dir = tmp_path / "game"
            game_dir.mkdir(parents=True, exist_ok=True)
            link = game_dir / "escape.png"
            try:
                os.symlink(str(outside), link)
            except OSError:
                pytest.skip("Cannot create symlink in this environment.")

            result = _resolve_relative_to_game("escape.png", str(tmp_path))
            assert result is None, (
                f"_resolve_relative_to_game resolved a symlink that escapes "
                f"the project root to {result!r} — symlinks must be followed "
                "by realpath before the containment check."
            )
        finally:
            try:
                outside.unlink()
            except OSError:
                pass
