"""RED tests for small FIXes noticed during code reconnaissance.

FIX-32 (file_discovery.py): ``sorted(dirs)`` is case-sensitive. On
Windows (case-insensitive FS) ``Assets`` and ``assets`` sort
differently, giving non-deterministic traversal order between
machines. Fix: ``sorted(dirs, key=str.lower)``.

FIX-51 (type_inference.py): ``infer_default_value`` returns ``"[]"``
for ``set`` — silently changes the type to ``list``. After this, ``.add()``
on the variable triggers RPY108 (list has no ``.add()`` method). The
rule chain becomes: RPY106 warns about set → generator suggests ``[]``
→ RPY108 fires on the generated default. Fix: return
``"renpy.revertable_set()"`` — same set semantics (``.add()`` works),
rollback-compatible (RPY106-compliant).

These are isolated one-line fixes touched during reconnaissance of
the larger FIX-57+58 GitLab cluster. Per the project methodology
("если то что заметил - можно починить сразу - чини, это не scope"),
they are fixed in the same patch.
"""

from __future__ import annotations

import ast
from pathlib import Path

from senpy.core.file_discovery import discover_rpy_files
from senpy.core.type_inference import infer_default_value

# =============================================================================
# FIX-32: sorted(dirs) case-sensitive — non-deterministic on Windows
# =============================================================================


class TestSortedDirsCaseInsensitive:
    """``sorted(dirs)`` must be case-insensitive for cross-platform determinism.

    On Linux (case-sensitive FS): ``Assets`` < ``assets`` (uppercase first).
    On Windows/macOS (case-insensitive FS): ``Assets`` == ``assets`` but
    ``os.walk`` may return them in either order. Without ``key=str.lower``,
    ``sorted()`` uses codepoint order → ``Assets`` sorts before ``assets``
    on Linux but the order is filesystem-dependent on Windows.

    The fix (``sorted(dirs, key=str.lower)``) ensures the SAME traversal
    order on every platform, so the analyzer output is reproducible
    across CI runs (Linux CI vs Windows developer machine).
    """

    def test_dirs_traversed_case_insensitively(self, tmp_path: Path):
        """Create ``Banana/`` and ``apple/`` siblings — order must be
        case-insensitive (``apple`` first, not ``Banana`` first).

        With case-sensitive ``sorted()``: ``Banana`` (B=0x42) < ``apple``
        (a=0x61) → ``Banana`` first.
        With case-insensitive ``sorted(..., key=str.lower)``: ``banana``
        > ``apple`` → ``apple`` first.

        The fix is to use ``key=str.lower`` so that on Windows
        (case-insensitive FS) the traversal order matches the order on
        Linux, giving reproducible analyzer output across platforms.
        """
        (tmp_path / "Banana").mkdir()
        (tmp_path / "Banana" / "B_script.rpy").write_text("label b:\n    return\n")
        (tmp_path / "apple").mkdir()
        (tmp_path / "apple" / "a_script.rpy").write_text("label a:\n    return\n")

        main_files, _ = discover_rpy_files(str(tmp_path))
        rel_paths = [Path(f).relative_to(tmp_path).as_posix() for f in main_files]
        # ``apple/a_script.rpy`` MUST come first (case-insensitive order).
        idx_apple = rel_paths.index("apple/a_script.rpy")
        idx_banana = rel_paths.index("Banana/B_script.rpy")
        assert idx_apple < idx_banana, (
            f"case-insensitive sort broken: expected apple/ before Banana/, " f"got: {rel_paths}"
        )

    def test_lowercase_dirs_sorted_alphabetically(self, tmp_path: Path):
        """Within lowercase dirs, alphabetical order is preserved."""
        for name in ["z_dir", "m_dir", "a_dir"]:
            d = tmp_path / name
            d.mkdir()
            (d / f"{name}.rpy").write_text(f"label {name}:\n    return\n")

        main_files, _ = discover_rpy_files(str(tmp_path))
        rel_paths = [Path(f).relative_to(tmp_path).as_posix() for f in main_files]
        # Expected order: a_dir/a_dir.rpy, m_dir/m_dir.rpy, z_dir/z_dir.rpy
        assert rel_paths == [
            "a_dir/a_dir.rpy",
            "m_dir/m_dir.rpy",
            "z_dir/z_dir.rpy",
        ], f"alphabetical order broken: {rel_paths}"


# =============================================================================
# FIX-51: infer_default_value for set returns "[]" (silent type change)
# =============================================================================


class TestInferDefaultValueForSet:
    """``infer_default_value`` for a set-typed expression must return a
    set-compatible default — not ``"[]"`` (which silently changes the type
    to list, after which ``.add()`` calls trip RPY108).

    The proper fix per roadmap is ``"renpy.revertable_set()"`` —
    Ren'Py's rollback-compatible set type (has ``.add()``, ``.discard()``,
    ``.remove()`` like the built-in set, and reverts correctly during
    rollback). This is exactly what RPY106 suggests as the safe alternative.
    """

    def test_set_literal_returns_revertable_set(self):
        """``{1, 2, 3}`` (set literal) → default must be ``renpy.revertable_set()``."""
        node = ast.parse("{1, 2, 3}", mode="eval").body
        result = infer_default_value(node)
        assert result == "renpy.revertable_set()", (
            f"set default should be 'renpy.revertable_set()' (rollback-compatible, "
            f"has .add()/.discard()/.remove() like set, RPY106-compliant), got: {result!r}"
        )

    def test_set_call_returns_revertable_set(self):
        """``set()`` (set constructor) → default must be ``renpy.revertable_set()``."""
        node = ast.parse("set()", mode="eval").body
        result = infer_default_value(node)
        assert (
            result == "renpy.revertable_set()"
        ), f"set() default should be 'renpy.revertable_set()', got: {result!r}"

    def test_set_default_does_not_silently_become_list(self):
        """Regression: ``"[]"`` was the old (buggy) default — silently
        changed the type to list, after which ``.add()`` calls tripped RPY108.
        The chain was: RPY106 warns about set → --defaults generator
        writes ``default x = []`` → user's existing ``$ x.add(...)`` code
        triggers RPY108 (list has no .add()). The fix breaks the chain."""
        node = ast.parse("{1, 2}", mode="eval").body
        result = infer_default_value(node)
        assert result != "[]", (
            "set default must NOT be '[]' — that silently changes the type to "
            "list and trips RPY108 on subsequent .add() calls."
        )
        assert result != "set()", (
            "set default must NOT be plain 'set()' — that's a non-revertable "
            "type and RPY106 would flag it. Use 'renpy.revertable_set()'."
        )
