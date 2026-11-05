"""Dead code detection: RPY701-707 (unused define/transform/screen/variable/screen-param/transform-param/audio-channel).

Extracted from core/analyzer.py in 0.6.6 to reduce analyzer god-class.
The function takes an analyzer instance and appends diagnostics directly.

RPY704-707 extend the dead-code taxonomy (added in 0.7.6):
  - RPY704: unused `default` variable (non-constant, complement to RPY701)
  - RPY705: unused screen parameter (param declared but never referenced in body)
  - RPY706: unused transform parameter (same logic as RPY705 for transforms)
  - RPY707: unused audio channel registration (registered via
    renpy.music.register_channel but never played on)
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING

from senpy.core.constants import BUILTIN_SCREENS, BUILTIN_SYMBOLS
from senpy.core.models import Diagnostic
from senpy.core.paths import normalize_path

if TYPE_CHECKING:
    from senpy.core.analyzer import SenpyAnalyzer

# Pre-compiled regex for word tokenization.
_WORD_RE = re.compile(r"\w+")

# Regex for finding renpy.music.register_channel calls (RPY707).
_RE_REGISTER_CHANNEL = re.compile(r'renpy\.music\.register_channel\s*\(\s*["\']([^\W\d]\w*)["\']')

# Built-in audio channels that are always considered "used".
_BUILTIN_AUDIO_CHANNELS = frozenset({"music", "sound", "voice", "audio"})


# =============================================================================
# Shared infrastructure — word index + _is_used helper
# =============================================================================


def _build_word_index(
    analyzer: SenpyAnalyzer,
) -> dict[str, set[tuple[str, int]]]:
    """Build a word → set of (norm_path, line_idx_0based) index in one pass.

    Words are lowercased so lookups are case-insensitive — this matters
    for RPY707 where channel names ("ambient") may appear in comments
    or strings with different casing ("Ambient channel is...").

    The index is shared across all RPY701-707 checks to avoid re-scanning
    the entire project multiple times. On DDLC (50 files, 77k lines),
    the old O(symbols × total_lines) approach was hanging for minutes;
    this index makes it O(total_words + symbols).
    """
    word_locations: dict[str, set[tuple[str, int]]] = defaultdict(set)
    for norm_path in analyzer.file_scopes:
        lines = analyzer._stage1_lines.get(norm_path)
        if lines is None:
            try:
                with open(norm_path, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except OSError:
                continue
            analyzer._stage1_lines[norm_path] = lines
        for i, line in enumerate(lines):
            for word in _WORD_RE.findall(line):
                word_locations[word.lower()].add((norm_path, i))
    return word_locations


def _is_used(
    name: str,
    decl_file: str,
    decl_line: int,
    word_locations: dict[str, set[tuple[str, int]]],
) -> bool:
    """O(1) lookup: name is used if it appears outside its declaration line.

    Case-insensitive (lowercases both name and lookup). This is correct
    for Ren'Py identifiers (case-sensitive in the language, but a
    channel named 'ambient' is the same channel whether the user
    writes 'play ambient' or accidentally references it in a comment
    as 'Ambient' — the comment still indicates awareness of the channel).
    """
    decl_norm = normalize_path(decl_file)
    decl_loc = (decl_norm, decl_line - 1)
    locations = word_locations.get(name.lower())
    if not locations:
        return False
    if len(locations) > 1:
        return True
    return decl_loc not in locations


# =============================================================================
# Individual rule checks (RPY701-707)
# =============================================================================


def _check_rpy701(
    analyzer: SenpyAnalyzer,
    word_locations: dict[str, set[tuple[str, int]]],
) -> None:
    """RPY701: Unused define constants."""
    for name, var_sym in analyzer.variables.items():
        if not var_sym.is_constant:
            continue
        if var_sym.is_character:
            continue
        if not _is_used(name, var_sym.file_path, var_sym.line_number, word_locations):
            analyzer._add_diagnostic_by_file(
                Diagnostic(
                    file_path=var_sym.file_path,
                    line_number=var_sym.line_number,
                    line_content=var_sym.code_line,
                    code="RPY701",
                    message=f"Constant '{name}' is declared with 'define' but never used. Consider removing this dead code.",
                    severity="HINT",
                )
            )


def _check_rpy702(
    analyzer: SenpyAnalyzer,
    word_locations: dict[str, set[tuple[str, int]]],
) -> None:
    """RPY702: Unused transforms."""
    for name, trn_sym in analyzer.transforms.items():
        if name in BUILTIN_SYMBOLS:
            continue
        if not _is_used(name, trn_sym.file_path, trn_sym.line_number, word_locations):
            analyzer._add_diagnostic_by_file(
                Diagnostic(
                    file_path=trn_sym.file_path,
                    line_number=trn_sym.line_number,
                    line_content=trn_sym.code_line,
                    code="RPY702",
                    message=f"Transform '{name}' is defined but never used in 'show/scene at'. Consider removing this dead code.",
                    severity="HINT",
                )
            )


def _check_rpy703(
    analyzer: SenpyAnalyzer,
    word_locations: dict[str, set[tuple[str, int]]],
) -> None:
    """RPY703: Unused screens."""
    for name, scr_sym in analyzer.screens.items():
        if name in BUILTIN_SCREENS:
            continue
        if not _is_used(name, scr_sym.file_path, scr_sym.line_number, word_locations):
            analyzer._add_diagnostic_by_file(
                Diagnostic(
                    file_path=scr_sym.file_path,
                    line_number=scr_sym.line_number,
                    line_content=f"screen {name}():",
                    code="RPY703",
                    message=f"Screen '{name}' is defined but never called or shown. Consider removing this dead code.",
                    severity="HINT",
                )
            )


def _check_rpy704(
    analyzer: SenpyAnalyzer,
    word_locations: dict[str, set[tuple[str, int]]],
) -> None:
    """RPY704: Unused `default` variables (non-constant, complement to RPY701).

    Skip variables that are used in dialogue interpolation ([var]) —
    word_locations catches those because [ and ] are word boundaries
    for \\w+, so `player_name` inside `[player_name]` is indexed.
    Skip variables used only in their own declaration line (caught by
    _is_used returning False when the only location is the declaration).
    """
    for name, var_sym in analyzer.variables.items():
        if var_sym.is_constant:
            continue  # RPY701 handles constants
        if var_sym.is_character:
            continue
        if not _is_used(name, var_sym.file_path, var_sym.line_number, word_locations):
            analyzer._add_diagnostic_by_file(
                Diagnostic(
                    file_path=var_sym.file_path,
                    line_number=var_sym.line_number,
                    line_content=var_sym.code_line,
                    code="RPY704",
                    message=f"Variable '{name}' is declared with 'default' but never used. Consider removing this dead code, or rename to '_' if intentional.",
                    severity="HINT",
                )
            )


def _check_rpy705(
    analyzer: SenpyAnalyzer,
    word_locations: dict[str, set[tuple[str, int]]],
) -> None:
    """RPY705: Unused screen parameters.

    For each screen, check each declared parameter (from signature.all_names).
    A parameter is "used" if it appears anywhere in the same file
    (not just in the screen body — approximation, but matches how
    Ren'Py allows screens to reference each other's params via actions).
    False positive risk: if a parameter name happens to match another
    identifier in the same file. Accepted for v1 — we document it.
    """
    for name, scr_sym in analyzer.screens.items():
        if name in BUILTIN_SCREENS:
            continue
        if scr_sym.signature is None or not scr_sym.signature.has_params:
            continue
        for param_name in scr_sym.signature.all_names:
            if not _is_used(param_name, scr_sym.file_path, scr_sym.line_number, word_locations):
                analyzer._add_diagnostic_by_file(
                    Diagnostic(
                        file_path=scr_sym.file_path,
                        line_number=scr_sym.line_number,
                        line_content=f"screen {name}(...):",
                        code="RPY705",
                        message=(
                            f"Screen '{name}' declares parameter '{param_name}' "
                            f"but never uses it in the body. Consider removing "
                            f"the parameter or prefixing it with '_' if it's "
                            f"intentionally unused."
                        ),
                        severity="HINT",
                    )
                )


def _check_rpy706(
    analyzer: SenpyAnalyzer,
    word_locations: dict[str, set[tuple[str, int]]],
) -> None:
    """RPY706: Unused transform parameters (same logic as RPY705 for transforms)."""
    for name, trn_sym in analyzer.transforms.items():
        if name in BUILTIN_SYMBOLS:
            continue
        if trn_sym.signature is None or not trn_sym.signature.has_params:
            continue
        for param_name in trn_sym.signature.all_names:
            if not _is_used(param_name, trn_sym.file_path, trn_sym.line_number, word_locations):
                analyzer._add_diagnostic_by_file(
                    Diagnostic(
                        file_path=trn_sym.file_path,
                        line_number=trn_sym.line_number,
                        line_content=f"transform {name}(...):",
                        code="RPY706",
                        message=(
                            f"Transform '{name}' declares parameter '{param_name}' "
                            f"but never uses it in the body. Consider removing "
                            f"the parameter or prefixing it with '_' if it's "
                            f"intentionally unused."
                        ),
                        severity="HINT",
                    )
                )


def _check_rpy707(
    analyzer: SenpyAnalyzer,
    word_locations: dict[str, set[tuple[str, int]]],
) -> None:
    """RPY707: Unused audio channel registrations.

    `renpy.music.register_channel("name", ...)` adds to
    analyzer.registered_audio_channels. A channel is "used" if it
    appears in a `play <channel> ...` / `queue <channel> ...` /
    `stop <channel> ...` statement anywhere in the project.

    We reuse the case-insensitive word_locations index. But we can't
    just check `chan in word_locations` — the channel name also appears
    in the `register_channel("chan", ...)` declaration line itself.
    So we check: does the channel name appear in word_locations at
    any line that is NOT a `register_channel("...", ...)` call?
    """
    # Build (file, line_idx) set of all register_channel lines, per file.
    register_lines: dict[str, set[int]] = defaultdict(set)
    for norm_path in analyzer.file_scopes:
        lines = analyzer._stage1_lines.get(norm_path)
        if lines is None:
            continue
        for i, line in enumerate(lines):
            if _RE_REGISTER_CHANNEL.search(line):
                register_lines[norm_path].add(i)

    def _is_channel_used(chan: str) -> bool:
        """Channel is used if it appears in any line that is NOT a
        register_channel declaration. This catches `play <chan>`,
        `queue <chan>`, `stop <chan>`, and even comments mentioning the
        channel (acceptable false-positive risk — a comment about a
        channel suggests the developer knows about it)."""
        decl_locations = word_locations.get(chan.lower())
        if not decl_locations:
            return False
        for file_path, line_idx in decl_locations:
            if line_idx in register_lines.get(file_path, set()):
                continue
            return True
        return False

    for chan in analyzer.registered_audio_channels:
        if chan.lower() in _BUILTIN_AUDIO_CHANNELS:
            continue
        if not _is_channel_used(chan):
            _emit_unused_channel_diagnostic(analyzer, chan, register_lines)


def _emit_unused_channel_diagnostic(
    analyzer: SenpyAnalyzer,
    chan: str,
    register_lines: dict[str, set[int]],
) -> None:
    """Find the declaration line for an unused channel and emit RPY707."""
    decl_file = "<unknown>"
    decl_line = 0
    for file_path, line_idxs in register_lines.items():
        if not line_idxs:
            continue
        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
        except OSError:
            continue
        for li in line_idxs:
            if li >= len(all_lines):
                continue
            m = _RE_REGISTER_CHANNEL.search(all_lines[li])
            if m and m.group(1) == chan:
                decl_file = file_path
                decl_line = li + 1  # 1-based
                break
        if decl_file != "<unknown>":
            break
    analyzer._add_diagnostic_by_file(
        Diagnostic(
            file_path=decl_file,
            line_number=decl_line,
            line_content=f'renpy.music.register_channel("{chan}", ...)',
            code="RPY707",
            message=(
                f"Audio channel '{chan}' is registered via "
                f"renpy.music.register_channel but never used in any "
                f"'play'/'queue'/'stop' statement. Consider removing "
                f"the registration or the channel is dead code."
            ),
            severity="HINT",
        )
    )


# =============================================================================
# Public entry point — thin dispatcher
# =============================================================================


def check_unused_declarations(analyzer: SenpyAnalyzer) -> None:
    """RPY701-707: Find unused define/transform/screen/variable/param/channel (dead code).

    Disabled if the project has dynamic jumps (can't track references reliably).
    Delegates to 7 individual check functions, sharing a single word index.

    Before this split (0.7.6), this function was 272 lines with CC=53.
    Now it's a 15-line dispatcher — each rule check lives in its own
    function, making it easy to test and modify individual rules.
    """
    if analyzer.has_dynamic_jumps:
        return

    word_locations = _build_word_index(analyzer)

    _check_rpy701(analyzer, word_locations)
    _check_rpy702(analyzer, word_locations)
    _check_rpy703(analyzer, word_locations)
    _check_rpy704(analyzer, word_locations)
    _check_rpy705(analyzer, word_locations)
    _check_rpy706(analyzer, word_locations)
    _check_rpy707(analyzer, word_locations)
