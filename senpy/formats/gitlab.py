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
import logging
import os
from typing import Any

from senpy.core.models import Diagnostic

_logger = logging.getLogger("senpy.formats.gitlab")

# Senpy severity → GitLab severity.
# GitLab's full list is: blocker, critical, major, minor, info.
# Senpy's own diagnostics only emit ERROR/WARNING/HINT/INFO, but plugins
# and user-supplied severities may use GitLab's full vocabulary
# (blocker/critical) or any case variant. We recognize the full GitLab
# set case-insensitively so a plugin emitting ``severity="critical"``
# (Python logging convention) is not silently downgraded to ``minor``.
_SEVERITY_MAP: dict[str, str] = {
    "ERROR": "major",
    "WARNING": "minor",
    "HINT": "info",
    "INFO": "info",
    # GitLab-only levels: surfaced when a plugin or external source emits
    # them directly (Senpy itself never produces these). Without these
    # entries, ``BLOCKER``/``CRITICAL`` would fall through to the
    # ``minor`` default — a security/availability blocker shown as the
    # lowest priority in GitLab MR review.
    "BLOCKER": "blocker",
    "CRITICAL": "critical",
    "MAJOR": "major",
    "MINOR": "minor",
}

# Code-specific severity overrides. RPY105 mutates a ``define``
# constant — this breaks rollback/save compatibility, so by consequence
# it is closer to GitLab's ``critical`` (security/availability) than to
# the default ``major`` for a regular ERROR. RPY106 imports
# non-deterministic RNG, which also breaks rollback. Without these
# overrides the findings silently degrade to ``major`` in GitLab.
_CRITICAL_RULE_CODES: frozenset[str] = frozenset({"RPY105", "RPY106"})


def _map_severity(diag: Diagnostic) -> str:
    """Map a Senpy Diagnostic to a GitLab severity string.

    Lookup order:
      1. Code-specific override (RPY105/RPY106 → ``critical``).
      2. Case-insensitive lookup in ``_SEVERITY_MAP``.
      3. ``None`` → ``minor`` (a diagnostic that reached the renderer
         before severity was applied — surface it at the lowest
         non-info level so it still appears in GitLab MR review).
      4. Unknown severity → ``minor`` with a WARNING log, so the user
         sees the degradation instead of it being silent.
    """
    if diag.code in _CRITICAL_RULE_CODES:
        return "critical"
    sev = diag.severity
    if sev is None:
        return "minor"
    # Case-insensitive: plugins often emit lowercase (Python logging
    # convention: "error"/"warning"), GitLab docs use lowercase too.
    upper = sev.upper()
    if upper in _SEVERITY_MAP:
        return _SEVERITY_MAP[upper]
    _logger.warning(
        "Unknown severity %r on %s — falling back to 'minor' in GitLab "
        "report. Expected one of ERROR/WARNING/HINT/INFO/BLOCKER/"
        "CRITICAL/MAJOR/MINOR (case-insensitive).",
        sev,
        diag.code,
    )
    return "minor"


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
    # ``usedforsecurity=False`` is required for non-cryptographic hashing on
    # FIPS-enabled systems (RHEL/Fedora, corporate images). Without it,
    # ``hashlib.md5()`` raises ``ValueError: [digital envelope routines]
    # unsupported`` and the entire GitLab renderer crashes. Available since
    # Python 3.9+ (Senpy requires 3.11+).
    return hashlib.md5(payload.encode("utf-8"), usedforsecurity=False).hexdigest()


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
                "severity": _map_severity(diag),
                "location": {
                    "path": rel_path,
                    "lines": {"begin": max(1, diag.line_number)},
                },
            }
        )

    # ``sort_keys=True`` makes the output deterministic across runs (the
    # docstring above promises this). Without it, dict insertion order
    # (which is stable in Python 3.7+ but depends on the literal above)
    # would be the only guarantee — fragile if someone reorders the
    # literal. Matches ``inspect_dispatch.py:206`` and ``rule_dispatch.py``
    # which both use ``sort_keys=True`` for CI snapshot testing.
    return json.dumps(findings, ensure_ascii=False, sort_keys=True)
