from __future__ import annotations

import difflib
import os
import re
import textwrap
import warnings

from senpy.assets import AssetManager, find_orphaned_rpyc
from senpy.flow import StoryFlowAnalyzer
from senpy.python_ast import PythonAstChecker
from senpy.text_tags import get_utf16_range, process_quoted_strings

warnings.filterwarnings("ignore", category=SyntaxWarning)

# Импортируем вынесенные модели и константы
from senpy.constants import (
    BUILTIN_ACTIONS,
    BUILTIN_COLORS,
    BUILTIN_SCREENS,
    BUILTIN_SYMBOLS,
    CLAUSE_KEYWORDS,
    IGNORED_DIRS,
    NON_DIALOGUE_STATEMENTS,
    RE_BUTTON_LINE,
    RE_CONDITION,
    RE_DEFAULT,
    RE_DEFINE,
    RE_DEFINE_AUDIO,
    RE_FOR_LOOP,
    RE_IMAGE_DEF,
    RE_INIT_PYTHON_START,
    RE_JUMP_CALL,
    RE_LABEL,
    RE_MENU_START,
    RE_NOQA,
    RE_PLAY_AUDIO,
    RE_PYTHON_BLOCK_START,
    RE_RETURN,
    RE_SCREEN_CALL,
    RE_SCREEN_START,
    RE_SHOW_SCENE,
    SMART_QUOTES,
)
from senpy.models import RULE_SEVERITY, AnalysisResult, Diagnostic


def _strip_comment(line: str) -> str:
    """Удаляет комментарий (#), не ломая hex-цвета (#fff) и решетки внутри кавычек."""
    in_quote = None
    for i, ch in enumerate(line):
        if ch in ('"', "'"):
            if in_quote == ch:
                in_quote = None
            elif in_quote is None:
                in_quote = ch
        elif ch == '#' and in_quote is None:
            return line[:i]
    return line

class SenpyAnalyzer:
    def __init__(
        self,
        project_path: str,
        extra_files: list[str] | None = None,
        fix: bool = False,
        in_memory_files: dict[str, str] | None = None,
    ):
        self.project_path = os.path.abspath(project_path)
        self.assets = AssetManager(self.project_path)
        self.python_ast = PythonAstChecker(self)
        self.flow = StoryFlowAnalyzer(self)
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
        self.labels_with_return: set[str] = set()
        self.label_outgoing_jumps: dict[str, set[str]] = {}
        self.declared_images: dict[str, tuple[str, int, str]] = {}
        self.referenced_labels: set[str] = set()
        self.has_dynamic_jumps: bool = False
        self.diagnostics: list[Diagnostic] = []
        self.missing_defaults: dict[str, str] = {}
        self.total_lines: int = 0
        self.fixed_count: int = 0
        self.fixable_count: int = 0
        self._fuzzy_img_cache: dict[str, str | None] = {}
        self.defined_audio_map: dict[str, str] = {}

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
        self.missing_defaults.clear()
        self.diagnostics.clear()
        self._fuzzy_img_cache.clear()
        self.user_symbols.clear()
        self.declared_symbols = set(BUILTIN_SYMBOLS)
        self.declared_labels.clear()
        self.declared_screens.clear()
        self.referenced_labels.clear()
        self.labels_with_return.clear()
        self.label_outgoing_jumps.clear()
        self.declared_images.clear()
        self.defined_audio_map.clear()
        self.has_dynamic_jumps = False
        self.total_lines = 0
        self.fixed_count = 0
        self.fixable_count = 0
        self.defined_constants.clear()
        self.declared_characters.clear()

        self._index_assets()
        rpy_files = self._get_rpy_files() + self.extra_files

        total_files = len(rpy_files)

        for i, file_path in enumerate(rpy_files, 1):
            fname = os.path.basename(file_path)
            if not quiet:
                msg = f"\r[1/2] Сбор символов: {i}/{total_files} ({fname[:25]})"
                print(msg.ljust(75), end="", flush=True)
            self._collect_symbols(file_path)
        if not quiet:
            print()

        for i, file_path in enumerate(rpy_files, 1):
            fname = os.path.basename(file_path)
            if not quiet:
                msg = f"\r[2/2] Анализ правил: {i}/{total_files} ({fname[:25]})"
                print(msg.ljust(75), end="", flush=True)
            self._analyze_file(file_path)
        if not quiet:
            print()

        self._check_unreachable_labels()
        self._check_unused_assets()

        return AnalysisResult(
            diagnostics=self.diagnostics,
            file_count=len(rpy_files),
            total_lines=self.total_lines,
            fixed_count=self.fixed_count,
            fixable_count=self.fixable_count,
        )

    def analyze_file_only(self, file_path: str) -> list[Diagnostic]:
        """Быстрый анализ только одного измененного файла для LSP (10-15 мс вместо 4 сек)."""
        file_diags: list[Diagnostic] = []
        old_diags = self.diagnostics
        self.diagnostics = file_diags
        try:
            self._collect_symbols(file_path)
            self._analyze_file(file_path)
        finally:
            self.diagnostics = old_diags
        return file_diags

    def _get_rpy_files(self) -> list[str]:
        files: list[str] = []
        for root, dirs, filenames in os.walk(self.project_path):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for f in filenames:
                if f.endswith((".rpy", "_ren.py")):
                    files.append(os.path.join(root, f))
        return files

    def _collect_symbols(self, file_path: str):
        try:
            norm_path = os.path.normcase(os.path.abspath(file_path))
            if norm_path in self.in_memory_files:
                lines = self.in_memory_files[norm_path].splitlines(keepends=True)
            else:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()

            if file_path.endswith("_ren.py"):
                self._collect_from_python_block(lines)
                return

            idx = 0
            current_label: str | None = None

            while idx < len(lines):
                line = lines[idx]
                clean = _strip_comment(line).strip()
                if not clean:
                    idx += 1
                    continue

                m_def = RE_DEFAULT.match(clean)
                if m_def:
                    var = m_def.group(1)
                    self.user_symbols.add(var)
                    self.declared_symbols.add(var)
                    idx += 1
                    continue

                m_audio_def = RE_DEFINE_AUDIO.match(clean)
                if m_audio_def:
                    alias = m_audio_def.group(1)
                    target_file = m_audio_def.group(2).replace("\\", "/").lower()
                    self.defined_audio_map[alias] = target_file
                    self.declared_symbols.add(alias)
                    self.declared_symbols.add(f"audio.{alias}")
                    idx += 1
                    continue

                # 2. И ТОЛЬКО ПОТОМ обычный define
                m_define = RE_DEFINE.match(clean)
                if m_define:
                    var = m_define.group(1)
                    self.user_symbols.add(var)
                    self.declared_symbols.add(var)
                    self.defined_constants.add(var)

                    if "Character" in clean or "DynamicCharacter" in clean:
                        self.declared_characters.add(var)

                    idx += 1
                    continue

                m_screen_def = RE_SCREEN_START.match(line)
                if m_screen_def:
                    s_name = m_screen_def.group(2)
                    self.declared_screens[s_name] = (file_path, idx + 1)

                m_label = RE_LABEL.match(clean)
                if m_label:
                    label_name = m_label.group(1)
                    if label_name in self.declared_labels:
                        # Служебные хуки вроде label _(message): не считаем ошибкой
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
                        self.declared_labels[label_name] = (file_path, idx + 1, clean)
                    
                    current_label = label_name
                    self.label_outgoing_jumps[label_name] = set()

                    raw_params = m_label.group(2)
                    if raw_params:
                        for p in raw_params.split(","):
                            p_clean = p.split("=")[0].strip()
                            if p_clean and p_clean.isidentifier():
                                self.declared_symbols.add(p_clean)

                    idx += 1
                    continue

                if current_label:
                    if RE_RETURN.match(clean):
                        self.labels_with_return.add(current_label)
                    m_jump_in_label = re.match(r"^\s*jump\s+([a-zA-Z_][a-zA-Z0-9_]*)", clean)
                    if m_jump_in_label:
                        self.label_outgoing_jumps.setdefault(current_label, set()).add(m_jump_in_label.group(1))

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
                    self.declared_images[img_name] = (file_path, idx + 1, img_body)
                    idx += 1
                    continue

                if "renpy.call(" in clean or "renpy.jump(" in clean or "call expression" in clean or "jump expression" in clean:
                    self.has_dynamic_jumps = True

                for str_match in re.finditer(r'["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']', clean):
                    candidate = str_match.group(1)
                    if candidate.isidentifier():
                        self.referenced_labels.add(candidate)

                m_init = RE_INIT_PYTHON_START.match(line)
                if m_init:
                    indent = len(m_init.group(1))
                    idx, block_lines = self._consume_block(lines, idx + 1, indent)
                    self._collect_from_python_block(block_lines)
                    continue

                idx += 1
        except (UnicodeDecodeError, OSError):
            pass

    def _collect_from_python_block(self, code_lines: list[str]) -> None:
        self.python_ast.collect_from_python_block(code_lines)

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
        diag.severity = RULE_SEVERITY.get(diag.code, "WARNING")
        self.diagnostics.append(diag)

    def _suggest_similar_symbol(self, unknown_var: str) -> str:
        matches = difflib.get_close_matches(
            unknown_var, list(self.user_symbols), n=1, cutoff=0.6
        )
        if matches:
            return f" (did you mean '{matches[0]}' ?)"
        return ""

    def _can_reach_return(self, label_name: str, visited: set[str] | None = None) -> bool:
        return self.flow.can_reach_return(label_name, visited)

    def _analyze_file(self, file_path: str):
        try:
            norm_path = os.path.normcase(os.path.abspath(file_path))
            if norm_path in self.in_memory_files:
                lines = self.in_memory_files[norm_path].splitlines(keepends=True)
            else:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            if file_path.endswith("_ren.py"):
                return

            self.total_lines += len(lines)
            file_modified = False

            noqa_map: dict[int, set[str] | None] = {}
            for line_no, raw_line in enumerate(lines, start=1):
                has_noqa, codes = self._parse_noqa(raw_line)
                if has_noqa:
                    noqa_map[line_no] = codes

            idx = 0
            current_screen: str | None = None
            current_screen_indent = 0
            screen_local_symbols: set[str] = set()
            in_label_context: bool = False
            branch_uninitialized: dict[str, tuple[str, str]] = {}

            while idx < len(lines):
                raw_line = lines[idx]
                clean = _strip_comment(raw_line)
                stripped = clean.strip()

                if not stripped:
                    idx += 1
                    continue

                # RPY001: Проверка табуляции в отступах
                leading_ws = raw_line[:len(raw_line) - len(raw_line.lstrip())]
                if "\t" in leading_ws:
                    self.fixable_count += 1
                    if self.fix:
                        fixed_leading = leading_ws.replace("\t", "    ")
                        raw_line = fixed_leading + raw_line[len(leading_ws):]
                        lines[idx] = raw_line
                        file_modified = True
                        self.fixed_count += 1
                    else:
                        start_c, end_c = 0, len(leading_ws.encode("utf-16-le")) // 2
                        self._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=idx + 1,
                                line_content=raw_line.rstrip(),
                                code="RPY001",
                                message="Tab character ('\\t') used in indentation. Ren'Py requires 4 spaces per indent level.",
                                col=start_c,
                                end_col=end_c,
                                fix_title="Replace tabs with 4 spaces",
                                fix_replacement=leading_ws.replace("\t", "    "),
                                fix_start_col=start_c,
                                fix_end_col=end_c,
                            ),
                            noqa_map,
                        )

                # RPY002: Фигурные/типографские кавычки в коде
                if any(q in raw_line for q in SMART_QUOTES) and (
                    stripped.startswith(("$", "if ", "elif ", "default ", "define "))
                    or current_screen is not None
                ):
                        self.fixable_count += 1
                        if self.fix:
                            fixed_l = raw_line
                            for sq, aq in SMART_QUOTES.items():
                                fixed_l = fixed_l.replace(sq, aq)
                            lines[idx] = fixed_l
                            raw_line = fixed_l
                            file_modified = True
                            self.fixed_count += 1
                        else:
                            self._add_diagnostic(
                                Diagnostic(
                                    file_path=file_path,
                                    line_number=idx + 1,
                                    line_content=stripped,
                                    code="RPY002",
                                    message="Smart/curly quotes (“ ” ‘ ’ « ») detected in code statement. Will cause Python SyntaxError.",
                                    fix_title="Replace smart quotes with standard quotes",
                                    fix_replacement=''.join(SMART_QUOTES.get(c, c) for c in raw_line),
                                ),
                                noqa_map,
                            )

                line_indent = len(raw_line) - len(raw_line.lstrip(" "))

                m_init = RE_INIT_PYTHON_START.match(raw_line)
                if m_init:
                    indent = len(m_init.group(1))
                    next_idx, _ = self._consume_block(lines, idx + 1, indent)
                    idx = next_idx
                    continue

                if current_screen is not None and line_indent <= current_screen_indent:
                    current_screen = None
                    screen_local_symbols.clear()

                m_label = RE_LABEL.match(clean)
                if m_label:
                    # RPY308: Проверяем предыдущую строку перед меткой
                    if in_label_context and idx > 0:
                        prev_idx = idx - 1
                        while prev_idx >= 0 and not lines[prev_idx].strip():
                            prev_idx -= 1
                        if prev_idx >= 0:
                            prev_clean = _strip_comment(lines[prev_idx]).strip()
                            if (
                                prev_clean
                                and not prev_clean.startswith(("return", "jump ", "jump\t", "renpy.full_restart", "renpy.quit"))
                                and not prev_clean.endswith(":")
                            ):
                                    self._add_diagnostic(
                                        Diagnostic(
                                            file_path=file_path,
                                            line_number=idx + 1,
                                            line_content=stripped,
                                            code="RPY308",
                                            message=f"Label '{m_label.group(1)}' is preceded by regular statements without 'return' or 'jump'. Control flow will unintentionally fall through.",
                                            severity="WARNING",
                                        ),
                                        noqa_map,
                                    )
                    branch_uninitialized.clear()
                    in_label_context = True

                if line_indent == 0 and stripped.startswith(("screen ", "style ", "init ", "transform ")):
                    in_label_context = False

                m_screen = RE_SCREEN_START.match(raw_line)
                if m_screen:
                    current_screen = m_screen.group(2)
                    current_screen_indent = len(m_screen.group(1))
                    screen_local_symbols.clear()
                    in_label_context = False
                    params_str = m_screen.group(3)
                    if params_str:
                        for p in params_str.split(","):
                            p_clean = p.split("=")[0].strip()
                            if p_clean and p_clean.isidentifier():
                                screen_local_symbols.add(p_clean)
                    idx += 1
                    continue

                if current_screen is not None:
                    m_def = RE_DEFAULT.match(stripped)
                    if m_def:
                        screen_local_symbols.add(m_def.group(1))
                        idx += 1
                        continue

                    m_for = RE_FOR_LOOP.match(stripped)
                    if m_for:
                        screen_local_symbols.add(m_for.group(1))

                    m_btn = RE_BUTTON_LINE.match(stripped)
                    if m_btn:
                        # RPY203: кнопка без действия action
                        if not stripped.endswith(":") and not re.search(r"\baction\b", stripped):
                            btn_word = m_btn.group(1)
                            start_c, end_c = self._get_utf16_range(raw_line, btn_word)
                            self._add_diagnostic(
                                Diagnostic(
                                    file_path=file_path,
                                    line_number=idx + 1,
                                    line_content=stripped,
                                    code="RPY203",
                                    message=f"{btn_word.capitalize()} is missing an 'action' argument and will not respond to clicks.",
                                    col=start_c,
                                    end_col=end_c,
                                ),
                                noqa_map,
                            )
                        # RPY206: прямой вызов функции в action со скобками
                        m_act = re.search(r"\baction\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", stripped)
                        if m_act:
                            fn_name = m_act.group(1)
                            if fn_name not in BUILTIN_ACTIONS:
                                start_c, end_c = self._get_utf16_range(raw_line, f"action {fn_name}(")
                                self._add_diagnostic(
                                    Diagnostic(
                                        file_path=file_path,
                                        line_number=idx + 1,
                                        line_content=stripped,
                                        code="RPY206",
                                        message=f"Direct function call '{fn_name}()' in action. It executes immediately during screen render! Use 'action Function({fn_name}, ...)' instead.",
                                        col=start_c,
                                        end_col=end_c,
                                        fix_title=f"Wrap with Function({fn_name})",
                                        fix_replacement=f"Function({fn_name})",
                                    ),
                                    noqa_map,
                                )

                m_menu = RE_MENU_START.match(raw_line)
                if m_menu and current_screen is None:
                    menu_indent = len(m_menu.group(1))
                    next_idx, uninit_vars = self._analyze_menu_flow(
                        lines,
                        idx + 1,
                        menu_indent,
                        file_path=file_path,
                        noqa_map=noqa_map,
                    )
                    branch_uninitialized.update(uninit_vars)
                    idx = next_idx
                    continue

                m_scr = RE_SCREEN_CALL.match(stripped)
                if m_scr:
                    screen_target = m_scr.group(1)
                    if screen_target not in self.declared_screens and screen_target not in BUILTIN_SCREENS:
                        all_screens = list(self.declared_screens.keys()) + list(BUILTIN_SCREENS)
                        matches = difflib.get_close_matches(screen_target, all_screens, n=1, cutoff=0.6)
                        hint = f" (did you mean '{matches[0]}' ?)" if matches else ""
                        start_c, end_c = self._get_utf16_range(raw_line, screen_target)
                        self._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=idx + 1,
                                line_content=stripped,
                                code="RPY204",
                                message=f"Screen '{screen_target}' is not declared in project{hint}. Causes runtime ScriptError.",
                                col=start_c,
                                end_col=end_c,
                            ),
                            noqa_map,
                        )

                m_show = RE_SHOW_SCENE.match(stripped)
                if m_show and current_screen is None:
                    raw_tokens = m_show.group(2).split()
                    img_tokens = []
                    for t in raw_tokens:
                        if t in CLAUSE_KEYWORDS or t.endswith(":"):
                            break
                        img_tokens.append(t)

                    if img_tokens:
                        full_img_tag = " ".join(img_tokens)
                        self._mark_asset_used(full_img_tag)
                        base_tag = img_tokens[0]
                        all_valid = self.valid_images.union(self.declared_images.keys())

                        is_single_tag_manipulation = len(img_tokens) == 1 and m_show.group(1) == "show"
                        has_base = any(img.startswith(base_tag + " ") or img == base_tag for img in all_valid)

                        if is_single_tag_manipulation and has_base:
                            pass
                        elif full_img_tag not in all_valid and full_img_tag not in BUILTIN_COLORS:
                            if full_img_tag in self._fuzzy_img_cache:
                                best_sprite = self._fuzzy_img_cache[full_img_tag]
                            else:
                                candidates = [img for img in all_valid if img.startswith(base_tag + " ")]
                                if not candidates:
                                    all_tags = {img.split()[0] for img in all_valid}
                                    matched_tags = difflib.get_close_matches(base_tag, list(all_tags), n=1, cutoff=0.7)
                                    if matched_tags:
                                        candidates = [img for img in all_valid if img.startswith(matched_tags[0] + " ")]

                                matches = difflib.get_close_matches(full_img_tag, candidates, n=1, cutoff=0.6) if candidates else []
                                best_sprite = matches[0] if matches else None
                                self._fuzzy_img_cache[full_img_tag] = best_sprite

                            hint = f" (did you mean '{best_sprite}' ?)" if best_sprite else ""
                            start_c, end_c = self._get_utf16_range(raw_line, full_img_tag)
                            msg = f"Sprite or background '{full_img_tag}' not found in assets or 'image' definitions{hint}."
                            if has_base and not hint:
                                msg += f" Base character '{base_tag}' exists, but attribute is missing."
                            self._add_diagnostic(
                                Diagnostic(
                                    file_path=file_path,
                                    line_number=idx + 1,
                                    line_content=stripped,
                                    code="RPY502",
                                    message=msg,
                                    col=start_c,
                                    end_col=end_c,
                                    fix_title=f"Change to '{best_sprite}'" if best_sprite else None,
                                    fix_replacement=best_sprite,
                                ),
                                noqa_map,
                            )

                m_jump = RE_JUMP_CALL.match(stripped)
                if m_jump:
                    cmd_type, target_label = m_jump.group(1), m_jump.group(2)
                    if target_label == "expression":
                        self.has_dynamic_jumps = True
                    else:
                        self.referenced_labels.add(target_label)
                        if target_label not in self.declared_labels:
                            matches = difflib.get_close_matches(target_label, list(self.declared_labels.keys()), n=1, cutoff=0.6)
                            best_match = matches[0] if matches else None
                            hint = f" (did you mean '{best_match}' ?)" if best_match else ""
                            start_c, end_c = self._get_utf16_range(raw_line, target_label)
                            self._add_diagnostic(
                                Diagnostic(
                                    file_path=file_path,
                                    line_number=idx + 1,
                                    line_content=stripped,
                                    code="RPY302",
                                    message=f"{cmd_type.capitalize()} to non-existent label '{target_label}'{hint}. Causes ScriptError.",
                                    col=start_c,
                                    end_col=end_c,
                                    fix_title=f"Change to '{best_match}'" if best_match else None,
                                    fix_replacement=best_match,
                                ),
                                noqa_map,
                            )
                        if cmd_type == "jump":
                            branch_uninitialized.clear()
                        elif cmd_type == "call" and target_label in self.declared_labels and not self._can_reach_return(target_label):
                            self._add_diagnostic(
                                Diagnostic(
                                        file_path=file_path,
                                        line_number=idx + 1,
                                        line_content=stripped,
                                        code="RPY306",
                                        message=f"Static analysis could not find a 'return' path from called label '{target_label}'. Verify that control flow returns correctly.",
                                    ),
                                    noqa_map,
                                )
                    idx += 1
                    continue

                # RPY501: Проверка аудио (в кавычках и без)
                m_play = RE_PLAY_AUDIO.match(stripped)
                if m_play:
                    raw_audio_target = m_play.group(1).strip()
                    audio_found = False

                    if raw_audio_target.startswith(('"', "'")) and raw_audio_target.endswith(('"', "'")):
                        clean_audio_path = raw_audio_target[1:-1].strip()
                        # Срезаем Ren'Py-модификаторы таймингов вроде <from 10.0 to 50.0>
                        clean_audio_path = re.sub(r"^<[^>]+>\s*", "", clean_audio_path)
                        clean_audio_path = clean_audio_path.replace("\\", "/").lower()
                        audio_file = os.path.basename(clean_audio_path)
                        if clean_audio_path in self.known_assets or audio_file in self.known_assets:
                            audio_found = True
                            self._mark_asset_used(clean_audio_path)
                            self._mark_asset_used(audio_file)
                    else:
                        identifier = raw_audio_target
                        identifier = identifier.removeprefix("audio.")

                        if identifier in self.defined_audio_map:
                            audio_found = True
                            self._mark_asset_used(self.defined_audio_map[identifier])
                        elif identifier in self.audio_dir_files:
                            audio_found = True
                            self._mark_asset_used(self.audio_dir_files[identifier])
                        elif identifier in self.known_assets:
                            audio_found = True
                            self._mark_asset_used(identifier)

                    if not audio_found:
                        start_c, end_c = self._get_utf16_range(raw_line, raw_audio_target)
                        self._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=idx + 1,
                                line_content=stripped,
                                code="RPY501",
                                message=f"Audio asset '{raw_audio_target}' not found in project, 'audio/' directory, or RPA archives.",
                                col=start_c,
                                end_col=end_c,
                            ),
                            noqa_map,
                        )

                # RPY305: Проверка неэкранированных кавычек в диалоге
                first_token = stripped.split()[0] if stripped.split() else ""
                if in_label_context and current_screen is None and first_token not in NON_DIALOGUE_STATEMENTS:
                    unescaped_quotes = re.findall(r'(?<!\\)"', stripped)
                    is_odd_quotes = len(unescaped_quotes) % 2 != 0
                    has_inner_quotes = bool(re.search(r'(?<!\\)"[^"\\]*(?<!\\)"\s+[^\s"\'#]+.*(?<!\\)"', stripped))
                    if is_odd_quotes or has_inner_quotes:
                        self._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=idx + 1,
                                line_content=stripped,
                                code="RPY305",
                                message="Unescaped quotes inside dialogue text. Use '\\\"' instead of '\"' to avoid syntax errors.",
                            ),
                            noqa_map,
                        )

                new_line, modified = self._check_and_fix_quoted_strings(
                    file_path, idx + 1, raw_line, screen_local_symbols, noqa_map
                )
                if modified:
                    lines[idx] = new_line
                    file_modified = True

                self._check_cfg_interpolations(
                    file_path, idx + 1, stripped, branch_uninitialized, noqa_map
                )

                if stripped.startswith("$"):
                    py_code = stripped[1:].strip()
                    if current_screen is not None:
                        self._check_screen_mutation(
                            py_code,
                            file_path,
                            idx + 1,
                            stripped,
                            current_screen,
                            screen_local_symbols,
                            noqa_map,
                            lines=lines,
                        )
                    else:
                        self._check_python_ast(
                            py_code, file_path, start_line=idx + 1, noqa_map=noqa_map, lines=lines
                        )
                        self._clear_safe_cfg_vars(py_code, branch_uninitialized)
                    idx += 1
                    continue

                m_py = RE_PYTHON_BLOCK_START.match(raw_line)
                if m_py:
                    indent = len(m_py.group(1))
                    next_idx, block_lines = self._consume_block(lines, idx + 1, indent)
                    if block_lines:
                        code = textwrap.dedent("".join(block_lines))
                        if current_screen is not None:
                            self._check_screen_mutation(
                                code,
                                file_path,
                                idx + 2,
                                stripped,
                                current_screen,
                                screen_local_symbols,
                                noqa_map,
                                lines=lines,
                            )
                        else:
                            self._check_python_ast(
                                code, file_path, start_line=idx + 2, noqa_map=noqa_map, lines=lines
                            )
                            self._clear_safe_cfg_vars(code, branch_uninitialized)
                    idx = next_idx
                    continue

                m_cond = RE_CONDITION.match(stripped)
                if m_cond:
                    expr = m_cond.group(1)
                    self._check_condition(
                        file_path,
                        idx + 1,
                        stripped,
                        expr,
                        current_screen,
                        screen_local_symbols,
                        noqa_map,
                    )
                    self._check_cfg_condition(
                        file_path,
                        idx + 1,
                        stripped,
                        expr,
                        branch_uninitialized,
                        noqa_map,
                    )

                idx += 1

            if file_modified and self.fix:
                with open(file_path, "w", encoding="utf-8") as f:
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

    def _mark_asset_used(self, asset_ref: str):
        ref_norm = asset_ref.replace("\\", "/").lower().strip()
        self.used_asset_keys.add(ref_norm)
        self.used_asset_keys.add(os.path.basename(ref_norm))