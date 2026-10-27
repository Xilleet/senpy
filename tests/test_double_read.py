"""Холодный прогон читает каждый .rpy текстом один раз, не два.

Stage 1 (_collect_symbols) и stage 2 (_analyze_file) работают на одном rpy_files.
До фикса — каждый .rpy декодируется из UTF-8 дважды. После — stage 2 берёт lines
из self._stage1_lines, который populate'ит stage 1.
"""
from pathlib import Path

from senpy.analyzer import SenpyAnalyzer


def test_cold_run_reads_each_rpy_once(tmp_path: Path, monkeypatch):
    game = tmp_path / "game"
    game.mkdir()
    (game / "script.rpy").write_text('label start:\n    "hi"\n', encoding="utf-8")
    (game / "other.rpy").write_text("label other:\n    jump start\n", encoding="utf-8")

    real_open = open
    text_reads: dict[str, int] = {}

    def counting_open(path, mode="r", *args, **kwargs):
        p = str(path)
        if p.endswith(".rpy") and "r" in mode and "b" not in mode:
            text_reads[p] = text_reads.get(p, 0) + 1
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr("senpy.analyzer.open", counting_open, raising=False)

    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run(quiet=True)

    for f in [game / "script.rpy", game / "other.rpy"]:
        n = text_reads.get(str(f), 0)
        assert n == 1, (
            f"{f.name}: {n} текстовых чтений (ожидалось 1 — "
            "stage 2 должен переиспользовать lines из self._stage1_lines)"
        )