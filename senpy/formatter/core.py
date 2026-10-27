"""Core formatter module: FormatContext, FormatConfig, Formatter class.

Architecture:
- FormatContext: per-line context (line_idx, raw, indent, scope, skip)
- FormatConfig: formatter configuration (Black-style: minimal options)
- Formatter: orchestrator, applies rules in order
- @register_rule: decorator for rule registration (ESLint-style)

Rule contract:
    @register_rule("FMT-XXX")
    def rule(contexts: list[FormatContext], config: FormatConfig) -> list[FormatContext]:
        # Pure function: mutate contexts in place, return same list
        ...
        return contexts

Rules are applied in registration order. Order matters:
1. FMT-INDENT (tab → spaces) — must be first, other rules rely on indent field
2. FMT-BLANK-LINES — collapse before strip
3. FMT-TRAILING-WS — strip trailing whitespace
4. FMT-EOF-NEWLINE — ensure final newline (must be last)
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # for future type imports


# =============================================================================
# Data classes
# =============================================================================


@dataclass
class FormatContext:
    """Per-line context for formatting.

    Attributes:
        line_idx: 0-based line index in original file
        raw: raw line text (including newline)
        indent: number of leading spaces (after tab expansion, computed in _build_contexts)
        scope: current scope — "top", "label", "screen", "menu", "init", "atl"
        scope_name: name of label/screen/transform if applicable
        skip: True if inside `# senpy: format off` block
    """

    line_idx: int
    raw: str
    indent: int
    scope: str
    scope_name: str | None
    skip: bool = False


@dataclass
class FormatConfig:
    """Formatter configuration. Minimal, Black-style.

    Most decisions are baked in (opinionated). Only truly tunable params here.
    """

    indent_size: int = 4
    max_blank_lines: int = 2
    skip_directive: str = "# senpy: format"


# =============================================================================
# Rule registry (ESLint-style)
# =============================================================================

RuleFn = Callable[[list["FormatContext"], "FormatConfig"], list["FormatContext"]]
_REGISTRY: list[tuple[str, RuleFn]] = []


def register_rule(name: str) -> Callable[[RuleFn], RuleFn]:
    """Decorator to register a formatter rule.

    Usage:
        @register_rule("FMT-INDENT")
        def normalize_indent(contexts, config):
            ...
            return contexts

    Rules are applied in registration order. Order matters — see module docstring.
    """

    def decorator(fn: RuleFn) -> RuleFn:
        _REGISTRY.append((name, fn))
        return fn

    return decorator


def get_registered_rules() -> list[tuple[str, RuleFn]]:
    """Returns list of (name, fn) pairs in registration order."""
    return list(_REGISTRY)


# =============================================================================
# Scope detection
# =============================================================================

# Precompiled regexes for scope detection (compiled once at import)
_RE_LABEL = re.compile(r"^label\s+(\w+)")
_RE_SCREEN = re.compile(r"^screen\s+(\w+)")
_RE_INIT = re.compile(r"^init\s+python")
_RE_MENU = re.compile(r"^menu\s*:?")
_RE_TRANSFORM = re.compile(r"^transform\s+(\w+)")
_RE_FORMAT_OFF = re.compile(r"#\s*senpy:\s*format\s+off", re.IGNORECASE)
_RE_FORMAT_ON = re.compile(r"#\s*senpy:\s*format\s+on", re.IGNORECASE)


def _strip_comment_safe(line: str) -> str:
    """Strip # comment, but respect quotes (so # inside "..." is not a comment).

    Simplified version — full implementation is in analyzer._strip_comment.
    For formatter we don't need full accuracy; comment detection is only
    used to find # senpy: format off/on directives.
    """
    if "#" not in line:
        return line
    in_quote: str | None = None
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "\\":
            i += 2
            continue
        if in_quote:
            if ch == in_quote:
                in_quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            in_quote = ch
            i += 1
            continue
        if ch == "#":
            return line[:i]
        i += 1
    return line


# =============================================================================
# Context builder
# =============================================================================


def _build_contexts(lines: list[str], config: FormatConfig) -> list[FormatContext]:
    """Build FormatContext for each line.

    Detects scope (label/screen/menu/init/atl) by indentation + keywords.
    Tracks `# senpy: format off` blocks for skip.
    """
    contexts: list[FormatContext] = []
    # scope_stack: list of (scope, name, indent_at_open)
    scope_stack: list[tuple[str, str | None, int]] = [("top", None, 0)]
    skip_block = False

    for idx, raw in enumerate(lines):
        # Detect skip directives (in raw line, before any processing)
        if _RE_FORMAT_OFF.search(raw):
            skip_block = True
        if _RE_FORMAT_ON.search(raw):
            skip_block = False

        # Compute indent (in spaces, after tab expansion — but we don't modify raw here)
        # For MVP, indent is just leading spaces count (tab handling is in FMT-INDENT rule).
        stripped_for_indent = raw.lstrip(" \t")
        leading = raw[: len(raw) - len(stripped_for_indent)]
        # expandtabs for indent counting (1 tab = indent_size spaces)
        indent_spaces = len(leading.expandtabs(config.indent_size))

        # Strip comment for scope detection (so `label x: # comment` still detected)
        clean = _strip_comment_safe(raw).strip()

        # Pop scope stack on dedent
        while len(scope_stack) > 1 and indent_spaces < scope_stack[-1][2]:
            scope_stack.pop()

        # Push new scope on scope-opening keywords
        if clean:
            m_label = _RE_LABEL.match(clean)
            m_screen = _RE_SCREEN.match(clean)
            m_init = _RE_INIT.match(clean)
            m_menu = _RE_MENU.match(clean)
            m_transform = _RE_TRANSFORM.match(clean)

            if m_label:
                scope_stack.append(("label", m_label.group(1), indent_spaces))
            elif m_screen:
                scope_stack.append(("screen", m_screen.group(1), indent_spaces))
            elif m_init:
                scope_stack.append(("init", None, indent_spaces))
            elif m_menu:
                scope_stack.append(("menu", None, indent_spaces))
            elif m_transform:
                scope_stack.append(("atl", m_transform.group(1), indent_spaces))

        contexts.append(
            FormatContext(
                line_idx=idx,
                raw=raw,
                indent=indent_spaces,
                scope=scope_stack[-1][0],
                scope_name=scope_stack[-1][1],
                skip=skip_block,
            )
        )

    return contexts


def _emit(contexts: list[FormatContext]) -> str:
    """Join contexts back into a single string."""
    return "".join(c.raw for c in contexts)


# =============================================================================
# Formatter class
# =============================================================================


class Formatter:
    """Main formatter class. Idempotent: format(format(x)) == format(x).

    Usage:
        f = Formatter()  # default config
        formatted = f.format_code(source_text)
        f.format_file("path/to/file.rpy")  # in-place, returns True if changed
    """

    def __init__(self, config: FormatConfig | None = None):
        self.config = config or FormatConfig()
        self.rules: list[tuple[str, RuleFn]] = get_registered_rules()

    def format_code(self, code: str, filename: str = "<stdin>") -> str:
        """Format source code string. Returns formatted text.

        Idempotent: format(format(x)) == format(x).
        """
        # Normalize line endings: accept any, output \n
        # (splitlines handles \r\n, \r, \n; we add \n back in _emit via raw)
        lines = code.splitlines(keepends=True)
        # If file doesn't end with newline, splitlines won't add one —
        # FMT-EOF-NEWLINE rule handles this.

        contexts = _build_contexts(lines, self.config)
        for _name, rule_fn in self.rules:
            contexts = rule_fn(contexts, self.config)
        return _emit(contexts)

    def format_file(self, path: str) -> bool:
        """Format file in-place. Returns True if file was modified."""
        with open(path, encoding="utf-8", newline="") as f:
            original = f.read()
        formatted = self.format_code(original, filename=path)
        if formatted != original:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(formatted)
            return True
        return False

    def is_formatted(self, code: str) -> bool:
        """Check if code is already formatted (no changes needed)."""
        return self.format_code(code) == code
