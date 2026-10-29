"""RPY901: Hard-coded dialogue without _() for translation.

This is an example Senpy plugin rule. It demonstrates:
- Rule base class + RuleMeta
- @register_rule decorator
- PLUGIN_API_VERSION declaration (must match Senpy's)

Rule: flags dialogue lines (starting with " or ') that are NOT wrapped in
_() for translation. Translators need _() to extract strings for localization.

Severity: WARNING (not breaking, but accessibility issue)
"""
from __future__ import annotations

from senpy.api import Diagnostic
from senpy.plugins import Rule, RuleContext, RuleMeta, register_rule

# SEC-P1: declare which Senpy plugin API version this plugin targets.
# If Senpy's PLUGIN_API_VERSION is incompatible, the plugin is skipped
# with a warning (not crashed).
PLUGIN_API_VERSION = "1.0"


@register_rule("RPY901")
class HardcodedDialogueRule(Rule):
    """Flags dialogue lines not wrapped in _() for translation."""

    meta = RuleMeta(
        code="RPY901",
        docs=(
            "Dialogue lines should be wrapped in _() for translation. "
            "Without _(), translators cannot extract the string for localization, "
            "and the text will be hardcoded in the source language."
        ),
        severity="WARNING",
        fixable=False,
        tags=["translations", "accessibility"],
    )

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        """Analyze ctx.lines and return Diagnostics for hardcoded dialogue.

        A line is "hardcoded dialogue" if:
            1. First non-whitespace char is " or ' (Ren'Py dialogue convention)
            2. The line does NOT start with _(" or _(' (translation wrapper)

        Examples:
            "Hello, world!"              → flagged (RPY901)
            _("Hello, world!")           → OK (translated)
            'Hi there'                   → flagged
            _('Hi there')                → OK
            $ x = "not dialogue"          → not checked (not dialogue line)
        """
        diags: list[Diagnostic] = []

        for line_idx, raw_line in enumerate(ctx.lines, start=1):
            stripped = raw_line.lstrip(" \t")
            if not stripped:
                continue

            # Check if it's a dialogue line (starts with " or ')
            if stripped[0] not in ('"', "'"):
                continue

            # Check if wrapped in _() — pattern: _("...") or _('...')
            # (after optional leading whitespace)
            if stripped.startswith('_("') or stripped.startswith("_('"):
                continue  # already translated

            # Flag it
            diags.append(Diagnostic(
                file_path=ctx.file_path,
                line_number=line_idx,
                line_content=raw_line.rstrip("\n\r"),
                code="RPY901",
                message=(
                    f"Hard-coded dialogue without _() for translation. "
                    f"Wrap in _() so translators can extract this string: "
                    f"_({stripped.rstrip()})"
                ),
                severity="WARNING",
            ))

        return diags
