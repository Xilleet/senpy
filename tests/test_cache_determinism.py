from __future__ import annotations

from pathlib import Path

from senpy.analyzer import SenpyAnalyzer


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
