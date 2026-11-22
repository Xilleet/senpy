"""RED→GREEN tests for the augassign FP + LSP fast-path state-leak cluster.

Two roadmap items:

  * the augassign FP fix (python_ast.py:844) — ``_check_augassign_type_conflict`` uses
    ``or expected_t in ("dict", "bool")`` with NO ``and op_t != ...``
    clause. Python's ``and`` binds tighter than ``or``, so the last
    disjunct is unconditional for dict/bool expected types — every
    ``dict += X`` and ``bool += X`` fires RPY108, even when the
    operation is valid (``dict += dict`` is ``dict.update``; ``True + 1``
    is ``2``; ``bool += int`` is a perfectly legal counter pattern).

  * the LSP fast-path state-leak fix (analysis_pipeline.py:702) — ``analyze_file_only`` is the
    LSP fast-path invoked on every ``did_change``. Its docstring
    promises "without state leakage", but the only thing it restores
    is ``a.diagnostics``. The integer counters (``total_lines``,
    ``fixed_count``, ``fixable_count``) and the ``failed_writes`` list
    grow on every call — for a keystroke-driven LSP session, that is
    unbounded accumulation in long-running editor sessions.

    The fix restores ONLY the counters and ``failed_writes``. It does
    NOT restore ``file_scopes``, ``_noqa_maps``, or the symbol table:
    those are mutated in place (``_differential_purge_file`` pops the
    old scope, ``_collect_symbols`` adds the new one — a replace, not
    an accumulation), and the LSP server deliberately reads the
    post-call symbol table through ``_refresh_symbol_snapshot`` for
    autocomplete/rename. Restoring those would break autocomplete.
"""

from __future__ import annotations

from pathlib import Path

from senpy.api import Diagnostic, analyze_code
from senpy.core.analyzer import SenpyAnalyzer


def _codes(result: list[Diagnostic]) -> set[str]:
    return {d.code for d in result}


# ===========================================================================
# the augassign FP fix: dict / bool augmented assignment must not fire RPY108
# ===========================================================================


def test_dict_plus_eq_dict_does_not_fire_rpy108():
    """``dict += dict`` is ``dict.update`` — must NOT fire RPY108.

    RED today: ``or expected_t in ("dict", "bool")`` (python_ast.py:844)
    has no ``and op_t != ...`` clause, so ANY ``dict += X`` is flagged
    regardless of the operand type. The user gets a "will crash with
    TypeError" diagnostic on a valid ``dict.update`` call.
    """
    code = (
        "default d = {}\n"
        "default other = {}\n"
        "label start:\n"
        "    $ d += other\n"
        "    return\n"
    )
    codes = _codes(analyze_code(code))
    assert (
        "RPY108" not in codes
    ), f"dict += dict must not fire RPY108 (it is dict.update); got {codes}"


def test_bool_plus_eq_int_does_not_fire_rpy108():
    """``bool += int`` is a legal counter pattern — must NOT fire RPY108.

    RED today: ``True + 1 == 2`` in Python, and the counter pattern
    ``seen = False; seen += 1`` is idiomatic. The current code flags
    every ``bool += X`` because of the unconditional last disjunct.

    This is the canonical the augassign FP fix example from the roadmap.
    """
    code = "default seen = False\n" "label start:\n" "    $ seen += 1\n" "    return\n"
    codes = _codes(analyze_code(code))
    assert "RPY108" not in codes, f"bool += int must not fire RPY108 (True + 1 == 2); got {codes}"


def test_bool_plus_eq_bool_does_not_fire_rpy108():
    """``bool += bool`` — ``True + True == 2`` — must not fire RPY108."""
    code = "default flag = True\n" "label start:\n" "    $ flag += True\n" "    return\n"
    codes = _codes(analyze_code(code))
    assert "RPY108" not in codes, f"bool += bool must not fire RPY108; got {codes}"


def test_dict_plus_eq_str_still_fires_rpy108():
    """``dict += str`` is genuinely invalid — RPY108 MUST still fire.

    Regression guard for the fix: we only relax dict/bool to accept
    compatible operands; an incompatible operand (str for a dict var)
    must still be flagged.
    """
    code = "default d = {}\n" "label start:\n" '    $ d += "not a dict"\n' "    return\n"
    codes = _codes(analyze_code(code))
    assert "RPY108" in codes, f"dict += str MUST fire RPY108 (genuine TypeError); got {codes}"


def test_bool_plus_eq_str_still_fires_rpy108():
    """``bool += str`` is genuinely invalid — RPY108 MUST still fire."""
    code = "default flag = True\n" "label start:\n" '    $ flag += "oops"\n' "    return\n"
    codes = _codes(analyze_code(code))
    assert "RPY108" in codes, f"bool += str MUST fire RPY108 (genuine TypeError); got {codes}"


def test_str_plus_eq_int_still_fires_rpy108():
    """``str += int`` — the original RPY108 fixture case — must still fire.

    Ensures the the augassign FP fix change does not relax the str/int/float/list
    branches of the incompatibility check, only the dict/bool one.
    """
    code = 'default name = "Eileen"\n' "label start:\n" "    $ name += 1\n" "    return\n"
    codes = _codes(analyze_code(code))
    assert "RPY108" in codes, f"str += int MUST still fire RPY108; got {codes}"


# ===========================================================================
# the LSP fast-path state-leak fix: analyze_file_only must not leak the integer counters / failed_writes
# ===========================================================================


def _make_two_file_project(tmp_path: Path) -> Path:
    game = tmp_path / "game"
    game.mkdir()
    (game / "a.rpy").write_text('label a:\n    "hello"\n    return\n', encoding="utf-8")
    (game / "b.rpy").write_text('label b:\n    "world"\n    return\n', encoding="utf-8")
    return game


def test_analyze_file_only_does_not_leak_total_lines(tmp_path: Path):
    """``total_lines`` must NOT grow across repeated ``analyze_file_only`` calls.

    RED today: each call runs ``_analyze_file`` which does
    ``a.total_lines += len(lines)``. After N keystroke-driven calls,
    ``total_lines`` is inflated by N × file_length — the LSP server
    reports a project line count that has no relationship to reality.
    """
    game = _make_two_file_project(tmp_path)
    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run()
    baseline = analyzer.total_lines
    assert baseline > 0, "sanity: run() counted some lines"

    # Simulate the LSP did_change hot loop: 10 keystroke-driven
    # re-analyses of the same file.
    for _ in range(10):
        analyzer.analyze_file_only(str(game / "a.rpy"))

    assert analyzer.total_lines == baseline, (
        f"total_lines leaked: stable baseline {baseline}, grew to "
        f"{analyzer.total_lines} after 10 calls (each call should restore)"
    )


def test_analyze_file_only_does_not_leak_fixed_count(tmp_path: Path):
    """``fixed_count`` / ``fixable_count`` must NOT leak.

    The LSP fast-path does not run --fix, but the counters are still
    mutated by the per-file analysis pipeline if any fixable diagnostic
    is computed. Restoring them keeps the LSP server's reported counts
    honest.
    """
    game = _make_two_file_project(tmp_path)
    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run()
    baseline_fixed = analyzer.fixed_count
    baseline_fixable = analyzer.fixable_count

    for _ in range(10):
        analyzer.analyze_file_only(str(game / "a.rpy"))

    assert (
        analyzer.fixed_count == baseline_fixed
    ), f"fixed_count leaked: {baseline_fixed} -> {analyzer.fixed_count}"
    assert (
        analyzer.fixable_count == baseline_fixable
    ), f"fixable_count leaked: {baseline_fixable} -> {analyzer.fixable_count}"


def test_analyze_file_only_does_not_leak_failed_writes(tmp_path: Path):
    """``failed_writes`` must NOT accumulate across calls."""
    game = _make_two_file_project(tmp_path)
    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run()
    baseline = list(analyzer.failed_writes)

    for _ in range(10):
        analyzer.analyze_file_only(str(game / "a.rpy"))

    assert (
        analyzer.failed_writes == baseline
    ), f"failed_writes leaked: {baseline} -> {analyzer.failed_writes}"


def test_analyze_file_only_preserves_diagnostics_contract(tmp_path: Path):
    """The returned per-file diagnostics list must still work (no regression).

    the LSP fast-path state-leak fix must not break the primary contract of ``analyze_file_only``:
    it returns the diagnostics for the analyzed file only, not the
    accumulated global diagnostics.
    """
    game = _make_two_file_project(tmp_path)
    # Add a file with a real diagnostic (str += int -> RPY108)
    bad = game / "bad.rpy"
    bad.write_text(
        'default name = "E"\nlabel bad:\n    $ name += 1\n    return\n',
        encoding="utf-8",
    )
    analyzer = SenpyAnalyzer(str(tmp_path))
    analyzer.run()

    diags = analyzer.analyze_file_only(str(bad))
    codes = {d.code for d in diags}
    assert (
        "RPY108" in codes
    ), f"analyze_file_only must still return per-file diagnostics; got {codes}"
