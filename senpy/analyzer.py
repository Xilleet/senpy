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
    fix_title: str | None = None
    fix_replacement: str | None = None


@dataclass
class AnalysisResult:
    diagnostics: list[Diagnostic]
    file_count: int
    total_lines: int
    fixed_count: int = 0
    fixable_count: int = 0


# Градация правил (Severity levels)
RULE_SEVERITY = {
    "RPY101": "ERROR",    # Опечатка в [var] -> падение с KeyError
    "RPY102": "ERROR",    # += до default -> NameError при входе
    "RPY103": "ERROR",    # if var: без объявления -> NameError при входе
    "RPY104": "WARNING",  # $ var = 1 без default -> риск для сохранений/патчей
    "RPY105": "ERROR",    # Мутация define-константы -> ломает откат и сейвы
    "RPY106": "WARNING",  # Использование import random / mutable set
    "RPY201": "WARNING",  # Мутация внутри screen -> ломает откат и нагружает UI
    "RPY202": "WARNING",  # Переменная в screen без default -> риск падения в меню
    "RPY203": "WARNING",  # Кнопка без action -> некликабельный UI
    "RPY204": "ERROR",    # Вызов или показ несуществующего экрана -> ScriptError
    "RPY205": "WARNING",  # Тяжелые циклы for/while внутри экрана -> тормоза UI
    "RPY301": "ERROR",    # Незакрытый тег диалога -> ломает стили/шрифт
    "RPY302": "ERROR",    # Прыжок на несуществующую метку -> ScriptError
    "RPY303": "INFO",     # Мертвая метка (эвристика, может быть динамический роутер)
    "RPY304": "ERROR",    # Невалидный hex-цвет -> падение движка рендера
    "RPY305": "ERROR",    # Неэкранированные кавычки внутри диалога
    "RPY306": "WARNING",  # call метки без return в конце -> сюжет утекает дальше
    "RPY401": "WARNING",  # Развилка menu: переменная объявлена не везде
    "RPY402": "WARNING",  # Пустой выбор в menu -> сквозной провал сюжета
    "RPY403": "WARNING",  # Заведомо ложное или мертвое условие
    "RPY501": "ERROR",    # Отсутствует аудиофайл
    "RPY502": "WARNING",  # Спрайт, поза или фон не найдены в ассетах
    "RPY504": "WARNING",  # Дубликат объявления image
}

BUILTIN_SCREENS = {
    "say", "choice", "nvl", "main_menu", "navigation", "file_slots",
    "save", "load", "preferences", "confirm", "history", "help",
    "keyboard_help", "mouse_help", "gamepad_help", "input", "notify",
    "quick_menu", "dialog", "ctc"
}

BUILTIN_COLORS = {"black", "white", "trueblack", "none"}
CLAUSE_KEYWORDS = {"at", "as", "with", "zorder", "behind", "onlayer"}

BUILTIN_SYMBOLS = {
    "config",
    "persistent",
    "renpy",
    "gui",
    "main_menu",
    "_return",
    "_in_replay",
    "_window_during_functions",
    "_history_list",
    "_restart",
    "name",
    "player",
    "theme",
    "style",
    "who",
    "what",
    "prefix_",
    *dir(builtins),
}

IGNORED_DIRS = {
    ".git", ".svn", ".hg", "node_modules", ".venv", "venv", "env",
    "__pycache__", ".idea", ".vscode", "build", "dist", "out"
}

SYSTEM_LABELS = {
    "start",
    "splashscreen",
    "after_load",
    "main_menu",
    "before_main_menu",
    "quit",
    "after_warp",
    "hide_windows",
}

SELF_CLOSING_TAGS = {"w", "p", "nw", "fast", "space", "vspace"}
PAIR_TAGS = {
    "b", "i", "u", "s", "plain", "color", "size", "font", "alpha", "cps", "k", "a"
}

NAMED_COLORS = {
    "black", "white", "red", "green", "blue", "yellow", "cyan", "magenta",
    "gray", "grey", "orange", "purple", "brown", "pink", "lime", "navy"
}

RE_DEFAULT = re.compile(r"^\s*default\s+([a-zA-Z_][a-zA-Z0-9_]*)")
RE_DEFINE = re.compile(r"^\s*define\s+([a-zA-Z_][a-zA-Z0-9_]*)")
RE_IMAGE_DEF = re.compile(r"^\s*image\s+([a-zA-Z0-9_]+(?:\s+[a-zA-Z0-9_]+)*)\s*[:=]")
RE_RETURN = re.compile(r"^\s*return\b")
RE_LABEL = re.compile(r"^\s*label\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:\(.*\))?\s*:")
RE_JUMP_CALL = re.compile(
    r"^\s*(jump|call)\s+(?!screen\b|expression\b)([a-zA-Z_][a-zA-Z0-9_]*)"
)
RE_PLAY_AUDIO = re.compile(
    r"^\s*play\s+(?:music|sound|voice|audio)\s+[\"']([^\"']+)[\"']", re.IGNORECASE
)
RE_INTERPOLATION = re.compile(r"\[([a-zA-Z_][a-zA-Z0-9_]*)(?:![a-zA-Z]+)?\]")
RE_CONDITION = re.compile(r"^\s*(?:if|elif)\s+(.+):$")
RE_PYTHON_BLOCK_START = re.compile(r"^(\s*)python(?:\s+early)?\s*:$")
RE_INIT_PYTHON_START = re.compile(r"^(\s*)init(?:\s+-?\d+)?\s+python(?:\s+early)?\s*:$")
RE_SCREEN_START = re.compile(
    r"^(\s*)screen\s+([a-zA-Z_][a-zA-Z0-9_]*)(?:\((.*?)\))?\s*:"
)
RE_SCREEN_CALL = re.compile(r"^\s*(?:show\s+screen|call\s+screen|use)\s+([a-zA-Z_][a-zA-Z0-9_]*)")
RE_SHOW_SCENE = re.compile(r"^\s*(show|scene)\s+(?!expression\b|screen\b)([a-zA-Z0-9_]+(?:\s+[a-zA-Z0-9_]+)*)")
RE_BUTTON_LINE = re.compile(r"^\s*(textbutton|imagebutton)\b")
RE_FOR_LOOP = re.compile(r"^\s*for\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+in\s+")
RE_MENU_START = re.compile(r"^(\s*)menu(?:\s+[a-zA-Z0-9_]+)?\s*:")
RE_MENU_CHOICE = re.compile(r"^(\s*)(\"[^\"]+\"|\'[^\']+\')(?:\s+if\s+.*)?\s*:")
RE_TAG = re.compile(r"\{(/)?([a-zA-Z_]+)(?:=([^}]*))?\}")
RE_STRING_MATCH = re.compile(
    r'("([^"\\]*(?:\\.[^"\\]*)*)")|(\'([^\'\\]*(?:\\.[^\'\\]*)*)\')'
)

RE_NOQA = re.compile(
    r"#\s*(?:noqa|senpy:\s*ignore)(?:\[([a-zA-Z0-9_,\s]+)\]|:\s*([a-zA-Z0-9_,\s]+))?",
    re.IGNORECASE,
)

def _infer_default_value(val_node: ast.AST | None) -> str:
    """Умно определяет стартовое значение для default по типу выражения."""
    if val_node is None:
        return "False"
    if isinstance(val_node, ast.Constant):
        if isinstance(val_node.value, bool):
            return "False"
        elif isinstance(val_node.value, (int, float)):
            return "0"
        elif isinstance(val_node.value, str):
            return '""'
        elif val_node.value is None:
            return "None"
    elif isinstance(val_node, (ast.List, ast.ListComp)):
        return "[]"
    elif isinstance(val_node, (ast.Dict, ast.DictComp)):
        return "{}"
    elif isinstance(val_node, (ast.Set, ast.SetComp)):
        return "[]"
    elif isinstance(val_node, ast.Call) and isinstance(val_node.func, ast.Name):
        if val_node.func.id in ("list", "set"):
            return "[]"
        elif val_node.func.id == "dict":
            return "{}"
    return "False"

class SenpyAnalyzer:
    def __init__(
        self,
        project_path: str,
        extra_files: list[str] | None = None,
        fix: bool = False,
        in_memory_files: dict[str, str] | None = None,
    ):
        self.project_path = project_path
        self.extra_files = extra_files or []
        self.fix = fix
        self.in_memory_files = {
            os.path.normcase(os.path.abspath(k)): v
            for k, v in (in_memory_files or {}).items()
        }
        self.user_symbols: set[str] = set()
        self.declared_symbols: set[str] = set(BUILTIN_SYMBOLS)
        self.defined_constants: set[str] = set()
        self.declared_labels: dict[str, tuple[str, int, str]] = {}
        self.declared_screens: dict[str, tuple[str, int]] = {}
        self.valid_images: set[str] = set(BUILTIN_COLORS)
        self.labels_with_return: set[str] = set()
        self.declared_images: dict[str, tuple[str, int]] = {}
        self.referenced_labels: set[str] = set()
        self.known_assets: set[str] = set()
        self.diagnostics: list[Diagnostic] = []
        self.missing_defaults: dict[str, str] = {}
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
        self.missing_defaults.clear()
        self.diagnostics.clear()
        self.user_symbols.clear()
        self.declared_symbols = set(BUILTIN_SYMBOLS)
        self.declared_labels.clear()
        self.declared_screens.clear()
        self.referenced_labels.clear()
        self.valid_images = set(BUILTIN_COLORS)
        self.labels_with_return.clear()
        self.declared_images.clear()
        self.total_lines = 0
        self.fixed_count = 0
        self.fixable_count = 0

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
        for root, dirs, filenames in os.walk(self.project_path):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for f in filenames:
                full_path = os.path.join(root, f)
                rel_path = (
                    os.path.relpath(full_path, self.project_path)
                    .replace("\\", "/")
                    .lower()
                )
                self.known_assets.add(rel_path)
                self.known_assets.add(f.lower())

                if f.lower().endswith(".rpa"):
                    self._read_rpa_index(full_path)

        for asset in self.known_assets:
            base, ext = os.path.splitext(asset)
            if ext.lower() in (".png", ".webp", ".jpg", ".jpeg"):
                clean_name = base.replace("\\", "/")
                if clean_name.startswith("images/"):
                    clean_name = clean_name[7:]
                tokenized = clean_name.replace("/", " ").replace("_", " ")
                self.valid_images.add(tokenized)
                self.valid_images.add(os.path.basename(clean_name))

    def _read_rpa_index(self, rpa_path: str):
        with (
            contextlib.suppress(
                OSError, zlib.error, pickle.UnpicklingError, ValueError
            ),
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
        for root, dirs, filenames in os.walk(self.project_path):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for f in filenames:
                if f.endswith(".rpy"):
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
                    self.defined_constants.add(var)
                    idx += 1
                    continue

                m_screen_def = RE_SCREEN_START.match(line)
                if m_screen_def:
                    s_name = m_screen_def.group(2)
                    self.declared_screens[s_name] = (file_path, idx + 1)

                m_label = RE_LABEL.match(clean)
                if m_label:
                    label_name = m_label.group(1)
                    self.declared_labels[label_name] = (file_path, idx + 1, clean)
                    
                    param_match = re.search(r"\((.*?)\)", clean)
                    if param_match:
                        raw_params = param_match.group(1)
                        for p in raw_params.split(","):
                            p_clean = p.split("=")[0].strip()
                            if p_clean and p_clean.isidentifier():
                                self.declared_symbols.add(p_clean)

                    check_idx = idx + 1
                    while check_idx < len(lines):
                        check_line = lines[check_idx].split("#")[0].strip()
                        if RE_LABEL.match(check_line):
                            break
                        if RE_RETURN.match(check_line):
                            self.labels_with_return.add(label_name)
                            break
                        check_idx += 1

                    idx += 1
                    continue

                m_img = RE_IMAGE_DEF.match(clean)
                if m_img:
                    img_name = m_img.group(1).strip()
                    if img_name in self.declared_images:
                        prev_file, prev_line = self.declared_images[img_name]
                        self.diagnostics.append(
                            Diagnostic(
                                file_path=file_path,
                                line_number=idx + 1,
                                line_content=clean,
                                code="RPY504",
                                message=f"Duplicate image declaration '{img_name}'. Previously declared in {os.path.basename(prev_file)}:{prev_line}."
                            )
                        )
                    else:
                        self.declared_images[img_name] = (file_path, idx + 1)
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
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
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

    @staticmethod
    def _get_utf16_range(line: str, sub: str | None = None) -> tuple[int, int]:
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
        matches = difflib.get_close_matches(
            unknown_var, self.user_symbols, n=1, cutoff=0.6
        )
        if matches:
            return f" (did you mean '{matches[0]}' ?)"
        return ""

    def _suggest_similar_label(self, unknown_label: str) -> str:
        matches = difflib.get_close_matches(
            unknown_label, list(self.declared_labels.keys()), n=1, cutoff=0.6
        )
        if matches:
            return f" (did you mean '{matches[0]}' ?)"
        return ""

    def _analyze_file(self, file_path: str):
        try:
            norm_path = os.path.normcase(os.path.abspath(file_path))
            if norm_path in self.in_memory_files:
                lines = self.in_memory_files[norm_path].splitlines(keepends=True)
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
                    next_idx, block_lines = self._consume_block(lines, idx + 1, indent)
                    if block_lines:
                        code = textwrap.dedent("".join(block_lines))
                        self._check_python_ast(code, file_path, start_line=idx + 2, noqa_map=noqa_map, lines=lines)
                    idx = next_idx
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

                    m_btn = RE_BUTTON_LINE.match(stripped)
                    if m_btn:
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
                                    end_col=end_c
                                ),
                                noqa_map
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

                # RPY204: Проверка вызова экранов
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
                                end_col=end_c
                            ),
                            noqa_map
                        )

                # RPY502: Проверка спрайтов и фонов в show / scene
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
                        base_tag = img_tokens[0]
                        all_valid = self.valid_images.union(self.declared_images.keys())

                        # В Ren'Py "show sayori at t42" легален, если базовый персонаж существует
                        is_single_tag_manipulation = len(img_tokens) == 1 and m_show.group(1) == "show"
                        has_base = any(img.startswith(base_tag + " ") or img == base_tag for img in all_valid)

                        if is_single_tag_manipulation and has_base:
                            pass  # Это просто перемещение или скрытие уже показанного персонажа
                        elif full_img_tag not in all_valid and full_img_tag not in BUILTIN_COLORS:
                            matches = difflib.get_close_matches(full_img_tag, list(all_valid), n=1, cutoff=0.6)
                            hint = f" (did you mean '{matches[0]}' ?)" if matches else ""

                            start_c, end_c = self._get_utf16_range(raw_line, full_img_tag)
                            msg = f"Sprite or background '{full_img_tag}' not found in assets or 'image' definitions{hint}."
                            if has_base and not hint:
                                msg += f" Base character '{base_tag}' exists, but attribute is missing."

                            best_sprite = matches[0] if matches else None
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
                                    fix_replacement=best_sprite
                                ),
                                noqa_map
                            )

                m_jump = RE_JUMP_CALL.match(stripped)
                if m_jump:
                    cmd_type, target_label = m_jump.group(1), m_jump.group(2)
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
                                fix_replacement=best_match
                            ),
                            noqa_map
                        )
                    if cmd_type == "jump":
                        branch_uninitialized.clear()
                    elif cmd_type == "call":
                        if target_label in self.declared_labels and target_label not in self.labels_with_return:
                            self._add_diagnostic(
                                Diagnostic(
                                    file_path=file_path,
                                    line_number=idx + 1,
                                    line_content=stripped,
                                    code="RPY306",
                                    message=f"Called label '{target_label}' does not contain a 'return' statement. Control flow will accidentally fall through to subsequent labels."
                                ),
                                noqa_map
                            )
                    idx += 1
                    continue

                m_play = RE_PLAY_AUDIO.match(stripped)
                if m_play:
                    audio_path = m_play.group(1).replace("\\", "/").lower()
                    audio_file = os.path.basename(audio_path)
                    if audio_path not in self.known_assets and audio_file not in self.known_assets:
                        raw_audio_str = m_play.group(1)
                        start_c, end_c = self._get_utf16_range(raw_line, raw_audio_str)
                        self._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=idx + 1,
                                line_content=stripped,
                                code="RPY501",
                                message=f"Audio file '{raw_audio_str}' not found in project or .rpa archives.",
                                col=start_c,
                                end_col=end_c
                            ),
                            noqa_map
                        )

                # RPY305: Проверка кавычек
                if not stripped.startswith(("#", "$", "image", "default", "define", "init", "Text(", "Composite(", "textbutton", "imagebutton", "action ", "add ", "Play(", "if ", "elif ", "text ")):
                    if not re.search(r'\baction\b|\bPlay\(|\bImageDissolve\(', stripped):
                        if not re.search(r'["\'],\s*["\']', stripped) and not stripped.endswith(","):
                            if re.search(r'(?<!\\)"[^"]*(?<!\\)"\s+[a-zA-Z0-9_а-яА-ЯёЁ]+.*(?<!\\)"', stripped):
                                self._add_diagnostic(
                                    Diagnostic(
                                        file_path=file_path,
                                        line_number=idx + 1,
                                        line_content=stripped,
                                        code="RPY305",
                                        message="Unescaped quotes inside dialogue text. Use '\\\"' instead of '\"' to avoid syntax errors."
                                    ),
                                    noqa_map
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
                            noqa_map,
                            lines=lines
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
                                noqa_map,
                                lines=lines
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
                        noqa_map,
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
                            start_c, end_c = self._get_utf16_range(raw_line, tag_param)
                            self._add_diagnostic(
                                Diagnostic(
                                    file_path=file_path,
                                    line_number=line_idx,
                                    line_content=raw_line.strip(),
                                    code="RPY304",
                                    message=f"Malformed hex color '{color_val}' in {{color}} tag.",
                                    col=start_c,
                                    end_col=end_c
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
                                message=f"Unknown color name '{color_val}' in {{color}} tag.",
                            ),
                            noqa_map,
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
                                    message=f"Found closing tag '{{/{tag_name}}}' without matching opening tag.",
                                ),
                                noqa_map,
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
                                        message=f"Mismatched tag: expected '{{/{last_tag}}}', found '{{/{tag_name}}}'.",
                                    ),
                                    noqa_map,
                                )
                    else:
                        stack.append(tag_name)

            if stack:
                if self.fix:
                    closing_tags = "".join(f"{{/{t}}}" for t in reversed(stack))
                    fixed_str = f"{quote_char}{inner_content}{closing_tags}{quote_char}"
                    start, end = match.span()
                    reconstructed_line = (
                        reconstructed_line[:start]
                        + fixed_str
                        + reconstructed_line[end:]
                    )
                    modified = True
                    self.fixed_count += 1
                else:
                    self.fixable_count += 1
                    unclosed = ", ".join(f"'{{{t}}}'" for t in stack)
                    first_unclosed_tag = f"{{{stack[0]}}}"
                    start_c, end_c = self._get_utf16_range(raw_line, first_unclosed_tag)
                    closing_tags = "".join(f"{{/{t}}}" for t in reversed(stack))

                    self._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=line_idx,
                            line_content=raw_line.strip(),
                            code="RPY301",
                            message=f"Unclosed text tag(s) in dialogue: {unclosed}.",
                            col=start_c,
                            end_col=end_c,
                            fix_title=f"Auto-close tag(s) with '{closing_tags}'",
                            fix_replacement=closing_tags
                        ),
                        noqa_map
                    )

        return reconstructed_line, modified

    def _check_unreachable_labels(self):
        for label_name, (file_path, line_idx, content) in self.declared_labels.items():
            clean_name = label_name.strip().lower()
            if clean_name.startswith("_") or clean_name in SYSTEM_LABELS or clean_name in ("start", "splashscreen", "after_load", "quit", "before_main_menu", "warningscreen"):
                continue
            if label_name not in self.referenced_labels:
                start_c, end_c = self._get_utf16_range(content, label_name)
                diag = Diagnostic(
                    file_path=file_path,
                    line_number=line_idx,
                    line_content=content,
                    code="RPY303",
                    message=f"Label '{label_name}' is declared but never jumped to or called. It might be unreachable dead code or dynamic router target.",
                    severity="INFO",
                    col=start_c,
                    end_col=end_c
                )
                self.diagnostics.append(diag)

    def _analyze_menu_flow(
        self,
        lines: list[str],
        start_idx: int,
        menu_indent: int,
        file_path: str = "",
        noqa_map: dict | None = None,
    ) -> tuple[int, dict[str, tuple[str, str]]]:
        idx = start_idx
        choices: list[dict] = []
        current_choice = None
        noqa_map = noqa_map or {}

        def check_empty_choice(choice_dict):
            if choice_dict and choice_dict["statement_count"] == 0 and file_path:
                raw_full = choice_dict.get("raw_full", choice_dict["raw"])
                start_c, end_c = self._get_utf16_range(raw_full, choice_dict["title"])
                self._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=choice_dict["line"],
                        line_content=choice_dict["raw"],
                        code="RPY402",
                        message=f"Menu choice '{choice_dict['title']}' has no statements inside and will immediately fall through.",
                        col=start_c,
                        end_col=end_c
                    ),
                    noqa_map
                )

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
                    check_empty_choice(current_choice)
                    choices.append(current_choice)
                current_choice = {
                    "title": m_choice.group(2).strip("\"'"),
                    "indent": line_indent,
                    "defined": set(),
                    "terminates": False,
                    "statement_count": 0,
                    "line": idx + 1,
                    "raw": stripped,
                    "raw_full": raw_line,
                }
                idx += 1
                continue

            if current_choice and line_indent > current_choice["indent"]:
                current_choice["statement_count"] += 1
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
            check_empty_choice(current_choice)
            choices.append(current_choice)

        merging_choices = [c for c in choices if not c["terminates"]]
        uninitialized_vars: dict[str, tuple[str, str]] = {}

        if len(merging_choices) > 1:
            all_defined = set().union(*(c["defined"] for c in merging_choices))
            for var in all_defined:
                if var in self.user_symbols:
                    continue

                defined_choice = next(
                    c["title"] for c in merging_choices if var in c["defined"]
                )
                missing_choice = next(
                    (c["title"] for c in merging_choices if var not in c["defined"]),
                    None,
                )

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

    def _check_cfg_condition(
        self,
        file_path: str,
        line_idx: int,
        line_content: str,
        expr: str,
        branch_uninitialized: dict,
        noqa_map: dict,
    ):
        with contextlib.suppress(SyntaxError):
            tree = ast.parse(expr, mode="eval")
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Load)
                    and node.id in branch_uninitialized
                ):
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
                            ),
                        ),
                        noqa_map,
                    )

    def _check_cfg_interpolations(
        self,
        file_path: str,
        line_idx: int,
        line_content: str,
        branch_uninitialized: dict,
        noqa_map: dict,
    ):
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
                            ),
                        ),
                        noqa_map,
                    )

    def _check_screen_mutation(self, py_code: str, file_path: str, line_idx: int, line_content: str, screen_name: str, noqa_map: dict, lines: list[str] | None = None):
        with contextlib.suppress(SyntaxError):
            tree = ast.parse(py_code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.For, ast.While)):
                    loop_type = type(node).__name__.lower()
                    real_line = line_idx + getattr(node, "lineno", 1) - 1
                    target_line = lines[real_line - 1] if lines and 0 <= real_line - 1 < len(lines) else f"{loop_type} ..."
                    start_c, end_c = self._get_utf16_range(target_line, loop_type)
                    self._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=real_line,
                            line_content=lines[real_line - 1].strip() if lines and 0 <= real_line - 1 < len(lines) else f"{loop_type} ...:",
                            code="RPY205",
                            message=(
                                f"Imperative '{loop_type}' loop inside screen '{screen_name}'. "
                                "Python loops inside screens severely hurt UI prediction performance. "
                                "Use screen-level declarative 'for' loops instead."
                            ),
                            col=start_c,
                            end_col=end_c
                        ),
                        noqa_map
                    )
                    break

                if isinstance(node, (ast.Assign, ast.AugAssign)):
                    target_name = "variable"
                    target_node = node.target if isinstance(node, ast.AugAssign) else (node.targets[0] if node.targets else None)
                    if isinstance(target_node, ast.Name):
                        target_name = target_node.id
                    elif isinstance(target_node, ast.Attribute):
                        target_name = ast.unparse(target_node) 

                    raw_l = lines[line_idx - 1] if lines and 0 <= line_idx - 1 < len(lines) else line_content
                    start_c, end_c = self._get_utf16_range(raw_l, target_name)

                    self._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=line_idx,
                            line_content=raw_l.strip(),
                            code="RPY201",
                            message=(
                                f"Direct state mutation '{target_name}' inside screen '{screen_name}'. "
                                "Screens are evaluated predictively and continuously! "
                                "Use screen Actions (e.g., SetVariable, Function) instead."
                            ),
                            col=start_c,
                            end_col=end_c
                        ),
                        noqa_map
                    )
                    break

    def _check_python_ast(self, py_code: str, file_path: str, start_line: int, noqa_map: dict, lines: list[str] | None = None):
        with contextlib.suppress(SyntaxError):
            tree = ast.parse(py_code)
            for node in tree.body:
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "random":
                            real_line = start_line + getattr(node, "lineno", 1) - 1
                            raw_l = lines[real_line - 1] if lines and 0 <= real_line - 1 < len(lines) else "import random"
                            start_c, end_c = self._get_utf16_range(raw_l, "import random")
                            self._add_diagnostic(
                                Diagnostic(
                                    file_path=file_path,
                                    line_number=real_line,
                                    line_content=raw_l.strip(),
                                    code="RPY106",
                                    message="Do not use standard 'import random'! It breaks Ren'Py rollback and save-game determinism. Use 'renpy.random' instead.",
                                    col=start_c,
                                    end_col=end_c,
                                    fix_title="Replace with 'from renpy import random'",
                                    fix_replacement="from renpy import random"
                                ),
                                noqa_map
                            )
                elif isinstance(node, ast.ImportFrom) and node.module == "random":
                    real_line = start_line + getattr(node, "lineno", 1) - 1
                    raw_l = lines[real_line - 1] if lines and 0 <= real_line - 1 < len(lines) else "from random import ..."
                    start_c, end_c = self._get_utf16_range(raw_l, "random")
                    self._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=real_line,
                            line_content=raw_l.strip(),
                            code="RPY106",
                            message="Do not import from 'random'! It breaks Ren'Py rollback and save-game determinism. Use 'renpy.random' instead.",
                            col=start_c,
                            end_col=end_c
                        ),
                        noqa_map
                    )

                elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                    var_name = node.target.id
                    real_line = start_line + getattr(node, "lineno", 1) - 1
                    raw_l = lines[real_line - 1] if lines and 0 <= real_line - 1 < len(lines) else ""
                    if (not raw_l or var_name not in raw_l) and lines and 0 <= start_line - 1 < len(lines):
                        raw_l = lines[start_line - 1]
                    start_c, end_c = self._get_utf16_range(raw_l, var_name)

                    if var_name in self.defined_constants:
                        self._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=real_line,
                                line_content=raw_l.strip(),
                                code="RPY105",
                                message=f"Constant '{var_name}' was declared with 'define', but modified via '+='. Use 'default' for mutable variables.",
                                col=start_c,
                                end_col=end_c
                            ),
                            noqa_map
                        )
                    elif var_name not in self.declared_symbols:
                        hint = self._suggest_similar_symbol(var_name)
                        self._add_diagnostic(
                            Diagnostic(
                                file_path=file_path,
                                line_number=real_line,
                                line_content=raw_l.strip(),
                                code="RPY102",
                                message=f"Augmented assignment to '{var_name}' before declaration via 'default'{hint}. Causes runtime NameError.",
                                col=start_c,
                                end_col=end_c
                            ),
                            noqa_map
                        )

                elif isinstance(node, ast.Assign):
                    real_line = start_line + getattr(node, "lineno", 1) - 1
                    raw_l = lines[real_line - 1] if lines and 0 <= real_line - 1 < len(lines) else ""
                    if not raw_l.strip() and lines and 0 <= start_line - 1 < len(lines):
                        raw_l = lines[start_line - 1]
                    for target in node.targets:
                        is_set = False
                        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "set":
                            is_set = True
                        elif isinstance(node.value, (ast.Set, ast.SetComp)):
                            is_set = True

                        if is_set:
                            sub_str = "set" if "set" in raw_l else "{"
                            start_c, end_c = self._get_utf16_range(raw_l, sub_str)
                            self._add_diagnostic(
                                Diagnostic(
                                    file_path=file_path,
                                    line_number=real_line,
                                    line_content=raw_l.strip(),
                                    code="RPY106",
                                    message="Do not use Python's mutable 'set'! Ren'Py rollback does not track standard sets and will corrupt saves. Use a list '[]' or 'renpy.revertable_set()' instead.",
                                    col=start_c,
                                    end_col=end_c
                                ),
                                noqa_map
                            )
                        if isinstance(target, ast.Name):
                            self._verify_assign_target(target.id, file_path, real_line, noqa_map, raw_line=raw_l, val_node=node.value)
                        elif isinstance(target, (ast.Tuple, ast.List)):
                            for elt in target.elts:
                                if isinstance(elt, ast.Name):
                                    self._verify_assign_target(elt.id, file_path, real_line, noqa_map, raw_line=raw_l, val_node=node.value)

    def _verify_assign_target(self, var_name: str, file_path: str, line_idx: int, noqa_map: dict, raw_line: str = "", val_node: ast.AST | None = None):
        if var_name.startswith("_"):
            return

        start_c, end_c = self._get_utf16_range(raw_line, var_name) if raw_line else (0, 0)

        if var_name in self.defined_constants:
            self._add_diagnostic(
                Diagnostic(
                    file_path=file_path,
                    line_number=line_idx,
                    line_content=f"{var_name} = ...",
                    code="RPY105",
                    message=(
                        f"Variable '{var_name}' was declared with 'define' (constant), but is reassigned dynamically. "
                        "Ren'Py expects 'default' for variables that change, otherwise rollback and saves will corrupt."
                    ),
                    col=start_c,
                    end_col=end_c
                ),
                noqa_map
            )
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
                    col=start_c,
                    end_col=end_c
                ),
                noqa_map
            )
            self.declared_symbols.add(var_name)
        if var_name not in self.missing_defaults:
                self.missing_defaults[var_name] = _infer_default_value(val_node)

    def _check_condition(
        self,
        file_path: str,
        line_idx: int,
        line_content: str,
        expr: str,
        screen_name: str | None,
        screen_local_symbols: set[str],
        noqa_map: dict,
    ):
        with contextlib.suppress(SyntaxError):
            cond_tree = ast.parse(expr, mode="eval")
            if isinstance(cond_tree.body, ast.Constant) and not bool(cond_tree.body.value):
                self._add_diagnostic(
                    Diagnostic(
                        file_path=file_path,
                        line_number=line_idx,
                        line_content=line_content,
                        code="RPY403",
                        message=f"Condition '{expr}' is always False. This block will never execute.",
                    ),
                    noqa_map
                )
            elif isinstance(cond_tree.body, ast.BoolOp) and isinstance(cond_tree.body.op, ast.And):
                names = {n.id for n in cond_tree.body.values if isinstance(n, ast.Name)}
                not_names = {
                    n.operand.id for n in cond_tree.body.values
                    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not) and isinstance(n.operand, ast.Name)
                }
                contradictions = names.intersection(not_names)
                if contradictions:
                    var_c = next(iter(contradictions))
                    self._add_diagnostic(
                        Diagnostic(
                            file_path=file_path,
                            line_number=line_idx,
                            line_content=line_content,
                            code="RPY403",
                            message=f"Condition contains mutually exclusive contradiction: '{var_c} and not {var_c}'. Always evaluates to False.",
                        ),
                        noqa_map
                    )
            tree = ast.parse(expr, mode="eval")
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    var_name = node.id
                    if var_name.startswith("_"):
                        continue
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
                                    end_col=end_c,
                                ),
                                noqa_map,
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
                                    end_col=end_c,
                                ),
                                noqa_map,
                            )

    def generate_defaults_file(self) -> tuple[str, int]:
        """Генерирует файл senpy_defaults.rpy со всеми найденными переменными."""
        if not self.missing_defaults:
            return "", 0

        # Если в проекте есть папка game/, сохраняем прямо в неё
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