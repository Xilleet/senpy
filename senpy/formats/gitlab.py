"""GitLab Code Quality JSON output format.

GitLab CI consumes a Code Quality report artifact (a JSON array of
finding objects) to surface issues directly in merge requests. The
schema is documented at:

    https://docs.gitlab.com/ee/ci/testing/code_quality.html#implement-a-custom-tool

Required fields per finding:

    description     (str)  — human-readable message
    check_name      (str)  — rule identifier (e.g. "RPY104")
    fingerprint     (str)  — stable hash for deduplication across runs
    severity        (str)  — one of "blocker", "critical", "major",
                             "minor", "info"
    location.path   (str)  — repo-relative path with forward slashes
    location.lines.begin (int) — 1-based line number

Field mapping (Senpy → GitLab):

    Diagnostic.code         → check_name
    Diagnostic.message      → description
    Diagnostic.severity     → severity (ERROR→major, WARNING→minor,
                              HINT/INFO→info)
    Diagnostic.file_path    → location.path (repo-relative)
    Diagnostic.line_number  → location.lines.begin (1-based)
    md5(code|path|line|msg) → fingerprint

The fingerprint algorithm is pinned by tests/test_gitlab.py — change
it and every GitLab finding would re-open. Use the helper if you
need to regenerate.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from senpy.core.models import Diagnostic

# Senpy severity → GitLab severity.
# GitLab's full list is: blocker, critical, major, minor, info.
# Senpy has no concept of "blocker" or "critical" — those are reserved
# for security/availability findings in GitLab's model. We map into
# the three levels that make sense for a linter.
_SEVERITY_MAP: dict[str, str] = {
    "ERROR": "major",
    "WARNING": "minor",
    "HINT": "info",
    "INFO": "info",
}


def _relpath(file_path: str, project_path: str) -> str:
    """Repo-relative path with forward slashes.

    On Windows, ``os.path.relpath`` raises ValueError when the paths
    are on different drives. Fall back to the raw file_path in that
    case (matches the rdjson.py behaviour).
    """
    try:
        rel = os.path.relpath(file_path, project_path)
    except ValueError:
        rel = file_path
    return rel.replace("\\", "/")


def _fingerprint(diag: Diagnostic, rel_path: str) -> str:
    """Stable hash for deduplication across runs.

    The fingerprint must be stable across runs (same input → same
    output) and distinct for logically distinct findings. We hash
    ``code|path|line|message`` — this means re-running on the same
    file produces the same fingerprint, but a new line or a changed
    message produces a new one (so GitLab will treat it as a new
    finding, which is the desired behaviour).

    MD5 is used because GitLab's example implementations use it and
    it is sufficient for non-cryptographic deduplication. A future
    migration to BLAKE2b/3 is tracked separately in the worklog.
    """
    payload = f"{diag.code}|{rel_path}|{diag.line_number}|{diag.message}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def generate_gitlab_json(diagnostics: list[Diagnostic], project_path: str) -> str:
    """Generate a GitLab Code Quality JSON report from Senpy diagnostics.

    Returns a JSON string. The top-level structure is an array (not
    NDJSON). Empty input → ``"[]"``.

    The output is deterministic: same input list → same string
    (sorted dict keys, ensure_ascii=False for non-ASCII messages).
    """
    if not diagnostics:
        return "[]"

    findings: list[dict[str, Any]] = []
    for diag in diagnostics:
        rel_path = _relpath(diag.file_path, project_path)
        findings.append(
            {
                "description": diag.message,
                "check_name": diag.code,
                "fingerprint": _fingerprint(diag, rel_path),
                "severity": _SEVERITY_MAP.get(diag.severity or "WARNING", "minor"),
                "location": {
                    "path": rel_path,
                    "lines": {"begin": max(1, diag.line_number)},
                },
            }
        )

    return json.dumps(findings, ensure_ascii=False)
