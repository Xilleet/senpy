#!/usr/bin/env python3
"""Fetch Ren'Py documentation from GitHub and generate an API definition file.

Python port of renpy-magic's ``scripts/fetch-renpy-docs.ts`` (MIT,
Copyright (c) 2026 Allure Diffusion). Algorithm adapted 1:1 from the
TypeScript original; the RST source layout and directive grammar are
dictated by the Ren'Py Sphinx docs, not by renpy-magic's code.

Coverage gap this script closes vs Senpy's existing ``update_renpy_api.py``:
- ``update_renpy_api.py`` parses Python export modules (statementexports.py
  etc.) via AST and extracts only ``renpy.X()`` function signatures.
- This script parses RST docs and extracts:
    * ``config.*`` variables (≈286 entries)
    * ``gui.*`` variables (≈107 entries)
    * ``build.*`` variables (≈18 entries)
    * style properties (``.. style-property::``)
    * transform properties (``.. transform-property::``)
    * classes / transitions / screen actions (``.. class::``)
    * functions declared in RST (``.. function::``)
    * ``:var:`namespace.name``` definition-list items

The combined output (≈730 entries) goes into
``senpy/domain/renpy_api_generated.py`` as a Python dict literal so it
ships in the wheel without an extra JSON read at import time.

Merge strategy (in ``senpy/domain/renpy_api.py``):
    RENPY_API_DOCS_ALL = {**RENPY_API_DOCS_GENERATED, **RENPY_API_DOCS}
Curated entries (hand-written, with examples/URLs) win on key collision.

Usage:
    python scripts/fetch_renpy_docs.py            # writes generated module
    python scripts/fetch_renpy_docs.py --dry-run  # print summary only

The script is invoked manually by maintainers and the output is committed
to the repo (same workflow renpy-magic uses — not auto-regenerated in CI).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Literal

# Same source URLs as renpy-magic's fetch-renpy-docs.ts.
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/renpy/renpy/master/sphinx/source/"
GITHUB_RAW_COMMON = "https://raw.githubusercontent.com/renpy/renpy/master/renpy/common/"

# RST files to parse. Same list as renpy-magic — covers config/gui/build/
# transforms/transitions/style_properties/transform_properties/screens/
# actions/etc.
RST_FILES = [
    "config.rst",
    "gui.rst",
    "build.rst",
    "transforms.rst",
    "transitions.rst",
    "style_properties.rst",
    "transform_properties.rst",
    "statement_equivalents.rst",  # renpy.say, renpy.pause, etc.
    "audio.rst",
    "save_load_rollback.rst",
    "persistent.rst",
    "preferences.rst",
    "other.rst",
    "screen_actions.rst",
    "screens.rst",
    "text.rst",
    "displayables.rst",
    "layeredimage.rst",
    "model.rst",
    "side_image.rst",
    "rooms.rst",
    "drag_drop.rst",
    "sprites.rst",
    "cds.rst",
    "cdd.rst",
]

# Ren'Py source files with action/class definitions (parsed for docstrings).
RPY_SOURCE_FILES = [
    "00action_control.rpy",
    "00action_data.rpy",
    "00action_file.rpy",
    "00action_menu.rpy",
    "00action_audio.rpy",
    "00action_other.rpy",
]

# Ren'Py version this script targets. Bump when renpy/renpy master moves
# past a release we want to track. The version is written into the generated
# module so consumers can detect staleness.
TARGET_RENPY_VERSION = "8.5.3"

HEADERS = {"User-Agent": "Mozilla/5.0 Senpy-fetcher"}

Category = Literal["variable", "function", "action", "class", "property", "transition"]


# =============================================================================
# HTTP fetch
# =============================================================================


def fetch_url(url: str, timeout: float = 15.0) -> str | None:
    """Fetch a URL with one redirect follow. Returns None on any failure."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status in (301, 302, 307, 308):
                location = resp.headers.get("Location")
                if location:
                    return fetch_url(location, timeout=timeout)
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


# =============================================================================
# RST parsing
# =============================================================================

# Directive matchers — kept identical to the TS version so output matches.
_RE_VAR = re.compile(r"^\.\.\s+var::\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s*(?:=\s*(.+))?$")
_RE_FUNC = re.compile(r"^\.\.\s+function::\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s*\(([^)]*)\)")
_RE_CLASS = re.compile(r"^\.\.\s+class::\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s*(?:\(([^)]*)\))?")
_RE_PROP = re.compile(
    r"^\.\.\s+(?:style-property|transform-property)::\s+([a-zA-Z_][a-zA-Z0-9_]*)"
)
_RE_DEF_LIST_VAR = re.compile(
    r"^:var:`((?:gui|config|build|renpy)\.[a-zA-Z_][a-zA-Z0-9_]*)`\s*$"
)
_RE_DIRECTIVE_START = re.compile(r"^\.\.\s+\w+::")

# RST role cleanup (same regex chain as collectDescription in the TS).
_RE_RST_ROLE_FULL = re.compile(
    r":(?:func|class|var|ref|doc|term|attr|meth|exc|data|const|obj|mod|keyword|"
    r"option|envvar|token|grammar-token|index|any|role|numref|eq|download|hoverxref|"
    r"py:func|py:class|py:meth|py:attr|py:obj|py:exc|py:data|py:const|py:mod)`([^`]+)`"
)
_RE_RST_ROLE_GENERIC = re.compile(r":[a-z]+:`([^`]+)`")
_RE_RST_LITERAL = re.compile(r"``([^`]+)``")
_RE_RST_NOTE = re.compile(r"^\.\.\s+(?:note|warning|tip|important|seealso)::\s*", re.MULTILINE)
_RE_MANY_NEWLINES = re.compile(r"\n{3,}")


def _clean_rst_formatting(text: str) -> str:
    """Convert RST cross-refs/literals/notes to plain markdown."""
    text = _RE_RST_ROLE_FULL.sub(r"`\1`", text)
    text = _RE_RST_ROLE_GENERIC.sub(r"`\1`", text)
    text = _RE_RST_LITERAL.sub(r"`\1`", text)
    text = _RE_RST_NOTE.sub("\n**Note:** ", text)
    text = _RE_MANY_NEWLINES.sub("\n\n", text)
    return text.strip()


def collect_description(lines: list[str], start_index: int) -> str:
    """Collect the indented description block following an RST directive.

    Stops at the next directive or at the first non-indented non-blank line.
    Strips exactly one leading 4-space indent (or one tab) from each line,
    matching the TS implementation's ``line.replace(/^    /, '')``.
    """
    desc_lines: list[str] = []
    i = start_index
    n = len(lines)

    # Skip blank lines.
    while i < n and lines[i].strip() == "":
        i += 1

    while i < n:
        line = lines[i]
        if _RE_DIRECTIVE_START.match(line):
            break
        if line.strip() != "" and not line.startswith("    ") and not line.startswith("\t"):
            break
        # Strip one level of indentation.
        if line.startswith("    "):
            line = line[4:]
        elif line.startswith("\t"):
            line = line[1:]
        desc_lines.append(line)
        i += 1

    return _clean_rst_formatting("\n".join(desc_lines))


# Transition / action name heuristics — same lists as the TS.
_TRANSITION_NAMES = (
    "Dissolve", "Fade", "ImageDissolve", "AlphaDissolve", "CropMove",
    "PushMove", "MoveTransition", "MoveFactory", "MoveIn", "MoveOut",
    "Pixellate", "Swing", "Zoom", "ZoomInOut",
)
_ACTION_PATTERNS = (
    "Action", "Jump", "Call", "Show", "Hide", "Return", "Set", "Toggle",
    "Play", "Stop", "Queue", "Mute", "File", "Preference", "Quit", "Start",
    "Rollback", "Notify", "Confirm", "If", "Screenshot", "Skip", "Auto",
    "Menu", "Replay", "End", "Mouse", "Open", "Null",
)


def _is_transition_name(name: str) -> bool:
    return any(t in name for t in _TRANSITION_NAMES)


def _is_action_name(name: str) -> bool:
    return any(p in name for p in _ACTION_PATTERNS)


def parse_rst_file(content: str, filename: str) -> list[dict]:
    """Parse one RST file, return a list of API entries.

    Mirrors ``parseRstFile`` in fetch-renpy-docs.ts: directive-by-directive
    walk with a second pass for ``:var:`ns.name``` definition-list items.
    """
    entries: list[dict] = []
    lines = content.split("\n")
    seen_names: set[str] = set()

    i = 0
    while i < len(lines):
        line = lines[i]

        # .. var:: ns.name = default
        m = _RE_VAR.match(line)
        if m:
            full_name = m.group(1)
            default_value = (m.group(2) or "").strip()
            description = collect_description(lines, i + 1)
            namespace = _namespace_of(full_name)
            entries.append({
                "name": full_name,
                "signature": (
                    f"{full_name} = {default_value}" if default_value else full_name
                ),
                "description": description,
                "category": "variable",
                "namespace": namespace,
            })
            seen_names.add(full_name)
            i += 1
            continue

        # .. function:: name(params)
        m = _RE_FUNC.match(line)
        if m:
            full_name = m.group(1)
            params = m.group(2)
            description = collect_description(lines, i + 1)
            entries.append({
                "name": full_name,
                "signature": f"{full_name}({params})",
                "description": description,
                "category": "function",
                "namespace": _namespace_of(full_name),
            })
            seen_names.add(full_name)
            i += 1
            continue

        # .. class:: Name(params)
        m = _RE_CLASS.match(line)
        if m:
            full_name = m.group(1)
            params = (m.group(2) or "").strip()
            description = collect_description(lines, i + 1)
            category: Category = "class"
            if "transition" in filename or _is_transition_name(full_name):
                category = "transition"
            elif "action" in filename or _is_action_name(full_name):
                category = "action"
            entries.append({
                "name": full_name,
                "signature": (
                    f"{full_name}({params})" if params else full_name
                ),
                "description": description,
                "category": category,
            })
            seen_names.add(full_name)
            i += 1
            continue

        # .. style-property:: name  /  .. transform-property:: name
        m = _RE_PROP.match(line)
        if m:
            name = m.group(1)
            description = collect_description(lines, i + 1)
            entries.append({
                "name": name,
                "signature": name,
                "description": description,
                "category": "property",
            })
            seen_names.add(name)
            i += 1
            continue

        i += 1

    # Second pass: ``:var:`ns.name``` definition-list items.
    for j, line in enumerate(lines):
        m = _RE_DEF_LIST_VAR.match(line)
        if not m:
            continue
        full_name = m.group(1)
        if full_name in seen_names:
            continue
        description = collect_description(lines, j + 1)
        entries.append({
            "name": full_name,
            "signature": full_name,
            "description": description,
            "category": "variable",
            "namespace": _namespace_of(full_name),
        })
        seen_names.add(full_name)

    return entries


def _namespace_of(full_name: str) -> str | None:
    """Return the namespace prefix (config/gui/build/renpy) or None."""
    if full_name.startswith("config."):
        return "config"
    if full_name.startswith("gui."):
        return "gui"
    if full_name.startswith("build."):
        return "build"
    if full_name.startswith("renpy."):
        return "renpy"
    return None


# =============================================================================
# Ren'Py source (.rpy) parsing — for action classes with docstrings
# =============================================================================

_RE_PY_CLASS = re.compile(
    r"^\s*class\s+([A-Z][a-zA-Z0-9_]*)\s*(?:\([^)]*\))?\s*:"
)
_RE_PY_INIT = re.compile(r"def\s+__init__\s*\(\s*self\s*,?\s*([^)]*)\)")
# Allow leading whitespace so the regexes work on indented class-body lines
# (e.g. ``    """Docstring."""`` inside a class). The TS version uses
# ``lines[j].includes('"""')`` to detect, then collectPythonDocstring does
# its own line-by-line scan; we use regexes for clarity but must accept
# the same indentation.
_RE_DOC_OPEN = re.compile(r'^\s*"""\s*(.*)')
_RE_DOC_CLOSE = re.compile(r'(.*?)"""')
_RE_DOC_SINGLE = re.compile(r'^\s*"""\s*(.+?)\s*"""')
_RE_ARGS_DIRECTIVE = re.compile(r":args:\s*\(([^)]+)\)")


def _collect_python_docstring(lines: list[str], start_index: int) -> str:
    """Collect a triple-quoted Python docstring starting at lines[start_index]."""
    if start_index >= len(lines):
        return ""
    first_line = lines[start_index]

    # Single-line docstring: """text"""
    m = _RE_DOC_SINGLE.match(first_line)
    if m:
        return m.group(1)

    # Multi-line: opening """ on first_line, closing """ on a later line.
    m = _RE_DOC_OPEN.match(first_line)
    if not m:
        return ""

    doc_lines: list[str] = []
    if m.group(1):
        doc_lines.append(m.group(1))

    i = start_index + 1
    while i < len(lines):
        line = lines[i]
        close_m = _RE_DOC_CLOSE.match(line)
        if close_m:
            if close_m.group(1).strip():
                doc_lines.append(close_m.group(1))
            break
        doc_lines.append(line)
        i += 1

    # Strip 4-8 leading spaces from each line (TS: `l.replace(/^\s{4,8}/, '')`).
    cleaned = [re.sub(r"^\s{4,8}", "", line) for line in doc_lines]
    return "\n".join(cleaned).strip()


def _extract_signature_from_init(
    lines: list[str], class_line_index: int, class_name: str
) -> str:
    """Look for ``def __init__(self, ...)`` in the next ~30 lines."""
    upper = min(class_line_index + 30, len(lines))
    for i in range(class_line_index + 1, upper):
        line = lines[i]
        # Stop at the next class definition.
        if _RE_PY_CLASS.match(line):
            break
        m = _RE_PY_INIT.search(line)
        if m:
            params = m.group(1).strip()
            return f"{class_name}({params})" if params else f"{class_name}()"
    return f"{class_name}()"


def parse_rpy_file(content: str, filename: str) -> list[dict]:
    """Parse a Ren'Py .rpy source file for class definitions + docstrings.

    Mirrors ``parseRpyFile`` in fetch-renpy-docs.ts.
    """
    entries: list[dict] = []
    lines = content.split("\n")

    i = 0
    while i < len(lines):
        line = lines[i]
        m = _RE_PY_CLASS.match(line)
        if m:
            class_name = m.group(1)

            # Skip blank lines.
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1

            # Check for docstring.
            if j < len(lines) and '"""' in lines[j]:
                docstring = _collect_python_docstring(lines, j)
                if docstring:
                    args_m = _RE_ARGS_DIRECTIVE.search(docstring)
                    if args_m:
                        signature = f"{class_name}({args_m.group(1)})"
                    else:
                        signature = _extract_signature_from_init(lines, i, class_name)

                    # Clean description (remove :doc: and :args: directives).
                    description = docstring
                    description = re.sub(r":doc:\s*\w+\s*", "", description)
                    description = re.sub(r":args:\s*\([^)]+\)\s*", "", description)
                    description = description.strip()

                    category: Category = "class"
                    if class_name.endswith("Action") or _is_action_name(class_name):
                        category = "action"
                    elif _is_transition_name(class_name):
                        category = "transition"

                    entries.append({
                        "name": class_name,
                        "signature": signature,
                        "description": description,
                        "category": category,
                    })
        i += 1

    return entries


# =============================================================================
# Output: write senpy/domain/renpy_api_generated.py
# =============================================================================


def _serialize_entry(entry: dict) -> str:
    """Render one entry as a Python dict literal block."""
    fields = []
    fields.append(f'        "signature": {entry["signature"]!r},')
    fields.append(f'        "doc": {entry["description"]!r},')
    if entry.get("category"):
        fields.append(f'        "category": {entry["category"]!r},')
    if entry.get("namespace"):
        fields.append(f'        "namespace": {entry["namespace"]!r},')
    # Synthesize a docs URL from the namespace (best-effort link to renpy.org).
    url = _docs_url_for(entry)
    if url:
        fields.append(f'        "url": {url!r},')
    return "    " + repr(entry["name"]) + ": {\n" + "\n".join(fields) + "\n    },"


def _docs_url_for(entry: dict) -> str | None:
    """Best-effort docs URL. renpy.org uses section.html#anchor pattern."""
    name = entry["name"]
    namespace = entry.get("namespace")
    if namespace == "config":
        return f"https://www.renpy.org/doc/html/config.html#var-{name.replace('.', '-')}"
    if namespace == "gui":
        return f"https://www.renpy.org/doc/html/gui.html#var-{name.replace('.', '-')}"
    if namespace == "build":
        return f"https://www.renpy.org/doc/html/build.html#var-{name.replace('.', '-')}"
    if namespace == "renpy":
        return f"https://www.renpy.org/doc/html/other.html#{name.replace('.', '-')}"
    if entry.get("category") == "action":
        return f"https://www.renpy.org/doc/html/screen_actions.html#{name}"
    if entry.get("category") == "transition":
        return f"https://www.renpy.org/doc/html/transitions.html#{name}"
    if entry.get("category") == "property":
        # Style and transform properties live on separate pages.
        # We can't tell which without metadata; pick the style page as default.
        return f"https://www.renpy.org/doc/html/style_properties.html#style-property-{name}"
    return None


def serialize_python_module(version: str, generated_at: str, entries: list[dict]) -> str:
    """Render the generated Python module source.

    Output is a single ``RENPY_API_DOCS_GENERATED`` dict literal — same
    schema as the curated ``RENPY_API_DOCS`` (signature/doc/details/url +
    extras: category, namespace) so the merge in renpy_api.py is a plain
    dict update.
    """
    # Deduplicate by name (keep first occurrence — same as TS).
    seen: set[str] = set()
    unique: list[dict] = []
    for e in entries:
        if e["name"] in seen:
            continue
        seen.add(e["name"])
        unique.append(e)

    # Sort by name for stable diffs.
    unique.sort(key=lambda e: e["name"])

    lines = [
        '"""Auto-generated Ren\'Py API documentation.',
        "",
        f"Source: Ren'Py v{version} RST docs (sphinx/source/) + common/*.rpy.",
        f"Generated: {generated_at}",
        "",
        "DO NOT EDIT BY HAND — re-run ``python scripts/fetch_renpy_docs.py``.",
        "",
        "Schema mirrors RENPY_API_DOCS in senpy/domain/renpy_api.py:",
        '    {signature, doc, [details], [example], [url], [category], [namespace]}',
        "",
        "Merge strategy in renpy_api.py:",
        "    RENPY_API_DOCS_ALL = {**RENPY_API_DOCS_GENERATED, **RENPY_API_DOCS}",
        "Curated entries win on key collision (they have richer examples/URLs).",
        '"""',
        "from __future__ import annotations",
        "",
        f'RENPY_DOC_VERSION_GENERATED = "{version}"',
        f'RENPY_DOC_GENERATED_AT = "{generated_at}"',
        "",
        "RENPY_API_DOCS_GENERATED: dict[str, dict[str, str]] = {",
    ]
    for entry in unique:
        lines.append(_serialize_entry(entry))
    lines.append("}")
    lines.append("")
    lines.append("__all__ = [\"RENPY_API_DOCS_GENERATED\", \"RENPY_DOC_VERSION_GENERATED\", \"RENPY_DOC_GENERATED_AT\"]")
    lines.append("")
    return "\n".join(lines)


# =============================================================================
# Main
# =============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch + parse + print summary, but don't write the output file.",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output path. Default: senpy/domain/renpy_api_generated.py next to this repo.",
    )
    args = parser.parse_args()

    print("=" * 65)
    print(" SENPY — Ren'Py RST docs fetcher ")
    print("=" * 65)

    all_entries: list[dict] = []

    print("\n=== RST Documentation Files ===")
    # Parallel fetch — same pattern as update_renpy_api.py.
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(fetch_url, GITHUB_RAW_BASE + fname): fname
            for fname in RST_FILES
        }
        for future in as_completed(futures):
            fname = futures[future]
            content = future.result()
            if content is None:
                print(f"  ✗ {fname}: fetch failed")
                continue
            entries = parse_rst_file(content, fname)
            print(f"  ✓ {fname}: {len(entries)} entries")
            all_entries.extend(entries)

    print("\n=== Ren'Py Source Files (Actions) ===")
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(fetch_url, GITHUB_RAW_COMMON + fname): fname
            for fname in RPY_SOURCE_FILES
        }
        for future in as_completed(futures):
            fname = futures[future]
            content = future.result()
            if content is None:
                print(f"  ✗ {fname}: fetch failed")
                continue
            entries = parse_rpy_file(content, fname)
            print(f"  ✓ {fname}: {len(entries)} entries")
            all_entries.extend(entries)

    # Deduplicate + summary.
    seen: set[str] = set()
    unique: list[dict] = []
    for e in all_entries:
        if e["name"] in seen:
            continue
        seen.add(e["name"])
        unique.append(e)

    by_category: dict[str, int] = {}
    by_namespace: dict[str, int] = {}
    for e in unique:
        by_category[e["category"]] = by_category.get(e["category"], 0) + 1
        ns = e.get("namespace") or "(none)"
        by_namespace[ns] = by_namespace.get(ns, 0) + 1

    print(f"\n=== Summary ===\nTotal unique entries: {len(unique)}")
    print("\nBy category:")
    for cat, n in sorted(by_category.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {n}")
    print("\nBy namespace:")
    for ns, n in sorted(by_namespace.items(), key=lambda x: -x[1]):
        print(f"  {ns}: {n}")

    if args.dry_run:
        print("\n[--dry-run] Not writing output file.")
        return 0

    # Resolve output path.
    if args.output:
        output_path = args.output
    else:
        # Default: senpy/domain/renpy_api_generated.py
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        output_path = os.path.join(repo_root, "senpy", "domain", "renpy_api_generated.py")

    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    module_source = serialize_python_module(TARGET_RENPY_VERSION, generated_at, unique)

    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(module_source)

    print(f"\n[✔] Wrote {len(unique)} entries to: {output_path}")
    print(f"    Ren'Py version: {TARGET_RENPY_VERSION}")
    print(f"    Generated at:   {generated_at}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[!] Interrupted.")
        sys.exit(130)
