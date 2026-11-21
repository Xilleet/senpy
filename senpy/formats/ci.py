from __future__ import annotations

import os
import shlex

from senpy.__version__ import __version__ as _SENPY_VERSION

# GitHub Actions workflow template for Senpy code scanning.
#
# The template uses ``string.Template`` substitution (``$var``) rather than
# ``str.format`` (``{var}``) — this is deliberate. ``str.format`` would
# break on any literal ``{}`` in the YAML (e.g. GitHub Actions expressions
# like ``${{ github.event_name }}`` if we ever add a conditional or matrix).
# ``string.Template`` only interprets ``$identifier`` and ``${identifier}``,
# leaving ``{}`` untouched.
#
# Substitution variables:
#   $scan_target   — the path inside the repo to scan (e.g. ``game/`` or ``.``).
#                    Always passed through ``shlex.quote`` before substitution
#                    so paths with spaces (``My Games/foo``) don't break
#                    the shell command.
#   $senpy_pin     — the installed Senpy version (e.g. ``0.9.2``), pinned in
#                    the workflow so CI does not silently pick up new rules
#                    on every ``pip install --upgrade``. Without the pin,
#                    two CI runs a day apart could produce different SARIF
#                    outputs and different rule sets, breaking snapshot
#                    diffing.
WORKFLOW_TEMPLATE = """name: Senpy Code Scanning

on:
  push:
    branches: [ "main", "master" ]
  pull_request:
    branches: [ "main", "master" ]
  workflow_dispatch:

permissions:
  contents: read
  security-events: write

jobs:
  senpy-scan:
    name: Senpy Semantic Lint
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install Senpy (pinned)
        run: pip install senpy-linter==$senpy_pin

      - name: Run Senpy Analysis (SARIF report)
        run: senpy $scan_target --format sarif --output-file senpy.sarif
        continue-on-error: true

      - name: Upload SARIF report to GitHub Code Scanning
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: senpy.sarif
          category: senpy

      - name: Gate — fail CI on ERROR-severity diagnostics
        run: senpy $scan_target --errors-only
"""


def find_repo_root(start_path: str) -> str:
    """Determines the repository root by the presence of .git or the location of the game/ folder."""
    abs_path = os.path.abspath(start_path)
    curr = abs_path
    while curr and os.path.dirname(curr) != curr:
        if os.path.exists(os.path.join(curr, ".git")):
            return curr
        curr = os.path.dirname(curr)

    if os.path.basename(abs_path).lower() == "game":
        return os.path.dirname(abs_path)
    return abs_path


def init_ci_workflow(target_path: str, *, force: bool = False) -> tuple[str, bool]:
    """Create or update the ``.github/workflows/senpy.yml`` file.

    Args:
        target_path: Path the user wants to scan. Used to determine both
            the repo root (where ``.github/workflows/`` lives) AND the
            scan target inside the workflow. Previously the ``target_path``
            argument was only consulted for repo-root detection and the
            scan target was hard-derived from ``game/`` presence — a
            monorepo with ``path/to/my/game`` would generate a workflow
            that scanned ``.`` (the whole repo, including unrelated
            ``.rpy`` files from other subprojects).

            The scan target is now the repo-relative form of
            ``target_path``: if ``target_path`` points at a ``game/``
            directory, the workflow scans ``game/``; if it points at a
            subdirectory, the workflow scans that subdirectory; if it
            points at the repo root, the workflow scans ``.``.
        force: If ``True``, overwrite an existing ``senpy.yml`` without
            prompting. If ``False`` (default) and the file already exists,
            return early with ``was_created=False`` and do NOT overwrite —
            the user's manual edits to the workflow (extra steps, custom
            matrix, etc.) are preserved. The caller is expected to surface
            a WARNING to the user in this case.

    Returns:
        ``(file_path, was_created)`` where ``was_created`` is ``True`` if
        the file was newly written and ``False`` if it already existed
        (and was left untouched unless ``force=True``).

    Raises:
        OSError: If the ``.github/workflows/`` directory cannot be created
            (read-only filesystem, ``.github`` is a file instead of a
            directory, etc.). Previously these errors propagated as raw
            tracebacks; now the caller is expected to catch ``OSError``
            and surface a clean message (same pattern as
            ``CacheManager.save_manifest``).
    """
    repo_root = find_repo_root(target_path)
    workflows_dir = os.path.join(repo_root, ".github", "workflows")
    os.makedirs(workflows_dir, exist_ok=True)

    workflow_file = os.path.join(workflows_dir, "senpy.yml")

    # Do NOT silently overwrite an existing workflow. The user may
    # have hand-edited it (added matrix, env vars, extra steps). Only
    # write if the file is absent OR ``force=True`` was passed.
    if os.path.exists(workflow_file) and not force:
        return workflow_file, False

    # Derive scan_target from target_path (not just from repo-root
    # game/ presence). The scan target is the repo-relative form of
    # target_path — if target_path IS the repo root, scan ``.``; if it's
    # a subdirectory, scan that subdirectory.
    target_abs = os.path.abspath(target_path)
    try:
        rel_target = os.path.relpath(target_abs, repo_root)
    except ValueError:
        # Windows cross-drive relpath — fall back to the absolute path.
        # shlex.quote will neutralise spaces but not drive letters, so this
        # is a best-effort fallback for an unusual setup.
        rel_target = target_abs
    # Normalise: if target_path is the repo root, rel_target becomes "."
    # (which is what the workflow expects). Replace backslashes with
    # forward slashes for cross-platform YAML.
    scan_target = rel_target.replace("\\", "/") if rel_target != "." else "."
    # shlex.quote the scan target so paths with spaces
    # (``My Games/foo``) do not break the shell command in the workflow.
    # ``shlex.quote(".")`` returns ``"."`` (no quotes needed for ``.``),
    # and ``shlex.quote("game/")`` returns ``"game/"`` — both safe.
    scan_target_quoted = shlex.quote(scan_target)

    # Pin the Senpy version in the workflow so CI does not
    # silently pick up new rules on every ``pip install --upgrade``.
    # Two CI runs a day apart (with ~2 releases/day) would produce
    # different SARIF outputs and different rule sets, breaking snapshot
    # diffing and making MR annotations churn.
    senpy_pin = _SENPY_VERSION

    # Use ``string.Template`` instead of ``str.format`` so that any
    # future ``${{ ... }}`` GitHub Actions expressions in the template
    # are not interpreted as ``str.format`` placeholders.
    from string import Template

    content = Template(WORKFLOW_TEMPLATE).safe_substitute(
        scan_target=scan_target_quoted,
        senpy_pin=senpy_pin,
    )

    with open(workflow_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)

    return workflow_file, True
