"""Idempotency tests for Senpy formatter.

Contract: format(format(x)) == format(x)

This is the most important property of any formatter (Black, ruff format, etc).
If not idempotent — formatter is broken.

Test cases cover:
- Tab → 4 spaces
- Trailing whitespace
- Missing EOF newline
- Too many blank lines
- Mixed tab + spaces
- Skip blocks (# senpy: format off ... on)
- Already-formatted file (no-op)
- Empty file
- File with only comments
- Realistic .rpy with label/screen/menu
"""

from __future__ import annotations

from pathlib import Path

import pytest

from senpy.formatter import FormatConfig, Formatter


@pytest.fixture
def formatter() -> Formatter:
    return Formatter(FormatConfig())


# =============================================================================
# Idempotency parametrized tests
# test
# =============================================================================


@pytest.mark.parametrize(
    "code,label",
    [
        # 1. Tab → 4 spaces
        (
            'label start:\n\t"Hello"\n\treturn\n',
            "tab_to_spaces",
        ),
        # 2. Trailing whitespace on multiple lines
        (
            'label start:   \n    "Hello"   \n    return\t\n',
            "trailing_whitespace",
        ),
        # 3. No newline at end of file
        (
            'label start:\n    "Hello"\n    return',
            "no_eof_newline",
        ),
        # 4. Multiple newlines at end of file
        (
            'label start:\n    "Hello"\n    return\n\n\n\n',
            "multiple_eof_newlines",
        ),
        # 5. Too many blank lines between labels
        (
            'label a:\n    "x"\n\n\n\n\nlabel b:\n    "y"\n',
            "too_many_blanks",
        ),
        # 6. Mixed tab + spaces
        (
            'label start:\n  \t"Mixed"\n',
            "mixed_tab_space",
        ),
        # 7. Skip block — should NOT be touched
        (
            "# senpy: format off\n$ x =\t1\n# senpy: format on\n",
            "skip_block",
        ),
        # 8. Already formatted (no-op)
        (
            'label start:\n    "Hello"\n    return\n',
            "already_formatted",
        ),
        # 9. Empty file
        (
            "",
            "empty",
        ),
        # 10. Only comments
        (
            "# comment 1\n# comment 2\n",
            "only_comments",
        ),
        # 11. Realistic .rpy with multiple scopes
        (
            'label start:\n    "Hello"\n    jump chapter2\n\n\n\n\n'
            'label chapter2:\n    "World"\n    return\n',
            "realistic_multi_label",
        ),
        # 12. Screen block
        (
            'screen main_menu():\n    textbutton "Start" action Start()\n'
            '    textbutton "Quit" action Quit()\n',
            "screen_block",
        ),
        # 13. Init python block
        (
            "init python:\n    config.developer = True\n    \n",
            "init_python",
        ),
        # 14. CRLF line endings (Windows)
        (
            'label start:\r\n\t"Hello"\r\n\treturn\r\n',
            "crlf_endings",
        ),
        # 15. Leading blank lines at start of file
        (
            '\n\n\nlabel start:\n    "Hello"\n    return\n',
            "leading_blanks",
        ),
    ],
)
def test_idempotent(formatter: Formatter, code: str, label: str) -> None:
    """format(format(x)) == format(x) — must hold for any input."""
    once = formatter.format_code(code)
    twice = formatter.format_code(once)
    assert once == twice, (
        f"NOT idempotent for case '{label}':\n"
        f"--- once ---\n{once!r}\n"
        f"--- twice ---\n{twice!r}\n"
        f"--- diff ---\n"
        + "\n".join(
            f"  L{i}: {a!r} vs {b!r}"
            for i, (a, b) in enumerate(zip(once.split("\n"), twice.split("\n")))
            if a != b
        )
    )


# =============================================================================
# Specific behavior tests
# =============================================================================


def test_tab_converted_to_spaces(formatter: Formatter) -> None:
    """Tab in indentation → 4 spaces."""
    code = 'label start:\n\t"Hello"\n'
    result = formatter.format_code(code)
    assert "\t" not in result, f"Tab still present:\n{result}"
    assert '    "Hello"' in result, f"4-space indent not applied:\n{result}"


def test_trailing_whitespace_stripped(formatter: Formatter) -> None:
    """Trailing spaces/tabs stripped, newline preserved."""
    code = 'label start:   \n    "Hello"   \n'
    result = formatter.format_code(code)
    assert "   \n" not in result, f"Trailing whitespace not stripped:\n{result!r}"
    assert result.endswith("\n"), "EOF newline missing"


def test_eof_newline_added(formatter: Formatter) -> None:
    """If no newline at end → exactly one added."""
    code = 'label start:\n    "Hello"'
    result = formatter.format_code(code)
    assert result.endswith("\n"), "EOF newline not added"
    assert not result.endswith("\n\n"), "Multiple EOF newlines"


def test_eof_newline_collapsed(formatter: Formatter) -> None:
    """If multiple newlines at end → at most max_blank_lines + 1 (final newline)."""
    code = 'label start:\n    "Hello"\n\n\n\n'
    result = formatter.format_code(code)
    # After FMT-BLANK-LINES (max 2) + FMT-EOF-NEWLINE: "Hello" + 2 blank + \n
    # = "Hello"\n\n\n (3 newlines = 2 blank lines + final newline)
    # This is correct: 2 blank lines at end is allowed.
    assert result.endswith('"Hello"\n\n\n') or result.endswith('"Hello"\n'), (
        f"Unexpected ending: {result!r}"
    )
    # Should NOT have 4+ newlines (3+ blank lines)
    assert not result.endswith("\n\n\n\n"), f"3+ blank lines at end:\n{result!r}"


def test_blank_lines_collapsed(formatter: Formatter) -> None:
    """4+ consecutive blank lines → at most 2 (max_blank_lines=2)."""
    # 5 newlines between labels = 4 blank lines → should collapse to 2 blank lines
    code = 'label a:\n    "x"\n\n\n\n\nlabel b:\n    "y"\n'
    result = formatter.format_code(code)
    # 4 blank lines = 5 newlines between "x" and "label b"
    # After collapse: 2 blank lines = 3 newlines between
    # So "\n\n\n\n\n" should be replaced with "\n\n\n"
    assert "\n\n\n\n" not in result, f"3+ blank lines not collapsed:\n{result!r}"
    # 2 blank lines (="\n\n\n") is OK and expected
    assert "\n\n\nlabel b:" in result, f"Expected 2 blank lines before label b:\n{result!r}"


def test_skip_block_preserved(formatter: Formatter) -> None:
    """# senpy: format off ... on — content untouched."""
    code = "# senpy: format off\n$ x =\t1   \n# senpy: format on\n"
    result = formatter.format_code(code)
    assert "$ x =\t1   " in result, f"Skip block was modified!\n{result!r}"


def test_already_formatted_is_noop(formatter: Formatter) -> None:
    """Already-formatted file should not change."""
    code = 'label start:\n    "Hello"\n    return\n'
    result = formatter.format_code(code)
    assert result == code, (
        f"Already-formatted file changed:\n--- in ---\n{code}\n--- out ---\n{result}"
    )


def test_empty_file(formatter: Formatter) -> None:
    """Empty file → empty file (or just \\n)."""
    code = ""
    result = formatter.format_code(code)
    # Empty input → empty output (we don't force a newline on empty file)
    assert result in ("", "\n"), f"Empty file became: {result!r}"


def test_format_file_returns_true_when_modified(formatter: Formatter, tmp_path: Path) -> None:
    """format_file returns True when file was modified, False otherwise."""
    f = tmp_path / "test.rpy"
    f.write_text('label start:\n\t"Hello"\n', encoding="utf-8")
    assert formatter.format_file(str(f)) is True
    # Second run — no changes
    assert formatter.format_file(str(f)) is False


def test_format_file_preserves_skip_blocks(formatter: Formatter, tmp_path: Path) -> None:
    """format_file with skip blocks — skip content untouched."""
    f = tmp_path / "test.rpy"
    original = '# senpy: format off\n$ x =\t1   \n# senpy: format on\nlabel start:\n\t"Hello"\n'
    f.write_text(original, encoding="utf-8")
    formatter.format_file(str(f))
    result = f.read_text(encoding="utf-8")
    assert "$ x =\t1   " in result, "Skip block content was modified!"
    # But tab outside skip should be converted
    assert "\t" not in result.split("# senpy: format on")[1], "Tab outside skip not converted!"


# =============================================================================
# CLI integration smoke test (no subprocess — direct call)
# =============================================================================


def test_format_code_via_formatter_class() -> None:
    """Smoke test: Formatter class works as documented in __init__.py."""
    from senpy.formatter import FormatConfig, Formatter

    f = Formatter(FormatConfig(indent_size=4))
    code = 'label start:\n\t"Hello"\n\treturn\n'
    result = f.format_code(code)
    assert "    " in result, "4-space indent not applied"
    assert "\t" not in result, "Tab not converted"
    assert result.endswith("\n"), "EOF newline missing"
