"""RED tests for FIX-57 + FIX-58 — GitLab Code Quality fingerprint & column.

FIX-57: ``_fingerprint()`` includes ``line_number`` in the payload
(``code|path|line|message``). GitLab deduplicates findings across MR
commits by fingerprint. Inserting 5 lines at the top of a file shifts
every finding's line_number by 5 → every finding gets a new fingerprint
→ GitLab closes all old MR discussions as "fixed" and opens new ones
for the same findings. The MR history lies: "everything was fixed and
re-broken in the same commit."

The fix removes ``line_number`` from the payload and adds an ordinal
within each ``(code, path, message)`` group so two genuinely-distinct
findings (e.g., same RPY104 message on two different lines) still get
different fingerprints.

FIX-58: GitLab Code Quality schema supports ``location.positions.begin.column``
(1-based) but senpy's GitLab output only emits ``location.lines.begin``
(line number). Consequence: MR widget can't point at the offending
token, and two findings on the same line are visually indistinguishable.
The fix adds ``positions.begin`` (with line + column) when ``diag.col``
is set, leaving ``lines.begin`` for backward compatibility with
consumers that only read the simpler form.

Property-based tests verify the INVARIANTS (stable under line shift,
distinct for distinct findings, deterministic for same input) rather
than pinning the exact hash algorithm — so future fingerprint tweaks
don't break tests unless they violate the invariants.
"""

from __future__ import annotations

import hashlib
import json

from senpy.core.models import Diagnostic
from senpy.formats.gitlab import generate_gitlab_json


def _diag(
    *,
    code: str = "RPY104",
    file: str = "/repo/game/script.rpy",
    line: int = 7,
    col: int = 0,
    end_col: int = 0,
    severity: str | None = "WARNING",
    message: str = "Dynamic assignment without top-level 'default'.",
    line_content: str = "    $ x = 1",
) -> Diagnostic:
    return Diagnostic(
        file_path=file,
        line_number=line,
        line_content=line_content,
        code=code,
        message=message,
        severity=severity,
        col=col,
        end_col=end_col,
    )


# =============================================================================
# FIX-57: fingerprint stability under line shift
# =============================================================================


class TestFingerprintStableUnderLineShift:
    """Property: shifting a file by N lines preserves every fingerprint.

    This is the core invariant GitLab MR dedup relies on. If line shift
    changes the fingerprint, GitLab closes old discussions and opens new
    ones — MR history becomes noise.
    """

    def test_single_finding_fingerprint_unchged_when_line_shifts(self):
        """Same finding at line 7 vs line 12 (file shifted +5) → same fingerprint."""
        d_before = _diag(line=7)
        d_after = _diag(line=12)  # 5 lines inserted above
        out_before = generate_gitlab_json([d_before], "/repo")
        out_after = generate_gitlab_json([d_after], "/repo")
        fp_before = json.loads(out_before)[0]["fingerprint"]
        fp_after = json.loads(out_after)[0]["fingerprint"]
        assert fp_before == fp_after, (
            f"fingerprint changed under line shift: {fp_before} → {fp_after}. "
            "GitLab MR dedup would close+reopen every discussion on each commit."
        )

    def test_multiple_findings_fingerprints_preserved_under_uniform_shift(self):
        """Three findings shifted by +10 lines → all three fingerprints preserved."""
        diags_before = [
            _diag(line=10, message="msg A"),
            _diag(line=20, message="msg B"),
            _diag(line=30, message="msg C"),
        ]
        diags_after = [
            _diag(line=20, message="msg A"),
            _diag(line=30, message="msg B"),
            _diag(line=40, message="msg C"),
        ]
        fps_before = [
            d["fingerprint"] for d in json.loads(generate_gitlab_json(diags_before, "/repo"))
        ]
        fps_after = [
            d["fingerprint"] for d in json.loads(generate_gitlab_json(diags_after, "/repo"))
        ]
        assert fps_before == fps_after, (
            f"fingerprint sets differ under uniform line shift:\n"
            f"  before: {fps_before}\n  after:  {fps_after}"
        )

    def test_line_number_alone_in_payload_would_violate_invariant(self):
        """Sanity check: the OLD payload ``code|path|line|msg`` would NOT be stable.

        This test exists to prove the bug is real (not just theoretical)
        and to document why we removed ``line_number`` from the payload.
        """
        # OLD algorithm (deliberately reconstructed here):
        old_fp_line7 = hashlib.md5(b"RPY104|game/script.rpy|7|msg").hexdigest()
        old_fp_line12 = hashlib.md5(b"RPY104|game/script.rpy|12|msg").hexdigest()
        assert old_fp_line7 != old_fp_line12, (
            "OLD algorithm should produce different fingerprints for line 7 vs 12 — "
            "this is the bug FIX-57 fixes."
        )


# =============================================================================
# FIX-57: fingerprint distinguishes genuinely-distinct findings
# =============================================================================


class TestFingerprintDistinguishesDistinctFindings:
    """Property: two distinct findings → two distinct fingerprints.

    Without an ordinal within (code, path, message) groups, two
    RPY104 findings with the same message in the same file would
    collide — GitLab would dedup them, hiding one from MR review.
    """

    def test_two_findings_same_code_path_message_different_lines_get_different_fingerprints(self):
        """Same RPY104 message on line 5 and line 10 → different fingerprints."""
        d1 = _diag(line=5, message="Dynamic assignment without top-level 'default'.")
        d2 = _diag(line=10, message="Dynamic assignment without top-level 'default'.")
        out = generate_gitlab_json([d1, d2], "/repo")
        data = json.loads(out)
        assert data[0]["fingerprint"] != data[1]["fingerprint"], (
            "two distinct findings (same code/path/message, different lines) "
            "must have different fingerprints — otherwise GitLab dedups them."
        )

    def test_different_messages_get_different_fingerprints(self):
        d1 = _diag(message="Message A")
        d2 = _diag(message="Message B")
        out = generate_gitlab_json([d1, d2], "/repo")
        data = json.loads(out)
        assert data[0]["fingerprint"] != data[1]["fingerprint"]

    def test_different_codes_get_different_fingerprints(self):
        d1 = _diag(code="RPY104")
        d2 = _diag(code="RPY105")
        out = generate_gitlab_json([d1, d2], "/repo")
        data = json.loads(out)
        assert data[0]["fingerprint"] != data[1]["fingerprint"]

    def test_different_paths_get_different_fingerprints(self):
        d1 = _diag(file="/repo/game/a.rpy")
        d2 = _diag(file="/repo/game/b.rpy")
        out = generate_gitlab_json([d1, d2], "/repo")
        data = json.loads(out)
        assert data[0]["fingerprint"] != data[1]["fingerprint"]


# =============================================================================
# FIX-57: fingerprint deterministic for same input
# =============================================================================


class TestFingerprintDeterministic:
    """Property: same input → same fingerprint (no randomness, no ordering surprise)."""

    def test_same_diagnostic_produces_same_fingerprint_across_runs(self):
        d = _diag()
        out1 = generate_gitlab_json([d], "/repo")
        out2 = generate_gitlab_json([d], "/repo")
        assert json.loads(out1)[0]["fingerprint"] == json.loads(out2)[0]["fingerprint"]

    def test_same_list_in_any_order_produces_compatible_fingerprints(self):
        """Reordering the input list should not break fingerprint identity
        for a single finding — the (code, path, message) group has only
        one member, so its ordinal is 0 regardless of input order."""
        d1 = _diag(line=5, message="msg A")
        d2 = _diag(line=10, message="msg B")
        out1 = json.loads(generate_gitlab_json([d1, d2], "/repo"))
        out2 = json.loads(generate_gitlab_json([d2, d1], "/repo"))
        # Map by message so order doesn't matter for the comparison.
        fp1 = {d["description"]: d["fingerprint"] for d in out1}
        fp2 = {d["description"]: d["fingerprint"] for d in out2}
        assert fp1 == fp2


# =============================================================================
# FIX-58: GitLab output includes column when diag.col is set
# =============================================================================


class TestGitLabColumnEmission:
    """``location.positions.begin.column`` is emitted when ``diag.col > 0``."""

    def test_col_emitted_when_set(self):
        """diag.col=4 → positions.begin.column=5 (1-based)."""
        diag = _diag(col=4, end_col=12)
        out = generate_gitlab_json([diag], "/repo")
        obj = json.loads(out)[0]
        # ``positions.begin`` MUST be present with both line and column.
        assert (
            "positions" in obj["location"]
        ), f"positions missing from location: {obj['location']!r}"
        begin = obj["location"]["positions"]["begin"]
        assert begin["line"] == 7, f"positions.begin.line wrong: {begin!r}"
        assert (
            begin["column"] == 5
        ), f"positions.begin.column should be 1-based (col=4 → 5), got: {begin!r}"

    def test_col_omitted_when_unset(self):
        """diag.col=0 (unset/whole-line) → no positions block (only lines.begin)."""
        diag = _diag(col=0, end_col=0)
        out = generate_gitlab_json([diag], "/repo")
        obj = json.loads(out)[0]
        # ``lines.begin`` is always present (backward compat).
        assert obj["location"]["lines"]["begin"] == 7
        # ``positions`` should NOT be present — without a real column,
        # emitting ``column: 1`` would be misleading (suggests col=0
        # was a real 1-based column).
        assert (
            "positions" not in obj["location"]
        ), f"positions should be omitted when col=0, but got: {obj['location']!r}"

    def test_lines_begin_preserved_for_backward_compat(self):
        """``lines.begin`` (integer) MUST remain even when ``positions`` is added.

        Existing GitLab consumers (MR widget, code climate aggregators)
        read ``lines.begin``. Replacing it with ``positions`` would
        break them — we add ``positions`` alongside, not instead.
        """
        diag = _diag(col=4, end_col=12)
        out = generate_gitlab_json([diag], "/repo")
        obj = json.loads(out)[0]
        assert "lines" in obj["location"]
        assert obj["location"]["lines"]["begin"] == 7

    def test_two_findings_same_line_distinguishable_by_column(self):
        """Two findings on the same line, different columns → different positions.

        Without ``positions``, the MR widget shows two findings at the
        same line and the user can't tell which token each refers to.
        """
        d1 = _diag(col=4, end_col=8, message="issue with first var")
        d2 = _diag(col=20, end_col=24, message="issue with second var")
        out = generate_gitlab_json([d1, d2], "/repo")
        data = json.loads(out)
        cols = [d["location"]["positions"]["begin"]["column"] for d in data]
        assert cols == [5, 21], f"columns should be 1-based (4→5, 20→21), got: {cols!r}"


# =============================================================================
# FIX-57: ordinal within group — pin the algorithm explicitly
# =============================================================================


class TestFingerprintAlgorithmPinned:
    """Pin the NEW algorithm so accidental changes are visible.

    The new payload is ``code|path|message|ordinal`` where ``ordinal``
    is the 0-based index of this finding within its (code, path, message)
    group. This test documents the algorithm — change it and GitLab MR
    discussions will close+reopen.
    """

    def test_single_finding_fingerprint_is_md5_of_code_path_message_zero(self):
        """md5(f"{code}|{path}|{msg}|0") for the first (and only) finding in a group."""
        diag = _diag(code="RPY104", file="/repo/game/script.rpy", line=7, message="msg")
        out = generate_gitlab_json([diag], "/repo")
        fp = json.loads(out)[0]["fingerprint"]
        expected = hashlib.md5(b"RPY104|game/script.rpy|msg|0").hexdigest()
        assert fp == expected, (
            f"fingerprint algorithm changed!\n"
            f"  expected (md5 of 'RPY104|game/script.rpy|msg|0'): {expected}\n"
            f"  got: {fp}\n"
            f"If you intentionally changed the algorithm, update this test."
        )

    def test_second_finding_in_group_gets_ordinal_1(self):
        """Two findings with same (code, path, message) → ordinals 0 and 1."""
        d1 = _diag(line=5, message="msg")
        d2 = _diag(line=10, message="msg")
        out = generate_gitlab_json([d1, d2], "/repo")
        data = json.loads(out)
        expected_0 = hashlib.md5(b"RPY104|game/script.rpy|msg|0").hexdigest()
        expected_1 = hashlib.md5(b"RPY104|game/script.rpy|msg|1").hexdigest()
        assert data[0]["fingerprint"] == expected_0
        assert data[1]["fingerprint"] == expected_1
