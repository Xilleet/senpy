"""Tests for `senpy/formats/rdjson.py` — Reviewdog RDJSON output.

RDJSON (Reviewdog Diagnostic Format JSON) is a newline-delimited JSON
format consumed by Reviewdog and several CI tools (e.g. GitHub PR
annotations via reviewdog/action-reviewdog). One diagnostic = one
JSON object on its own line (NDJSON).

Schema reference:
    https://github.com/reviewdog/reviewdog/blob/master/proto/rdf/jsonschema/Diagnostic.json

Key fields:
    source.name, source.url
    severity         (one of "ERROR", "WARNING", "INFO" — Reviewdog
                      accepts these strings directly)
    message
    code.value, code.url
    location.path    (repo-relative, forward slashes)
    location.range.start.line   (1-based)
    location.range.start.column (1-based, optional)
    location.range.end.line     (optional)
    location.range.end.column   (optional)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from senpy.core.models import Diagnostic
from senpy.formats.rdjson import generate_rdjson


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
# Structure / single diagnostic
# ---------------------------------------------------------------------------


def test_rdjson_empty_diagnostics_returns_empty_string():
    """No diagnostics → empty output (no trailing newline, no JSON)."""
    assert generate_rdjson([], "/repo") == ""


def test_rdjson_single_diagnostic_is_one_ndjson_line():
    """One diagnostic = one JSON object on its own line. Trailing newline required."""
    out = generate_rdjson([_diag()], "/repo")
    assert out.endswith("\n")
    lines = out.splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["source"]["name"] == "Senpy"
    assert obj["source"]["url"].startswith("https://github.com/Xilleet/senpy")


def test_rdjson_severity_passed_through_unchanged():
    """Reviewdog natively accepts ERROR/WARNING/INFO — no mapping needed.

    HINT is not in the Reviewdog severity list; we map it to INFO so
    the output stays valid against the schema.
    """
    out = generate_rdjson(
        [
            _diag(severity="ERROR"),
            _diag(severity="WARNING"),
            _diag(severity="HINT"),
            _diag(severity="INFO"),
        ],
        "/repo",
    )
    sev = [json.loads(line)["severity"] for line in out.splitlines()]
    assert sev == ["ERROR", "WARNING", "INFO", "INFO"]


def test_rdjson_location_uses_repo_relative_path_with_forward_slashes():
    """Path is repo-relative and uses forward slashes (even on Windows)."""
    diag = _diag(file="/repo/game/sub/script.rpy")
    out = generate_rdjson([diag], "/repo")
    obj = json.loads(out.splitlines()[0])
    assert obj["location"]["path"] == "game/sub/script.rpy"


def test_rdjson_line_and_column_are_1_based():
    """Diagnostic.line_number is 1-based already; col is 0-based → +1."""
    diag = _diag(line=7, col=4, end_col=12)
    out = generate_rdjson([diag], "/repo")
    obj = json.loads(out.splitlines()[0])
    rng = obj["location"]["range"]
    assert rng["start"]["line"] == 7
    assert rng["start"]["column"] == 5  # 0-based 4 → 1-based 5
    assert rng["end"]["line"] == 7
    assert rng["end"]["column"] == 13  # 0-based 12 → 1-based 13


def test_rdjson_code_field_has_value_and_url():
    """Each diagnostic carries a `code` block with rule id + RULES.md URL."""
    out = generate_rdjson([_diag(code="RPY104")], "/repo")
    obj = json.loads(out.splitlines()[0])
    assert obj["code"]["value"] == "RPY104"
    assert obj["code"]["url"].endswith("RULES.md#rpy104")


def test_rdjson_message_preserved_with_unicode():
    """Messages with non-ASCII characters survive (ensure_ascii=False)."""
    diag = _diag(message="Неэкранированные кавычки «» в реплике.")
    out = generate_rdjson([diag], "/repo")
    obj = json.loads(out.splitlines()[0])
    assert obj["message"] == "Неэкранированные кавычки «» в реплике."


def test_rdjson_message_with_newlines_is_escaped_by_json_dumps():
    """A newline inside a message must not break NDJSON — json.dumps handles it."""
    diag = _diag(message="Line one\nLine two")
    out = generate_rdjson([diag], "/repo")
    lines = out.splitlines()
    assert len(lines) == 1, "newline in message must be escaped, not literal"
    obj = json.loads(lines[0])
    assert obj["message"] == "Line one\nLine two"


# ---------------------------------------------------------------------------
# Multiple diagnostics
# ---------------------------------------------------------------------------


def test_rdjson_two_diagnostics_produce_two_ndjson_lines():
    out = generate_rdjson([_diag(line=7), _diag(line=42)], "/repo")
    lines = out.splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["location"]["range"]["start"]["line"] == 7
    assert json.loads(lines[1])["location"]["range"]["start"]["line"] == 42


def test_rdjson_path_outside_repo_falls_back_to_absolute():
    """If relpath fails (different drive on Windows) or path is outside repo,
    fall back to the raw file_path rather than crash."""
    diag = _diag(file="/other_drive/elsewhere.rpy")
    out = generate_rdjson([diag], "/repo")
    obj = json.loads(out.splitlines()[0])
    # We don't assert the exact form — just that the path is present
    # and non-empty. On Linux relpath succeeds and gives "../other_drive/...";
    # on Windows it would raise ValueError and we fall back to the raw path.
    assert obj["location"]["path"]


# ---------------------------------------------------------------------------
# Range edge cases
# ---------------------------------------------------------------------------


def test_rdjson_zero_col_becomes_1_based_one():
    """A diagnostic with col=0 (unset) should still produce a valid 1-based column."""
    diag = _diag(col=0, end_col=0)
    out = generate_rdjson([diag], "/repo")
    obj = json.loads(out.splitlines()[0])
    rng = obj["location"]["range"]
    assert rng["start"]["column"] == 1
    assert rng["end"]["column"] == 1


def test_rdjson_none_severity_defaults_to_warning():
    """A diagnostic with severity=None must not crash; defaults to WARNING."""
    diag = _diag(severity=None)
    out = generate_rdjson([diag], "/repo")
    obj = json.loads(out.splitlines()[0])
    assert obj["severity"] == "WARNING"


# ---------------------------------------------------------------------------
# Rule metadata lookup
# ---------------------------------------------------------------------------


def test_rdjson_unknown_rule_code_still_emits_with_code_value():
    """A diagnostic whose code is not in RULES_DATABASE still gets a code.value.
    The code.url field is omitted (we don't know where to link)."""
    diag = _diag(code="RPY999")
    out = generate_rdjson([diag], "/repo")
    obj = json.loads(out.splitlines()[0])
    assert obj["code"]["value"] == "RPY999"
    assert "url" not in obj["code"] or obj["code"].get("url") is None
