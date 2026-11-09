"""TDD tests for HTML report XSS escaping.

``senpy/formats/html_report.generate_html_report`` already escapes
``diag.message``, ``diag.line_content`` and ``diag.file_path`` via
``html.escape`` — but interpolates ``diag.code`` and ``diag.severity``
into the rendered card WITHOUT escaping. Both fields originate from
the rule's metadata, and plugin rules expose arbitrary strings to
the host (``@register_rule("ANY STRING")`` + ``RuleMeta(severity=...)``).

A malicious or buggy plugin with ``code = 'RPY001"><img src=x
onerror=alert(document.cookie)>'`` produces a standalone HTML report
that executes the payload when the user opens it in a browser — XSS
in a file that the linter itself generated.

After the fix: ``diag.code`` and ``diag.severity`` are passed through
``html.escape`` everywhere they enter the card template, the same way
``diag.message`` already is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from senpy.core.models import Diagnostic
from senpy.formats.html_report import generate_html_report


def _make_diag(**overrides) -> Diagnostic:
    defaults = {
        "file_path": "test.rpy",
        "line_number": 5,
        "line_content": "x = 1",
        "code": "RPY101",
        "message": "test message",
        "severity": "ERROR",
    }
    defaults.update(overrides)
    return Diagnostic(**defaults)


def _generate(tmp_path: Path, diags: list[Diagnostic]) -> str:
    """Run generate_html_report on a fixed set of diagnostics and return the HTML."""
    out = tmp_path / "report.html"
    generate_html_report(
        diagnostics=diags,
        graph_mermaid="graph TD\n  A[Start]",
        file_count=1,
        total_lines=10,
        elapsed=0.0,
        out_path=str(out),
    )
    return out.read_text(encoding="utf-8")


class TestHtmlReportXssEscaping:
    """``diag.code`` and ``diag.severity`` must be HTML-escaped in the report."""

    def test_diag_code_with_html_tag_is_escaped(self, tmp_path: Path):
        """A rule code containing ``<img onerror=...>`` must NOT appear verbatim.

        Before the fix, ``{diag.code}`` was interpolated raw into the card
        template — a plugin rule with a malicious code string executed the
        payload when the user opened the HTML report in a browser.
        """
        malicious_code = 'RPY001"><img src=x onerror=alert(document.cookie)>'
        html_out = _generate(tmp_path, [_make_diag(code=malicious_code, severity="ERROR")])

        # The raw <img onerror> tag must NOT be in the output.
        assert "<img src=x onerror=" not in html_out, (
            "diag.code with an HTML payload was interpolated raw — XSS. "
            "The <img onerror=...> tag must be escaped to &lt;img onerror=...&gt;."
        )
        # The escaped representation must be present so the code is still visible.
        assert "&lt;img" in html_out, (
            "diag.code's < must be escaped to &lt; — the original rule code "
            "should still be readable in the report after escaping."
        )

    def test_diag_code_with_script_tag_is_escaped(self, tmp_path: Path):
        """A rule code containing ``<script>`` must NOT appear verbatim.

        ``<script>`` in an attribute or text node would execute in the
        browser if CSP allows it (the HTML report CSP includes
        ``script-src 'self' 'unsafe-inline'``, so this is a real vector).
        """
        malicious_code = 'RPY001"><script>alert(1)</script>'
        html_out = _generate(tmp_path, [_make_diag(code=malicious_code, severity="ERROR")])

        assert (
            "<script>alert(1)</script>" not in html_out
        ), "diag.code with a <script> tag was interpolated raw — XSS."
        assert "&lt;script&gt;" in html_out

    def test_diag_severity_with_html_tag_is_escaped(self, tmp_path: Path):
        """A rule severity containing HTML must NOT appear verbatim.

        ``diag.severity`` is interpolated in three places per card: the
        ``class`` attribute, the CSS variable lookup, and the visible
        label. A malicious severity string injects into all three.
        """
        malicious_severity = 'ERROR"><script>alert(1)</script>'
        html_out = _generate(
            tmp_path,
            [_make_diag(code="RPY101", severity=malicious_severity)],
        )

        assert (
            "<script>alert(1)</script>" not in html_out
        ), "diag.severity with a <script> tag was interpolated raw — XSS."

    def test_normal_diag_code_and_severity_render_correctly(self, tmp_path: Path):
        """Regression guard: legitimate code/severity must round-trip cleanly.

        A built-in rule code ``RPY101`` and severity ``ERROR`` must appear
        in the output unchanged after escaping — the fix must not break
        the normal case.
        """
        html_out = _generate(
            tmp_path,
            [_make_diag(code="RPY101", message="undeclared variable", severity="ERROR")],
        )

        # The literal code and severity must be present.
        assert "RPY101" in html_out
        assert "ERROR" in html_out
        # The diagnostic message must still be escaped-and-present.
        assert "undeclared variable" in html_out

    def test_diag_code_with_quotes_does_not_break_attribute(self, tmp_path: Path):
        """A rule code containing ``"`` must not break out of the HTML attribute.

        The card renders ``class="diag-card {severity}"`` and
        ``style="color: var(--{severity})"`` — a code/severity with a
        double quote could close the attribute early and inject markup.
        """
        malicious_code = 'RPY001" onload="alert(1)'
        html_out = _generate(tmp_path, [_make_diag(code=malicious_code, severity="ERROR")])

        # The raw ``" onload=`` sequence must NOT be in the output.
        assert '" onload=' not in html_out, (
            "diag.code with a double quote broke out of an HTML attribute — "
            "the quote must be escaped to &quot;."
        )

    def test_diag_severity_in_css_variable_is_escaped(self, tmp_path: Path):
        """``diag.severity`` flows into ``var(--{severity})`` for the colour.

        The CSS variable name must be a valid CSS identifier — only
        ``[A-Za-z0-9_-]``. A severity containing ``)`` could close the
        ``var(...)`` expression early and inject arbitrary CSS rules
        (e.g. ``background: url(javascript:...)`` on older browsers, or
        ``position:fixed`` overlays). The fix reduces the severity to a
        safe CSS identifier token before interpolation.
        """
        malicious_severity = "ERROR); background:url(javascript:alert(1)"
        html_out = _generate(
            tmp_path,
            [_make_diag(code="RPY101", severity=malicious_severity)],
        )

        import re

        # Find every ``var(--TOKEN)`` occurrence in the output. The TOKEN
        # inside must be a valid CSS identifier — anything else means the
        # severity was interpolated raw and an attacker can close the
        # ``var(...)`` early and inject CSS.
        css_var_matches = re.findall(r"var\(--([^)]*)\)", html_out)
        assert css_var_matches, "No var(--...) found in output — the test setup is wrong."
        for token in css_var_matches:
            assert re.fullmatch(r"[A-Za-z0-9_-]*", token), (
                f"CSS variable name var(--{token!r}) contains unsafe characters "
                "(only [A-Za-z0-9_-] are valid CSS identifiers). "
                "diag.severity was not reduced to a safe CSS identifier, "
                "allowing the ``)`` in the payload to close the var(...) "
                "and inject arbitrary CSS."
            )
