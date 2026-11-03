"""RPY902: TODO/FIXME/XXX/HACK comments left in .rpy files.

Example Senpy plugin rule. Demonstrates:
  - Subclassing `Rule` with `RuleMeta` (severity=HINT, tags=[productivity])
  - Line-by-line scan via `RuleContext.lines`
  - Case-insensitive keyword matching with word-boundary check
    (so "todolist" doesn't fire, but "# TODO:" does)
  - Returning `Diagnostic` objects with file_path + line_number + message

The rule fires on any comment line (Ren'Py comments start with `#`)
containing one of: TODO, FIXME, XXX, HACK (case-insensitive).

Severity: HINT — these are not bugs, just reminders. In --errors-only
mode they are suppressed. Use `--info` (or just run without --errors-only)
to see them.

Installation (development mode):
    cd examples/todo_comment_plugin
    pip install -e .
    senpy --trust-plugin todo-comment-plugin
    senpy path/to/game/

Verify:
    senpy rule list --format json | jq '.[] | select(.code == "RPY902")'
"""

from __future__ import annotations

import re

from senpy.api import Diagnostic
from senpy.plugins import Rule, RuleContext, RuleMeta, register_rule

# SEC-P1: declare which Senpy plugin API version this plugin targets.
# If Senpy's PLUGIN_API_VERSION is incompatible, the plugin is skipped
# with a warning (not crashed).
PLUGIN_API_VERSION = "1.0"

# Keywords that trigger RPY902. Case-insensitive match.
# We require a word boundary (or start of comment body) before the
# keyword so that "todolist" or "fixme-variable" don't fire.
#
# The regex matches: after `#` and optional whitespace, one of the
# keywords, followed by either `:`, ` ` (space), or end of line.
_TODO_RE = re.compile(
    r"#\s*\b(TODO|FIXME|XXX|HACK)\b\s*:?",
    re.IGNORECASE,
)


@register_rule("RPY902")
class TodoCommentRule(Rule):
    """Flags TODO/FIXME/XXX/HACK comments in .rpy files."""

    meta = RuleMeta(
        code="RPY902",
        docs=(
            "Detects TODO, FIXME, XXX, and HACK comments left in Ren'Py "
            "source files. These are not bugs, but they are reminders "
            "that something is unfinished. Use HINT severity so they "
            "don't clutter --errors-only output, but show up in normal "
            "and --info runs."
        ),
        severity="HINT",
        fixable=False,
        tags=["productivity", "dead-code"],
    )

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        """Scan ctx.lines for TODO/FIXME/XXX/HACK comments.

        A line is flagged if it matches `#\\s*\\b(TODO|FIXME|XXX|HACK)\\b`.
        The word-boundary check prevents false positives on identifiers
        like `todolist` or `fixme_var`.

        Examples:
            # TODO: implement this label             → flagged (RPY902)
            # FIXME: this crashes on rollback        → flagged (RPY902)
            # xxx: not safe                          → flagged (case-insensitive)
            # HACK: bypass renpy rollback            → flagged (RPY902)
            "TODO: this is dialogue, not a comment"  → not checked (not a comment)
            $ x = "todolist"                         → not checked (not a comment)
            # todolist — not the keyword             → not flagged (no word boundary)
        """
        diags: list[Diagnostic] = []

        for line_idx, raw_line in enumerate(ctx.lines, start=1):
            stripped = raw_line.strip()
            if not stripped.startswith("#"):
                continue

            match = _TODO_RE.search(raw_line)
            if match is None:
                continue

            keyword = match.group(1).upper()  # normalize to TODO/FIXME/XXX/HACK
            diags.append(
                Diagnostic(
                    file_path=ctx.file_path,
                    line_number=line_idx,
                    line_content=raw_line.rstrip("\n\r"),
                    code="RPY902",
                    message=(
                        f"{keyword} comment found. This is a reminder, not a bug. "
                        f"Resolve or remove the comment when done."
                    ),
                    severity="HINT",
                )
            )

        return diags
