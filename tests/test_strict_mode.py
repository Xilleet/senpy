"""Integration tests for ``strict = true`` config mode.

When ``strict = true`` is set in ``senpy.toml``, every diagnostic produced
by Senpy must be promoted to severity ``"ERROR"`` — regardless of the
rule's default severity. This is the documented behaviour of the
``strict`` field on ``SenpyConfig`` (see ``senpy/core/config.py`` and
ARCHITECTURE.md).

Two important invariants covered here:

1. ``strict = true`` promotes WARNING/HINT/INFO to ERROR.
2. Explicit ``[tool.senpy.severity]`` overrides have PRIORITY over
   ``strict`` — otherwise the user could not demote a noisy rule to
   INFO while running in strict mode.

The fixture is a small ``.rpy`` file that triggers:

* RPY104 (default WARNING) — ``$ x = 1`` without a top-level ``default``.
* RPY701 (default HINT)    — a ``define`` constant that is never used.
"""

from __future__ import annotations

from pathlib import Path

from senpy.core.analyzer import SenpyAnalyzer


def _make_project(
    tmp_path: Path,
    *,
    strict: bool,
    severity_overrides: dict[str, str] | None = None,
) -> Path:
    """Create a tmp project with a script.rpy that triggers RPY104 and RPY701.

    RPY104 (WARNING by default): ``$ x = 1`` without a top-level ``default x``.
    RPY701 (HINT by default):    a ``define`` constant that is never referenced.
    """
    project = tmp_path / "proj"
    project.mkdir()
    game = project / "game"
    game.mkdir()

    (game / "script.rpy").write_text(
        "define unused_const = 100   # RPY701 (default HINT)\n"
        "label start:\n"
        "    $ undeclared_var = 1   # RPY104 (default WARNING)\n"
        "    return\n",
        encoding="utf-8",
    )

    # Build senpy.toml. load_config accepts the [senpy] section name
    # (see test_config_logging.py for the same convention).
    toml_lines: list[str] = ["[senpy]", f"strict = {str(strict).lower()}"]
    if severity_overrides:
        toml_lines.append("[senpy.severity]")
        for code, sev in severity_overrides.items():
            toml_lines.append(f'{code} = "{sev}"')
    (project / "senpy.toml").write_text("\n".join(toml_lines) + "\n", encoding="utf-8")
    return project


def _severities_by_code(result) -> dict[str, set[str]]:
    """Group diagnostics by code → set of severities seen for that code."""
    out: dict[str, set[str]] = {}
    for d in result.diagnostics:
        out.setdefault(d.code, set()).add(d.severity)
    return out


def test_strict_true_promotes_warning_and_hint_to_error(tmp_path: Path, monkeypatch):
    """With strict=true, RPY104 (WARNING) and RPY701 (HINT) both become ERROR."""
    # chdir isolation keeps load_config deterministic regardless of the
    # real cwd's own senpy.toml.
    monkeypatch.chdir(tmp_path)
    project = _make_project(tmp_path, strict=True)

    analyzer = SenpyAnalyzer(str(project), no_cache=True)
    result = analyzer.run()

    by_code = _severities_by_code(result)
    assert "RPY104" in by_code, "fixture should have triggered RPY104"
    assert "RPY701" in by_code, "fixture should have triggered RPY701"
    assert by_code["RPY104"] == {
        "ERROR"
    }, f"strict=true must promote RPY104 to ERROR, got {by_code['RPY104']!r}"
    assert by_code["RPY701"] == {
        "ERROR"
    }, f"strict=true must promote RPY701 to ERROR, got {by_code['RPY701']!r}"


def test_strict_false_preserves_default_severities(tmp_path: Path, monkeypatch):
    """With strict=false (the default), RPY104 stays WARNING and RPY701 stays HINT."""
    monkeypatch.chdir(tmp_path)
    project = _make_project(tmp_path, strict=False)

    analyzer = SenpyAnalyzer(str(project), no_cache=True)
    result = analyzer.run()

    by_code = _severities_by_code(result)
    assert "RPY104" in by_code
    assert "RPY701" in by_code
    assert by_code["RPY104"] == {
        "WARNING"
    }, f"strict=false must keep RPY104 as WARNING, got {by_code['RPY104']!r}"
    assert by_code["RPY701"] == {
        "HINT"
    }, f"strict=false must keep RPY701 as HINT, got {by_code['RPY701']!r}"


def test_strict_true_does_not_override_explicit_severity(tmp_path: Path, monkeypatch):
    """``[tool.senpy.severity]`` overrides have priority over strict=true.

    Rationale: if the user explicitly demotes a rule to INFO, strict
    mode must not silently re-promote it — otherwise strict mode would
    be unusable for projects with one or two noisy rules.
    """
    monkeypatch.chdir(tmp_path)
    project = _make_project(
        tmp_path,
        strict=True,
        severity_overrides={"RPY104": "INFO"},
    )

    analyzer = SenpyAnalyzer(str(project), no_cache=True)
    result = analyzer.run()

    by_code = _severities_by_code(result)
    assert by_code.get("RPY104") == {"INFO"}, (
        "explicit severity override (RPY104=INFO) must win over strict=true; "
        f"got {by_code.get('RPY104')!r}"
    )
    # RPY701 has no override → strict promotes it to ERROR.
    assert by_code.get("RPY701") == {"ERROR"}


def test_strict_default_is_false_when_field_absent(tmp_path: Path, monkeypatch):
    """If ``strict`` is not mentioned in senpy.toml, behaviour matches strict=false."""
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    (project / "game").mkdir()
    (project / "game" / "script.rpy").write_text(
        "label start:\n" "    $ x = 1   # RPY104 (default WARNING)\n" "    return\n",
        encoding="utf-8",
    )
    # No senpy.toml at all — load_config returns {} and strict defaults to False.

    analyzer = SenpyAnalyzer(str(project), no_cache=True)
    result = analyzer.run()

    by_code = _severities_by_code(result)
    assert by_code.get("RPY104") == {"WARNING"}, (
        "without strict=true, RPY104 must stay WARNING; " f"got {by_code.get('RPY104')!r}"
    )
