"""AnalysisPipeline — orchestration extracted from SenpyAnalyzer.

Manages the analysis lifecycle:
  1. run() — top-level orchestrator: reset → collect → analyze → finalize → return
  2. _analyze_all_files — Tier 2 cache check + per-file analysis loop
  3. _analyze_file — per-file dispatcher: logical line loop → checkers
  4. _finalize_results — post-analysis: dead code, TL, severity, cache save
  5. _run_line_checkers — run 6 checkers for one logical line
  6. _push_label_scope_if_match / _push_screen_scope_if_match — scope management
  7. _apply_severity / _add_diagnostic — diagnostic management
  8. _check_and_fix_quoted_strings — RPY101/301/304
  9. analyze_file_only — LSP fast-path (no global state pollution)

Before this extraction, SenpyAnalyzer was 855 lines. After: ~400 lines
(facade: __init__ + properties + delegation wrappers).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from senpy.core.cache import CachedFileEntry, compute_file_hash
from senpy.core.constants import RE_LABEL, RE_SCREEN_START
from senpy.core.file_collector import build_noqa_map
from senpy.core.models import RULE_SEVERITY, AnalysisResult, Diagnostic
from senpy.core.paths import normalize_path
from senpy.core.progress import progress_print
from senpy.core.scope import ScopeStack, ScopeType
from senpy.domain.text_tags import process_quoted_strings
from senpy.rules.checkers import (
    AssetChecker,
    DialogueChecker,
    FormattingChecker,
    ScreenChecker,
    StateChecker,
)
from senpy.text_utils import _get_logical_line

if TYPE_CHECKING:
    from senpy.core.analyzer import SenpyAnalyzer


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


class AnalysisPipeline:
    """Orchestrates the full analysis lifecycle.

    Takes an analyzer reference and delegates:
      - Symbol storage → analyzer's SymbolTable (via properties)
      - File collection → analyzer's FileCollector
      - Per-file analysis → 6 checkers (Formatting, Screen, Asset, Dialogue, State, QuotedStrings)
      - Cache → analyzer's CacheManager
      - Diagnostics → analyzer.diagnostics list
    """

    def __init__(self, analyzer: SenpyAnalyzer) -> None:
        self.analyzer = analyzer

    def run(self, quiet: bool = False) -> AnalysisResult:
        """Top-level orchestrator: reset → collect → analyze → finalize."""
        a = self.analyzer
        a._run_reset()

        a._index_assets()
        main_rpy, tl_rpy = a._get_rpy_files()
        rpy_files = main_rpy + a.extra_files

        old_manifest = a.cache_manager.load_manifest() if not a.fix else None
        cached_files = old_manifest.files if old_manifest else {}

        file_hashes, stage1_diags_map = a._collect_all_symbols(rpy_files, cached_files, quiet)

        a._rebuild_aggregates()

        current_global_hash = a.cache_manager.compute_global_hash(a)
        is_global_unchanged = (
            old_manifest is not None and old_manifest.global_symbol_hash == current_global_hash
        )

        new_cached_entries = self._analyze_all_files(
            rpy_files, cached_files, file_hashes, stage1_diags_map, is_global_unchanged, quiet
        )

        self._finalize_results(tl_rpy, new_cached_entries, current_global_hash)

        return AnalysisResult(
            diagnostics=a.diagnostics,
            file_count=len(rpy_files) + len(tl_rpy),
            total_lines=a.total_lines,
            fixed_count=a.fixed_count,
            fixable_count=a.fixable_count,
        )

    def _analyze_all_files(
        self,
        rpy_files: list[str],
        cached_files: dict,
        file_hashes: dict[str, str],
        stage1_diags_map: dict[str, list],
        is_global_unchanged: bool,
        quiet: bool,
    ) -> dict[str, CachedFileEntry]:
        """[2/2] Analyze all .rpy files for lint rules (Tier 2 cache)."""
        a = self.analyzer
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
                and norm_path not in a.in_memory_files
                and not a.fix
            ):
                entry = cached_files[norm_path]
                f_hash = file_hashes.get(norm_path) or compute_file_hash(file_path)
                if entry.content_hash and f_hash == entry.content_hash:
                    a.diagnostics.extend(entry.diagnostics)
                    a.assets.used_asset_keys.update(entry.used_assets)
                    a.total_lines += entry.lines_count
                    # Restore per-file fixable/fixed counters so warm runs
                    # report the same totals as cold. Without this the CLI
                    # silently drops the "[*] N fixable with the --fix option"
                    # footer on cached runs.
                    a.fixable_count += getattr(entry, "fixable_count", 0)
                    a.fixed_count += getattr(entry, "fixed_count", 0)
                    new_cached_entries[norm_path] = entry
                    is_tier2_hit = True

            if not is_tier2_hit:
                diag_start = len(a.diagnostics)
                lines_start = a.total_lines
                used_start = set(a.assets.used_asset_keys)
                fixable_start = a.fixable_count
                fixed_start = a.fixed_count

                self._analyze_file(file_path)

                new_diags = a.diagnostics[diag_start:]
                lines_added = a.total_lines - lines_start
                new_used = a.assets.used_asset_keys - used_start
                fixable_added = a.fixable_count - fixable_start
                fixed_added = a.fixed_count - fixed_start

                if norm_path in a.file_scopes and not a.fix:
                    f_hash = file_hashes.get(norm_path) or compute_file_hash(file_path)
                    new_cached_entries[norm_path] = CachedFileEntry(
                        mtime=mtime,
                        size=size,
                        lines_count=lines_added,
                        scope=a.file_scopes[norm_path],
                        diagnostics=new_diags,
                        used_assets=new_used,
                        content_hash=f_hash,
                        collect_diagnostics=stage1_diags_map.get(norm_path, []),
                        fixable_count=fixable_added,
                        fixed_count=fixed_added,
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
        from senpy.__version__ import __version__ as SENPY_VERSION
        from senpy.core.cache import CacheManifest
        from senpy.rules.checkers.translation import (
            analyze_tl_file,
            check_cross_language_consistency,
        )
        from senpy.rules.dead_code import check_unused_declarations

        a = self.analyzer

        a._check_unreachable_labels()
        a._check_unused_assets()
        check_unused_declarations(a)

        for tl_file in tl_rpy:
            analyze_tl_file(a, tl_file)

        check_cross_language_consistency(a, tl_rpy)

        if a.severity_overrides:
            for d in a.diagnostics:
                if d.code in a.severity_overrides:
                    d.severity = a.severity_overrides[d.code]

        if a.strict:
            for d in a.diagnostics:
                if d.code not in a.severity_overrides:
                    d.severity = "ERROR"

        if not a.fix and new_cached_entries:
            new_manifest = CacheManifest(
                version=SENPY_VERSION,
                global_symbol_hash=current_global_hash,
                files=new_cached_entries,
            )
            a.cache_manager.save_manifest(new_manifest)

    def _analyze_file(self, file_path: str) -> None:
        """Analyze a single .rpy file: collect symbols and run all lint rules."""
        a = self.analyzer
        lines = a._read_file_lines(file_path)
        if lines is None or file_path.endswith("_ren.py"):
            return

        a.total_lines += len(lines)
        state = _FileAnalysisState(
            scope_stack=ScopeStack(a.declared_symbols),
            fmt=FormattingChecker(a),
            screen=ScreenChecker(a),
            asset=AssetChecker(a),
            dialogue=DialogueChecker(a),
            st_checker=StateChecker(a),
        )
        noqa_map = build_noqa_map(lines)
        # Persist the per-file noqa map so that cross-file rules
        # (RPY701 through RPY707 and RPY802) running later in
        # _finalize_results can honour inline suppression directives on the
        # declaration line of the symbol they fire on.
        a._noqa_maps[normalize_path(file_path)] = noqa_map

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

            init_next = a._handle_init_python_block(lines, idx, file_path, noqa_map)
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
        if state.file_modified and a.fix:
            self._write_fixed_file(file_path, lines)

    def _push_label_scope_if_match(self, clean: str, state: Any, line_indent: int) -> None:
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

    def _push_screen_scope_if_match(self, raw_line: str, state: Any, line_indent: int) -> bool:
        """If `raw_line` matches `screen X():`, push a SCREEN scope + params."""
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
        state: Any,
        noqa_map: dict,
        lines: list[str],
    ) -> int:
        """Run screen, asset, dialogue, quoted-string, and state checkers
        for one logical line."""

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

    def _check_and_fix_quoted_strings(
        self,
        file_path: str,
        line_idx: int,
        raw_line: str,
        extra_symbols: set[str],
        noqa_map: dict,
    ) -> tuple[str, bool]:
        a = self.analyzer
        new_line, modified, diags, fixed, fixable, used_assets = process_quoted_strings(
            raw_line=raw_line,
            line_idx=line_idx,
            file_path=file_path,
            declared_symbols=a.declared_symbols,
            extra_symbols=extra_symbols,
            user_symbols=a.user_symbols,
            fix=a.fix,
        )
        for asset in used_assets:
            a._mark_asset_used(asset)
        for diag in diags:
            self._add_diagnostic(diag, noqa_map)
        a.fixed_count += fixed
        a.fixable_count += fixable
        return new_line, modified

    def _apply_severity(self, diag: Diagnostic) -> None:
        """Applies severity overrides from the config or default levels."""
        a = self.analyzer
        if a.severity_overrides and diag.code in a.severity_overrides:
            diag.severity = a.severity_overrides[diag.code]
        elif not diag.severity:
            diag.severity = RULE_SEVERITY.get(diag.code, "WARNING")
        if a.strict and diag.code not in a.severity_overrides:
            diag.severity = "ERROR"

    def _add_diagnostic(self, diag: Diagnostic, noqa_map: dict[int, set[str] | None]) -> None:
        if diag.line_number in noqa_map:
            ignored_codes = noqa_map[diag.line_number]
            if ignored_codes is None or diag.code in ignored_codes:
                return
        self._apply_severity(diag)
        self.analyzer.diagnostics.append(diag)

    def _write_fixed_file(self, file_path: str, lines: list[str]) -> None:
        """Write modified lines back to file (for --fix mode)."""
        try:
            with open(file_path, "w", encoding="utf-8", newline="") as f:
                f.writelines(lines)
        except OSError:
            pass

    def analyze_file_only(self, file_path: str) -> list[Diagnostic]:
        """Fast analysis of only the changed file for LSP without state leakage."""
        a = self.analyzer
        file_diags: list[Diagnostic] = []
        old_diags = a.diagnostics
        a.diagnostics = file_diags
        norm_path = normalize_path(file_path)
        try:
            rel_parts = os.path.relpath(file_path, a.project_path).replace("\\", "/").split("/")
        except ValueError:
            rel_parts = file_path.replace("\\", "/").split("/")
        try:
            if "tl" in rel_parts:
                from senpy.rules.checkers.translation import analyze_tl_file

                analyze_tl_file(a, file_path)
            else:
                a._differential_purge_file(norm_path, file_path)
                a._collect_symbols(file_path)
                self._analyze_file(file_path)
        finally:
            a.diagnostics = old_diags
        return file_diags
