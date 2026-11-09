"""Tests for `senpy/formats/gitlab.py` — GitLab Code Quality JSON output.

GitLab CI consumes a Code Quality report artifact (a JSON array of
objects) to surface findings directly in merge requests. The schema
is documented at:

    https://docs.gitlab.com/ee/ci/testing/code_quality.html#implement-a-custom-tool

Key fields per finding:
    description     (str)  — human-readable message
    check_name      (str)  — rule identifier (e.g. "RPY104")
    fingerprint     (str)  — stable hash for deduplication across runs
    severity         (str)  — one of "blocker", "critical", "major",
                              "minor", "info" (Senpy maps into
                              {major, minor, info})
    location.path    (str)  — repo-relative path
    location.lines.begin (int) — 1-based line number
"""

from __future__ import annotations

import hashlib
import json
import re

import pytest

from senpy.core.models import Diagnostic
from senpy.formats.gitlab import generate_gitlab_json


def _diag(
    code: str = "RPY104",
    *,
    file: str = "game/script.rpy",
    line: int = 7,
    col: int = 4,
    end_col: int = 12,
    severity: str | None = "WARNING",
    message: str = "Dynamic assignment without top-level 'default'.",
) -> Diagnostic:
    return Diagnostic(
        file_path=file,
        line_number=line,
        line_content="    $ x = 1",
        code=code,
        message=message,
        severity=severity,
        col=col,
        end_col=end_col,
    )


# ---------------------------------------------------------------------------
# Structure / top-level
# ---------------------------------------------------------------------------


def test_gitlab_empty_diagnostics_returns_empty_json_array():
    """No diagnostics → '[]' (GitLab accepts an empty array as a valid report)."""
    out = generate_gitlab_json([], "/repo")
    assert out == "[]"
    assert json.loads(out) == []


def test_gitlab_single_diagnostic_is_a_json_array_with_one_object():
    """The report is a JSON array (not NDJSON) — GitLab requires this."""
    out = generate_gitlab_json([_diag()], "/repo")
    data = json.loads(out)
    assert isinstance(data, list)
    assert len(data) == 1


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------


def test_gitlab_check_name_is_the_rule_code():
    out = generate_gitlab_json([_diag(code="RPY107")], "/repo")
    obj = json.loads(out)[0]
    assert obj["check_name"] == "RPY107"


def test_gitlab_description_is_the_diagnostic_message():
    msg = "Deprecated Ren'Py API 'LiveComposite'. Use 'Composite' instead."
    out = generate_gitlab_json([_diag(message=msg)], "/repo")
    obj = json.loads(out)[0]
    assert obj["description"] == msg


def test_gitlab_severity_mapping():
    """Senpy severity → GitLab severity.

    ERROR   → major
    WARNING → minor
    HINT    → info
    INFO    → info
    """
    cases = [
        ("ERROR", "major"),
        ("WARNING", "minor"),
        ("HINT", "info"),
        ("INFO", "info"),
    ]
    diags = [_diag(severity=sev) for sev, _ in cases]
    out = generate_gitlab_json(diags, "/repo")
    data = json.loads(out)
    actual = [d["severity"] for d in data]
    assert actual == [expected for _, expected in cases]


def test_gitlab_none_severity_defaults_to_minor():
    diag = _diag(severity=None)
    out = generate_gitlab_json([diag], "/repo")
    obj = json.loads(out)[0]
    assert obj["severity"] == "minor"


def test_gitlab_location_path_is_repo_relative_with_forward_slashes():
    diag = _diag(file="/repo/game/sub/script.rpy")
    out = generate_gitlab_json([diag], "/repo")
    obj = json.loads(out)[0]
    assert obj["location"]["path"] == "game/sub/script.rpy"


def test_gitlab_location_lines_begin_is_1_based_line_number():
    diag = _diag(line=42)
    out = generate_gitlab_json([diag], "/repo")
    obj = json.loads(out)[0]
    assert obj["location"]["lines"]["begin"] == 42


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


def test_gitlab_fingerprint_is_present_and_hex():
    """Fingerprint is required by GitLab for deduplication. Must be hex md5/sha."""
    out = generate_gitlab_json([_diag()], "/repo")
    obj = json.loads(out)[0]
    fp = obj["fingerprint"]
    assert isinstance(fp, str)
    assert re.fullmatch(r"[0-9a-f]{32,64}", fp), f"not a hex hash: {fp!r}"


def test_gitlab_fingerprint_is_stable_across_runs():
    """Same diagnostic → same fingerprint (deterministic)."""
    diag = _diag()
    out1 = generate_gitlab_json([diag], "/repo")
    out2 = generate_gitlab_json([diag], "/repo")
    assert json.loads(out1)[0]["fingerprint"] == json.loads(out2)[0]["fingerprint"]


def test_gitlab_fingerprint_differs_for_different_messages():
    """Different message → different fingerprint (avoid dedup collisions)."""
    d1 = _diag(message="Message A")
    d2 = _diag(message="Message B")
    out = generate_gitlab_json([d1, d2], "/repo")
    data = json.loads(out)
    assert data[0]["fingerprint"] != data[1]["fingerprint"]


def test_gitlab_fingerprint_differs_for_different_lines():
    """Same code+message, different line → different fingerprint."""
    d1 = _diag(line=10)
    d2 = _diag(line=20)
    out = generate_gitlab_json([d1, d2], "/repo")
    data = json.loads(out)
    assert data[0]["fingerprint"] != data[1]["fingerprint"]


def test_gitlab_fingerprint_uses_md5_of_code_path_line_message():
    """Document the fingerprint algorithm: md5(f"{code}|{path}|{line}|{msg}").

    Pinning the algorithm in a test makes accidental changes visible
    (a fingerprint change would re-open every GitLab finding).
    """
    diag = _diag(code="RPY104", file="/repo/game/script.rpy", line=7, message="msg")
    out = generate_gitlab_json([diag], "/repo")
    fp = json.loads(out)[0]["fingerprint"]
    expected = hashlib.md5(b"RPY104|game/script.rpy|7|msg").hexdigest()
    assert fp == expected


# ---------------------------------------------------------------------------
# Multiple diagnostics
# ---------------------------------------------------------------------------


def test_gitlab_two_diagnostics_produce_two_array_entries():
    out = generate_gitlab_json([_diag(line=7), _diag(line=42)], "/repo")
    data = json.loads(out)
    assert len(data) == 2
    assert data[0]["location"]["lines"]["begin"] == 7
    assert data[1]["location"]["lines"]["begin"] == 42


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_gitlab_message_with_quotes_is_properly_escaped():
    """JSON serialization must escape double quotes inside messages."""
    diag = _diag(message='She said "hi" and left.')
    out = generate_gitlab_json([diag], "/repo")
    # Must be valid JSON
    obj = json.loads(out)[0]
    assert obj["description"] == 'She said "hi" and left.'


def test_gitlab_unicode_message_preserved():
    diag = _diag(message="Неэкранированные кавычки «» в реплике.")
    out = generate_gitlab_json([diag], "/repo")
    obj = json.loads(out)[0]
    assert obj["description"] == "Неэкранированные кавычки «» в реплике."


def test_gitlab_path_outside_repo_falls_back_to_raw():
    diag = _diag(file="/other_drive/elsewhere.rpy")
    out = generate_gitlab_json([diag], "/repo")
    obj = json.loads(out)[0]
    assert obj["location"]["path"]
