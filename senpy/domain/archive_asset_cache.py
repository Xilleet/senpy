"""Sandbox cache for archive-only assets.

When an image / audio reference resolves to no disk file but the asset lives
inside a parsed ``.rpa`` archive, the LSP hover used to render only
a "found inside archive" text hint — VS Code's viewer cannot decode a byte
range inside an archive. This module extracts the asset's full bytes (every
segment, via :func:`read_rpa_segment`) to a stable on-disk cache path so the
hover can render a REAL preview (inline image / audio link) pointing at the
extracted file instead of the text-only hint.

Cache layout: ``<cache_root>/<sha1(archive_path)[:16]>/<entry.filename>``.
The per-archive hash discriminates projects / archives that happen to share
an entry filename; the entry filename preserves its subdir structure
(``game/images/bg.png``) so two same-named assets in different subdirs of
one archive do not collide. Path-traversal entries (``../../evil.png``) are
refused — the resolved destination must stay inside the per-archive cache
dir (``os.path.commonpath`` containment, mirroring
``extract_scripts_from_rpa``).

Invalidation: an existing cache file whose mtime is >= the archive's mtime
is reused as-is (no re-extraction). When the archive changes, its mtime
advances and the stale cache is overwritten on the next hover.

The cache is best-effort and lazily populated (only assets actually
hovered). It is not bounded; an LRU / cleanup pass is a future concern.
"""

from __future__ import annotations

import hashlib
import logging
import os

from senpy.domain.rpa import RpaEntry, read_rpa_segment

__all__ = ["extract_asset_to_cache", "DEFAULT_CACHE_ROOT"]

_logger = logging.getLogger(__name__)

DEFAULT_CACHE_ROOT = os.path.expanduser("~/.senpy/archive_assets")


def _cache_dir_for(archive_path: str, cache_root: str) -> str:
    """Per-archive cache subdir: ``<cache_root>/<sha1(abs_path)[:16]>``.

    Hashing the archive's absolute path keeps two projects that both ship a
    ``game/images/bg.png`` from colliding in the shared cache root, while
    staying stable across hover calls (so the mtime cache works)."""
    digest = hashlib.sha1(os.path.abspath(archive_path).encode("utf-8")).hexdigest()[:16]
    return os.path.join(cache_root, digest)


def extract_asset_to_cache(entry: RpaEntry, cache_root: str | None = None) -> str | None:
    """Extract *entry*'s full bytes to the sandbox cache; return the absolute
    cache path, or ``None`` on failure (archive unreadable, path-traversal
    entry, truncated segment, IO error).

    Reads every segment via :func:`read_rpa_segment` and concatenates (prefix
    is prepended per segment, semantics preserved). Since,
    ``read_rpa_segment`` raises ``ValueError`` on a short read (truncated
    segment / offset beyond EOF); that propagates as ``None`` here so the
    hover falls back to the "found inside archive" hint rather than caching a
    partial file. Idempotent: a cache file whose mtime is >= the archive's
    mtime is returned without re-reading bytes, so repeated hovers of the
    same asset are cheap.
    """
    root = cache_root or DEFAULT_CACHE_ROOT
    if not entry.archive_path or not entry.segments:
        return None
    subdir = _cache_dir_for(entry.archive_path, root)
    dest = os.path.abspath(os.path.join(subdir, entry.filename))
    subdir_abs = os.path.abspath(subdir)
    # Path-traversal guard: dest must stay inside the per-archive subdir.
    # Blocks entry filenames like ``../../evil.png`` (or absolute paths)
    # that would otherwise escape the cache root. Mirrors the containment
    # check in ``extract_scripts_from_rpa``.
    try:
        if os.path.commonpath([dest, subdir_abs]) != subdir_abs:
            _logger.debug(
                "refused path-traversal archive entry %r (would escape %s)",
                entry.filename,
                subdir_abs,
            )
            return None
    except ValueError:
        # commonpath raises on Windows cross-drive paths — a definite escape.
        return None

    try:
        rpa_mtime = os.path.getmtime(entry.archive_path)
    except OSError:
        return None

    # Cache hit: reuse if the cached file is at least as new as the archive.
    if os.path.exists(dest) and os.path.getmtime(dest) >= rpa_mtime:
        return dest

    try:
        with open(entry.archive_path, "rb") as f:
            file_bytes = b"".join(read_rpa_segment(f, seg) for seg in entry.segments)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as out:
            out.write(file_bytes)
        return dest
    except (OSError, ValueError, TypeError) as exc:
        # Archive vanished mid-read, segment seek out of range, or the disk
        # is unwritable. Non-fatal — the hover falls back to the RPA-11 hint.
        _logger.debug("archive asset extract failed for %s: %s", entry.archive_path, exc)
        return None
