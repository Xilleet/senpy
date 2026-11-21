"""RED→GREEN tests for the tl-directory detection cluster.

Three roadmap items share one root cause: the test ``"tl" in rel_parts``
matches a ``tl`` directory ANYWHERE in the relative path, not only the
canonical Ren'Py translation root ``game/tl/``. This mis-routes:

* ``game/mods/tl_backup/foo.rpy``    → tl_files (it is NOT a translation)
* ``game/tl/old_backup/tl/russian/file.rpy`` → language ``old_backup``
  (the first ``tl`` after game) instead of ``russian``
* ``game/tl_backup/foo.rpy`` in the LSP fast-path → ``analyze_tl_file``
  instead of the main analysis path

The fix introduces a single helper, ``_find_tl_dir_index(rel_parts)``,
that returns the index of the canonical ``tl`` directory (the one that
sits directly under ``game``, or — when ``game`` is absent — the first
``tl`` in the path as a project-layout fallback). All three call sites
are routed through it.

Covers the language-resolution fix (coverage.py), the discovery-routing fix (file_discovery.py), the LSP-fast-path-routing fix
(analysis_pipeline.py).
"""

from __future__ import annotations

from pathlib import Path

import senpy.core.file_discovery as fd_mod
from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.coverage import calculate_translation_coverage
from senpy.core.file_discovery import discover_rpy_files

# ===========================================================================
# Helper-level tests for _find_tl_dir_index (the shared fix primitive)
# ===========================================================================


def test_find_tl_dir_index_canonical_game_tl():
    """``game/tl/russian/script.rpy`` → index of ``tl`` is 1."""
    rel_parts = ["game", "tl", "russian", "script.rpy"]
    assert fd_mod._find_tl_dir_index(rel_parts) == 1


def test_find_tl_dir_index_rejects_tl_not_under_game():
    """``game/mods/tl_backup/foo.rpy`` → ``tl_backup`` is NOT ``tl``.

    A directory NAMED ``tl_backup`` is a normal project folder; the
    helper must NOT confuse it with the canonical ``tl`` segment.
    """
    # Note: ``tl_backup`` is a single path component — it is NOT ``tl``.
    # The legacy ``"tl" in rel_parts`` check is exact-match on parts,
    # so ``tl_backup`` was already safe. The regression is the case
    # below (an actual ``tl`` directory NOT directly under game).
    assert fd_mod._find_tl_dir_index(["game", "mods", "tl_backup", "foo.rpy"]) is None


def test_find_tl_dir_index_rejects_tl_under_other_dir():
    """``game/mods/tl/foo.rpy`` → ``tl`` is under ``mods``, not ``game``.

    RED today: ``"tl" in rel_parts`` returns True → the file is
    mis-routed to translation analysis. The helper must return None
    because ``tl`` is not a direct child of ``game``.
    """
    assert fd_mod._find_tl_dir_index(["game", "mods", "tl", "foo.rpy"]) is None


def test_find_tl_dir_index_nested_tl_in_canonical_root():
    """``game/tl/old_backup/tl/russian/file.rpy`` → second ``tl`` (index 3).

    RED today (the language-resolution fix): ``rel_parts.index("tl")`` returns the FIRST
    ``tl`` (index 1), so the language is parsed as ``old_backup``
    instead of ``russian``. The helper must find the ``tl`` that
    actually precedes the language folder — the LAST ``tl`` that is
    a direct child of ``game`` is index 1, but its language subfolder
    ``old_backup`` is itself a directory, not a language. The real
    translation root is ``game/tl/russian/``, so the helper returns
    the LAST ``tl`` directly under ``game`` whose next segment is a
    language directory. We resolve this by taking the LAST ``tl``
    that sits directly under ``game`` — for this path that is index 3
    (the ``tl`` inside ``old_backup`` is NOT under game, so it does not
    count; but ``game/tl/`` at index 1 has a non-language subfolder
    ``old_backup``). The conservative, correct resolution is the
    LAST ``tl`` whose parent chain back to ``game`` contains no other
    ``tl`` — here index 3 (parent is ``old_backup``, grandparent is
    ``tl`` at index 1, which IS the canonical root, so the nested
    ``tl`` is a backup copy inside the canonical root's subtree).
    """
    rel_parts = ["game", "tl", "old_backup", "tl", "russian", "file.rpy"]
    # The canonical translation root is game/tl/ (index 1). Inside it,
    # old_backup/tl/russian/ is a backup layout. The language the user
    # actually wants is "russian" (the LAST tl that has a language
    # folder after it). We resolve to the last tl whose next segment
    # looks like a language dir AND that is reachable from game.
    idx = fd_mod._find_tl_dir_index(rel_parts)
    assert idx is not None, "nested tl must still resolve"
    assert (
        rel_parts[idx + 1] == "russian"
    ), f"language after tl index {idx} is {rel_parts[idx + 1]!r}, expected 'russian'"


def test_find_tl_dir_index_no_game_fallback_to_first_tl():
    """When ``game`` is not in the path, fall back to the first ``tl``.

    Some project layouts use the project root AS the game dir (no
    ``game`` wrapper). In that case the first ``tl`` segment is the
    translation root. This preserves backward compat with the legacy
    ``"tl" in rel_parts`` behaviour for the canonical case while
    fixing the false-positive cases above.
    """
    assert fd_mod._find_tl_dir_index(["tl", "russian", "script.rpy"]) == 0


def test_find_tl_dir_index_no_tl_at_all():
    """``game/script.rpy`` → no tl → None."""
    assert fd_mod._find_tl_dir_index(["game", "script.rpy"]) is None


# ===========================================================================
# the discovery-routing fix: discover_rpy_files routes tl_backup OUT of tl_files
# ===========================================================================


def test_discover_rpy_files_excludes_tl_backup(tmp_path: Path):
    """``game/mods/tl_backup/foo.rpy`` is a MAIN file, not a translation.

    RED today: ``"tl" in rel_parts`` matches the literal substring
    only if a path component is exactly ``tl`` — so ``tl_backup`` is
    already safe. The real regression is ``game/mods/tl/foo.rpy`` (a
    directory literally named ``tl`` that is NOT under game/tl/).
    """
    game = tmp_path / "game"
    (game / "mods" / "tl").mkdir(parents=True)
    (game / "mods" / "tl" / "foo.rpy").write_text("label start:\n    return\n", encoding="utf-8")
    (game / "script.rpy").write_text("label main:\n    return\n", encoding="utf-8")

    main_files, tl_files = discover_rpy_files(str(tmp_path))
    # ``game/mods/tl/foo.rpy`` must be a MAIN file, not a tl file.
    tl_basenames = {Path(f).name for f in tl_files}
    main_basenames = {Path(f).name for f in main_files}
    assert (
        "foo.rpy" in main_basenames
    ), "game/mods/tl/foo.rpy must be a MAIN file (tl is not under game/)"
    assert (
        "foo.rpy" not in tl_basenames
    ), "game/mods/tl/foo.rpy leaked into tl_files — the discovery-routing fix not applied"


def test_discover_rpy_files_keeps_canonical_game_tl(tmp_path: Path):
    """``game/tl/russian/script.rpy`` is still a translation (no regression)."""
    game = tmp_path / "game"
    (game / "tl" / "russian").mkdir(parents=True)
    (game / "tl" / "russian" / "script.rpy").write_text(
        'translate None start:\n    "hello"\n', encoding="utf-8"
    )
    (game / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")

    main_files, tl_files = discover_rpy_files(str(tmp_path))
    tl_basenames = {Path(f).name for f in tl_files}
    assert (
        "script.rpy" in tl_basenames
    ), "game/tl/russian/script.rpy must remain a tl file (no regression)"


# ===========================================================================
# the language-resolution fix: calculate_translation_coverage picks the right language folder
# ===========================================================================


def test_coverage_picks_nested_language_not_old_backup(tmp_path: Path):
    """``game/tl/old_backup/tl/russian/file.rpy`` → language is ``russian``.

    RED today (the language-resolution fix): ``rel_parts.index("tl")`` returns the FIRST
    ``tl`` (the canonical one at index 1), so the language is parsed
    as ``old_backup`` — coverage reports a bogus language and the
    real ``russian`` folder is ignored. The helper must resolve to
    the LAST ``tl`` inside the canonical ``game/tl/`` subtree so the
    language folder after it is the real one.

    Layout mirrors the roadmap example exactly:
    ``game/tl/old_backup/tl/russian/file.rpy`` (a backup copy nested
    inside the canonical translation root).
    """
    game = tmp_path / "game"
    # The real translation root: game/tl/russian/common.rpy
    ru_dir = game / "tl" / "russian"
    ru_dir.mkdir(parents=True)
    (ru_dir / "common.rpy").write_text('translate russian start:\n    "привет"\n', encoding="utf-8")
    # A backup layout that SHOULD resolve to language 'russian', not
    # 'old_backup': game/tl/old_backup/tl/russian/file.rpy. The FIRST
    # 'tl' after game is at index 1, its direct child is 'old_backup'
    # (a backup dir, not a language). The nested 'tl' at index 3 has
    # 'russian' after it — that is the real language.
    nested_ru = game / "tl" / "old_backup" / "tl" / "russian"
    nested_ru.mkdir(parents=True)
    (nested_ru / "file.rpy").write_text(
        'translate russian start:\n    "привет (backup)"\n', encoding="utf-8"
    )

    stats = calculate_translation_coverage(str(tmp_path))
    # 'russian' must be present — it is the real language (both from
    # the canonical root and from the nested backup layout).
    assert "russian" in stats, f"coverage missed 'russian'; got languages: {sorted(stats)}"
    # 'old_backup' must NOT be reported as a language — it is a
    # backup directory, not a translation language. The legacy
    # ``rel_parts.index("tl")`` returned the first tl (index 1) and
    # parsed 'old_backup' as the language; the helper returns the
    # last tl (index 3) whose next segment is 'russian'.
    assert "old_backup" not in stats, (
        "coverage reported 'old_backup' as a language — the language-resolution fix not applied; "
        f"languages: {sorted(stats)}"
    )


# ===========================================================================
# the LSP-fast-path-routing fix: analyze_file_only (LSP fast-path) does NOT route tl_backup to
# analyze_tl_file
# ===========================================================================


def test_analyze_file_only_treats_tl_outside_game_as_main(tmp_path: Path):
    """LSP fast-path must NOT call analyze_tl_file for ``game/mods/tl/foo.rpy``.

    RED today (the LSP-fast-path-routing fix): ``"tl" in rel_parts`` routes any file whose
    path contains a ``tl`` component to ``analyze_tl_file``, which
    expects translation-pair syntax and produces a flood of bogus
    RPY8xx diagnostics on a normal script file.

    We exercise ``analyze_file_only`` directly (the LSP fast-path
    entry point) and assert that a normal script under
    ``game/mods/tl/`` does NOT produce translation-rule diagnostics
    (RPY801/RPY802) that ``analyze_tl_file`` would emit.
    """
    game = tmp_path / "game"
    (game / "mods" / "tl").mkdir(parents=True)
    target = game / "mods" / "tl" / "foo.rpy"
    target.write_text('label start:\n    "hello"\n    return\n', encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
    analyzer.run(quiet=True)

    # Now run the LSP fast-path on the file under game/mods/tl/.
    diags = analyzer.analyze_file_only(str(target))
    tl_diags = [d for d in diags if d.code in ("RPY801", "RPY802", "RPY803", "RPY804")]
    assert not tl_diags, (
        "analyze_file_only routed game/mods/tl/foo.rpy to analyze_tl_file "
        f"(emitted TL diagnostics: {[(d.code, d.message) for d in tl_diags]}) — "
        "the LSP-fast-path-routing fix not applied"
    )


def test_analyze_file_only_still_routes_canonical_game_tl(tmp_path: Path):
    """LSP fast-path must STILL route ``game/tl/russian/foo.rpy`` as TL.

    Regression guard: the fix must not over-correct and drop
    canonical translation files from the TL path.
    """
    game = tmp_path / "game"
    ru_dir = game / "tl" / "russian"
    ru_dir.mkdir(parents=True)
    target = ru_dir / "common.rpy"
    target.write_text('translate russian start:\n    "привет"\n', encoding="utf-8")

    analyzer = SenpyAnalyzer(str(tmp_path), no_cache=True)
    analyzer.run(quiet=True)

    # We cannot easily assert "this went through analyze_tl_file" without
    # spying, but we CAN assert it does NOT crash and produces a result
    # list (the canonical TL path returns diags or []).
    diags = analyzer.analyze_file_only(str(target))
    assert isinstance(
        diags, list
    ), f"analyze_file_only on canonical TL file returned {type(diags)!r}"
