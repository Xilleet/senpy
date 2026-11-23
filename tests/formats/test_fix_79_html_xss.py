"""RED tests for 0.9.4 — security & defense-in-depth.

``formats/html_report.py`` interpolates ``diag.line_number`` raw
into the HTML template without ``html.escape``. A malicious plugin rule
can pass ``Diagnostic(line_number="<script>alert(1)</script>")`` — the
type hint is ``int`` but Python does not enforce it at runtime, so the
string flows through to the browser. Every other user-influenced field
(``message``, ``line_content``, ``code``, ``severity``, ``file_path``)
is escaped — ``line_number`` was the only one missed.

LSP runners and handlers call ``_uri_to_path(uri)``
without passing ``workspace_root``, so the workspace containment check
in ``_uri_to_path`` is bypassed. The fix passes ``_current_workspace_root``
so out-of-workspace URIs (e.g. ``file:///etc/passwd``) are rejected.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from senpy.core.models import Diagnostic

# =============================================================================
# FIX-79: html_report.py line_number XSS
# =============================================================================


class TestHtmlReportLineNumberXss:
    """``diag.line_number`` must be HTML-escaped in the report.

    Before FIX-79: ``{file_name}:{diag.line_number}`` and
    ``{diag.line_number} | {safe_code}`` interpolated ``line_number``
    raw — every other field was escaped, but ``line_number`` was missed.
    A malicious plugin passing ``Diagnostic(line_number="<script>...")``
    achieved XSS.

    After FIX-79: ``line_number`` is coerced to ``str`` and passed
    through ``html.escape``.
    """

    def test_line_number_xss_is_escaped(self, tmp_path: Path) -> None:
        """RED: ``<script>`` tag in ``line_number`` must not appear raw."""
        from senpy.formats.html_report import generate_html_report

        diag = Diagnostic(
            file_path="test.rpy",
            line_number="<script>alert(1)</script>",
            line_content="test code",
            code="RPY001",
            message="test message",
            severity="ERROR",
        )
        out_path = tmp_path / "report.html"
        generate_html_report([diag], "graph code", 1, 10, 0.1, str(out_path))
        html = out_path.read_text(encoding="utf-8")
        # The raw ``<script>alert(1)</script>`` must NOT appear in the HTML.
        assert "<script>alert(1)</script>" not in html, (
            "line_number XSS: raw <script> tag appeared in HTML report — "
            "diag.line_number must be html.escape()'d before interpolation."
        )
        # The escaped form must be present.
        assert "&lt;script&gt;" in html, (
            "line_number should be HTML-escaped to &lt;script&gt; in the "
            "report; got no escaped form."
        )

    def test_normal_line_number_survives(self, tmp_path: Path) -> None:
        """Sanity: a normal int ``line_number`` still appears correctly."""
        from senpy.formats.html_report import generate_html_report

        diag = Diagnostic(
            file_path="test.rpy",
            line_number=42,
            line_content="test code",
            code="RPY001",
            message="test message",
            severity="ERROR",
        )
        out_path = tmp_path / "report.html"
        generate_html_report([diag], "graph code", 1, 10, 0.1, str(out_path))
        html = out_path.read_text(encoding="utf-8")
        assert (
            ":42" in html or "42 |" in html
        ), "Normal line_number 42 must appear in the report. Got HTML missing ':42' or '42 |'."
