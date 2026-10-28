from __future__ import annotations

import difflib
import os
import re
import textwrap

from senpy.constants import (
    BUILTIN_ACTIONS,
    BUILTIN_COLORS,
    BUILTIN_SCREENS,
    CLAUSE_KEYWORDS,
    NON_DIALOGUE_STATEMENTS,
    RE_AUDIO_STATEMENT,
    RE_BUTTON_LINE,
    RE_CONDITION,
    RE_DEFAULT,
    RE_FOR_LOOP,
    RE_JUMP_CALL,
    RE_LABEL,
    RE_MENU_START,
    RE_PYTHON_BLOCK_START,
    RE_SCREEN_CALL,
    RE_SHOW_SCENE,
    RE_STOP_STATEMENT,
    SCREEN_LOCAL_IGNORE,
    SMART_QUOTES,
)
from senpy.flow import FlowBranch, merge_flow_branches
from senpy.models import Diagnostic
from senpy.python_ast import extract_assigned_names
from senpy.signature import validate_call_arguments


class IfBlockContext:
    """Контекст активного блока if/elif/else в анализе потока управления."""

    def __init__(self, indent: int, line: int):
        self.indent = indent
        self.line = line
        self.branches: list[FlowBranch] = []
        self.current_branch: FlowBranch | None = None


from senpy.scope import ScopeStack  # noqa: E402
from senpy.sink import DiagnosticSink  # Фаза 1.3: Protocol вместо SenpyAnalyzer  # noqa: E402


class BaseChecker:
    def __init__(self, analyzer: DiagnosticSink):
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
        leading_ws = new_raw_line[: len(new_raw_line) - len(new_raw_line.lstrip())]
        if "\t" in leading_ws:
            self.analyzer.fixable_count += 1
            if self.analyzer.fix:
                fixed_leading = leading_ws.replace("\t", "    ")
                new_raw_line = fixed_leading + new_raw_line[len(leading_ws) :]
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
            or (
                scope_stack.current_screen_name() is not None
                and not stripped.startswith(("text ", "textbutton "))
            )
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
                        fix_replacement="".join(SMART_QUOTES.get(c, c) for c in new_raw_line),
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

            # RPY202 & RPY208: Проверка переменных в screen Actions (SetVariable, ToggleVariable)
            if "SetVariable" in stripped or "ToggleVariable" in stripped:
                for m_var_act in re.finditer(
                    r'\b(SetVariable|ToggleVariable)\s*\(\s*["\']([^\W\d]\w*)["\']', stripped
                ):
                    act_name = m_var_act.group(1)
                    target_var = m_var_act.group(2)
                    local_syms = scope_stack.get_local_symbols()

                    # RPY208: Использование глобального SetVariable / ToggleVariable на локальной переменной экрана
                    if target_var in local_syms and target_var not in SCREEN_LOCAL_IGNORE:
                        correct_act = (
                            "SetScreenVariable"
                            if act_name == "SetVariable"
                            else "ToggleScreenVariable"
                        )
                        start_c, end_c = self.analyzer._get_utf16_range(raw_line, act_name)
                        self.analyzer._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=idx + 1,
                                line_content=stripped,
                                code="RPY208",
                                message=(
                                    f"Screen action '{act_name}' targets screen-local variable '{target_var}'. "
                                    f"This leaks into the global store instead of updating the screen! "
                                    f"Use '{correct_act}' instead."
                                ),
                                severity="ERROR",
                                col=start_c,
                                end_col=end_c,
                                fix_title=f"Replace '{act_name}' with '{correct_act}'",
                                fix_replacement=correct_act,
                                fix_start_col=start_c,
                                fix_end_col=end_c,
                            ),
                            noqa_map,
                        )

                    elif (
                        target_var not in self.analyzer.declared_symbols
                        and target_var not in self.analyzer.user_symbols
                        and target_var not in local_syms
                        and not target_var.startswith("_")
                    ):
                        matches = difflib.get_close_matches(
                            target_var, list(self.analyzer.user_symbols), n=1, cutoff=0.6
                        )
                        hint = f" (did you mean '{matches[0]}' ?)" if matches else ""
                        start_c, end_c = self.analyzer._get_utf16_range(raw_line, target_var)
                        self.analyzer._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=idx + 1,
                                line_content=stripped,
                                code="RPY202",
                                message=(
                                    f"Screen action references undeclared variable '{target_var}'{hint}. "
                                    "Variable must be declared with 'default' at top-level to ensure save persistence."
                                ),
                                severity="WARNING",
                                col=start_c,
                                end_col=end_c,
                                fix_title=f"Change to '{matches[0]}'" if matches else None,
                                fix_replacement=matches[0] if matches else None,
                            ),
                            noqa_map,
                        )

            # RPY204: Проверка экранов в screen Actions (Show, ShowMenu, Hide)
            if any(act in stripped for act in ("Show", "ShowMenu", "Hide")):
                for m_scr_act in re.finditer(
                    r'\b(?:Show|ShowMenu|Hide)\s*\(\s*["\']([^\W\d]\w*)["\']', stripped
                ):
                    target_scr = m_scr_act.group(1)
                    if (
                        target_scr not in self.analyzer.screens
                        and target_scr not in BUILTIN_SCREENS
                    ):
                        all_screens = list(self.analyzer.screens.keys()) + list(BUILTIN_SCREENS)
                        matches = difflib.get_close_matches(
                            target_scr, all_screens, n=1, cutoff=0.6
                        )
                        hint = f" (did you mean '{matches[0]}' ?)" if matches else ""
                        start_c, end_c = self.analyzer._get_utf16_range(raw_line, target_scr)
                        self.analyzer._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=idx + 1,
                                line_content=stripped,
                                code="RPY204",
                                message=f"Screen action references non-existent screen '{target_scr}'{hint}. Causes runtime ScriptError.",
                                severity="ERROR",
                                col=start_c,
                                end_col=end_c,
                                fix_title=f"Change to '{matches[0]}'" if matches else None,
                                fix_replacement=matches[0] if matches else None,
                            ),
                            noqa_map,
                        )

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
                m_act = re.search(r"\baction\s+([^\W\d]\w*)\s*\(", stripped)
                if m_act:
                    fn_name = m_act.group(1)
                    if fn_name not in BUILTIN_ACTIONS:
                        start_c, end_c = self.analyzer._get_utf16_range(
                            raw_line, f"action {fn_name}("
                        )
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

        # RPY204: Вызов несуществующего экрана (проверяем по self.analyzer.screens)
        m_scr = (
            RE_SCREEN_CALL.match(stripped)
            if stripped.startswith(("show screen", "call screen", "use "))
            else None
        )
        if m_scr:
            screen_target = m_scr.group(1)
            if screen_target not in self.analyzer.screens and screen_target not in BUILTIN_SCREENS:
                all_screens = list(self.analyzer.screens.keys()) + list(BUILTIN_SCREENS)
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

        # RPY207: Несовпадение аргументов при вызове экрана
        if m_scr:
            screen_target = m_scr.group(1)
            if (
                screen_target in self.analyzer.screens
                and self.analyzer.screens[screen_target].signature
            ):
                sig = self.analyzer.screens[screen_target].signature
                m_scr_args = re.search(
                    r"\b(?:show\s+screen|call\s+screen|use)\s+[^\W\d]\w*\s*(?:\((.*?)\))?", stripped
                )
                scr_args = (
                    m_scr_args.group(1) if m_scr_args and m_scr_args.group(1) is not None else None
                )
                err_msg = validate_call_arguments(sig, scr_args)
                if err_msg:
                    self.analyzer._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=idx + 1,
                            line_content=stripped,
                            code="RPY207",
                            message=f"Invalid parameters in screen '{screen_target}': {err_msg}. Causes runtime Exception.",
                            severity="ERROR",
                        ),
                        noqa_map,
                    )

        return raw_line, False


class AssetChecker(BaseChecker):
    def _validate_transition_expr(
        self,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        expr_str: str,
        noqa_map: dict[int, set[str] | None],
    ) -> None:
        clean_expr = expr_str.strip().rstrip(",")
        m_name = re.match(r"^([^\W\d]\w*)", clean_expr)
        if not m_name:
            return
        trans_name = m_name.group(1)
        if (
            trans_name not in self.analyzer.declared_symbols
            and trans_name not in self.analyzer.user_symbols
        ):
            all_candidates = [s for s in self.analyzer.declared_symbols if s.isidentifier()]
            matches = difflib.get_close_matches(trans_name, all_candidates, n=1, cutoff=0.6)
            hint = f" (did you mean '{matches[0]}' ?)" if matches else ""
            start_c, end_c = self.analyzer._get_utf16_range(raw_line, trans_name)
            self.analyzer._add_diagnostic(
                Diagnostic(
                    file_path=file_path,
                    line_number=idx + 1,
                    line_content=stripped,
                    code="RPY502",
                    message=f"Transition '{trans_name}' is not defined{hint}. Causes runtime NameError.",
                    col=start_c,
                    end_col=end_c,
                    fix_title=f"Change to '{matches[0]}'" if matches else None,
                    fix_replacement=matches[0] if matches else None,
                ),
                noqa_map,
            )

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
        m_show = (
            RE_SHOW_SCENE.match(stripped)
            if (not is_in_screen and stripped.startswith(("show ", "scene ")))
            else None
        )
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

            # "show layer <имя>" — очистка слоя (renpy.show_layer_at), а НЕ показ
            # изображения: слово layer зарезервировано парсером Ren'Py и не может
            # быть тегом картинки. АТ-трансформы ниже проверяются как раньше.
            if img_tokens and img_tokens[0] == "layer" and m_show.group(1) == "show":
                img_tokens = []

            if img_tokens:
                full_img_tag = " ".join(img_tokens)
                self.analyzer._mark_asset_used(full_img_tag)
                base_tag = img_tokens[0]
                all_valid = self.analyzer.valid_images.union(self.analyzer.images.keys())

                has_base = (
                    base_tag in self.analyzer.images and self.analyzer.images[base_tag].is_layered
                ) or any(img.startswith(base_tag + " ") or img == base_tag for img in all_valid)
                is_single_tag = len(img_tokens) == 1 and m_show.group(1) == "show"

                if (
                    full_img_tag in all_valid
                    or full_img_tag in BUILTIN_COLORS
                    or (is_single_tag and has_base)
                ):
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
                        matches = difflib.get_close_matches(
                            err_attr, list(valid_attrs), n=1, cutoff=0.6
                        )
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
                    all_tags = {img.split()[0] for img in all_valid}.union(
                        k for k, v in self.analyzer.images.items() if v.is_layered
                    )
                    matched_tags = difflib.get_close_matches(
                        base_tag, list(all_tags), n=1, cutoff=0.7
                    )
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

            # RPY502: Проверка валидности ATL-трансформаций в конструкции 'show ... at ...'
            m_at = re.search(
                r"\bat\s+([^:]+?)(?:\s+(?:with|as|zorder|behind|onlayer)\b|:|$)", stripped
            )
            if m_at:
                at_clause = m_at.group(1)
                parts: list[str] = []
                curr: list[str] = []
                paren_depth = 0
                for ch in at_clause:
                    if ch == "(":
                        paren_depth += 1
                    elif ch == ")":
                        paren_depth -= 1
                    elif ch == "," and paren_depth == 0:
                        parts.append("".join(curr).strip())
                        curr = []
                        continue
                    curr.append(ch)
                if curr:
                    parts.append("".join(curr).strip())

                for part in parts:
                    m_name = re.match(r"^([^\W\d]\w*)", part)
                    if not m_name:
                        continue
                    trans_name = m_name.group(1)
                    if (
                        trans_name not in self.analyzer.declared_symbols
                        and trans_name not in self.analyzer.user_symbols
                    ):
                        all_candidates = [
                            s for s in self.analyzer.declared_symbols if s.isidentifier()
                        ]
                        matches = difflib.get_close_matches(
                            trans_name, all_candidates, n=1, cutoff=0.6
                        )
                        hint = f" (did you mean '{matches[0]}' ?)" if matches else ""
                        start_c, end_c = self.analyzer._get_utf16_range(raw_line, trans_name)
                        self.analyzer._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=idx + 1,
                                line_content=stripped,
                                code="RPY502",
                                message=f"Transform or position '{trans_name}' is not defined{hint}. Causes runtime NameError.",
                                col=start_c,
                                end_col=end_c,
                                fix_title=f"Change to '{matches[0]}'" if matches else None,
                                fix_replacement=matches[0] if matches else None,
                            ),
                            noqa_map,
                        )

        # RPY502: Проверка переходов в конструкции 'with <transition>'
        if not is_in_screen and not stripped.startswith(("$", "python")):
            trans_expr: str | None = None
            if stripped.startswith(("show ", "scene ")):
                m_sw = re.search(
                    r"\bwith\s+([^:#]+?)(?:\s+(?:onlayer|zorder|behind|as)\b|:|$)", stripped
                )
                if m_sw:
                    trans_expr = m_sw.group(1)
            elif (
                stripped.startswith(("with ", "with\t"))
                and not stripped.endswith(":")
                and not re.search(r"\bas\b", stripped)
            ):
                m_w = re.match(r"^with\s+([^:#]+)", stripped)
                if m_w:
                    trans_expr = m_w.group(1)
            elif re.search(r'["\']\s+with\s+([^:#]+)$', stripped):
                m_dw = re.search(r'["\']\s+with\s+([^:#]+)$', stripped)
                if m_dw:
                    trans_expr = m_dw.group(1)

            if trans_expr:
                self._validate_transition_expr(
                    file_path, idx, raw_line, stripped, trans_expr, noqa_map
                )
        # RPY505: Проверка stop <channel> (Задача 6: раньше stop не проверялся вовсе)
        m_stop = RE_STOP_STATEMENT.match(stripped) if stripped.startswith("stop ") else None
        if m_stop:
            stop_channel = m_stop.group(1).lower()
            if stop_channel not in self.analyzer.registered_audio_channels and stop_channel not in {
                k.lower() for k in self.analyzer.defined_audio_map
            }:
                start_c, end_c = self.analyzer._get_utf16_range(raw_line, m_stop.group(1))
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=idx + 1,
                        line_content=stripped,
                        code="RPY505",
                        message=(
                            f"Audio channel '{stop_channel}' is not a built-in channel (music, sound, voice, audio) "
                            "and has not been registered via 'renpy.music.register_channel()'. Causes runtime Exception."
                        ),
                        severity="WARNING",
                        col=start_c,
                        end_col=end_c,
                    ),
                    noqa_map,
                )

        # RPY501 & RPY505: Проверка play / queue (каналы и файлы)
        m_audio = (
            RE_AUDIO_STATEMENT.match(stripped) if stripped.startswith(("play ", "queue ")) else None
        )
        if m_audio:
            channel = m_audio.group(2).lower()
            rest = (m_audio.group(3) or "").strip()

            # 1. RPY505: Проверка валидности канала
            if channel not in self.analyzer.registered_audio_channels and channel not in {
                k.lower() for k in self.analyzer.defined_audio_map
            }:
                start_c, end_c = self.analyzer._get_utf16_range(raw_line, m_audio.group(2))
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=idx + 1,
                        line_content=stripped,
                        code="RPY505",
                        message=(
                            f"Audio channel '{channel}' is not a built-in channel (music, sound, voice, audio) "
                            "and has not been registered via 'renpy.music.register_channel()' or defined via 'define audio.<channel>'. Causes runtime Exception."
                        ),
                        severity="WARNING",
                        col=start_c,
                        end_col=end_c,
                    ),
                    noqa_map,
                )

            # 2. RPY505: Зацикливание голоса на канале voice
            if channel == "voice" and re.search(r"\bloop\b", rest, re.IGNORECASE):
                start_c, end_c = self.analyzer._get_utf16_range(raw_line, "loop")
                self.analyzer._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=idx + 1,
                        line_content=stripped,
                        code="RPY505",
                        message="Using 'loop' on the 'voice' audio channel. Voice playback is cut off on dialogue advance; looping voice causes audio glitches.",
                        severity="WARNING",
                        col=start_c,
                        end_col=end_c,
                    ),
                    noqa_map,
                )
            # 2a. RPY501: play/queue без файла — файл берётся из 'define audio.<канал>'
            if not rest:
                defined_file = next(
                    (f for k, f in self.analyzer.defined_audio_map.items() if k.lower() == channel),
                    None,
                )
                if defined_file is not None:
                    self.analyzer._mark_asset_used(defined_file)
                elif channel in self.analyzer.registered_audio_channels:
                    start_c, end_c = self.analyzer._get_utf16_range(raw_line, m_audio.group(2))
                    self.analyzer._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=idx + 1,
                            line_content=stripped,
                            code="RPY501",
                            message=(
                                f"'{m_audio.group(2)}' without a file: the file is taken from "
                                f"'define audio.{m_audio.group(2)}', but no such definition was found. "
                                "Add 'define audio.<channel> = \"file.ogg\"' or specify the file explicitly."
                            ),
                            severity="ERROR",
                            col=start_c,
                            end_col=end_c,
                        ),
                        noqa_map,
                    )
            # 3. RPY501: Проверка существования аудиофайла (с поддержкой плейлистов [track1, track2])
            audio_targets = []
            clean_rest = rest.strip()
            if clean_rest.startswith("["):
                b_end = clean_rest.find("]")
                sub_content = clean_rest[1:b_end] if b_end != -1 else clean_rest[1:]
                for m_item in re.finditer(
                    r'("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\'|[^\s,]+)',
                    sub_content,
                ):
                    t = m_item.group(1).strip()
                    if t and t not in (",", "[", "]"):
                        audio_targets.append(t)
            else:
                m_target = re.match(
                    r'("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\'|[^\s]+)',
                    clean_rest,
                )
                if m_target:
                    audio_targets.append(m_target.group(1).strip())

            for raw_audio_target in audio_targets:
                audio_found = False

                if raw_audio_target.startswith(('"', "'")) and raw_audio_target.endswith(
                    ('"', "'")
                ):
                    clean_audio_path = raw_audio_target[1:-1].strip()
                    clean_audio_path = re.sub(r"^<[^>]+>\s*", "", clean_audio_path)
                    clean_audio_path = clean_audio_path.replace("\\", "/").lower()
                    audio_file = os.path.basename(clean_audio_path)
                    if (
                        clean_audio_path in self.analyzer.known_assets
                        or audio_file in self.analyzer.known_assets
                    ):
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

                if not audio_found and raw_audio_target not in ("fadein", "fadeout", "volume"):
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
    """RPY3xx — Диалоги, проверка кавычек, переходов jump/call и падений в меток."""

    def __init__(self, analyzer: DiagnosticSink):
        super().__init__(analyzer)
        self.in_label_context = False
        self.current_global_label: str | None = None

    def reset(self) -> None:
        self.in_label_context = False
        self.current_global_label = None

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
        from senpy.text_utils import _strip_comment  # Фаза 1.3: вынесено в text_utils
        stripped = clean_line.strip()
        line_indent = len(raw_line) - len(raw_line.lstrip(" "))
        is_in_screen = scope_stack.current_screen_name() is not None

        if line_indent == 0 and stripped.startswith(("screen ", "style ", "init ", "transform ")):
            self.in_label_context = False

        # RPY308: Проверка на падение сюжета (fallthrough) перед меткой
        m_label = RE_LABEL.match(clean_line)
        if m_label:
            raw_lbl = m_label.group(1)
            if not raw_lbl.startswith("."):
                self.current_global_label = raw_lbl
            if self.in_label_context and idx > 0:
                prev_idx = idx - 1
                while prev_idx >= 0 and not lines[prev_idx].strip():
                    prev_idx -= 1
                if prev_idx >= 0:
                    prev_clean = _strip_comment(lines[prev_idx]).strip()
                    if (
                        prev_clean
                        and not prev_clean.startswith(
                            (
                                "return",
                                "jump ",
                                "jump\t",
                                "call ",
                                "call\t",
                                "renpy.full_restart",
                                "renpy.quit",
                            )
                        )
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

        # RPY302 & RPY306: Переходы jump и call (проверяем по self.analyzer.labels)
        m_jump = RE_JUMP_CALL.match(stripped) if stripped.startswith(("jump ", "call ")) else None
        if m_jump:
            cmd_type, raw_target = m_jump.group(1), m_jump.group(2)
            if raw_target == "expression":
                self.analyzer.has_dynamic_jumps = True
            else:
                if raw_target.startswith("."):
                    target_label = (
                        f"{self.current_global_label}{raw_target}"
                        if self.current_global_label
                        else raw_target
                    )
                else:
                    target_label = raw_target

                self.analyzer.referenced_labels.add(target_label)
                if target_label not in self.analyzer.labels:
                    matches = difflib.get_close_matches(
                        target_label, list(self.analyzer.labels.keys()), n=1, cutoff=0.6
                    )
                    best_match = matches[0] if matches else None
                    hint = f" (did you mean '{best_match}' ?)" if best_match else ""
                    start_c, end_c = self.analyzer._get_utf16_range(raw_line, raw_target)
                    self.analyzer._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=idx + 1,
                            line_content=stripped,
                            code="RPY302",
                            message=f"{cmd_type.capitalize()} to non-existent label '{raw_target}'{hint}. Causes ScriptError.",
                            col=start_c,
                            end_col=end_c,
                            fix_title=f"Change to '{best_match}'" if best_match else None,
                            fix_replacement=best_match,
                        ),
                        noqa_map,
                    )
                if cmd_type == "jump" and branch_uninitialized is not None:
                    branch_uninitialized.clear()
                elif cmd_type == "call":
                    # 1. RPY310: Проверка сигнатуры аргументов вызова метки
                    if (
                        target_label in self.analyzer.labels
                        and self.analyzer.labels[target_label].signature
                    ):
                        sig = self.analyzer.labels[target_label].signature
                        m_args = re.search(
                            r"\bcall\s+(?!screen\b)[^\W\d]\w*\s*(?:\((.*?)\))?", stripped
                        )
                        call_args = (
                            m_args.group(1) if m_args and m_args.group(1) is not None else None
                        )
                        err_msg = validate_call_arguments(sig, call_args)
                        if err_msg:
                            self.analyzer._add_diagnostic(
                                Diagnostic(
                                    file_path=file_path,
                                    line_number=idx + 1,
                                    line_content=stripped,
                                    code="RPY310",
                                    message=f"Invalid arguments in 'call {target_label}': {err_msg}. Causes fatal TypeError.",
                                    severity="ERROR",
                                ),
                                noqa_map,
                            )

                    # 2. RPY306: Проверка наличия пути к return
                    if target_label in self.analyzer.labels and not self.analyzer._can_reach_return(
                        target_label
                    ):
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

        # RPY302: Переходы через UI Actions и Python (Jump, Call, renpy.jump, renpy.call)
        if any(kw in stripped for kw in ("Jump", "Call", "renpy.jump", "renpy.call")):
            for m_dyn in re.finditer(
                r'\b(?:Jump|Call|renpy\.jump|renpy\.call)\s*\(\s*["\']([^"\']+)["\']', stripped
            ):
                raw_target = m_dyn.group(1)
                if raw_target.startswith("."):
                    target_label = (
                        f"{self.current_global_label}{raw_target}"
                        if self.current_global_label
                        else raw_target
                    )
                else:
                    target_label = raw_target

                self.analyzer.referenced_labels.add(target_label)
                if target_label not in self.analyzer.labels:
                    matches = difflib.get_close_matches(
                        target_label, list(self.analyzer.labels.keys()), n=1, cutoff=0.6
                    )
                    best_match = matches[0] if matches else None
                    hint = f" (did you mean '{best_match}' ?)" if best_match else ""
                    start_c, end_c = self.analyzer._get_utf16_range(raw_line, raw_target)
                    self.analyzer._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=idx + 1,
                            line_content=stripped,
                            code="RPY302",
                            message=f"Jump/Call action to non-existent label '{raw_target}'{hint}. Causes ScriptError.",
                            col=start_c,
                            end_col=end_c,
                            fix_title=f"Change to '{best_match}'" if best_match else None,
                            fix_replacement=best_match,
                        ),
                        noqa_map,
                    )

        # RPY305: Неэкранированные кавычки в диалоге
        first_token = stripped.split()[0] if stripped.split() else ""
        if (
            self.in_label_context
            and not is_in_screen
            and first_token not in NON_DIALOGUE_STATEMENTS
        ):
            unescaped_quotes = re.findall(r'(?<!\\)"', stripped)
            is_odd_quotes = len(unescaped_quotes) % 2 != 0
            has_inner_quotes = bool(
                re.search(r'(?<!\\)"[^"\\]*(?<!\\)"\s+[^\s"\'#]+.*(?<!\\)"', stripped)
            )
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

    def __init__(self, analyzer: DiagnosticSink):
        super().__init__(analyzer)
        self.branch_uninitialized: dict[str, tuple[str, ...]] = {}
        self.guaranteed_vars: set[str] = set()
        self.if_stack: list[IfBlockContext] = []

    def reset(self) -> None:
        self.branch_uninitialized.clear()
        self.guaranteed_vars.clear()
        self.if_stack.clear()

    def _pop_and_merge_all_if(self) -> None:
        while self.if_stack:
            self._merge_if_context(self.if_stack.pop())

    def _merge_if_context(self, ctx: IfBlockContext) -> None:
        has_else = any(b.kind == "else" for b in ctx.branches)
        guaranteed_in_if, uninit_vars, all_terminates = merge_flow_branches(
            branches=ctx.branches,
            block_kind="if",
            block_line=ctx.line,
            has_else=has_else,
            known_symbols=self.analyzer.user_symbols,
            already_guaranteed=self.guaranteed_vars,
        )

        self.branch_uninitialized.update(uninit_vars)

        if self.if_stack:
            self.if_stack[-1].current_branch.defined_vars.update(guaranteed_in_if)
            if all_terminates:
                self.if_stack[-1].current_branch.terminates = True
        else:
            self.guaranteed_vars.update(guaranteed_in_if)

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
        line_indent = len(raw_line) - len(raw_line.lstrip(" "))
        is_in_screen = scope_stack.current_screen_name() is not None

        # Управление стеком if/elif/else ветвлений вне экранов
        if not is_in_screen:
            is_if = bool(re.match(r"^if\s+", stripped) and stripped.endswith(":"))
            is_elif = bool(re.match(r"^elif\s+", stripped) and stripped.endswith(":"))
            is_else = bool(stripped == "else:" or re.match(r"^else\s*:", stripped))

            # Закрываем завершившиеся блоки if при уменьшении отступа
            while self.if_stack:
                top = self.if_stack[-1]
                if line_indent < top.indent:
                    self._merge_if_context(self.if_stack.pop())
                elif line_indent == top.indent:
                    if is_elif or is_else:
                        break
                    self._merge_if_context(self.if_stack.pop())
                else:
                    break

            # Переключение на ветку elif или else
            if (is_elif or is_else) and self.if_stack and line_indent == self.if_stack[-1].indent:
                b_kind = "elif" if is_elif else "else"
                new_branch = FlowBranch(
                    kind=b_kind,
                    name=f"{b_kind} branch",
                    line=idx + 1,
                )
                self.if_stack[-1].branches.append(new_branch)
                self.if_stack[-1].current_branch = new_branch

            # Открытие нового if-блока
            elif is_if:
                new_ctx = IfBlockContext(indent=line_indent, line=idx + 1)
                new_branch = FlowBranch(
                    kind="if",
                    name="if branch",
                    line=idx + 1,
                )
                new_ctx.branches.append(new_branch)
                new_ctx.current_branch = new_branch
                self.if_stack.append(new_ctx)

            # распознаём jump, return и терминирующие вызовы renpy.*
            if self.if_stack and re.match(
                r"^\s*(?:jump\b|return\b|\$?\s*renpy\.(?:quit|full_restart|utter_restart|jump|jump_out_of_context)\b)",
                stripped,
            ):
                self.if_stack[-1].current_branch.terminates = True

        # RPY404: Проверка интерполяций [var] после развилок
        self.analyzer._check_cfg_interpolations(
            file_path, idx + 1, stripped, self.branch_uninitialized, noqa_map
        )

        # menu: развилки (с полной передачей гарантированных переменных в if_stack)
        m_menu = RE_MENU_START.match(raw_line)
        if m_menu and not is_in_screen:
            menu_indent = len(m_menu.group(1))
            consumed_idx, uninit_vars, guaranteed_vars, all_terminates = (
                self.analyzer._analyze_menu_flow(
                    lines,
                    idx + 1,
                    menu_indent,
                    file_path=file_path,
                    noqa_map=noqa_map,
                )
            )
            self.branch_uninitialized.update(uninit_vars)

            # Передаём вычисленные гарантированные переменные меню в текущую ветку if_stack
            if self.if_stack:
                self.if_stack[-1].current_branch.defined_vars.update(guaranteed_vars)
                if all_terminates:
                    self.if_stack[-1].current_branch.terminates = True
            else:
                self.guaranteed_vars.update(guaranteed_vars)

            return consumed_idx, file_modified

        # $ python code
        if stripped.startswith("$"):
            self.analyzer._scan_python_assets(raw_line)
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
                assigned_names = extract_assigned_names(py_code)
                if self.if_stack:
                    self.if_stack[-1].current_branch.defined_vars.update(assigned_names)
                else:
                    self.guaranteed_vars.update(assigned_names)
            return idx + 1, file_modified

        # python: block
        m_py = RE_PYTHON_BLOCK_START.match(raw_line)
        if m_py:
            indent = len(m_py.group(1))
            consumed_idx, block_lines = self.analyzer._consume_block(lines, idx + 1, indent)
            if block_lines:
                self.analyzer._scan_python_assets(block_lines)
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
                    assigned_names = extract_assigned_names(code)
                    if self.if_stack:
                        self.if_stack[-1].current_branch.defined_vars.update(assigned_names)
                        if re.search(
                            r"\brenpy\.(?:quit|full_restart|utter_restart|jump|jump_out_of_context)\s*\(",
                            code,
                        ):
                            self.if_stack[-1].current_branch.terminates = True
                    else:
                        self.guaranteed_vars.update(assigned_names)
            return consumed_idx, file_modified

        # if / elif condition
        m_cond = (
            RE_CONDITION.match(stripped)
            if stripped.startswith(("if ", "elif ", "while "))
            else None
        )
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
