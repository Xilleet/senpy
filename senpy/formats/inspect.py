"""Introspection format — `senpy inspect` JSON output.

WL-506: serialize all symbols collected by `SenpyAnalyzer` into a
JSON-serializable dict for the `senpy inspect` CLI subcommand.

The function `dump_symbols(analyzer, *, with_source=False)` reads
directly from the analyzer's in-memory registries (set after
`analyzer.run()` completes). It does not re-scan the project — this
is a cheap serialization pass over already-collected data.

Top-level JSON structure (per the 0.7.4 design):

    {
      "labels":     {name: {...}, ...},
      "screens":     {name: {...}, ...},
      "variables":   {name: {...}, ...},
      "transforms":  {name: {...}, ...},
      "images":      {name: {...}, ...},
      "jump_sources": {target: [[file, line], ...], ...},
      "used_assets":  [asset, ...],
      "diagnostics":  [{...}, ...],
      "unresolved": {
        "broken_jumps":         [{...}, ...],
        "missing_screens":       [{...}, ...],
        "unreferenced_labels":   [{...}, ...],
        "unused_assets":         [asset, ...]
      },
      "stats": {files, lines, labels, screens, variables, transforms,
                images, diagnostics, broken_jumps, missing_screens,
                unreferenced_labels, unused_assets}
    }

`with_source=False` (default) omits `code_line` (for labels, variables,
transforms) and `body` (for images) to keep the JSON compact.
`with_source=True` includes them — used by `senpy inspect --with-source`
and auto-enabled for single-symbol lookups (`--label NAME` etc.).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from senpy.core.analyzer import SenpyAnalyzer
    from senpy.core.signature import SignatureInfo


# =============================================================================
# Public API
# =============================================================================


def dump_symbols(analyzer: SenpyAnalyzer, *, with_source: bool = False) -> dict:
    """Build a JSON-serializable dict of all symbols + unresolved + stats.

    Args:
        analyzer: SenpyAnalyzer that has had `.run()` called.
        with_source: When True, include `code_line`/`body` for each
            symbol. When False (default), omit them for a more compact
            JSON.

    Returns:
        A JSON-serializable dict with the structure documented in this
        module's docstring. All `set` and `tuple` containers are
        converted to `list` (JSON does not have set/tuple types).
    """
    labels = _dump_labels(analyzer, with_source)
    screens = _dump_screens(analyzer, with_source)
    variables = _dump_variables(analyzer, with_source)
    transforms = _dump_transforms(analyzer, with_source)
    images = _dump_images(analyzer, with_source)
    jump_sources = _dump_jump_sources(analyzer)
    used_assets = _dump_used_assets(analyzer)
    diagnostics = _dump_diagnostics(analyzer)
    unresolved = _dump_unresolved(analyzer)
    stats = _build_stats(
        analyzer, labels, screens, variables, transforms, images, diagnostics, unresolved
    )

    return {
        "labels": labels,
        "screens": screens,
        "variables": variables,
        "transforms": transforms,
        "images": images,
        "jump_sources": jump_sources,
        "used_assets": used_assets,
        "diagnostics": diagnostics,
        "unresolved": unresolved,
        "stats": stats,
    }


# =============================================================================
# Per-section dumpers
# =============================================================================


def _dump_labels(analyzer: SenpyAnalyzer, with_source: bool) -> dict:
    out: dict = {}
    for name, sym in analyzer.labels.items():
        entry: dict = {
            "name": sym.name,
            "file_path": sym.file_path,
            "line_number": sym.line_number,
            "has_return": sym.has_return,
            "outgoing_jumps": sorted(sym.outgoing_jumps),
            "jump_sources": [[file, line] for file, line in sym.jump_sources],
        }
        if sym.signature is not None:
            entry["signature"] = _dump_signature(sym.signature)
        if with_source:
            entry["code_line"] = sym.code_line
        out[name] = entry
    return out


def _dump_screens(analyzer: SenpyAnalyzer, with_source: bool) -> dict:
    out: dict = {}
    for name, sym in analyzer.screens.items():
        entry: dict = {
            "name": sym.name,
            "file_path": sym.file_path,
            "line_number": sym.line_number,
        }
        if sym.signature is not None:
            entry["signature"] = _dump_signature(sym.signature)
        # Screens don't have a `code_line` field in ScreenSymbol — the
        # source line can be re-read from file_path:line_number if needed.
        # We still honor `with_source` for symmetry, but no extra field
        # is added here.
        out[name] = entry
    return out


def _dump_variables(analyzer: SenpyAnalyzer, with_source: bool) -> dict:
    out: dict = {}
    for name, sym in analyzer.variables.items():
        entry: dict = {
            "name": sym.name,
            "file_path": sym.file_path,
            "line_number": sym.line_number,
            "type_name": sym.type_name,
            "is_constant": sym.is_constant,
            "is_character": sym.is_character,
        }
        if with_source:
            entry["code_line"] = sym.code_line
        out[name] = entry
    return out


def _dump_transforms(analyzer: SenpyAnalyzer, with_source: bool) -> dict:
    out: dict = {}
    for name, sym in analyzer.transforms.items():
        entry: dict = {
            "name": sym.name,
            "file_path": sym.file_path,
            "line_number": sym.line_number,
        }
        if with_source:
            entry["code_line"] = sym.code_line
        out[name] = entry
    return out


def _dump_images(analyzer: SenpyAnalyzer, with_source: bool) -> dict:
    out: dict = {}
    for name, sym in analyzer.images.items():
        entry: dict = {
            "name": sym.name,
            "file_path": sym.file_path,
            "line_number": sym.line_number,
            "is_layered": sym.is_layered,
            "attributes": sorted(sym.attributes),
            "image_path": sym.image_path,
        }
        if with_source:
            entry["body"] = sym.body
        out[name] = entry
    return out


def _dump_jump_sources(analyzer: SenpyAnalyzer) -> dict:
    """jump_sources: dict[str, list[tuple[str, int]]] -> dict[str, list[list]]."""
    out: dict = {}
    for target, sources in analyzer.jump_sources.items():
        out[target] = [[file, line] for file, line in sources]
    return out


def _dump_used_assets(analyzer: SenpyAnalyzer) -> list:
    """used_asset_keys is a set — sorted list for JSON stability."""
    try:
        keys = sorted(analyzer.used_asset_keys)
    except TypeError:
        # If used_asset_keys returns non-sortable (e.g. mixed types),
        # sort by string representation.
        keys = sorted(str(k) for k in analyzer.used_asset_keys)
    return keys


def _dump_diagnostics(analyzer: SenpyAnalyzer) -> list:
    out: list = []
    for d in analyzer.diagnostics:
        out.append(
            {
                "file_path": d.file_path,
                "line_number": d.line_number,
                "code": d.code,
                "message": d.message,
                "severity": d.severity,
                "col": d.col,
                "end_col": d.end_col,
            }
        )
    return out


def _dump_unresolved(analyzer: SenpyAnalyzer) -> dict:
    """The 4 unresolved categories — derived from analyzer state."""
    broken_jumps = _collect_broken_jumps(analyzer)
    missing_screens = _collect_missing_screens(analyzer)
    unreferenced_labels = _collect_unreferenced_labels(analyzer)
    unused_assets = _collect_unused_assets(analyzer)
    return {
        "broken_jumps": broken_jumps,
        "missing_screens": missing_screens,
        "unreferenced_labels": unreferenced_labels,
        "unused_assets": unused_assets,
    }


def _build_stats(
    analyzer: SenpyAnalyzer,
    labels: dict,
    screens: dict,
    variables: dict,
    transforms: dict,
    images: dict,
    diagnostics: list,
    unresolved: dict,
) -> dict:
    return {
        "files": len(analyzer.file_scopes),
        "lines": analyzer.total_lines,
        "labels": len(labels),
        "screens": len(screens),
        "variables": len(variables),
        "transforms": len(transforms),
        "images": len(images),
        "diagnostics": len(diagnostics),
        "broken_jumps": len(unresolved["broken_jumps"]),
        "missing_screens": len(unresolved["missing_screens"]),
        "unreferenced_labels": len(unresolved["unreferenced_labels"]),
        "unused_assets": len(unresolved["unused_assets"]),
    }


# =============================================================================
# Unresolved collectors
# =============================================================================


def _collect_broken_jumps(analyzer: SenpyAnalyzer) -> list:
    """Targets referenced via jump/call but NOT in analyzer.labels.

    Each entry: {"target": name, "jump_from": [[file, line], ...]}.
    Uses `analyzer.jump_sources` (reverse index) for the location list.
    """
    out: list = []
    label_names = set(analyzer.labels.keys())
    # Referenced labels = jump/call targets that appear in jump_sources
    # (and possibly also in referenced_labels set).
    for target, sources in analyzer.jump_sources.items():
        if target not in label_names:
            out.append(
                {
                    "target": target,
                    "jump_from": [[file, line] for file, line in sources],
                }
            )
    # Some referenced labels may not have a jump_sources entry (e.g.
    # dynamic jumps or labels referenced only from `call`). Check the
    # `referenced_labels` set too.
    for target in analyzer.referenced_labels:
        if target not in label_names and not any(e["target"] == target for e in out):
            out.append({"target": target, "jump_from": []})
    out.sort(key=lambda e: e["target"])
    return out


def _collect_missing_screens(analyzer: SenpyAnalyzer) -> list:
    """Screens used (via `call screen X` or `use X`) but not declared.

    Each entry: {"target": name, "used_in": [[file, line], ...]} if
    we can locate the use site, else {"target": name, "used_in": []}.
    """
    out: list = []
    screen_names = set(analyzer.screens.keys())
    for used in analyzer.used_screens:
        if used not in screen_names:
            # Try to locate where the screen was used. The `screen_uses`
            # dict maps a containing label/screen to set of screens it
            # uses, but doesn't give the file:line. For now, leave the
            # used_in list empty — we know it was used but not where.
            out.append({"target": used, "used_in": []})
    out.sort(key=lambda e: e["target"])
    return out


def _collect_unreferenced_labels(analyzer: SenpyAnalyzer) -> list:
    """Labels declared but never referenced via jump/call/statically.

    `start` is special — it's the Ren'Py entry point, never flagged.
    Each entry: {"name": label, "file_path": str, "line_number": int}.
    """
    out: list = []
    referenced = set(analyzer.referenced_labels)
    for name, sym in analyzer.labels.items():
        if name == "start":
            continue
        if name not in referenced:
            out.append(
                {
                    "name": name,
                    "file_path": sym.file_path,
                    "line_number": sym.line_number,
                }
            )
    out.sort(key=lambda e: e["name"])
    return out


def _collect_unused_assets(analyzer: SenpyAnalyzer) -> list:
    """Assets on disk (or referenced as `define audio.X = "..."`) but
    never used in `show`/`scene`/`play`/`queue` statements.

    Implementation note: this is the RPY503 rule. The analyzer's
    `known_assets` (files on disk in image/audio dirs) minus
    `used_asset_keys` (assets referenced in code). We do NOT include
    builtin `valid_images` (white, black, etc.) — those are not real
    on-disk files.

    Each entry: a string (the asset path).
    """
    used = set(analyzer.used_asset_keys)
    known = set(analyzer.known_assets)
    # Builtin images like "white", "black" are not real assets.
    builtin_images = set(getattr(analyzer, "_BUILTIN_IMAGES", set()))
    unused = known - used - builtin_images
    return sorted(unused)


# =============================================================================
# Signature serializer
# =============================================================================


def _dump_signature(sig: SignatureInfo) -> dict:
    """Serialize a SignatureInfo dataclass to a JSON-serializable dict."""
    return {
        "min_args": sig.min_args,
        "max_args": sig.max_args,
        "has_varargs": sig.has_varargs,
        "has_varkwargs": sig.has_varkwargs,
        "required_names": sorted(sig.required_names) if sig.required_names else [],
        "all_names": sorted(sig.all_names) if sig.all_names else [],
        "has_params": sig.has_params,
        "pos_names": list(sig.pos_names) if sig.pos_names else [],
    }
