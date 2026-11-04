from __future__ import annotations

import os
from dataclasses import dataclass

from senpy.core.cache import CachedFileEntry, CacheManager, CacheManifest, compute_file_hash
from senpy.core.config import load_config
from senpy.core.constants import (
    RE_LABEL,
    RE_SCREEN_START,
    SENPY_VERSION,
)
from senpy.core.file_collector import (
    FileCollector,
    build_noqa_map,
    discover_rpy_files,
    emit_encoding_error,
    read_file_lines,
)
from senpy.core.models import RULE_SEVERITY, AnalysisResult, Diagnostic, FileScope
from senpy.core.paths import normalize_path
from senpy.core.progress import progress_print
from senpy.core.scope import ScopeStack, ScopeType
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
from senpy.rules.python_ast import PythonAstChecker

# Phase 1.3 (0.5.3): _strip_comment was moved to senpy/text_utils.py to break
# the circular dependency checkers/flow → analyzer. Re-exported for backward compat.
from senpy.text_utils import (  # noqa: E402, F401
    _count_bracket_delta,
    _get_logical_line,
    _strip_comment,
)

# Extract the first quoted string literal from a Python expression
# body. Used for `image name = "path"` and `image name = Transform("path", …)`
# so ImageSymbol.image_path can be populated at parse time (renpy-magic's
# extractAssetPath does the same in TS; we cover the common cases here).


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
        self._collector = FileCollector(self)

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

    def _collect_all_symbols(self, *args, **kwargs):
        return self._collector._collect_all_symbols(*args, **kwargs)

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
        return discover_rpy_files(self.project_path)

    def _emit_encoding_error(self, file_path: str, err: UnicodeDecodeError) -> None:
        emit_encoding_error(file_path, err, self.diagnostics)

    def _collect_default(self, *args, **kwargs):
        return self._collector._collect_default(*args, **kwargs)

    def _collect_define(self, *args, **kwargs):
        return self._collector._collect_define(*args, **kwargs)

    def _collect_define_audio(self, *args, **kwargs):
        return self._collector._collect_define_audio(*args, **kwargs)

    def _collect_screen_transform(self, *args, **kwargs):
        return self._collector._collect_screen_transform(*args, **kwargs)

    def _collect_label(self, *args, **kwargs):
        return self._collector._collect_label(*args, **kwargs)

    def _collect_label_body(self, *args, **kwargs):
        return self._collector._collect_label_body(*args, **kwargs)

    def _collect_images(self, *args, **kwargs):
        return self._collector._collect_images(*args, **kwargs)

    def _collect_misc(self, *args, **kwargs):
        return self._collector._collect_misc(*args, **kwargs)

    def _collect_symbols(self, *args, **kwargs):
        return self._collector._collect_symbols(*args, **kwargs)

    def _collect_from_python_block(self, *args, **kwargs):
        return self._collector._collect_from_python_block(*args, **kwargs)

    def _consume_block(self, *args, **kwargs):
        return self._collector._consume_block(*args, **kwargs)

    def _parse_noqa(self, line: str) -> tuple[bool, set[str] | None]:
        from senpy.core.file_collector import parse_noqa

        return parse_noqa(line)

    def _scan_python_assets(self, *args, **kwargs):
        return self._collector._scan_python_assets(*args, **kwargs)

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
        return build_noqa_map(lines)

    def _handle_init_python_block(self, *args, **kwargs):
        return self._collector._handle_init_python_block(*args, **kwargs)

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
        return read_file_lines(file_path, self.in_memory_files, self._stage1_lines)

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
