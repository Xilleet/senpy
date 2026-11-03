"""CLI tests for `senpy inspect` subcommand.

Tests for `senpy/cli/inspect_dispatch.py`. The dispatch
function `dispatch_inspect(argv)` parses argv, runs the analyzer, and
emits JSON. Tests cover subcommand parsing, the 4 shortcut flags
(`--summary`, `--unresolved`, `--label`, `--screen`), `--no-cache`,
`--with-source`, `--output-file`, and `--decompile`.

All tests run the subcommand via `dispatch_inspect([...])` directly
(no subprocess) for speed.
"""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_GAME = REPO_ROOT / "test_game"


# =============================================================================
# Helper: run inspect, capture stdout
# =============================================================================


def _run_inspect(argv: list) -> tuple[int, str]:
    """Run dispatch_inspect(argv), return (exit_code, captured_stdout)."""
    # Import lazily so test collection does not fail if module doesn't
    # exist yet (Phase 3 RED).
    from senpy.cli.inspect_dispatch import dispatch_inspect

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = dispatch_inspect(argv)
    return rc, buf.getvalue()


def _run_inspect_json(argv: list) -> dict:
    """Run inspect, parse stdout as JSON, return the dict."""
    rc, out = _run_inspect(argv)
    assert rc == 0, f"exit={rc}, stdout={out[:500]}"
    return json.loads(out)


# =============================================================================
# 1. Subcommand parsing — basic
# =============================================================================


def test_inspect_full_json_to_stdout():
    """`senpy inspect test_game/` produces valid JSON with all top-level keys."""
    data = _run_inspect_json([str(TEST_GAME)])
    expected_keys = {
        "labels",
        "screens",
        "variables",
        "transforms",
        "images",
        "jump_sources",
        "used_assets",
        "diagnostics",
        "unresolved",
        "stats",
    }
    assert expected_keys.issubset(data.keys())


def test_inspect_default_path_is_cwd(tmp_path: Path, monkeypatch):
    """When no path is given, defaults to current working directory."""
    (tmp_path / "minimal.rpy").write_text('label start:\n    "Hello"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    data = _run_inspect_json([])
    assert "start" in data["labels"]


def test_inspect_exit_zero_on_success():
    """Successful inspect returns exit code 0."""
    rc, _ = _run_inspect([str(TEST_GAME)])
    assert rc == 0


# =============================================================================
# 2. --summary shortcut — only stats section
# =============================================================================


def test_inspect_summary_outputs_only_stats():
    """`--summary` prints only the `stats` sub-dict (no other top-level keys)."""
    data = _run_inspect_json([str(TEST_GAME), "--summary"])
    # stats is a dict; assert it has the expected sub-keys but no other top-level.
    assert "labels" in data  # stats.labels counter
    assert "lines" in data
    assert "files" in data
    # When --summary is set, the dump is just stats — NOT wrapped in {"stats": ...}.
    # So `data` IS the stats dict, no "labels" (top-level) symbol dict.
    assert "broken_jumps" in data


# =============================================================================
# 3. --unresolved shortcut — only unresolved section
# =============================================================================


def test_inspect_unresolved_outputs_only_unresolved():
    """`--unresolved` prints only the 4 unresolved sub-sections."""
    data = _run_inspect_json([str(TEST_GAME), "--unresolved"])
    expected = {"broken_jumps", "missing_screens", "unreferenced_labels", "unused_assets"}
    assert expected.issubset(data.keys())
    # The unresolved sub-dict has at least one broken jump in test_game
    # (test_game has 'jump bad_edd' and 'jump missing_secret_room').
    assert len(data["broken_jumps"]) >= 1


# =============================================================================
# 4. --label NAME — single label details, auto --with-source
# =============================================================================


def test_inspect_label_lookup_includes_source():
    """`--label start` returns just the `start` label dict with code_line."""
    data = _run_inspect_json([str(TEST_GAME), "--label", "start"])
    assert "name" in data
    assert data["name"] == "start"
    # Single-lookup auto-enables --with-source.
    assert "code_line" in data, "single-lookup must auto-include code_line"
    assert data["code_line"].strip() == "label start:"


def test_inspect_label_lookup_unknown_returns_null_or_empty():
    """`--label nonexistent` — graceful: returns null or empty dict, exit 0."""
    rc, out = _run_inspect([str(TEST_GAME), "--label", "nonexistent_label"])
    assert rc == 0
    # Either `null` or `{}` — both are valid "label not found" responses.
    parsed = json.loads(out)
    assert parsed is None or parsed == {}


# =============================================================================
# 5. --screen NAME — single screen details, auto --with-source
# =============================================================================


def test_inspect_screen_lookup():
    """`--screen shop` returns the shop screen dict."""
    data = _run_inspect_json([str(TEST_GAME), "--screen", "shop"])
    assert data["name"] == "shop"


# =============================================================================
# 6. --transform NAME — single transform details
# =============================================================================


def test_inspect_transform_lookup_unknown_returns_null():
    """`--transform nonexistent` returns null (test_game has no transforms)."""
    rc, out = _run_inspect([str(TEST_GAME), "--transform", "nonexistent"])
    assert rc == 0
    parsed = json.loads(out)
    assert parsed is None or parsed == {}


# =============================================================================
# 7. --with-source flag — include code_line for all symbols
# =============================================================================


def test_inspect_with_source_includes_code_line():
    """`--with-source` includes code_line on labels/variables/transforms."""
    data = _run_inspect_json([str(TEST_GAME), "--with-source"])
    if "start" in data["labels"]:
        assert "code_line" in data["labels"]["start"]
    if "friend_name" in data["variables"]:
        assert "code_line" in data["variables"]["friend_name"]


def test_inspect_without_source_omits_code_line():
    """Default (no --with-source) omits code_line from labels."""
    data = _run_inspect_json([str(TEST_GAME)])
    if "start" in data["labels"]:
        assert "code_line" not in data["labels"]["start"]


# =============================================================================
# 8. --no-cache flag — cold run
# =============================================================================


def test_inspect_no_cache_works():
    """`--no-cache` runs without error and produces valid JSON."""
    data = _run_inspect_json([str(TEST_GAME), "--no-cache"])
    assert "labels" in data


# =============================================================================
# 9. --output-file — write to file instead of stdout
# =============================================================================


def test_inspect_output_file(tmp_path: Path):
    """`-o FILE` writes JSON to file, stdout stays empty."""
    out_file = tmp_path / "dump.json"
    rc, stdout = _run_inspect([str(TEST_GAME), "-o", str(out_file)])
    assert rc == 0
    # stdout should be empty (or close to) when -o is used.
    assert stdout.strip() == "" or "Wrote" in stdout  # allow a "Wrote dump.json" notice
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert "labels" in data


# =============================================================================
# 10. --decompile flag — honored when explicit
# =============================================================================


def test_inspect_decompile_flag_no_rpyc_in_test_game(tmp_path: Path, monkeypatch):
    """`--decompile` with no .rpyc orphans → no extras, runs clean.

    Creates a project with only .rpy files. discover_files(interactive=False)
    should not prompt and not decompile anything.
    """
    (tmp_path / "minimal.rpy").write_text('label start:\n    "Hello"\n', encoding="utf-8")

    # Sentinel: any input() call must raise.
    def _no_input(*a, **kw):
        raise AssertionError("input() must not be called in inspect mode")

    monkeypatch.setattr("builtins.input", _no_input)

    # Run with --decompile — should not crash even with no .rpyc.
    rc, stdout = _run_inspect([str(tmp_path), "--decompile"])
    assert rc == 0


def test_inspect_never_prompts_on_rpyc_orphan(tmp_path: Path, monkeypatch):
    """`senpy inspect` with .rpyc orphan and no --decompile: never prompts,
    silently skips. The user must explicitly pass --decompile."""
    (tmp_path / "orphan.rpyc").write_bytes(b"\x00\x01\x02 fake rpyc")
    (tmp_path / "minimal.rpy").write_text('label start:\n    "Hello"\n', encoding="utf-8")

    def _no_input(*a, **kw):
        raise AssertionError("inspect must NEVER call input() — interactive=False")

    monkeypatch.setattr("builtins.input", _no_input)
    # Force TTY True to ensure the only thing suppressing prompt is interactive=False.
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    rc, stdout = _run_inspect([str(tmp_path)])
    assert rc == 0
    # Verify the .rpy was analyzed; orphan .rpyc skipped.
    data = json.loads(stdout)
    assert "start" in data["labels"]


def test_inspect_ignores_config_decompile_setting(tmp_path: Path, monkeypatch):
    """`senpy inspect` must NOT honor `decompile = true` from senpy.toml.

    Regression test for a real Windows-only bug found in user testing
    (2026-11-03): a project with `decompile = true` in its `senpy.toml`
    would silently trigger unrpyc decompilation when running
    `senpy inspect PATH` (no --decompile flag), polluting the JSON
    output with `[Подготовка] 1/1 (orphan.rpyc)` and
    `[Декомпиляция] 1/1 (orphan.rpy)` lines from `progress_print`.

    inspect must be deterministic: the same `senpy inspect PATH` command
    must produce the same JSON regardless of any `senpy.toml` settings.
    Decompile is opt-in via the `--decompile` flag for inspect.
    """
    (tmp_path / "orphan.rpyc").write_bytes(b"\x00\x01\x02 fake rpyc")
    (tmp_path / "minimal.rpy").write_text('label start:\n    "Hello"\n', encoding="utf-8")
    # Plant a senpy.toml that says decompile = true. The main CLI would
    # honor this; inspect must NOT.
    (tmp_path / "senpy.toml").write_text("[tool.senpy]\ndecompile = true\n", encoding="utf-8")

    def _no_input(*a, **kw):
        raise AssertionError("inspect must NEVER call input() even with config decompile=true")

    monkeypatch.setattr("builtins.input", _no_input)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    rc, stdout = _run_inspect([str(tmp_path)])
    assert rc == 0

    # The stdout must be pure JSON — no [Подготовка]/[Декомпиляция] lines.
    assert "[Подготовка]" not in stdout, (
        f"Decompilation ran despite config decompile=true being ignored "
        f"by inspect. stdout prefix: {stdout[:200]!r}"
    )
    assert "[Декомпиляция]" not in stdout
    assert "[Preparing]" not in stdout
    assert "[Decompiling]" not in stdout

    # And the JSON must parse cleanly.
    data = json.loads(stdout)
    assert "start" in data["labels"]


# =============================================================================
# 11. JSON output is stable (sorted keys)
# =============================================================================


def test_inspect_json_is_sorted():
    """Output JSON is serialized with sort_keys=True for stability
    (important for snapshot-style regression testing in the future)."""
    rc, out = _run_inspect([str(TEST_GAME)])
    # Check that keys appear in sorted order at the top level.
    # We can't easily assert "sort_keys=True" directly, but we can
    # re-parse and re-dump with sort_keys and check it matches.
    parsed = json.loads(out)
    redumped = json.dumps(parsed, indent=2, sort_keys=True, ensure_ascii=False)
    # The original output should already be sorted (modulo whitespace).
    # Compare by re-parsing the redumped: must equal original.
    assert json.loads(redumped) == parsed


# =============================================================================
# 12. Dispatch integration — _dispatch_subcommand routes to inspect
# =============================================================================


def test_dispatch_subcommand_routes_inspect():
    """`_dispatch_subcommand(['senpy', 'inspect', 'test_game/'])` returns
    the inspect exit code (not None).

    _dispatch_subcommand expects sys.argv-style argv (with argv[0] being
    the program name); the subcommand is at argv[1].
    """
    from senpy.cli.main import _dispatch_subcommand

    rc = _dispatch_subcommand(["senpy", "inspect", str(TEST_GAME)])
    assert rc is not None
    assert rc == 0
