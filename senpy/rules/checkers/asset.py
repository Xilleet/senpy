"""asset — extracted from checkers.py (Phase 2, 0.5.4)."""

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
from senpy.text_utils import strip_string_literals

# Regex to match individual audio targets inside a playlist `[a, b, c]` or a
# single-file statement `play music "file.ogg"`. Matches quoted strings or
# bare tokens up to whitespace/commas.
_RE_AUDIO_TARGET = re.compile(
    r'("([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\'|[^\s,]+)'
)


def _parse_audio_targets(rest: str) -> list[str]:
    """Parse audio file targets from the `rest` part of a play/queue statement.

    Handles both:
        - Playlists: `[track1, "track2.ogg", track3]` → 3 targets
        - Single files: `"bgm.ogg"` or `audio.bgm_calm` → 1 target
    """
    clean_rest = rest.strip()
    if not clean_rest:
        return []

    targets: list[str] = []
    if clean_rest.startswith("["):
        b_end = clean_rest.find("]")
        sub_content = clean_rest[1:b_end] if b_end != -1 else clean_rest[1:]
        for m_item in _RE_AUDIO_TARGET.finditer(sub_content):
            t = m_item.group(1).strip()
            if t and t not in (",", "[", "]"):
                targets.append(t)
    else:
        m_target = _RE_AUDIO_TARGET.match(clean_rest)
        if m_target:
            targets.append(m_target.group(1).strip())
    return targets


def _split_at_clause(at_clause: str) -> list[str]:
    """Split an `at` clause into individual transform parts by comma.

    Handles parenthesized expressions (e.g. `at center, ease(1.0, 2.0)`)
    by tracking paren depth — commas inside parens don't split.
    """
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
    return parts


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

    # =========================================================================
    # check_line is split into 2 methods.
    # check_line is now a dispatcher
    # =========================================================================

    def _check_show_scene(
        self,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        scope_stack: ScopeStack,
        noqa_map: dict,
    ) -> None:
        """RPY502: Check show / scene — sprites, ATL transforms, transitions."""
        is_in_screen = scope_stack.current_screen_name() is not None
        m_show = (
            RE_SHOW_SCENE.match(stripped)
            if (not is_in_screen and stripped.startswith(("show ", "scene ")))
            else None
        )
        if m_show:
            self._validate_show_scene_image(
                m_show=m_show,
                file_path=file_path,
                idx=idx,
                raw_line=raw_line,
                stripped=stripped,
                noqa_map=noqa_map,
            )
            self._validate_atl_transforms(
                m_show=m_show,
                stripped=stripped,
                file_path=file_path,
                idx=idx,
                raw_line=raw_line,
                noqa_map=noqa_map,
            )
        if not is_in_screen and not stripped.startswith(("$", "python")):
            self._validate_transition_clause(
                stripped=stripped,
                file_path=file_path,
                idx=idx,
                raw_line=raw_line,
                noqa_map=noqa_map,
            )

    def _validate_show_scene_image(
        self,
        *,
        m_show,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        noqa_map: dict,
    ) -> None:
        """RPY502: Validate the image name and attributes in show/scene.

        Dispatcher: extracts image tokens via `_extract_show_image_tokens`,
        then dispatches to `_validate_image_attributes` (base exists, attrs wrong)
        or `_emit_unknown_base_tag` (base tag missing).
        """
        extracted = self._extract_show_image_tokens(m_show)
        if extracted is None:
            return

        img_tokens, full_img_tag = extracted
        self.analyzer._mark_asset_used(full_img_tag)
        base_tag = img_tokens[0]
        all_valid = self.analyzer.valid_images.union(self.analyzer.images.keys())

        has_base = (
            base_tag in self.analyzer.images and self.analyzer.images[base_tag].is_layered
        ) or any(img.startswith(base_tag + " ") or img == base_tag for img in all_valid)
        is_single_tag = len(img_tokens) == 1 and m_show.group(1) == "show"

        # Case 1: full tag or single-tag-with-base is valid → OK
        if (
            full_img_tag in all_valid
            or full_img_tag in BUILTIN_COLORS
            or (is_single_tag and has_base)
        ):
            return

        # Case 2: base tag exists, but some attributes are wrong
        if has_base:
            self._validate_image_attributes(
                base_tag=base_tag,
                img_tokens=img_tokens,
                full_img_tag=full_img_tag,
                all_valid=all_valid,
                file_path=file_path,
                idx=idx,
                raw_line=raw_line,
                stripped=stripped,
                noqa_map=noqa_map,
            )
            return

        # Case 3: base tag not found → suggest closest
        self._emit_unknown_base_tag(
            base_tag=base_tag,
            all_valid=all_valid,
            file_path=file_path,
            idx=idx,
            raw_line=raw_line,
            stripped=stripped,
            noqa_map=noqa_map,
        )

    @staticmethod
    def _extract_show_image_tokens(m_show) -> tuple[list[str], str] | None:
        """Parse `m_show.group(2)` into (img_tokens, full_img_tag), or None if the
        statement is not actually showing an image (no tokens, or `show layer <name>`).

        Stops at the first CLAUSE_KEYWORDS token (e.g. `at`, `with`, `as`) and at
        the first token ending with `:` (ATL block opener).
        """
        raw_tokens = m_show.group(2).split()
        img_tokens: list[str] = []
        for t in raw_tokens:
            clean_t = t.rstrip(":")
            if clean_t in CLAUSE_KEYWORDS:
                break
            img_tokens.append(clean_t)
            if t.endswith(":"):
                break

        # "show layer <name>" — clearing a layer, NOT showing an image
        if img_tokens and img_tokens[0] == "layer" and m_show.group(1) == "show":
            return None

        if not img_tokens:
            return None

        return img_tokens, " ".join(img_tokens)

    def _validate_image_attributes(
        self,
        *,
        base_tag: str,
        img_tokens: list[str],
        full_img_tag: str,
        all_valid: set,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        noqa_map: dict,
    ) -> None:
        """RPY502: Validate attributes of a known base tag (e.g. `sayori happy` → check `happy`).

        Improvement (0.7.6): case-insensitive attribute matching. If the user
        writes `show sayori Happy` but the attribute is `happy`, suggest the
        correctly-cased attribute. Falls back to difflib fuzzy match.
        """
        valid_attrs = self.analyzer._get_tag_known_attributes(base_tag, all_valid)
        provided_attrs = img_tokens[1:]
        invalid_attrs = []
        for attr in provided_attrs:
            clean_attr = attr.removeprefix("-")
            if clean_attr not in valid_attrs:
                invalid_attrs.append(clean_attr)

        if valid_attrs and not invalid_attrs:
            return  # all provided attributes are valid

        err_attr = invalid_attrs[0] if invalid_attrs else full_img_tag

        # Case-insensitive exact match for attributes: "Happy" → suggest "happy"
        case_match = None
        for attr in valid_attrs:
            if attr.lower() == err_attr.lower():
                case_match = attr
                break

        if case_match:
            hint = f" (case mismatch: did you mean '{case_match}' ?)"
            fix_attr = case_match
        else:
            # Standard difflib fuzzy match (case-sensitive, 0.6 cutoff)
            matches = difflib.get_close_matches(err_attr, list(valid_attrs), n=1, cutoff=0.6)
            hint = f" (did you mean attribute '{matches[0]}' ?)" if matches else ""
            fix_attr = matches[0] if matches else None
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
                fix_title=f"Change to '{fix_attr}'" if fix_attr else None,
                fix_replacement=fix_attr,
            ),
            noqa_map,
        )

    def _emit_unknown_base_tag(
        self,
        *,
        base_tag: str,
        all_valid: set,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        noqa_map: dict,
    ) -> None:
        """RPY502: Emit 'sprite not found' diagnostic with closest-match suggestion.

        Improvement (0.7.6): case-insensitive matching. If the user writes
        `show Sayori` but the image is defined as `sayori`, the standard
        difflib.get_close_matches (case-sensitive) returns no match.
        We now check for case-insensitive exact matches first, and if
        found, suggest the correctly-cased tag as a fix.
        """
        all_tags = {img.split()[0] for img in all_valid}.union(
            k for k, v in self.analyzer.images.items() if v.is_layered
        )

        # Case-insensitive exact match: "Sayori" → suggest "sayori"
        case_match = None
        for tag in all_tags:
            if tag.lower() == base_tag.lower():
                case_match = tag
                break

        if case_match:
            hint = f" (case mismatch: did you mean '{case_match}' ?)"
            fix_tag = case_match
        else:
            # Standard difflib fuzzy match (case-sensitive, 0.7 cutoff)
            matched_tags = difflib.get_close_matches(base_tag, list(all_tags), n=1, cutoff=0.7)
            hint = f" (did you mean base tag '{matched_tags[0]}' ?)" if matched_tags else ""
            fix_tag = matched_tags[0] if matched_tags else None

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
                fix_title=f"Change to '{fix_tag}'" if fix_tag else None,
                fix_replacement=fix_tag,
            ),
            noqa_map,
        )

    def _validate_atl_transforms(
        self,
        *,
        m_show,
        stripped: str,
        file_path: str,
        idx: int,
        raw_line: str,
        noqa_map: dict,
    ) -> None:
        """RPY502: Validate ATL transforms in `show X at <transform>`."""
        m_at = re.search(r"\bat\s+([^:]+?)(?:\s+(?:with|as|zorder|behind|onlayer)\b|:|$)", stripped)
        if not m_at:
            return

        at_clause = m_at.group(1)
        parts = _split_at_clause(at_clause)
        for part in parts:
            m_name = re.match(r"^([^\W\d]\w*)", part)
            if not m_name:
                continue
            trans_name = m_name.group(1)
            if (
                trans_name in self.analyzer.declared_symbols
                or trans_name in self.analyzer.user_symbols
            ):
                continue
            # Transform not found → suggest closest
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
                    message=f"Transform or position '{trans_name}' is not defined{hint}. Causes runtime NameError.",
                    col=start_c,
                    end_col=end_c,
                    fix_title=f"Change to '{matches[0]}'" if matches else None,
                    fix_replacement=matches[0] if matches else None,
                ),
                noqa_map,
            )

    def _validate_transition_clause(
        self,
        *,
        stripped: str,
        file_path: str,
        idx: int,
        raw_line: str,
        noqa_map: dict,
    ) -> None:
        """RPY502: Detect `with <transition>` and delegate to `_validate_transition_expr`."""
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
            self._validate_transition_expr(file_path, idx, raw_line, stripped, trans_expr, noqa_map)

    def _check_audio_statement(
        self,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        noqa_map: dict,
    ) -> None:
        """RPY501/RPY505: Check play / queue / stop (channels and files)."""
        if stripped.startswith("stop "):
            self._check_stop_audio(
                file_path=file_path,
                idx=idx,
                raw_line=raw_line,
                stripped=stripped,
                noqa_map=noqa_map,
            )
            return

        if stripped.startswith(("play ", "queue ")):
            self._check_play_queue_audio(
                file_path=file_path,
                idx=idx,
                raw_line=raw_line,
                stripped=stripped,
                noqa_map=noqa_map,
            )

    def _check_stop_audio(
        self,
        *,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        noqa_map: dict,
    ) -> None:
        """RPY505: Verify `stop <channel>` references a valid audio channel."""
        m_stop = RE_STOP_STATEMENT.match(stripped)
        if not m_stop:
            return
        stop_channel = m_stop.group(1).lower()
        if stop_channel in self.analyzer.registered_audio_channels:
            return
        if stop_channel in {k.lower() for k in self.analyzer.defined_audio_map}:
            return
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

    def _check_play_queue_audio(
        self,
        *,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        noqa_map: dict,
    ) -> None:
        """RPY501/RPY505: Validate play/queue channel + audio file existence."""
        m_audio = RE_AUDIO_STATEMENT.match(stripped)
        if not m_audio:
            return

        channel = m_audio.group(2).lower()
        rest = (m_audio.group(3) or "").strip()

        self._validate_audio_channel(
            channel=channel,
            raw_channel=m_audio.group(2),
            file_path=file_path,
            idx=idx,
            raw_line=raw_line,
            stripped=stripped,
            noqa_map=noqa_map,
        )
        self._check_voice_loop(
            channel=channel,
            rest=rest,
            raw_line=raw_line,
            file_path=file_path,
            idx=idx,
            stripped=stripped,
            noqa_map=noqa_map,
        )
        self._check_audio_file_targets(
            channel=channel,
            rest=rest,
            m_audio=m_audio,
            file_path=file_path,
            idx=idx,
            raw_line=raw_line,
            stripped=stripped,
            noqa_map=noqa_map,
        )

    def _validate_audio_channel(
        self,
        *,
        channel: str,
        raw_channel: str,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        noqa_map: dict,
    ) -> None:
        """RPY505: Validate the channel name in a play/queue statement."""
        if channel in self.analyzer.registered_audio_channels:
            return
        if channel in {k.lower() for k in self.analyzer.defined_audio_map}:
            return
        start_c, end_c = self.analyzer._get_utf16_range(raw_line, raw_channel)
        self.analyzer._add_diagnostic(
            Diagnostic(
                file_path=file_path,
                line_number=idx + 1,
                line_content=stripped,
                code="RPY505",
                message=(
                    f"Audio channel '{channel}' is not a built-in channel (music, sound, voice, audio) "
                    "and has not been registered via 'renpy.music.register_channel()' or defined via "
                    "'define audio.<channel>'. Causes runtime Exception."
                ),
                severity="WARNING",
                col=start_c,
                end_col=end_c,
            ),
            noqa_map,
        )

    def _check_voice_loop(
        self,
        *,
        channel: str,
        rest: str,
        raw_line: str,
        file_path: str,
        idx: int,
        stripped: str,
        noqa_map: dict,
    ) -> None:
        """RPY505: Warn about `loop` on the `voice` channel (causes audio glitches)."""
        # Mask string literals before checking for 'loop' keyword — a
        # filename like "my loop song.ogg" contains 'loop' as a word but
        # it's inside a string literal, not a loop keyword (P2-16 fix).
        clean_rest = strip_string_literals(rest)
        if channel != "voice" or not re.search(r"\bloop\b", clean_rest, re.IGNORECASE):
            return
        start_c, end_c = self.analyzer._get_utf16_range(raw_line, "loop")
        self.analyzer._add_diagnostic(
            Diagnostic(
                file_path=file_path,
                line_number=idx + 1,
                line_content=stripped,
                code="RPY505",
                message=(
                    "Using 'loop' on the 'voice' audio channel. Voice playback is cut off "
                    "on dialogue advance; looping voice causes audio glitches."
                ),
                severity="WARNING",
                col=start_c,
                end_col=end_c,
            ),
            noqa_map,
        )

    def _check_audio_file_targets(
        self,
        *,
        channel: str,
        rest: str,
        m_audio,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        noqa_map: dict,
    ) -> None:
        """RPY501: Verify audio files exist (with playlist + define audio alias support)."""
        # No file specified → check define audio.<channel> map.
        if not rest:
            self._check_audio_no_file(
                channel=channel,
                raw_channel=m_audio.group(2),
                file_path=file_path,
                idx=idx,
                raw_line=raw_line,
                stripped=stripped,
                noqa_map=noqa_map,
            )
            return

        # Parse audio targets from rest (handles both playlists and single files).
        audio_targets = _parse_audio_targets(rest)
        for raw_audio_target in audio_targets:
            self._validate_one_audio_target(
                raw_audio_target=raw_audio_target,
                file_path=file_path,
                idx=idx,
                raw_line=raw_line,
                stripped=stripped,
                noqa_map=noqa_map,
            )

    def _check_audio_no_file(
        self,
        *,
        channel: str,
        raw_channel: str,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        noqa_map: dict,
    ) -> None:
        """RPY501: play/queue without a file — look it up in define audio.<channel>."""
        defined_file = next(
            (f for k, f in self.analyzer.defined_audio_map.items() if k.lower() == channel),
            None,
        )
        if defined_file is not None:
            self.analyzer._mark_asset_used(defined_file)
            return
        if channel not in self.analyzer.registered_audio_channels:
            return  # channel already flagged by _validate_audio_channel
        start_c, end_c = self.analyzer._get_utf16_range(raw_line, raw_channel)
        self.analyzer._add_diagnostic(
            Diagnostic(
                file_path=file_path,
                line_number=idx + 1,
                line_content=stripped,
                code="RPY501",
                message=(
                    f"'{raw_channel}' without a file: the file is taken from "
                    f"'define audio.{raw_channel}', but no such definition was found. "
                    "Add 'define audio.<channel> = \"file.ogg\"' or specify the file explicitly."
                ),
                severity="ERROR",
                col=start_c,
                end_col=end_c,
            ),
            noqa_map,
        )

    def _validate_one_audio_target(
        self,
        *,
        raw_audio_target: str,
        file_path: str,
        idx: int,
        raw_line: str,
        stripped: str,
        noqa_map: dict,
    ) -> None:
        """RPY501: Check a single audio target (quoted path, identifier, or alias)."""
        audio_found = False
        if raw_audio_target.startswith(('"', "'")) and raw_audio_target.endswith(('"', "'")):
            audio_found = self._resolve_quoted_audio(raw_audio_target)
        else:
            audio_found = self._resolve_identifier_audio(raw_audio_target)

        if not audio_found and raw_audio_target not in ("fadein", "fadeout", "volume"):
            start_c, end_c = self.analyzer._get_utf16_range(raw_line, raw_audio_target)
            self.analyzer._add_diagnostic(
                Diagnostic(
                    file_path=file_path,
                    line_number=idx + 1,
                    line_content=stripped,
                    code="RPY501",
                    message=(
                        f"Audio asset '{raw_audio_target}' not found in project, "
                        "'audio/' directory, or RPA archives."
                    ),
                    col=start_c,
                    end_col=end_c,
                ),
                noqa_map,
            )

    def _resolve_quoted_audio(self, raw_audio_target: str) -> bool:
        """Resolve a quoted audio path (e.g. "music/bgm.ogg") against known assets."""
        clean_audio_path = raw_audio_target[1:-1].strip()
        clean_audio_path = re.sub(r"^<[^>]+>\s*", "", clean_audio_path)
        clean_audio_path = clean_audio_path.replace("\\", "/").lower()
        audio_file = os.path.basename(clean_audio_path)
        if (
            clean_audio_path in self.analyzer.known_assets
            or audio_file in self.analyzer.known_assets
        ):
            self.analyzer._mark_asset_used(clean_audio_path)
            self.analyzer._mark_asset_used(audio_file)
            return True
        return False

    def _resolve_identifier_audio(self, raw_audio_target: str) -> bool:
        """Resolve an identifier audio reference (e.g. `audio.bgm_calm` or bare name)."""
        identifier = raw_audio_target.removeprefix("audio.")
        if identifier in self.analyzer.defined_audio_map:
            self.analyzer._mark_asset_used(self.analyzer.defined_audio_map[identifier])
            return True
        if identifier in self.analyzer.audio_dir_files:
            self.analyzer._mark_asset_used(self.analyzer.audio_dir_files[identifier])
            return True
        if identifier in self.analyzer.known_assets:
            self.analyzer._mark_asset_used(identifier)
            return True
        return False

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
        """Dispatcher: checks show/scene and audio via _check_* methods.

        Phase 4 Step 1 (0.5.7): split from 351 lines into 2 methods + dispatcher.
        """
        stripped = clean_line.strip()

        # RPY502: show / scene + ATL + transitions
        self._check_show_scene(file_path, idx, raw_line, stripped, scope_stack, noqa_map)

        # RPY501/RPY505: play / queue / stop
        self._check_audio_statement(file_path, idx, raw_line, stripped, noqa_map)

        return raw_line, False
