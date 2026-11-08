"""Regression tests for RPY502 false positive on GIF/BMP images.

``AssetManager._index_valid_images`` in ``senpy/domain/assets.py`` hardcoded
the image extension tuple as ``(".png", ".webp", ".jpg", ".jpeg")`` — missing
``.gif`` and ``.bmp``. Meanwhile, ``IMAGE_EXTENSIONS`` in
``senpy/core/constants.py`` includes all six: ``{.png, .jpg, .jpeg, .webp,
.gif, .bmp}``.

The split had two consequences:
  - ``image_name_to_path`` (used by LSP hover) was built from
    ``IMAGE_EXTENSIONS`` — so hovering over ``show foo bar`` worked when
    ``images/foo bar.gif`` existed.
  - ``valid_images`` (used by RPY502 to validate ``show`` statements) was
    built from the hardcoded tuple — so ``show foo bar`` triggered RPY502
    "unknown image" even though the image existed and hover worked.

The fix replaces the hardcoded tuple with ``IMAGE_EXTENSIONS`` from
``senpy/core/constants.py``, making ``valid_images`` consistent with
``image_name_to_path`` and the documented image extension set.
"""

from __future__ import annotations

from pathlib import Path

from senpy.core.analyzer import SenpyAnalyzer
from senpy.domain.assets import AssetManager


def _diagnostic_codes(analyzer: SenpyAnalyzer) -> list[tuple[str, int]]:
    """Return (code, line_number) pairs for analyzer.diagnostics."""
    return [(d.code, d.line_number) for d in analyzer.diagnostics]


class TestRPY502GifBmpNotFalsePositive:
    """RPY502 must NOT fire on `show` of a GIF/BMP image in `images/`."""

    def test_gif_in_images_no_rpy502(self, tmp_path: Path):
        """`show foo bar` must NOT fire RPY502 when `images/foo bar.gif` exists.

        Before P1-2 fix: `_index_valid_images` hardcoded
        `(".png", ".webp", ".jpg", ".jpeg")` — GIF was missing. The image
        was registered in `image_name_to_path` (hover worked) but NOT in
        `valid_images`. RPY502 then fired on `show foo bar` because the
        tokenized name was not in `valid_images`.
        """
        game = tmp_path / "game"
        game.mkdir()
        images = game / "images"
        images.mkdir()
        # Create a minimal GIF file (GIF87a header, 1x1 pixel).
        gif_bytes = b"GIF87a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        (images / "foo bar.gif").write_bytes(gif_bytes)
        (game / "script.rpy").write_text(
            "label start:\n" "    show foo bar\n" "    return\n",
            encoding="utf-8",
        )

        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)

        rpy502 = [d for d in _diagnostic_codes(analyzer) if d[0] == "RPY502"]
        assert rpy502 == [], (
            f"RPY502 must NOT fire on `show foo bar` when `images/foo bar.gif` "
            f"exists. The hardcoded tuple in _index_valid_images was missing "
            f".gif. Got: {rpy502}"
        )

    def test_bmp_in_images_no_rpy502(self, tmp_path: Path):
        """`show foo bar` must NOT fire RPY502 when `images/foo bar.bmp` exists.

        Same root cause as GIF: BMP is in IMAGE_EXTENSIONS but was missing
        from the hardcoded tuple.
        """
        game = tmp_path / "game"
        game.mkdir()
        images = game / "images"
        images.mkdir()
        # Minimal BMP header (1x1, 24-bit).
        bmp_bytes = (
            b"BM"
            + b"\x00" * 6
            + b"\x36\x00\x00\x00"
            + b"\x28\x00\x00\x00"
            + b"\x01\x00\x00\x00"
            + b"\x01\x00\x00\x00"
            + b"\x01\x00"
            + b"\x18\x00"
            + b"\x00" * 6
            + b"\x04\x00\x00\x00"
            + b"\x00" * 12
            + b"\x00\x00\x00\x00"
        )
        (images / "foo bar.bmp").write_bytes(bmp_bytes)
        (game / "script.rpy").write_text(
            "label start:\n" "    show foo bar\n" "    return\n",
            encoding="utf-8",
        )

        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)

        rpy502 = [d for d in _diagnostic_codes(analyzer) if d[0] == "RPY502"]
        assert rpy502 == [], (
            f"RPY502 must NOT fire on `show foo bar` when `images/foo bar.bmp` "
            f"exists. The hardcoded tuple in _index_valid_images was missing "
            f".bmp. Got: {rpy502}"
        )


class TestValidImagesConsistentWithImageExtensions:
    """`valid_images` must include all IMAGE_EXTENSIONS, not a hardcoded subset."""

    def test_gif_in_valid_images(self, tmp_path: Path):
        """`AssetManager.valid_images` must contain tokenized name for GIF.

        Direct check on AssetManager (no analyzer run) — proves the
        hardcoded tuple was replaced with IMAGE_EXTENSIONS.
        """
        game = tmp_path / "game"
        game.mkdir()
        images = game / "images"
        images.mkdir()
        gif_bytes = b"GIF87a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        (images / "foo bar.gif").write_bytes(gif_bytes)

        am = AssetManager(str(tmp_path))
        am.index()

        # "foo bar" (tokenized from "foo bar.gif" with _→space, /→space)
        # AND "foo bar" (basename) should both be in valid_images.
        assert "foo bar" in am.valid_images, (
            f"`foo bar` (from images/foo bar.gif) must be in valid_images. "
            f"Got: {sorted(am.valid_images)}"
        )

    def test_bmp_in_valid_images(self, tmp_path: Path):
        """`AssetManager.valid_images` must contain tokenized name for BMP."""
        game = tmp_path / "game"
        game.mkdir()
        images = game / "images"
        images.mkdir()
        bmp_bytes = (
            b"BM"
            + b"\x00" * 6
            + b"\x36\x00\x00\x00"
            + b"\x28\x00\x00\x00"
            + b"\x01\x00\x00\x00"
            + b"\x01\x00\x00\x00"
            + b"\x01\x00"
            + b"\x18\x00"
            + b"\x00" * 6
            + b"\x04\x00\x00\x00"
            + b"\x00" * 12
            + b"\x00\x00\x00\x00"
        )
        (images / "foo bar.bmp").write_bytes(bmp_bytes)

        am = AssetManager(str(tmp_path))
        am.index()

        assert "foo bar" in am.valid_images, (
            f"`foo bar` (from images/foo bar.bmp) must be in valid_images. "
            f"Got: {sorted(am.valid_images)}"
        )


class TestRPY502StillFiresOnMissingImage:
    """Sanity: RPY502 must still fire when the image genuinely does not exist.

    Guards against over-broadening: if IMAGE_EXTENSIONS were accidentally
    made to match every file, RPY502 would stop firing on real missing
    images.
    """

    def test_rpy502_fires_on_truly_missing_image(self, tmp_path: Path):
        """`show nonexistent` must still fire RPY502 when no image exists."""
        game = tmp_path / "game"
        game.mkdir()
        (game / "script.rpy").write_text(
            "label start:\n" "    show nonexistent image\n" "    return\n",
            encoding="utf-8",
        )

        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer.run(quiet=True)

        rpy502 = [d for d in _diagnostic_codes(analyzer) if d[0] == "RPY502"]
        assert rpy502, (
            "RPY502 MUST fire on `show nonexistent image` when no image file "
            "exists. If this fails, IMAGE_EXTENSIONS was over-broadened."
        )
