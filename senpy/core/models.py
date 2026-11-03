from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from senpy.core.symbols import (
        ImageSymbol,
        LabelSymbol,
        ScreenSymbol,
        TransformSymbol,
        VariableSymbol,
    )


@dataclass(slots=True)
class Diagnostic:
    file_path: str
    line_number: int
    line_content: str
    code: str
    message: str
    severity: str | None = None
    col: int = 0
    end_col: int = 0
    fix_title: str | None = None
    fix_replacement: str | None = None
    fix_start_col: int | None = None
    fix_end_col: int | None = None


@dataclass(slots=True)
class AnalysisResult:
    diagnostics: list[Diagnostic]
    file_count: int
    total_lines: int
    fixed_count: int = 0
    fixable_count: int = 0


@dataclass(slots=True)
class FileScope:
    user_symbols: set[str] = field(default_factory=set)
    declared_symbols: set[str] = field(default_factory=set)
    defined_audio_map: dict[str, str] = field(default_factory=dict)
    registered_audio_channels: set[str] = field(default_factory=set)
    referenced_labels: set[str] = field(default_factory=set)

    # --- New clean object model ---
    variables: dict[str, VariableSymbol] = field(default_factory=dict)
    labels: dict[str, LabelSymbol] = field(default_factory=dict)
    screens: dict[str, ScreenSymbol] = field(default_factory=dict)
    images: dict[str, ImageSymbol] = field(default_factory=dict)
    transforms: dict[str, TransformSymbol] = field(default_factory=dict)

    jump_sources: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    screen_action_jumps: dict[str, set[str]] = field(default_factory=dict)
    used_screens: set[str] = field(default_factory=set)
    screen_uses: dict[str, set[str]] = field(default_factory=dict)


RULE_SEVERITY: dict[str, str] = {
    # 0xx: Syntax and formatting (critical for the parser)
    "RPY001": "ERROR",  # Tabs in indentation -> SyntaxError
    "RPY002": "ERROR",  # Curly/typographic quotes in code -> SyntaxError
    # 1xx: Variables, state and Python
    "RPY100": "ERROR",  # File does not decode as UTF-8 -> silently dropped from analysis
    "RPY101": "ERROR",  # Typo in [var] -> KeyError in dialogue
    "RPY102": "ERROR",  # += before default -> NameError on scene entry
    "RPY103": "ERROR",  # if var: without declaration -> NameError
    "RPY104": "WARNING",  # $ var = 1 without default -> breaks saves after a patch
    "RPY105": "ERROR",  # Mutation of a define constant -> breaks rollback
    "RPY106": "WARNING",  # Use of random/set during gameplay
    "RPY107": "HINT",  # Deprecated Ren'Py API (LiveComposite etc. work but are deprecated)
    "RPY108": "ERROR",  # Type conflict or incompatible += -> TypeError
    "RPY109": "ERROR",  # init python load order violation (call before declaration)
    # 2xx: Screens and UI
    "RPY201": "WARNING",  # Global mutation inside screen -> breaks UI prediction
    "RPY202": "WARNING",  # Variable in screen without default
    "RPY203": "WARNING",  # Button without action (dead UI element)
    "RPY204": "ERROR",  # Non-existent screen -> ScriptError
    "RPY205": "WARNING",  # for/while loops inside a screen (FPS drops)
    "RPY206": "ERROR",  # Direct function call in action with parentheses
    "RPY207": "ERROR",  # Parameter mismatch on screen call (use / call screen)
    "RPY208": "ERROR",  # Screen local variable leaks into global store (SetVariable instead of SetScreenVariable)
    # 3xx: Dialogue and story graph
    "RPY301": "ERROR",  # Unclosed dialogue tag {b}
    "RPY302": "ERROR",  # Jump to non-existent label -> ScriptError
    "RPY303": "HINT",  # Lone label without references (may be called dynamically)
    "RPY304": "ERROR",  # Invalid hex color
    "RPY305": "ERROR",  # Unescaped quotes in dialogue
    "RPY306": "WARNING",  # call chain does not guarantee return
    "RPY307": "ERROR",  # Duplicate label declaration -> ScriptError
    "RPY308": "WARNING",  # Label fallthrough without return/jump
    "RPY309": "WARNING",  # Story island / isolated scene cycle
    "RPY310": "ERROR",  # Argument mismatch on call label (TypeError)
    # 4xx: Story branches and conditions
    "RPY401": "WARNING",  # menu: branch: variable not declared in all branches
    "RPY402": "WARNING",  # Empty menu choice
    "RPY403": "WARNING",  # Always-false condition (dead code block)
    "RPY404": "WARNING",  # Reading a variable with MAYBE_SET status after a menu branch
    # 5xx: Assets and media
    "RPY501": "ERROR",  # Missing audio file on disk
    "RPY502": "WARNING",  # Sprite or pose not found in assets
    "RPY503": "HINT",  # Unused asset on disk (extra build weight)
    "RPY504": "HINT",  # Re-declaration/override of image (often intentional in mods)
    "RPY505": "WARNING",  # Non-existent audio channel or invalid modifier (loop on voice)
    # 6xx: Localization (tl/)
    "RPY601": "ERROR",  # [var] desync in translation -> KeyError
    "RPY602": "WARNING",  # {tag} desync in translation
    "RPY603": "WARNING",  # Empty translation string new ""
    # 7xx: Dead code (Dead Code Detection)
    "RPY701": "HINT",  # Unused define constant (dead code)
    "RPY702": "HINT",  # Unused transform (dead code)
    "RPY703": "HINT",  # Unused screen (dead code)
    "RPY704": "HINT",  # Unused default variable (dead code)
    "RPY705": "HINT",  # Unused screen parameter (dead code)
    "RPY706": "HINT",  # Unused transform parameter (dead code)
    "RPY707": "HINT",  # Unused audio channel registration (dead code)
}
