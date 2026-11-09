from __future__ import annotations

from pathlib import Path

from senpy.core.analyzer import SenpyAnalyzer


def _snapshot(result):
    return sorted((d.code, d.line_number, d.message) for d in result.diagnostics)


def test_warm_run_repeats_cold_diagnostics(tmp_path: Path):
    """[N2] Тёплый (кэшированный) прогон обязан повторять диагностики холодного.

    Регрессия: RPY307/RPY504/RPY105 (stage-1) исчезали на тёплом прогоне,
    а RPY303 ложно появлялся для меток, на которые ссылаются только jump'ы.
    """
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)

    (game_dir / "script.rpy").write_text(
        """
label start:
    jump epilogue_only_by_jump
    return

label epilogue_only_by_jump:
    return

image bg town = "images/bg_town.png"
""",
        encoding="utf-8",
    )

    (game_dir / "extra.rpy").write_text(
        """
label start:
    return

image bg town = "images/bg_town.png"
""",
        encoding="utf-8",
    )

    cold = SenpyAnalyzer(str(tmp_path)).run(quiet=True)
    warm = SenpyAnalyzer(str(tmp_path)).run(quiet=True)

    cold_snap = _snapshot(cold)
    warm_snap = _snapshot(warm)

    # Sanity: холодный прогон реально находит правила stage-1
    assert any(code == "RPY307" for code, _, _ in cold_snap), f"No RPY307 on cold run: {cold_snap}"
    assert any(code == "RPY504" for code, _, _ in cold_snap), f"No RPY504 on cold run: {cold_snap}"

    assert cold_snap == warm_snap, (
        "Cache non-determinism (N2):\n"
        f"cold-only: {sorted(set(cold_snap) - set(warm_snap))}\n"
        f"warm-only: {sorted(set(warm_snap) - set(cold_snap))}"
    )


def test_warm_run_preserves_fixable_count(tmp_path: Path):
    """Tier 2 cache hit обязан восстанавливать fixable_count и fixed_count.

    Регрессия: при cache hit восстанавливались entry.diagnostics и
    entry.used_assets, но НЕ счётчики fixable_count / fixed_count.
    На warm-прогоне число fixable ошибок обнулялось, и CLI не показывал
    строку "[*] N fixable with the --fix option".

    Воспроизводство: проект с RPY001 (tab в indentation — fixable).
    Cold должен показать fixable_count > 0; warm должен показать то же число.
    """
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)

    # Табы в indentation — это RPY001, fixable правило.
    (game_dir / "script.rpy").write_text(
        'label start:\n\t"Tab-indented dialogue."\n\t$ x = 1\n    return\n',
        encoding="utf-8",
    )

    cold = SenpyAnalyzer(str(tmp_path)).run(quiet=True)
    warm = SenpyAnalyzer(str(tmp_path)).run(quiet=True)

    # Sanity: cold действительно нашёл fixable диагностики
    assert cold.fixable_count > 0, (
        f"Cold run should detect RPY001 (tab indentation) as fixable, "
        f"got fixable_count={cold.fixable_count}. Diagnostics: "
        f"{[(d.code, d.line_number) for d in cold.diagnostics]}"
    )

    # Регрессия: warm должен показывать то же число fixable, что и cold
    assert warm.fixable_count == cold.fixable_count, (
        f"Tier 2 cache hit lost fixable_count: cold={cold.fixable_count}, "
        f"warm={warm.fixable_count}. The cache entry stores diagnostics but "
        f"not the fixable counter."
    )
    assert (
        warm.fixed_count == cold.fixed_count
    ), f"Tier 2 cache hit lost fixed_count: cold={cold.fixed_count}, warm={warm.fixed_count}."

    # Дополнительно: diagnostics тоже должны совпадать (та же регрессия N2,
    # но проверяем здесь тоже, чтобы тест был самодостаточным)
    assert _snapshot(cold) == _snapshot(warm), "Diagnostics diverged between cold and warm"
