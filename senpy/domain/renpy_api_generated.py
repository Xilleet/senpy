"""Auto-generated Ren'Py API documentation — JSON-backed loader.

Source: Ren'Py v8.6.1 RST docs (sphinx/source/) + common/*.rpy.
Generated: 2026-11-20T22:23:35Z

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
from importlib.resources import files

# Load the JSON resource once at module import. The file sits next to
# this module under data/ — resolved via ``importlib.resources`` so the
# path is correct in EVERY distribution shape:
#
#   - dev checkout           — files("senpy.domain") → repo source dir
#   - pip-installed wheel    — files("senpy.domain") → site-packages dir
#                              (the JSON is shipped via [tool.setuptools.
#                              package-data] "senpy.domain.data" = ["*.json"])
#   - PyInstaller onefile    — files("senpy.domain") → the temp _MEI...
#                              extraction dir, where the JSON is bundled
#                              by senpy.spec's ``collect_all('senpy')``
#                              (which runs collect_data_files and copies
#                              every non-.py file in the package, including
#                              data/renpy_api_generated.json, into the
#                              bundle at senpy/domain/data/).
#
# This replaces the previous ``Path(__file__).parent / "data" / ...``
# resolution, which worked in dev and wheel but broke the frozen
# senpy.exe: when the JSON was not added to the bundle's datas list,
# ``__file__`` pointed into the _MEI... tree and the data path did not
# exist, crashing every invocation (including ``--version``) at import
# time with FileNotFoundError (0.9.2 release blocker).
#
# ``importlib.resources`` is the canonical bundle-aware resource API and
# is honoured by PyInstaller's import machinery as long as the data file
# is in the bundle's datas list — which collect_all('senpy') guarantees.
_RESOURCE = files("senpy.domain").joinpath("data", "renpy_api_generated.json")

with _RESOURCE.open(encoding="utf-8") as _f:
    _DATA = json.load(_f)

RENPY_DOC_VERSION_GENERATED: str = _DATA["version"]
RENPY_DOC_GENERATED_AT: str = _DATA["generated_at"]
RENPY_API_DOCS_GENERATED: dict[str, dict] = _DATA["docs"]

__all__ = [
    "RENPY_API_DOCS_GENERATED",
    "RENPY_DOC_VERSION_GENERATED",
    "RENPY_DOC_GENERATED_AT",
]
