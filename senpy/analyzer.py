from __future__ import annotations

import os
import re
import warnings

from senpy.assets import AssetManager, find_orphaned_rpyc
from senpy.cache import CachedFileEntry, CacheManager, CacheManifest
from senpy.deprecated import DeprecationChecker
from senpy.flow import StoryFlowAnalyzer
from senpy.python_ast import PythonAstChecker, infer_expr_type
from senpy.signature import SignatureInfo, parse_signature
from senpy.text_tags import get_utf16_range, process_quoted_strings

warnings.filterwarnings("ignore", category=SyntaxWarning)

from senpy.checkers import (
    AssetChecker,
    DialogueChecker,
    FormattingChecker,
    ScreenChecker,
    StateChecker,
)

# Импортируем вынесенные модели и константы
from senpy.constants import (
    BUILTIN_AUDIO_CHANNELS,
    BUILTIN_SYMBOLS,
    IGNORED_DIRS,
    NON_DIALOGUE_STATEMENTS,
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
    RE_SCREEN_START,
    SENPY_VERSION,
)
from senpy.models import RULE_SEVERITY, AnalysisResult, Diagnostic, FileScope
from senpy.scope import ScopeStack, ScopeType


def _strip_comment(line: str) -> str:
    """Удаляет комментарий (#), не ломая hex-цвета, экранированные кавычки (\") и тройные кавычки."""
    if '#' not in line:
        return line
    
    in_quote = None
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == '\\':
            i += 2
            continue
        if in_quote in ('"""', "'''"):
            if line[i:i + 3] == in_quote:
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
        if line[i:i + 3] in ('"""', "'''"):
            in_quote = line[i:i + 3]
            i += 3
            continue
        if ch in ('"', "'"):
            in_quote = ch
            i += 1
            continue
        if ch == '#':
            return line[:i]
        i += 1
    return line


def _count_bracket_delta(s: str) -> int:
    """Считает баланс скобок (, [, { вне строковых литералов."""
    delta = 0
    in_quote = None
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == '\\':
            i += 2
            continue
        if in_quote in ('"""', "'''"):
            if s[i:i + 3] == in_quote:
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
        if s[i:i + 3] in ('"""', "'''"):
            in_quote = s[i:i + 3]
            i += 3
            continue
        if ch in ('"', "'"):
            in_quote = ch
            i += 1
            continue
        if ch in '([{':
            delta += 1
        elif ch in ')]}':
            delta -= 1
        i += 1
    return delta


def _get_logical_line(lines: list[str], idx: int) -> tuple[int, str, str]:
    """
    Склеивает многострочные конструкции (перенос через '\\' или незакрытые скобки).
    Возвращает (next_idx, raw_line, clean_line).
    Отказоустойчив: предотвращает каскадное поглощение файла при незакрытых скобках.
    """
    first_raw = lines[idx]
    first_clean = _strip_comment(first_raw)
    stripped = first_clean.strip()

    # Обычные диалоги и короткие строки не требуют заглядывания вперед
    should_check = stripped.endswith('\\') or stripped.startswith((
        "if ", "elif ", "while ", "screen ", "label ",
        "image ", "define ", "default ", "$", "show ", "scene "
    ))

    if not should_check:
        return idx + 1, first_raw, first_clean

    raw_parts = [first_raw]
    clean_parts = [first_clean]
    bracket_depth = _count_bracket_delta(first_clean)
    curr_idx = idx

    max_lookahead = 50  # Защита от бесконечного поглощения строк
    lookahead_count = 0

    while curr_idx + 1 < len(lines):
        clean_stripped = clean_parts[-1].rstrip()
        ends_with_backslash = clean_stripped.endswith('\\')
        if not ends_with_backslash and bracket_depth <= 0:
            break

        lookahead_count += 1
        if lookahead_count > max_lookahead:
            break

        peek_raw = lines[curr_idx + 1]
        peek_clean = _strip_comment(peek_raw).strip()

        # Граница блока: если нет явного обратного слэша '\', а следующая строка —
        # новая ключевая конструкция верхнего уровня (label, screen, init, define, default),
        # принудительно останавливаемся, чтобы не поглотить чужую сцену при сломанной скобке.
        peek_indent = len(peek_raw) - len(peek_raw.lstrip(" "))
        if not ends_with_backslash and peek_indent == 0 and peek_clean.startswith((
            "label ", "screen ", "init ", "define ", "default "
        )):
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
        if c.endswith('\\'):
            c = c[:-1].strip()
        if c:
            cleaned_tokens.append(c)

    indent = len(clean_parts[0]) - len(clean_parts[0].lstrip())
    joined_clean = (" " * indent) + " ".join(cleaned_tokens)
    return curr_idx + 1, "".join(raw_parts), joined_clean

class SenpyAnalyzer:
    def __init__(
        self,
        project_path: str,
        extra_files: list[str] | None = None,
        fix: bool = False,
        in_memory_files: dict[str, str] | None = None,
        no_cache: bool = False,
    ):
        self.project_path = os.path.abspath(project_path)
        self.cache_manager = CacheManager(self.project_path, enabled=not no_cache)
        self.assets = AssetManager(self.project_path)
        self.python_ast = PythonAstChecker(self)
        self.flow = StoryFlowAnalyzer(self)
        self.deprecated = DeprecationChecker()
        self.extra_files = extra_files or []
        self.fix = fix
        self.in_memory_files = {
            os.path.normcase(os.path.abspath(k)): v
            for k, v in (in_memory_files or {}).items()
        }
        self.user_symbols: set[str] = set()
        self.declared_symbols: set[str] = set(BUILTIN_SYMBOLS)
        self.defined_constants: set[str] = set()
        self.declared_characters: set[str] = set()
        self.declared_labels: dict[str, tuple[str, int, str]] = {}
        self.declared_screens: dict[str, tuple[str, int]] = {}
        self.label_signatures: dict[str, SignatureInfo] = {}
        self.screen_signatures: dict[str, SignatureInfo] = {}
        self.labels_with_return: set[str] = set()
        self.label_outgoing_jumps: dict[str, set[str]] = {}
        self.declared_images: dict[str, tuple[str, int, str]] = {}
        self.declared_layeredimages: dict[str, set[str]] = {}
        self.symbol_declarations: dict[str, tuple[str, int, str]] = {}
        self.symbol_types: dict[str, str] = {}
        self.jump_sources: dict[str, list[tuple[str, int]]] = {}
        self.referenced_labels: set[str] = set()
        self.has_dynamic_jumps: bool = False
        self.diagnostics: list[Diagnostic] = []
        self.missing_defaults: dict[str, str] = {}
        self.total_lines: int = 0
        self.fixed_count: int = 0
        self.fixable_count: int = 0
        self.defined_audio_map: dict[str, str] = {}
        self.registered_audio_channels: set[str] = set(BUILTIN_AUDIO_CHANNELS)
        self.file_scopes: dict[str, FileScope] = {}
        

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
        self.file_scopes.clear()
        self.missing_defaults.clear()
        self.diagnostics.clear()
        self.user_symbols.clear()
        self.declared_symbols = set(BUILTIN_SYMBOLS)
        self.declared_labels.clear()
        self.declared_screens.clear()
        self.label_signatures.clear()
        self.screen_signatures.clear()
        self.referenced_labels.clear()
        self.labels_with_return.clear()
        self.label_outgoing_jumps.clear()
        self.jump_sources.clear()
        self.declared_images.clear()
        self.declared_layeredimages.clear()
        self.defined_audio_map.clear()
        self.registered_audio_channels = set(BUILTIN_AUDIO_CHANNELS)
        self.symbol_declarations.clear()
        self.symbol_types.clear()
        self.has_dynamic_jumps = False
        self.total_lines = 0
        self.fixed_count = 0
        self.fixable_count = 0
        self.defined_constants.clear()
        self.declared_characters.clear()

        self._index_assets()
        main_rpy, tl_rpy = self._get_rpy_files()
        rpy_files = main_rpy + self.extra_files
        total_files = len(rpy_files)

        # 0. Загрузка кэша
        old_manifest = self.cache_manager.load_manifest() if not self.fix else None
        cached_files = old_manifest.files if old_manifest else {}
        new_cached_entries: dict[str, CachedFileEntry] = {}

        # [1/2] Сбор символов (Tier 1 Cache: восстановление неизмененных FileScope)
        for i, file_path in enumerate(rpy_files, 1):
            fname = os.path.basename(file_path)
            norm_path = os.path.normcase(os.path.abspath(file_path))

            mtime = os.path.getmtime(file_path) if os.path.exists(file_path) else 0.0
            size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

            # Проверяем Tier 1 hit
            if norm_path in cached_files and cached_files[norm_path].mtime == mtime and cached_files[norm_path].size == size and norm_path not in self.in_memory_files:
                cached_scope = cached_files[norm_path].scope
                self.file_scopes[norm_path] = cached_scope
            else:
                if not quiet:
                    msg = f"\r[1/2] Сбор символов: {i}/{total_files} ({fname[:25]})"
                    print(msg.ljust(75), end="", flush=True)
                self._collect_symbols(file_path)

        if not quiet:
            print()

        self._rebuild_aggregates()

        # [2/2] Анализ правил (Tier 2 Cache: если глобальные символы не изменились — мгновенно отдаем диагностики)
        current_global_hash = self.cache_manager.compute_global_hash(self)
        is_global_unchanged = (old_manifest is not None and old_manifest.global_symbol_hash == current_global_hash)

        for i, file_path in enumerate(rpy_files, 1):
            fname = os.path.basename(file_path)
            norm_path = os.path.normcase(os.path.abspath(file_path))

            mtime = os.path.getmtime(file_path) if os.path.exists(file_path) else 0.0
            size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

            # Проверяем Tier 2 hit
            if is_global_unchanged and norm_path in cached_files and cached_files[norm_path].mtime == mtime and cached_files[norm_path].size == size and norm_path not in self.in_memory_files and not self.fix:
                entry = cached_files[norm_path]
                self.diagnostics.extend(entry.diagnostics)
                self.assets.used_asset_keys.update(entry.used_assets)
                self.total_lines += entry.lines_count
                new_cached_entries[norm_path] = entry
            else:
                if not quiet:
                    msg = f"\r[2/2] Анализ правил: {i}/{total_files} ({fname[:25]})"
                    print(msg.ljust(75), end="", flush=True)

                diag_start = len(self.diagnostics)
                lines_start = self.total_lines
                used_start = set(self.assets.used_asset_keys)

                self._analyze_file(file_path)

                new_diags = self.diagnostics[diag_start:]
                lines_added = self.total_lines - lines_start
                new_used = self.assets.used_asset_keys - used_start

                if norm_path in self.file_scopes and not self.fix:
                    new_cached_entries[norm_path] = CachedFileEntry(
                        mtime=mtime,
                        size=size,
                        lines_count=lines_added,
                        scope=self.file_scopes[norm_path],
                        diagnostics=new_diags,
                        used_assets=new_used,
                    )

        if not quiet:
            print()

        self._check_unreachable_labels()
        self._check_unused_assets()

        # [3/3] Валидация файлов перевода (TL-Checker)
        for tl_file in tl_rpy:
            self._analyze_tl_file(tl_file)

        # Сохранение обновленного манифеста
        if not self.fix and new_cached_entries:
            new_manifest = CacheManifest(
                version=SENPY_VERSION,
                global_symbol_hash=current_global_hash,
                files=new_cached_entries,
            )
            self.cache_manager.save_manifest(new_manifest)

        return AnalysisResult(
            diagnostics=self.diagnostics,
            file_count=len(rpy_files) + len(tl_rpy),
            total_lines=self.total_lines,
            fixed_count=self.fixed_count,
            fixable_count=self.fixable_count,
        )

    def _purge_file_symbols(self, norm_path: str) -> None:
        """Удаляет символы файла из кэша и пересобирает глобальные таблицы."""
        if norm_path in self.file_scopes:
            del self.file_scopes[norm_path]
            self._rebuild_aggregates()

    def _rebuild_aggregates(self) -> None:
        """Пересобирает глобальные множества символов на основе scopes всех остальных файлов."""
        self.label_outgoing_jumps.clear()
        self.declared_symbols = set(BUILTIN_SYMBOLS)
        self.user_symbols.clear()
        self.defined_constants.clear()
        self.declared_characters.clear()
        self.declared_labels.clear()
        self.declared_screens.clear()
        self.declared_images.clear()
        self.declared_layeredimages.clear()
        self.defined_audio_map.clear()
        self.registered_audio_channels = set(BUILTIN_AUDIO_CHANNELS)
        for scope in self.file_scopes.values():
            self.registered_audio_channels.update(scope.registered_audio_channels)
        self.referenced_labels.clear()
        self.labels_with_return.clear()

        self.label_signatures.clear()
        self.screen_signatures.clear()
        self.symbol_declarations.clear()
        self.symbol_types.clear()
        self.jump_sources.clear()

        for scope in self.file_scopes.values():
            self.declared_symbols.update(scope.declared_symbols)
            self.user_symbols.update(scope.user_symbols)
            self.defined_constants.update(scope.defined_constants)
            self.declared_characters.update(scope.declared_characters)
            self.declared_labels.update(scope.declared_labels)
            self.declared_screens.update(scope.declared_screens)
            self.declared_images.update(scope.declared_images)
            self.symbol_declarations.update(getattr(scope, "symbol_declarations", {}))
            self.symbol_types.update(getattr(scope, "symbol_types", {}))
            self.label_signatures.update(getattr(scope, "label_signatures", {}))
            self.screen_signatures.update(getattr(scope, "screen_signatures", {}))
            for tgt, locs in getattr(scope, "jump_sources", {}).items():
                self.jump_sources.setdefault(tgt, []).extend(locs)
            for tag, attrs in scope.declared_layeredimages.items():
                self.declared_layeredimages.setdefault(tag, set()).update(attrs)
            self.defined_audio_map.update(scope.defined_audio_map)
            self.referenced_labels.update(scope.referenced_labels)
            self.labels_with_return.update(scope.labels_with_return)
            for lbl, targets in scope.label_outgoing_jumps.items():
                self.label_outgoing_jumps.setdefault(lbl, set()).update(targets)

    def analyze_file_only(self, file_path: str) -> list[Diagnostic]:
        """Быстрый анализ только одного измененного файла для LSP без утечки состояния."""
        file_diags: list[Diagnostic] = []
        old_diags = self.diagnostics
        self.diagnostics = file_diags
        norm_path = os.path.normcase(os.path.abspath(file_path))
        rel_parts = os.path.relpath(file_path, self.project_path).replace("\\", "/").split("/")
        try:
            if "tl" in rel_parts:
                self._analyze_tl_file(file_path)
            else:
                self._purge_file_symbols(norm_path)
                self._collect_symbols(file_path)
                self._analyze_file(file_path)
        finally:
            self.diagnostics = old_diags
        return file_diags

    def _get_rpy_files(self) -> tuple[list[str], list[str]]:
        main_files: list[str] = []
        tl_files: list[str] = []
        for root, dirs, filenames in os.walk(self.project_path):
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

    def _collect_symbols(self, file_path: str):
        try:
            norm_path = os.path.normcase(os.path.abspath(file_path))
            scope = FileScope()

            if norm_path in self.in_memory_files:
                lines = self.in_memory_files[norm_path].splitlines(keepends=True)
            else:
                with open(file_path, "r", encoding="utf-8", newline="") as f:
                    lines = f.readlines()

            if file_path.endswith("_ren.py"):
                self._collect_from_python_block(lines, scope, file_path, 1)
                self.file_scopes[norm_path] = scope
                return

            idx = 0
            current_label: str | None = None

            while idx < len(lines):
                next_idx, line, clean_line = _get_logical_line(lines, idx)
                clean = clean_line.strip()
                if not clean:
                    idx = next_idx
                    continue

                m_def = RE_DEFAULT.match(clean)
                if m_def:
                    var = m_def.group(1)
                    val_str = m_def.group(2)
                    scope.user_symbols.add(var)
                    scope.declared_symbols.add(var)
                    scope.symbol_declarations[var] = (file_path, idx + 1, clean)
                    self.user_symbols.add(var)
                    self.declared_symbols.add(var)
                    self.symbol_declarations[var] = (file_path, idx + 1, clean)

                    inferred_t = infer_expr_type(val_str)
                    if inferred_t:
                        scope.symbol_types[var] = inferred_t
                        self.symbol_types[var] = inferred_t

                    idx = next_idx
                    continue

                m_audio_def = RE_DEFINE_AUDIO.match(clean)
                if m_audio_def:
                    alias = m_audio_def.group(1)
                    target_file = m_audio_def.group(2).replace("\\", "/").lower()
                    scope.defined_audio_map[alias] = target_file
                    scope.declared_symbols.add(alias)
                    scope.declared_symbols.add(f"audio.{alias}")
                    self.defined_audio_map[alias] = target_file
                    self.declared_symbols.add(alias)
                    self.declared_symbols.add(f"audio.{alias}")
                    idx = next_idx
                    continue

                m_define = RE_DEFINE.match(clean)
                if m_define:
                    var = m_define.group(1)
                    val_str = m_define.group(2)
                    scope.user_symbols.add(var)
                    scope.declared_symbols.add(var)
                    scope.symbol_declarations[var] = (file_path, idx + 1, clean)
                    self.user_symbols.add(var)
                    self.declared_symbols.add(var)
                    self.symbol_declarations[var] = (file_path, idx + 1, clean)
                    inferred_t = infer_expr_type(val_str)
                    if inferred_t:
                        scope.symbol_types[var] = inferred_t
                        self.symbol_types[var] = inferred_t
                    # Если define настраивает свойство (config.xxx, gui.xxx, persistent.xxx), не считаем корень константой
                    if "." not in clean.split("=")[0]:
                        scope.defined_constants.add(var)
                        self.defined_constants.add(var)

                    if "Character" in clean or "DynamicCharacter" in clean:
                        scope.declared_characters.add(var)
                        self.declared_characters.add(var)

                    idx = next_idx
                    continue

                m_screen_def = RE_SCREEN_START.match(line)
                if m_screen_def:
                    s_name = m_screen_def.group(2)
                    s_params = m_screen_def.group(3)
                    sig = parse_signature(s_params)
                    scope.declared_screens[s_name] = (file_path, idx + 1)
                    scope.screen_signatures[s_name] = sig
                    self.declared_screens[s_name] = (file_path, idx + 1)
                    self.screen_signatures[s_name] = sig

                m_label = RE_LABEL.match(clean)
                if m_label:
                    label_name = m_label.group(1)
                    if label_name in self.declared_labels:
                        if not label_name.startswith("_"):
                            prev_file, prev_line, _ = self.declared_labels[label_name]
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
                        scope.declared_labels[label_name] = (file_path, idx + 1, clean)
                        self.declared_labels[label_name] = (file_path, idx + 1, clean)

                    current_label = label_name
                    scope.label_outgoing_jumps[label_name] = set()
                    self.label_outgoing_jumps[label_name] = set()

                    raw_params = m_label.group(2)
                    sig = parse_signature(raw_params)
                    scope.label_signatures[label_name] = sig
                    self.label_signatures[label_name] = sig

                    idx = next_idx
                    continue

                if current_label:
                    if RE_RETURN.match(clean):
                        scope.labels_with_return.add(current_label)
                        self.labels_with_return.add(current_label)

                    m_jump_in_label = RE_JUMP_TARGET.match(clean)
                    if m_jump_in_label:
                        target_j = m_jump_in_label.group(1)
                        scope.label_outgoing_jumps.setdefault(current_label, set()).add(target_j)
                        self.label_outgoing_jumps.setdefault(current_label, set()).add(target_j)
                        self.jump_sources.setdefault(target_j, []).append((file_path, idx + 1))
                        scope.jump_sources.setdefault(target_j, []).append((file_path, idx + 1))

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

                    scope.declared_layeredimages[limg_tag] = attrs
                    self.declared_layeredimages[limg_tag] = attrs
                    # Регистрируем базовый тег как валидный спрайт
                    scope.declared_images[limg_tag] = (file_path, idx + 1, "layeredimage")
                    self.declared_images[limg_tag] = (file_path, idx + 1, "layeredimage")

                    idx = next_block_idx
                    continue

                m_img = RE_IMAGE_DEF.match(clean)
                if m_img:
                    img_name = m_img.group(1).strip()
                    img_body = m_img.group(2).strip()

                    if img_name in self.declared_images:
                        prev_file, prev_line, prev_body = self.declared_images[img_name]
                        is_exact_dup = (img_body == prev_body)
                        msg = (
                            f"Duplicate image declaration '{img_name}'. Identical to declaration at {os.path.basename(prev_file)}:{prev_line}."
                            if is_exact_dup else
                            f"Image '{img_name}' is redefined (override). Previously declared at {os.path.basename(prev_file)}:{prev_line}."
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
                    scope.declared_images[img_name] = (file_path, idx + 1, img_body)
                    self.declared_images[img_name] = (file_path, idx + 1, img_body)
                    idx = next_idx
                    continue

                m_chan = re.search(r'renpy\.music\.register_channel\s*\(\s*["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']', clean)
                if m_chan:
                    chan_name = m_chan.group(1).lower()
                    scope.registered_audio_channels.add(chan_name)
                    self.registered_audio_channels.add(chan_name)

                if "renpy.call(" in clean or "renpy.jump(" in clean or "call expression" in clean or "jump expression" in clean:
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
                    idx = next_idx
                    continue

                idx = next_idx

            self.file_scopes[norm_path] = scope

        except (UnicodeDecodeError, OSError):
            pass

    def _collect_from_python_block(
        self, code_lines: list[str], scope: FileScope | None = None, file_path: str = "", start_line: int = 1
    ) -> None:
        full_code = "".join(code_lines)
        for m in re.finditer(r'renpy\.music\.register_channel\s*\(\s*["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']', full_code):
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
                if file_path:
                    scope.symbol_declarations[name] = (file_path, real_line, f"# definition of {name}")
            self.user_symbols.add(name)
            self.declared_symbols.add(name)
            if file_path:
                self.symbol_declarations[name] = (file_path, real_line, f"# definition of {name}")
        
        if scope is not None:
            scope.referenced_labels.update(refs)
        self.referenced_labels.update(refs)

    def _consume_block(self, lines: list[str], start_idx: int, header_indent: int) -> tuple[int, list[str]]:
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

    def _add_diagnostic(self, diag: Diagnostic, noqa_map: dict[int, set[str] | None]):
        if diag.line_number in noqa_map:
            ignored_codes = noqa_map[diag.line_number]
            if ignored_codes is None or diag.code in ignored_codes:
                return
        if not diag.severity:
            diag.severity = RULE_SEVERITY.get(diag.code, "WARNING")
        self.diagnostics.append(diag)

    def _can_reach_return(self, label_name: str, visited: set[str] | None = None) -> bool:
        return self.flow.can_reach_return(label_name, visited)

    def _get_tag_known_attributes(self, base_tag: str, all_valid: set[str]) -> set[str]:
        """Возвращает все известные атрибуты для тега (из layeredimage и файловой структуры)."""
        attrs = set(self.declared_layeredimages.get(base_tag, set()))
        prefix = base_tag + " "
        for valid_img in all_valid:
            if valid_img.startswith(prefix):
                for token in valid_img[len(prefix):].split():
                    attrs.add(token)
        return attrs

    def _analyze_file(self, file_path: str):
        try:
            norm_path = os.path.normcase(os.path.abspath(file_path))
            if norm_path in self.in_memory_files:
                lines = self.in_memory_files[norm_path].splitlines(keepends=True)
            else:
                with open(file_path, "r", encoding="utf-8", newline="") as f:
                    lines = f.readlines()
            if file_path.endswith("_ren.py"):
                return

            self.total_lines += len(lines)
            file_modified = False

            scope_stack = ScopeStack(self.declared_symbols)
            format_checker = FormattingChecker(self)
            screen_checker = ScreenChecker(self)
            asset_checker = AssetChecker(self)
            dialogue_checker = DialogueChecker(self)
            state_checker = StateChecker(self)

            noqa_map: dict[int, set[str] | None] = {}
            for line_no, raw_line in enumerate(lines, start=1):
                has_noqa, codes = self._parse_noqa(raw_line)
                if has_noqa:
                    noqa_map[line_no] = codes

            idx = 0
            while idx < len(lines):
                next_idx, raw_line, clean = _get_logical_line(lines, idx)
                stripped = clean.strip()

                if not stripped:
                    idx = next_idx
                    continue

                line_indent = len(raw_line) - len(raw_line.lstrip(" "))
                scope_stack.pop_to_indent(line_indent)

                # 1. FormattingChecker (RPY001, RPY002, RPY107)
                raw_line, modified = format_checker.check_line(
                    file_path, idx, raw_line, clean, scope_stack, noqa_map, lines
                )
                if modified:
                    file_modified = True

                m_init = RE_INIT_PYTHON_START.match(raw_line)
                if m_init:
                    indent = len(m_init.group(1))
                    next_idx, block_lines = self._consume_block(lines, idx + 1, indent)
                    if block_lines:
                        import textwrap
                        code = textwrap.dedent("".join(block_lines))
                        self.python_ast.check_init_dependency(
                            code, file_path, idx + 2, noqa_map, lines
                        )
                        # Также проверяем стандартные правила (устаревший API и т.д.)
                        self.python_ast.check_python_ast(
                            code, file_path, idx + 2, noqa_map, lines
                        )
                    idx = next_idx
                    continue

                # Scope: Labels
                m_label = RE_LABEL.match(clean)
                if m_label:
                    scope_stack.push(ScopeType.LABEL, m_label.group(1), line_indent)
                    state_checker.reset()
                    raw_params = m_label.group(2)
                    if raw_params:
                        for p in raw_params.split(","):
                            p_clean = p.split("=")[0].strip()
                            if p_clean and p_clean.isidentifier():
                                scope_stack.add_symbol(p_clean)

                # Scope: Screens
                m_screen = RE_SCREEN_START.match(raw_line)
                if m_screen:
                    screen_name = m_screen.group(2)
                    scope_stack.push(ScopeType.SCREEN, screen_name, line_indent)
                    params_str = m_screen.group(3)
                    if params_str:
                        for p in params_str.split(","):
                            p_clean = p.split("=")[0].strip()
                            if p_clean and p_clean.isidentifier():
                                scope_stack.add_symbol(p_clean)
                    idx += 1
                    continue

                # 2. ScreenChecker (RPY203, RPY204, RPY206)
                _, _ = screen_checker.check_line(
                    file_path, idx, raw_line, clean, scope_stack, noqa_map, lines
                )

                # 3. AssetChecker (RPY501, RPY502)
                _, _ = asset_checker.check_line(
                    file_path, idx, raw_line, clean, scope_stack, noqa_map, lines
                )

                # 4. DialogueChecker (RPY302, RPY305, RPY306, RPY308)
                _, _ = dialogue_checker.check_line(
                    file_path, idx, raw_line, clean, scope_stack, noqa_map, lines, state_checker.branch_uninitialized
                )

                # 5. Проверка кавычек, интерполяций и тегов (RPY101, RPY301, RPY304)
                new_line, modified = self._check_and_fix_quoted_strings(
                    file_path, idx + 1, raw_line, scope_stack.get_local_symbols(), noqa_map
                )
                if modified:
                    lines[idx] = new_line
                    file_modified = True

                # 6. StateChecker (RPY102-106, RPY201, RPY205, RPY401-403)
                next_idx, _ = state_checker.check_line(
                    file_path, idx, next_idx, raw_line, clean, scope_stack, noqa_map, lines
                )

                idx = next_idx

            if file_modified and self.fix:
                with open(file_path, "w", encoding="utf-8", newline="") as f:
                    f.writelines(lines)

        except (UnicodeDecodeError, OSError):
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
    ) -> tuple[int, dict[str, tuple[str, str]]]:
        return self.flow.analyze_menu_flow(lines, start_idx, menu_indent, file_path, noqa_map)

    def export_graph(self) -> str:
        """Возвращает Mermaid.js диаграмму сюжета."""
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
            py_code, file_path, line_idx, line_content, screen_name, screen_local_symbols, noqa_map, lines
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

    def _analyze_tl_file(self, file_path: str):
        try:
            norm_path = os.path.normcase(os.path.abspath(file_path))
            if norm_path in self.in_memory_files:
                lines = self.in_memory_files[norm_path].splitlines(keepends=True)
            else:
                with open(file_path, "r", encoding="utf-8", newline="") as f:
                    lines = f.readlines()
        except (UnicodeDecodeError, OSError):
            return

        self.total_lines += len(lines)
        pairs = self._parse_tl_pairs(lines)
        self._validate_tl_pairs(pairs, file_path)

    @staticmethod
    def _parse_tl_pairs(lines: list[str]) -> list[tuple[str, int, str, int]]:
        """
        Конечный автомат (State Machine). Собирает безопасные пары:
        (исходный_текст, строка_old, текст_перевода, строка_new)
        Устойчив к комментариям, пустым строкам, voice/with и пропущенным new.
        """
        re_old = re.compile(r'^\s*old\s+("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')')
        re_new = re.compile(r'^\s*new\s+("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')')
        re_dialogue_old = re.compile(
            r'^\s*#\s*(?:(?:[a-zA-Z0-9_]+|"[^"]*"|\'[^\']*\')(?:\s+[a-zA-Z0-9_]+)*\s+)?("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')'
        )
        re_dialogue_new = re.compile(
            r'^\s*(?:(?:[a-zA-Z0-9_]+|"[^"]*"|\'[^\']*\')(?:\s+[a-zA-Z0-9_]+)*\s+)?("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')'
        )

        pairs = []
        pending_old = None
        pending_old_line = 0

        for line_no, raw_line in enumerate(lines, start=1):
            clean = raw_line.strip()
            if not clean:
                continue

            # 1. Поиск для translate strings: (old / new)
            m_old = re_old.match(clean)
            if m_old:
                s = m_old.group(1)
                pending_old = s[1:-1]
                pending_old_line = line_no
                continue

            m_new = re_new.match(clean)
            if m_new:
                if pending_old is not None:
                    s = m_new.group(1)
                    pairs.append((pending_old, pending_old_line, s[1:-1], line_no))
                    pending_old = None
                    pending_old_line = 0
                continue

            # 2. Поиск для диалоговых блоков translate: (# "оригинал" / "перевод")
            if clean.startswith("#"):
                m_d_old = re_dialogue_old.match(clean)
                if m_d_old:
                    s = m_d_old.group(1)
                    pending_old = s[1:-1]
                    pending_old_line = line_no
                continue
            else:
                first_word = clean.split()[0] if clean.split() else ""
                # Пропускаем служебные команды внутри диалога (voice, with, $, play, scene и т.д.)
                if first_word in NON_DIALOGUE_STATEMENTS or clean.startswith("translate "):
                    if clean.startswith("translate "):
                        pending_old = None
                    continue

                if pending_old is not None:
                    m_d_new = re_dialogue_new.match(clean)
                    if m_d_new:
                        s = m_d_new.group(1)
                        pairs.append((pending_old, pending_old_line, s[1:-1], line_no))
                    pending_old = None
                    pending_old_line = 0

        return pairs

    def _validate_tl_pairs(self, pairs: list[tuple[str, int, str, int]], file_path: str):
        from collections import Counter
        re_var = re.compile(r"\[([a-zA-Z_][a-zA-Z0-9_]*)(?:![a-zA-Z]+)?\]")
        re_tag = re.compile(r"\{(/?[a-zA-Z_]+)(?:=[^}]*)?\}")

        for old_txt, old_line, new_txt, new_line in pairs:
            # Маскируем экранированные скобки \[ и \{
            old_masked = re.sub(r"\\.|(\{\{|\}\}|\[\[|\]\])", "  ", old_txt)
            new_masked = re.sub(r"\\.|(\{\{|\}\}|\[\[|\]\])", "  ", new_txt)

            # RPY603: Пустой перевод
            if old_txt.strip() and not new_txt.strip():
                start_c, end_c = self._get_utf16_range(f'new "{new_txt}"', new_txt)
                self.diagnostics.append(
                    Diagnostic(
                        file_path=file_path,
                        line_number=new_line,
                        line_content=f'new "{new_txt}"',
                        code="RPY603",
                        message="Translation string is empty ('new \"\"'). Players will see blank text.",
                        severity="WARNING",
                        col=start_c,
                        end_col=end_c,
                    )
                )
                continue

            # RPY601: Сверка переменных [var]
            old_vars = Counter(re_var.findall(old_masked))
            new_vars = Counter(re_var.findall(new_masked))
            missing = old_vars - new_vars
            extra = new_vars - old_vars

            if missing or extra:
                diffs = []
                if missing:
                    diffs.append(f"lost: {', '.join(f'[{v}]' for v in missing)}")
                if extra:
                    diffs.append(f"typo/extra: {', '.join(f'[{v}]' for v in extra)}")

                start_c, end_c = self._get_utf16_range(new_txt, next(iter(extra)) if extra else None)
                self.diagnostics.append(
                    Diagnostic(
                        file_path=file_path,
                        line_number=new_line,
                        line_content=new_txt,
                        code="RPY601",
                        message=f"Variable mismatch in translation ({'; '.join(diffs)}). Will crash with KeyError at runtime!",
                        severity="ERROR",
                        col=start_c,
                        end_col=end_c,
                    )
                )

            # RPY602: Сверка тегов форматирования {b}, {color} и т.д.
            old_tags = Counter(re_tag.findall(old_masked))
            new_tags = Counter(re_tag.findall(new_masked))
            if old_tags != new_tags:
                self.diagnostics.append(
                    Diagnostic(
                        file_path=file_path,
                        line_number=new_line,
                        line_content=new_txt,
                        code="RPY602",
                        message="Formatting tags count or names do not match the original string. Text styles may break.",
                        severity="WARNING",
                    )
                )

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