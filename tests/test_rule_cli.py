"""CLI tests for `senpy rule` subcommand.

Covers `senpy rule list` (text + json, with --tag / --severity filters)
and `senpy rule show <CODE>` (text + json, including unknown code).

All tests run dispatch_rule([...]) directly (no subprocess) for speed,
mirroring the pattern in tests/test_inspect_cli.py.
"""

from __future__ import annotations

import io
import json
import sys

import pytest

from senpy.cli.rule_dispatch import dispatch_rule
from senpy.rules.rules_info import RULES_DATABASE

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    """Run dispatch_rule(argv), capture stdout/stderr, return (exit_code, out, err)."""
    rc = dispatch_rule(argv)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


# ---------------------------------------------------------------------------
# `senpy rule list`
# ---------------------------------------------------------------------------


class TestRuleListText:
    def test_list_text_prints_all_rules(self, capsys):
        rc, out, _ = _run(["list"], capsys)
        assert rc == 0
        # Every rule code must appear in the output.
        for code in RULES_DATABASE:
            assert code in out, f"{code} missing from list output"


class TestRuleListJson:
    def test_list_json_emits_a_json_array(self, capsys):
        rc, out, _ = _run(["list", "--format", "json"], capsys)
        assert rc == 0
        data = json.loads(out)
        assert isinstance(data, list)
        # `>=` instead of `==`: autoloaded plugins may add extra rules
        # (e.g. RPY901 from examples/my_senpy_plugin if installed in dev env).
        assert len(data) >= len(RULES_DATABASE)

    def test_list_json_each_entry_has_required_fields(self, capsys):
        rc, out, _ = _run(["list", "--format", "json"], capsys)
        data = json.loads(out)
        required = {"code", "title", "severity", "tags", "why", "bad", "good"}
        for entry in data:
            missing = required - set(entry.keys())
            assert not missing, f"entry {entry.get('code')} missing fields: {missing}"

    def test_list_json_includes_code_field(self, capsys):
        """JSON output must include the rule code as a field (not just as
        the dict key) — otherwise consumers can't sort/group programmatically.

        Note: we check `issubset`, not equality, because plugins registered
        via `autoload_plugins()` may add extra codes (e.g. RPY901 from the
        example plugin if it's installed in the dev environment). Built-in
        codes must always be present; plugin codes are a bonus.
        """
        rc, out, _ = _run(["list", "--format", "json"], capsys)
        data = json.loads(out)
        codes = {entry["code"] for entry in data}
        assert set(RULES_DATABASE.keys()).issubset(codes)

    def test_list_json_includes_tags_array(self, capsys):
        rc, out, _ = _run(["list", "--format", "json"], capsys)
        data = json.loads(out)
        rpy104 = next(e for e in data if e["code"] == "RPY104")
        assert isinstance(rpy104["tags"], list)
        assert "variables" in rpy104["tags"]
        assert "rollback" in rpy104["tags"]


class TestRuleListTagFilter:
    def test_list_filter_by_single_tag_returns_matching_rules(self, capsys):
        rc, out, _ = _run(["list", "--format", "json", "--tag", "rollback"], capsys)
        assert rc == 0
        data = json.loads(out)
        # Every returned rule must have the 'rollback' tag.
        for entry in data:
            assert (
                "rollback" in entry["tags"]
            ), f"{entry['code']} returned by --tag rollback but lacks the tag"
        # Sanity: at least RPY104, RPY105, RPY106 have rollback tag.
        codes = {e["code"] for e in data}
        assert {"RPY104", "RPY105", "RPY106"}.issubset(codes)

    def test_list_filter_by_multiple_tags_is_union(self, capsys):
        """Multiple --tag values produce a union (any tag matches)."""
        rc, out, _ = _run(
            ["list", "--format", "json", "--tag", "audio", "--tag", "images"],
            capsys,
        )
        data = json.loads(out)
        codes = {e["code"] for e in data}
        # Audio rules
        assert {"RPY501", "RPY505"}.issubset(codes)
        # Image rules
        assert {"RPY502", "RPY504"}.issubset(codes)

    def test_list_filter_by_nonexistent_tag_returns_empty_list(self, capsys):
        rc, out, _ = _run(["list", "--format", "json", "--tag", "nonexistent"], capsys)
        assert rc == 0
        data = json.loads(out)
        assert data == []


class TestRuleListSeverityFilter:
    def test_list_filter_by_severity_error(self, capsys):
        rc, out, _ = _run(["list", "--format", "json", "--severity", "ERROR"], capsys)
        data = json.loads(out)
        for entry in data:
            assert entry["severity"] == "ERROR"

    def test_list_filter_by_severity_hint(self, capsys):
        rc, out, _ = _run(["list", "--format", "json", "--severity", "HINT"], capsys)
        data = json.loads(out)
        for entry in data:
            assert entry["severity"] == "HINT"
        # Sanity: RPY701, RPY702, RPY703 are HINT.
        codes = {e["code"] for e in data}
        assert {"RPY701", "RPY702", "RPY703"}.issubset(codes)


# ---------------------------------------------------------------------------
# `senpy rule show`
# ---------------------------------------------------------------------------


class TestRuleShowText:
    def test_show_known_rule_prints_detail_panel(self, capsys):
        rc, out, _ = _run(["show", "RPY104"], capsys)
        assert rc == 0
        assert "RPY104" in out
        # Title from the rule must appear.
        assert "Dynamic assignment" in out
        # Tags must appear in the detail panel.
        assert "rollback" in out

    def test_show_unknown_rule_exits_nonzero(self, capsys):
        rc, out, err = _run(["show", "RPY999"], capsys)
        assert rc != 0
        # Error message goes to stderr and mentions the unknown code.
        assert "RPY999" in err or "RPY999" in out

    def test_show_lowercases_input_code(self, capsys):
        """User typing 'rpy104' should still work — codes are case-insensitive."""
        rc, out, _ = _run(["show", "rpy104"], capsys)
        assert rc == 0
        assert "RPY104" in out


class TestRuleShowJson:
    def test_show_json_known_rule(self, capsys):
        rc, out, _ = _run(["show", "RPY104", "--format", "json"], capsys)
        assert rc == 0
        data = json.loads(out)
        assert data["code"] == "RPY104"
        assert data["title"] == "Dynamic assignment without top-level 'default'"
        assert data["severity"] == "WARNING"
        assert "rollback" in data["tags"]

    def test_show_json_unknown_rule_exits_nonzero(self, capsys):
        rc, out, _ = _run(["show", "RPY999", "--format", "json"], capsys)
        assert rc != 0


# ---------------------------------------------------------------------------
# `senpy rule --help`
# ---------------------------------------------------------------------------


class TestRuleHelp:
    def test_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            dispatch_rule(["--help"])
        assert exc_info.value.code == 0

    def test_no_subcommand_prints_help_and_exits_nonzero(self, capsys):
        """`senpy rule` with no subcommand should print usage and exit non-zero."""
        rc = dispatch_rule([])
        assert rc != 0
        captured = capsys.readouterr()
        # Should mention `list` and `show` as subcommands.
        assert "list" in captured.out + captured.err
        assert "show" in captured.out + captured.err


# ---------------------------------------------------------------------------
# `senpy rule list --output-file`
# ---------------------------------------------------------------------------


class TestRuleListOutputFile:
    def test_list_json_writes_to_output_file(self, tmp_path, capsys):
        out_file = tmp_path / "rules.json"
        rc = dispatch_rule(["list", "--format", "json", "-o", str(out_file)])
        assert rc == 0
        data = json.loads(out_file.read_text(encoding="utf-8"))
        # `>=` instead of `==`: autoloaded plugins may add extra rules.
        assert len(data) >= len(RULES_DATABASE)

    def test_list_text_writes_to_output_file(self, tmp_path, capsys):
        out_file = tmp_path / "rules.txt"
        rc = dispatch_rule(["list", "-o", str(out_file)])
        assert rc == 0
        text = out_file.read_text(encoding="utf-8")
        for code in RULES_DATABASE:
            assert code in text
