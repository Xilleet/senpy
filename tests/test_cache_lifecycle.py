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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
