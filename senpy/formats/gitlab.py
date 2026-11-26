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

Optional fields (emitted when available):

    location.positions.begin.line   (int) — 1-based line (mirrors lines.begin)
    location.positions.begin.column (int) — 1-based column (when diag.col set)

Field mapping (Senpy → GitLab):

    Diagnostic.code         → check_name
    Diagnostic.message      → description
    Diagnostic.severity     → severity (ERROR→major, WARNING→minor,
                              HINT/INFO→info)
    Diagnostic.file_path    → location.path (repo-relative)
    Diagnostic.line_number  → location.lines.begin (1-based)
    Diagnostic.col          → location.positions.begin.column (1-based, when > 0)
    md5(code|path|msg|ord)  → fingerprint

Fingerprint algorithm:

    payload = f"{code}|{rel_path}|{message}|{ordinal}"

where ``ordinal`` is the 0-based index of this finding within its
``(code, rel_path, message)`` group. Line number is INTENTIONALLY
excluded — inserting 5 lines at the top of a file shifts every
finding's line_number by 5, which would produce new fingerprints and
cause GitLab to close all old MR discussions as "fixed" and open new
ones for the same findings. The ordinal distinguishes two genuinely-
distinct findings with the same (code, path, message) — without it,
GitLab would dedup them and hide one from MR review.

The fingerprint algorithm is pinned by tests/formats/test_gitlab.py
and tests/formats/test_fix_57_58_gitlab.py — change it and every
GitLab finding would re-open.
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


def _fingerprint(diag: Diagnostic, rel_path: str, ordinal: int) -> str:
    """Stable hash for deduplication across runs.

    The fingerprint must be stable across runs (same input → same
    output) and distinct for logically distinct findings.

    Payload: ``f"{code}|{rel_path}|{message}|{ordinal}"``

    Why ``line_number`` is NOT in the payload (FIX-57):

      GitLab deduplicates findings across MR commits by fingerprint.
      Including ``line_number`` means inserting N lines at the top of a
      file shifts every finding's line_number by N → every finding gets
      a new fingerprint → GitLab closes all old MR discussions as
      "fixed" and opens new ones for the same findings. The MR history
      becomes noise: "you fixed everything and re-broke it in the same
      commit."

    Why ``ordinal`` IS in the payload:

      Without it, two genuinely-distinct findings with the same
      (code, path, message) — e.g. RPY104 emitted on two different
      lines with the same message — would collide on fingerprint and
      GitLab would dedup them, hiding one from MR review.

      The ordinal is the 0-based index of this finding within its
      (code, rel_path, message) group, computed by ``generate_gitlab_json``
      as it walks the input list. As long as the analyzer emits
      diagnostics in a deterministic order (by file, then by line),
      the ordinals are stable across runs.

    MD5 is used because GitLab's example implementations use it and
    it is sufficient for non-cryptographic deduplication. A future
    migration to BLAKE2b/3 is tracked separately in the worklog.
    """
    payload = f"{diag.code}|{rel_path}|{diag.message}|{ordinal}"
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

    # Group by (code, rel_path, message) and assign ordinals so two
    # genuinely-distinct findings with the same triple get different
    # fingerprints (without the ordinal, GitLab would dedup them).
    # See _fingerprint docstring for the full rationale.
    group_ordinals: dict[tuple[str, str, str], int] = {}

    findings: list[dict[str, Any]] = []
    for diag in diagnostics:
        rel_path = _relpath(diag.file_path, project_path)
        key = (diag.code, rel_path, diag.message)
        ordinal = group_ordinals.get(key, 0)
        group_ordinals[key] = ordinal + 1

        location: dict[str, Any] = {
            "path": rel_path,
            "lines": {"begin": max(1, diag.line_number)},
        }
        # GitLab Code Quality schema supports ``positions.begin``
        # (object with line + column) alongside the simpler ``lines.begin``
        # (integer). We emit ``positions.begin`` only when ``diag.col`` is
        # set (>0) so the MR widget can point at the offending token and
        # two findings on the same line are visually distinguishable.
        # ``lines.begin`` is always present for backward compat with
        # consumers that only read the simpler form.
        # ``diag.col`` is 0-based; GitLab columns are 1-based.
        if diag.col > 0:
            location["positions"] = {
                "begin": {
                    "line": max(1, diag.line_number),
                    "column": diag.col + 1,
                }
            }

        findings.append(
            {
                "description": diag.message,
                "check_name": diag.code,
                "fingerprint": _fingerprint(diag, rel_path, ordinal),
                "severity": _map_severity(diag),
                "location": location,
            }
        )

    # ``sort_keys=True`` makes the output deterministic across runs (the
    # docstring above promises this). Without it, dict insertion order
    # (which is stable in Python 3.7+ but depends on the literal above)
    # would be the only guarantee — fragile if someone reorders the
    # literal. Matches ``inspect_dispatch.py:206`` and ``rule_dispatch.py``
    # which both use ``sort_keys=True`` for CI snapshot testing.
    return json.dumps(findings, ensure_ascii=False, sort_keys=True)
