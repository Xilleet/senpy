#!/usr/bin/env python3
"""bump_version.py — Senpy version bumper.

The version is stored in a single place: senpy/__version__.py.
All other files (constants.py, server.py, pyproject.toml) import or
read it dynamically. Only package.json (for the VS Code marketplace)
still requires an explicit version — we update it here.

Hardcoded version mentions (4 files that reference the version as a
plain string, not via import) are also updated here:
  - .pre-commit-hooks.yaml         (rev: vX.Y.Z in comment)
  - .github/release-header.md      (Open VSX badge URL)
  - docs/install.md                (comment with version)
  - docs/index.md                  (Open VSX badge URL)

Usage:
    python bump_version.py             # interactive menu
    python bump_version.py patch       # 0.4.7 -> 0.4.8
    python bump_version.py minor       # 0.4.7 -> 0.5.0
    python bump_version.py major       # 0.4.7 -> 1.0.0
    python bump_version.py 1.2.3       # explicit version
"""

from __future__ import annotations

import json
import os
import re
import sys

VERSION_PY_PATH = os.path.join("senpy", "__version__.py")
PACKAGE_JSON_PATH = os.path.join("senpy-vscode", "package.json")

# Hardcoded version mentions — files that reference the version as a plain
# string (not via import). Each entry: (file_path, regex_pattern, replacement_template).
# The regex must capture the current version (X.Y.Z or vX.Y.Z) so we can
# replace only the version token, preserving surrounding text (URLs, comments).
# Patterns use \d+\.\d+\.\d+ to match ANY semver — the script replaces the
# FIRST occurrence per file. If a file has multiple version mentions, extend
# the per-file logic below.
HARDCODED_VERSION_FILES: list[tuple[str, str]] = [
    # .pre-commit-hooks.yaml: "#         rev: 0.8.4   # Use the latest tag"
    # made `v` optional — the file uses `rev: 0.8.4` (no `v` prefix),
    # while README.md uses `rev: v0.8.4` (with `v`). Both should match.
    (".pre-commit-hooks.yaml", r"(rev:\s*)v?\d+\.\d+\.\d+"),
    # .github/release-header.md: "Open%20VSX-0.7.7-success"
    (".github/release-header.md", r"(Open%20VSX-)\d+\.\d+\.\d+"),
    # docs/install.md: "# senpy 0.7.7"
    ("docs/install.md", r"(senpy\s+)\d+\.\d+\.\d+"),
    # docs/index.md: "Open%20VSX-0.7.7-success"
    ("docs/index.md", r"(Open%20VSX-)\d+\.\d+\.\d+"),
]


def select_target_version(major: int, minor: int, patch: int) -> str | None:
    patch_ver = f"{major}.{minor}.{patch + 1}"
    minor_ver = f"{major}.{minor + 1}.0"
    major_ver = f"{major + 1}.0.0"

    # If a command-line argument was passed (e.g. `python bump_version.py minor`)
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip().lower()
        if arg in ("patch", "p", "1"):
            return patch_ver
        if arg in ("minor", "m", "2"):
            return minor_ver
        if arg in ("major", "3"):
            return major_ver
        if re.match(r"^\d+\.\d+\.\d+$", arg):
            return arg
        print(f"[!] Unknown argument: '{arg}'. Use: patch, minor, major, or version X.Y.Z")
        return None

    # Interactive menu
    print("=" * 50)
    print(f"[*] Current version: {major}.{minor}.{patch}")
    print("=" * 50)
    print(
        f"  [1] Patch: {patch_ver}  (intended for bugfixes, hotfixes, and small regex tweaks without architecture changes or major features)"
    )
    print(
        f"  [2] Minor: {minor_ver}  (released when the project gains significant new capabilities, semantic extensions, or a new quality level)"
    )
    print(
        f"  [3] Major: {major_ver}  (first stable production-ready build, when the API is stabilized and tested on dozens of real visual novels)"
    )
    print("  [c] Enter a custom version manually")
    print("  [q] Cancel")
    print("=" * 50)

    choice = input("[?] Choose [1/2/3/c/q] (default 2): ").strip().lower()

    if choice in ("q", "quit", "exit"):
        return None
    if choice in ("1", "patch"):
        return patch_ver
    if choice in ("", "2", "minor"):
        return minor_ver
    if choice in ("3", "major"):
        return major_ver
    if choice in ("c", "custom"):
        custom = input("[?] Enter version (e.g. 0.3.0): ").strip()
        if re.match(r"^\d+\.\d+\.\d+$", custom):
            return custom
        print("[!] Invalid version format.")
        return None

    return minor_ver


def read_current_version() -> tuple[int, int, int]:
    """Read the current version from senpy/__version__.py."""
    if not os.path.exists(VERSION_PY_PATH):
        print(f"[ERROR] {VERSION_PY_PATH} not found!")
        sys.exit(1)

    with open(VERSION_PY_PATH, encoding="utf-8") as f:
        content = f.read()

    # Look for __version__ = "X.Y.Z"
    match = re.search(r'__version__\s*=\s*["\'](\d+)\.(\d+)\.(\d+)["\']', content)
    if not match:
        print("[!] __version__ line not found in senpy/__version__.py.")
        sys.exit(1)

    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def write_version_to_pyfile(next_ver: str) -> None:
    """Update senpy/__version__.py with the new version + MAJOR/MINOR/PATCH."""
    major, minor, patch = (int(x) for x in next_ver.split("."))
    new_content = f'''"""Single source of truth for the Senpy version.

All other locations (pyproject.toml, constants.SENPY_VERSION, server.py,
senpy-vscode/package.json) must be synchronized with this file via
`python bump_version.py`.

Change the version only here (or via `bump_version.py`, which will
update it here and everywhere else automatically).
"""
from __future__ import annotations

__version__ = "{next_ver}"

# Convenient aliases for use in different parts of the codebase
# (e.g. the LSP server often needs "v0.4.7" with the prefix).
VERSION_WITH_PREFIX = f"v{{__version__}}"

# Semver parsing for complex checks (e.g. cache invalidation by major.minor)
MAJOR: int = {major}
MINOR: int = {minor}
PATCH: int = {patch}

__all__ = ["__version__", "VERSION_WITH_PREFIX", "MAJOR", "MINOR", "PATCH"]
'''
    with open(VERSION_PY_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"[+] senpy/__version__.py: -> {next_ver}")


def write_version_to_package_json(next_ver: str) -> None:
    """Update senpy-vscode/package.json — the VS Code marketplace requires an explicit version."""
    if not os.path.exists(PACKAGE_JSON_PATH):
        print(f"[!] Warning: {PACKAGE_JSON_PATH} not found, skipping.")
        return
    try:
        with open(PACKAGE_JSON_PATH, encoding="utf-8") as f:
            pkg_data = json.load(f)
        old_ver = pkg_data.get("version", "?")
        pkg_data["version"] = next_ver
        with open(PACKAGE_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(pkg_data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"[+] senpy-vscode/package.json: {old_ver} -> {next_ver}")
    except (OSError, json.JSONDecodeError, KeyError) as e:
        print(f"[!] Warning: failed to sync package.json: {e}")


def write_version_to_hardcoded_files(next_ver: str) -> None:
    """Update hardcoded version mentions in 4 files that can't import __version__.

    These files reference the version as a plain string (in comments, badge
    URLs, etc.) and are not dynamically updated. Without this function, they
    drift every release — e.g. ``.pre-commit-hooks.yaml`` was stuck at
    ``v0.7.5`` while the project moved to ``0.7.7``.
    """
    for file_path, pattern in HARDCODED_VERSION_FILES:
        if not os.path.exists(file_path):
            print(f"[!] Warning: {file_path} not found, skipping.")
            continue
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
            # Replace the FIRST version match in the file. All 4 files have
            # exactly one version mention; if a file ever gains more, extend
            # this with a per-file count or use re.sub with count=N.
            new_content, n = re.subn(pattern, rf"\g<1>{next_ver}", content, count=1)
            if n == 0:
                print(f"[!] Warning: no version pattern matched in {file_path}. Skipping.")
                continue
            if new_content == content:
                print(f"[=] {file_path}: already at {next_ver}")
                continue
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"[+] {file_path}: -> {next_ver}")
        except OSError as e:
            print(f"[!] Warning: failed to update {file_path}: {e}")


def bump_version():
    maj_n, min_n, pat_n = read_current_version()
    current_ver = f"{maj_n}.{min_n}.{pat_n}"

    next_ver = select_target_version(maj_n, min_n, pat_n)
    if not next_ver:
        print(f"[*] Version {current_ver} remains unchanged.\n")
        return

    print(f"\n[+] Bumping version: {current_ver} -> {next_ver}\n")

    # 1. Update senpy/__version__.py — the single source of truth
    write_version_to_pyfile(next_ver)

    # 2. Update senpy-vscode/package.json (marketplace requires explicit version)
    write_version_to_package_json(next_ver)

    # 3. Update hardcoded version mentions in 4 files (pre-commit-hooks,
    #    release-header, docs/install, docs/index). These can't import
    #    __version__ and used to drift every release.
    write_version_to_hardcoded_files(next_ver)

    # 4. Done. constants.py, server.py, pyproject.toml will pick up the version
    # automatically via import / dynamic = ["version"].
    print(f"\n[*] Success! Project updated to version {next_ver}.")
    print("    constants.py / server.py / pyproject.toml will pick it up automatically.\n")


if __name__ == "__main__":
    bump_version()
