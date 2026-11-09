"""Cross-file fixture test for RPY109.

RPY109 catches function calls in ``init python:`` blocks where the
function is defined in a file that Ren'Py loads LATER (alphabetical
order). The rule fires only when the definition is in a DIFFERENT file
(``python_ast.py:739-740: if def_file == file_path: continue``).

The original fixture ``tests/fixtures/rules/RPY109/bad_init_order.rpy``
had both ``init python:`` blocks in a single file — RPY109 correctly
did NOT fire (same-file), but the snapshot was ``[]`` so
``test_rule_fixture`` passed vacuously, masking the fact that no
cross-file fixture existed.

Real cross-file coverage was already provided by
``test_analyzer.py::test_init_dependency_graph_rpy109`` (inline code).
This module adds fixture-based cross-file coverage so the fixture
directory is no longer misleading: the same-file case is now a positive
fixture (``good_init_order_same_file.rpy``), and the cross-file case
is covered here via ``cross_file/a_caller.rpy`` + ``cross_file/z_definer.rpy``.

Why a separate test module (not test_rule_fixture)?
  ``test_rule_fixture`` copies ONE .rpy file into tmp_path/game/ and
  runs the analyzer. RPY109 requires TWO files (caller + definer) —
  the rule's ``def_file == file_path`` check would skip the diagnostic
  if both blocks were in the same file. A separate test module loads
  both fixture files into the same tmp_path and asserts RPY109 fires.
"""

from __future__ import annotations

from pathlib import Path

from senpy.core.analyzer import SenpyAnalyzer

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "rpy109_cross_file"


def test_rpy109_cross_file_fixture_fires(tmp_path: Path):
    """RPY109 must fire when a_caller.rpy references z_definer.rpy's function.

    Loads both fixture files into tmp_path/game/ and asserts RPY109
    fires exactly once, on a_caller.rpy, mentioning setup_gui and
    z_definer.rpy.
    """
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)

    # Copy both fixture files into the isolated project.
    a_caller_src = _FIXTURE_DIR / "a_caller.rpy"
    z_definer_src = _FIXTURE_DIR / "z_definer.rpy"
    assert a_caller_src.exists(), f"Missing fixture: {a_caller_src}"
    assert z_definer_src.exists(), f"Missing fixture: {z_definer_src}"

    (game_dir / "a_caller.rpy").write_text(
        a_caller_src.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (game_dir / "z_definer.rpy").write_text(
        z_definer_src.read_text(encoding="utf-8"), encoding="utf-8"
    )

    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)

    rpy109_diags = [d for d in result.diagnostics if d.code == "RPY109"]
    assert len(rpy109_diags) == 1, (
        f"Expected exactly 1 RPY109 diagnostic from cross-file fixture, "
        f"got {len(rpy109_diags)}: {[d.message for d in rpy109_diags]}"
    )

    diag = rpy109_diags[0]
    # The diagnostic must point at a_caller.rpy (the file that loads first
    # and references a function defined later).
    assert (
        "a_caller.rpy" in diag.file_path
    ), f"RPY109 must fire on a_caller.rpy (the early loader), got: {diag.file_path}"
    # The message must mention the function name and the defining file.
    assert (
        "setup_gui" in diag.message
    ), f"RPY109 message must mention 'setup_gui', got: {diag.message}"
    assert (
        "z_definer.rpy" in diag.message
    ), f"RPY109 message must mention 'z_definer.rpy' (the defining file), got: {diag.message}"
    assert diag.severity == "ERROR"


def test_rpy109_cross_file_fixture_no_fire_when_ordered_correctly(tmp_path: Path):
    """RPY109 must NOT fire when files are renamed to load in correct order.

    Negative case: rename a_caller.rpy → z_caller.rpy and z_definer.rpy →
    m_definer.rpy. Now m_definer.rpy loads first (defines setup_gui),
    z_caller.rpy loads later (calls setup_gui) — correct order, no RPY109.
    """
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)

    a_caller_src = _FIXTURE_DIR / "a_caller.rpy"
    z_definer_src = _FIXTURE_DIR / "z_definer.rpy"

    # Correct order: definer loads first (m_ < z_), caller loads later.
    (game_dir / "m_definer.rpy").write_text(
        z_definer_src.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (game_dir / "z_caller.rpy").write_text(
        a_caller_src.read_text(encoding="utf-8"), encoding="utf-8"
    )

    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)

    rpy109_diags = [d for d in result.diagnostics if d.code == "RPY109"]
    assert rpy109_diags == [], (
        f"RPY109 must NOT fire when files are in correct alphabetical order "
        f"(definer before caller). Got: {[d.message for d in rpy109_diags]}"
    )
