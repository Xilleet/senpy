from __future__ import annotations

import re

from senpy.core.models import Diagnostic
from senpy.domain.text_tags import get_utf16_range
from senpy.text_utils import _strip_comment

# Dictionary of deprecated APIs:
# Function name -> (Advice/explanation, 1-to-1 replacement for autofix or None)
#
# Sources (in priority order):
#   1. Ren'Py "Image Manipulators" docs (https://www.renpy.org/doc/html/im.html) —
#      all ``im.*`` functions explicitly marked as "Deprecated since version 7.4.0"
#      are listed here with their modern Transform-property replacement.
#   2. Ren'Py "Incompatible Changes" page (https://www.renpy.org/doc/html/incompatible.html) —
#      APIs that were removed or superseded in a specific version.
#   3. Historical knowledge from the Senpy codebase (LiveComposite, anim.*, ui.*).
#
# NOTE on RENPY-5 (0.9.2 roadmap): the original plan was to auto-extract
# these from ``renpy_api_generated.json`` by parsing the ``.. deprecated::``
# RST directive in ``scripts/fetch_renpy_docs.py``. Investigation showed
# Ren'Py Sphinx docs do NOT use ``.. deprecated::`` for these APIs — the
# deprecation is mentioned in prose ("Deprecated since version 7.4.0").
# Auto-extraction would require NLP over the prose, which is brittle.
# Manual curation here is the pragmatic compromise; the set should be
# reviewed on each Ren'Py pin bump (see ``docs/renpy_api_diff.md``).
DEPRECATED_APIS: dict[str, tuple[str, str | None]] = {
    # Deprecated Displayables (legacy composite helpers).
    "LiveComposite": (
        "This function is obsolete or outdated. Use 'Composite' instead.",
        "Composite",
    ),
    "LiveCrop": ("This function is obsolete or outdated. Use 'Crop' instead.", "Crop"),
    "LiveTile": ("This function is obsolete or outdated. Use 'Tile' instead.", "Tile"),
    "DynamicCharacter": (
        "Deprecated in modern Ren'Py. Use 'Character' with '[var]' interpolation instead.",
        "Character",
    ),
    # Deprecated animations (replaced by ATL).
    "anim.Filmstrip": (
        "Legacy animation helper. Prefer modern ATL (transform / pause) instead.",
        None,
    ),
    "anim.Blink": ("Legacy animation helper. Prefer modern ATL instead.", None),
    "anim.SMAnimation": ("Legacy animation helper. Prefer modern ATL instead.", None),
    # Deprecated ui.* calls (replaced by Screen Language).
    "ui.text": (
        "Legacy 'ui' screen function is obsolete. Use Screen Language 'text' statement.",
        None,
    ),
    "ui.button": (
        "Legacy 'ui' screen function is obsolete. Use Screen Language 'button' statement.",
        None,
    ),
    "ui.imagebutton": (
        "Legacy 'ui' screen function is obsolete. Use Screen Language 'imagebutton' statement.",
        None,
    ),
    "ui.textbutton": (
        "Legacy 'ui' screen function is obsolete. Use Screen Language 'textbutton' statement.",
        None,
    ),
    "ui.vbox": (
        "Legacy 'ui' screen function is obsolete. Use Screen Language 'vbox' statement.",
        None,
    ),
    "ui.hbox": (
        "Legacy 'ui' screen function is obsolete. Use Screen Language 'hbox' statement.",
        None,
    ),
    "ui.grid": (
        "Legacy 'ui' screen function is obsolete. Use Screen Language 'grid' statement.",
        None,
    ),
    "ui.close": (
        "Legacy 'ui' screen construction is obsolete. Use declarative Screen Language.",
        None,
    ),
    # Deprecated im.* image manipulators (deprecated since Ren'Py 7.4.0).
    # Source: https://www.renpy.org/doc/html/im.html
    # Each has a modern Transform-property replacement.
    "im.Blur": (
        "Deprecated since Ren'Py 7.4.0. Use the 'blur' transform property instead.",
        None,
    ),
    "im.Crop": (
        "Deprecated since Ren'Py 7.4.0. Use the 'crop' transform property instead.",
        None,
    ),
    "im.FactorScale": (
        "Deprecated since Ren'Py 7.4.0. Use 'zoom', 'xzoom', or 'yzoom' transform properties instead.",
        None,
    ),
    "im.Flip": (
        "Deprecated since Ren'Py 7.4.0. Use 'xzoom'/'yzoom' with negative values instead.",
        None,
    ),
    "im.Grayscale": (
        "Deprecated since Ren'Py 7.4.0. Use 'matrixcolor' transform property with SaturationMatrix(0) instead.",
        None,
    ),
    "im.Sepia": (
        "Deprecated since Ren'Py 7.4.0. Use 'matrixcolor' transform property with SepiaMatrix() instead.",
        None,
    ),
    "im.Tile": (
        "Deprecated since Ren'Py 7.4.0. Use 'Tile' with the 'xysize' property instead.",
        None,
    ),
    "im.MatrixColor": (
        "Deprecated since Ren'Py 7.4.0. Use 'Transform' with the 'matrixcolor' property instead.",
        None,
    ),
    # Deprecated im.matrix class methods (deprecated since Ren'Py 7.4.0).
    # Source: https://www.renpy.org/doc/html/im.html
    "im.matrix.brightness": (
        "Deprecated since Ren'Py 7.4.0. Use 'matrixcolor' with BrightnessMatrix() instead.",
        None,
    ),
    "im.matrix.colorize": (
        "Deprecated since Ren'Py 7.4.0. Use 'matrixcolor' with ColorizeMatrix() instead.",
        None,
    ),
    "im.matrix.contrast": (
        "Deprecated since Ren'Py 7.4.0. Use 'matrixcolor' with ContrastMatrix() instead.",
        None,
    ),
    "im.matrix.desaturate": (
        "Deprecated since Ren'Py 7.4.0. Use 'matrixcolor' with SaturationMatrix(0) instead.",
        None,
    ),
    "im.matrix.hue": (
        "Deprecated since Ren'Py 7.4.0. Use 'matrixcolor' with HueMatrix() instead.",
        None,
    ),
    "im.matrix.identity": (
        "Deprecated since Ren'Py 7.4.0. Use 'matrixcolor' with IdentityMatrix() instead.",
        None,
    ),
    "im.matrix.invert": (
        "Deprecated since Ren'Py 7.4.0. Use 'matrixcolor' with InvertMatrix() instead.",
        None,
    ),
    "im.matrix.opacity": (
        "Deprecated since Ren'Py 7.4.0. Use 'matrixcolor' with OpacityMatrix() instead.",
        None,
    ),
    "im.matrix.saturation": (
        "Deprecated since Ren'Py 7.4.0. Use 'matrixcolor' with SaturationMatrix() instead.",
        None,
    ),
    "im.matrix.tint": (
        "Deprecated since Ren'Py 7.4.0. Use 'matrixcolor' with TintMatrix() instead.",
        None,
    ),
    # Superseded config variables (from Ren'Py incompatible changes).
    # These still work, but are documented as superseded — Senpy warns so
    # users migrate proactively before a future removal.
    "config.images_directory": (
        "Superseded in Ren'Py 8.5.0 by 'config.image_directories' (a list). "
        'Migrate to: define config.image_directories = [ "myimages" ]',
        None,
    ),
}

# Pre-compiled regular expression for fast lookup
RE_DEPRECATED = re.compile(r"\b(" + "|".join(re.escape(k) for k in DEPRECATED_APIS) + r")\b")

# Fast substring filter so we don't run the regex on ordinary strings.
# Updated in 0.9.2 (RENPY-5) to include "im." and "config.images_directory"
# so the new im.* and config.images_directory entries trigger the fast path.
FAST_TERMS = (
    "Live",
    "anim.",
    "ui.",
    "im.",
    "DynamicCharacter",
    "config.images_directory",
)


class DeprecationChecker:
    """Checks scenario code lines for usage of deprecated Ren'Py APIs."""

    @staticmethod
    def _is_in_quotes(s: str, pos: int) -> bool:
        """Checks whether position pos is inside a string literal.

        Handles single/double quotes and triple-quoted strings.
        Previously only single-line ``"..."`` and ``'...'`` were checked —
        deprecated API names inside ``\"\"\"docstrings\"\"\"`` or
        ``'''multiline strings'''`` triggered false positives.
        """
        in_quote = None
        i = 0
        while i < pos:
            ch = s[i]
            if ch == "\\":
                i += 2
                continue
            if in_quote:
                if ch == in_quote:
                    in_quote = None
            elif ch in ('"', "'"):
                # Check for triple-quoted string start.
                if s[i : i + 3] == ch * 3:
                    # Triple-quote — skip to the closing triple-quote.
                    end = s.find(ch * 3, i + 3)
                    if end == -1 or end >= pos:
                        # No closing triple-quote before pos, or none at all
                        # — pos is inside the triple-quoted string.
                        return True
                    i = end + 3
                    continue
                in_quote = ch
            i += 1
        return in_quote is not None

    @classmethod
    def check_line(cls, line: str, line_no: int, file_path: str) -> list[Diagnostic]:
        # 1. Fast filter: if no substring matches, exit in 5 nanoseconds
        if not any(term in line for term in FAST_TERMS):
            return []

        # 2. Skip full-line comments
        stripped = line.strip()
        if stripped.startswith("#"):
            return []

        # 3. Determine the inline-comment boundary (if any).
        # ``_strip_comment`` returns the code portion of the line with the
        # comment removed (string-literal-aware: ``#`` inside ``"..."`` is
        # preserved). A deprecated-API match in the comment portion must
        # NOT produce a diagnostic — otherwise a line like
        # ``$ x = LiveComposite()  # uses LiveComposite`` gets TWO RPY107
        # (one for the real call, one for the word "LiveComposite" in the
        # comment). Both match'ed at the same col (the first occurrence)
        # which is even more confusing.
        code_only = _strip_comment(line)
        comment_start = len(code_only)
        # If ``_strip_comment`` did not strip anything, ``code_only`` equals
        # ``line`` (modulo trailing whitespace) and ``comment_start`` is
        # past the end — every match is in code. If it stripped something,
        # ``comment_start`` is the index in ``line`` where the ``#``
        # begins (approximate — ``_strip_comment`` may rstrip whitespace,
        # but the ``#`` is always at or after ``comment_start``).

        diagnostics: list[Diagnostic] = []
        for match in RE_DEPRECATED.finditer(line):
            # If the token is inside dialogue quotes — ignore
            if cls._is_in_quotes(line, match.start()):
                continue

            # If the token is in the inline-comment portion — ignore.
            # ``comment_start`` is the boundary; any match at or after it
            # is in the comment.
            if match.start() >= comment_start:
                continue

            token = match.group(1)
            advice, replacement = DEPRECATED_APIS[token]
            start_c, end_c = get_utf16_range(line, token)

            diagnostics.append(
                Diagnostic(
                    file_path=file_path,
                    line_number=line_no,
                    line_content=line.strip(),
                    code="RPY107",
                    message=f"Deprecated Ren'Py API '{token}'. {advice}",
                    severity="WARNING",
                    col=start_c,
                    end_col=end_c,
                    fix_title=f"Replace '{token}' with '{replacement}'" if replacement else None,
                    fix_replacement=replacement if replacement else None,
                    fix_start_col=start_c if replacement else None,
                    fix_end_col=end_c if replacement else None,
                )
            )
        return diagnostics
