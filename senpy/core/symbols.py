from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from senpy.core.signature import SignatureInfo


@dataclass(slots=True)
class VariableSymbol:
    """Представляет переменную (default) или константу (define) в проекте."""

    name: str
    file_path: str
    line_number: int
    code_line: str
    type_name: str | None = None
    is_constant: bool = False  # True если define, False если default
    is_character: bool = False  # True если это Character(...) или DynamicCharacter(...)


@dataclass(slots=True)
class LabelSymbol:
    """Представляет сюжетную метку (label)."""

    name: str
    file_path: str
    line_number: int
    code_line: str
    signature: SignatureInfo | None = None
    has_return: bool = False
    outgoing_jumps: set[str] = field(default_factory=set)
    jump_sources: list[tuple[str, int]] = field(default_factory=list)


@dataclass(slots=True)
class ScreenSymbol:
    """Представляет UI экран (screen)."""

    name: str
    file_path: str
    line_number: int
    signature: SignatureInfo | None = None


@dataclass(slots=True)
class ImageSymbol:
    """Представляет объявление спрайта или фона (image / layeredimage)."""

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
    """Представляет ATL-трансформацию (transform)."""

    name: str
    file_path: str
    line_number: int
    code_line: str
