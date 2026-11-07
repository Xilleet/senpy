from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from senpy.core.signature import SignatureInfo


@dataclass(slots=True)
class VariableSymbol:
    """Represents a variable (default) or a constant (define) in the project."""

    name: str
    file_path: str
    line_number: int
    code_line: str
    type_name: str | None = None
    is_constant: bool = False  # True if define, False if default
    is_character: bool = False  # True if this is Character(...) or DynamicCharacter(...)


@dataclass(slots=True)
class LabelSymbol:
    """Represents a story label (label)."""

    name: str
    file_path: str
    line_number: int
    code_line: str
    signature: SignatureInfo | None = None
    has_return: bool = False
    outgoing_jumps: set[str] = field(default_factory=set)
    jump_sources: list[tuple[str, int]] = field(default_factory=list)
    # Name of the next label in the same file that this label falls
    # through to, when its body does not terminate with ``return``,
    # ``jump``, ``call`` (with ``from``), ``renpy.quit()``, or
    # ``renpy.full_restart()``. ``None`` means no fall-through edge
    # (either the label terminates or there is no next label in the
    # same file). Used by RPY309 reachability to model the implicit
    # fall-through edge between adjacent labels in a file.
    fall_through_to: str | None = None


@dataclass(slots=True)
class ScreenSymbol:
    """Represents a UI screen (screen)."""

    name: str
    file_path: str
    line_number: int
    signature: SignatureInfo | None = None


@dataclass(slots=True)
class ImageSymbol:
    """Represents a sprite or background declaration (image / layeredimage)."""

    name: str
    file_path: str
    line_number: int
    body: str
    is_layered: bool = False
    attributes: set[str] = field(default_factory=set)
    # Optional on-disk path extracted from `image name = "path"` or
    # `image name = Transform("path", ...)` declarations. Filled by the
    # analyzer at parse time so hover does not have to re-read the source
    # file per request. None for layeredimage or image built from a Python
    # expression without a string literal.
    image_path: str | None = None


@dataclass(slots=True)
class TransformSymbol:
    """Represents an ATL transform (transform).

    The signature field (parameters declared in `transform name(a, b):`)
    was added in 0.7.6 to support RPY706 (unused transform parameter).
    Older code that constructs TransformSymbol without signature continues
    to work — the default is None, which means "no params declared".
    """

    name: str
    file_path: str
    line_number: int
    code_line: str
    signature: SignatureInfo | None = None
