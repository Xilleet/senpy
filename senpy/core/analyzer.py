from __future__ import annotations

import os
import re
import warnings
from collections import defaultdict

from senpy.core.cache import CachedFileEntry, CacheManager, CacheManifest, compute_file_hash
from senpy.core.config import load_config
from senpy.core.constants import (
    BUILTIN_AUDIO_CHANNELS,
    BUILTIN_SCREENS,
    BUILTIN_SYMBOLS,
    IGNORED_DIRS,
    MEDIA_EXTENSIONS,
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
    RE_SCREEN_CALL,
    RE_SCREEN_JUMP_ACTION,
    RE_SCREEN_SHOW_ACTION,
    RE_SCREEN_START,
    RE_STRING_MATCH,
    RE_TRANSFORM,
    SENPY_VERSION,
)
from senpy.core.models import RULE_SEVERITY, AnalysisResult, Diagnostic, FileScope
from senpy.core.scope import ScopeStack, ScopeType
from senpy.core.signature import parse_signature
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

warnings.filterwarnings("ignore", category=SyntaxWarning)



# Pre-compiled regex for word tokenization. Used by _check_unused_declarations
# to build a word→locations index in a single pass over all files (O(N+M)
# instead of O(N*M) for naive per-symbol re.search loop).
_WORD_RE = re.compile(r"\w+")


# Фаза 1.3 (0.5.3): _strip_comment вынесен в senpy/text_utils.py для разрыва
# циклической зависимости checkers/flow → analyzer. Реэкспортируем для backward compat.
from senpy.text_utils import _strip_comment  # noqa: E402, F401


def _count_bracket_delta(s: str) -> int:
    """Считает баланс скобок (, [, { вне строковых литералов."""
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
    Склеивает многострочные конструкции (перенос через '\\' или незакрытые скобки).
    Возвращает (next_idx, raw_line, clean_line).
    Отказоустойчив: предотвращает каскадное поглощение файла при незакрытых скобках.
    """
    first_raw = lines[idx]
    first_clean = _strip_comment(first_raw)
    stripped = first_clean.strip()

    bracket_depth = _count_bracket_delta(first_clean)
    ends_with_backslash = stripped.endswith("\\")

    # Строка требует склейки ТОЛЬКО если есть явный перенос '\' или незакрытая скобка вне кавычек
    if not ends_with_backslash and bracket_depth <= 0:
        return idx + 1, first_raw, first_clean

    raw_parts = [first_raw]
    clean_parts = [first_clean]
    curr_idx = idx

    max_lookahead = 50  # Защита от бесконечного поглощения строк
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

        # Граница блока: если нет явного обратного слэша '\', а следующая строка —
        # новая ключевая конструкция верхнего уровня (label, screen, init, define, default, transform, image, style, layeredimage),
        # принудительно останавливаемся, чтобы не поглотить чужую сцену при сломанной скобке.
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
        self.in_memory_files = {
            os.path.normcase(os.path.abspath(k)): v for k, v in (in_memory_files or {}).items()
        }

        # Настройка уровней строгости: переданные аргументы или секция [tool.senpy.severity] из конфига
        if severity_overrides is not None:
            self.severity_overrides = {
                k.strip().upper(): v.strip().upper() for k, v in severity_overrides.items()
            }
        else:
            cfg = load_config(self.project_path)
            self.severity_overrides = {
                k.strip().upper(): v.strip().upper() for k, v in cfg.get("severity", {}).items()
            }

        # Базовые множества
        self.user_symbols: set[str] = set()
        self.declared_symbols: set[str] = set(BUILTIN_SYMBOLS)
        self.referenced_labels: set[str] = set()
        self.defined_audio_map: dict[str, str] = {}
        self.registered_audio_channels: set[str] = set(BUILTIN_AUDIO_CHANNELS)

        # --- Новые объектные реестры (заменяют 13 старых словарей) ---
        self.variables: dict[str, VariableSymbol] = {}
        self.labels: dict[str, LabelSymbol] = {}
        self.screens: dict[str, ScreenSymbol] = {}
        self.images: dict[str, ImageSymbol] = {}
        self.transforms: dict[str, TransformSymbol] = {}

        # Остальные структуры и метаданные сканирования
        self.jump_sources: dict[str, list[tuple[str, int]]] = {}
        self.screen_action_jumps: dict[str, set[str]] = {}
        self.used_screens: set[str] = set()
        self.screen_uses: dict[str, set[str]] = {}
        self.has_dynamic_jumps: bool = False
        self.diagnostics: list[Diagnostic] = []
        self.missing_defaults: dict[str, str] = {}
        self.total_lines: int = 0
        self.fixed_count: int = 0
        self.fixable_count: int = 0
        self.file_scopes: dict[str, FileScope] = {}
        self._stage1_lines: dict[str, list[str]] = {}

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

    def _check_unused_declarations(self) -> None:
        """RPY701-703: Поиск неиспользуемых define/transform/screen (мёртвый код).

        Отключается, если в проекте есть динамические jump'ы.
        Использует предварительно построенный индекс word → {(file, line_idx)}
        за один проход по всем файлам — O(total_words + symbols) вместо
        O(symbols × total_lines) у наивной реализации с re.search в цикле.

        PERF-2: регрессия — изначальная реализация на DDLC (50 файлов,
        77k строк, ~200 символов) зависала на минуты.
        """
        if self.has_dynamic_jumps:
            return

        # Шаг 1: За один проход по всем файлам строим индекс
        # word → set of (norm_path, line_idx_0based).
        # Это позволяет проверять любое количество символов за O(1) lookup каждый.
        word_locations: dict[str, set[tuple[str, int]]] = defaultdict(set)
        for norm_path in self.file_scopes:
            lines = self._stage1_lines.get(norm_path)
            if lines is None:
                try:
                    with open(norm_path, encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
                except OSError:
                    continue
                # Кэшируем, чтобы повторные прогоны не перечитывали файл.
                self._stage1_lines[norm_path] = lines
            for i, line in enumerate(lines):
                # \w+ = [A-Za-z0-9_]+ — это и есть "слова" в Ren'Py идентификаторах.
                # One findall per line is much faster than N regex searches per line.
                for word in _WORD_RE.findall(line):
                    word_locations[word].add((norm_path, i))

        def _is_used(name: str, decl_file: str, decl_line: int) -> bool:
            """O(1) lookup: имя использовано, если оно есть где-то вне строки объявления."""
            decl_norm = os.path.normcase(os.path.abspath(decl_file))
            decl_loc = (decl_norm, decl_line - 1)
            locations = word_locations.get(name)
            if not locations:
                return False
            # Если имя встречается более чем в одном месте — точно используется.
            # Если только в одном — проверяем, что это не строка объявления.
            if len(locations) > 1:
                return True
            return decl_loc not in locations

        # RPY701: Неиспользуемые define-константы
        for name, var_sym in self.variables.items():
            if not var_sym.is_constant:
                continue
            if var_sym.is_character:
                continue
            if not _is_used(name, var_sym.file_path, var_sym.line_number):
                self.diagnostics.append(
                    Diagnostic(
                        file_path=var_sym.file_path,
                        line_number=var_sym.line_number,
                        line_content=var_sym.code_line,
                        code="RPY701",
                        message=f"Constant '{name}' is declared with 'define' but never used. Consider removing this dead code.",
                        severity="HINT",
                    )
                )

        # RPY702: Неиспользуемые transform
        for name, trn_sym in self.transforms.items():
            if name in BUILTIN_SYMBOLS:
                continue
            if not _is_used(name, trn_sym.file_path, trn_sym.line_number):
                self.diagnostics.append(
                    Diagnostic(
                        file_path=trn_sym.file_path,
                        line_number=trn_sym.line_number,
                        line_content=trn_sym.code_line,
                        code="RPY702",
                        message=f"Transform '{name}' is defined but never used in 'show/scene at'. Consider removing this dead code.",
                        severity="HINT",
                    )
                )

        # RPY703: Неиспользуемые screen
        for name, scr_sym in self.screens.items():
            if name in BUILTIN_SCREENS:
                continue
            if not _is_used(name, scr_sym.file_path, scr_sym.line_number):
                self.diagnostics.append(
                    Diagnostic(
                        file_path=scr_sym.file_path,
                        line_number=scr_sym.line_number,
                        line_content=f"screen {name}():",
                        code="RPY703",
                        message=f"Screen '{name}' is defined but never called or shown. Consider removing this dead code.",
                        severity="HINT",
                    )
                )

    def run(self, quiet: bool = False) -> AnalysisResult:
        self.file_scopes.clear()
        self.missing_defaults.clear()
        self.diagnostics.clear()

        # Сброс базовых множеств
        self.user_symbols.clear()
        self.declared_symbols = set(BUILTIN_SYMBOLS)
        self.defined_audio_map.clear()
        self.referenced_labels.clear()
        self.screen_action_jumps.clear()
        self.used_screens.clear()
        self.screen_uses.clear()
        self.registered_audio_channels = set(BUILTIN_AUDIO_CHANNELS)

        # Очистка новых объектных реестров
        self.variables.clear()
        self.labels.clear()
        self.screens.clear()
        self.images.clear()
        self.transforms.clear()
        self.jump_sources.clear()
        self.screen_action_jumps.clear()
        self.used_screens.clear()
        self.screen_uses.clear()

        # Сброс флагов и счётчиков
        self.has_dynamic_jumps = False
        self.total_lines = 0
        self.fixed_count = 0
        self.fixable_count = 0
        self._stage1_lines.clear()

        self._index_assets()
        main_rpy, tl_rpy = self._get_rpy_files()
        rpy_files = main_rpy + self.extra_files
        total_files = len(rpy_files)

        # 0. Загрузка кэша
        old_manifest = self.cache_manager.load_manifest() if not self.fix else None
        cached_files = old_manifest.files if old_manifest else {}
        new_cached_entries: dict[str, CachedFileEntry] = {}
        stage1_diags_map: dict[str, list] = {}

        # [1/2] Сбор символов (Tier 1 Cache: восстановление неизмененных FileScope)
        file_hashes: dict[str, str] = {}
        for i, file_path in enumerate(rpy_files, 1):
            fname = os.path.basename(file_path)
            norm_path = os.path.normcase(os.path.abspath(file_path))

            mtime = os.path.getmtime(file_path) if os.path.exists(file_path) else 0.0
            size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

            if not quiet:
                msg = f"\r[1/2] Сбор символов: {i}/{total_files} ({fname[:25]})"
                print(msg.ljust(75), end="", flush=True)

            # Проверяем Tier 1 hit с контролем content_hash
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
                    # восстанавливаем stage-1 диагностики (RPY307/RPY504/RPY105),
                    # которые раньше исчезали на тёплом прогоне
                    self.diagnostics.extend(getattr(cached_entry, "collect_diagnostics", ()) or ())

            if not is_tier1_hit:
                f_hash = file_hashes.get(norm_path) or compute_file_hash(file_path)
                file_hashes[norm_path] = f_hash
                diag_start = len(self.diagnostics)
                self._collect_symbols(file_path)
                stage1_diags_map[norm_path] = list(self.diagnostics[diag_start:])

        if not quiet:
            print()

        self._rebuild_aggregates()

        # [2/2] Анализ правил (Tier 2 Cache: если глобальные символы не изменились — мгновенно отдаем диагностики)
        current_global_hash = self.cache_manager.compute_global_hash(self)
        is_global_unchanged = (
            old_manifest is not None and old_manifest.global_symbol_hash == current_global_hash
        )

        for i, file_path in enumerate(rpy_files, 1):
            fname = os.path.basename(file_path)
            norm_path = os.path.normcase(os.path.abspath(file_path))

            mtime = os.path.getmtime(file_path) if os.path.exists(file_path) else 0.0
            size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

            if not quiet:
                msg = f"\r[2/2] Анализ правил: {i}/{total_files} ({fname[:25]})"
                print(msg.ljust(75), end="", flush=True)

            # Проверяем Tier 2 hit с контролем content_hash
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

        self._check_unreachable_labels()
        self._check_unused_assets()
        self._check_unused_declarations()

        # [3/3] Валидация файлов перевода (TL-Checker)
        for tl_file in tl_rpy:
            self._analyze_tl_file(tl_file)

        # Применяем переопределения строгости ко всем собранным диагностикам (включая граф и ассеты)
        if self.severity_overrides:
            for d in self.diagnostics:
                if d.code in self.severity_overrides:
                    d.severity = self.severity_overrides[d.code]

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

    def _differential_purge_file(self, norm_path: str, file_path: str) -> None:
        """
        Дифференциально удаляет символы только одного файла из глобальных структур,
        не вызывая дорогую полную пересборку всех файлов проекта (_rebuild_aggregates).
        """
        old_scope = self.file_scopes.pop(norm_path, None)
        if not old_scope:
            return

        # 1. Быстрое удаление O(1) из объектных реестров
        for k in old_scope.variables:
            self.variables.pop(k, None)
        for k in old_scope.labels:
            self.labels.pop(k, None)
        for k in old_scope.screens:
            self.screens.pop(k, None)
        for k in old_scope.images:
            self.images.pop(k, None)
        for k in old_scope.transforms:
            self.transforms.pop(k, None)
        for k in old_scope.defined_audio_map:
            self.defined_audio_map.pop(k, None)

        # 2. Очистка jump_sources только для данного файла
        for tgt in old_scope.jump_sources:
            if tgt in self.jump_sources:
                self.jump_sources[tgt] = [
                    loc for loc in self.jump_sources[tgt] if loc[0] != file_path
                ]
                if not self.jump_sources[tgt]:
                    self.jump_sources.pop(tgt, None)

        # 3. Дифференциальная очистка множеств:
        # Символ удаляется из глобального множества только если его нет ни в одном другом файле проекта.
        other_scopes = list(self.file_scopes.values())

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

    def _purge_file_symbols(self, norm_path: str) -> None:
        """Полное удаление символов файла с последующей глобальной пересборкой."""
        if norm_path in self.file_scopes:
            del self.file_scopes[norm_path]
            self._rebuild_aggregates()

    def _rebuild_aggregates(self) -> None:
        """Пересобирает глобальные множества символов на основе scopes всех остальных файлов."""
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

        for scope in self.file_scopes.values():
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

        # экранные Jump/Call-экшены — тоже статические ссылки (RPY303, кэш-стабильно)
        for targets in self.screen_action_jumps.values():
            self.referenced_labels.update(targets)

    def analyze_file_only(self, file_path: str) -> list[Diagnostic]:
        """Быстрый анализ только одного измененного файла для LSP без утечки состояния."""
        file_diags: list[Diagnostic] = []
        old_diags = self.diagnostics
        self.diagnostics = file_diags
        norm_path = os.path.normcase(os.path.abspath(file_path))
        try:
            rel_parts = os.path.relpath(file_path, self.project_path).replace("\\", "/").split("/")
        except ValueError:
            # Windows: file_path и project_path на разных дисках (D: vs C:)
            # — os.path.relpath падает. Используем абсолютный путь как fallback.
            rel_parts = file_path.replace("\\", "/").split("/")
        try:
            if "tl" in rel_parts:
                self._analyze_tl_file(file_path)
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

    def _emit_encoding_error(self, file_path: str, err: UnicodeDecodeError) -> None:
        """RPY100: файл не читается как UTF-8. Раньше decode-ошибка глохла в
        `except: pass` — линтер молча пропускал файл и рапортовал «чисто»,
        хотя Ren'Py упадёт на загрузке такого скрипта."""
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
        """Обработка `default var = expr` — RPY105, VariableSymbol."""
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
        """Обработка `define var = expr` — RPY105, VariableSymbol."""
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
        """Обработка `define audio.NAME = "file.ogg"`."""
        alias = m_audio_def.group(1)
        target_file = m_audio_def.group(2).replace("\\", "/").lower()
        scope.defined_audio_map[alias] = target_file
        scope.declared_symbols.add(alias)
        scope.declared_symbols.add(f"audio.{alias}")
        self.defined_audio_map[alias] = target_file
        self.declared_symbols.add(alias)
        self.declared_symbols.add(f"audio.{alias}")

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
        """Обработка `screen name(...)` и `transform name(...)`.

        Возвращает текущий screen name (или None) для контекста.
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

        # Контекст экрана (screen-блоки всегда top-level)
        if len(line) - len(line.lstrip(" ")) == 0:
            new_screen = m_screen_def.group(2) if m_screen_def else None

        if m_trans:
            trans_name = m_trans.group(1)
            trans_sym = TransformSymbol(
                name=trans_name,
                file_path=file_path,
                line_number=idx + 1,
                code_line=clean,
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
        """Обработка `label name(params):` — RPY307, LabelSymbol.

        Возвращает (label_name, current_global_label, current_label).
        """
        raw_name = m_label.group(1)
        if raw_name.startswith("."):
            label_name = (
                f"{current_global_label}{raw_name}"
                if current_global_label
                else raw_name
            )
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
        """Обработка jump/call/return внутри label + screen edges."""
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

        # Рёбра из экранов (Jump/Call-экшены) и использования экранов
        if current_screen:
            for m_act in RE_SCREEN_JUMP_ACTION.finditer(clean):
                scope.screen_action_jumps.setdefault(current_screen, set()).add(
                    m_act.group(1)
                )
                self.screen_action_jumps.setdefault(current_screen, set()).add(
                    m_act.group(1)
                )

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
        """Обработка layeredimage и image declarations — RPY504.

        Возвращает (was_handled, new_idx).
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
        """Обработка channels, dynamic jumps, quoted strings, init python.

        Возвращает (was_init_python, new_idx).
        """
        m_chan = re.search(
            r'renpy\.music\.register_channel\s*\(\s*["\']([^\W\d]\w*)["\']', clean
        )
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
        """Собирает символы из .rpy файла (default/define/screen/label/image/...).

        Phase 3 Step 5 (0.5.6): разбит с 378 строк на 7 методов + dispatcher.
        """
        try:
            norm_path = os.path.normcase(os.path.abspath(file_path))
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

                # Контекст экрана (screen-блоки всегда top-level)
                # Важно: current_screen сбрасывается в None для ЛЮБОЙ top-level строки,
                # не только screen. Это нужно чтобы label start: сбрасывал screen context.
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
                    clean, file_path, idx, scope,
                    current_label, current_global_label, current_screen
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
        """Точечный поиск медиа-файлов в блоках Python (защита от ложных RPY503 без оверхеда)."""
        if isinstance(code_lines, str):
            code_lines = [code_lines]
        for line in code_lines:
            if '"' in line or "'" in line:  # Fast-path: сверхбыстрая отсечка
                for match in RE_STRING_MATCH.finditer(line):
                    inner = match.group(0).strip("\"'")
                    val_clean = inner.replace("\\", "/").lower().strip()
                    if any(val_clean.endswith(ext) for ext in MEDIA_EXTENSIONS):
                        self._mark_asset_used(val_clean)
                        self._mark_asset_used(os.path.basename(val_clean))

    def _apply_severity(self, diag: Diagnostic) -> None:
        """Применяет переопределения строгости из конфига или дефолтные уровни."""
        if self.severity_overrides and diag.code in self.severity_overrides:
            diag.severity = self.severity_overrides[diag.code]
        elif not diag.severity:
            diag.severity = RULE_SEVERITY.get(diag.code, "WARNING")

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
        """Возвращает все известные атрибуты для тега (из layeredimage и файловой структуры)."""
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
        try:
            norm_path = os.path.normcase(os.path.abspath(file_path))
            if norm_path in self.in_memory_files:
                lines = self.in_memory_files[norm_path].splitlines(keepends=True)
            elif norm_path in self._stage1_lines:
                lines = self._stage1_lines.pop(norm_path)
            else:
                with open(file_path, encoding="utf-8", newline="") as f:
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
                        self._scan_python_assets(block_lines)
                        import textwrap

                        code = textwrap.dedent("".join(block_lines))
                        self.python_ast.check_init_dependency(
                            code, file_path, idx + 2, noqa_map, lines
                        )
                        # Также проверяем стандартные правила (устаревший API и т.д.)
                        self.python_ast.check_python_ast(code, file_path, idx + 2, noqa_map, lines)
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
                    file_path,
                    idx,
                    raw_line,
                    clean,
                    scope_stack,
                    noqa_map,
                    lines,
                    state_checker.branch_uninitialized,
                )

                # 5. Проверка кавычек, интерполяций и тегов (RPY101, RPY301, RPY304)
                # Выполняется только для диалогов и экранов, но не для строк чистого Python ($ / python:)
                if not stripped.startswith(("$", "python")):
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

            state_checker._pop_and_merge_all_if()

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
    ) -> tuple[int, dict[str, tuple[str, ...]], set[str], bool]:
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

    def _analyze_tl_file(self, file_path: str):
        try:
            norm_path = os.path.normcase(os.path.abspath(file_path))
            if norm_path in self.in_memory_files:
                lines = self.in_memory_files[norm_path].splitlines(keepends=True)
            else:
                with open(file_path, encoding="utf-8", newline="") as f:
                    lines = f.readlines()
        except UnicodeDecodeError as e:
            self._emit_encoding_error(file_path, e)
            return
        except OSError:
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
        re_old = re.compile(
            r'^\s*old\s+("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')'
        )
        re_new = re.compile(
            r'^\s*new\s+("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')'
        )
        re_dialogue_old = re.compile(
            r'^\s*#\s*(?:(?:\w+|"[^"]*"|\'[^\']*\')(?:\s+\w+)*\s+)?("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')'
        )
        re_dialogue_new = re.compile(
            r'^\s*(?:(?:\w+|"[^"]*"|\'[^\']*\')(?:\s+\w+)*\s+)?("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\')'
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

        re_var = re.compile(r"\[([^\W\d]\w*)(?:![a-zA-Z]+)?\]")
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

                start_c, end_c = self._get_utf16_range(
                    new_txt, next(iter(extra)) if extra else None
                )
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
