from __future__ import annotations

import os
import re
from dataclasses import dataclass

from senpy.core.cache import CachedFileEntry, CacheManager, CacheManifest, compute_file_hash
from senpy.core.config import load_config
from senpy.core.constants import (
    IGNORED_DIRS,
    MEDIA_EXTENSIONS,
    RE_DEFAULT,
    RE_DEFINE,
    RE_DEFINE_AUDIO,
    RE_IMAGE_DEF,
    RE_INIT_PYTHON_START,
    RE_JUMP_TARGET,
    RE_LABEL,
    RE_LAYEREDIMAGE_ATTR,
    RE_LAYEREDIMAGE_START,
    RE_NOQA,
    RE_QUOTED_IDENTIFIER,
    RE_RETURN,
    RE_SCREEN_CALL,
    RE_SCREEN_JUMP_ACTION,
    RE_SCREEN_SHOW_ACTION,
    RE_SCREEN_START,
    RE_STRING_MATCH,
    RE_TRANSFORM,
    SENPY_VERSION,
)
from senpy.core.models import RULE_SEVERITY, AnalysisResult, Diagnostic, FileScope
from senpy.core.paths import normalize_path
from senpy.core.progress import progress_print
from senpy.core.scope import ScopeStack, ScopeType
from senpy.core.signature import parse_signature
from senpy.core.symbol_table import SymbolTable
from senpy.core.symbols import (
    ImageSymbol,
    LabelSymbol,
    ScreenSymbol,
    TransformSymbol,
    VariableSymbol,
)
from senpy.domain.assets import AssetManager, find_orphaned_rpyc
from senpy.domain.text_tags import get_utf16_range, process_quoted_strings
from senpy.rules.checkers import (
    AssetChecker,
    DialogueChecker,
    FormattingChecker,
    ScreenChecker,
    StateChecker,
)
from senpy.rules.deprecated import DeprecationChecker
from senpy.rules.flow import StoryFlowAnalyzer
from senpy.rules.python_ast import PythonAstChecker, infer_expr_type

# Phase 1.3 (0.5.3): _strip_comment was moved to senpy/text_utils.py to break
# the circular dependency checkers/flow → analyzer. Re-exported for backward compat.
from senpy.text_utils import _strip_comment  # noqa: E402, F401

# Extract the first quoted string literal from a Python expression
# body. Used for `image name = "path"` and `image name = Transform("path", …)`
# so ImageSymbol.image_path can be populated at parse time (renpy-magic's
# extractAssetPath does the same in TS; we cover the common cases here).
_RE_STRING_LITERAL = re.compile(r"""(["'])(?P<value>(?:\\.|(?!\1).)*)\1""")


def _extract_string_literal(expr: str) -> str | None:
    """Return the first single- or double-quoted string literal in *expr*.

    Returns the literal contents (with backslash escapes preserved as-is;
    callers can os.path.normpath later if they want). None if no string
    literal is found (e.g. body is a Python expression without a literal).
    """
    if not expr:
        return None
    m = _RE_STRING_LITERAL.search(expr)
    if m is None:
        return None
    return m.group("value")


def _count_bracket_delta(s: str) -> int:
    """Counts the bracket balance of (, [, { outside string literals."""
    if not any(c in s for c in "()[]{}"):
        return 0

    delta = 0
    in_quote = None
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "\\":
            i += 2
            continue
        if in_quote in ('"""', "'''"):
            if s[i : i + 3] == in_quote:
                in_quote = None
                i += 3
                continue
            i += 1
            continue
        if in_quote:
            if ch == in_quote:
                in_quote = None
            i += 1
            continue
        if s[i : i + 3] in ('"""', "'''"):
            in_quote = s[i : i + 3]
            i += 3
            continue
        if ch in ('"', "'"):
            in_quote = ch
            i += 1
            continue
        if ch in "([{":
            delta += 1
        elif ch in ")]}":
            delta -= 1
        i += 1
    return delta


def _get_logical_line(lines: list[str], idx: int) -> tuple[int, str, str]:
    """
    Joins multi-line constructs (line continuation via '\\' or unclosed brackets).
    Returns (next_idx, raw_line, clean_line).
    Fault-tolerant: prevents cascading file swallowing on unclosed brackets.
    """
    first_raw = lines[idx]
    first_clean = _strip_comment(first_raw)
    stripped = first_clean.strip()

    bracket_depth = _count_bracket_delta(first_clean)
    ends_with_backslash = stripped.endswith("\\")

    # The line needs joining ONLY if there is an explicit '\' continuation or an unclosed bracket outside quotes
    if not ends_with_backslash and bracket_depth <= 0:
        return idx + 1, first_raw, first_clean

    raw_parts = [first_raw]
    clean_parts = [first_clean]
    curr_idx = idx

    max_lookahead = 50  # Protection against infinite line swallowing
    lookahead_count = 0

    while curr_idx + 1 < len(lines):
        clean_stripped = clean_parts[-1].rstrip()
        ends_with_backslash = clean_stripped.endswith("\\")
        if not ends_with_backslash and bracket_depth <= 0:
            break

        lookahead_count += 1
        if lookahead_count > max_lookahead:
            break

        peek_raw = lines[curr_idx + 1]
        peek_clean = _strip_comment(peek_raw).strip()

        # Block boundary: if there is no explicit backslash '\', and the next line is
        # a new top-level keyword construct (label, screen, init, define, default, transform, image, style, layeredimage),
        # force-stop so we don't swallow another scene on a broken bracket.
        peek_indent = len(peek_raw) - len(peek_raw.lstrip(" "))
        if (
            not ends_with_backslash
            and peek_indent == 0
            and peek_clean.startswith(
                (
                    "label ",
                    "screen ",
                    "init ",
                    "define ",
                    "default ",
                    "transform ",
                    "image ",
                    "style ",
                    "layeredimage ",
                )
            )
        ):
            break

        curr_idx += 1
        next_raw = lines[curr_idx]
        next_clean = _strip_comment(next_raw)

        raw_parts.append(next_raw)
        clean_parts.append(next_clean)
        bracket_depth += _count_bracket_delta(next_clean)

    if len(raw_parts) == 1:
        return idx + 1, first_raw, first_clean

    cleaned_tokens = []
    for p in clean_parts:
        c = p.strip()
        if c.endswith("\\"):
            c = c[:-1].strip()
        if c:
            cleaned_tokens.append(c)

    indent = len(clean_parts[0]) - len(clean_parts[0].lstrip())
    joined_clean = (" " * indent) + " ".join(cleaned_tokens)
    return curr_idx + 1, "".join(raw_parts), joined_clean


@dataclass(slots=True)
class _FileAnalysisState:
    """Per-file mutable state shared across _analyze_file helpers.

    Bundles the 5 checkers + scope stack + file_modified flag so the
    dispatcher can pass a single object instead of 7 parameters.
    """

    scope_stack: ScopeStack
    fmt: FormattingChecker
    screen: ScreenChecker
    asset: AssetChecker
    dialogue: DialogueChecker
    st_checker: StateChecker
    file_modified: bool = False


class SenpyAnalyzer:
    def __init__(
        self,
        project_path: str,
        extra_files: list[str] | None = None,
        fix: bool = False,
        in_memory_files: dict[str, str] | None = None,
        no_cache: bool = False,
        severity_overrides: dict[str, str] | None = None,
    ):
        self.project_path = os.path.abspath(project_path)
        self.cache_manager = CacheManager(self.project_path, enabled=not no_cache)
        self.assets = AssetManager(self.project_path)
        self.python_ast = PythonAstChecker(self)
        self.flow = StoryFlowAnalyzer(self)
        self.deprecated = DeprecationChecker()
        self.extra_files = extra_files or []
        self.fix = fix
        self.in_memory_files = {normalize_path(k): v for k, v in (in_memory_files or {}).items()}

        # Configure severity levels: passed args or the [tool.senpy.severity] section from config
        if severity_overrides is not None:
            self.severity_overrides = {
                k.strip().upper(): v.strip().upper() for k, v in severity_overrides.items()
            }
            # When severity_overrides is passed explicitly, we don't load
            # the rest of the config — assume strict=False (caller manages
            # the full severity policy themselves).
            self.strict = False
        else:
            cfg = load_config(self.project_path)
            self.severity_overrides = {
                k.strip().upper(): v.strip().upper() for k, v in cfg.get("severity", {}).items()
            }
            # strict=True promotes every diagnostic to ERROR (after the
            # explicit severity_overrides have been applied, so overrides
            # still win — see _apply_severity).
            self.strict = bool(cfg.get("strict", False))

        # Base sets — now managed by SymbolTable
        self._symbols = SymbolTable()

        # Other structures and scan metadata
        self.diagnostics: list[Diagnostic] = []
        self.total_lines: int = 0
        self.fixed_count: int = 0
        self.fixable_count: int = 0
        self.file_scopes: dict[str, FileScope] = {}
        self._stage1_lines: dict[str, list[str]] = {}

    # --- SymbolTable delegation (properties) ---
    # All symbol attributes are now backed by SymbolTable.
    # This is transparent to all 17 consumer files — they still access
    # analyzer.variables, analyzer.labels, etc. as before.

    @property
    def variables(self) -> dict[str, VariableSymbol]:
        return self._symbols.variables

    @property
    def labels(self) -> dict[str, LabelSymbol]:
        return self._symbols.labels

    @property
    def screens(self) -> dict[str, ScreenSymbol]:
        return self._symbols.screens

    @property
    def images(self) -> dict[str, ImageSymbol]:
        return self._symbols.images

    @property
    def transforms(self) -> dict[str, TransformSymbol]:
        return self._symbols.transforms

    @property
    def user_symbols(self) -> set[str]:
        return self._symbols.user_symbols

    @property
    def declared_symbols(self) -> set[str]:
        return self._symbols.declared_symbols

    @declared_symbols.setter
    def declared_symbols(self, value: set[str]) -> None:
        self._symbols.declared_symbols = value

    @property
    def referenced_labels(self) -> set[str]:
        return self._symbols.referenced_labels

    @property
    def defined_audio_map(self) -> dict[str, str]:
        return self._symbols.defined_audio_map

    @property
    def registered_audio_channels(self) -> set[str]:
        return self._symbols.registered_audio_channels

    @registered_audio_channels.setter
    def registered_audio_channels(self, value: set[str]) -> None:
        self._symbols.registered_audio_channels = value

    @property
    def jump_sources(self) -> dict[str, list[tuple[str, int]]]:
        return self._symbols.jump_sources

    @property
    def screen_action_jumps(self) -> dict[str, set[str]]:
        return self._symbols.screen_action_jumps

    @property
    def used_screens(self) -> set[str]:
        return self._symbols.used_screens

    @property
    def screen_uses(self) -> dict[str, set[str]]:
        return self._symbols.screen_uses

    @property
    def has_dynamic_jumps(self) -> bool:
        return self._symbols.has_dynamic_jumps

    @has_dynamic_jumps.setter
    def has_dynamic_jumps(self, value: bool) -> None:
        self._symbols.has_dynamic_jumps = value

    @property
    def missing_defaults(self) -> dict[str, str]:
        return self._symbols.missing_defaults

    @staticmethod
    def _get_utf16_range(line: str, sub: str | None = None) -> tuple[int, int]:
        return get_utf16_range(line, sub)

    @property
    def known_assets(self) -> set[str]:
        return self.assets.known_assets

    @property
    def valid_images(self) -> set[str]:
        return self.assets.valid_images

    @property
    def media_disk_files(self) -> dict[str, str]:
        return self.assets.media_disk_files

    @property
    def audio_dir_files(self) -> dict[str, str]:
        return self.assets.audio_dir_files

    @property
    def used_asset_keys(self) -> set[str]:
        return self.assets.used_asset_keys

    @staticmethod
    def find_orphaned_rpyc(project_path: str) -> list[str]:
        return find_orphaned_rpyc(project_path)

    def _mark_asset_used(self, asset_ref: str) -> None:
        self.assets.mark_used(asset_ref)

    def _index_assets(self) -> None:
        self.assets.index()

    def _check_unused_assets(self) -> None:
        self.diagnostics.extend(self.assets.check_unused())

    def run(self, quiet: bool = False) -> AnalysisResult:
        self._run_reset()

        self._index_assets()
        main_rpy, tl_rpy = self._get_rpy_files()
        rpy_files = main_rpy + self.extra_files

        old_manifest = self.cache_manager.load_manifest() if not self.fix else None
        cached_files = old_manifest.files if old_manifest else {}

        file_hashes, stage1_diags_map = self._collect_all_symbols(rpy_files, cached_files, quiet)

        self._rebuild_aggregates()

        current_global_hash = self.cache_manager.compute_global_hash(self)
        is_global_unchanged = (
            old_manifest is not None and old_manifest.global_symbol_hash == current_global_hash
        )

        new_cached_entries = self._analyze_all_files(
            rpy_files, cached_files, file_hashes, stage1_diags_map, is_global_unchanged, quiet
        )

        self._finalize_results(tl_rpy, new_cached_entries, current_global_hash)

        return AnalysisResult(
            diagnostics=self.diagnostics,
            file_count=len(rpy_files) + len(tl_rpy),
            total_lines=self.total_lines,
            fixed_count=self.fixed_count,
            fixable_count=self.fixable_count,
        )

    def _run_reset(self) -> None:
        """Reset all analyzer state for a fresh run."""
        self._symbols.reset()
        self.file_scopes.clear()
        self.diagnostics.clear()
        self.total_lines = 0
        self.fixed_count = 0
        self.fixable_count = 0
        self._stage1_lines.clear()

    def _collect_all_symbols(
        self, rpy_files: list[str], cached_files: dict, quiet: bool
    ) -> tuple[dict[str, str], dict[str, list]]:
        """[1/2] Collect symbols from all .rpy files (Tier 1 cache: restore unchanged FileScope).

        Returns (file_hashes, stage1_diags_map).
        """
        total_files = len(rpy_files)
        file_hashes: dict[str, str] = {}
        stage1_diags_map: dict[str, list] = {}

        for i, file_path in enumerate(rpy_files, 1):
            fname = os.path.basename(file_path)
            norm_path = normalize_path(file_path)
            mtime = os.path.getmtime(file_path) if os.path.exists(file_path) else 0.0
            size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

            if not quiet:
                msg = f"\r[1/2] Сбор символов: {i}/{total_files} ({fname[:25]})"
                progress_print(msg)

            is_tier1_hit = False
            if (
                norm_path in cached_files
                and cached_files[norm_path].mtime == mtime
                and cached_files[norm_path].size == size
                and norm_path not in self.in_memory_files
            ):
                cached_entry = cached_files[norm_path]
                f_hash = compute_file_hash(file_path)
                file_hashes[norm_path] = f_hash
                if cached_entry.content_hash and f_hash == cached_entry.content_hash:
                    self.file_scopes[norm_path] = cached_entry.scope
                    is_tier1_hit = True
                    self.diagnostics.extend(getattr(cached_entry, "collect_diagnostics", ()) or ())

            if not is_tier1_hit:
                f_hash = file_hashes.get(norm_path) or compute_file_hash(file_path)
                file_hashes[norm_path] = f_hash
                diag_start = len(self.diagnostics)
                self._collect_symbols(file_path)
                stage1_diags_map[norm_path] = list(self.diagnostics[diag_start:])

        if not quiet:
            print()

        return file_hashes, stage1_diags_map

    def _analyze_all_files(
        self,
        rpy_files: list[str],
        cached_files: dict,
        file_hashes: dict[str, str],
        stage1_diags_map: dict[str, list],
        is_global_unchanged: bool,
        quiet: bool,
    ) -> dict[str, CachedFileEntry]:
        """[2/2] Analyze all .rpy files for lint rules (Tier 2 cache).

        Returns new_cached_entries for manifest save.
        """
        total_files = len(rpy_files)
        new_cached_entries: dict[str, CachedFileEntry] = {}

        for i, file_path in enumerate(rpy_files, 1):
            fname = os.path.basename(file_path)
            norm_path = normalize_path(file_path)
            mtime = os.path.getmtime(file_path) if os.path.exists(file_path) else 0.0
            size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

            if not quiet:
                msg = f"\r[2/2] Анализ правил: {i}/{total_files} ({fname[:25]})"
                progress_print(msg)

            is_tier2_hit = False
            if (
                is_global_unchanged
                and norm_path in cached_files
                and cached_files[norm_path].mtime == mtime
                and cached_files[norm_path].size == size
                and norm_path not in self.in_memory_files
                and not self.fix
            ):
                entry = cached_files[norm_path]
                f_hash = file_hashes.get(norm_path) or compute_file_hash(file_path)
                if entry.content_hash and f_hash == entry.content_hash:
                    self.diagnostics.extend(entry.diagnostics)
                    self.assets.used_asset_keys.update(entry.used_assets)
                    self.total_lines += entry.lines_count
                    new_cached_entries[norm_path] = entry
                    is_tier2_hit = True

            if not is_tier2_hit:
                diag_start = len(self.diagnostics)
                lines_start = self.total_lines
                used_start = set(self.assets.used_asset_keys)

                self._analyze_file(file_path)

                new_diags = self.diagnostics[diag_start:]
                lines_added = self.total_lines - lines_start
                new_used = self.assets.used_asset_keys - used_start

                if norm_path in self.file_scopes and not self.fix:
                    f_hash = file_hashes.get(norm_path) or compute_file_hash(file_path)
                    new_cached_entries[norm_path] = CachedFileEntry(
                        mtime=mtime,
                        size=size,
                        lines_count=lines_added,
                        scope=self.file_scopes[norm_path],
                        diagnostics=new_diags,
                        used_assets=new_used,
                        content_hash=f_hash,
                        collect_diagnostics=stage1_diags_map.get(norm_path, []),
                    )

        if not quiet:
            print()

        return new_cached_entries

    def _finalize_results(
        self,
        tl_rpy: list[str],
        new_cached_entries: dict[str, CachedFileEntry],
        current_global_hash: str,
    ) -> None:
        """Run post-analysis checks, TL validation, severity overrides, and save cache."""
        from senpy.rules.checkers.translation import (
            analyze_tl_file,
            check_cross_language_consistency,
        )
        from senpy.rules.dead_code import check_unused_declarations

        self._check_unreachable_labels()
        self._check_unused_assets()
        check_unused_declarations(self)

        for tl_file in tl_rpy:
            analyze_tl_file(self, tl_file)

        # RPY802: cross-language consistency — check if the same source
        # string is translated inconsistently across different files within
        # the SAME language directory. Catches copy-paste translation errors
        # where the same source gets two different translations in one lang.
        check_cross_language_consistency(self, tl_rpy)

        if self.severity_overrides:
            for d in self.diagnostics:
                if d.code in self.severity_overrides:
                    d.severity = self.severity_overrides[d.code]

        # strict=True: promote every remaining diagnostic to ERROR.
        # Runs AFTER severity_overrides so an explicit demote (e.g.
        # RPY104=INFO) still wins — see _apply_severity for the same
        # policy on the hot path.
        if self.strict:
            for d in self.diagnostics:
                if d.code not in self.severity_overrides:
                    d.severity = "ERROR"

        if not self.fix and new_cached_entries:
            new_manifest = CacheManifest(
                version=SENPY_VERSION,
                global_symbol_hash=current_global_hash,
                files=new_cached_entries,
            )
            self.cache_manager.save_manifest(new_manifest)

    def _differential_purge_file(self, norm_path: str, file_path: str) -> None:
        """Differentially removes symbols of only one file — delegates to SymbolTable."""
        old_scope = self.file_scopes.pop(norm_path, None)
        if not old_scope:
            return

        self._symbols.purge_object_registries(old_scope)
        self._symbols.purge_jump_sources(old_scope, file_path)
        self._symbols.purge_shared_sets(old_scope, self.file_scopes)

    def _purge_file_symbols(self, norm_path: str) -> None:
        """Full removal of a file's symbols followed by a global rebuild."""
        if norm_path in self.file_scopes:
            del self.file_scopes[norm_path]
            self._rebuild_aggregates()

    def _rebuild_aggregates(self) -> None:
        """Rebuilds global symbol sets — delegates to SymbolTable."""
        self._symbols.rebuild_from_scopes(self.file_scopes)

    def analyze_file_only(self, file_path: str) -> list[Diagnostic]:
        """Fast analysis of only the changed file for LSP without state leakage."""
        file_diags: list[Diagnostic] = []
        old_diags = self.diagnostics
        self.diagnostics = file_diags
        norm_path = normalize_path(file_path)
        try:
            rel_parts = os.path.relpath(file_path, self.project_path).replace("\\", "/").split("/")
        except ValueError:
            # Windows: file_path and project_path are on different drives (D: vs C:)
            # — os.path.relpath fails. Use the absolute path as a fallback.
            rel_parts = file_path.replace("\\", "/").split("/")
        try:
            if "tl" in rel_parts:
                from senpy.rules.checkers.translation import analyze_tl_file

                analyze_tl_file(self, file_path)
            else:
                self._differential_purge_file(norm_path, file_path)
                self._collect_symbols(file_path)
                self._analyze_file(file_path)
        finally:
            self.diagnostics = old_diags
        return file_diags

    def _get_rpy_files(self) -> tuple[list[str], list[str]]:
        main_files: list[str] = []
        tl_files: list[str] = []
        for root, dirs, filenames in os.walk(self.project_path, followlinks=False):
            dirs[:] = sorted([d for d in dirs if d not in IGNORED_DIRS])
            rel_parts = os.path.relpath(root, self.project_path).replace("\\", "/").split("/")
            is_tl_dir = "tl" in rel_parts

            for f in sorted(filenames):
                if f.endswith((".rpy", "_ren.py")):
                    full_p = os.path.join(root, f)
                    if is_tl_dir:
                        tl_files.append(full_p)
                    else:
                        main_files.append(full_p)
        return sorted(main_files), sorted(tl_files)

    def _emit_encoding_error(self, file_path: str, err: UnicodeDecodeError) -> None:
        """RPY100: the file is not readable as UTF-8. Previously the decode error was
        swallowed by `except: pass` — the linter silently skipped the file and reported "clean",
        although Ren'Py will crash when loading such a script."""
        self.diagnostics.append(
            Diagnostic(
                file_path=file_path,
                line_number=1,
                line_content="",
                code="RPY100",
                severity="ERROR",
                message=(
                    f"File is not valid UTF-8 ({err.reason} at byte offset {err.start}). "
                    "Ren'Py requires UTF-8 script files: the game will fail to load it. "
                    "The file was skipped by the linter; re-save it with UTF-8 encoding."
                ),
            )
        )

    def _collect_default(
        self,
        m_def,
        clean: str,
        line: str,
        file_path: str,
        idx: int,
        scope: FileScope,
    ) -> None:
        """Handle `default var = expr` — RPY105, VariableSymbol."""
        var = m_def.group(1)
        if "." in clean.split("=")[0]:
            return
        val_str = m_def.group(2)
        scope.user_symbols.add(var)
        scope.declared_symbols.add(var)
        self.user_symbols.add(var)
        self.declared_symbols.add(var)

        prev_var = self.variables.get(var)
        if prev_var and prev_var.is_constant and not prev_var.is_character:
            prev_file = os.path.basename(prev_var.file_path)
            prev_line = prev_var.line_number
            start_c, end_c = self._get_utf16_range(line, var)
            self.diagnostics.append(
                Diagnostic(
                    file_path=file_path,
                    line_number=idx + 1,
                    line_content=clean,
                    code="RPY105",
                    message=(
                        f"Variable '{var}' is declared with both 'define' and 'default'. "
                        f"Previously declared with 'define' at {prev_file}:{prev_line}. "
                        "Define is for constants and default is for mutable state; choose one to prevent save and rollback corruption."
                    ),
                    severity="ERROR",
                    col=start_c,
                    end_col=end_c,
                )
            )

        inferred_t = infer_expr_type(val_str, known_vars=self.variables)
        var_sym = VariableSymbol(
            name=var,
            file_path=file_path,
            line_number=idx + 1,
            code_line=clean,
            type_name=inferred_t,
            is_constant=False,
            is_character=False,
        )
        scope.variables[var] = var_sym
        self.variables[var] = var_sym

    def _collect_define(
        self,
        m_define,
        clean: str,
        line: str,
        file_path: str,
        idx: int,
        scope: FileScope,
    ) -> None:
        """Handle `define var = expr` — RPY105, VariableSymbol."""
        var = m_define.group(1)
        if "." in clean.split("=")[0]:
            return
        val_str = m_define.group(2)
        scope.user_symbols.add(var)
        scope.declared_symbols.add(var)
        self.user_symbols.add(var)
        self.declared_symbols.add(var)

        prev_var = self.variables.get(var)
        if prev_var and not prev_var.is_constant:
            prev_file = os.path.basename(prev_var.file_path)
            prev_line = prev_var.line_number
            start_c, end_c = self._get_utf16_range(line, var)
            self.diagnostics.append(
                Diagnostic(
                    file_path=file_path,
                    line_number=idx + 1,
                    line_content=clean,
                    code="RPY105",
                    message=(
                        f"Variable '{var}' is declared with both 'define' and 'default'. "
                        f"Previously declared with 'default' at {prev_file}:{prev_line}. "
                        "Define is for constants and default is for mutable state; choose one to prevent save and rollback corruption."
                    ),
                    severity="ERROR",
                    col=start_c,
                    end_col=end_c,
                )
            )

        inferred_t = infer_expr_type(val_str, known_vars=self.variables)
        is_const = "." not in clean.split("=")[0]
        is_char = "Character" in clean or "DynamicCharacter" in clean
        var_sym = VariableSymbol(
            name=var,
            file_path=file_path,
            line_number=idx + 1,
            code_line=clean,
            type_name=inferred_t,
            is_constant=is_const,
            is_character=is_char,
        )
        scope.variables[var] = var_sym
        self.variables[var] = var_sym

    def _collect_define_audio(self, m_audio_def, scope: FileScope) -> None:
        """Handle `define audio.NAME = "file.ogg"`."""
        alias = m_audio_def.group(1)
        target_file = m_audio_def.group(2).replace("\\", "/").lower()
        scope.defined_audio_map[alias] = target_file
        scope.declared_symbols.add(alias)
        scope.declared_symbols.add(f"audio.{alias}")
        self.defined_audio_map[alias] = target_file
        self.declared_symbols.add(alias)
        self.declared_symbols.add(f"audio.{alias}")
        # Register alias → disk path for audio hover. The alias
        # resolves to the *file* named in target_file (relative to game/);
        # we look it up via media_disk_files. Done at parse time so hover
        # never re-reads source files (renpy-magic re-reads per hover —
        # we avoid that anti-pattern).
        self.assets.register_audio_alias(alias, target_file)

    def _collect_screen_transform(
        self,
        m_screen_def,
        m_trans,
        clean: str,
        line: str,
        file_path: str,
        idx: int,
        scope: FileScope,
    ) -> str | None:
        """Handle `screen name(...)` and `transform name(...)`.

        Returns the current screen name (or None) for context.
        """
        if m_screen_def:
            s_name = m_screen_def.group(2)
            s_params = m_screen_def.group(3)
            sig = parse_signature(s_params)
            scr_sym = ScreenSymbol(
                name=s_name, file_path=file_path, line_number=idx + 1, signature=sig
            )
            scope.screens[s_name] = scr_sym
            self.screens[s_name] = scr_sym

        new_screen = None

        # Screen context (screen blocks are always top-level)
        if len(line) - len(line.lstrip(" ")) == 0:
            new_screen = m_screen_def.group(2) if m_screen_def else None

        if m_trans:
            trans_name = m_trans.group(1)
            trans_params = m_trans.group(2)  # None if no params declared
            trans_sig = parse_signature(trans_params) if trans_params else None
            trans_sym = TransformSymbol(
                name=trans_name,
                file_path=file_path,
                line_number=idx + 1,
                code_line=clean,
                signature=trans_sig,
            )
            scope.transforms[trans_name] = trans_sym
            self.transforms[trans_name] = trans_sym
            scope.user_symbols.add(trans_name)
            scope.declared_symbols.add(trans_name)
            self.user_symbols.add(trans_name)
            self.declared_symbols.add(trans_name)

        return new_screen

    def _collect_label(
        self,
        m_label,
        clean: str,
        file_path: str,
        idx: int,
        scope: FileScope,
        current_global_label: str | None,
    ) -> tuple[str, str, str | None]:
        """Handle `label name(params):` — RPY307, LabelSymbol.

        Returns (label_name, current_global_label, current_label).
        """
        raw_name = m_label.group(1)
        if raw_name.startswith("."):
            label_name = f"{current_global_label}{raw_name}" if current_global_label else raw_name
        else:
            label_name = raw_name
            current_global_label = label_name
        if label_name in self.labels:
            if not label_name.startswith("_"):
                prev_file = self.labels[label_name].file_path
                prev_line = self.labels[label_name].line_number
                self.diagnostics.append(
                    Diagnostic(
                        file_path=file_path,
                        line_number=idx + 1,
                        line_content=clean,
                        code="RPY307",
                        message=f"Duplicate label '{label_name}'. Previously declared at {os.path.basename(prev_file)}:{prev_line}. Causes fatal ScriptError.",
                        severity="ERROR",
                    )
                )
        else:
            sig = parse_signature(m_label.group(2))
            lbl_sym = LabelSymbol(
                name=label_name,
                file_path=file_path,
                line_number=idx + 1,
                code_line=clean,
                signature=sig,
            )
            scope.labels[label_name] = lbl_sym
            self.labels[label_name] = lbl_sym

        return label_name, current_global_label, label_name

    def _collect_label_body(
        self,
        clean: str,
        file_path: str,
        idx: int,
        scope: FileScope,
        current_label: str | None,
        current_global_label: str | None,
        current_screen: str | None,
    ) -> None:
        """Handle jump/call/return inside label + screen edges."""
        if current_label:
            if RE_RETURN.match(clean):
                if current_label in scope.labels:
                    scope.labels[current_label].has_return = True
                if current_label in self.labels:
                    self.labels[current_label].has_return = True

            m_jump_in_label = RE_JUMP_TARGET.match(clean)
            if m_jump_in_label:
                raw_target_j = m_jump_in_label.group(1)
                if raw_target_j.startswith("."):
                    target_j = (
                        f"{current_global_label}{raw_target_j}"
                        if current_global_label
                        else raw_target_j
                    )
                else:
                    target_j = raw_target_j

                if current_label in scope.labels:
                    scope.labels[current_label].outgoing_jumps.add(target_j)
                if current_label in self.labels:
                    self.labels[current_label].outgoing_jumps.add(target_j)
                scope.referenced_labels.add(target_j)
                self.referenced_labels.add(target_j)

                self.jump_sources.setdefault(target_j, []).append((file_path, idx + 1))
                scope.jump_sources.setdefault(target_j, []).append((file_path, idx + 1))

        # Edges from screens (Jump/Call actions) and screen usage
        if current_screen:
            for m_act in RE_SCREEN_JUMP_ACTION.finditer(clean):
                scope.screen_action_jumps.setdefault(current_screen, set()).add(m_act.group(1))
                self.screen_action_jumps.setdefault(current_screen, set()).add(m_act.group(1))

        for m_usage in RE_SCREEN_CALL.finditer(clean):
            scope.used_screens.add(m_usage.group(1))
            self.used_screens.add(m_usage.group(1))
            usage_src = current_screen or current_label
            if usage_src:
                scope.screen_uses.setdefault(usage_src, set()).add(m_usage.group(1))
                self.screen_uses.setdefault(usage_src, set()).add(m_usage.group(1))

        for m_show in RE_SCREEN_SHOW_ACTION.finditer(clean):
            scope.used_screens.add(m_show.group(1))
            self.used_screens.add(m_show.group(1))

    def _collect_images(
        self,
        clean: str,
        clean_line: str,
        file_path: str,
        idx: int,
        lines: list[str],
        scope: FileScope,
    ) -> tuple[bool, int]:
        """Handle layeredimage and image declarations — RPY504.

        Returns (was_handled, new_idx).
        """
        m_limg = RE_LAYEREDIMAGE_START.match(clean_line)
        if m_limg:
            limg_indent = len(m_limg.group(1))
            limg_tag = m_limg.group(2).strip()
            next_block_idx, block_lines = self._consume_block(lines, idx + 1, limg_indent)

            attrs: set[str] = set()
            for bl in block_lines:
                clean_bl = _strip_comment(bl).strip()
                m_attr = RE_LAYEREDIMAGE_ATTR.match(clean_bl)
                if m_attr:
                    attrs.add(m_attr.group(1).strip())

            img_sym = ImageSymbol(
                name=limg_tag,
                file_path=file_path,
                line_number=idx + 1,
                body="layeredimage",
                is_layered=True,
                attributes=attrs,
            )
            scope.images[limg_tag] = img_sym
            self.images[limg_tag] = img_sym

            return True, next_block_idx

        m_img = RE_IMAGE_DEF.match(clean)
        if m_img:
            img_name = m_img.group(1).strip()
            img_body = m_img.group(2).strip()

            if img_name in self.images:
                prev_file = self.images[img_name].file_path
                prev_line = self.images[img_name].line_number
                prev_body = self.images[img_name].body
                is_exact_dup = img_body == prev_body
                msg = (
                    f"Duplicate image declaration '{img_name}'. Identical to declaration at {os.path.basename(prev_file)}:{prev_line}."
                    if is_exact_dup
                    else f"Image '{img_name}' is redefined (override). Previously declared at {os.path.basename(prev_file)}:{prev_line}."
                )
                self.diagnostics.append(
                    Diagnostic(
                        file_path=file_path,
                        line_number=idx + 1,
                        line_content=clean,
                        code="RPY504",
                        message=msg,
                        severity="WARNING" if not is_exact_dup else "INFO",
                    )
                )
            img_sym = ImageSymbol(
                name=img_name,
                file_path=file_path,
                line_number=idx + 1,
                body=img_body,
                is_layered=False,
                image_path=_extract_string_literal(img_body),
            )
            scope.images[img_name] = img_sym
            self.images[img_name] = img_sym
            return True, idx  # caller will use next_idx

        return False, idx

    def _collect_misc(
        self,
        clean: str,
        line: str,
        file_path: str,
        idx: int,
        lines: list[str],
        scope: FileScope,
    ) -> tuple[bool, int]:
        """Handle channels, dynamic jumps, quoted strings, init python.

        Returns (was_init_python, new_idx).
        """
        m_chan = re.search(r'renpy\.music\.register_channel\s*\(\s*["\']([^\W\d]\w*)["\']', clean)
        if m_chan:
            chan_name = m_chan.group(1).lower()
            scope.registered_audio_channels.add(chan_name)
            self.registered_audio_channels.add(chan_name)

        if (
            "renpy.call(" in clean
            or "renpy.jump(" in clean
            or "call expression" in clean
            or "jump expression" in clean
        ):
            self.has_dynamic_jumps = True

        if '"' in clean or "'" in clean:
            for str_match in RE_QUOTED_IDENTIFIER.finditer(clean):
                candidate = str_match.group(1)
                if candidate.isidentifier():
                    scope.referenced_labels.add(candidate)
                    self.referenced_labels.add(candidate)

        m_init = RE_INIT_PYTHON_START.match(line)
        if m_init:
            indent = len(m_init.group(1))
            next_idx, block_lines = self._consume_block(lines, idx + 1, indent)
            self._collect_from_python_block(block_lines, scope, file_path, idx + 2)
            return True, next_idx

        return False, idx

    def _collect_symbols(self, file_path: str):
        """Collects symbols from a .rpy file (default/define/screen/label/image/...).

        Phase 3 Step 5 (0.5.6): split from 378 lines into 7 methods + dispatcher.
        """
        try:
            norm_path = normalize_path(file_path)
            scope = FileScope()

            if norm_path in self.in_memory_files:
                lines = self.in_memory_files[norm_path].splitlines(keepends=True)
            else:
                with open(file_path, encoding="utf-8", newline="") as f:
                    lines = f.readlines()
                self._stage1_lines[norm_path] = lines

            if file_path.endswith("_ren.py"):
                self._collect_from_python_block(lines, scope, file_path, 1)
                self.file_scopes[norm_path] = scope
                return

            idx = 0
            current_label: str | None = None
            current_global_label: str | None = None
            current_screen: str | None = None

            while idx < len(lines):
                next_idx, line, clean_line = _get_logical_line(lines, idx)
                clean = clean_line.strip()
                if not clean:
                    idx = next_idx
                    continue

                # --- default ---
                m_def = RE_DEFAULT.match(clean)
                if m_def:
                    self._collect_default(m_def, clean, line, file_path, idx, scope)
                    idx = next_idx
                    continue

                # --- define audio ---
                m_audio_def = RE_DEFINE_AUDIO.match(clean)
                if m_audio_def:
                    self._collect_define_audio(m_audio_def, scope)
                    idx = next_idx
                    continue

                # --- define ---
                m_define = RE_DEFINE.match(clean)
                if m_define:
                    self._collect_define(m_define, clean, line, file_path, idx, scope)
                    idx = next_idx
                    continue

                # --- screen + transform ---
                m_screen_def = RE_SCREEN_START.match(line)
                m_trans = RE_TRANSFORM.match(clean)
                if m_screen_def or m_trans:
                    self._collect_screen_transform(
                        m_screen_def, m_trans, clean, line, file_path, idx, scope
                    )

                # Screen context (screen blocks are always top-level)
                # Important: current_screen is reset to None for ANY top-level line,
                # not only screen. This is needed so `label start:` resets the screen context.
                if len(line) - len(line.lstrip(" ")) == 0:
                    current_screen = m_screen_def.group(2) if m_screen_def else None

                # --- label ---
                m_label = RE_LABEL.match(clean)
                if m_label:
                    label_name, current_global_label, current_label = self._collect_label(
                        m_label, clean, file_path, idx, scope, current_global_label
                    )
                    idx = next_idx
                    continue

                # --- label body (jumps, returns, screen edges) ---
                self._collect_label_body(
                    clean,
                    file_path,
                    idx,
                    scope,
                    current_label,
                    current_global_label,
                    current_screen,
                )

                # --- images (layeredimage + image) ---
                img_handled, img_new_idx = self._collect_images(
                    clean, clean_line, file_path, idx, lines, scope
                )
                if img_handled:
                    idx = img_new_idx if img_new_idx != idx else next_idx
                    continue

                # --- misc (channels, dynamic jumps, strings, init python) ---
                init_handled, init_new_idx = self._collect_misc(
                    clean, line, file_path, idx, lines, scope
                )
                if init_handled:
                    idx = init_new_idx
                    continue

                idx = next_idx

            self.file_scopes[norm_path] = scope

        except UnicodeDecodeError as e:
            self._emit_encoding_error(file_path, e)
        except OSError:
            pass

    def _collect_from_python_block(
        self,
        code_lines: list[str],
        scope: FileScope | None = None,
        file_path: str = "",
        start_line: int = 1,
    ) -> None:
        full_code = "".join(code_lines)
        for m in re.finditer(
            r'renpy\.music\.register_channel\s*\(\s*["\']([^\W\d]\w*)["\']', full_code
        ):
            chan = m.group(1).lower()
            if scope is not None:
                scope.registered_audio_channels.add(chan)
            self.registered_audio_channels.add(chan)

        names, refs = self.python_ast.collect_from_python_block(code_lines)
        for name, line_offset in names.items():
            real_line = start_line + line_offset - 1
            if scope is not None:
                scope.user_symbols.add(name)
                scope.declared_symbols.add(name)
            self.user_symbols.add(name)
            self.declared_symbols.add(name)
            if file_path:
                var_sym = VariableSymbol(
                    name=name,
                    file_path=file_path,
                    line_number=real_line,
                    code_line=f"# definition of {name}",
                    is_constant=False,
                )
                if scope is not None:
                    scope.variables[name] = var_sym
                self.variables[name] = var_sym

        if scope is not None:
            scope.referenced_labels.update(refs)
        self.referenced_labels.update(refs)

    def _consume_block(
        self, lines: list[str], start_idx: int, header_indent: int
    ) -> tuple[int, list[str]]:
        block = []
        idx = start_idx
        while idx < len(lines):
            line = lines[idx]
            stripped = line.strip()
            if not stripped:
                block.append(line)
                idx += 1
                continue

            current_indent = len(line) - len(line.lstrip(" "))
            if stripped.startswith("#") and current_indent <= header_indent:
                break

            if current_indent > header_indent:
                block.append(line)
                idx += 1
            else:
                break

        while block and not block[-1].strip():
            block.pop()
            idx -= 1

        return idx, block

    def _parse_noqa(self, line: str) -> tuple[bool, set[str] | None]:
        m = RE_NOQA.search(line)
        if not m:
            return False, None
        codes_str = m.group(1) or m.group(2)
        if codes_str:
            codes = {c.strip().upper() for c in codes_str.split(",") if c.strip()}
            return True, codes
        return True, None

    def _scan_python_assets(self, code_lines: list[str] | str) -> None:
        """Targeted search for media files in Python blocks (protection against false RPY503 without overhead)."""
        if isinstance(code_lines, str):
            code_lines = [code_lines]
        for line in code_lines:
            if '"' in line or "'" in line:  # Fast-path: ultra-fast pre-filter
                for match in RE_STRING_MATCH.finditer(line):
                    inner = match.group(0).strip("\"'")
                    val_clean = inner.replace("\\", "/").lower().strip()
                    if any(val_clean.endswith(ext) for ext in MEDIA_EXTENSIONS):
                        self._mark_asset_used(val_clean)
                        self._mark_asset_used(os.path.basename(val_clean))

    def _apply_severity(self, diag: Diagnostic) -> None:
        """Applies severity overrides from the config or default levels.

        Resolution order (first match wins):
        1. Explicit ``[tool.senpy.severity]`` override for this rule code.
        2. The diagnostic's own severity (set by the checker).
        3. ``RULE_SEVERITY`` default for this code, falling back to WARNING.
        4. If ``strict`` is True and steps 1-3 did not produce ERROR,
           promote to ERROR. Step 1 (explicit override) still wins over
           strict — otherwise strict mode would silently re-promote a
           rule the user explicitly demoted.
        """
        if self.severity_overrides and diag.code in self.severity_overrides:
            diag.severity = self.severity_overrides[diag.code]
        elif not diag.severity:
            diag.severity = RULE_SEVERITY.get(diag.code, "WARNING")
        if self.strict and diag.code not in self.severity_overrides:
            diag.severity = "ERROR"

    def _add_diagnostic(self, diag: Diagnostic, noqa_map: dict[int, set[str] | None]):
        if diag.line_number in noqa_map:
            ignored_codes = noqa_map[diag.line_number]
            if ignored_codes is None or diag.code in ignored_codes:
                return
        self._apply_severity(diag)
        self.diagnostics.append(diag)

    def _can_reach_return(self, label_name: str, visited: set[str] | None = None) -> bool:
        return self.flow.can_reach_return(label_name, visited)

    def _get_tag_known_attributes(self, base_tag: str, all_valid: set[str]) -> set[str]:
        """Returns all known attributes for a tag (from layeredimage and filesystem structure)."""
        attrs = set()
        if base_tag in self.images and self.images[base_tag].is_layered:
            attrs.update(self.images[base_tag].attributes)
        prefix = base_tag + " "
        for valid_img in all_valid:
            if valid_img.startswith(prefix):
                for token in valid_img[len(prefix) :].split():
                    attrs.add(token)
        return attrs

    def _analyze_file(self, file_path: str):
        """Analyze a single .rpy file: collect symbols and run all lint rules.

        This is the per-file dispatcher. The main loop walks logical lines
        and delegates to 6 checkers (format, screen, asset, dialogue,
        quoted-strings, state) plus init-python-block AST checks.
        """
        lines = self._read_file_lines(file_path)
        if lines is None or file_path.endswith("_ren.py"):
            return

        self.total_lines += len(lines)
        state = _FileAnalysisState(
            scope_stack=ScopeStack(self.declared_symbols),
            fmt=FormattingChecker(self),
            screen=ScreenChecker(self),
            asset=AssetChecker(self),
            dialogue=DialogueChecker(self),
            st_checker=StateChecker(self),
        )
        noqa_map = self._build_noqa_map(lines)

        idx = 0
        while idx < len(lines):
            next_idx, raw_line, clean = _get_logical_line(lines, idx)
            stripped = clean.strip()
            if not stripped:
                idx = next_idx
                continue

            line_indent = len(raw_line) - len(raw_line.lstrip(" "))
            state.scope_stack.pop_to_indent(line_indent)

            raw_line, modified = state.fmt.check_line(
                file_path, idx, raw_line, clean, state.scope_stack, noqa_map, lines
            )
            if modified:
                state.file_modified = True

            init_next = self._handle_init_python_block(lines, idx, file_path, noqa_map)
            if init_next is not None:
                idx = init_next
                continue

            self._push_label_scope_if_match(clean, state, line_indent)

            if self._push_screen_scope_if_match(raw_line, state, line_indent):
                idx += 1
                continue

            next_idx = self._run_line_checkers(
                file_path, idx, next_idx, raw_line, clean, stripped, state, noqa_map, lines
            )
            idx = next_idx

        state.st_checker._pop_and_merge_all_if()
        if state.file_modified and self.fix:
            self._write_fixed_file(file_path, lines)

    def _build_noqa_map(self, lines: list[str]) -> dict[int, set[str] | None]:
        """Pre-parse all `# noqa` comments in the file into a line→codes map."""
        noqa_map: dict[int, set[str] | None] = {}
        for line_no, raw_line in enumerate(lines, start=1):
            has_noqa, codes = self._parse_noqa(raw_line)
            if has_noqa:
                noqa_map[line_no] = codes
        return noqa_map

    def _handle_init_python_block(
        self, lines: list[str], idx: int, file_path: str, noqa_map: dict
    ) -> int | None:
        """Detect `init python:` block and run AST checks on it.

        Returns `next_idx` (the index after the block) if an init block was
        found and processed, or `None` if the current line is not an init
        python block start.
        """
        # Use the raw_line from lines[idx] — format_checker may have modified it.
        raw_line = lines[idx]
        m_init = RE_INIT_PYTHON_START.match(raw_line)
        if not m_init:
            return None

        indent = len(m_init.group(1))
        next_idx, block_lines = self._consume_block(lines, idx + 1, indent)
        if block_lines:
            self._scan_python_assets(block_lines)
            import textwrap

            code = textwrap.dedent("".join(block_lines))
            self.python_ast.check_init_dependency(code, file_path, idx + 2, noqa_map, lines)
            self.python_ast.check_python_ast(code, file_path, idx + 2, noqa_map, lines)
        return next_idx

    def _push_label_scope_if_match(
        self, clean: str, state: _FileAnalysisState, line_indent: int
    ) -> None:
        """If `clean` matches `label X:`, push a LABEL scope and register params."""
        m_label = RE_LABEL.match(clean)
        if not m_label:
            return
        state.scope_stack.push(ScopeType.LABEL, m_label.group(1), line_indent)
        state.st_checker.reset()
        raw_params = m_label.group(2)
        if raw_params:
            for p in raw_params.split(","):
                p_clean = p.split("=")[0].strip()
                if p_clean and p_clean.isidentifier():
                    state.scope_stack.add_symbol(p_clean)

    def _push_screen_scope_if_match(
        self, raw_line: str, state: _FileAnalysisState, line_indent: int
    ) -> bool:
        """If `raw_line` matches `screen X():`, push a SCREEN scope + params.

        Returns True if a screen scope was pushed (caller should `continue`),
        False otherwise.
        """
        m_screen = RE_SCREEN_START.match(raw_line)
        if not m_screen:
            return False
        screen_name = m_screen.group(2)
        state.scope_stack.push(ScopeType.SCREEN, screen_name, line_indent)
        params_str = m_screen.group(3)
        if params_str:
            for p in params_str.split(","):
                p_clean = p.split("=")[0].strip()
                if p_clean and p_clean.isidentifier():
                    state.scope_stack.add_symbol(p_clean)
        return True

    def _run_line_checkers(
        self,
        file_path: str,
        idx: int,
        next_idx: int,
        raw_line: str,
        clean: str,
        stripped: str,
        state: _FileAnalysisState,
        noqa_map: dict,
        lines: list[str],
    ) -> int:
        """Run screen, asset, dialogue, quoted-string, and state checkers
        for one logical line. Returns the next line index (may differ from
        `next_idx` if state_checker overrides it).
        """
        # 2. ScreenChecker (RPY203, RPY204, RPY206)
        state.screen.check_line(file_path, idx, raw_line, clean, state.scope_stack, noqa_map, lines)
        # 3. AssetChecker (RPY501, RPY502)
        state.asset.check_line(file_path, idx, raw_line, clean, state.scope_stack, noqa_map, lines)
        # 4. DialogueChecker (RPY302, RPY305, RPY306, RPY308)
        state.dialogue.check_line(
            file_path,
            idx,
            raw_line,
            clean,
            state.scope_stack,
            noqa_map,
            lines,
            state.st_checker.branch_uninitialized,
        )
        # 5. Quoted strings check (RPY101, RPY301, RPY304)
        if not stripped.startswith(("$", "python")):
            new_line, modified = self._check_and_fix_quoted_strings(
                file_path, idx + 1, raw_line, state.scope_stack.get_local_symbols(), noqa_map
            )
            if modified:
                lines[idx] = new_line
                state.file_modified = True
        # 6. StateChecker (RPY102-106, RPY201, RPY205, RPY401-403)
        next_idx, _ = state.st_checker.check_line(
            file_path, idx, next_idx, raw_line, clean, state.scope_stack, noqa_map, lines
        )
        return next_idx

    def _read_file_lines(self, file_path: str) -> list[str] | None:
        """Read file lines for analysis: in-memory, stage1 cache, or from disk.

        Returns None if file can't be read.
        """
        try:
            norm_path = normalize_path(file_path)
            if norm_path in self.in_memory_files:
                return self.in_memory_files[norm_path].splitlines(keepends=True)
            elif norm_path in self._stage1_lines:
                return self._stage1_lines.pop(norm_path)
            else:
                with open(file_path, encoding="utf-8", newline="") as f:
                    return f.readlines()
        except (UnicodeDecodeError, OSError):
            return None

    def _write_fixed_file(self, file_path: str, lines: list[str]) -> None:
        """Write modified lines back to file (for --fix mode)."""
        try:
            with open(file_path, "w", encoding="utf-8", newline="") as f:
                f.writelines(lines)
        except OSError:
            pass

    def _check_and_fix_quoted_strings(
        self,
        file_path: str,
        line_idx: int,
        raw_line: str,
        extra_symbols: set[str],
        noqa_map: dict,
    ) -> tuple[str, bool]:
        new_line, modified, diags, fixed, fixable, used_assets = process_quoted_strings(
            raw_line=raw_line,
            line_idx=line_idx,
            file_path=file_path,
            declared_symbols=self.declared_symbols,
            extra_symbols=extra_symbols,
            user_symbols=self.user_symbols,
            fix=self.fix,
        )
        for asset in used_assets:
            self._mark_asset_used(asset)
        for diag in diags:
            self._add_diagnostic(diag, noqa_map)
        self.fixed_count += fixed
        self.fixable_count += fixable
        return new_line, modified

    def _check_unreachable_labels(self) -> None:
        self.diagnostics.extend(self.flow.check_unreachable_labels())
        self.diagnostics.extend(self.flow.check_story_islands())

    def _analyze_menu_flow(
        self,
        lines: list[str],
        start_idx: int,
        menu_indent: int,
        file_path: str = "",
        noqa_map: dict | None = None,
    ) -> tuple[int, dict[str, tuple[str, ...]], set[str], bool]:
        return self.flow.analyze_menu_flow(lines, start_idx, menu_indent, file_path, noqa_map)

    def export_graph(self) -> str:
        """Returns a Mermaid.js diagram of the story."""
        return self.flow.generate_mermaid_graph()

    def _clear_safe_cfg_vars(self, py_code: str, branch_uninitialized: dict) -> None:
        self.python_ast.clear_safe_cfg_vars(py_code, branch_uninitialized)

    def _check_cfg_condition(
        self,
        file_path: str,
        line_idx: int,
        line_content: str,
        expr: str,
        branch_uninitialized: dict,
        noqa_map: dict,
    ) -> None:
        self.python_ast.check_cfg_condition(
            file_path, line_idx, line_content, expr, branch_uninitialized, noqa_map
        )

    def _check_cfg_interpolations(
        self,
        file_path: str,
        line_idx: int,
        line_content: str,
        branch_uninitialized: dict[str, tuple[str, str]],
        noqa_map: dict,
    ) -> None:
        self.flow.check_cfg_interpolations(
            file_path, line_idx, line_content, branch_uninitialized, noqa_map
        )

    def _check_screen_mutation(
        self,
        py_code: str,
        file_path: str,
        line_idx: int,
        line_content: str,
        screen_name: str,
        screen_local_symbols: set[str],
        noqa_map: dict,
        lines: list[str] | None = None,
    ) -> None:
        self.python_ast.check_screen_mutation(
            py_code,
            file_path,
            line_idx,
            line_content,
            screen_name,
            screen_local_symbols,
            noqa_map,
            lines,
        )

    def _check_python_ast(
        self,
        py_code: str,
        file_path: str,
        start_line: int,
        noqa_map: dict,
        lines: list[str] | None = None,
    ) -> None:
        self.python_ast.check_python_ast(py_code, file_path, start_line, noqa_map, lines)

    def _check_condition(
        self,
        file_path: str,
        line_idx: int,
        line_content: str,
        expr: str,
        screen_name: str | None,
        screen_local_symbols: set[str],
        noqa_map: dict,
    ) -> None:
        self.python_ast.check_condition(
            file_path, line_idx, line_content, expr, screen_name, screen_local_symbols, noqa_map
        )

    @staticmethod
    def _parse_tl_pairs(lines: list[str]) -> list[tuple[str, int, str, int]]:
        """Parse translation pairs.

        .. deprecated::
            Use ``senpy.rules.checkers.translation.parse_tl_pairs`` directly.
            Kept as a ``@staticmethod`` for backward compat — ``core/coverage.py``
            calls it via ``SenpyAnalyzer._parse_tl_pairs(lines)`` and external
            plugin code may rely on the same path.
        """
        from senpy.rules.checkers.translation import parse_tl_pairs

        return parse_tl_pairs(lines)

    def generate_defaults_file(self) -> tuple[str, int]:
        if not self.missing_defaults:
            return "", 0

        game_dir = os.path.join(self.project_path, "game")
        out_dir = game_dir if os.path.isdir(game_dir) else self.project_path
        out_file = os.path.join(out_dir, "senpy_defaults.rpy")

        lines = [
            "## -----------------------------------------------------------------------------\n",
            "## Automatically generated by Senpy Linter to protect save files and rollback.\n",
            "## -----------------------------------------------------------------------------\n\n",
        ]

        for var, val in sorted(self.missing_defaults.items()):
            lines.append(f"default {var} = {val}\n")

        with open(out_file, "w", encoding="utf-8") as f:
            f.writelines(lines)

        return out_file, len(self.missing_defaults)
