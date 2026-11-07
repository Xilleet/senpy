"""Regression tests for cache state restoration.

These tests reproduce four cache-incomplete-restore bugs where a cold
run and a warm run produce different analyzer state or different
diagnostic sets:

    * Tier 2 cache hit does not restore ``analyzer._noqa_maps``, so
      cross-file rules (RPY701-707, RPY802) re-emit diagnostics that the
      user suppressed with ``# noqa`` on the cold run.
    * Tier 2 cache hit does not restore ``analyzer.missing_defaults``,
      so ``senpy_defaults.rpy`` autogeneration produces an empty file
      on warm runs.
    * Tier 1 cache hit does not restore ``has_dynamic_jumps``, so
      RPY701-707 flip from suppressed (cold) to active (warm) when
      any .rpy contains ``renpy.jump(...)`` or ``call expression``.
    * The cache environment fingerprint does not include the
      ``enable_plugins`` config flag or the set of registered plugin
      rules, so toggling plugins on/off (or upgrading a plugin) leaves
      the Tier 2 cache serving stale results.

The contract being tested: a cold run and a warm run on the same project
must produce identical diagnostic sets and identical analyzer state
(diagnostics, missing_defaults, has_dynamic_jumps, _noqa_maps).

The RPA-archive TypeError case (malformed .rpa pickle root not caught
by `_read_rpa_index`'s except clause) is a separate concern and is
covered by `tests/test_rpa_malformed_archive.py`.
"""

from __future__ import annotations

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


def _run_cold_then_warm(project_path: Path):
    """Run analyzer twice: cold (no cache) then warm (Tier 1+2 hit).

    Returns (cold_result, warm_result, cold_analyzer, warm_analyzer).
    """
    cache_dir = project_path / ".senpy_cache"
    shutil.rmtree(cache_dir, ignore_errors=True)

    cold_a = SenpyAnalyzer(str(project_path))
    cold_r = cold_a.run(quiet=True)

    # Warm run — same project, cache should be present.
    warm_a = SenpyAnalyzer(str(project_path))
    warm_r = warm_a.run(quiet=True)

    return cold_r, warm_r, cold_a, warm_a


# ---------------------------------------------------------------------------
# Tier 2 cache loses `# noqa` for cross-file rules
# ---------------------------------------------------------------------------


def test_noqa_suppression_survives_warm_run(tmp_path: Path) -> None:
    """Reproducer: ``# noqa: RPY701`` on a `define` line suppresses the
    diagnostic on cold, but Tier 2 cache hit on warm does not restore
    `_noqa_maps[path]`, so RPY701 re-fires.
    """
    rpy = """define unused_constant = 10  # noqa: RPY701

label start:
    return
"""
    project = _setup_project(tmp_path, rpy)
    cold_r, warm_r, _, _ = _run_cold_then_warm(project)

    cold_rpy701 = [d for d in cold_r.diagnostics if d.code == "RPY701"]
    warm_rpy701 = [d for d in warm_r.diagnostics if d.code == "RPY701"]
    assert cold_rpy701 == [], f"Cold run should suppress RPY701 via # noqa, got: {cold_rpy701}"
    assert warm_rpy701 == [], (
        f"Warm run must preserve the # noqa suppression, but RPY701 " f"re-fired: {warm_rpy701}"
    )


# ---------------------------------------------------------------------------
# `missing_defaults` not restored from Tier 2 cache
# ---------------------------------------------------------------------------


def test_missing_defaults_survive_warm_run(tmp_path: Path) -> None:
    """Reproducer: `missing_defaults` is populated during `_visit_assign`
    on cold runs. On Tier 2 cache hit, `_analyze_file` is skipped, so
    `missing_defaults` stays empty.
    """
    rpy = """label start:
    $ score = 0
    $ other_var = ""
    "Score: [score] [other_var]"
    return
"""
    project = _setup_project(tmp_path, rpy)
    cold_r, warm_r, cold_a, warm_a = _run_cold_then_warm(project)

    assert cold_a.missing_defaults, "Cold run should populate missing_defaults (sanity check)"
    assert warm_a.missing_defaults == cold_a.missing_defaults, (
        f"Warm run missing_defaults differs from cold: "
        f"cold={cold_a.missing_defaults}, warm={warm_a.missing_defaults}"
    )


def test_generate_defaults_file_works_on_warm_run(tmp_path: Path) -> None:
    """The user-facing consequence: `generate_defaults_file` returns an
    empty file on warm runs because `missing_defaults` is empty.
    """
    rpy = """label start:
    $ score = 0
    "Score: [score]"
    return
"""
    project = _setup_project(tmp_path, rpy)

    # Cold run — populate cache.
    cold_a = SenpyAnalyzer(str(project))
    cold_a.run(quiet=True)
    cold_content, cold_count = cold_a.generate_defaults_file()

    # Warm run — Tier 2 cache hit.
    warm_a = SenpyAnalyzer(str(project))
    warm_a.run(quiet=True)
    warm_content, warm_count = warm_a.generate_defaults_file()

    assert cold_count > 0, "Cold run should detect missing defaults"
    assert warm_count == cold_count, (
        f"Warm run should detect the same missing defaults as cold, "
        f"but cold_count={cold_count}, warm_count={warm_count}"
    )


# ---------------------------------------------------------------------------
# Tier 1 cache does not restore `has_dynamic_jumps`
# ---------------------------------------------------------------------------


def test_has_dynamic_jumps_survives_warm_run(tmp_path: Path) -> None:
    """Reproducer: `jump expression` sets `has_dynamic_jumps=True` on
    cold run. Warm run restores FileScope but not the flag, so RPY701-707
    flip from suppressed to active.
    """
    rpy = """label start:
    $ target = "ending"
    jump expression target
    return

label ending:
    return
"""
    project = _setup_project(tmp_path, rpy)
    cold_r, warm_r, cold_a, warm_a = _run_cold_then_warm(project)

    assert (
        cold_a.has_dynamic_jumps is True
    ), "Cold run should detect `jump expression` and set has_dynamic_jumps"
    assert warm_a.has_dynamic_jumps is True, (
        "Warm run must preserve has_dynamic_jumps=True (Tier 1 cache hit "
        "should restore the flag from cached FileScope state)."
    )


def test_rpy701_suppression_survives_warm_run_with_dynamic_jumps(
    tmp_path: Path,
) -> None:
    """The user-facing consequence: when `has_dynamic_jumps=True`,
    RPY701-707 are suppressed. If the flag is lost on warm run, RPY701
    re-fires on `define unused_constant = 10`.
    """
    rpy = """define unused_constant = 10

label start:
    $ target = "ending"
    jump expression target
    return

label ending:
    return
"""
    project = _setup_project(tmp_path, rpy)
    cold_r, warm_r, _, _ = _run_cold_then_warm(project)

    cold_rpy701 = [d for d in cold_r.diagnostics if d.code == "RPY701"]
    warm_rpy701 = [d for d in warm_r.diagnostics if d.code == "RPY701"]
    assert cold_rpy701 == [], (
        f"Cold run: has_dynamic_jumps=True should suppress RPY701, " f"got: {cold_rpy701}"
    )
    assert warm_rpy701 == [], (
        f"Warm run: has_dynamic_jumps must be restored from cache to "
        f"suppress RPY701, but it re-fired: {warm_rpy701}"
    )


# ---------------------------------------------------------------------------
# Cache fingerprint does not include plugins
# ---------------------------------------------------------------------------


def test_cache_fingerprint_changes_with_enable_plugins(tmp_path: Path) -> None:
    """Reproducer (logical layer): the environment fingerprint must
    include the `enable_plugins` config flag so that toggling plugins
    on/off invalidates the Tier 2 cache. Without this, a warm run after
    enabling plugins serves stale results from the no-plugins run.

    We test this at the fingerprint level (not the full run level)
    because plugin loading requires entry_points machinery that is
    hard to set up in a unit test. The fingerprint contract is what we
    need to enforce.
    """
    rpy = """label start:
    return
"""
    project = _setup_project(tmp_path, rpy)

    # Read the current config (no senpy.toml on disk → defaults).
    from senpy.core.cache import CacheManager
    from senpy.core.config import load_config

    original_cfg = load_config(str(project))
    original_enable_plugins = original_cfg.get("enable_plugins", False)

    a = SenpyAnalyzer(str(project))
    a.run(quiet=True)
    fp_with_original = CacheManager.compute_environment_fingerprint(a)

    # Monkey-patch load_config to return a config with the toggled flag.
    # We don't write a senpy.toml file (that would couple this test to the
    # config file format); we just simulate what the analyzer would see if
    # the user flipped the flag.
    # NOTE: analyzer.py imports `load_config` via `from senpy.core.config
    # import load_config`, so patching `senpy.core.config.load_config`
    # alone is NOT enough — we must patch the analyzer module's local
    # binding too.
    import senpy.core.analyzer as analyzer_mod
    import senpy.core.config as config_mod

    original_load = config_mod.load_config

    def _patched_load(project_path, *args, **kwargs):
        d = dict(original_load(project_path, *args, **kwargs))
        d["enable_plugins"] = not original_enable_plugins
        return d

    config_mod.load_config = _patched_load
    analyzer_mod.load_config = _patched_load
    try:
        # Re-init analyzer so its config field picks up the patched value.
        a2 = SenpyAnalyzer(str(project))
        a2.run(quiet=True)
        fp_with_toggled = CacheManager.compute_environment_fingerprint(a2)
    finally:
        config_mod.load_config = original_load
        analyzer_mod.load_config = original_load

    assert fp_with_original != fp_with_toggled, (
        "Environment fingerprint must change when `enable_plugins` is "
        "toggled. Without this, a warm run after enabling plugins would "
        "serve stale Tier 2 cache results from the no-plugins run."
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
