"""TDD tests for ``compute_global_hash`` symbol fields (hash extension part B.1).

``compute_global_hash`` is used to detect when the global symbol table
changed between runs (so cached diagnostics for file B can be reused
only if the global hash is unchanged). The hash must include every
symbol field that another file's diagnostics can depend on — otherwise
file B gets stale diagnostics from the cache.

This test file covers the symbol-hash extension:
  - label ``has_return`` and ``outgoing_jumps`` (RPY306/309/706
    depend on whether a label returns and where it jumps).
  - transform ``signature`` (RPY706 unused-param depends on the
    declared parameter list).
  - image ``image_path``, ``is_layered``, ``attributes``, ``body``
    (cross-file layeredimage attribute lookups depend on these).

The filesystem-dependent fingerprint is a
separate concern and is NOT tested here. It will be added in a
follow-up task.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.cache import CacheManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(
    tmp_path: Path, script_content: str, extra_files: dict[str, str] | None = None
) -> Path:
    """Build a minimal Ren'Py project with one or more .rpy files."""
    game = tmp_path / "game"
    game.mkdir(parents=True, exist_ok=True)
    (game / "script.rpy").write_text(script_content, encoding="utf-8")
    if extra_files:
        for name, content in extra_files.items():
            (game / name).write_text(content, encoding="utf-8")
    return tmp_path


def _snapshot(result):
    """Sorted (code, line_number, message) tuple of all diagnostics."""
    return sorted((d.code, d.line_number, d.message) for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Label: has_return + outgoing_jumps
# ---------------------------------------------------------------------------


class TestLabelHasReturnInGlobalHash:
    """``label.has_return`` must be part of the global hash.

    RPY306 (call without return) and RPY309 (story islands) depend on
    whether a label returns. If file A's label gains or loses a
    ``return``, file B's diagnostics must invalidate.
    """

    def test_has_return_change_invalidates_cache(self, tmp_path: Path):
        """Edit file A's label to add ``return`` → file B's cached
        diagnostics must NOT be reused (global hash must change).
        """
        # Run 1: label foo has no return.
        project = _make_project(
            tmp_path,
            script_content=("label foo:\n    jump bar\nlabel bar:\n    return\n"),
            extra_files={
                "caller.rpy": ("label start:\n    call foo\n    return\n"),
            },
        )

        analyzer1 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer1.run(quiet=True)
        hash1 = CacheManager.compute_global_hash(analyzer1)

        # Run 2: edit foo to add return (semantic change for callers).
        (project / "game" / "script.rpy").write_text(
            "label foo:\n    jump bar\n    return\nlabel bar:\n    return\n",
            encoding="utf-8",
        )

        analyzer2 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer2.run(quiet=True)
        hash2 = CacheManager.compute_global_hash(analyzer2)

        assert hash1 != hash2, (
            "Adding `return` to a label did not change the global hash. "
            "has_return must be part of the hash — RPY306 (call without "
            "return) and RPY309 (story islands) depend on whether a label "
            "returns. Without this, a warm run would serve stale "
            "diagnostics from the cache."
        )

    def test_outgoing_jumps_change_invalidates_cache(self, tmp_path: Path):
        """Edit file A's label jump target → file B's cached
        diagnostics must NOT be reused (global hash must change).
        """
        project = _make_project(
            tmp_path,
            script_content=("label foo:\n    jump bar\nlabel bar:\n    return\n"),
            extra_files={
                "caller.rpy": ("label start:\n    call foo\n    return\n"),
            },
        )

        analyzer1 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer1.run(quiet=True)
        hash1 = CacheManager.compute_global_hash(analyzer1)

        # Run 2: change the jump target.
        (project / "game" / "script.rpy").write_text(
            "label foo:\n    jump baz\nlabel bar:\n    return\nlabel baz:\n    return\n",
            encoding="utf-8",
        )

        analyzer2 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer2.run(quiet=True)
        hash2 = CacheManager.compute_global_hash(analyzer2)

        assert hash1 != hash2, (
            "Changing a label's outgoing jump target did not change the "
            "global hash. outgoing_jumps must be part of the hash — "
            "RPY302 (broken jump) and RPY309 (story islands) depend on "
            "where a label jumps. Without this, a warm run would serve "
            "stale diagnostics from the cache."
        )


# ---------------------------------------------------------------------------
# Transform: signature
# ---------------------------------------------------------------------------


class TestTransformSignatureInGlobalHash:
    """``transform.signature`` must be part of the global hash.

    RPY706 (unused transform parameter) depends on the declared
    parameter list. If file A's transform gains or loses a parameter,
    file B's diagnostics must invalidate.
    """

    def test_signature_change_invalidates_cache(self, tmp_path: Path):
        """Edit file A's transform signature → global hash must change."""
        project = _make_project(
            tmp_path,
            script_content=("transform slide(a, b):\n    xoffset a\n    yoffset b\n"),
            extra_files={
                "user.rpy": ("label start:\n    show bg at slide(1, 2)\n    return\n"),
            },
        )

        analyzer1 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer1.run(quiet=True)
        hash1 = CacheManager.compute_global_hash(analyzer1)

        # Run 2: change the signature (add a parameter).
        (project / "game" / "script.rpy").write_text(
            "transform slide(a, b, c):\n    xoffset a\n    yoffset b\n    rotate c\n",
            encoding="utf-8",
        )

        analyzer2 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer2.run(quiet=True)
        hash2 = CacheManager.compute_global_hash(analyzer2)

        assert hash1 != hash2, (
            "Changing a transform's signature did not change the global "
            "hash. transform.signature must be part of the hash — RPY706 "
            "(unused transform parameter) depends on the declared "
            "parameter list. Without this, a warm run would serve stale "
            "diagnostics from the cache."
        )


# ---------------------------------------------------------------------------
# Image: image_path, is_layered, attributes, body
# ---------------------------------------------------------------------------


class TestImageFieldsInGlobalHash:
    """Image ``image_path``, ``is_layered``, ``attributes``, ``body`` must
    be part of the global hash.

    Cross-file layeredimage attribute lookups depend on these. If file
    A's layeredimage gains or loses an attribute, file B's diagnostics
    (which check ``images[base_tag].attributes``) must invalidate.
    """

    def test_is_layered_change_invalidates_cache(self, tmp_path: Path):
        """Changing a regular image to a layeredimage → global hash changes."""
        project = _make_project(
            tmp_path,
            script_content=('image bg_town = "images/bg_town.png"\n'),
            extra_files={
                "user.rpy": ("label start:\n    scene bg_town\n    return\n"),
            },
        )

        analyzer1 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer1.run(quiet=True)
        hash1 = CacheManager.compute_global_hash(analyzer1)

        # Run 2: change to a layeredimage (is_layered=True, has attributes).
        (project / "game" / "script.rpy").write_text(
            "layeredimage bg_town:\n"
            '    always "images/bg_town.png"\n'
            '    attribute night "images/bg_town_night.png"\n',
            encoding="utf-8",
        )

        analyzer2 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer2.run(quiet=True)
        hash2 = CacheManager.compute_global_hash(analyzer2)

        assert hash1 != hash2, (
            "Changing a regular image to a layeredimage did not change the "
            "global hash. is_layered must be part of the hash — "
            "AssetChecker uses images[base_tag].attributes for "
            "layeredimage attribute validation. Without this, a warm run "
            "would serve stale diagnostics from the cache."
        )

    def test_attributes_change_invalidates_cache(self, tmp_path: Path):
        """Adding/removing a layeredimage attribute → global hash changes."""
        project = _make_project(
            tmp_path,
            script_content=(
                "layeredimage bg_town:\n"
                '    always "images/bg_town.png"\n'
                '    attribute night "images/bg_town_night.png"\n'
            ),
        )

        analyzer1 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer1.run(quiet=True)
        hash1 = CacheManager.compute_global_hash(analyzer1)

        # Run 2: add another attribute.
        (project / "game" / "script.rpy").write_text(
            "layeredimage bg_town:\n"
            '    always "images/bg_town.png"\n'
            '    attribute night "images/bg_town_night.png"\n'
            '    attribute day "images/bg_town_day.png"\n',
            encoding="utf-8",
        )

        analyzer2 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer2.run(quiet=True)
        hash2 = CacheManager.compute_global_hash(analyzer2)

        assert hash1 != hash2, (
            "Adding a layeredimage attribute did not change the global "
            "hash. attributes must be part of the hash — cross-file "
            "layeredimage attribute lookups depend on them. Without this, "
            "a warm run would serve stale diagnostics from the cache."
        )

    def test_image_path_change_invalidates_cache(self, tmp_path: Path):
        """Changing an image's ``image_path`` → global hash changes."""
        project = _make_project(
            tmp_path,
            script_content=('image bg_town = "images/bg_town.png"\n'),
        )

        analyzer1 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer1.run(quiet=True)
        hash1 = CacheManager.compute_global_hash(analyzer1)

        # Run 2: change the image_path.
        (project / "game" / "script.rpy").write_text(
            'image bg_town = "images/bg_city.png"\n',
            encoding="utf-8",
        )

        analyzer2 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer2.run(quiet=True)
        hash2 = CacheManager.compute_global_hash(analyzer2)

        assert hash1 != hash2, (
            "Changing an image's image_path did not change the global "
            "hash. image_path must be part of the hash — LSP hover uses "
            "it to resolve the on-disk preview. Without this, a warm run "
            "would serve stale hover info from the cache."
        )


# ---------------------------------------------------------------------------
# Characterization: hash determinism (same input → same hash)
# ---------------------------------------------------------------------------


class TestGlobalHashDeterminism:
    """Characterization: the same project state must produce the same hash.

    Regression guard for the hash extension — adding new fields must not
    break determinism. If the project is unchanged, two runs must
    produce byte-identical hashes (otherwise the cache would never hit).
    """

    def test_same_project_produces_same_hash(self, tmp_path: Path):
        """Two runs of the same project → identical global hash."""
        project = _make_project(
            tmp_path,
            script_content=(
                "label start:\n"
                "    call foo\n"
                "    return\n"
                "label foo:\n"
                "    jump bar\n"
                "    return\n"
                "label bar:\n"
                "    return\n"
                "transform slide(a, b):\n"
                "    xoffset a\n"
                'image bg_town = "images/bg_town.png"\n'
                "layeredimage eileen:\n"
                '    always "images/eileen_base.png"\n'
                '    attribute happy "images/eileen_happy.png"\n'
            ),
        )

        analyzer1 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer1.run(quiet=True)
        hash1 = CacheManager.compute_global_hash(analyzer1)

        analyzer2 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer2.run(quiet=True)
        hash2 = CacheManager.compute_global_hash(analyzer2)

        assert hash1 == hash2, (
            "Same project state produced different global hashes. The hash "
            "must be deterministic — otherwise the cache would never hit "
            "and every warm run would be as slow as a cold run."
        )

    def test_unrelated_change_preserves_hash(self, tmp_path: Path):
        """A change to a file that does NOT affect symbols (e.g. a
        comment) must NOT change the global hash.

        This is the inverse of the invalidation tests: the hash must
        only change when the symbol table actually changes, not on
        every file touch. Otherwise the cache is useless.
        """
        project = _make_project(
            tmp_path,
            script_content=("label start:\n    return\n"),
        )

        analyzer1 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer1.run(quiet=True)
        hash1 = CacheManager.compute_global_hash(analyzer1)

        # Add a comment — does not change any symbol.
        (project / "game" / "script.rpy").write_text(
            "# This is a comment.\nlabel start:\n    return\n",
            encoding="utf-8",
        )

        analyzer2 = SenpyAnalyzer(str(project), no_cache=True)
        analyzer2.run(quiet=True)
        hash2 = CacheManager.compute_global_hash(analyzer2)

        assert hash1 == hash2, (
            "Adding a comment changed the global hash. The hash must only "
            "respond to symbol-table changes, not to whitespace/comments. "
            "Otherwise every save in the editor would invalidate the cache."
        )
