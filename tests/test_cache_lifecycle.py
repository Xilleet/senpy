"""Infrastructure tests for analyzer state lifecycle and cache backward
compatibility.

These tests enforce contracts that the bug-fix regression tests in
``test_cache_state_restore.py`` and ``test_rpa_malformed_archive.py``
only check incidentally:

    test_run_idempotency — two consecutive ``run()`` calls on the same
        analyzer instance must produce identical state. Catches
        forget-to-reset bugs of the kind where a state field is not
        cleared in `_run_reset` and the second run inherits stale data.

    test_cache_backward_compat — loading a manifest written by an
        older Senpy version (one that lacks the ``fixable_count`` /
        ``fixed_count`` / ``missing_defaults`` fields on
        ``CachedFileEntry``) must not crash. The fallback default of 0
        must apply silently so an upgrade does not wipe the cache.

    test_cold_warm_equivalence — a cold run and a warm run on the same
        project must produce identical diagnostic sets and analyzer
        state. This is the architectural investment against cache
        incomplete restore — catches future forget-to-restore bugs
        automatically.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer


def _setup_project(tmp_path: Path, rpy_content: str) -> Path:
    """Create a minimal Ren'Py project with a single .rpy file."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "scenario.rpy").write_text(rpy_content, encoding="utf-8")
    return tmp_path


# A small but diverse project: dynamic jumps, missing defaults, noqa,
# cross-file rule (RPY701) target. Triggers the state-restoration paths
# exercised by the bug-fix tests.
_SAMPLE_RPY = """define unused_constant = 10  # noqa: RPY701

label start:
    $ score = 0
    $ target = "ending"
    jump expression target
    return

label ending:
    $ other_var = ""
    "Score: [score] [other_var]"
    return
"""


# ---------------------------------------------------------------------------
# run() idempotency
# ---------------------------------------------------------------------------


def test_run_idempotency(tmp_path: Path) -> None:
    """Two consecutive ``run()`` calls on the same analyzer instance must
    produce identical state.

    Catches ``_run_reset`` bugs: when a state field is not reset between
    runs, the second run produces stale or duplicated diagnostics. This
    is the architectural investment against forget-to-reset state bugs
    (state not propagated / state not cleared between runs) —
    catches future variants automatically.
    """
    project = _setup_project(tmp_path, _SAMPLE_RPY)
    shutil.rmtree(project / ".senpy_cache", ignore_errors=True)

    a = SenpyAnalyzer(str(project))
    r1 = a.run(quiet=True)
    snap1 = {
        "diagnostic_codes": sorted({d.code for d in a.diagnostics}),
        "diagnostic_count": len(a.diagnostics),
        "missing_defaults": dict(a.missing_defaults),
        "referenced_labels": sorted(a.referenced_labels),
        "has_dynamic_jumps": a.has_dynamic_jumps,
        "user_symbols": sorted(a.user_symbols),
        "total_lines": a.total_lines,
        "fixable_count": a.fixable_count,
        "fixed_count": a.fixed_count,
    }

    # Second run on the same instance — must produce identical state.
    r2 = a.run(quiet=True)
    snap2 = {
        "diagnostic_codes": sorted({d.code for d in a.diagnostics}),
        "diagnostic_count": len(a.diagnostics),
        "missing_defaults": dict(a.missing_defaults),
        "referenced_labels": sorted(a.referenced_labels),
        "has_dynamic_jumps": a.has_dynamic_jumps,
        "user_symbols": sorted(a.user_symbols),
        "total_lines": a.total_lines,
        "fixable_count": a.fixable_count,
        "fixed_count": a.fixed_count,
    }

    assert snap1 == snap2, (
        "run() idempotency violated — second run produced different "
        "state. Differences:\n"
        + "\n".join(f"  {k}: {snap1[k]!r} → {snap2[k]!r}" for k in snap1 if snap1[k] != snap2[k])
    )
    assert r1.diagnostics == r2.diagnostics or (
        sorted(d.code for d in r1.diagnostics) == sorted(d.code for d in r2.diagnostics)
    ), "Diagnostic sets must be equivalent across runs"


# ---------------------------------------------------------------------------
# cache backward compat
# ---------------------------------------------------------------------------


def test_cache_backward_compat_missing_fixable_count(tmp_path: Path) -> None:
    """A manifest written by an older Senpy version (one that lacks
    ``fixable_count``/``fixed_count``/``missing_defaults`` on
    ``CachedFileEntry``) must load without crashing.

    The fallback default of 0 (via ``getattr(entry, ..., 0)``) must apply
    silently so an upgrade does not wipe the cache. We simulate an old
    manifest by constructing a ``CachedFileEntry``-like object that only
    has the original fields.
    """
    project = _setup_project(tmp_path, _SAMPLE_RPY)

    # Cold run — populates cache with the new field set.
    cold_a = SenpyAnalyzer(str(project))
    cold_a.run(quiet=True)

    # Locate the cache manifest on disk and tamper with it: strip the
    # fields added in 0.8.x to simulate a 0.7.x manifest.
    cache_dir = project / ".senpy_cache"
    manifest_path = cache_dir / "cache.pkl"
    assert manifest_path.exists(), "Cold run should have written a manifest"

    # We construct a synthetic old-style CachedFileEntry by removing the
    # new fields via __dict__ manipulation. Since CachedFileEntry uses
    # slots, we use the load path directly with a stub class.
    import pickle

    from senpy.__version__ import __version__ as SENPY_VERSION
    from senpy.core.cache import CachedFileEntry, CacheManifest, SafeCacheUnpickler

    # Read the existing manifest so we can mutate it.
    with open(manifest_path, "rb") as f:
        manifest = SafeCacheUnpickler(f).load()

    # Build a stub CachedFileEntry-like object that omits the new fields.
    # We can't easily strip slots fields from a slotted dataclass, so we
    # use a different approach: construct a fake entry as a SimpleNamespace
    # with only the original fields, and replace the manifest's entry.
    from types import SimpleNamespace

    old_style_files = {}
    for path, entry in manifest.files.items():
        old_style_files[path] = SimpleNamespace(
            mtime=entry.mtime,
            size=entry.size,
            lines_count=entry.lines_count,
            scope=entry.scope,
            diagnostics=entry.diagnostics,
            used_assets=entry.used_assets,
            content_hash=entry.content_hash,
            collect_diagnostics=entry.collect_diagnostics,
            # NOTE: fixable_count, fixed_count, missing_defaults are
            # ABSENT — simulating a 0.7.x manifest.
        )

    old_manifest = CacheManifest(
        version=SENPY_VERSION,
        global_symbol_hash=manifest.global_symbol_hash,
        files=old_style_files,
    )

    with open(manifest_path, "wb") as f:
        pickle.dump(old_manifest, f)

    # Warm run — must not crash. The missing fields must fall back to 0
    # via getattr(entry, ..., 0).
    warm_a = SenpyAnalyzer(str(project))
    warm_r = warm_a.run(quiet=True)

    # Diagnostics must still be served from the (degraded) cache.
    assert warm_r.diagnostics, (
        "Warm run should serve cached diagnostics even when "
        "fixable_count/fixed_count/missing_defaults are absent."
    )


# ---------------------------------------------------------------------------
# test_cold_warm_equivalence — §11.1 of dev assist
# ---------------------------------------------------------------------------


def test_cold_warm_equivalence(tmp_path: Path) -> None:
    """A cold run and a warm run on the same project must produce
    identical diagnostic sets and analyzer state.

    This is the architectural investment against cache incomplete restore.
    The bug fixes for the cache-restore cluster each close one
    specific instance; this test catches any future
    forget-to-restore automatically.
    """
    project = _setup_project(tmp_path, _SAMPLE_RPY)
    cache_dir = project / ".senpy_cache"
    shutil.rmtree(cache_dir, ignore_errors=True)

    # Cold run.
    cold_a = SenpyAnalyzer(str(project))
    cold_r = cold_a.run(quiet=True)

    # Warm run — Tier 1 + Tier 2 cache hits.
    warm_a = SenpyAnalyzer(str(project))
    warm_r = warm_a.run(quiet=True)

    # Diagnostic sets must be equivalent (codes, lines — messages may
    # differ in formatting but content must match).
    def _diag_signature(d) -> tuple:
        return (d.code, d.line_number, d.message)

    cold_set = sorted(_diag_signature(d) for d in cold_r.diagnostics)
    warm_set = sorted(_diag_signature(d) for d in warm_r.diagnostics)
    assert cold_set == warm_set, (
        f"Cold and warm diagnostic sets differ.\n"
        f"  Cold only: {set(cold_set) - set(warm_set)}\n"
        f"  Warm only: {set(warm_set) - set(cold_set)}"
    )

    # Analyzer state must be identical.
    assert cold_a.missing_defaults == warm_a.missing_defaults, (
        f"missing_defaults differs: cold={cold_a.missing_defaults}, "
        f"warm={warm_a.missing_defaults}"
    )
    assert cold_a.referenced_labels == warm_a.referenced_labels, (
        f"referenced_labels differs: cold={cold_a.referenced_labels}, "
        f"warm={warm_a.referenced_labels}"
    )
    assert cold_a.has_dynamic_jumps == warm_a.has_dynamic_jumps, (
        f"has_dynamic_jumps differs: cold={cold_a.has_dynamic_jumps}, "
        f"warm={warm_a.has_dynamic_jumps}"
    )
    assert cold_a.user_symbols == warm_a.user_symbols, (
        f"user_symbols differs: cold={cold_a.user_symbols}, " f"warm={warm_a.user_symbols}"
    )
    assert cold_a.total_lines == warm_a.total_lines, (
        f"total_lines differs: cold={cold_a.total_lines}, " f"warm={warm_a.total_lines}"
    )
    assert cold_a.fixable_count == warm_a.fixable_count, (
        f"fixable_count differs: cold={cold_a.fixable_count}, " f"warm={warm_a.fixable_count}"
    )
    assert cold_a.fixed_count == warm_a.fixed_count, (
        f"fixed_count differs: cold={cold_a.fixed_count}, " f"warm={warm_a.fixed_count}"
    )


# ---------------------------------------------------------------------------
# test_no_cache_equals_cold_cache — P1-4 architectural invariant
# ---------------------------------------------------------------------------


def _assert_analyzer_state_equal(a1, a2, label1: str, label2: str) -> None:
    """Assert two analyzers have identical diagnostic set + state.

    Shared helper for parity tests. Compares the same fields as
    test_cold_warm_equivalence, plus a few extra that are relevant for
    cache-write parity (labels, variables, screens).
    """

    # Diagnostic sets — same comparison as test_cold_warm_equivalence.
    def _diag_signature(d) -> tuple:
        return (d.code, d.line_number, d.message)

    set1 = sorted(_diag_signature(d) for d in a1.diagnostics)
    set2 = sorted(_diag_signature(d) for d in a2.diagnostics)
    assert set1 == set2, (
        f"{label1} and {label2} diagnostic sets differ.\n"
        f"  {label1} only: {set(set1) - set(set2)}\n"
        f"  {label2} only: {set(set2) - set(set1)}"
    )

    # State fields — same as test_cold_warm_equivalence.
    assert a1.missing_defaults == a2.missing_defaults, (
        f"missing_defaults differs: {label1}={a1.missing_defaults}, "
        f"{label2}={a2.missing_defaults}"
    )
    assert a1.referenced_labels == a2.referenced_labels, (
        f"referenced_labels differs: {label1}={a1.referenced_labels}, "
        f"{label2}={a2.referenced_labels}"
    )
    assert a1.has_dynamic_jumps == a2.has_dynamic_jumps, (
        f"has_dynamic_jumps differs: {label1}={a1.has_dynamic_jumps}, "
        f"{label2}={a2.has_dynamic_jumps}"
    )
    assert a1.user_symbols == a2.user_symbols, (
        f"user_symbols differs: {label1}={a1.user_symbols}, " f"{label2}={a2.user_symbols}"
    )
    assert a1.total_lines == a2.total_lines, (
        f"total_lines differs: {label1}={a1.total_lines}, " f"{label2}={a2.total_lines}"
    )
    assert a1.fixable_count == a2.fixable_count, (
        f"fixable_count differs: {label1}={a1.fixable_count}, " f"{label2}={a2.fixable_count}"
    )
    assert a1.fixed_count == a2.fixed_count, (
        f"fixed_count differs: {label1}={a1.fixed_count}, " f"{label2}={a2.fixed_count}"
    )


def test_no_cache_equals_cold_cache(tmp_path: Path) -> None:
    """A run with ``no_cache=True`` must produce identical diagnostics and
    state to a cold run with ``no_cache=False`` on the same fresh project.

    Architectural invariant (P1-4): the cache must NOT change the
    diagnostic output. If a cache-write path bug (e.g. ``_finalize_results``
    skips ``save_manifest`` in some scenario, or ``CachedFileEntry``
    stores stale diagnostics) caused the cached run to differ from the
    no-cache run, this test would catch it.

    ``test_cold_warm_equivalence`` (above) covers the cold→warm path
    (cache-restore bugs). This test covers the no-cache→cache path
    (cache-write bugs). Together they form a full parity guard.
    """
    project = _setup_project(tmp_path, _SAMPLE_RPY)
    cache_dir = project / ".senpy_cache"
    shutil.rmtree(cache_dir, ignore_errors=True)

    # Fresh project — no cache. Run with no_cache=True (cache disabled,
    # nothing written to disk).
    no_cache_a = SenpyAnalyzer(str(project), no_cache=True)
    no_cache_a.run(quiet=True)

    # Verify the cache directory was NOT created by the no_cache run.
    assert not cache_dir.exists(), (
        "no_cache=True run created .senpy_cache/ — CacheManager should be "
        "disabled and must not write anything to disk."
    )

    # Fresh project again — no cache. Run with no_cache=False (cache
    # enabled, will write to disk after the run).
    shutil.rmtree(cache_dir, ignore_errors=True)
    cold_a = SenpyAnalyzer(str(project), no_cache=False)
    cold_a.run(quiet=True)

    # The cache directory MUST be created by the cold run (sanity check
    # that no_cache=False actually enables the cache).
    assert cache_dir.exists(), (
        "no_cache=False run did NOT create .senpy_cache/ — CacheManager "
        "should be enabled and must write the manifest after analysis."
    )

    # The two runs must produce identical diagnostics and state.
    _assert_analyzer_state_equal(no_cache_a, cold_a, "no_cache=True", "cold_cache")


@pytest.mark.parametrize("no_cache", [True, False])
def test_cache_parity_no_cache_vs_cache(tmp_path: Path, no_cache: bool) -> None:
    """Parametrized parity: each mode must produce the same diagnostic set.

    Companion to test_no_cache_equals_cold_cache — runs each mode in
    isolation (fresh tmp_path per parametrization) and snapshots the
    diagnostic signature. The snapshot is compared manually between the
    two parametrizations via the test_no_cache_equals_cold_cache test
    above; this test guards against either mode producing an empty or
    degenerate diagnostic set (e.g. if a refactor accidentally made
    no_cache=True skip all rules).
    """
    project = _setup_project(tmp_path, _SAMPLE_RPY)
    shutil.rmtree(project / ".senpy_cache", ignore_errors=True)

    analyzer = SenpyAnalyzer(str(project), no_cache=no_cache)
    analyzer.run(quiet=True)

    # _SAMPLE_RPY is designed to trigger several diagnostics — the
    # exact set is not asserted here (that's test_no_cache_equals_cold_cache's
    # job), but we assert the set is non-empty to guard against a refactor
    # that makes one mode silently skip all rules.
    assert analyzer.diagnostics, (
        f"no_cache={no_cache}: expected non-empty diagnostics from _SAMPLE_RPY "
        f"(which has dynamic jumps, missing defaults, noqa). Got empty list — "
        f"a refactor may have silently broken analysis in this mode."
    )
    # Sanity: the sample triggers at least one of the expected rules.
    # RPY302 (dynamic jump target) and RPY104 (missing default) are the
    # two most reliable triggers in _SAMPLE_RPY.
    diag_codes = {d.code for d in analyzer.diagnostics}
    expected_triggers = {"RPY302", "RPY104"}
    assert diag_codes & expected_triggers, (
        f"no_cache={no_cache}: expected at least one of {expected_triggers} "
        f"in diagnostics, got codes: {diag_codes}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
