#!/usr/bin/env python3
"""Push badge JSON files from .github/badges/ to a GitHub Gist.

Replaces the old "commit-back to main" pattern that caused merge conflicts
between the maintainer's pushes and the CI's badge-update commits. With a
Gist, CI writes badge JSON to a separate storage that does not touch the
``main`` branch — no race condition, no merge commits, no badge noise in
``git log --oneline``.

Usage (typically called from CI after ``update_badges.py --run``):

    GIST_TOKEN=<pat-with-gist-scope> \\
    GIST_ID=<gist-id-from-url> \\
    python scripts/push_badges_to_gist.py

Environment variables:
    GIST_TOKEN (required) — Personal Access Token (classic) with the
        ``gist`` scope. The Actions-provided ``GITHUB_TOKEN`` does NOT
        have gist permissions — a PAT is mandatory. Store it as a repo
        secret named ``GIST_TOKEN`` and pass it via the ``env:`` block
        of the workflow step.
    GIST_ID (required) — the gist ID, taken from the gist's URL:
        ``https://gist.github.com/<user>/<GIST_ID>``. Store as a repo
        secret or variable named ``GIST_ID``.

The gist must be PUBLIC (or the token must have access to a secret gist).
shields.io ``endpoint`` badges need a publicly reachable URL to fetch
the JSON from.

Exit codes:
    0 — all badges pushed (or no change needed)
    1 — missing env vars, API error, or non-200 response from GitHub
    2 — local badges directory not found / empty (setup error)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BADGES_DIR = REPO_ROOT / ".github" / "badges"
GITHUB_API = "https://api.github.com/gists/"


def _fail(msg: str, code: int = 1) -> int:
    print(f"push_badges_to_gist: ERROR: {msg}", file=sys.stderr)
    return code


def _load_local_badges() -> dict[str, str]:
    """Read every .github/badges/*.json file into {filename: content}."""
    if not BADGES_DIR.is_dir():
        return {}
    out: dict[str, str] = {}
    for path in sorted(BADGES_DIR.glob("*.json")):
        # Re-serialise to canonical form (same as update_badges.py writes),
        # so a gist that already has byte-identical content is a no-op.
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out[path.name] = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        except (OSError, json.JSONDecodeError) as e:
            print(f"push_badges_to_gist: WARN: skipping {path.name}: {e}", file=sys.stderr)
    return out


def _fetch_gist(gist_id: str, token: str) -> dict | None:
    """GET /gists/{id} → current gist state (or None on error)."""
    req = urllib.request.Request(
        GITHUB_API + gist_id,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"push_badges_to_gist: HTTP {e.code} on GET gist: {e.reason}", file=sys.stderr)
        try:
            body = e.read().decode("utf-8")
            print(f"  body: {body[:500]}", file=sys.stderr)
        except OSError:
            pass
        return None
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"push_badges_to_gist: network error on GET gist: {e}", file=sys.stderr)
        return None


def _push_gist(gist_id: str, token: str, files_to_update: dict[str, str]) -> bool:
    """PATCH /gists/{id} with the changed files. Returns True on success."""
    # GitHub API expects: {"files": {"name.json": {"content": "..."}}}
    payload = json.dumps(
        {"files": {name: {"content": content} for name, content in files_to_update.items()}}
    ).encode("utf-8")
    req = urllib.request.Request(
        GITHUB_API + gist_id,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
            return True
    except urllib.error.HTTPError as e:
        print(f"push_badges_to_gist: HTTP {e.code} on PATCH gist: {e.reason}", file=sys.stderr)
        try:
            body = e.read().decode("utf-8")
            print(f"  body: {body[:500]}", file=sys.stderr)
        except OSError:
            pass
        return False
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"push_badges_to_gist: network error on PATCH gist: {e}", file=sys.stderr)
        return False


def main() -> int:
    token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("GIST_ID")
    if not token:
        return _fail(
            "GIST_TOKEN env var is not set. Create a classic PAT with the 'gist' scope and store it as a repo secret named GIST_TOKEN."
        )
    if not gist_id:
        return _fail(
            "GIST_ID env var is not set. Create a public gist and store its ID (from the URL) as a repo secret named GIST_ID."
        )

    local_badges = _load_local_badges()
    if not local_badges:
        return _fail(
            f"no badge JSON files found in {BADGES_DIR}. Run `python scripts/update_badges.py --run` first.",
            code=2,
        )

    # Fetch the current gist state to skip the PATCH when nothing changed
    # (avoids creating a new gist revision every CI run for nothing).
    current = _fetch_gist(gist_id, token)
    if current is None:
        return 1

    current_files = current.get("files", {}) or {}
    changed: dict[str, str] = {}
    for name, content in local_badges.items():
        existing = current_files.get(name)
        if existing is None or existing.get("content") != content:
            changed[name] = content
        else:
            print(f"push_badges_to_gist: up-to-date: {name}")

    if not changed:
        print("push_badges_to_gist: all badges already up-to-date in gist — nothing to push.")
        return 0

    print(f"push_badges_to_gist: pushing {len(changed)} file(s): {', '.join(sorted(changed))}")
    if _push_gist(gist_id, token, changed):
        print("push_badges_to_gist: OK — gist updated.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
