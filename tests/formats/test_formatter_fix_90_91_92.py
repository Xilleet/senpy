"""Regression tests for formatter.

``# senpy: format off`` / ``on`` directives matched inside string
literals. ``_RE_FORMAT_OFF.search(raw)`` scanned the raw line including
string content, so a dialogue line ``    "# senpy: format off"`` or an
assignment ``$ note = "# senpy: format off until v2"`` silently flipped
``skip_block`` and the formatter passed the rest of the file through
untouched. Fix: scan only the comment portion of the line (via
``_find_comment_start``).

``=`` (and binary ops) were not normalised before a unary operand.
``_OP_PATTERNS`` right-boundary ``(?=[\\w\\(\\'\\\"\\{\\[])`` excluded operator
chars, so ``x=-5`` stayed ``x=-5`` instead of becoming ``x = -5`` (same for
``x=+y``, ``x +=-1``, ``x=~mask``). Fix: admit ``- + ~`` in the right
boundary — safe because unary ops are still filtered by the left boundary
``(?<=[\\w\\)\\]\\}])`` (a unary op is preceded by another operator, not a
word/bracket).

``_split_by_strings`` did not split on ``#`` comments, so the
op/comma/colon/string-consistency rules reformatted comment interiors:
``$ x = 1  #a=b,c`` became ``$ x = 1  #a = b, c``. Fix: once a real ``#``
(outside a string) is reached, the rest of the line is a single preserved
segment (``is_string=True``).
"""

from __future__ import annotations

import pytest

from senpy.formatter import FormatConfig, Formatter


@pytest.fixture
def formatter() -> Formatter:
    return Formatter(FormatConfig())


# =============================================================================
# format-off / format-on directives inside string literals
# =============================================================================


class TestFix90FormatDirectiveInStringLiteral:
    """A ``# senpy: format off`` / ``on`` token that appears inside a string
    literal must NOT toggle the skip block — only a real comment may."""

    def test_format_off_inside_dialogue_string_does_not_skip(self, formatter: Formatter) -> None:
        """A dialogue line whose text contains ``# senpy: format off`` must
        not cause subsequent code lines to be skipped."""
        code = (
            '    "# senpy: format off"\n'
            "$ x=1\n"  # would be normalised to "$ x = 1" if NOT skipped
        )
        result = formatter.format_code(code)
        assert "$ x = 1" in result, (
            f"format-off inside dialogue string wrongly skipped the next " f"line:\n{result!r}"
        )

    def test_format_off_inside_assignment_string_does_not_skip(self, formatter: Formatter) -> None:
        """``$ note = "# senpy: format off until v2"`` must not skip."""
        code = '$ note = "# senpy: format off until v2"\n' "$ y=2\n"
        result = formatter.format_code(code)
        assert (
            "$ y = 2" in result
        ), f"format-off inside assignment string wrongly skipped:\n{result!r}"

    def test_format_on_inside_string_literal_does_not_unskip(self, formatter: Formatter) -> None:
        """Symmetric: ``# senpy: format on`` inside a string must not unskip
        a genuinely active skip block."""
        code = (
            "# senpy: format off\n"
            "$ keep=1\n"  # inside skip — must stay untouched
            '    "# senpy: format on"\n'  # string literal, NOT a directive
            "$ stillskip=2\n"  # still inside skip — must stay untouched
            "# senpy: format on\n"
        )
        result = formatter.format_code(code)
        # Both skip-block lines must be preserved verbatim (not normalised).
        assert "$ keep=1" in result, f"first skip line was touched:\n{result!r}"
        assert (
            "$ stillskip=2" in result
        ), f"format-on inside string wrongly ended the skip block:\n{result!r}"

    def test_legitimate_format_off_still_skips(self, formatter: Formatter) -> None:
        """Regression guard: a real ``# senpy: format off`` comment still
        activates the skip block."""
        code = "# senpy: format off\n$ x=\t1   \n# senpy: format on\n"
        result = formatter.format_code(code)
        assert "$ x=\t1   " in result, f"legitimate skip block was touched:\n{result!r}"

    def test_format_off_after_code_on_same_line_still_skips(self, formatter: Formatter) -> None:
        """``$ x = 1  # senpy: format off`` — directive in a real comment
        after code — must still activate skip (the comment portion is a
        real comment, not a string)."""
        code = "$ x = 1  # senpy: format off\n$ y=2\n# senpy: format on\n"
        result = formatter.format_code(code)
        # `$ y=2` is inside the skip block → must be preserved verbatim.
        assert "$ y=2" in result, f"inline-comment directive did not activate skip:\n{result!r}"

    def test_idempotent_format_off_in_string(self, formatter: Formatter) -> None:
        code = '    "# senpy: format off"\n' "$ x=1\n"
        once = formatter.format_code(code)
        twice = formatter.format_code(once)
        assert once == twice, f"NOT idempotent:\n--- once ---\n{once}\n--- twice ---\n{twice}"


# =============================================================================
# assignment / binary op before a unary operand
# =============================================================================


class TestFix91UnaryRightOperand:
    """``=`` and binary ops must be normalised even when the right operand
    starts with a unary ``-`` / ``+`` / ``~``."""

    @pytest.mark.parametrize(
        "code,expected",
        [
            ("$ x=-5\n", "$ x = -5\n"),
            ("$ x=+y\n", "$ x = +y\n"),
            ("$ x=~mask\n", "$ x = ~mask\n"),
            ("$ x +=-1\n", "$ x += -1\n"),
            ("$ x -=+2\n", "$ x -= +2\n"),
            ("$ a=1+-5\n", "$ a = 1 + -5\n"),
            ("$ a=1-+5\n", "$ a = 1 - +5\n"),
            ("$ b=2*~flags\n", "$ b = 2 * ~flags\n"),
        ],
    )
    def test_op_normalised_before_unary(
        self, formatter: Formatter, code: str, expected: str
    ) -> None:
        result = formatter.format_code(code)
        assert (
            result == expected
        ), f"\n--- in ---\n{code}\n--- out ---\n{result}\n--- want ---\n{expected}"

    def test_unary_minus_not_split(self, formatter: Formatter) -> None:
        """``$ x = -5`` must stay ``$ x = -5`` (NOT ``$ x = - 5``)."""
        result = formatter.format_code("$ x = -5\n")
        assert "$ x = -5" in result
        assert "$ x = - 5" not in result, f"unary minus was split into binary:\n{result!r}"

    def test_unary_plus_not_split(self, formatter: Formatter) -> None:
        result = formatter.format_code("$ y = +x\n")
        assert "$ y = +x" in result
        assert "$ y = + x" not in result

    def test_unary_tilde_not_split(self, formatter: Formatter) -> None:
        result = formatter.format_code("$ z = ~mask\n")
        assert "$ z = ~mask" in result
        assert "$ z = ~ mask" not in result

    def test_idempotent_unary(self, formatter: Formatter) -> None:
        for code in ("$ x=-5\n", "$ a=1+-5\n", "$ x +=-1\n"):
            once = formatter.format_code(code)
            twice = formatter.format_code(once)
            assert (
                once == twice
            ), f"NOT idempotent for {code!r}:\n--- once ---\n{once}\n--- twice ---\n{twice}"


# =============================================================================
# comment interiors preserved by all spacing rules
# =============================================================================


class TestFix92CommentPreserved:
    """Everything after the first real ``#`` (outside a string) must be
    preserved verbatim — op/comma/colon/string-consistency rules must not
    reformat comment interiors."""

    def test_comment_with_equals_not_mangled(self, formatter: Formatter) -> None:
        """``$ x = 1  #a=b,c`` — the ``=`` and ``,`` inside the comment must
        stay untouched (previously became ``#a = b, c``)."""
        code = "$ x = 1  #a=b,c\n"
        result = formatter.format_code(code)
        assert "#a=b,c" in result, f"comment interior was mangled:\n{result!r}"
        assert "#a = b" not in result
        assert "#b, c" not in result

    def test_comment_with_commas_not_mangled(self, formatter: Formatter) -> None:
        """``$ f(a,b)  #g(x,y)`` — code normalised, comment preserved."""
        code = "$ f(a,b)  #g(x,y)\n"
        result = formatter.format_code(code)
        assert "$ f(a, b)" in result, f"code not normalised:\n{result!r}"
        assert "#g(x,y)" in result, f"comment mangled:\n{result!r}"
        assert "#g(x, y)" not in result

    def test_comment_with_colon_not_mangled(self, formatter: Formatter) -> None:
        """``$ y = 1  #if x :`` — comment colon preserved."""
        code = "$ y = 1  #if x :\n"
        result = formatter.format_code(code)
        assert "#if x :" in result, f"comment colon mangled:\n{result!r}"
        # The colon-spacing rule must NOT have collapsed " :" in the comment.
        # (It collapses to ":" — so the mangled form would be "#if x:".)
        # Note: "#if x:" alone is ambiguous, so we assert the original survives.

    def test_comment_with_single_quotes_not_converted(self, formatter: Formatter) -> None:
        """``$ z = 1  #'hi'`` — string-consistency must not convert ``'hi'``
        inside a comment to ``"hi"``."""
        code = "$ z = 1  #'hi'\n"
        result = formatter.format_code(code)
        assert "#'hi'" in result, f"comment quotes converted:\n{result!r}"
        assert '#"hi"' not in result

    def test_comment_only_line_preserved(self, formatter: Formatter) -> None:
        """A line that is only a comment must pass through verbatim."""
        code = "#if x : a=b,c\n"
        result = formatter.format_code(code)
        assert (
            result == "#if x : a=b,c\n"
        ), f"comment-only line was modified:\n--- in ---\n{code}\n--- out ---\n{result}"

    def test_hash_inside_string_before_real_comment(self, formatter: Formatter) -> None:
        """``$ x = "a#b"  #real comment`` — the ``#`` inside the string is
        NOT a comment marker; the real comment after it is preserved, and
        the string is untouched."""
        code = '$ x = "a#b"  #real=a,b\n'
        result = formatter.format_code(code)
        assert '"a#b"' in result, f"string with # was mangled:\n{result!r}"
        assert "#real=a,b" in result, f"real comment mangled:\n{result!r}"
        assert "#real = a, b" not in result

    def test_code_before_comment_still_normalised(self, formatter: Formatter) -> None:
        """``$ x=1+2  #ok`` — code part normalised, comment preserved."""
        code = "$ x=1+2  #ok\n"
        result = formatter.format_code(code)
        assert "$ x = 1 + 2" in result, f"code not normalised:\n{result!r}"
        assert "#ok" in result

    def test_idempotent_with_comments(self, formatter: Formatter) -> None:
        for code in (
            "$ x = 1  #a=b,c\n",
            "$ f(a,b)  #g(x,y)\n",
            "$ x=1+2  #ok\n",
        ):
            once = formatter.format_code(code)
            twice = formatter.format_code(once)
            assert (
                once == twice
            ), f"NOT idempotent for {code!r}:\n--- once ---\n{once}\n--- twice ---\n{twice}"


# =============================================================================
# Combined idempotency: all three fixes together
# =============================================================================


def test_combined_idempotency(formatter: Formatter) -> None:
    """A realistic snippet exercising all three fixes must be idempotent."""
    code = '    "# senpy: format off"\n' "$ x=-5\n" "$ y=1+2  #note a=b\n" "$ z=+flag\n"
    once = formatter.format_code(code)
    twice = formatter.format_code(once)
    assert once == twice, f"NOT idempotent:\n--- once ---\n{once}\n--- twice ---\n{twice}"
    # And the specific fixes are visible in the output:
    assert "$ x = -5" in once
    assert "$ y = 1 + 2" in once
    assert "#note a=b" in once  # comment preserved
    assert "$ z = +flag" in once
