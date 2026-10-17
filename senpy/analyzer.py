from __future__ import annotations

import ast
import builtins
import contextlib
import difflib
import os
import pickle
import re
import textwrap
import zlib
from dataclasses import dataclass


@dataclass
class Diagnostic:
    file_path: str
    line_number: int
    line_content: str
    code: str
    message: str
    severity: str = "ERROR"  # "ERROR", "WARNING", "INFO"
    col: int = 0
    end_col: int = 0


@dataclass
class AnalysisResult:
    diagnostics: list[Diagnostic]
    file_count: int
    total_lines: int
    fixed_count: int = 0
    fixable_count: int = 0


# Градация уверенности правил (Severity levels)
RULE_SEVERITY = {
    "RPY101": "ERROR",    # Опечатка в [var] -> падение с KeyError
    "RPY102": "ERROR",    # += до default -> NameError при входе
    "RPY103": "ERROR",    # if var: без объявления -> NameError при входе
    "RPY104": "WARNING",  # $ var = 1 без default -> риск для сохранений/патчей
    "RPY201": "WARNING",  # Мутация внутри screen -> ломает откат и нагружает UI
    "RPY202": "WARNING",  # Переменная в screen без default -> риск падения в меню
    "RPY301": "ERROR",    # Незакрытый тег диалога -> ломает стили/шрифт
    "RPY302": "ERROR",    # Прыжок на несуществующую метку -> ScriptError
    "RPY303": "INFO",     # Мертвая метка (эвристика, может быть динамический роутер)
    "RPY304": "ERROR",    # Невалидный hex-цвет -> падение движка рендера
    "RPY401": "WARNING",  # Развилка menu: переменная объявлена не везде
    "RPY501": "ERROR",    # Отсутствует аудиофайл
}

BUILTIN_SYMBOLS = {
    "config", "persistent", "renpy", "gui", "main_menu",
    "_return", "_in_replay", "_window_during_functions",
    "name", "player", "theme", "style", "who", "what",
    *dir(builtins),
}

SYSTEM_LABELS = {
    "start", "splashscreen", "after_load", "main_menu",
    "before_main_menu", "quit", "after_warp", "hide_windows"
}

SELF_CLOSING_TAGS = {"w", "p", "nw", "fast", "space", "vspace"}
PAIR_TAGS = {"b", "i", "u", "s", "plain", "color", "size", "font", "alpha", "cps", "k", "a"}

NAMED_COLORS = {
    "black", "white", "red", "green", "blue", "yellow", "cyan", "magenta",
    "gray", "grey", "orange", "purple", "brown", "pink", "lime", "navy"
}

RE_DEFAULT = re.compile(r"^\s*default\s+([a-zA-Z_][a-zA-Z0-9_]*)")
RE_DEFINE = re.compile(r"^\s*define\s+([a-zA-Z_][a-zA-Z0-9_]*)")
RE_LABEL = re.compile(r"^\s*label\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:\(.*\))?\s*:")
RE_JUMP_CALL = re.compile(r"^\s*(jump|call)\s+(?!screen\b|expression\b)([a-zA-Z_][a-zA-Z0-9_]*)")
RE_PLAY_AUDIO = re.compile(r"^\s*play\s+(?:music|sound|voice|audio)\s+[\"']([^\"']+)[\"']", re.IGNORECASE)
RE_INTERPOLATION = re.compile(r"\[([a-zA-Z_][a-zA-Z0-9_]*)(?:![a-zA-Z]+)?\]")
RE_CONDITION = re.compile(r"^\s*(?:if|elif)\s+(.+):$")
RE_PYTHON_BLOCK_START = re.compile(r"^(\s*)python(?:\s+early)?\s*:$")
RE_INIT_PYTHON_START = re.compile(r"^(\s*)init(?:\s+-?\d+)?\s+python(?:\s+early)?\s*:$")
RE_SCREEN_START = re.compile(r"^(\s*)screen\s+([a-zA-Z_][a-zA-Z0-9_]*)(?:\((.*?)\))?\s*:")
RE_FOR_LOOP = re.compile(r"^\s*for\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+in\s+")
RE_MENU_START = re.compile(r"^(\s*)menu(?:\s+[a-zA-Z0-9_]+)?\s*:")
RE_MENU_CHOICE = re.compile(r"^(\s*)(\"[^\"]+\"|\'[^\']+\')(?:\s+if\s+.*)?\s*:")
RE_TAG = re.compile(r"\{(/)?([a-zA-Z_]+)(?:=([^}]*))?\}")
RE_STRING_MATCH = re.compile(r'("([^"\\]*(?:\\.[^"\\]*)*)")|(\'([^\'\\]*(?:\\.[^\'\\]*)*)\')')

RE_NOQA = re.compile(
    r"#\s*(?:noqa|senpy:\s*ignore)(?:\[([a-zA-Z0-9_,\s]+)\]|:\s*([a-zA-Z0-9_,\s]+))?",
    re.IGNORECASE
)


class SenpyAnalyzer:
    def __init__(self, project_path: str, extra_files: list[str] | None = None, fix: bool = False, in_memory_files: dict[str, str] | None = None):
        self.project_path = project_path
        self.extra_files = extra_files or []
        self.fix = fix
        self.in_memory_files =  in_memory_files or {}
        self.user_symbols: set[str] = set()
        self.declared_symbols: set[str] = set(BUILTIN_SYMBOLS)
        self.declared_labels: dict[str, tuple[str, int, str]] = {}
        self.referenced_labels: set[str] = set()
        self.known_assets: set[str] = set()
        self.diagnostics: list[Diagnostic] = []
        self.total_lines: int = 0
        self.fixed_count: int = 0
        self.fixable_count: int = 0

    @staticmethod
    def find_orphaned_rpyc(project_path: str) -> list[str]:
        orphans = []
        for root, _, filenames in os.walk(project_path):
            for f in filenames:
                if f.endswith(".rpyc"):
                    base_name = f[:-1]
                    rpy_path = os.path.join(root, base_name)
                    if not os.path.exists(rpy_path):
                        orphans.append(os.path.join(root, f))
        return orphans

    def run(self) -> AnalysisResult:
        self._index_assets()
        rpy_files = self._get_rpy_files() + self.extra_files
        
        for file_path in rpy_files:
            self._collect_symbols(file_path)

        for file_path in rpy_files:
            self._analyze_file(file_path)

        self._check_unreachable_labels()

        return AnalysisResult(
            diagnostics=self.diagnostics,
            file_count=len(rpy_files),
            total_lines=self.total_lines,
            fixed_count=self.fixed_count,
            fixable_count=self.fixable_count,
        )

    def _index_assets(self):
        for root, _, filenames in os.walk(self.project_path):
            for f in filenames:
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, self.project_path).replace("\\", "/").lower()
                self.known_assets.add(rel_path)
                self.known_assets.add(f.lower())

                if f.lower().endswith(".rpa"):
                    self._read_rpa_index(full_path)

    def _read_rpa_index(self, rpa_path: str):
        with (
            contextlib.suppress(OSError, zlib.error, pickle.UnpicklingError, ValueError),
            open(rpa_path, "rb") as f,
        ):
            header = f.read(40)
            if header.startswith((b"RPA-3.0 ", b"RPA-2.0 ")):
                offset = int(header[8:24], 16)
                f.seek(offset)
                data = zlib.decompress(f.read())
                index = pickle.loads(data)
                for filename in index:
                    clean_fn = filename.replace("\\", "/").lower()
                    self.known_assets.add(clean_fn)
                    self.known_assets.add(os.path.basename(clean_fn))

    def _get_rpy_files(self) -> list[str]:
        files: list[str] = []
        for root, _, filenames in os.walk(self.project_path):
            for f in filenames:
                if f.endswith(".rpy"):
                    files.append(os.path.join(root, f))
        return files

    def _collect_symbols(self, file_path: str):
        try:
            # Если файл прямо сейчас редактируется в VS Code — берем его из памяти!
            if file_path in self.in_memory_files:
                lines = self.in_memory_files[file_path].splitlines(keepends=True)
            else:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()

            idx = 0
            while idx < len(lines):
                line = lines[idx]
                clean = line.split("#")[0].strip()
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

                m_define = RE_DEFINE.match(clean)
                if m_define:
                    var = m_define.group(1)
                    self.user_symbols.add(var)
                    self.declared_symbols.add(var)
                    idx += 1
                    continue

                m_label = RE_LABEL.match(clean)
                if m_label:
                    label_name = m_label.group(1)
                    self.declared_labels[label_name] = (file_path, idx + 1, clean)
                    idx += 1
                    continue

                m_init = RE_INIT_PYTHON_START.match(line)
                if m_init:
                    indent = len(m_init.group(1))
                    idx, block_lines = self._consume_block(lines, idx + 1, indent)
                    self._collect_from_python_block(block_lines)
                    continue

                idx += 1
        except (UnicodeDecodeError, OSError):
            pass

    def _collect_from_python_block(self, code_lines: list[str]):
        code = textwrap.dedent("".join(code_lines))
        with contextlib.suppress(SyntaxError):
            tree = ast.parse(code)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    self.user_symbols.add(node.name)
                    self.declared_symbols.add(node.name)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            self.user_symbols.add(target.id)
                            self.declared_symbols.add(target.id)

    def _consume_block(self, lines: list[str], start_idx: int, header_indent: int) -> tuple[int, list[str]]:
        block = []
        idx = start_idx
        while idx < len(lines):
            line = lines[idx]
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                block.append(line)
                idx += 1
                continue

            current_indent = len(line) - len(line.lstrip(" "))
            if current_indent > header_indent:
                block.append(line)
                idx += 1
            else:
                break
        return idx, block

    @staticmethod
    def _get_utf16_range(line: str, sub: str | None = None) -> tuple[int, int]:
        """Считает точные координаты слова в стандарте UTF-16 для VS Code/LSP."""
        line_clean = line.rstrip("\r\n")
        if not sub:
            indent = len(line_clean) - len(line_clean.lstrip())
            start = len(line_clean[:indent].encode("utf-16-le")) // 2
            end = len(line_clean.encode("utf-16-le")) // 2
            return start, max(start + 1, end)

        idx = line_clean.find(sub)
        if idx == -1:
            indent = len(line_clean) - len(line_clean.lstrip())
            start = len(line_clean[:indent].encode("utf-16-le")) // 2
            end = len(line_clean.encode("utf-16-le")) // 2
            return start, max(start + 1, end)

        start = len(line_clean[:idx].encode("utf-16-le")) // 2
        end = len(line_clean[:idx + len(sub)].encode("utf-16-le")) // 2
        return start, end

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
        matches = difflib.get_close_matches(unknown_var, self.user_symbols, n=1, cutoff=0.6)
        if matches:
            return f" (did you mean '{matches[0]}' ?)"
        return ""

    def _suggest_similar_label(self, unknown_label: str) -> str:
        matches = difflib.get_close_matches(unknown_label, list(self.declared_labels.keys()), n=1, cutoff=0.6)
        if matches:
            return f" (did you mean '{matches[0]}' ?)"
        return ""

    def _analyze_file(self, file_path: str):
        try:
            # Если файл прямо сейчас редактируется в VS Code — берем его из памяти!
            if file_path in self.in_memory_files:
                lines = self.in_memory_files[file_path].splitlines(keepends=True)
            else:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()

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
            branch_uninitialized: dict[str, tuple[str, str]] = {}

            while idx < len(lines):
                raw_line = lines[idx]
                clean = raw_line.split("#")[0]
                stripped = clean.strip()
                line_indent = len(raw_line) - len(raw_line.lstrip(" "))

                if not stripped:
                    idx += 1
                    continue

                m_init = RE_INIT_PYTHON_START.match(raw_line)
                if m_init:
                    indent = len(m_init.group(1))
                    idx, _ = self._consume_block(lines, idx + 1, indent)
                    continue

                if current_screen is not None and line_indent <= current_screen_indent:
                    current_screen = None
                    screen_local_symbols.clear()

                m_label = RE_LABEL.match(clean)
                if m_label:
                    branch_uninitialized.clear()

                m_screen = RE_SCREEN_START.match(raw_line)
                if m_screen:
                    current_screen = m_screen.group(2)
                    current_screen_indent = len(m_screen.group(1))
                    screen_local_symbols.clear()
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

                m_menu = RE_MENU_START.match(raw_line)
                if m_menu and current_screen is None:
                    menu_indent = len(m_menu.group(1))
                    next_idx, uninit_vars = self._analyze_menu_flow(lines, idx + 1, menu_indent)
                    branch_uninitialized.update(uninit_vars)
                    idx = next_idx
                    continue

                m_jump = RE_JUMP_CALL.match(stripped)
                if m_jump:
                    cmd_type, target_label = m_jump.group(1), m_jump.group(2)
                    self.referenced_labels.add(target_label)
                    if target_label not in self.declared_labels:
                        hint = self._suggest_similar_label(target_label)
                        start_c, end_c = self._get_utf16_range(raw_line, target_label)
                        self._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=idx + 1,
                                line_content=stripped,
                                code="RPY302",
                                message=f"{cmd_type.capitalize()} to non-existent label '{target_label}'{hint}. Causes ScriptError.",
                                col=start_c,
                                end_col=end_c
                            ),
                            noqa_map
                        )
                    if cmd_type == "jump":
                        branch_uninitialized.clear()
                    idx += 1
                    continue

                m_play = RE_PLAY_AUDIO.match(stripped)
                if m_play:
                    audio_path = m_play.group(1).replace("\\", "/").lower()
                    audio_file = os.path.basename(audio_path)
                    if audio_path not in self.known_assets and audio_file not in self.known_assets:
                        self._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=idx + 1,
                                line_content=stripped,
                                code="RPY501",
                                message=f"Audio file '{m_play.group(1)}' not found in project or .rpa archives."
                            ),
                            noqa_map
                        )

                new_line, modified = self._check_and_fix_quoted_strings(
                    file_path, idx + 1, raw_line, screen_local_symbols, noqa_map
                )
                if modified:
                    lines[idx] = new_line
                    file_modified = True

                self._check_cfg_interpolations(file_path, idx + 1, stripped, branch_uninitialized, noqa_map)

                if stripped.startswith("$"):
                    py_code = stripped[1:].strip()
                    if current_screen is not None:
                        self._check_screen_mutation(py_code, file_path, idx + 1, stripped, current_screen, noqa_map)
                    else:
                        self._check_python_ast(py_code, file_path, start_line=idx + 1, noqa_map=noqa_map)
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
                            self._check_screen_mutation(code, file_path, idx + 2, stripped, current_screen, noqa_map)
                        else:
                            self._check_python_ast(code, file_path, start_line=idx + 2, noqa_map=noqa_map)
                            self._clear_safe_cfg_vars(code, branch_uninitialized)
                    idx = next_idx
                    continue

                m_cond = RE_CONDITION.match(stripped)
                if m_cond:
                    expr = m_cond.group(1)
                    self._check_condition(file_path, idx + 1, stripped, expr, current_screen, screen_local_symbols, noqa_map)
                    self._check_cfg_condition(file_path, idx + 1, stripped, expr, branch_uninitialized, noqa_map)

                idx += 1

            if file_modified and self.fix:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.writelines(lines)

        except (UnicodeDecodeError, OSError):
            pass

    def _check_and_fix_quoted_strings(self, file_path: str, line_idx: int, raw_line: str,
                                     extra_symbols: set[str], noqa_map: dict) -> tuple[str, bool]:
        modified = False
        reconstructed_line = raw_line

        matches = list(RE_STRING_MATCH.finditer(raw_line))
        for match in reversed(matches):
            full_str = match.group(0)
            quote_char = full_str[0]
            inner_content = full_str[1:-1]

            for var in RE_INTERPOLATION.findall(inner_content):
                if var not in self.declared_symbols and var not in extra_symbols:
                    hint = self._suggest_similar_symbol(var)
                    start_c, end_c = self._get_utf16_range(raw_line, f"[{var}]")
                    self._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=line_idx,
                            line_content=raw_line.strip(),
                            code="RPY101",
                            message=f"Variable '[{var}]' is not declared via 'default' or 'define'{hint}.",
                            col=start_c,
                            end_col=end_c,
                        ),
                        noqa_map
                    )


            stack: list[str] = []
            for t_match in RE_TAG.finditer(inner_content):
                is_closing = t_match.group(1) == "/"
                tag_name = t_match.group(2).lower()
                tag_param = t_match.group(3)

                if tag_name == "color" and not is_closing and tag_param:
                    color_val = tag_param.strip("\"'").lower()
                    if color_val.startswith("#"):
                        hex_str = color_val[1:]
                        if len(hex_str) not in (3, 4, 6, 8) or not all(c in "0123456789abcdef" for c in hex_str):
                            self._add_diagnostic(
                                Diagnostic(
                                    file_path=file_path,
                                    line_number=line_idx,
                                    line_content=raw_line.strip(),
                                    code="RPY304",
                                    message=f"Malformed hex color '{color_val}' in {{color}} tag."
                                ),
                                noqa_map
                            )
                    elif color_val not in NAMED_COLORS:
                        self._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=line_idx,
                                line_content=raw_line.strip(),
                                code="RPY304",
                                message=f"Unknown color name '{color_val}' in {{color}} tag."
                            ),
                            noqa_map
                        )

                if tag_name in SELF_CLOSING_TAGS:
                    continue

                if tag_name in PAIR_TAGS:
                    if is_closing:
                        if not stack:
                            self._add_diagnostic(
                                Diagnostic(
                                    file_path=file_path,
                                    line_number=line_idx,
                                    line_content=raw_line.strip(),
                                    code="RPY301",
                                    message=f"Found closing tag '{{/{tag_name}}}' without matching opening tag."
                                ),
                                noqa_map
                            )
                        else:
                            last_tag = stack.pop()
                            if last_tag != tag_name:
                                self._add_diagnostic(
                                    Diagnostic(
                                        file_path=file_path,
                                        line_number=line_idx,
                                        line_content=raw_line.strip(),
                                        code="RPY301",
                                        message=f"Mismatched tag: expected '{{/{last_tag}}}', found '{{/{tag_name}}}'."
                                    ),
                                    noqa_map
                                )
                    else:
                        stack.append(tag_name)

            if stack:
                if self.fix:
                    closing_tags = "".join(f"{{/{t}}}" for t in reversed(stack))
                    fixed_str = f"{quote_char}{inner_content}{closing_tags}{quote_char}"
                    start, end = match.span()
                    reconstructed_line = reconstructed_line[:start] + fixed_str + reconstructed_line[end:]
                    modified = True
                    self.fixed_count += 1
                else:
                    self.fixable_count += 1
                    unclosed = ", ".join(f"'{{{t}}}'" for t in stack)
                    self._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=line_idx,
                            line_content=raw_line.strip(),
                            code="RPY301",
                            message=f"Unclosed text tag(s) in dialogue: {unclosed}."
                        ),
                        noqa_map
                    )

        return reconstructed_line, modified

    def _check_unreachable_labels(self):
        for label_name, (file_path, line_idx, content) in self.declared_labels.items():
            if label_name.startswith("_") or label_name.lower() in SYSTEM_LABELS:
                continue
            if label_name not in self.referenced_labels:
                diag = Diagnostic(
                    file_path=file_path,
                    line_number=line_idx,
                    line_content=content,
                    code="RPY303",
                    message=f"Label '{label_name}' is declared but never jumped to or called. It might be unreachable dead code or dynamic router target.",
                    severity="INFO"
                )
                self.diagnostics.append(diag)

    def _analyze_menu_flow(self, lines: list[str], start_idx: int, menu_indent: int) -> tuple[int, dict[str, tuple[str, str]]]:
        idx = start_idx
        choices: list[dict] = []
        current_choice = None

        while idx < len(lines):
            raw_line = lines[idx]
            stripped = raw_line.split("#")[0].strip()
            line_indent = len(raw_line) - len(raw_line.lstrip(" "))

            if not stripped:
                idx += 1
                continue

            if line_indent <= menu_indent:
                break

            m_choice = RE_MENU_CHOICE.match(raw_line)
            if m_choice and line_indent > menu_indent:
                if current_choice:
                    choices.append(current_choice)
                current_choice = {
                    "title": m_choice.group(2).strip("\"'"),
                    "indent": line_indent,
                    "defined": set(),
                    "terminates": False,
                }
                idx += 1
                continue

            if current_choice and line_indent > current_choice["indent"]:
                if stripped.startswith("$"):
                    py = stripped[1:].strip()
                    with contextlib.suppress(SyntaxError):
                        tree = ast.parse(py)
                        for node in ast.walk(tree):
                            if isinstance(node, ast.Assign):
                                for target in node.targets:
                                    if isinstance(target, ast.Name):
                                        current_choice["defined"].add(target.id)
                if re.match(r"^\s*(jump\b|return\b)", stripped):
                    current_choice["terminates"] = True

            idx += 1

        if current_choice:
            choices.append(current_choice)

        merging_choices = [c for c in choices if not c["terminates"]]
        uninitialized_vars: dict[str, tuple[str, str]] = {}

        if len(merging_choices) > 1:
            all_defined = set().union(*(c["defined"] for c in merging_choices))
            for var in all_defined:
                if var in self.user_symbols:
                    continue

                defined_choice = next(c["title"] for c in merging_choices if var in c["defined"])
                missing_choice = next((c["title"] for c in merging_choices if var not in c["defined"]), None)

                if missing_choice:
                    uninitialized_vars[var] = (missing_choice, defined_choice)

        return idx, uninitialized_vars

    def _clear_safe_cfg_vars(self, py_code: str, branch_uninitialized: dict):
        with contextlib.suppress(SyntaxError):
            tree = ast.parse(py_code)
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            branch_uninitialized.pop(target.id, None)

    def _check_cfg_condition(self, file_path: str, line_idx: int, line_content: str, expr: str,
                            branch_uninitialized: dict, noqa_map: dict):
        with contextlib.suppress(SyntaxError):
            tree = ast.parse(expr, mode="eval")
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in branch_uninitialized:
                    missing_choice, defined_choice = branch_uninitialized[node.id]
                    self._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=line_idx,
                            line_content=line_content,
                            code="RPY401",
                            message=(
                                f"Variable '{node.id}' is only defined in menu choice '{defined_choice}', "
                                f"but missing in '{missing_choice}'. When choosing '{missing_choice}', "
                                "this condition will crash with NameError."
                            )
                        ),
                        noqa_map
                    )

    def _check_cfg_interpolations(self, file_path: str, line_idx: int, line_content: str,
                                 branch_uninitialized: dict, noqa_map: dict):
        matches = RE_STRING_MATCH.findall(line_content)
        for double_q, _, single_q, _ in matches:
            s = double_q if double_q else single_q
            for var in RE_INTERPOLATION.findall(s):
                if var in branch_uninitialized:
                    missing_choice, defined_choice = branch_uninitialized[var]
                    self._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=line_idx,
                            line_content=line_content,
                            code="RPY401",
                            message=(
                                f"Variable '[{var}]' is only defined in menu choice '{defined_choice}', "
                                f"but missing in '{missing_choice}'. Taking '{missing_choice}' will cause KeyError."
                            )
                        ),
                        noqa_map
                    )

    def _check_screen_mutation(self, py_code: str, file_path: str, line_idx: int, line_content: str, screen_name: str, noqa_map: dict):
        with contextlib.suppress(SyntaxError):
            tree = ast.parse(py_code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AugAssign)):
                    target_name = "variable"
                    if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                        target_name = node.target.id
                    elif isinstance(node, ast.Assign) and node.targets and isinstance(node.targets[0], ast.Name):
                        target_name = node.targets[0].id

                    self._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=line_idx,
                            line_content=line_content,
                            code="RPY201",
                            message=(
                                f"Direct state mutation '{target_name}' inside screen '{screen_name}'. "
                                "Screens are evaluated predictively and continuously! "
                                "Use screen Actions (e.g., SetVariable, Function) instead."
                            )
                        ),
                        noqa_map
                    )
                    break

    def _check_python_ast(self, py_code: str, file_path: str, start_line: int, noqa_map: dict):
        with contextlib.suppress(SyntaxError):
            tree = ast.parse(py_code)
            for node in tree.body:
                if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                    var_name = node.target.id
                    if var_name not in self.declared_symbols:
                        hint = self._suggest_similar_symbol(var_name)
                        real_line = start_line + getattr(node, "lineno", 1) - 1
                        self._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=real_line,
                                line_content=f"{var_name} += ...",
                                code="RPY102",
                                message=f"Augmented assignment to '{var_name}' before declaration via 'default'{hint}. Causes runtime NameError."
                            ),
                            noqa_map
                        )

                elif isinstance(node, ast.Assign):
                    real_line = start_line + getattr(node, "lineno", 1) - 1
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            self._verify_assign_target(target.id, file_path, real_line, noqa_map)
                        elif isinstance(target, (ast.Tuple, ast.List)):
                            for elt in target.elts:
                                if isinstance(elt, ast.Name):
                                    self._verify_assign_target(elt.id, file_path, real_line, noqa_map)

    def _verify_assign_target(self, var_name: str, file_path: str, line_idx: int, noqa_map: dict):
        if var_name.startswith("_"):
            return

        if var_name not in self.declared_symbols:
            hint = self._suggest_similar_symbol(var_name)
            self._add_diagnostic(
                Diagnostic(
                    file_path=file_path,
                    line_number=line_idx,
                    line_content=f"{var_name} = ...",
                    code="RPY104",
                    message=(
                        f"Variable '{var_name}' is assigned dynamically without a top-level 'default'{hint}. "
                        "This will break save games and cause NameError on other story branches."
                    ),
                ),
                noqa_map
            )
            self.declared_symbols.add(var_name)

    def _check_condition(self, file_path: str, line_idx: int, line_content: str, expr: str,
                         screen_name: str | None, screen_local_symbols: set[str], noqa_map: dict):
        with contextlib.suppress(SyntaxError):
            tree = ast.parse(expr, mode="eval")
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    var_name = node.id
                    if var_name not in self.declared_symbols and var_name not in screen_local_symbols:
                        hint = self._suggest_similar_symbol(var_name)
                        start_c, end_c = self._get_utf16_range(line_content, var_name)
                        if screen_name:
                            self._add_diagnostic(
                                Diagnostic(
                                    file_path=file_path,
                                    line_number=line_idx,
                                    line_content=line_content,
                                    code="RPY202",
                                    message=(
                                        f"Screen '{screen_name}' accesses undeclared variable '{var_name}'{hint}. "
                                        "Screens can be evaluated in the main menu or before game start, causing a crash."
                                    ),
                                    col=start_c,
                                    end_col=end_c
                                ),
                                noqa_map
                            )
                        else:
                            self._add_diagnostic(
                                Diagnostic(
                                    file_path=file_path,
                                    line_number=line_idx,
                                    line_content=line_content,
                                    code="RPY103",
                                    message=f"Undeclared variable '{var_name}' in condition{hint}. Evaluating this condition will crash with NameError.",
                                    col=start_c,
                                    end_col=end_c
                                ),
                                noqa_map
                            )