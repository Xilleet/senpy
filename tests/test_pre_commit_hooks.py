"""Characterization test for the published pre-commit hook.

The ``.pre-commit-hooks.yaml`` file at the repo root is the *published*
pre-commit hook that third-party Ren'Py projects consume via:

    repos:
      - repo: https://github.com/Xilleet/senpy
        rev: <tag>
        hooks:
          - id: senpy

When pre-commit runs the hook, it executes ``entry: <command>`` and fails
the commit if the command exits non-zero.

Contract this test guards
-------------------------
The hook's ``entry`` MUST use a CLI invocation that fails (exit != 0)
when the analyzed project has ERROR-severity diagnostics — even when
those diagnostics are NOT auto-fixable. Otherwise the pre-commit gate
silently lets broken code through, defeating the entire point of wiring
senpy into pre-commit.

Historical bug (P0-1)
---------------------
``entry: senpy --check`` only exits 1 when ``fixable_count > 0`` (see
``runner._handle_check_mode``). A project with 50 unfixable ERRORs
passes the gate silently. The fix is to use ``--errors-only``, which
filters output to ERRORs and computes exit code via
``renderers._exit_code`` (1 if error_count > 0, unless ``--exit-zero``).

Parsing note
------------
``.pre-commit-hooks.yaml`` is parsed WITHOUT PyYAML. The file is a flat
``key: value`` mapping after the ``---`` document marker (no nesting,
no quoting, no multiline scalars) — a regex extractor is sufficient
and avoids adding ``pyyaml`` to runtime dependencies just for one
test. The extractor only reads the fields the test guards (``id``,
``entry``); if future hook fields need validation, extend the extractor
or revisit whether ``pyyaml`` belongs in dev dependencies.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HOOKS_FILE = _REPO_ROOT / ".pre-commit-hooks.yaml"

# Match a top-level YAML key after the `---` document marker.
# Pre-commit hook files are flat mappings (no nesting at top level),
# so a line-anchored regex is sufficient and avoids a PyYAML dependency.
# `key` is captured as `[A-Za-z_][A-Za-z0-9_]*` (valid YAML identifier);
# `value` is everything after `: ` up to end-of-line (stripped).
# Inline comments (` # ...`) are NOT stripped because the hook file does
# not use them on the data lines we care about (id, entry, language...).
_RE_KV = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*?)\s*$", re.MULTILINE)


def _load_hooks_yaml() -> dict:
    """Parse .pre-commit-hooks.yaml into a flat dict (top-level keys only).

    The pre-commit hook spec uses a flat mapping — no nested keys, no
    flow sequences at top level (``types: [file]`` is the only flow
    style, and we don't guard on it). A regex extractor over the
    post-``---`` body is sufficient and avoids a runtime dependency
    on PyYAML.

    Raises AssertionError with a helpful message if the file is missing
    or empty — both are project-structure regressions.
    """
    assert _HOOKS_FILE.exists(), (
        ".pre-commit-hooks.yaml missing — this file is the published pre-commit "
        "hook that third-party Ren'Py projects consume. See Senpy docs."
    )
    text = _HOOKS_FILE.read_text(encoding="utf-8")
    # Strip everything up to and including the `---` document marker so
    # that commented-out YAML examples in the file header (which also
    # use `key: value` syntax) don't pollute the parsed fields.
    marker = text.find("\n---\n")
    if marker != -1:
        body = text[marker + len("\n---\n") :]
    else:
        # No document marker — parse the whole file (defensive; the
        # current file always has the marker, but this keeps the parser
        # robust if it's ever removed).
        body = text

    data: dict[str, str] = {}
    for m in _RE_KV.finditer(body):
        key, value = m.group(1), m.group(2)
        # Last-write-wins on duplicate keys (YAML semantics for flat
        # mappings reject duplicates, but we don't enforce that —
        # pre-commit's own validator does).
        data[key] = value
    assert data, (
        ".pre-commit-hooks.yaml parsed to an empty dict — the file is either "
        "empty or has no top-level key:value lines after the `---` marker."
    )
    return data


def _parse_entry_tokens(entry: str) -> list[str]:
    """Split a pre-commit ``entry`` string into argv tokens.

    Pre-commit does shell-like splitting on ``entry``; for senpy's
    documented invocation the entry is a flat ``senpy <flag>`` pair
    with no quoting, so a simple ``.split()`` is sufficient and avoids
    pulling in shlex (which would also handle edge cases senpy doesn't
    support).
    """
    return entry.split()


class TestPreCommitHookEntry:
    """Verify the published pre-commit hook fails on ERROR diagnostics."""

    def test_hooks_file_exists_and_has_senpy_id(self):
        """Sanity: the file declares a hook with id ``senpy``."""
        data = _load_hooks_yaml()
        assert (
            data.get("id") == "senpy"
        ), f".pre-commit-hooks.yaml must declare id: senpy, got {data.get('id')!r}."

    def test_entry_is_not_check_mode(self):
        """``--check`` only fails on fixable issues, not on unfixable ERRORs.

        This is the regression guard for the historical P0-1 bug where
        ``entry: senpy --check`` silently passed projects with 50
        unfixable ERROR diagnostics through the pre-commit gate.
        """
        data = _load_hooks_yaml()
        entry = data.get("entry", "")
        assert entry, ".pre-commit-hooks.yaml must have a non-empty 'entry' field."
        tokens = _parse_entry_tokens(entry)

        # The entry must NOT use --check: it only fails when there are
        # fixable issues (fixable_count > 0), letting unfixable ERRORs
        # through silently.
        assert "--check" not in tokens, (
            ".pre-commit-hooks.yaml entry uses '--check', which only exits 1 when "
            "fixable_count > 0. Projects with unfixable ERROR diagnostics pass the "
            "pre-commit gate silently. Use '--errors-only' instead — it filters "
            "output to ERRORs and exits 1 when error_count > 0 (unless --exit-zero)."
        )

    def test_entry_fails_on_errors(self):
        """The entry MUST use a flag whose exit code reflects ERROR count.

        ``--errors-only`` filters diagnostics to ERROR severity and the
        renderer's ``_exit_code`` returns 1 when error_count > 0 (unless
        ``--exit-zero`` is also passed, which it is not here).
        """
        data = _load_hooks_yaml()
        entry = data.get("entry", "")
        tokens = _parse_entry_tokens(entry)

        # The entry MUST include --errors-only (the only documented CLI
        # flag that both filters to ERRORs AND fails on them).
        assert "--errors-only" in tokens, (
            ".pre-commit-hooks.yaml entry must include '--errors-only' so the hook "
            "fails (exit 1) when the analyzed project has ERROR-severity diagnostics. "
            f"Current entry: {entry!r}."
        )

    def test_entry_does_not_silence_errors_with_exit_zero(self):
        """``--exit-zero`` would defeat the gate — must not be present."""
        data = _load_hooks_yaml()
        entry = data.get("entry", "")
        tokens = _parse_entry_tokens(entry)
        assert "--exit-zero" not in tokens, (
            ".pre-commit-hooks.yaml entry must NOT include '--exit-zero': that flag "
            "forces exit 0 even with ERRORs, defeating the pre-commit gate."
        )

    def test_entry_invokes_senpy(self):
        """Sanity: entry starts with the senpy executable."""
        data = _load_hooks_yaml()
        entry = data.get("entry", "")
        tokens = _parse_entry_tokens(entry)
        assert tokens, ".pre-commit-hooks.yaml entry must have at least one token."
        assert (
            tokens[0] == "senpy"
        ), f".pre-commit-hooks.yaml entry must invoke 'senpy', got {tokens[0]!r}."

    def test_entry_does_not_use_fix(self):
        """``--fix`` would mutate files — the hook is documented as non-mutating."""
        data = _load_hooks_yaml()
        entry = data.get("entry", "")
        tokens = _parse_entry_tokens(entry)
        assert "--fix" not in tokens, (
            ".pre-commit-hooks.yaml entry must NOT use '--fix': the hook is "
            "documented as non-mutating (see file header comment). A --fix hook "
            "would also create an infinite loop with ruff-format on Windows "
            "(CRLF <-> LF via git autocrlf)."
        )
