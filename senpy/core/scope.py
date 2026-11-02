from __future__ import annotations

from enum import Enum, auto


class ScopeType(Enum):
    GLOBAL = auto()  # Global variables (default, define, built-in)
    LABEL = auto()  # Story labels (label arguments)
    SCREEN = auto()  # Screens (screen arguments, local Python variables)
    BLOCK = auto()  # Code blocks (init python, loops, menu)


class Scope:
    """Represents a single scope in the code."""

    def __init__(self, scope_type: ScopeType, name: str = "", indent: int = 0):
        self.scope_type = scope_type
        self.name = name
        self.indent = indent
        self.symbols: set[str] = set()
        self.constants: set[str] = set()
        self.uninitialized: dict[str, tuple[str, str]] = {}


class ScopeStack:
    """Scope stack. Manages transitions between screens, labels, and blocks."""

    def __init__(self, builtins: set[str]):
        global_scope = Scope(ScopeType.GLOBAL, "global", -1)
        global_scope.symbols.update(builtins)
        self.scopes: list[Scope] = [global_scope]

    @property
    def current(self) -> Scope:
        return self.scopes[-1]

    @property
    def global_scope(self) -> Scope:
        return self.scopes[0]

    def push(self, scope_type: ScopeType, name: str, indent: int) -> None:
        self.scopes.append(Scope(scope_type, name, indent))

    def pop_to_indent(self, indent: int) -> None:
        while len(self.scopes) > 1 and self.scopes[-1].indent >= indent:
            self.scopes.pop()

    def add_symbol(self, var: str, is_constant: bool = False, is_global: bool = False) -> None:
        target_scope = self.global_scope if is_global else self.current
        target_scope.symbols.add(var)
        if is_constant:
            target_scope.constants.add(var)

    def is_declared(self, var: str) -> bool:
        return any(var in s.symbols for s in reversed(self.scopes))

    def is_constant(self, var: str) -> bool:
        return any(var in s.constants for s in reversed(self.scopes))

    def current_screen_name(self) -> str | None:
        for s in reversed(self.scopes):
            if s.scope_type == ScopeType.SCREEN:
                return s.name
        return None

    def get_local_symbols(self) -> set[str]:
        locals_set = set()
        for s in reversed(self.scopes):
            if s.scope_type == ScopeType.GLOBAL:
                break
            locals_set.update(s.symbols)
        return locals_set
