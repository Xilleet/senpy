"""TDD tests for post-0.8 fixes (is_character hash, metaJson escaping, SECURITY.md version).

``is_character`` must be part of the global hash — RPY105 depends
on whether a variable is a Character (changing ``define x = Character(...)``
to ``define x = 5`` changes the diagnostic, but the symbol hash did not
include ``is_character``, so Tier-2 cache served stale diagnostics).

``metaJson`` in the VS Code graph webview must escape ``</script>``
— the JSON is interpolated into a ``<script type="application/json">``
element, and an HTML parser terminates the element on ``</script>``
regardless of the ``type`` attribute. A file path containing
``</script>`` would break out of the script element.

SECURITY.md must declare version 0.8.x as actively supported —
the 0.8.0 release shipped, but the Supported Versions table still said
0.7.x.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.cache import CacheManager
from tests._helpers.paths import (
    EXTENSION_TS,
    SECURITY_MD,
)

# ===========================================================================
# is_character in global hash
# ===========================================================================


class TestIsCharacterInGlobalHash:
    """``VariableSymbol.is_character`` must be part of the global hash.

    RPY105 (constant mutation) checks ``var_sym.is_character`` — if a
    variable changes from ``Character("Eileen")`` to a plain constant,
    the diagnostic changes, but the symbol hash did not include
    ``is_character`` (only ``name``, ``type_name``, ``is_constant``).
    """

    def test_is_character_change_invalidates_hash(self, tmp_path: Path):
        """Changing a variable's ``is_character`` flag must change the
        combined hash.

        RPY105 checks ``var_sym.is_character`` — if a variable changes
        from Character to non-Character (or vice versa), the diagnostic
        changes. The hash must include ``is_character`` so Tier-2 cache
        is invalidated.

        Note: in practice, most non-Character defines also get a
        ``type_name`` (which is already hashed), so the hash changes
        anyway. But ``is_character`` is a separate semantic flag — a
        future variable type could have ``type_name=None`` AND
        ``is_character=False``, which would not invalidate the hash
        without this fix. The docstring also claims ``is_character``
        is hashed, so the code must match the documentation.
        """
        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        (game / "script.rpy").write_text(
            'define eileen = Character("Eileen")\nlabel start:\n    return\n',
            encoding="utf-8",
        )

        analyzer1 = SenpyAnalyzer(str(tmp_path), no_cache=True)
        analyzer1.run(quiet=True)
        hash1 = CacheManager.compute_combined_hash(analyzer1)

        # Manually flip is_character on the variable symbol — simulates
        # a hypothetical define that has type_name=None (like Character)
        # but is_character=False (unlike Character). Without hashing
        # is_character, the hash would not change.
        analyzer1.variables["eileen"].is_character = False
        hash2 = CacheManager.compute_combined_hash(analyzer1)

        assert hash1 != hash2, (
            "Flipping is_character on a variable did not change the combined "
            "hash. is_character must be part of the hash — the docstring "
            "claims it is, and RPY105 depends on it. Even if most real-world "
            "defines also change type_name (which is already hashed), "
            "is_character is a separate semantic flag that must be included."
        )


# ===========================================================================
# metaJson </script> escaping in VS Code webview
# ===========================================================================


class TestMetaJsonEscaping:
    """``metaJson`` in the graph webview must escape ``</script>``.

    The JSON metadata is interpolated into a ``<script type="application/json">``
    element. An HTML parser terminates the element on ``</script>``
    regardless of the ``type`` attribute — so a file path containing
    ``</script>`` would break out of the script element and potentially
    execute injected HTML.
    """

    def test_metajson_is_escaped_in_html(self):
        """The webview HTML must not contain a literal ``</script>`` inside
        the metadata script element.
        """
        import re

        ext_ts = EXTENSION_TS
        if not ext_ts.exists():
            pytest.skip("extension.ts not found — VS Code extension not built.")
        src = ext_ts.read_text(encoding="utf-8")

        # Find the getWebviewContent function.
        m = re.search(r"function\s+getWebviewContent\s*\([^)]*\)\s*(?::\s*\w+\s*)?{", src)
        assert m, "Could not find getWebviewContent function"
        start = m.end()
        rest = src[start:]
        next_fn = re.search(r"\n(function|export\s+function)\s+\w+\s*\(", rest)
        body = rest[: next_fn.start()] if next_fn else rest

        # The metaJson interpolation must be escaped — either via a
        # helper function (like escapeHtml) or via inline replace.
        # Look for the metaJson variable usage.
        assert "metaJson" in body, "metaJson not found in getWebviewContent"

        # Check that metaJson is escaped before interpolation.
        # The escape can be:
        #   - escapeHtml(metaJson)
        #   - metaJson.replace(/</g, '\\u003c')
        #   - or a JSON.stringify with a replacer
        metajson_escaped = (
            "escapeHtml(metaJson)" in body
            or "escapeJson(metaJson)" in body
            or re.search(r"metaJson\.replace\(/</g", body) is not None
            or re.search(r"metaJson.*replace.*<.*\\\\u003c", body) is not None
            or re.search(r"\.replace\(/</g.*\\\\u003c.*\).*metaJson", body) is not None
            or re.search(r"metaJson.*replace.*</", body) is not None
        )
        assert metajson_escaped, (
            'metaJson is interpolated into <script type="application/json"> '
            "without escaping </script>. An HTML parser terminates the script "
            "element on </script> regardless of the type attribute — a file "
            "path containing </script> would break out. Escape < to \\u003c "
            "before interpolation, or wrap in escapeHtml()."
        )


# ===========================================================================
# SECURITY.md version 0.8.x
# ===========================================================================


class TestSecurityMdVersion:
    """SECURITY.md must declare 0.8.x as actively supported."""

    def test_security_md_has_0_8x(self):
        """The Supported Versions table must include 0.8.x with active support."""
        security_md = SECURITY_MD
        if not security_md.exists():
            pytest.skip("SECURITY.md not found.")
        content = security_md.read_text(encoding="utf-8")

        # The table must have a row for 0.8.x.
        assert "0.8" in content, (
            "SECURITY.md does not mention version 0.8.x. After the 0.8.0 "
            "release, the Supported Versions table must include 0.8.x."
        )

        # The "currently 0.7.x" text must be updated to 0.8.x.
        assert "currently 0.7" not in content.lower(), (
            "SECURITY.md still says 'currently 0.7.x'. After the 0.8.0 "
            "release, this must say 'currently 0.8.x'."
        )
