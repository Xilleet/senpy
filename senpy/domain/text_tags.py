from __future__ import annotations

import difflib
import os
import re

from senpy.core.constants import (
    MEDIA_EXTENSIONS,
    NAMED_COLORS,
    PAIR_TAGS,
    RE_INTERPOLATION,
    RE_STRING_MATCH,
    RE_TAG,
    SELF_CLOSING_TAGS,
)
from senpy.core.models import Diagnostic

# Tags that cannot be nested inside themselves. If encountered while already
# inside one, treat as a likely typo of the closing tag ({b}...{b} → {b}...{/b}).
_NON_NESTABLE_TAGS = frozenset({"b", "i", "u", "s", "plain"})


def get_utf16_range(line: str, sub: str | None = None) -> tuple[int, int]:
    """Возвращает UTF-16 смещения (start, end) для LSP и подсветки в редакторе."""
    line_clean = line.rstrip("\r\n")
    if not sub:
        indent = len(line_clean) - len(line_clean.lstrip())
        start = len(line_clean[:indent].encode("utf-16-le")) // 2
        end = len(line_clean.encode("utf-16-le")) // 2
        return start, max(start + 1, end)

    idx = line_clean.find(sub)
    if idx == -1:
        indent = len(line_clean) - len(line_clean.lstrip())
        start = len(line_clean[:indent].encode("utf-16-le")) // 2
        end = len(line_clean.encode("utf-16-le")) // 2
        return start, max(start + 1, end)

    start = len(line_clean[:idx].encode("utf-16-le")) // 2
    end = len(line_clean[: idx + len(sub)].encode("utf-16-le")) // 2
    return start, end


def suggest_similar_symbol(unknown_var: str, user_symbols: set[str]) -> str:
    """Предлагает близкое по написанию имя переменной."""
    matches = difflib.get_close_matches(unknown_var, list(user_symbols), n=1, cutoff=0.6)
    if matches:
        return f" (did you mean '{matches[0]}' ?)"
    return ""


def process_quoted_strings(
    raw_line: str,
    line_idx: int,
    file_path: str,
    declared_symbols: set[str],
    extra_symbols: set[str],
    user_symbols: set[str],
    fix: bool = False,
) -> tuple[str, bool, list[Diagnostic], int, int, list[str]]:
    """
    Разбирает все строковые литералы в строке:
    - Выявляет и автофиксирует незакрытые теги (RPY301).
    - Проверяет hex-цвета в {color} (RPY304).
    - Проверяет необъявленные переменные в [var] (RPY101).
    - Регистрирует упомянутые ассеты (для RPY503).

    Возвращает (reconstructed_line, modified, diagnostics, fixed_count,
    fixable_count, used_assets).
    """
    if '"' not in raw_line and "'" not in raw_line:
        return raw_line, False, [], 0, 0, []

    matches = list(RE_STRING_MATCH.finditer(raw_line))
    if not matches:
        return raw_line, False, [], 0, 0, []

    state = _TagCheckState(raw_line=raw_line)
    diagnostics: list[Diagnostic] = []
    used_assets: list[str] = []

    for match in matches:
        _process_one_match(
            match=match,
            raw_line=raw_line,
            line_idx=line_idx,
            file_path=file_path,
            declared_symbols=declared_symbols,
            extra_symbols=extra_symbols,
            user_symbols=user_symbols,
            state=state,
            diagnostics=diagnostics,
            used_assets=used_assets,
        )

    _finalize_unclosed_tags(
        matches=matches,
        state=state,
        raw_line=raw_line,
        line_idx=line_idx,
        file_path=file_path,
        fix=fix,
        diagnostics=diagnostics,
    )

    fixed_count, fixable_count = state.fixed_count, state.fixable_count
    if fix and state.modified:
        return state.reconstructed_line, True, diagnostics, fixed_count, fixable_count, used_assets
    return (
        state.reconstructed_line,
        state.modified,
        diagnostics,
        fixed_count,
        fixable_count,
        used_assets,
    )


class _TagCheckState:
    """Mutable state shared across all string-literal matches in a single line.

    `process_quoted_strings` walks every string literal on a line; the open-tag
    stack, accumulated fix counters and reconstructed line need to persist
    between iterations. This tiny dataclass keeps the dispatcher signature
    short and makes the helpers below easy to test in isolation.
    """

    __slots__ = (
        "raw_line",
        "stack",
        "first_unclosed_match",
        "modified",
        "reconstructed_line",
        "fixed_count",
        "fixable_count",
    )

    def __init__(self, raw_line: str) -> None:
        self.raw_line = raw_line
        # Stack of currently-open pair tags (e.g. {"b", "i"}).
        self.stack: list[str] = []
        # First match where an unclosed tag was detected — used for the
        # "Auto-close tag(s)" QuickFix range.
        self.first_unclosed_match: re.Match[str] | None = None
        # True if any in-place replacement or auto-close was applied.
        self.modified: bool = False
        # Reconstructed line — only diverges from raw_line when `fix=True`
        # and a replacement was applied.
        self.reconstructed_line: str = raw_line
        # Counters for the `--show-fixes` report.
        self.fixed_count: int = 0
        self.fixable_count: int = 0


def _process_one_match(
    *,
    match: re.Match[str],
    raw_line: str,
    line_idx: int,
    file_path: str,
    declared_symbols: set[str],
    extra_symbols: set[str],
    user_symbols: set[str],
    state: _TagCheckState,
    diagnostics: list[Diagnostic],
    used_assets: list[str],
) -> None:
    """Process one string-literal match: extract assets, check interpolation
    vars (RPY101), check color tags (RPY304), match open/close pair tags
    (RPY301), and apply in-place fixes for non-nestable tag typos.
    """
    full_str = match.group(0)
    if full_str.startswith(('"""', "'''")):
        quote_len = 3
        quote_char = full_str[:3]
    else:
        quote_len = 1
        quote_char = full_str[0]
    inner_content = full_str[quote_len:-quote_len]

    # RPY503: register media assets referenced by string literal
    val_clean = inner_content.replace("\\", "/").lower().strip()
    if any(val_clean.endswith(ext) for ext in MEDIA_EXTENSIONS):
        used_assets.append(val_clean)
        used_assets.append(os.path.basename(val_clean))

    # Mask escaped chars and doubled braces/brackets so RE_TAG and RE_INTERPOLATION
    # don't match inside escapes (e.g. `\\{` or `{{`).
    masked_content = re.sub(r"\\.|(\{\{|\[\[)", lambda m: " " * len(m.group(0)), inner_content)

    # RPY101: undeclared variables in [var] interpolation
    _check_interpolation_vars(
        masked_content,
        raw_line,
        line_idx,
        file_path,
        declared_symbols,
        extra_symbols,
        user_symbols,
        diagnostics,
    )

    in_place_replacements: list[tuple[int, int, str]] = _collect_tag_diagnostics(
        masked_content=masked_content,
        match=match,
        raw_line=raw_line,
        line_idx=line_idx,
        file_path=file_path,
        state=state,
        diagnostics=diagnostics,
    )

    if in_place_replacements:
        state.fixable_count += len(in_place_replacements)
        # In-place replacements are applied later (in the fix branch) to
        # avoid mutating `inner_content` while we might still be iterating.
        # We accumulate them here, then apply in reverse order below.
        if True:  # keep structure flat for readability
            _apply_in_place_replacements(
                in_place_replacements=in_place_replacements,
                inner_content=inner_content,
                match=match,
                quote_char=quote_char,
                state=state,
            )


def _collect_tag_diagnostics(
    *,
    masked_content: str,
    match: re.Match[str],
    raw_line: str,
    line_idx: int,
    file_path: str,
    state: _TagCheckState,
    diagnostics: list[Diagnostic],
) -> list[tuple[int, int, str]]:
    """Walk all {tag} occurrences in `masked_content`.

    For each tag:
      - Validate hex/named color (RPY304) — delegated to `_check_color_tag`.
      - Self-closing tags are skipped.
      - For pair tags: pop/push the shared stack, report mismatches (RPY301).
      - For non-nestable tags opened twice in a row: queue an in-place
        replacement `{x}` → `{/x}` (RPY301, fixable).

    Returns the list of queued in-place replacements (start, end, replacement)
    in `masked_content` coordinates — to be applied by the caller.
    """
    in_place_replacements: list[tuple[int, int, str]] = []

    for t_match in RE_TAG.finditer(masked_content):
        is_closing = t_match.group(1) == "/"
        tag_name = t_match.group(2).lower()
        tag_param = t_match.group(3)
        t_start, t_end = t_match.span()

        # RPY304: Validate hex/named color in {color} tag
        _check_color_tag(
            tag_name, is_closing, tag_param, raw_line, line_idx, file_path, diagnostics
        )

        if tag_name in SELF_CLOSING_TAGS:
            continue

        if tag_name not in PAIR_TAGS:
            continue

        if is_closing:
            _handle_closing_tag(
                tag_name=tag_name,
                stack=state.stack,
                raw_line=raw_line,
                line_idx=line_idx,
                file_path=file_path,
                diagnostics=diagnostics,
            )
            continue

        # Opening pair tag
        if tag_name in _NON_NESTABLE_TAGS and tag_name in state.stack:
            # Likely a typo of the closing tag. Queue an in-place replacement
            # and emit a fixable diagnostic.
            state.stack.remove(tag_name)
            replacement_tag = f"{{/{tag_name}}}"
            in_place_replacements.append((t_start, t_end, replacement_tag))

            raw_tag_start = match.start() + 1 + t_start
            raw_tag_end = match.start() + 1 + t_end
            start_c = len(raw_line[:raw_tag_start].encode("utf-16-le")) // 2
            end_c = len(raw_line[:raw_tag_end].encode("utf-16-le")) // 2

            diagnostics.append(
                Diagnostic(
                    file_path=file_path,
                    line_number=line_idx,
                    line_content=raw_line.strip(),
                    code="RPY301",
                    message=(
                        f"Duplicate opening tag '{{{tag_name}}}' while already inside "
                        f"'{{{tag_name}}}'. Did you mean '{{/{tag_name}}}'?"
                    ),
                    col=start_c,
                    end_col=end_c,
                    fix_title=f"Change '{{{tag_name}}}' to '{{/{tag_name}}}'",
                    fix_replacement=replacement_tag,
                    fix_start_col=start_c,
                    fix_end_col=end_c,
                )
            )
        else:
            if not state.stack and state.first_unclosed_match is None:
                state.first_unclosed_match = match
            state.stack.append(tag_name)

    return in_place_replacements


def _handle_closing_tag(
    *,
    tag_name: str,
    stack: list[str],
    raw_line: str,
    line_idx: int,
    file_path: str,
    diagnostics: list[Diagnostic],
) -> None:
    """Process a `{/tag}` closing tag against the shared open-tag stack.

    Empty stack → "closing tag without opening" diagnostic (RPY301).
    Top of stack ≠ tag → "mismatched tag" diagnostic (RPY301).
    Otherwise pop the matching open tag silently.
    """
    if not stack:
        diagnostics.append(
            Diagnostic(
                file_path=file_path,
                line_number=line_idx,
                line_content=raw_line.strip(),
                code="RPY301",
                message=f"Found closing tag '{{/{tag_name}}}' without matching opening tag.",
            )
        )
        return

    last_tag = stack.pop()
    if last_tag != tag_name:
        diagnostics.append(
            Diagnostic(
                file_path=file_path,
                line_number=line_idx,
                line_content=raw_line.strip(),
                code="RPY301",
                message=(f"Mismatched tag: expected '{{/{last_tag}}}', found '{{/{tag_name}}}'."),
            )
        )


def _apply_in_place_replacements(
    *,
    in_place_replacements: list[tuple[int, int, str]],
    inner_content: str,
    match: re.Match[str],
    quote_char: str,
    state: _TagCheckState,
) -> None:
    """Apply queued in-place tag replacements to `inner_content` and splice
    the result back into `state.reconstructed_line`.

    Always counts the replacements as fixable; only marks `state.modified`
    and increments `state.fixed_count` if `state` indicates fixes were
    applied. Since `process_quoted_strings` only enables fixing on the `fix`
    branch (caller responsibility), we always apply here and let the caller
    decide via `state.modified` whether to advertise the change.
    """
    # Note: the caller has already incremented `fixable_count` before
    # calling us. We unconditionally apply the replacements to the
    # reconstructed line so the caller's `fix=True` branch picks them up.
    for s, e, repl in sorted(in_place_replacements, key=lambda x: x[0], reverse=True):
        inner_content = inner_content[:s] + repl + inner_content[e:]
    state.modified = True
    state.fixed_count += len(in_place_replacements)
    start, end = match.span()
    state.reconstructed_line = (
        state.reconstructed_line[:start]
        + f"{quote_char}{inner_content}{quote_char}"
        + state.reconstructed_line[end:]
    )


def _finalize_unclosed_tags(
    *,
    matches: list[re.Match[str]],
    state: _TagCheckState,
    raw_line: str,
    line_idx: int,
    file_path: str,
    fix: bool,
    diagnostics: list[Diagnostic],
) -> None:
    """After processing every string literal on the line, if any open pair
    tags remain on the stack, emit RPY301 "unclosed tag" diagnostics and —
    when `fix=True` — insert auto-close tags at the end of the last match.
    """
    if not state.stack:
        return

    last_match = matches[-1]
    closing_tags = "".join(f"{{/{t}}}" for t in reversed(state.stack))
    quote_len = 3 if last_match.group(0).startswith(('"""', "'''")) else 1

    if fix:
        insert_pos = last_match.end() - quote_len
        state.reconstructed_line = (
            state.reconstructed_line[:insert_pos]
            + closing_tags
            + state.reconstructed_line[insert_pos:]
        )
        state.modified = True
        state.fixed_count += len(state.stack)
        return

    # Non-fix branch: count one fixable item and emit the diagnostic.
    state.fixable_count += 1
    unclosed = ", ".join(f"'{{{t}}}'" for t in state.stack)
    first_unclosed_tag = f"{{{state.stack[0]}}}"
    start_c, end_c = get_utf16_range(raw_line, first_unclosed_tag)

    insert_idx = last_match.end() - quote_len
    ins_char = len(raw_line[:insert_idx].encode("utf-16-le")) // 2

    diagnostics.append(
        Diagnostic(
            file_path=file_path,
            line_number=line_idx,
            line_content=raw_line.strip(),
            code="RPY301",
            message=f"Unclosed text tag(s) in dialogue: {unclosed}.",
            col=start_c,
            end_col=end_c,
            fix_title=f"Auto-close tag(s) with '{closing_tags}'",
            fix_replacement=closing_tags,
            fix_start_col=ins_char,
            fix_end_col=ins_char,
        )
    )


def _check_interpolation_vars(
    masked_content: str,
    raw_line: str,
    line_idx: int,
    file_path: str,
    declared_symbols: set[str],
    extra_symbols: set[str],
    user_symbols: set[str],
    diagnostics: list[Diagnostic],
) -> None:
    """RPY101: Check for undeclared variables in [var] interpolation."""
    for var in RE_INTERPOLATION.findall(masked_content):
        if var not in declared_symbols and var not in extra_symbols:
            hint = suggest_similar_symbol(var, user_symbols)
            start_c, end_c = get_utf16_range(raw_line, f"[{var}]")
            diagnostics.append(
                Diagnostic(
                    file_path=file_path,
                    line_number=line_idx,
                    line_content=raw_line.strip(),
                    code="RPY101",
                    message=f"Variable '[{var}]' is not declared via 'default' or 'define'{hint}.",
                    col=start_c,
                    end_col=end_c,
                )
            )


def _check_color_tag(
    tag_name: str,
    is_closing: bool,
    tag_param: str | None,
    raw_line: str,
    line_idx: int,
    file_path: str,
    diagnostics: list[Diagnostic],
) -> None:
    """RPY304: Validate hex color or named color in {color} tag."""
    if tag_name != "color" or is_closing or not tag_param:
        return

    color_val = tag_param.strip("\"'").lower()
    if color_val.startswith("#"):
        hex_str = color_val[1:]
        if len(hex_str) not in (3, 4, 6, 8) or not all(c in "0123456789abcdef" for c in hex_str):
            start_c, end_c = get_utf16_range(raw_line, tag_param)
            diagnostics.append(
                Diagnostic(
                    file_path=file_path,
                    line_number=line_idx,
                    line_content=raw_line.strip(),
                    code="RPY304",
                    message=f"Malformed hex color '{color_val}' in {{color}} tag.",
                    col=start_c,
                    end_col=end_c,
                )
            )
    elif color_val not in NAMED_COLORS:
        diagnostics.append(
            Diagnostic(
                file_path=file_path,
                line_number=line_idx,
                line_content=raw_line.strip(),
                code="RPY304",
                message=f"Unknown color name '{color_val}' in {{color}} tag.",
            )
        )
