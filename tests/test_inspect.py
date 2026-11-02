"""Tests for `senpy/formats/inspect.py` — the `dump_symbols()` function.

WL-506: `senpy inspect` subcommand. The `dump_symbols(analyzer)`
function serializes all symbols collected by `SenpyAnalyzer` into a
JSON-serializable dict for CLI output.

Test strategy (per the 0.7.4 plan): assertion-based + size invariants.
Snapshot tests are explicitly NOT used (brittle during active development).

The fixture is `test_game/script.rpy` (95 lines), which exercises every
section of the JSON output: labels, screens, variables, transforms,
images, jump_sources, used_assets, diagnostics, unresolved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from senpy.core.analyzer import SenpyAnalyzer

# Import will fail until senpy/formats/inspect.py is created (Phase 2 RED).
from senpy.formats.inspect import dump_symbols

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_GAME = REPO_ROOT / "test_game"


# =============================================================================
# Fixture: run analyzer on test_game, return (analyzer, dump)
# =============================================================================


@pytest.fixture(scope="module")
def analyzer() -> SenpyAnalyzer:
    """Run SenpyAnalyzer on test_game/ once per module."""
    a = SenpyAnalyzer(str(TEST_GAME), no_cache=True)
    a.run(quiet=True)
    return a


@pytest.fixture(scope="module")
def dump(analyzer) -> dict:
    """dump_symbols(analyzer) — full JSON-serializable dict."""
    return dump_symbols(analyzer)


# =============================================================================
# 1. Mandatory top-level keys
# =============================================================================


def test_dump_has_all_mandatory_keys(dump: dict):
    """Every section listed in the design must be present at top level."""
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
    assert expected_keys.issubset(dump.keys()), f"Missing keys: {expected_keys - dump.keys()}"


def test_unresolved_has_all_subkeys(dump: dict):
    """The `unresolved` section must contain all 4 sub-sections."""
    expected = {"broken_jumps", "missing_screens", "unreferenced_labels", "unused_assets"}
    assert expected.issubset(
        dump["unresolved"].keys()
    ), f"Missing unresolved subkeys: {expected - dump['unresolved'].keys()}"


def test_stats_has_counters(dump: dict):
    """stats must contain per-section counters for quick overview."""
    expected = {
        "files",
        "lines",
        "labels",
        "screens",
        "variables",
        "transforms",
        "images",
        "diagnostics",
        "broken_jumps",
        "missing_screens",
        "unreferenced_labels",
        "unused_assets",
    }
    assert expected.issubset(
        dump["stats"].keys()
    ), f"Missing stats counters: {expected - dump['stats'].keys()}"


# =============================================================================
# 2. Size invariants — stats counters match actual section sizes
# =============================================================================


def test_stats_labels_count_matches(dump: dict):
    assert dump["stats"]["labels"] == len(dump["labels"])


def test_stats_screens_count_matches(dump: dict):
    assert dump["stats"]["screens"] == len(dump["screens"])


def test_stats_variables_count_matches(dump: dict):
    assert dump["stats"]["variables"] == len(dump["variables"])


def test_stats_images_count_matches(dump: dict):
    assert dump["stats"]["images"] == len(dump["images"])


def test_stats_diagnostics_count_matches(dump: dict):
    assert dump["stats"]["diagnostics"] == len(dump["diagnostics"])


def test_stats_broken_jumps_count_matches(dump: dict):
    assert dump["stats"]["broken_jumps"] == len(dump["unresolved"]["broken_jumps"])


def test_stats_missing_screens_count_matches(dump: dict):
    assert dump["stats"]["missing_screens"] == len(dump["unresolved"]["missing_screens"])


def test_stats_unreferenced_labels_count_matches(dump: dict):
    assert dump["stats"]["unreferenced_labels"] == len(dump["unresolved"]["unreferenced_labels"])


def test_stats_unused_assets_count_matches(dump: dict):
    assert dump["stats"]["unused_assets"] == len(dump["unresolved"]["unused_assets"])


# =============================================================================
# 3. Specific facts from test_game/script.rpy
# =============================================================================


def test_dump_finds_start_label(dump: dict):
    """test_game/script.rpy has `label start:` — must be in dump."""
    assert "start" in dump["labels"]


def test_dump_start_label_has_file_path(dump: dict):
    """The `start` label must have a file_path ending in script.rpy."""
    start = dump["labels"]["start"]
    assert start["file_path"].endswith("script.rpy"), f"Got: {start['file_path']}"


def test_dump_finds_shop_screen(dump: dict):
    """test_game/script.rpy has `screen shop():` — must be in dump."""
    assert "shop" in dump["screens"]


def test_dump_finds_default_friend_name(dump: dict):
    """test_game/script.rpy has `default friend_name = "Дима"` — must be
    in dump as a variable with is_constant=False."""
    assert "friend_name" in dump["variables"]
    assert dump["variables"]["friend_name"]["is_constant"] is False


def test_dump_finds_define_max_hp(dump: dict):
    """test_game/script.rpy has `define max_hp = 100` — must be in dump
    with is_constant=True."""
    assert "max_hp" in dump["variables"]
    assert dump["variables"]["max_hp"]["is_constant"] is True


def test_dump_finds_bg_room_image(dump: dict):
    """test_game/script.rpy declares `image bg room = "room_day.png"`."""
    assert "bg room" in dump["images"]


# =============================================================================
# 4. Unresolved consistency — structural invariants
# =============================================================================


def test_broken_jumps_targets_not_in_labels(dump: dict):
    """Every broken jump target must NOT be a known label (otherwise it
    would not be broken)."""
    label_names = set(dump["labels"].keys())
    for entry in dump["unresolved"]["broken_jumps"]:
        # Each broken jump entry should reference a target name.
        # Format: list of dicts OR list of lists — implementation detail.
        # We check: target name must not appear in labels.
        target = _extract_target(entry)
        assert (
            target not in label_names
        ), f"Broken jump target {target!r} IS in labels — not actually broken?"


def test_missing_screens_not_in_screens(dump: dict):
    """Every missing screen must NOT be a known screen."""
    screen_names = set(dump["screens"].keys())
    for entry in dump["unresolved"]["missing_screens"]:
        target = _extract_target(entry)
        assert (
            target not in screen_names
        ), f"Missing screen {target!r} IS in screens — not actually missing?"


def test_unreferenced_labels_in_labels(dump: dict):
    """Every unreferenced label must still be a known label (it exists,
    but no one jumps to it)."""
    label_names = set(dump["labels"].keys())
    for entry in dump["unresolved"]["unreferenced_labels"]:
        name = entry if isinstance(entry, str) else _extract_target(entry)
        assert (
            name in label_names
        ), f"Unreferenced label {name!r} is NOT in labels — does not exist?"


# =============================================================================
# 5. with_source flag — code_line / body inclusion
# =============================================================================


def test_dump_default_omits_code_line(analyzer: SenpyAnalyzer):
    """By default, dump_symbols does not include `code_line`/`body`."""
    d = dump_symbols(analyzer, with_source=False)
    # Pick the first label we know exists.
    if "start" in d["labels"]:
        assert "code_line" not in d["labels"]["start"], "code_line should be omitted by default"
    # ImageSymbol has `body` not `code_line`.
    if "bg room" in d["images"]:
        assert "body" not in d["images"]["bg room"], "body should be omitted by default"


def test_dump_with_source_includes_code_line(analyzer: SenpyAnalyzer):
    """With with_source=True, dump_symbols includes `code_line`/`body`."""
    d = dump_symbols(analyzer, with_source=True)
    if "start" in d["labels"]:
        assert "code_line" in d["labels"]["start"], "code_line should be present with --with-source"
    if "bg room" in d["images"]:
        assert "body" in d["images"]["bg room"], "body should be present with --with-source"


# =============================================================================
# 6. JSON serializability — no sets, no tuples
# =============================================================================


def test_dump_is_json_serializable(dump: dict):
    """The full dump must be JSON-serializable (no sets, no tuples, no
    dataclasses — all converted to lists / dicts / primitives)."""
    text = json.dumps(dump, indent=2, sort_keys=True, ensure_ascii=False)
    assert isinstance(text, str)
    # Round-trip must preserve data.
    restored = json.loads(text)
    assert restored == dump


def test_dump_outgoing_jumps_are_lists(dump: dict):
    """LabelSymbol.outgoing_jumps is a set internally — must be a list in JSON."""
    for label_name, label_data in dump["labels"].items():
        if "outgoing_jumps" in label_data:
            assert isinstance(label_data["outgoing_jumps"], list), (
                f"{label_name}.outgoing_jumps must be list, got "
                f"{type(label_data['outgoing_jumps'])}"
            )


def test_dump_jump_sources_values_are_lists(dump: dict):
    """jump_sources values are list[tuple[str, int]] internally — in JSON
    must be list[list[str|int]]."""
    for target, sources in dump["jump_sources"].items():
        assert isinstance(
            sources, list
        ), f"jump_sources[{target!r}] must be list, got {type(sources)}"
        for src in sources:
            assert isinstance(src, list), (
                f"jump_sources[{target!r}] entry must be list (not tuple), " f"got {type(src)}"
            )


def test_dump_used_assets_is_list(dump: dict):
    """used_assets is a set internally — must be a sorted list in JSON."""
    assert isinstance(
        dump["used_assets"], list
    ), f"used_assets must be list, got {type(dump['used_assets'])}"


# =============================================================================
# Helpers
# =============================================================================


def _extract_target(entry) -> str:
    """Extract a target name from an unresolved entry.

    The entry can be either:
      - A string (e.g. unreferenced label name): return as-is.
      - A dict with a 'target' key: return entry['target'].
      - A list of [file, line, target] or [file, line, target, ...]: return last element.
    """
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        for key in ("target", "name", "label", "screen"):
            if key in entry:
                return entry[key]
        raise AssertionError(f"Cannot extract target from dict: {entry}")
    if isinstance(entry, list):
        # Last element is conventionally the target name.
        return entry[-1]
    raise AssertionError(f"Cannot extract target from {type(entry)}: {entry}")
