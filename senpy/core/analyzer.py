from __future__ import annotations

import os
from typing import Any

from senpy.core.analysis_pipeline import AnalysisPipeline
from senpy.core.cache import CacheManager
from senpy.core.config import load_config, validate_config
from senpy.core.file_collector import (
    FileCollector,
    build_noqa_map,
    discover_rpy_files,
    emit_encoding_error,
    read_file_lines,
)
from senpy.core.logging import get_logger
from senpy.core.models import AnalysisResult, Diagnostic, FileScope
from senpy.core.paths import normalize_path
from senpy.core.symbol_table import SymbolTable
from senpy.core.symbols import (
    ImageSymbol,
    LabelSymbol,
    ScreenSymbol,
    TransformSymbol,
    VariableSymbol,
)
from senpy.domain.assets import AssetManager, find_orphaned_rpyc
from senpy.domain.text_tags import get_utf16_range
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

_logger = get_logger("analyzer")

# Extract the first quoted string literal from a Python expression
# body. Used for `image name = "path"` and `image name = Transform("path", …)`
# so ImageSymbol.image_path can be populated at parse time (renpy-magic's
# extractAssetPath does the same in TS; we cover the common cases here).


class SenpyAnalyzer:
    def __init__(
        self,
        project_path: str,
        extra_files: list[str] | None = None,
        fix: bool = False,
        in_memory_files: dict[str, str] | None = None,
        no_cache: bool = False,
        severity_overrides: dict[str, str] | None = None,
        strict: bool | None = None,
        cache_dir: str | None = None,
        config_path: str | None = None,
        config: dict[str, Any] | None = None,
    ):
        self.project_path = os.path.abspath(project_path)
        # cache_dir: passed through to CacheManager (CLI --cache-dir).
        # None = default <project>/.senpy_cache.
        self.cache_manager = CacheManager(
            self.project_path, enabled=not no_cache, cache_dir=cache_dir
        )
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
            # Plugin execution is also caller-managed: explicit callers
            # (e.g. tests, LSP) default to plugins OFF unless they opt in
            # via the dedicated constructor argument. Reading senpy.toml
            # here would surprise callers that pass severity_overrides
            # expecting full programmatic control.
            self.enable_plugins = False
            # Same caller-managed reasoning for the user-extended Ren'Py
            # built-ins: callers that pass severity_overrides bypass the
            # config, so they get the shipped defaults only. Tests that
            # need extension should construct a SenpyConfig / cfg dict
            # themselves.
            self._additional_builtins: set[str] = set()
            self._additional_actions: set[str] = set()
        elif config is not None:
            # Explicit programmatic config — caller passes a dict that
            # follows the same schema as ``senpy.toml [tool.senpy]``
            # (see ``senpy.core.config.SenpyConfig`` for the canonical
            # field list). Validated via pydantic so a missing/typo'd
            # field surfaces as a logged WARNING + empty-config fallback
            # rather than a silent misconfiguration.
            #
            # This branch enables ``analyze_code(code, config=...)``
            # in the public API to override severity / ignore / strict /
            # additional_builtins etc. without writing a senpy.toml file.
            cfg = validate_config(config)
            self.severity_overrides = {
                k.strip().upper(): v.strip().upper() for k, v in cfg.get("severity", {}).items()
            }
            self.strict = bool(strict) if strict is not None else bool(cfg.get("strict", False))
            self.enable_plugins = bool(cfg.get("enable_plugins", False))
            self._additional_builtins = set(cfg.get("additional_builtins", []))
            self._additional_actions = set(cfg.get("additional_actions", []))
        else:
            cfg = load_config(self.project_path, config_path=config_path)
            self.severity_overrides = {
                k.strip().upper(): v.strip().upper() for k, v in cfg.get("severity", {}).items()
            }
            # strict=True promotes every diagnostic to ERROR (after the
            # explicit severity_overrides have been applied, so overrides
            # still win — see _apply_severity).
            # The `strict` constructor argument (CLI --strict) overrides
            # the config value: --strict forces strict=True even if
            # senpy.toml says strict=false. None (default) = use config.
            self.strict = bool(strict) if strict is not None else bool(cfg.get("strict", False))
            # Plugin rule execution is opt-in for 0.8.0 (default False).
            # When True, registered Rule subclasses are invoked per-file
            # during _analyze_file (see T-003 in WORKLOG).
            self.enable_plugins = bool(cfg.get("enable_plugins", False))
            # User-extended Ren'Py built-ins / screen actions
            # (`senpy.toml [tool.senpy].additional_builtins` /
            # `.additional_actions`). Merged with the shipped defaults in
            # `BUILTIN_SYMBOLS` / `BUILTIN_ACTIONS` so the user does not
            # need to redeclare what Senpy already knows about. Used by
            # `SymbolTable.declared_symbols` (for namespaces) and by
            # `ScreenChecker._check_buttons` (for actions).
            self._additional_builtins = set(cfg.get("additional_builtins", []))
            self._additional_actions = set(cfg.get("additional_actions", []))

        # Base sets — now managed by SymbolTable. The user-extended
        # built-ins are passed in so they survive reset() / rebuild and
        # reach the rule checkers via `declared_symbols`.
        self._symbols = SymbolTable(additional_builtins=self._additional_builtins)
        self._collector = FileCollector(self)
        self._pipeline = AnalysisPipeline(self)

        # Other structures and scan metadata
        self.diagnostics: list[Diagnostic] = []
        self.total_lines: int = 0
        self.fixed_count: int = 0
        self.fixable_count: int = 0
        # File paths that --fix could not write back (read-only / permission
        # denied / disk full / ...). Surfaced via AnalysisResult.failed_writes
        # so runner.main() can exit non-zero and the user is told the fixes
        # were not applied.
        self.failed_writes: list[str] = []
        self.file_scopes: dict[str, FileScope] = {}
        self._stage1_lines: dict[str, list[str]] = {}
        # Per-file noqa maps accumulated during _analyze_file; consumed by
        # cross-file rules (RPY701-707, RPY802). Initialised here (not just
        # in _run_reset) so that analyze_file_only — which can be called
        # without a prior run() in LSP fast-path tests — does not crash
        # with AttributeError.
        self._noqa_maps: dict[str, dict[int, set[str] | None]] = {}

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

    def run(self, quiet: bool = False, dry_run_callback=None) -> AnalysisResult:
        """Run analysis. See AnalysisPipeline.run for parameter docs."""
        return self._pipeline.run(quiet, dry_run_callback=dry_run_callback)

    def _run_reset(self) -> None:
        """Reset all analyzer state for a fresh run."""
        self._symbols.reset()
        self.file_scopes.clear()
        self.diagnostics.clear()
        self.total_lines = 0
        self.fixed_count = 0
        self.fixable_count = 0
        self.failed_writes.clear()
        self._stage1_lines.clear()
        # Per-file noqa maps accumulated during _analyze_file; consumed by
        # cross-file rules (RPY701-707, RPY802) which emit diagnostics for
        # files that have already been analysed. Reset here so a warm run
        # does not leak stale directives from the previous pass.
        self._noqa_maps: dict[str, dict[int, set[str] | None]] = {}

    def _get_noqa_map_for_file(self, file_path: str) -> dict[int, set[str] | None]:
        """Return the ``# noqa`` directive map for ``file_path``.

        Returns an empty dict if the file was never analysed (e.g. a brand
        new file that has no diagnostics yet, or a file that was skipped
        due to a Tier 2 cache hit). Callers that emit cross-file
        diagnostics (RPY701-707, RPY802) use this to honour ``# noqa``
        directives on the declaration line of the symbol they fire on.
        """
        return self._noqa_maps.get(normalize_path(file_path), {})

    def _add_diagnostic_by_file(self, diag) -> None:
        """Emit a diagnostic for a specific file, honouring its noqa map.

        Used by cross-file rules (RPY701-707, RPY802) whose diagnostics
        target a declaration line in a file that has already been
        analysed. Looks up the per-file ``noqa_map`` populated during
        ``_analyze_file`` and delegates to ``_add_diagnostic``.

        If the target file was never analysed (no noqa map), the
        diagnostic is still emitted — ``# noqa`` suppression is a
        best-effort convenience, not a hard contract.
        """
        noqa_map = self._get_noqa_map_for_file(diag.file_path)
        self._add_diagnostic(diag, noqa_map)

    def _collect_all_symbols(self, *args, **kwargs):
        return self._collector._collect_all_symbols(*args, **kwargs)

    def _analyze_all_files(self, *args, **kwargs):
        return self._pipeline._analyze_all_files(*args, **kwargs)

    def _finalize_results(self, *args, **kwargs):
        return self._pipeline._finalize_results(*args, **kwargs)

    def _differential_purge_file(self, norm_path: str, file_path: str) -> None:
        """Differentially removes symbols of only one file — delegates to SymbolTable."""
        old_scope = self.file_scopes.pop(norm_path, None)
        if not old_scope:
            return

        self._symbols.purge_object_registries(old_scope, self.file_scopes)
        self._symbols.purge_jump_sources(old_scope, file_path)
        self._symbols.purge_shared_sets(old_scope, self.file_scopes)

    def _rebuild_aggregates(self) -> None:
        """Rebuilds global symbol sets — delegates to SymbolTable."""
        self._symbols.rebuild_from_scopes(self.file_scopes)
        # Restore audio aliases into AssetManager.audio_name_to_path.
        # On Tier 1 cache hit, _collect_symbols() is skipped (cached
        # FileScope is restored directly), so register_audio_alias() is
        # never called. rebuild_from_scopes() restores defined_audio_map
        # (alias→target_path), but NOT audio_name_to_path (the disk-path
        # index that resolve_audio_path() uses for hover). Without this
        # loop, audio hover stops working after the first (cold) run.
        for alias, target_file in self._symbols.defined_audio_map.items():
            self.assets.register_audio_alias(alias, target_file)

    def analyze_file_only(self, file_path):
        return self._pipeline.analyze_file_only(file_path)

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

    def _apply_severity(self, diag):
        return self._pipeline._apply_severity(diag)

    def _add_diagnostic(self, diag, noqa_map):
        return self._pipeline._add_diagnostic(diag, noqa_map)

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
        return self._pipeline._analyze_file(file_path)

    def _build_noqa_map(self, lines: list[str]) -> dict[int, set[str] | None]:
        return build_noqa_map(lines)

    def _handle_init_python_block(self, *args, **kwargs):
        return self._collector._handle_init_python_block(*args, **kwargs)

    def _push_label_scope_if_match(self, *args, **kwargs):
        return self._pipeline._push_label_scope_if_match(*args, **kwargs)

    def _push_screen_scope_if_match(self, *args, **kwargs):
        return self._pipeline._push_screen_scope_if_match(*args, **kwargs)

    def _run_line_checkers(self, *args, **kwargs):
        return self._pipeline._run_line_checkers(*args, **kwargs)

    def _read_file_lines(self, file_path: str) -> list[str] | None:
        return read_file_lines(file_path, self.in_memory_files, self._stage1_lines)

    def _write_fixed_file(self, file_path, lines):
        return self._pipeline._write_fixed_file(file_path, lines)

    def _check_and_fix_quoted_strings(self, *args, **kwargs):
        return self._pipeline._check_and_fix_quoted_strings(*args, **kwargs)

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
        already_guaranteed: set[str] | None = None,
    ) -> tuple[int, dict[str, tuple[str, ...]], set[str], bool]:
        return self.flow.analyze_menu_flow(
            lines,
            start_idx,
            menu_indent,
            file_path,
            noqa_map,
            already_guaranteed=already_guaranteed,
        )

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
        """Generate ``senpy_defaults.rpy`` with ``default`` declarations
        for every variable in ``self.missing_defaults``.

        Returns ``(out_file, count)``. On a successful write, ``out_file``
        is the absolute path written and ``count`` is the number of
        declarations. If ``missing_defaults`` is empty, returns ``("", 0)``
        without touching the filesystem.

        On ``OSError`` (read-only ``game/`` directory, disk full, path
        too long, missing parent directory after a race, ...), the failure
        is logged at WARNING level and the target path is appended to
        ``self.failed_writes`` — same pattern as
        ``AnalysisPipeline._write_fixed_file`` (R-P0-6). This lets
        ``runner._force_nonzero_if_failed_writes`` force exit code 1 and
        ``runner._print_failed_writes_summary`` print a clean user-facing
        summary, reusing the existing failed-writes infrastructure rather
        than inventing a parallel defaults-error path. Returns
        ``("", 0)`` so the caller (``handle_defaults``) treats it as
        "nothing was generated" rather than crashing the CLI with a raw
        traceback (audit BUG-3).
        """
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

        try:
            with open(out_file, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except OSError as e:
            _logger.warning("Failed to write defaults file to %s: %s", out_file, e)
            self.failed_writes.append(out_file)
            return "", 0

        return out_file, len(self.missing_defaults)
