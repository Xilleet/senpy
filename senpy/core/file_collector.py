"""FileCollector — file discovery, I/O, and symbol collection extracted from SenpyAnalyzer.

Manages:
  - .rpy file discovery (os.walk, IGNORED_DIRS, tl/ detection)
  - File reading (in-memory, stage1 cache, disk)
  - noqa comment parsing (# noqa: RPY001, RPY002)
  - noqa map building (line→codes)
  - Encoding error emission (RPY100)
  - Logical line joining (multi-line via backslash or unclosed brackets)
  - Per-file symbol collection (_collect_symbols and all _collect_*
    helpers — labels, screens, images, transforms, variables, defaults,
    defines, audio aliases, init python blocks, etc.)

The symbol collection logic was originally in SenpyAnalyzer and has
been fully migrated to FileCollector. SenpyAnalyzer now delegates to
FileCollector via thin pass-through wrappers (kept for back-compat
with external callers that still call analyzer._collect_symbols).
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from senpy.core.cache import compute_file_hash
from senpy.core.constants import (
    IGNORED_DIRS,
    MEDIA_EXTENSIONS,
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
)
from senpy.core.models import Diagnostic, FileScope
from senpy.core.paths import normalize_path
from senpy.core.progress import progress_print
from senpy.core.signature import parse_signature
from senpy.core.symbols import (
    ImageSymbol,
    LabelSymbol,
    ScreenSymbol,
    TransformSymbol,
    VariableSymbol,
)
from senpy.rules.python_ast import infer_expr_type
from senpy.text_utils import _get_logical_line, _strip_comment, dedent_python, strip_string_literals

if TYPE_CHECKING:
    pass

# Regex for extracting string literals from expressions (e.g. image definitions)
_RE_STRING_LITERAL = re.compile(r"""(["'])(?P<value>(?:\\.|(?!\1).)*)\1""")


def _extract_string_literal(expr: str) -> str | None:
    """Return the first single- or double-quoted string literal in *expr*."""
    if not expr:
        return None
    m = _RE_STRING_LITERAL.search(expr)
    if m is None:
        return None
    return m.group("value")


def discover_rpy_files(project_path: str) -> tuple[list[str], list[str]]:
    """Walk the project directory and return (main_rpy_files, tl_rpy_files).

    Separates files in game/tl/ directories (translation files) from
    main script files. Files are sorted for deterministic traversal order.
    """
    main_files: list[str] = []
    tl_files: list[str] = []
    for root, dirs, filenames in os.walk(project_path, followlinks=False):
        dirs[:] = sorted([d for d in dirs if d not in IGNORED_DIRS])
        rel_parts = os.path.relpath(root, project_path).replace("\\", "/").split("/")
        is_tl_dir = "tl" in rel_parts

        for f in sorted(filenames):
            if f.endswith((".rpy", "_ren.py")):
                full_p = os.path.join(root, f)
                if is_tl_dir:
                    tl_files.append(full_p)
                else:
                    main_files.append(full_p)
    return sorted(main_files), sorted(tl_files)


def parse_noqa(line: str) -> tuple[bool, set[str] | None]:
    """Parse a `# noqa` comment from a line.

    Returns (has_noqa, codes_or_None):
      - (False, None) if no noqa comment
      - (True, None) if bare `# noqa` (suppress all)
      - (True, {"RPY001", "RPY002"}) if `# noqa: RPY001, RPY002`
    """
    m = RE_NOQA.search(line)
    if not m:
        return False, None
    codes_str = m.group(1) or m.group(2)
    if codes_str:
        codes = {c.strip().upper() for c in codes_str.split(",") if c.strip()}
        return True, codes
    return True, None


def build_noqa_map(lines: list[str]) -> dict[int, set[str] | None]:
    """Pre-parse all `# noqa` comments in the file into a line→codes map."""
    noqa_map: dict[int, set[str] | None] = {}
    for line_no, raw_line in enumerate(lines, start=1):
        has_noqa, codes = parse_noqa(raw_line)
        if has_noqa:
            noqa_map[line_no] = codes
    return noqa_map


def emit_encoding_error(
    file_path: str, err: UnicodeDecodeError, diagnostics: list[Diagnostic]
) -> None:
    """Emit RPY100 diagnostic for a file that is not valid UTF-8.

    Previously the decode error was swallowed by `except: pass` — the linter
    silently skipped the file and reported "clean", although Ren'Py will crash
    when loading such a script.
    """
    diagnostics.append(
        Diagnostic(
            file_path=file_path,
            line_number=1,
            line_content="",
            code="RPY100",
            severity="ERROR",
            message=(
                f"File is not valid UTF-8 ({err.reason} at byte offset {err.start}). "
                "Ren'Py requires UTF-8 script files: the game will fail to load it. "
                "Re-save the file with UTF-8 encoding."
            ),
        )
    )


def read_file_lines(
    file_path: str,
    in_memory_files: dict[str, str],
    stage1_lines: dict[str, list[str]],
) -> list[str] | None:
    """Read file lines: in-memory first, then stage1 cache, then disk.

    Returns None if the file can't be read (encoding error, OS error).
    Pops from stage1_lines cache if found (single-use).
    """
    try:
        norm_path = normalize_path(file_path)
        if norm_path in in_memory_files:
            return in_memory_files[norm_path].splitlines(keepends=True)
        elif norm_path in stage1_lines:
            return stage1_lines.pop(norm_path)
        else:
            with open(file_path, encoding="utf-8", newline="") as f:
                return f.readlines()
    except (UnicodeDecodeError, OSError):
        return None


# =============================================================================
# FileCollector class — symbol collection from .rpy files
# =============================================================================


class FileCollector:
    """Collects symbols from .rpy files (labels, screens, variables, transforms, images).

    Extracted from SenpyAnalyzer. Takes an analyzer reference and delegates
    symbol storage to analyzer's SymbolTable (via properties).

    The collector methods access:
      - self.analyzer.variables, .labels, .screens, etc. (SymbolTable via properties)
      - self.analyzer.file_scopes (per-file scope storage)
      - self.analyzer._stage1_lines (file content cache)
      - self.analyzer.in_memory_files (virtual files for LSP)
      - self.analyzer.diagnostics (for RPY100 encoding errors)
      - self.analyzer.python_ast (for Python block collection)

    Internal calls (self._collect_default, self._collect_define, etc.) stay
    within FileCollector — they don't go through analyzer.
    """

    def __init__(self, analyzer):
        self.analyzer = analyzer

    def _collect_all_symbols(
        self, rpy_files: list[str], cached_files: dict, quiet: bool
    ) -> tuple[dict[str, str], dict[str, list]]:
        """[1/2] Collect symbols from all .rpy files (Tier 1 cache: restore unchanged FileScope).

        Returns (file_hashes, stage1_diags_map).
        """
        total_files = len(rpy_files)
        file_hashes: dict[str, str] = {}
        stage1_diags_map: dict[str, list] = {}

        for i, file_path in enumerate(rpy_files, 1):
            fname = os.path.basename(file_path)
            norm_path = normalize_path(file_path)
            mtime = os.path.getmtime(file_path) if os.path.exists(file_path) else 0.0
            size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

            if not quiet:
                msg = f"\r[1/2] Сбор символов: {i}/{total_files} ({fname[:25]})"
                progress_print(msg)

            is_tier1_hit = False
            if (
                norm_path in cached_files
                and cached_files[norm_path].mtime == mtime
                and cached_files[norm_path].size == size
                and norm_path not in self.analyzer.in_memory_files
            ):
                cached_entry = cached_files[norm_path]
                f_hash = compute_file_hash(file_path)
                file_hashes[norm_path] = f_hash
                if cached_entry.content_hash and f_hash == cached_entry.content_hash:
                    self.analyzer.file_scopes[norm_path] = cached_entry.scope
                    is_tier1_hit = True
                    self.analyzer.diagnostics.extend(
                        getattr(cached_entry, "collect_diagnostics", ()) or ()
                    )

            if not is_tier1_hit:
                f_hash = file_hashes.get(norm_path) or compute_file_hash(file_path)
                file_hashes[norm_path] = f_hash
                diag_start = len(self.analyzer.diagnostics)
                self._collect_symbols(file_path)
                stage1_diags_map[norm_path] = list(self.analyzer.diagnostics[diag_start:])

        if not quiet:
            print()

        return file_hashes, stage1_diags_map

    def _collect_default(
        self,
        m_def,
        clean: str,
        line: str,
        file_path: str,
        idx: int,
        scope: FileScope,
    ) -> None:
        """Handle `default var = expr` — RPY105, VariableSymbol."""
        var = m_def.group(1)
        if "." in clean.split("=")[0]:
            return
        val_str = m_def.group(2)
        scope.user_symbols.add(var)
        scope.declared_symbols.add(var)
        self.analyzer.user_symbols.add(var)
        self.analyzer.declared_symbols.add(var)

        prev_var = self.analyzer.variables.get(var)
        if prev_var and prev_var.is_constant and not prev_var.is_character:
            prev_file = os.path.basename(prev_var.file_path)
            prev_line = prev_var.line_number
            start_c, end_c = self.analyzer._get_utf16_range(line, var)
            self.analyzer.diagnostics.append(
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

        inferred_t = infer_expr_type(val_str, known_vars=self.analyzer.variables)
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
        self.analyzer.variables[var] = var_sym

    def _collect_define(
        self,
        m_define,
        clean: str,
        line: str,
        file_path: str,
        idx: int,
        scope: FileScope,
    ) -> None:
        """Handle `define var = expr` — RPY105, VariableSymbol."""
        var = m_define.group(1)
        if "." in clean.split("=")[0]:
            return
        val_str = m_define.group(2)
        scope.user_symbols.add(var)
        scope.declared_symbols.add(var)
        self.analyzer.user_symbols.add(var)
        self.analyzer.declared_symbols.add(var)

        prev_var = self.analyzer.variables.get(var)
        if prev_var and not prev_var.is_constant:
            prev_file = os.path.basename(prev_var.file_path)
            prev_line = prev_var.line_number
            start_c, end_c = self.analyzer._get_utf16_range(line, var)
            self.analyzer.diagnostics.append(
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

        inferred_t = infer_expr_type(val_str, known_vars=self.analyzer.variables)
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
        self.analyzer.variables[var] = var_sym

    def _collect_define_audio(self, m_audio_def, scope: FileScope) -> None:
        """Handle `define audio.NAME = "file.ogg"`."""
        alias = m_audio_def.group(1)
        target_file = m_audio_def.group(2).replace("\\", "/").lower()
        scope.defined_audio_map[alias] = target_file
        scope.declared_symbols.add(alias)
        scope.declared_symbols.add(f"audio.{alias}")
        self.analyzer.defined_audio_map[alias] = target_file
        self.analyzer.declared_symbols.add(alias)
        self.analyzer.declared_symbols.add(f"audio.{alias}")
        # Register alias → disk path for audio hover. The alias
        # resolves to the *file* named in target_file (relative to game/);
        # we look it up via media_disk_files. Done at parse time so hover
        # never re-reads source files (renpy-magic re-reads per hover —
        # we avoid that anti-pattern).
        self.analyzer.assets.register_audio_alias(alias, target_file)

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
        """Handle `screen name(...)` and `transform name(...)`.

        Returns the current screen name (or None) for context.
        """
        if m_screen_def:
            s_name = m_screen_def.group(2)
            s_params = m_screen_def.group(3)
            sig = parse_signature(s_params)
            scr_sym = ScreenSymbol(
                name=s_name, file_path=file_path, line_number=idx + 1, signature=sig
            )
            scope.screens[s_name] = scr_sym
            self.analyzer.screens[s_name] = scr_sym

        new_screen = None

        # Screen context (screen blocks are always top-level)
        if len(line) - len(line.lstrip(" ")) == 0:
            new_screen = m_screen_def.group(2) if m_screen_def else None

        if m_trans:
            trans_name = m_trans.group(1)
            trans_params = m_trans.group(2)  # None if no params declared
            trans_sig = parse_signature(trans_params) if trans_params else None
            trans_sym = TransformSymbol(
                name=trans_name,
                file_path=file_path,
                line_number=idx + 1,
                code_line=clean,
                signature=trans_sig,
            )
            scope.transforms[trans_name] = trans_sym
            self.analyzer.transforms[trans_name] = trans_sym
            scope.user_symbols.add(trans_name)
            scope.declared_symbols.add(trans_name)
            self.analyzer.user_symbols.add(trans_name)
            self.analyzer.declared_symbols.add(trans_name)

        return new_screen

    def _collect_label(
        self,
        m_label,
        clean: str,
        file_path: str,
        idx: int,
        scope: FileScope,
        current_global_label: str | None,
        lines: list[str] | None = None,
        previous_label: str | None = None,
    ) -> tuple[str, str, str | None]:
        """Handle `label name(params):` — RPY307, LabelSymbol.

        Returns (label_name, current_global_label, current_label).

        If ``lines`` and ``previous_label`` are provided, also populates
        ``fall_through_to`` on the previous label in the same file when
        the line just before this new label is not a terminator
        (``return``, ``jump``, ``call``, ``renpy.quit``,
        ``renpy.full_restart``) and does not end with ``:``. This models
        the implicit fall-through edge used by RPY309 reachability.
        """
        raw_name = m_label.group(1)
        if raw_name.startswith("."):
            label_name = f"{current_global_label}{raw_name}" if current_global_label else raw_name
        else:
            label_name = raw_name
            current_global_label = label_name
        if label_name in self.analyzer.labels and not label_name.startswith("_"):
            prev_file = self.analyzer.labels[label_name].file_path
            prev_line = self.analyzer.labels[label_name].line_number
            self.analyzer.diagnostics.append(
                Diagnostic(
                    file_path=file_path,
                    line_number=idx + 1,
                    line_content=clean,
                    code="RPY307",
                    message=f"Duplicate label '{label_name}'. Previously declared at {os.path.basename(prev_file)}:{prev_line}. Causes fatal ScriptError.",
                    severity="ERROR",
                )
            )
        sig = parse_signature(m_label.group(2))
        lbl_sym = LabelSymbol(
            name=label_name,
            file_path=file_path,
            line_number=idx + 1,
            code_line=clean,
            signature=sig,
        )
        # Always record in both scope.labels and analyzer.labels — even for
        # duplicate declarations — so that differential purge can correctly
        # detect that the symbol is still declared by a surviving file when
        # one of the declarations is removed.
        scope.labels[label_name] = lbl_sym
        self.analyzer.labels[label_name] = lbl_sym

        # Populate fall_through_to on the previous label in the same file.
        #
        # Algorithm:
        #   1. Walk back from idx-1 to find the last non-blank, non-comment
        #      line. That's the candidate "last statement of previous
        #      label's body".
        #   2. Walk back further from that line to the previous label's
        #      declaration line. If any indent-0 statement appears in
        #      between that is NOT a label declaration, the previous
        #      label's body ended earlier (e.g. with a `return`) and a
        #      new top-level construct (screen/style/transform/etc.)
        #      was declared — no fall-through to this new label.
        #   3. If no intervening top-level construct exists AND the last
        #      non-blank line is not a terminator (return/jump/call/
        #      renpy.quit/renpy.full_restart) and does not end with ':',
        #      then the previous label falls through to this new label.
        #
        # The intervening-construct check is critical: a `screen` block
        # between two labels is NOT a fall-through path — labels and
        # screens are separate top-level constructs in Ren'Py. Without
        # this check, `label A: ... return` followed by `screen X(): ...`
        # followed by `label B:` would incorrectly set A.fall_through_to
        # = B (the last non-blank line before B is the screen body, which
        # is not a terminator), making B appear reachable from A.
        if lines is not None and previous_label is not None and previous_label in scope.labels:
            from senpy.text_utils import _strip_comment

            prev_label_line = scope.labels[previous_label].line_number - 1  # 0-indexed

            # Step 1: walk back to find last non-blank line.
            last_nb_idx = idx - 1
            while last_nb_idx > prev_label_line and not lines[last_nb_idx].strip():
                last_nb_idx -= 1
            if last_nb_idx <= prev_label_line:
                # No body lines between previous label and this one —
                # previous label has empty body, no fall-through.
                pass
            else:
                # Step 2: walk back from last_nb_idx-1 to prev_label_line,
                # checking for any intervening indent-0 construct that's
                # not a label.
                has_intervening_top_level = False
                walk_idx = last_nb_idx - 1
                while walk_idx > prev_label_line:
                    line_text = lines[walk_idx]
                    if not line_text.strip():
                        walk_idx -= 1
                        continue
                    stripped_line = line_text.lstrip(" ")
                    indent = len(line_text) - len(stripped_line)
                    if indent == 0:
                        clean_at_zero = _strip_comment(stripped_line).strip()
                        if clean_at_zero and clean_at_zero.startswith(
                            (
                                "label ",
                                "screen ",
                                "style ",
                                "transform ",
                                "init ",
                                "image ",
                                "layeredimage ",
                                "define ",
                                "default ",
                            )
                        ):
                            # A top-level construct declaration between
                            # the previous label and this one breaks
                            # the fall-through chain.
                            has_intervening_top_level = True
                            break
                    walk_idx -= 1

                if not has_intervening_top_level:
                    # Step 3: check the last non-blank line for terminator.
                    prev_clean = _strip_comment(lines[last_nb_idx]).strip()
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
                                "pass",
                            )
                        )
                        and not prev_clean.endswith(":")
                    ):
                        prev_sym = scope.labels[previous_label]
                        prev_sym.fall_through_to = label_name
                        if previous_label in self.analyzer.labels:
                            self.analyzer.labels[previous_label].fall_through_to = label_name

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
        """Handle jump/call/return inside label + screen edges."""
        if current_label:
            if RE_RETURN.match(clean):
                if current_label in scope.labels:
                    scope.labels[current_label].has_return = True
                if current_label in self.analyzer.labels:
                    self.analyzer.labels[current_label].has_return = True

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
                if current_label in self.analyzer.labels:
                    self.analyzer.labels[current_label].outgoing_jumps.add(target_j)
                scope.referenced_labels.add(target_j)
                self.analyzer.referenced_labels.add(target_j)

                self.analyzer.jump_sources.setdefault(target_j, []).append((file_path, idx + 1))
                scope.jump_sources.setdefault(target_j, []).append((file_path, idx + 1))

        # Edges from screens (Jump/Call actions) and screen usage
        if current_screen:
            for m_act in RE_SCREEN_JUMP_ACTION.finditer(clean):
                scope.screen_action_jumps.setdefault(current_screen, set()).add(m_act.group(1))
                self.analyzer.screen_action_jumps.setdefault(current_screen, set()).add(
                    m_act.group(1)
                )

        for m_usage in RE_SCREEN_CALL.finditer(clean):
            scope.used_screens.add(m_usage.group(1))
            self.analyzer.used_screens.add(m_usage.group(1))
            usage_src = current_screen or current_label
            if usage_src:
                scope.screen_uses.setdefault(usage_src, set()).add(m_usage.group(1))
                self.analyzer.screen_uses.setdefault(usage_src, set()).add(m_usage.group(1))

        for m_show in RE_SCREEN_SHOW_ACTION.finditer(clean):
            scope.used_screens.add(m_show.group(1))
            self.analyzer.used_screens.add(m_show.group(1))

    def _collect_images(
        self,
        clean: str,
        clean_line: str,
        file_path: str,
        idx: int,
        lines: list[str],
        scope: FileScope,
    ) -> tuple[bool, int]:
        """Handle layeredimage and image declarations — RPY504.

        Returns (was_handled, new_idx).
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
            self.analyzer.images[limg_tag] = img_sym

            return True, next_block_idx

        m_img = RE_IMAGE_DEF.match(clean)
        if m_img:
            img_name = m_img.group(1).strip()
            img_body = m_img.group(2).strip()

            if img_name in self.analyzer.images:
                prev_file = self.analyzer.images[img_name].file_path
                prev_line = self.analyzer.images[img_name].line_number
                prev_body = self.analyzer.images[img_name].body
                is_exact_dup = img_body == prev_body
                msg = (
                    f"Duplicate image declaration '{img_name}'. Identical to declaration at {os.path.basename(prev_file)}:{prev_line}."
                    if is_exact_dup
                    else f"Image '{img_name}' is redefined (override). Previously declared at {os.path.basename(prev_file)}:{prev_line}."
                )
                self.analyzer.diagnostics.append(
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
                image_path=_extract_string_literal(img_body),
            )
            scope.images[img_name] = img_sym
            self.analyzer.images[img_name] = img_sym
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
        """Handle channels, dynamic jumps, quoted strings, init python.

        Returns (was_init_python, new_idx).
        """
        m_chan = re.search(r'renpy\.music\.register_channel\s*\(\s*["\']([^\W\d]\w*)["\']', clean)
        if m_chan:
            chan_name = m_chan.group(1).lower()
            scope.registered_audio_channels.add(chan_name)
            self.analyzer.registered_audio_channels.add(chan_name)

        # Mask string-literal contents before substring/regex matching so
        # that dialogue text and Python string constants cannot trigger
        # false positives (see `strip_string_literals` docstring).
        # Columns of code outside literals are preserved, so UTF-16 ranges
        # computed downstream remain valid for tokens that live outside
        # string literals.
        clean_for_check = strip_string_literals(clean)

        if (
            "renpy.call(" in clean_for_check
            or "renpy.jump(" in clean_for_check
            or "call expression" in clean_for_check
            or "jump expression" in clean_for_check
        ):
            self.analyzer.has_dynamic_jumps = True
            # Persist per-file flag so Tier 1 cache hit can re-aggregate
            # `has_dynamic_jumps` without re-running `_collect_misc`.
            scope.has_dynamic_jumps = True

        if '"' in clean_for_check or "'" in clean_for_check:
            for str_match in RE_QUOTED_IDENTIFIER.finditer(clean_for_check):
                candidate = str_match.group(1)
                if candidate.isidentifier():
                    scope.referenced_labels.add(candidate)
                    self.analyzer.referenced_labels.add(candidate)

        m_init = RE_INIT_PYTHON_START.match(line)
        if m_init:
            indent = len(m_init.group(1))
            next_idx, block_lines = self._consume_block(lines, idx + 1, indent)
            self._collect_from_python_block(block_lines, scope, file_path, idx + 2)
            return True, next_idx

        return False, idx

    def _collect_symbols(self, file_path: str):
        """Collects symbols from a .rpy file (default/define/screen/label/image/...).

        Phase 3 Step 5 (0.5.6): split from 378 lines into 7 methods + dispatcher.
        """
        try:
            norm_path = normalize_path(file_path)
            scope = FileScope()

            if norm_path in self.analyzer.in_memory_files:
                lines = self.analyzer.in_memory_files[norm_path].splitlines(keepends=True)
            else:
                with open(file_path, encoding="utf-8", newline="") as f:
                    lines = f.readlines()
                self.analyzer._stage1_lines[norm_path] = lines

            if file_path.endswith("_ren.py"):
                self._collect_from_python_block(lines, scope, file_path, 1)
                self.analyzer.file_scopes[norm_path] = scope
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

                # Screen context (screen blocks are always top-level)
                # Important: current_screen is reset to None for ANY top-level line,
                # not only screen. This is needed so `label start:` resets the screen context.
                if len(line) - len(line.lstrip(" ")) == 0:
                    current_screen = m_screen_def.group(2) if m_screen_def else None

                # Scan every line for media-asset string literals. This
                # catches references inside `style` blocks (e.g.
                # `foreground "gui/button/check_[prefix_]foreground.png"`)
                # which are not handled by the `$`/`python:`-only
                # `_scan_python_assets` calls in state.py. Without this,
                # RPY503 fires false positives on assets referenced via
                # the standard Ren'Py GUI auto-discovery pattern.
                # The fast-path (`if '"' in line or "'" in line`) makes
                # this cheap for the common case of label/jump/return
                # lines that have no quotes.
                self._scan_python_assets(line)

                # --- label ---
                m_label = RE_LABEL.match(clean)
                if m_label:
                    # Capture the previous label in this file before
                    # _collect_label reassigns current_label to the new one.
                    previous_label_in_file = current_label
                    label_name, current_global_label, current_label = self._collect_label(
                        m_label,
                        clean,
                        file_path,
                        idx,
                        scope,
                        current_global_label,
                        lines=lines,
                        previous_label=previous_label_in_file,
                    )
                    idx = next_idx
                    continue

                # --- label body (jumps, returns, screen edges) ---
                self._collect_label_body(
                    clean,
                    file_path,
                    idx,
                    scope,
                    current_label,
                    current_global_label,
                    current_screen,
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

            self.analyzer.file_scopes[norm_path] = scope

        except UnicodeDecodeError as e:
            self.analyzer._emit_encoding_error(file_path, e)
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
            self.analyzer.registered_audio_channels.add(chan)

        names, refs = self.analyzer.python_ast.collect_from_python_block(code_lines)
        for name, line_offset in names.items():
            real_line = start_line + line_offset - 1
            if scope is not None:
                scope.user_symbols.add(name)
                scope.declared_symbols.add(name)
            self.analyzer.user_symbols.add(name)
            self.analyzer.declared_symbols.add(name)
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
                self.analyzer.variables[name] = var_sym

        if scope is not None:
            scope.referenced_labels.update(refs)
        self.analyzer.referenced_labels.update(refs)

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

    def _scan_python_assets(self, code_lines: list[str] | str) -> None:
        """Targeted search for media files in Python blocks (protection against false RPY503 without overhead).

        Also expands the Ren'Py ``[prefix_]`` substitution token: when a
        string literal like ``"gui/button/check_[prefix_]foreground.png"``
        is found, the standard prefix list ("", "idle_", "hover_",
        "selected_", "selected_hover_", "selected_idle_", "insensitive_",
        "selected_insensitive_") is substituted and each expansion is
        marked as used. Without this, files like ``check_foreground.png``
        (the empty-prefix case) and ``check_idle_foreground.png`` would
        be reported as unused despite the style block clearly referencing
        them via the substitution pattern.
        """
        if isinstance(code_lines, str):
            code_lines = [code_lines]
        for line in code_lines:
            if '"' in line or "'" in line:  # Fast-path: ultra-fast pre-filter
                for match in RE_STRING_MATCH.finditer(line):
                    inner = match.group(0).strip("\"'")
                    val_clean = inner.replace("\\", "/").lower().strip()
                    if any(val_clean.endswith(ext) for ext in MEDIA_EXTENSIONS):
                        self._mark_asset_used_with_prefix_expansion(val_clean)

    def _mark_asset_used_with_prefix_expansion(self, val_clean: str) -> None:
        """Mark ``val_clean`` as used, expanding ``[prefix_]`` if present.

        Ren'Py's standard state-prefix substitution expands ``[prefix_]``
        to one of: "", "idle_", "hover_", "selected_", "selected_hover_",
        "selected_idle_", "insensitive_", "selected_insensitive_". Each
        expansion is registered as a used asset key.
        """
        if "[prefix_]" not in val_clean:
            self.analyzer._mark_asset_used(val_clean)
            self.analyzer._mark_asset_used(os.path.basename(val_clean))
            return
        for prefix in (
            "",
            "idle_",
            "hover_",
            "selected_",
            "selected_hover_",
            "selected_idle_",
            "insensitive_",
            "selected_insensitive_",
        ):
            expanded = val_clean.replace("[prefix_]", prefix)
            self.analyzer._mark_asset_used(expanded)
            self.analyzer._mark_asset_used(os.path.basename(expanded))

    def _handle_init_python_block(
        self, lines: list[str], idx: int, file_path: str, noqa_map: dict
    ) -> int | None:
        """Detect `init python:` block and run AST checks on it.

        Returns `next_idx` (the index after the block) if an init block was
        found and processed, or `None` if the current line is not an init
        python block start.
        """
        # Use the raw_line from lines[idx] — format_checker may have modified it.
        raw_line = lines[idx]
        m_init = RE_INIT_PYTHON_START.match(raw_line)
        if not m_init:
            return None

        indent = len(m_init.group(1))
        # Extract the init priority. Ren'Py default is 0 (e.g.
        # ``init python:``). ``init 998 python:`` → priority 998.
        # ``init -1 python:`` → priority -1. The priority determines
        # load order: lower number runs first; same priority falls back
        # to alphabetical by filename. RPY109 uses this to avoid firing
        # when a higher-priority block references a variable defined at
        # a lower-priority block in an alphabetically later file.
        priority_str = m_init.group(2)
        init_priority = int(priority_str) if priority_str else 0

        next_idx, block_lines = self._consume_block(lines, idx + 1, indent)
        if block_lines:
            self.analyzer._scan_python_assets(block_lines)
            code = dedent_python("".join(block_lines))
            self.analyzer.python_ast.check_init_dependency(
                code, file_path, idx + 2, noqa_map, lines, init_priority=init_priority
            )
            self.analyzer.python_ast.check_python_ast(code, file_path, idx + 2, noqa_map, lines)
            # Statically extract image names registered via
            # `renpy.image(NAME, ...)` calls. Without this, references
            # to dynamically-registered images (e.g. `scene bg_room night`
            # where `bg_room night` was registered in an init python
            # loop) fire false RPY502. The static evaluator handles
            # string literals, list-literal loop iterables, and simple
            # string concatenation with loop variables — anything more
            # complex remains a known limitation (users `# noqa`).
            self._collect_dynamic_renpy_images(code, file_path, idx + 2)
        return next_idx

    def _collect_dynamic_renpy_images(self, code: str, file_path: str, start_line: int) -> None:
        """Walk the AST of an ``init python:`` block and register image
        names declared via ``renpy.image(NAME, ...)`` calls.

        Handles:
          - Plain string literals: ``renpy.image("bg_static", ...)``
          - Loop variables from list-literal iterables:
            ``for x in ["a", "b"]: renpy.image(x, ...)``
          - String concatenation with loop variables:
            ``renpy.image(x + " night", ...)``

        Anything more complex (function calls as name, f-strings with
        non-literal interpolation, list comprehensions as iterable,
        ``os.listdir()`` iterables, etc.) is left as a known limitation —
        users can ``# noqa: RPY502`` for those.
        """
        import ast as _ast

        try:
            tree = _ast.parse(code)
        except SyntaxError:
            return

        # Walk the tree, tracking loop variable bindings from enclosing
        # `for` statements whose iterable is a list/tuple literal of
        # string constants.
        def _eval_name_expr(node, loop_vars):
            """Evaluate an AST expression to a list of possible string values.

            Returns ``None`` if the expression cannot be statically
            evaluated. Returns a list of strings (one or more) if it can.
            """
            # String constant → single value.
            if isinstance(node, _ast.Constant) and isinstance(node.value, str):
                return [node.value]
            # Name → look up in loop_vars. Each variable may have
            # multiple possible values (the iterable's elements).
            if isinstance(node, _ast.Name) and node.id in loop_vars:
                vals = loop_vars[node.id]
                return list(vals) if vals is not None else None
            # BinOp(Add, X, Y) → concatenate each X value with each Y value.
            if (
                isinstance(node, _ast.BinOp)
                and isinstance(node.op, _ast.Add)
                and node.left is not None
                and node.right is not None
            ):
                left_vals = _eval_name_expr(node.left, loop_vars)
                right_vals = _eval_name_expr(node.right, loop_vars)
                if left_vals is None or right_vals is None:
                    return None
                return [lv + rv for lv in left_vals for rv in right_vals]
            # JoinedStr (f-string) — only handle the case where every
            # FormattedValue is a statically-evaluable Name and the
            # literal parts are constants. This is rare in practice;
            # most dynamic image registration uses BinOp(Add).
            if isinstance(node, _ast.JoinedStr):
                # Collect possible values per part, then cross-product.
                parts = []
                for v in node.values:
                    if isinstance(v, _ast.Constant) and isinstance(v.value, str):
                        parts.append([v.value])
                    elif isinstance(v, _ast.FormattedValue):
                        vals = _eval_name_expr(v.value, loop_vars)
                        if vals is None:
                            return None
                        parts.append(vals)
                    else:
                        return None
                # Cross-product concatenation.
                results = [""]
                for part_vals in parts:
                    results = [r + pv for r in results for pv in part_vals]
                return results
            return None

        def _visit(nodes, loop_vars):
            for node in nodes:
                if isinstance(node, _ast.For):
                    # Track loop variable bindings if iterable is a
                    # list/tuple literal of string constants.
                    new_loop_vars = dict(loop_vars)
                    iter_node = node.iter
                    if isinstance(iter_node, (_ast.List, _ast.Tuple)):
                        iter_vals = []
                        for elt in iter_node.elts:
                            if isinstance(elt, _ast.Constant) and isinstance(elt.value, str):
                                iter_vals.append(elt.value)
                            else:
                                iter_vals = None
                                break
                        if iter_vals is not None:
                            if isinstance(node.target, _ast.Name):
                                new_loop_vars[node.target.id] = iter_vals
                            elif isinstance(node.target, (_ast.Tuple, _ast.List)):
                                # Tuple unpacking in for — too complex
                                # for this simple evaluator. Skip.
                                new_loop_vars = dict(loop_vars)
                    _visit(node.body, new_loop_vars)
                elif isinstance(node, _ast.If):
                    _visit(node.body, loop_vars)
                    _visit(node.orelse, loop_vars)
                elif isinstance(node, _ast.While):
                    _visit(node.body, loop_vars)
                elif isinstance(node, _ast.Try):
                    _visit(node.body, loop_vars)
                    for handler in node.handlers:
                        _visit(handler.body, loop_vars)
                    _visit(node.finalbody, loop_vars)
                elif isinstance(node, _ast.With):
                    _visit(node.body, loop_vars)
                elif isinstance(node, _ast.Expr) and isinstance(node.value, _ast.Call):
                    self._maybe_register_renpy_image(
                        node.value, loop_vars, _eval_name_expr, file_path, start_line
                    )

        _visit(tree.body, {})

    def _maybe_register_renpy_image(
        self, call_node, loop_vars, eval_fn, file_path: str, start_line: int
    ) -> None:
        """If ``call_node`` is a ``renpy.image(NAME, ...)`` call, register NAME."""
        import ast as _ast

        func = call_node.func
        # Match renpy.image(...) — Attribute(Name('renpy'), attr='image').
        if not (
            isinstance(func, _ast.Attribute)
            and isinstance(func.value, _ast.Name)
            and func.value.id == "renpy"
            and func.attr == "image"
        ):
            return
        if not call_node.args:
            return
        name_vals = eval_fn(call_node.args[0], loop_vars)
        if not name_vals:
            return
        for name_val in name_vals:
            # Register as a known image. Use a synthetic ImageSymbol so
            # downstream checks (RPY502, hover, completion) see it.
            # The `body` field is left empty — we don't track layered
            # attributes from dynamic registration.
            img_sym = ImageSymbol(
                name=name_val,
                file_path=file_path,
                line_number=start_line,
                body="",
            )
            self.analyzer.images[name_val] = img_sym
