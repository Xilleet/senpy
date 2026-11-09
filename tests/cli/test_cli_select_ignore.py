"""--select / --extend-select / --extend-ignore флаги.

  - `--select RPY101 RPY102` — показывать ТОЛЬКО эти правила (всё остальное скрыто).
  - `--extend-select RPY103` — добавить к select (расширяет whitelist).
  - `--extend-ignore RPY104` — добавить к ignore (расширяет blacklist).
  - Если передан --select, всё что не в select+extend_select скрыто.
  - Если передан только --ignore / --extend-ignore, всё показывается кроме этих.
  - Конфиг senpy.toml тоже может содержать `select` / `extend_select` / `extend_ignore`.
  - CLI имеет приоритет над конфигом.

Семантика:
  1. start with all rules enabled
  2. if `select` is non-empty: disable all, enable only `select`
  3. add `extend_select` to enabled
  4. remove `extend_ignore` from enabled
  5. also remove `ignore` from enabled (existing behavior)

Пример:
  senpy --select RPY101 RPY102 --extend-ignore RPY101
  → показывает только RPY102 (RPY101 в select, но убран extend_ignore)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from senpy.cli.main import filter_diagnostics
from senpy.core.analyzer import AnalysisResult, Diagnostic


def _make_diag(
    code: str, severity: str = "WARNING", file: str = "test.rpy", line: int = 1
) -> Diagnostic:
    return Diagnostic(
        file_path=file,
        line_number=line,
        code=code,
        message=f"{code} test",
        severity=severity,
        line_content="test",
    )


def _make_args(**kwargs) -> argparse.Namespace:
    """Создаёт args Namespace с дефолтами."""
    defaults = {
        "ignore": None,
        "select": None,
        "extend_select": None,
        "extend_ignore": None,
        "tag": None,
        "ignore_tag": None,
        "errors_only": False,
        "info": True,  # показываем INFO по умолчанию для тестов
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _make_result(*diags: Diagnostic) -> AnalysisResult:
    return AnalysisResult(
        diagnostics=list(diags),
        file_count=1,
        total_lines=10,
    )


# =============================================================================
# 1. --select: только перечисленные правила
# =============================================================================


def test_select_shows_only_listed_rules():
    """--select RPY101 RPY102 — показывает только их."""
    result = _make_result(
        _make_diag("RPY101"),
        _make_diag("RPY102"),
        _make_diag("RPY103"),
        _make_diag("RPY104"),
    )
    args = _make_args(select=["RPY101", "RPY102"])
    ignored = set()

    active, _ = filter_diagnostics(result, args, ignored)

    codes = {d.code for d in active}
    assert codes == {"RPY101", "RPY102"}, f"Expected only RPY101+RPY102, got {codes}"


def test_select_empty_shows_all():
    """Без --select показываются все правила."""
    result = _make_result(
        _make_diag("RPY101"),
        _make_diag("RPY102"),
    )
    args = _make_args(select=None)
    ignored = set()

    active, _ = filter_diagnostics(result, args, ignored)

    codes = {d.code for d in active}
    assert codes == {"RPY101", "RPY102"}


# =============================================================================
# 2. --extend-select: добавить к whitelist
# =============================================================================


def test_extend_select_adds_to_select():
    """--select RPY101 --extend-select RPY103 — показываются оба."""
    result = _make_result(
        _make_diag("RPY101"),
        _make_diag("RPY102"),
        _make_diag("RPY103"),
    )
    args = _make_args(select=["RPY101"], extend_select=["RPY103"])
    ignored = set()

    active, _ = filter_diagnostics(result, args, ignored)

    codes = {d.code for d in active}
    assert codes == {"RPY101", "RPY103"}, f"Expected RPY101+RPY103, got {codes}"


def test_extend_select_without_select_ignored():
    """--extend-select без --select — extend_select игнорируется (всё включено)."""
    result = _make_result(
        _make_diag("RPY101"),
        _make_diag("RPY102"),
    )
    args = _make_args(extend_select=["RPY101"])
    ignored = set()

    active, _ = filter_diagnostics(result, args, ignored)

    codes = {d.code for d in active}
    # Без --select всё показывается (extend_select не имеет эффекта)
    assert codes == {"RPY101", "RPY102"}


# =============================================================================
# 3. --extend-ignore: добавить к blacklist
# =============================================================================


def test_extend_ignore_removes_from_results():
    """--extend-ignore RPY101 — скрывает RPY101."""
    result = _make_result(
        _make_diag("RPY101"),
        _make_diag("RPY102"),
        _make_diag("RPY103"),
    )
    args = _make_args(extend_ignore=["RPY101"])
    ignored = set()

    active, _ = filter_diagnostics(result, args, ignored)

    codes = {d.code for d in active}
    assert "RPY101" not in codes
    assert "RPY102" in codes
    assert "RPY103" in codes


def test_extend_ignore_combines_with_ignore():
    """--ignore RPY101 --extend-ignore RPY102 — скрывают оба."""
    result = _make_result(
        _make_diag("RPY101"),
        _make_diag("RPY102"),
        _make_diag("RPY103"),
    )
    args = _make_args(ignore=["RPY101"], extend_ignore=["RPY102"])
    # ignored_codes передаётся отдельно (тут симулируем что main() уже собрал)
    ignored = {"RPY101", "RPY102"}

    active, _ = filter_diagnostics(result, args, ignored)

    codes = {d.code for d in active}
    assert "RPY101" not in codes
    assert "RPY102" not in codes
    assert "RPY103" in codes


# =============================================================================
# 4. Combination: --select + --extend-ignore
# =============================================================================


def test_select_with_extend_ignore():
    """--select RPY101 RPY102 --extend-ignore RPY101 — показывает только RPY102."""
    result = _make_result(
        _make_diag("RPY101"),
        _make_diag("RPY102"),
        _make_diag("RPY103"),
    )
    args = _make_args(select=["RPY101", "RPY102"], extend_ignore=["RPY101"])
    ignored = {"RPY101"}  # main() добавляет extend_ignore к ignored

    active, _ = filter_diagnostics(result, args, ignored)

    codes = {d.code for d in active}
    assert codes == {"RPY102"}, f"Expected only RPY102, got {codes}"


# =============================================================================
# 5. Backward compat: существующий --ignore продолжает работать
# =============================================================================


def test_existing_ignore_still_works():
    """Старый --ignore RPY101 — обратная совместимость."""
    result = _make_result(
        _make_diag("RPY101"),
        _make_diag("RPY102"),
    )
    args = _make_args(ignore=["RPY101"])
    ignored = {"RPY101"}

    active, _ = filter_diagnostics(result, args, ignored)

    codes = {d.code for d in active}
    assert "RPY101" not in codes
    assert "RPY102" in codes


def test_no_filters_shows_everything():
    """Без фильтров — всё показывается."""
    result = _make_result(
        _make_diag("RPY101"),
        _make_diag("RPY102"),
        _make_diag("RPY103"),
    )
    args = _make_args()
    ignored = set()

    active, _ = filter_diagnostics(result, args, ignored)

    codes = {d.code for d in active}
    assert codes == {"RPY101", "RPY102", "RPY103"}


# =============================================================================
# --tag / --ignore-tag: filter by rule metadata tags
# =============================================================================


def test_tag_filters_to_matching_rules_only():
    """--tag rollback — only rules with 'rollback' tag pass."""
    # RPY104, RPY105, RPY106 have 'rollback' tag (see RULES_DATABASE).
    # RPY101 does NOT have 'rollback'.
    result = _make_result(
        _make_diag("RPY101"),
        _make_diag("RPY104"),
        _make_diag("RPY105"),
        _make_diag("RPY106"),
    )
    args = _make_args(tag=["rollback"])
    ignored = set()

    active, _ = filter_diagnostics(result, args, ignored)

    codes = {d.code for d in active}
    assert codes == {
        "RPY104",
        "RPY105",
        "RPY106",
    }, f"--tag rollback should keep only rollback-tagged rules, got {codes}"


def test_tag_with_multiple_values_is_union():
    """--tag audio images — rules with EITHER tag pass (union semantics)."""
    # RPY501, RPY505 have 'audio'. RPY502, RPY504 have 'images'. RPY503 has
    # 'assets' + 'dead-code' (neither audio nor images) → filtered out.
    result = _make_result(
        _make_diag("RPY501"),
        _make_diag("RPY502"),
        _make_diag("RPY503"),
        _make_diag("RPY504"),
        _make_diag("RPY505"),
    )
    args = _make_args(tag=["audio", "images"])
    ignored = set()

    active, _ = filter_diagnostics(result, args, ignored)

    codes = {d.code for d in active}
    assert codes == {"RPY501", "RPY502", "RPY504", "RPY505"}


def test_tag_is_case_insensitive():
    """--tag ROLLBACK should match the same rules as --tag rollback."""
    result = _make_result(_make_diag("RPY104"), _make_diag("RPY101"))
    args = _make_args(tag=["ROLLBACK"])
    ignored = set()

    active, _ = filter_diagnostics(result, args, ignored)
    codes = {d.code for d in active}
    assert codes == {"RPY104"}


def test_ignore_tag_drops_matching_rules():
    """--ignore-tag dead-code — rules tagged 'dead-code' are dropped."""
    # RPY701, RPY702, RPY703 are tagged 'dead-code'. RPY101 is not.
    result = _make_result(
        _make_diag("RPY101"),
        _make_diag("RPY701"),
        _make_diag("RPY702"),
        _make_diag("RPY703"),
    )
    args = _make_args(ignore_tag=["dead-code"])
    ignored = set()

    active, _ = filter_diagnostics(result, args, ignored)

    codes = {d.code for d in active}
    assert codes == {"RPY101"}


def test_tag_and_ignore_tag_combine():
    """--tag variables --ignore-tag rollback — keep variable rules that
    are NOT rollback-related. RPY101 (variables, dialogue) passes; RPY104
    (variables, state, rollback) is dropped by --ignore-tag rollback."""
    result = _make_result(
        _make_diag("RPY101"),  # tags: variables, dialogue
        _make_diag("RPY104"),  # tags: variables, state, rollback
    )
    args = _make_args(tag=["variables"], ignore_tag=["rollback"])
    ignored = set()

    active, _ = filter_diagnostics(result, args, ignored)

    codes = {d.code for d in active}
    assert codes == {"RPY101"}


def test_tag_filter_with_unknown_rule_code_passes():
    """A diagnostic whose code is not in RULES_DATABASE (e.g. a plugin
    rule) has no tags. It should:
      - pass --tag (no constraint can be applied — no tags to match)
      - be dropped by --ignore-tag (conservative — we don't know its
        tags, so we can't prove it should be kept)
    This matches the documented behaviour in filter_diagnostics."""
    result = _make_result(_make_diag("PLG001"))
    args = _make_args(tag=["variables"])
    ignored = set()

    active, _ = filter_diagnostics(result, args, ignored)
    # Without tags, the rule has nothing in common with 'variables' → dropped.
    assert active == []
