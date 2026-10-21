from __future__ import annotations

import difflib
import os
import re
import textwrap
from typing import TYPE_CHECKING

from senpy.constants import (
    BUILTIN_ACTIONS,
    BUILTIN_COLORS,
    BUILTIN_SCREENS,
    CLAUSE_KEYWORDS,
    NON_DIALOGUE_STATEMENTS,
    RE_BUTTON_LINE,
    RE_CONDITION,
    RE_DEFAULT,
    RE_FOR_LOOP,
    RE_JUMP_CALL,
    RE_LABEL,
    RE_MENU_START,
    RE_PLAY_AUDIO,
    RE_PYTHON_BLOCK_START,
    RE_SCREEN_CALL,
    RE_SHOW_SCENE,
    SMART_QUOTES,
)
from senpy.models import Diagnostic

if TYPE_CHECKING:
    from senpy.analyzer import SenpyAnalyzer
    from senpy.scope import ScopeStack

class BaseChecker:
    def __init__(self, analyzer: SenpyAnalyzer):
        self.analyzer = analyzer

    def check_line(
        self,
        file_path: str,
        idx: int,
        raw_line: str,
        clean_line: str,
        scope_stack: ScopeStack,
        noqa_map: dict[int, set[str] | None],
        lines: list[str],
    ) -> tuple[str, bool]:
        """Возвращает (обновленная_строка, был_ли_модифицирован_файл)."""
        return raw_line, False


class FormattingChecker(BaseChecker):
    def check_line(
        self,
        file_path: str,
        idx: int,
        raw_line: str,
        clean_line: str,
        scope_stack: ScopeStack,
        noqa_map: dict[int, set[str] | None],
        lines: list[str],
    ) -> tuple[str, bool]:
        file_modified = False
        new_raw_line = raw_line
        stripped = clean_line.strip()

        # RPY107: Проверка устаревшего API Ren'Py
        for d in self.analyzer.deprecated.check_line(new_raw_line, idx + 1, file_path):
            self.analyzer._add_diagnostic(d, noqa_map)

        # RPY001: Проверка табуляции в отступах
        leading_ws = new_raw_line[:len(new_raw_line) - len(new_raw_line.lstrip())]
        if "\t" in leading_ws:
            self.analyzer.fixable_count += 1
            if self.analyzer.fix:
                fixed_leading = leading_ws.replace("\t", "    ")
                new_raw_line = fixed_leading + new_raw_line[len(leading_ws):]
                lines[idx] = new_raw_line
                file_modified = True
                self.analyzer.fixed_count += 1
            else:
                start_c, end_c = 0, len(leading_ws.encode("utf-16-le")) // 2
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=idx + 1,
                        line_content=new_raw_line.rstrip(),
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
        if any(q in clean_line for q in SMART_QUOTES) and (
            stripped.startswith(("$", "if ", "elif ", "default ", "define "))
            or (scope_stack.current_screen_name() is not None and not stripped.startswith(("text ", "textbutton ")))
        ):
            self.analyzer.fixable_count += 1
            if self.analyzer.fix:
                fixed_l = new_raw_line
                for sq, aq in SMART_QUOTES.items():
                    fixed_l = fixed_l.replace(sq, aq)
                lines[idx] = fixed_l
                new_raw_line = fixed_l
                file_modified = True
                self.analyzer.fixed_count += 1
            else:
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=idx + 1,
                        line_content=stripped,
                        code="RPY002",
                        message="Smart/curly quotes (“ ” ‘ ’ « ») detected in code statement. Will cause Python SyntaxError.",
                        fix_title="Replace smart quotes with standard quotes",
                        fix_replacement=''.join(SMART_QUOTES.get(c, c) for c in new_raw_line),
                    ),
                    noqa_map,
                )

        return new_raw_line, file_modified

class ScreenChecker(BaseChecker):
    def check_line(
        self,
        file_path: str,
        idx: int,
        raw_line: str,
        clean_line: str,
        scope_stack: ScopeStack,
        noqa_map: dict[int, set[str] | None],
        lines: list[str],
    ) -> tuple[str, bool]:
        stripped = clean_line.strip()
        is_in_screen = scope_stack.current_screen_name() is not None

        if is_in_screen:
            m_def = RE_DEFAULT.match(stripped)
            if m_def:
                scope_stack.add_symbol(m_def.group(1))

            m_for = RE_FOR_LOOP.match(stripped)
            if m_for:
                scope_stack.add_symbol(m_for.group(1))

            m_btn = RE_BUTTON_LINE.match(stripped)
            if m_btn:
                # RPY203: кнопка без действия action
                if not stripped.endswith(":") and not re.search(r"\baction\b", stripped):
                    btn_word = m_btn.group(1)
                    start_c, end_c = self.analyzer._get_utf16_range(raw_line, btn_word)
                    self.analyzer._add_diagnostic(
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
                        start_c, end_c = self.analyzer._get_utf16_range(raw_line, f"action {fn_name}(")
                        self.analyzer._add_diagnostic(
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

        # RPY204: Вызов несуществующего экрана
        m_scr = RE_SCREEN_CALL.match(stripped) if stripped.startswith(("show screen", "call screen", "use ")) else None
        if m_scr:
            screen_target = m_scr.group(1)
            if screen_target not in self.analyzer.declared_screens and screen_target not in BUILTIN_SCREENS:
                all_screens = list(self.analyzer.declared_screens.keys()) + list(BUILTIN_SCREENS)
                matches = difflib.get_close_matches(screen_target, all_screens, n=1, cutoff=0.6)
                hint = f" (did you mean '{matches[0]}' ?)" if matches else ""
                start_c, end_c = self.analyzer._get_utf16_range(raw_line, screen_target)
                self.analyzer._add_diagnostic(
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

        return raw_line, False

class AssetChecker(BaseChecker):
    def check_line(
        self,
        file_path: str,
        idx: int,
        raw_line: str,
        clean_line: str,
        scope_stack: ScopeStack,
        noqa_map: dict[int, set[str] | None],
        lines: list[str],
    ) -> tuple[str, bool]:
        stripped = clean_line.strip()
        is_in_screen = scope_stack.current_screen_name() is not None

        # RPY502: Проверка show / scene
        m_show = RE_SHOW_SCENE.match(stripped) if (not is_in_screen and stripped.startswith(("show ", "scene "))) else None
        if m_show:
            raw_tokens = m_show.group(2).split()
            img_tokens = []
            for t in raw_tokens:
                clean_t = t.rstrip(":")
                if clean_t in CLAUSE_KEYWORDS:
                    break
                img_tokens.append(clean_t)
                if t.endswith(":"):
                    break

            if img_tokens:
                full_img_tag = " ".join(img_tokens)
                self.analyzer._mark_asset_used(full_img_tag)
                base_tag = img_tokens[0]
                all_valid = self.analyzer.valid_images.union(self.analyzer.declared_images.keys())

                has_base = (
                    base_tag in self.analyzer.declared_layeredimages
                    or any(img.startswith(base_tag + " ") or img == base_tag for img in all_valid)
                )
                is_single_tag = len(img_tokens) == 1 and m_show.group(1) == "show"

                if full_img_tag in all_valid or full_img_tag in BUILTIN_COLORS or (is_single_tag and has_base):
                    pass
                elif has_base:
                    valid_attrs = self.analyzer._get_tag_known_attributes(base_tag, all_valid)
                    provided_attrs = img_tokens[1:]
                    invalid_attrs = []

                    for attr in provided_attrs:
                        clean_attr = attr.removeprefix("-")
                        if clean_attr not in valid_attrs:
                            invalid_attrs.append(clean_attr)

                    if not (valid_attrs and not invalid_attrs):
                        err_attr = invalid_attrs[0] if invalid_attrs else full_img_tag
                        matches = difflib.get_close_matches(err_attr, list(valid_attrs), n=1, cutoff=0.6)
                        hint = f" (did you mean attribute '{matches[0]}' ?)" if matches else ""
                        start_c, end_c = self.analyzer._get_utf16_range(raw_line, err_attr)
                        self.analyzer._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=idx + 1,
                                line_content=stripped,
                                code="RPY502",
                                message=f"Attribute '{err_attr}' is not defined for character '{base_tag}'{hint}.",
                                col=start_c,
                                end_col=end_c,
                                fix_title=f"Change to '{matches[0]}'" if matches else None,
                                fix_replacement=matches[0] if matches else None,
                            ),
                            noqa_map,
                        )
                else:
                    all_tags = {img.split()[0] for img in all_valid}.union(self.analyzer.declared_layeredimages.keys())
                    matched_tags = difflib.get_close_matches(base_tag, list(all_tags), n=1, cutoff=0.7)
                    hint = f" (did you mean base tag '{matched_tags[0]}' ?)" if matched_tags else ""
                    start_c, end_c = self.analyzer._get_utf16_range(raw_line, base_tag)
                    self.analyzer._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=idx + 1,
                            line_content=stripped,
                            code="RPY502",
                            message=f"Sprite or background '{base_tag}' not found in assets or 'image' definitions{hint}.",
                            col=start_c,
                            end_col=end_c,
                            fix_title=f"Change to '{matched_tags[0]}'" if matched_tags else None,
                            fix_replacement=matched_tags[0] if matched_tags else None,
                        ),
                        noqa_map,
                    )

        # RPY501: Проверка аудио (play / queue)
        m_play = RE_PLAY_AUDIO.match(stripped) if stripped.startswith(("play ", "queue ")) else None
        if m_play:
            raw_audio_target = m_play.group(1).strip()
            audio_found = False

            if raw_audio_target.startswith(('"', "'")) and raw_audio_target.endswith(('"', "'")):
                clean_audio_path = raw_audio_target[1:-1].strip()
                clean_audio_path = re.sub(r"^<[^>]+>\s*", "", clean_audio_path)
                clean_audio_path = clean_audio_path.replace("\\", "/").lower()
                audio_file = os.path.basename(clean_audio_path)
                if clean_audio_path in self.analyzer.known_assets or audio_file in self.analyzer.known_assets:
                    audio_found = True
                    self.analyzer._mark_asset_used(clean_audio_path)
                    self.analyzer._mark_asset_used(audio_file)
            else:
                identifier = raw_audio_target.removeprefix("audio.")
                if identifier in self.analyzer.defined_audio_map:
                    audio_found = True
                    self.analyzer._mark_asset_used(self.analyzer.defined_audio_map[identifier])
                elif identifier in self.analyzer.audio_dir_files:
                    audio_found = True
                    self.analyzer._mark_asset_used(self.analyzer.audio_dir_files[identifier])
                elif identifier in self.analyzer.known_assets:
                    audio_found = True
                    self.analyzer._mark_asset_used(identifier)

            if not audio_found:
                start_c, end_c = self.analyzer._get_utf16_range(raw_line, raw_audio_target)
                self.analyzer._add_diagnostic(
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

        return raw_line, False

class DialogueChecker(BaseChecker):
    """RPY3xx — Диалоги, проверка кавычек, переходов jump/call и падений в метки."""
    def __init__(self, analyzer: SenpyAnalyzer):
        super().__init__(analyzer)
        self.in_label_context = False

    def reset(self) -> None:
        self.in_label_context = False

    def check_line(
        self,
        file_path: str,
        idx: int,
        raw_line: str,
        clean_line: str,
        scope_stack: ScopeStack,
        noqa_map: dict[int, set[str] | None],
        lines: list[str],
        branch_uninitialized: dict | None = None,
    ) -> tuple[str, bool]:
        from senpy.analyzer import _strip_comment

        stripped = clean_line.strip()
        line_indent = len(raw_line) - len(raw_line.lstrip(" "))
        is_in_screen = scope_stack.current_screen_name() is not None

        if line_indent == 0 and stripped.startswith(("screen ", "style ", "init ", "transform ")):
            self.in_label_context = False

        # RPY308: Проверка на падение сюжета (fallthrough) перед меткой
        m_label = RE_LABEL.match(clean_line)
        if m_label:
            if self.in_label_context and idx > 0:
                prev_idx = idx - 1
                while prev_idx >= 0 and not lines[prev_idx].strip():
                    prev_idx -= 1
                if prev_idx >= 0:
                    prev_clean = _strip_comment(lines[prev_idx]).strip()
                    if (
                        prev_clean
                        and not prev_clean.startswith((
                            "return",
                            "jump ",
                            "jump\t",
                            "call ",
                            "call\t",
                            "renpy.full_restart",
                            "renpy.quit",
                        ))
                        and not prev_clean.endswith(":")
                    ):
                        self.analyzer._add_diagnostic(
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
            self.in_label_context = True

        # RPY302 & RPY306: Переходы jump и call
        m_jump = RE_JUMP_CALL.match(stripped) if stripped.startswith(("jump ", "call ")) else None
        if m_jump:
            cmd_type, target_label = m_jump.group(1), m_jump.group(2)
            if target_label == "expression":
                self.analyzer.has_dynamic_jumps = True
            else:
                self.analyzer.referenced_labels.add(target_label)
                if target_label not in self.analyzer.declared_labels:
                    matches = difflib.get_close_matches(target_label, list(self.analyzer.declared_labels.keys()), n=1, cutoff=0.6)
                    best_match = matches[0] if matches else None
                    hint = f" (did you mean '{best_match}' ?)" if best_match else ""
                    start_c, end_c = self.analyzer._get_utf16_range(raw_line, target_label)
                    self.analyzer._add_diagnostic(
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
                if cmd_type == "jump" and branch_uninitialized is not None:
                    branch_uninitialized.clear()
                elif cmd_type == "call" and target_label in self.analyzer.declared_labels and not self.analyzer._can_reach_return(target_label):
                    self.analyzer._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=idx + 1,
                            line_content=stripped,
                            code="RPY306",
                            message=f"Static analysis could not find a 'return' path from called label '{target_label}'. Verify that control flow returns correctly.",
                        ),
                        noqa_map,
                    )

        # RPY305: Неэкранированные кавычки в диалоге
        first_token = stripped.split()[0] if stripped.split() else ""
        if self.in_label_context and not is_in_screen and first_token not in NON_DIALOGUE_STATEMENTS:
            unescaped_quotes = re.findall(r'(?<!\\)"', stripped)
            is_odd_quotes = len(unescaped_quotes) % 2 != 0
            has_inner_quotes = bool(re.search(r'(?<!\\)"[^"\\]*(?<!\\)"\s+[^\s"\'#]+.*(?<!\\)"', stripped))
            if is_odd_quotes or has_inner_quotes:
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=idx + 1,
                        line_content=stripped,
                        code="RPY305",
                        message="Unescaped quotes inside dialogue text. Use '\\\"' instead of '\"' to avoid syntax errors.",
                    ),
                    noqa_map,
                )

        return raw_line, False

class StateChecker(BaseChecker):
    """RPY1xx, RPY4xx — Проверка переменных, типов, условий, мутаций и развилок menu."""

    def __init__(self, analyzer: SenpyAnalyzer):
        super().__init__(analyzer)
        self.branch_uninitialized: dict[str, tuple[str, str]] = {}

    def reset(self) -> None:
        self.branch_uninitialized.clear()

    def check_line(
        self,
        file_path: str,
        idx: int,
        next_idx: int,
        raw_line: str,
        clean_line: str,
        scope_stack: ScopeStack,
        noqa_map: dict[int, set[str] | None],
        lines: list[str],
    ) -> tuple[int, bool]:
        file_modified = False
        stripped = clean_line.strip()
        is_in_screen = scope_stack.current_screen_name() is not None

        # RPY401: Проверка интерполяций [var] после развилок menu
        self.analyzer._check_cfg_interpolations(
            file_path, idx + 1, stripped, self.branch_uninitialized, noqa_map
        )

        # menu: развилки
        m_menu = RE_MENU_START.match(raw_line)
        if m_menu and not is_in_screen:
            menu_indent = len(m_menu.group(1))
            consumed_idx, uninit_vars = self.analyzer._analyze_menu_flow(
                lines,
                idx + 1,
                menu_indent,
                file_path=file_path,
                noqa_map=noqa_map,
            )
            self.branch_uninitialized.update(uninit_vars)
            return consumed_idx, file_modified

        # $ python code
        if stripped.startswith("$"):
            py_code = stripped[1:].strip()
            if is_in_screen:
                self.analyzer._check_screen_mutation(
                    py_code,
                    file_path,
                    idx + 1,
                    stripped,
                    scope_stack.current_screen_name(),
                    scope_stack.get_local_symbols(),
                    noqa_map,
                    lines=lines,
                )
            else:
                self.analyzer._check_python_ast(
                    py_code, file_path, start_line=idx + 1, noqa_map=noqa_map, lines=lines
                )
                self.analyzer._clear_safe_cfg_vars(py_code, self.branch_uninitialized)
            return idx + 1, file_modified

        # python: block
        m_py = RE_PYTHON_BLOCK_START.match(raw_line)
        if m_py:
            indent = len(m_py.group(1))
            consumed_idx, block_lines = self.analyzer._consume_block(lines, idx + 1, indent)
            if block_lines:
                code = textwrap.dedent("".join(block_lines))
                if is_in_screen:
                    self.analyzer._check_screen_mutation(
                        code,
                        file_path,
                        idx + 2,
                        stripped,
                        scope_stack.current_screen_name(),
                        scope_stack.get_local_symbols(),
                        noqa_map,
                        lines=lines,
                    )
                else:
                    self.analyzer._check_python_ast(
                        code, file_path, start_line=idx + 2, noqa_map=noqa_map, lines=lines
                    )
                    self.analyzer._clear_safe_cfg_vars(code, self.branch_uninitialized)
            return consumed_idx, file_modified

        # if / elif condition
        m_cond = RE_CONDITION.match(stripped) if stripped.startswith(("if ", "elif ")) else None
        if m_cond:
            expr = m_cond.group(1)
            self.analyzer._check_condition(
                file_path,
                idx + 1,
                stripped,
                expr,
                scope_stack.current_screen_name(),
                scope_stack.get_local_symbols(),
                noqa_map,
            )
            self.analyzer._check_cfg_condition(
                file_path,
                idx + 1,
                stripped,
                expr,
                self.branch_uninitialized,
                noqa_map,
            )

        return next_idx, file_modified