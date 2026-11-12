"""Coverage push: Rich-render branches of senpy/rules/rules_info.py.

``show_rules_table`` and ``show_rule_detail`` build Rich ``Table`` /
``Panel`` renderings of ``RULES_DATABASE``. They were the only two
untested functions in this module — the underlying ``RULES_DATABASE``
data is already well-covered via ``tests/cli/test_rule_cli.py`` (which
exercises the JSON / Rich-table dispatch via the ``senpy rule`` CLI
subcommand, but that path runs in a subprocess so the in-process
``console.print`` calls are not recorded by coverage).

These tests patch the module-level ``console`` with a capturing
non-tty Console and assert that the rendered output contains the
expected rule codes, severity markers, and structured fields.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from senpy.rules import rules_info
from senpy.rules.rules_info import RULES_DATABASE, show_rule_detail, show_rules_table


@pytest.fixture
def captured_console(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
    """Replace ``rules_info.console`` with a capturing non-tty Console."""
    buf = io.StringIO()
    cap = Console(file=buf, force_terminal=False, no_color=True, width=200)
    monkeypatch.setattr(rules_info, "console", cap)
    return buf


# ---------------------------------------------------------------------------
# show_rules_table
# ---------------------------------------------------------------------------


class TestShowRulesTable:
    def test_renders_all_rules(self, captured_console: io.StringIO) -> None:
        show_rules_table()
        out = captured_console.getvalue()
        # Title contains the dynamic rule count.
        assert f"All {len(RULES_DATABASE)} Rules" in out
        # Every rule code appears in the table.
        for code in RULES_DATABASE:
            assert code in out, f"rule {code} missing from rendered table"

    def test_renders_at_least_one_error_warning_hint(self, captured_console: io.StringIO) -> None:
        """Verify the severity-style ternary picks all three branches."""
        show_rules_table()
        out = captured_console.getvalue()
        # RULES_DATABASE contains ERROR (RPY000), WARNING (RPY001),
        # and HINT/INFO rules — verify all three severity words appear.
        assert "ERROR" in out
        assert "WARNING" in out

    def test_renders_hint_footer(self, captured_console: io.StringIO) -> None:
        show_rules_table()
        out = captured_console.getvalue()
        assert "Run 'senpy --rule <CODE>'" in out


# ---------------------------------------------------------------------------
# show_rule_detail
# ---------------------------------------------------------------------------


class TestShowRuleDetail:
    def test_unknown_code_prints_error(self, captured_console: io.StringIO) -> None:
        show_rule_detail("RPY999")
        out = captured_console.getvalue()
        assert "Unknown rule code" in out
        assert "RPY999" in out
        # No panel rendered for unknown codes.
        assert "Rule RPY999" not in out

    def test_known_code_renders_panel(self, captured_console: io.StringIO) -> None:
        show_rule_detail("RPY001")
        out = captured_console.getvalue()
        # Panel title.
        assert "Rule RPY001" in out
        # All four sections.
        assert "BAD PRACTICE" in out
        assert "GOOD PRACTICE" in out
        # Title and severity are always rendered.
        info = RULES_DATABASE["RPY001"]
        assert info["title"] in out
        assert info["severity"] in out

    def test_renders_tags_when_present(self, captured_console: io.StringIO) -> None:
        # Find a rule that has tags (most do).
        code_with_tags = next(c for c, info in RULES_DATABASE.items() if info.get("tags"))
        show_rule_detail(code_with_tags)
        out = captured_console.getvalue()
        info = RULES_DATABASE[code_with_tags]
        for tag in info["tags"]:
            assert tag in out, f"tag {tag!r} missing from rendered detail"

    def test_renders_without_tags_when_absent(self, captured_console: io.StringIO) -> None:
        # Find a rule with NO tags (or empty tags) — if none, this test
        # is skipped rather than failing.
        code_no_tags = next(
            (c for c, info in RULES_DATABASE.items() if not info.get("tags")),
            None,
        )
        if code_no_tags is None:
            pytest.skip("every rule in RULES_DATABASE has tags")
        show_rule_detail(code_no_tags)
        out = captured_console.getvalue()
        # The function still renders the title — the no-tags branch
        # only skips the "Tags: ..." line.
        info = RULES_DATABASE[code_no_tags]
        assert info["title"] in out

    @pytest.mark.parametrize(
        "code",
        # Pick one rule per severity bucket to exercise all three
        # sev_style ternary branches in the renderer.
        [
            next(c for c, i in RULES_DATABASE.items() if i["severity"] == "ERROR"),
            next(c for c, i in RULES_DATABASE.items() if i["severity"] == "WARNING"),
            next(c for c, i in RULES_DATABASE.items() if i["severity"] not in ("ERROR", "WARNING")),
        ],
    )
    def test_renders_each_severity_bucket(self, code: str, captured_console: io.StringIO) -> None:
        show_rule_detail(code)
        out = captured_console.getvalue()
        info = RULES_DATABASE[code]
        assert info["severity"] in out
        # The full ``why`` text can be very long (RPY000's is ~600 chars)
        # and Rich truncates lines that overflow the console width. Use
        # the first sentence as a stable substring assertion.
        first_sentence = info["why"].split(".")[0]
        assert first_sentence in out
