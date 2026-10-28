"""asset — extracted from checkers.py (Фаза 2, 0.5.4)."""

from __future__ import annotations

import difflib
import os
import re

from senpy.core.constants import (
    BUILTIN_COLORS,
    CLAUSE_KEYWORDS,
    RE_AUDIO_STATEMENT,
    RE_SHOW_SCENE,
    RE_STOP_STATEMENT,
)
from senpy.core.models import Diagnostic
from senpy.core.scope import ScopeStack
from senpy.rules.base import BaseChecker


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
