"""SymbolTable — extracted from SenpyAnalyzer.

Manages all symbol registries: variables, labels, screens, transforms,
images, and aggregate sets (user_symbols, declared_symbols, etc.).

Before this extraction, SenpyAnalyzer held 15+ symbol-related attributes
directly in __init__ and managed them via _rebuild_aggregates,
_differential_purge_file, _purge_file_symbols, and _run_reset.
SymbolTable encapsulates all of that — SenpyAnalyzer becomes a facade
that delegates symbol access to SymbolTable.

The extraction is additive: SenpyAnalyzer still exposes the same
attributes (via properties), so all 17 consumer files (checkers, LSP
handlers, formatters, cache) continue to work without changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from senpy.core.constants import BUILTIN_AUDIO_CHANNELS, BUILTIN_SYMBOLS
from senpy.core.symbols import (
    ImageSymbol,
    LabelSymbol,
    ScreenSymbol,
    TransformSymbol,
    VariableSymbol,
)

if TYPE_CHECKING:
    from senpy.core.scope import FileScope


class SymbolTable:
    """Central registry for all symbols collected from .rpy files.

    Attributes:
        variables: dict[name, VariableSymbol] — define + default declarations
        labels: dict[name, LabelSymbol] — label declarations
        screens: dict[name, ScreenSymbol] — screen declarations
        images: dict[name, ImageSymbol] — image declarations
        transforms: dict[name, TransformSymbol] — transform declarations

        user_symbols: set of all user-declared identifiers (for RPY101/103)
        declared_symbols: set of all declared symbols (BUILTIN_SYMBOLS + user)
        referenced_labels: set of labels referenced via jump/call
        jump_sources: dict[label, list[(file, line)]] — reverse index

        defined_audio_map: dict[alias, file] — define audio.X = "file.ogg"
        registered_audio_channels: set of channels from renpy.music.register_channel

        screen_action_jumps: dict[screen, set[label]] — screen Jump/Call targets
        used_screens: set of screens referenced via show/call/use
        screen_uses: dict[source, set[target]] — screen use references

        has_dynamic_jumps: True if project uses renpy.jump() in strings
        missing_defaults: dict[var, inferred_default] — for senpy_defaults.rpy
    """

    def __init__(self) -> None:
        # Object registries (replace the old 13 dicts)
        self.variables: dict[str, VariableSymbol] = {}
        self.labels: dict[str, LabelSymbol] = {}
        self.screens: dict[str, ScreenSymbol] = {}
        self.images: dict[str, ImageSymbol] = {}
        self.transforms: dict[str, TransformSymbol] = {}

        # Aggregate sets
        self.user_symbols: set[str] = set()
        self.declared_symbols: set[str] = set(BUILTIN_SYMBOLS)
        self.referenced_labels: set[str] = set()

        # Audio
        self.defined_audio_map: dict[str, str] = {}
        self.registered_audio_channels: set[str] = set(BUILTIN_AUDIO_CHANNELS)

        # Jump/call tracking
        self.jump_sources: dict[str, list[tuple[str, int]]] = {}
        self.screen_action_jumps: dict[str, set[str]] = {}
        self.used_screens: set[str] = set()
        self.screen_uses: dict[str, set[str]] = {}

        # State
        self.has_dynamic_jumps: bool = False
        self.missing_defaults: dict[str, str] = {}

    def reset(self) -> None:
        """Reset all symbol state for a fresh run."""
        self.variables.clear()
        self.labels.clear()
        self.screens.clear()
        self.images.clear()
        self.transforms.clear()
        self.user_symbols.clear()
        self.declared_symbols = set(BUILTIN_SYMBOLS)
        self.referenced_labels.clear()
        self.defined_audio_map.clear()
        self.registered_audio_channels = set(BUILTIN_AUDIO_CHANNELS)
        self.jump_sources.clear()
        self.screen_action_jumps.clear()
        self.used_screens.clear()
        self.screen_uses.clear()
        self.has_dynamic_jumps = False
        self.missing_defaults.clear()

    def rebuild_from_scopes(self, file_scopes: dict[str, FileScope]) -> None:
        """Rebuild all global symbol sets from per-file FileScope objects.

        Called after _collect_all_symbols and after _purge_file_symbols
        (full rebuild path).
        """
        self.declared_symbols = set(BUILTIN_SYMBOLS)
        self.user_symbols.clear()
        self.registered_audio_channels = set(BUILTIN_AUDIO_CHANNELS)
        self.defined_audio_map.clear()
        self.referenced_labels.clear()

        self.variables.clear()
        self.labels.clear()
        self.screens.clear()
        self.images.clear()
        self.jump_sources.clear()
        self.screen_uses.clear()

        for scope in file_scopes.values():
            self.declared_symbols.update(scope.declared_symbols)
            self.user_symbols.update(scope.user_symbols)
            self.registered_audio_channels.update(scope.registered_audio_channels)
            self.defined_audio_map.update(scope.defined_audio_map)
            self.referenced_labels.update(scope.referenced_labels)
            for scr_name, targets in getattr(scope, "screen_action_jumps", {}).items():
                self.screen_action_jumps.setdefault(scr_name, set()).update(targets)
            self.used_screens.update(getattr(scope, "used_screens", ()))
            for src_name, targets in getattr(scope, "screen_uses", {}).items():
                self.screen_uses.setdefault(src_name, set()).update(targets)

            self.variables.update(scope.variables)
            self.labels.update(scope.labels)
            self.screens.update(scope.screens)
            self.images.update(scope.images)
            self.transforms.update(scope.transforms)

            for tgt, locs in scope.jump_sources.items():
                self.jump_sources.setdefault(tgt, []).extend(locs)

        # screen Jump/Call actions — also static references (RPY303, cache-stable)
        for targets in self.screen_action_jumps.values():
            self.referenced_labels.update(targets)

        # Re-aggregate has_dynamic_jumps from per-file FileScope flags.
        # Cold run sets this via `_collect_misc` (which also sets
        # `scope.has_dynamic_jumps`). Warm run (Tier 1 cache hit) restores
        # FileScope from disk and reaches this rebuild path — without
        # aggregating here, warm runs would lose the flag and RPY701-707
        # would re-fire on dynamic-jump projects.
        self.has_dynamic_jumps = any(
            getattr(scope, "has_dynamic_jumps", False) for scope in file_scopes.values()
        )

    def purge_object_registries(
        self, old_scope: FileScope, file_scopes: dict[str, FileScope]
    ) -> None:
        """Remove a file's symbols from global object dicts only when no
        other file scope still declares the same symbol.

        Mirrors the contract of purge_shared_sets: every key is checked
        against the surviving FileScopes before being popped. This keeps
        the LSP fast-path (analyze_file_only) consistent with the full
        rebuild path — when the edited file drops a declaration that
        another file still holds, the global registry must keep the
        surviving entry rather than silently losing it.
        """
        other_scopes = list(file_scopes.values())

        for k in old_scope.variables:
            if not any(k in s.variables for s in other_scopes):
                self.variables.pop(k, None)

        for k in old_scope.labels:
            if not any(k in s.labels for s in other_scopes):
                self.labels.pop(k, None)

        for k in old_scope.screens:
            if not any(k in s.screens for s in other_scopes):
                self.screens.pop(k, None)

        for k in old_scope.images:
            if not any(k in s.images for s in other_scopes):
                self.images.pop(k, None)

        for k in old_scope.transforms:
            if not any(k in s.transforms for s in other_scopes):
                self.transforms.pop(k, None)

        for k in old_scope.defined_audio_map:
            if not any(k in s.defined_audio_map for s in other_scopes):
                self.defined_audio_map.pop(k, None)

    def purge_jump_sources(self, old_scope: FileScope, file_path: str) -> None:
        """Clear jump_sources entries that originated from the purged file."""
        for tgt in old_scope.jump_sources:
            if tgt in self.jump_sources:
                self.jump_sources[tgt] = [
                    loc for loc in self.jump_sources[tgt] if loc[0] != file_path
                ]
                if not self.jump_sources[tgt]:
                    self.jump_sources.pop(tgt, None)

    def purge_shared_sets(self, old_scope: FileScope, file_scopes: dict[str, FileScope]) -> None:
        """Differential set cleanup: remove a symbol from the global set only
        if it is NOT present in any other file scope."""
        other_scopes = list(file_scopes.values())

        for sym in old_scope.user_symbols:
            if not any(sym in s.user_symbols for s in other_scopes):
                self.user_symbols.discard(sym)

        for sym in old_scope.declared_symbols:
            if sym not in BUILTIN_SYMBOLS and not any(
                sym in s.declared_symbols for s in other_scopes
            ):
                self.declared_symbols.discard(sym)

        for sym in old_scope.referenced_labels:
            if not any(sym in s.referenced_labels for s in other_scopes):
                self.referenced_labels.discard(sym)

        for scr_name in getattr(old_scope, "used_screens", ()):
            if not any(scr_name in getattr(s, "used_screens", ()) for s in other_scopes):
                self.used_screens.discard(scr_name)

        for scr_name in getattr(old_scope, "screen_action_jumps", {}):
            if not any(scr_name in getattr(s, "screen_action_jumps", {}) for s in other_scopes):
                self.screen_action_jumps.pop(scr_name, None)

        for src_name in getattr(old_scope, "screen_uses", {}):
            if not any(src_name in getattr(s, "screen_uses", {}) for s in other_scopes):
                self.screen_uses.pop(src_name, None)

        for chan in old_scope.registered_audio_channels:
            if chan not in BUILTIN_AUDIO_CHANNELS and not any(
                chan in s.registered_audio_channels for s in other_scopes
            ):
                self.registered_audio_channels.discard(chan)
