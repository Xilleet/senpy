"""Reviewdog RDJSON output format.

RDJSON (Reviewdog Diagnostic Format JSON) is a newline-delimited JSON
format consumed by Reviewdog and several CI tools (e.g. GitHub PR
annotations via reviewdog/action-reviewdog). One diagnostic = one
JSON object on its own line (NDJSON).

Schema reference:
    https://github.com/reviewdog/reviewdog/blob/master/proto/rdf/jsonschema/Diagnostic.json

Field mapping (Senpy → RDJSON):

    Diagnostic.code         → code.value
    RULES.md anchor         → code.url
    Diagnostic.severity     → severity (ERROR/WARNING/INFO; HINT→INFO)
    Diagnostic.message      → message
    Diagnostic.file_path    → location.path (repo-relative, forward slashes)
    Diagnostic.line_number  → location.range.start.line   (1-based)
    Diagnostic.col          → location.range.start.column (0-based → 1-based)
    Diagnostic.end_col      → location.range.end.column   (0-based → 1-based)

The function returns a string. Empty diagnostics → empty string (no
trailing newline). Otherwise each diagnostic is followed by ``\n``.
"""

from __future__ import annotations

import json
import os
from typing import Any

from senpy.core.models import Diagnostic
from senpy.rules.rules_info import RULES_DATABASE

_SOURCE_NAME = "Senpy"
_SOURCE_URL = "https://github.com/Xilleet/senpy"
_RULES_URL_BASE = "https://github.com/Xilleet/senpy/blob/main/RULES.md"

# Reviewdog accepts ERROR/WARNING/INFO natively. Senpy's HINT has no
# direct equivalent — we promote it to INFO (the closest match in
# severity ordering).
_SEVERITY_MAP: dict[str, str] = {
    "ERROR": "ERROR",
    "WARNING": "WARNING",
    "HINT": "INFO",
    "INFO": "INFO",
}


def _relpath(file_path: str, project_path: str) -> str:
    """Repo-relative path with forward slashes.

    On Windows, ``os.path.relpath`` raises ValueError when the paths
    are on different drives (e.g. C:\\repo vs D:\\file). In that case
    we fall back to the raw file_path.
    """
    try:
        rel = os.path.relpath(file_path, project_path)
    except ValueError:
        rel = file_path
    return rel.replace("\\", "/")


def _build_code_block(code: str) -> dict[str, Any]:
    """Build the `code` sub-object. URL is omitted for unknown rule codes."""
    block: dict[str, Any] = {"value": code}
    # Only attach a URL when the rule is in our database — otherwise
    # we'd be linking to a non-existent anchor.
    if code in RULES_DATABASE:
        block["url"] = f"{_RULES_URL_BASE}#{code.lower()}"
    return block


def _build_location(diag: Diagnostic, project_path: str) -> dict[str, Any]:
    """Build the `location` sub-object with 1-based line and column numbers."""
    start_line = max(1, diag.line_number)
    # Diagnostic.col is 0-based; RDJSON columns are 1-based. A 0 (unset)
    # becomes 1.
    start_col = max(1, diag.col + 1)
    end_col = max(1, diag.end_col + 1) if diag.end_col > diag.col else start_col
    return {
        "path": _relpath(diag.file_path, project_path),
        "range": {
            "start": {"line": start_line, "column": start_col},
            "end": {"line": start_line, "column": end_col},
        },
    }


def generate_rdjson(diagnostics: list[Diagnostic], project_path: str) -> str:
    """Generate Reviewdog RDJSON (NDJSON) from a list of Senpy diagnostics.

    Returns a string. Empty input → empty string. Otherwise each
    diagnostic is serialized as one JSON object followed by ``\\n``.

    The output is deterministic: given the same input list, the same
    string is produced (no dict iteration order surprises, no
    non-deterministic whitespace). Suitable for snapshot tests.
    """
    if not diagnostics:
        return ""

    lines: list[str] = []
    for diag in diagnostics:
        record: dict[str, Any] = {
            "source": {"name": _SOURCE_NAME, "url": _SOURCE_URL},
            "severity": _SEVERITY_MAP.get(diag.severity or "WARNING", "WARNING"),
            "message": diag.message,
            "code": _build_code_block(diag.code),
            "location": _build_location(diag, project_path),
        }
        # ensure_ascii=False so non-ASCII messages survive untouched
        # (matches SARIF behaviour in senpy/formats/sarif.py).
        lines.append(json.dumps(record, ensure_ascii=False))

    return "\n".join(lines) + "\n"
