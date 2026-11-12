#!/usr/bin/env python3
"""update_renpy_api.py — update pinned Ren'Py API docs source + regenerate JSON.

Mirrors the unrpyc pin pattern (scripts/update_unrpyc_pin.py):
  - A YAML config pins the source (Ren'Py version + git ref + SHA256 of each RST file).
  - This script downloads from the pinned ref, verifies hashes, and regenerates
    the JSON API docs when the source has changed.
  - Defence-in-depth: SHA256 verification catches corrupted/partial downloads
    and unintended source changes.

Usage:
    python scripts/update_renpy_api.py                  # check + update if changed
    python scripts/update_renpy_api.py --check          # verify hashes only (no write)
    python scripts/update_renpy_api.py --version 8.5.4  # set version label + update
    python scripts/update_renpy_api.py --force          # regenerate even if unchanged

Requirements:
    pip install pyyaml  (maintainer-only dependency, not in runtime requirements)

Workflow:
    1. Reads senpy/domain/data/renpy_api_source.yaml for pinned source_ref + file_hashes.
    2. Downloads all RST/RPY files from the pinned ref.
    3. Computes SHA256 of each downloaded file.
    4. Compares with YAML hashes:
       - If all match: "up to date", no regeneration needed (unless --force).
       - If any differ: regenerates JSON via fetch_renpy_docs.py, updates YAML hashes.
    5. Writes updated YAML + JSON.

After running:
    git add senpy/domain/data/renpy_api_source.yaml senpy/domain/data/renpy_api_generated.json
    git commit -m "update renpy api docs to <version>"
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    print("[ERROR] PyYAML not installed. Run: pip install pyyaml")
    sys.exit(1)

REPO_ROOT = Path(__file__).parent.parent
YAML_PATH = REPO_ROOT / "senpy" / "domain" / "data" / "renpy_api_source.yaml"
JSON_PATH = REPO_ROOT / "senpy" / "domain" / "data" / "renpy_api_generated.json"
FETCH_SCRIPT = REPO_ROOT / "scripts" / "fetch_renpy_docs.py"

# Same file lists as fetch_renpy_docs.py — duplicated here so this script
# can download them without importing the fetch script (which has heavy
# parsing deps). If the lists change in fetch_renpy_docs.py, update here too.
RST_FILES = [
    "config.rst",
    "gui.rst",
    "build.rst",
    "transforms.rst",
    "transitions.rst",
    "style_properties.rst",
    "transform_properties.rst",
    "statement_equivalents.rst",
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
RPY_SOURCE_FILES = [
    "00action_control.rpy",
    "00action_data.rpy",
    "00action_file.rpy",
    "00action_menu.rpy",
    "00action_audio.rpy",
    "00action_other.rpy",
]


def load_yaml() -> dict:
    """Load the source pin config."""
    with YAML_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_yaml(data: dict) -> None:
    """Write the source pin config."""
    with YAML_PATH.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=True, allow_unicode=True)


def download_file(url: str) -> bytes | None:
    """Download a file from URL, return raw bytes or None on failure."""
    req = urllib.request.Request(url, headers={"User-Agent": "Senpy-update-script"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_all_hashes(source_ref: str, yaml_config: dict) -> dict[str, str]:
    """Download all RST/RPY files from the pinned ref, return {filename: sha256}."""
    rst_base = yaml_config["source_urls"]["rst_base"].format(ref=source_ref)
    common_base = yaml_config["source_urls"]["common_base"].format(ref=source_ref)

    hashes: dict[str, str] = {}
    all_files = [(rst_base, f) for f in RST_FILES] + [(common_base, f) for f in RPY_SOURCE_FILES]

    for base_url, fname in all_files:
        url = base_url + fname
        print(f"  Fetching {fname}...", end=" ")
        data = download_file(url)
        if data is None:
            print("SKIP")
            continue
        sha = compute_sha256(data)
        hashes[fname] = sha
        print(f"{len(data)} bytes, sha256={sha[:12]}...")

    return hashes


def compare_hashes(
    old: dict[str, str], new: dict[str, str]
) -> tuple[list[str], list[str], list[str]]:
    """Compare old vs new hashes. Returns (changed, new_files, removed_files)."""
    changed = [f for f in new if f in old and new[f] != old[f]]
    new_files = [f for f in new if f not in old]
    removed = [f for f in old if f not in new]
    return changed, new_files, removed


def regenerate_json(version: str) -> bool:
    """Run fetch_renpy_docs.py to regenerate the JSON from the pinned source."""
    print(f"\n[*] Regenerating JSON via {FETCH_SCRIPT.name}...")
    result = subprocess.run(
        [sys.executable, str(FETCH_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print(f"[ERROR] fetch_renpy_docs.py failed (exit {result.returncode}):")
        print(result.stderr[-500:])
        return False
    print(f"[OK] JSON regenerated (version {version})")
    return True


def cmd_check() -> int:
    """Verify current file hashes match YAML."""
    config = load_yaml()
    ref = config["source_ref"]
    print(f"[*] Checking source ref: {ref}")
    print(f"[*] Pinned version: {config['renpy_version']}")
    print()

    new_hashes = fetch_all_hashes(ref, config)
    old_hashes = config.get("file_hashes", {})

    changed, new_files, removed = compare_hashes(old_hashes, new_hashes)

    if not changed and not new_files and not removed:
        print(f"\n[OK] All {len(new_hashes)} files match pinned hashes.")
        print(f"    Source: {ref}, version: {config['renpy_version']}")
        return 0

    if changed:
        print(f"\n[CHANGED] {len(changed)} files differ from pinned hashes:")
        for f in changed:
            print(f"  {f}: {old_hashes[f][:12]}... → {new_hashes[f][:12]}...")
    if new_files:
        print(f"\n[NEW] {len(new_files)} files not in YAML:")
        for f in new_files:
            print(f"  {f}: {new_hashes[f][:12]}...")
    if removed:
        print(f"\n[REMOVED] {len(removed)} files in YAML but not in source:")
        for f in removed:
            print(f"  {f}")

    print("\n[ACTION] Run: python scripts/update_renpy_api.py --update")
    return 1


def cmd_update(force: bool, new_version: str | None) -> int:
    """Download from pinned ref, compare hashes, regenerate if changed."""
    config = load_yaml()

    if new_version:
        config["renpy_version"] = new_version
        print(f"[*] Version label updated to: {new_version}")

    ref = config["source_ref"]
    print(f"[*] Source ref: {ref}")
    print(f"[*] Pinned version: {config['renpy_version']}")
    print()

    new_hashes = fetch_all_hashes(ref, config)
    old_hashes = config.get("file_hashes", {})

    changed, new_files, removed = compare_hashes(old_hashes, new_hashes)

    if not force and not changed and not new_files and not removed:
        print(f"\n[OK] All {len(new_hashes)} files match. Nothing to update.")
        print("    Use --force to regenerate anyway.")
        return 0

    if force:
        print("\n[*] --force: regenerating JSON regardless of hash match.")
    else:
        if changed:
            print(f"\n[CHANGED] {len(changed)} files differ — regenerating JSON.")
        if new_files:
            print(f"[NEW] {len(new_files)} new files — regenerating JSON.")

    # Regenerate JSON
    if not regenerate_json(config["renpy_version"]):
        return 1

    # Update YAML with new hashes
    from datetime import UTC, datetime

    config["file_hashes"] = new_hashes
    config["generated_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_yaml(config)
    print(f"[OK] YAML updated: {len(new_hashes)} file hashes")

    print(f"\n[DONE] Ren'Py API docs updated to version {config['renpy_version']}.")
    print(
        "   Commit: git add senpy/domain/data/renpy_api_source.yaml senpy/domain/data/renpy_api_generated.json"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update pinned Ren'Py API docs source + regenerate JSON."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify current file hashes match YAML. No writes.",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Download from pinned ref, regenerate JSON if changed, update YAML.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="With --update: regenerate JSON even if hashes match.",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Set the Ren'Py version label (e.g., --version 8.5.4).",
    )
    args = parser.parse_args()

    if args.check:
        return cmd_check()

    if args.update or args.version:
        return cmd_update(force=args.force, new_version=args.version)

    # Default: check
    return cmd_check()


if __name__ == "__main__":
    sys.exit(main())
