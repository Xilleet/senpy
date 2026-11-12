"""Auto-generated Ren'Py API documentation — JSON-backed loader.

Source: Ren'Py v8.5.3 RST docs (sphinx/source/) + common/*.rpy.
Generated: 2026-11-01T12:38:50Z

DO NOT EDIT — re-run ``python scripts/fetch_renpy_docs.py``.

Converted from a 4891-line Python
literal dict to a JSON resource loaded at import time. The JSON file
``senpy/domain/data/renpy_api_generated.json`` is the canonical data;
this module is a thin loader that exposes the same three public names
(``RENPY_API_DOCS_GENERATED``, ``RENPY_DOC_VERSION_GENERATED``,
``RENPY_DOC_GENERATED_AT``) for backward-compat with existing imports
in ``senpy/domain/renpy_api.py`` and ``tests/lsp/test_lsp_21_api_docs.py``.

Why JSON instead of Python literal:
  - 4891 lines of Python code removed from import-time parsing.
  - ``json.load`` is faster than parsing a Python literal dict of this
    size (Python parser builds AST; JSON parser builds dict directly).
  - The data is purely declarative — no Python logic, no computed
    values, no types that JSON cannot represent. A Python literal
    brought no benefit.
  - Future regeneration via ``scripts/fetch_renpy_docs.py`` writes JSON
    directly — no need to template Python source code.

Schema mirrors RENPY_API_DOCS in senpy/domain/renpy_api.py:
    {signature, doc, [details], [example], [url], [category], [namespace]}

Merge strategy in renpy_api.py:
    RENPY_API_DOCS_ALL = {**RENPY_API_DOCS_GENERATED, **RENPY_API_DOCS}
Curated entries win on key collision (they have richer examples/URLs).
"""

from __future__ import annotations

import json
from pathlib import Path

# Load the JSON resource once at module import. The file sits next to
# this module under data/ — resolved via __file__ so the package works
# regardless of the caller's CWD (important for LSP server which may
# be spawned from any directory).
_JSON_PATH = Path(__file__).parent / "data" / "renpy_api_generated.json"

with _JSON_PATH.open(encoding="utf-8") as _f:
    _DATA = json.load(_f)

RENPY_DOC_VERSION_GENERATED: str = _DATA["version"]
RENPY_DOC_GENERATED_AT: str = _DATA["generated_at"]
RENPY_API_DOCS_GENERATED: dict[str, dict] = _DATA["docs"]

__all__ = [
    "RENPY_API_DOCS_GENERATED",
    "RENPY_DOC_VERSION_GENERATED",
    "RENPY_DOC_GENERATED_AT",
]
