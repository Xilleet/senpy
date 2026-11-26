"""``MissingKind`` enum + ``MissingMetadata`` dataclass for MAYBE_SET tracking.

Replaces the prose-string metadata tuple ``(missing_desc, defined_desc, str(missing_line))``
that was built by ``flow._build_metadata`` and consumed by ``flow.check_cfg_interpolations``
and ``python_ast.check_cfg_condition``.

The old design used English substring checks (``"branch" in s or "condition" in s``)
to dispatch on the metadata kind — brittle (a choice named ``"Branch office"`` would
switch the message format) and duplicated across two consumer sites. The enum
makes the dispatch explicit and collapses the two consumer sites into a single
``format_maybe_set_reason(meta)`` helper.

The ``defined_desc`` field of the old tuple was built but never read — removed.
The ``"earlier"`` fallback (``info[2] if len(info) > 2 else "earlier"``) was dead
code (the tuple always had 3 elements) — removed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class MissingKind(Enum):
    """Why a variable is MAYBE_SET (defined in some branches, not all).

    The enum value drives the diagnostic message format via
    ``format_maybe_set_reason``. Adding a new kind requires:
      1. Add the enum member here.
      2. Add a branch in ``format_maybe_set_reason``.
      3. Emit it from ``flow._build_metadata``.
    """

    #: ``if`` block without ``else`` — the condition was False, so the
    #: body (where the var is set) never ran.
    CONDITION_FALSE_NO_ELSE = auto()

    #: ``if/elif/else`` — a specific branch (elif or else) was taken,
    #: and that branch doesn't define the var. ``branch_kind`` holds
    #: "elif" or "else" for the message.
    BRANCH_TAKEN = auto()

    #: ``if/elif/else`` — the missing branch couldn't be identified
    #: (e.g. all branches define the var except one that was pruned).
    #: Falls back to a generic "alternate branch" phrasing.
    ALTERNATE_BRANCH = auto()

    #: ``menu`` — a specific choice was taken, and that choice body
    #: doesn't define the var. ``choice_name`` holds the choice text.
    CHOICE_TAKEN = auto()

    #: ``menu`` — the missing choice couldn't be identified. Falls back
    #: to a generic "alternate choice" phrasing.
    ALTERNATE_CHOICE = auto()


@dataclass(slots=True, frozen=True)
class MissingMetadata:
    """Metadata about a MAYBE_SET variable.

    Replaces the old ``tuple[str, str, str]`` shape
    ``(missing_desc, defined_desc, str(missing_line))``. The ``defined_desc``
    field was built but never read by any consumer — removed. The
    ``missing_line`` is now an ``int`` (was stringified for tuple packing).

    Attributes:
        kind: dispatch tag for the message format.
        missing_line: 1-based line number of the missing branch/choice,
            or the block line for the no-else / alternate cases.
        branch_kind: "elif" or "else" — only set when ``kind == BRANCH_TAKEN``.
        choice_name: choice text — only set when ``kind == CHOICE_TAKEN``.
    """

    kind: MissingKind
    missing_line: int
    branch_kind: str | None = None
    choice_name: str | None = None


def format_maybe_set_reason(meta: MissingMetadata) -> str:
    """Format the "why this var is MAYBE_SET" reason for diagnostic messages.

    Single source of truth — both ``flow.check_cfg_interpolations`` and
    ``python_ast.check_cfg_condition`` call this instead of duplicating the
    prose-parsing logic.

    Returns the reason fragment that goes into:
        f"Variable '{var}' may be uninitialized (MAYBE_SET) if {reason} on line {line}."

    Examples:
        CONDITION_FALSE_NO_ELSE → "condition is False (no else branch)"
        BRANCH_TAKEN (elif)     → "elif branch was taken"
        ALTERNATE_BRANCH        → "alternate branch was taken"
        CHOICE_TAKEN ("Yes")    → "player took choice 'Yes'"
        ALTERNATE_CHOICE        → "player took choice 'alternate choice'"
    """
    match meta.kind:
        case MissingKind.CONDITION_FALSE_NO_ELSE:
            return "condition is False (no else branch)"
        case MissingKind.BRANCH_TAKEN:
            return f"{meta.branch_kind or 'elif'} branch was taken"
        case MissingKind.ALTERNATE_BRANCH:
            return "alternate branch was taken"
        case MissingKind.CHOICE_TAKEN:
            return f"player took choice '{meta.choice_name or 'alternate choice'}'"
        case MissingKind.ALTERNATE_CHOICE:
            return "player took choice 'alternate choice'"


__all__ = ["MissingKind", "MissingMetadata", "format_maybe_set_reason"]
