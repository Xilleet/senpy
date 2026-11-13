"""Tests for D.1 — deduplication of RPY103/RPY202 diagnostics on the same
line.

Before D.1, ``_check_undeclared_vars_in_condition`` walked ``ast.walk(cond_tree)``
and emitted one diagnostic for every ``ast.Name`` node in ``Load`` context
that was not in ``declared_symbols`` / ``screen_local_symbols``. When the
same undeclared variable appeared multiple times in the same condition
(e.g. ``if not fn.endswith(".png") and not fn.endswith(".jpg") and not
fn.endswith(".webp")`` references ``fn`` three times), three separate
diagnostics were emitted on the same line — all pointing at the same
first-occurrence column (because ``get_utf16_range`` returns the first
match). Visually this looks like a single stacked squiggly line on the
wrong column, not three underlines.

The fix introduces a ``seen`` set per ``_check_undeclared_vars_in_condition``
call: each (line, var_name) gets at most one diagnostic. Different
undeclared variables on the same line still each get their own diagnostic.
"""

from __future__ import annotations

from pathlib import Path

from senpy.core.analyzer import SenpyAnalyzer


class TestRPY103Deduplication:
    """The same variable referenced multiple times in one if-condition
    produces only ONE RPY103 diagnostic — not N stacked on the same
    column."""

    def test_repeated_var_in_condition_emits_one_rpy103(self, tmp_path: Path) -> None:
        """The exact case from user feedback #5: ``if not fn.lower()...
        and not fn.lower()... and not fn.lower()...:`` — `fn` appears
        three times. Before D.1 this produced three RPY103 diagnostics on
        the same line, all pointing at the first `fn` column. After D.1
        it produces exactly one RPY103."""
        project = tmp_path / "game"
        project.mkdir()
        (project / "script.rpy").write_text(
            "label start:\n"
            "    if not undefined_var and undefined_var and undefined_var:\n"
            "        pass\n",
            encoding="utf-8",
        )
        a = SenpyAnalyzer(str(tmp_path))
        a.run(quiet=True)
        rpy103 = [d for d in a.diagnostics if d.code == "RPY103" and "undefined_var" in d.message]
        assert len(rpy103) == 1, (
            f"Expected exactly 1 RPY103 for `undefined_var` (deduplicated), "
            f"got {len(rpy103)}: {[d.message for d in rpy103]}"
        )

    def test_distinct_undeclared_vars_each_get_their_own_rpy103(self, tmp_path: Path) -> None:
        """Sanity: if there are two DIFFERENT undeclared variables on the
        same line, each gets its own RPY103. The dedup is per-variable,
        not per-line."""
        project = tmp_path / "game"
        project.mkdir()
        (project / "script.rpy").write_text(
            "label start:\n    if undefined_var_a and undefined_var_b:\n        pass\n",
            encoding="utf-8",
        )
        a = SenpyAnalyzer(str(tmp_path))
        a.run(quiet=True)
        rpy103_a = [
            d for d in a.diagnostics if d.code == "RPY103" and "undefined_var_a" in d.message
        ]
        rpy103_b = [
            d for d in a.diagnostics if d.code == "RPY103" and "undefined_var_b" in d.message
        ]
        assert len(rpy103_a) == 1, f"Expected 1 RPY103 for `undefined_var_a`, got {len(rpy103_a)}"
        assert len(rpy103_b) == 1, f"Expected 1 RPY103 for `undefined_var_b`, got {len(rpy103_b)}"

    def test_repeated_var_in_screen_emits_one_rpy202(self, tmp_path: Path) -> None:
        """Same dedup applies to RPY202 (screen-context) — repeated
        variable references in one if-condition emit only one
        diagnostic."""
        project = tmp_path / "game"
        project.mkdir()
        (project / "script.rpy").write_text(
            "screen s():\n"
            "    if undeclared_var and undeclared_var:\n"
            "        pass\n"
            "label start:\n"
            '    "Hi"\n',
            encoding="utf-8",
        )
        a = SenpyAnalyzer(str(tmp_path))
        a.run(quiet=True)
        rpy202 = [d for d in a.diagnostics if d.code == "RPY202" and "undeclared_var" in d.message]
        assert len(rpy202) == 1, (
            f"Expected exactly 1 RPY202 for `undeclared_var` (deduplicated), "
            f"got {len(rpy202)}: {[d.message for d in rpy202]}"
        )

    def test_user_feedback_5_repro_no_duplicate_diagnostics(self, tmp_path: Path) -> None:
        """End-to-end repro from user feedback #5: ``init python hide:``
        with a for-loop and an if-condition that references `fn` three
        times.

        After B.2+D.2 (for-target extraction) + D.1 (dedup), the
        expected behaviour is:
            - ``fn`` is registered as a for-loop target → no RPY103 on it
              (B.2 + D.2 working).
            - The three ``fn.lower()`` references in the if-condition do
              not produce three stacked RPY103 diagnostics.

        We assert that there are ZERO RPY103 diagnostics on `fn` (the
        B.2+D.2 fix), and that there are no stacked duplicates of any
        kind in the diagnostic list."""
        project = tmp_path / "game"
        project.mkdir()
        (project / "script.rpy").write_text(
            "init python hide:\n"
            "    def create_automatic_images():\n"
            "        for fn in renpy.loader.listdirfiles():\n"
            "            if fn.startswith('_'):\n"
            "                continue\n"
            "            shortfn = fn[:-4]\n"
            "            if not fn.lower().endswith('.png') and not fn.lower().endswith('.jpg') and not fn.lower().endswith('.webp'):\n"
            "                continue\n"
            "            print(shortfn)\n"
            "label start:\n"
            '    "Hello"\n',
            encoding="utf-8",
        )
        a = SenpyAnalyzer(str(tmp_path))
        a.run(quiet=True)
        # After B.2+D.2: no RPY103 on `fn` (it's a for-loop target now).
        rpy103_fn = [d for d in a.diagnostics if d.code == "RPY103" and "'fn'" in d.message]
        assert not rpy103_fn, (
            f"RPY103 fired on `fn` (for-loop target) — B.2+D.2 fix should "
            f"silence it. Got: {[d.message for d in rpy103_fn]}"
        )
        # After D.1: no line should have multiple diagnostics with the
        # same code + same message. We don't care about exact dedup of
        # which diagnostic; we just assert no N>1 stack of identical
        # (line, code, message) tuples.
        seen_keys: set[tuple[str, int, str]] = set()
        duplicates = []
        for d in a.diagnostics:
            key = (d.file_path, d.line_number, d.message)
            if key in seen_keys:
                duplicates.append(key)
            seen_keys.add(key)
        assert not duplicates, (
            f"Found {len(duplicates)} duplicate (line, code, message) "
            f"diagnostics — D.1 dedup is broken: {duplicates[:3]}"
        )
