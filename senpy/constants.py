from __future__ import annotations

import builtins
import re

BUILTIN_SCREENS = {
    "say", "choice", "nvl", "main_menu", "navigation", "file_slots",
    "save", "load", "preferences", "confirm", "history", "help",
    "keyboard_help", "mouse_help", "gamepad_help", "input", "notify",
    "quick_menu", "dialog", "ctc"
}

BUILTIN_COLORS = {"black", "white", "trueblack", "none"}
BUILTIN_AUDIO_CHANNELS = {"music", "sound", "voice", "audio"}
CLAUSE_KEYWORDS = {"at", "as", "with", "zorder", "behind", "onlayer"}

BUILTIN_SYMBOLS = {
    "config",
    "persistent",
    "renpy",
    "audio",
    "currentuser",
    "gui",
    "layout",
    "store",
    "ui",
    "im",
    "Action",
    "Preferences",
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
    "dissolve", "fade", "pixellate", "vpunch", "hpunch", "pushright",
    "pushleft", "pushup", "pushdown", "wipeleft", "wiperight", "wipeup",
    "wipedown", "slideleft", "slideright", "slideup", "slidedown",
    "zoomin", "zoomout", "zoominout", "blinds", "squares", "irisin", "irisout",
    # Стандартные позиции и базовые трансформы Ren'Py
    "center", "truecenter", "left", "right", "top", "topleft", "topright",
    "offscreenleft", "offscreenright", "reset", "default",
    # Встроенные классы переходов Ren'Py (для вызовов с параметрами: Dissolve(1.0), Fade(...))
    "Dissolve", "Fade", "Pixellate", "MoveTransition", "MultipleTransition",
    "CropMove", "PushMove", "ImageDissolve", "AlphaDissolve", "ComposeTransition", "Pause",
    *dir(builtins),
}

BUILTIN_ACTIONS = {
    "SetVariable", "SetField", "SetScreenVariable", "ToggleVariable",
    "ToggleField", "ToggleScreenVariable", "Show", "Hide", "Jump",
    "Return", "Function", "Play", "Stop", "Queue", "PauseAudio",
    "NullAction", "Call", "Notify", "Confirm", "Preference",
    "FileSave", "FileLoad", "FileDelete", "FileAction", "QuickSave",
    "QuickLoad", "Rollback", "Skip", "Help", "Quit", "OpenURL",
    "SelectedIf", "SensitiveIf", "With", "HideInterface",
    "ShowMenu", "MainMenu", "Start", "EndReplay", "If", "Language", 
    "ShowTransient", "FilePage"
}

SENPY_VERSION = "0.4.5"

IGNORED_DIRS = {
    ".git", ".svn", ".hg", "node_modules", ".venv", "venv", "env",
    "__pycache__", ".idea", ".vscode", "build", "dist", "out",
    "renpy", "lib", ".senpy_cache"
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
    "warningscreen",
}

NON_DIALOGUE_STATEMENTS = {
    "$", "python", "menu", "show", "scene", "hide", "play", "stop",
    "voice", "queue", "call", "jump", "return", "default", "define",
    "image", "screen", "init", "label", "transform", "style", "window",
    "if", "elif", "else", "while", "for", "pass", "pause", "camera", "with",
    "text", "color", "frame", "vbox", "hbox", "grid", "fixed", "viewport",
    "button", "textbutton", "imagebutton", "bar", "vbar", "null", "add",
    "key", "timer", "on", "action", "use", "has", "hotspot", "hotbar"
}

SELF_CLOSING_TAGS = {"w", "p", "nw", "fast", "space", "vspace"}
PAIR_TAGS = {
    "b", "i", "u", "s", "plain", "color", "size", "font", "alpha", "cps", "k", "a"
}

NAMED_COLORS = {
    "black", "white", "red", "green", "blue", "yellow", "cyan", "magenta",
    "gray", "grey", "orange", "purple", "brown", "pink", "lime", "navy"
}

MEDIA_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".avif",
    ".mp3", ".ogg", ".wav", ".opus", ".flac", ".webm", ".ogv"
}
AUDIO_EXTENSIONS = {".mp3", ".ogg", ".wav", ".opus", ".flac"}

SMART_QUOTES = {
    "“": '"', "”": '"', "«": '"', "»": '"',
    "‘": "'", "’": "'"
}

SCREEN_LOCAL_IGNORE = {
    "start", "end", "cols", "slot", "i", "idx", "item", "page",
    "original", "fixed1", "fixed2", "fixed3", "currentTrack", "lastPlayed"
}

# Скомпилированные регулярные выражения
RE_DEFAULT = re.compile(r"^\s*default\s+([a-zA-Z_][a-zA-Z0-9_]*)(?:\s*=\s*(.*))?")
RE_DEFINE = re.compile(r"^\s*define\s+([a-zA-Z_][a-zA-Z0-9_]*)(?:\s*=\s*(.*))?")
RE_DEFINE_AUDIO = re.compile(
    r"^\s*define\s+(?:audio\.)?([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*[\"']([^\"']+)[\"']"
)
RE_IMAGE_DEF = re.compile(r"^\s*image\s+([a-zA-Z0-9_]+(?:\s+[a-zA-Z0-9_]+)*)\s*(?:=|:)(.*)")
RE_LAYEREDIMAGE_START = re.compile(
    r"^(\s*)layeredimage\s+([a-zA-Z_][a-zA-Z0-9_]*)(?:\s*\(.*?\))?\s*:"
)
RE_LAYEREDIMAGE_ATTR = re.compile(r"^\s*attribute\s+([a-zA-Z_][a-zA-Z0-9_]*)")
RE_RETURN = re.compile(r"^\s*return\b")
RE_LABEL = re.compile(r"^\s*label\s+(\.?[a-zA-Z_][a-zA-Z0-9_\.]*)\s*(?:\((.*?)\))?\s*:")
RE_JUMP_CALL = re.compile(
    r"^\s*(jump|call)\s+(?!screen\b)(\.?[a-zA-Z_][a-zA-Z0-9_\.]*|\bexpression\b)"
)
RE_AUDIO_STATEMENT = re.compile(
    r"^\s*(play|queue)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+(.+)",
    re.IGNORECASE,
)
RE_INTERPOLATION = re.compile(r"\[([a-zA-Z_][a-zA-Z0-9_]*)[^\]]*\]")
RE_CONDITION = re.compile(r"^\s*(?:if|elif|while)\s+(.+):$")
RE_PYTHON_BLOCK_START = re.compile(r"^(\s*)python(?:\s+early)?\s*:\s*(?:#.*)?$")
RE_INIT_PYTHON_START = re.compile(r"^(\s*)init(?:\s+-?\d+)?\s+python(?:\s+early)?\s*:\s*(?:#.*)?$")
RE_TRANSFORM = re.compile(r"^\s*transform\s+([a-zA-Z_][a-zA-Z0-9_]*)(?:\s*\(.*?\))?\s*:")
RE_SCREEN_START = re.compile(
    r"^(\s*)screen\s+([a-zA-Z_][a-zA-Z0-9_]*)(?:\((.*?)\))?\s*:\s*(?:#.*)?$"
)
RE_SCREEN_CALL = re.compile(r"^\s*(?:show\s+screen|call\s+screen|use)\s+([a-zA-Z_][a-zA-Z0-9_]*)")
RE_SHOW_SCENE = re.compile(r"^\s*(show|scene)\s+(?!expression\b|screen\b)([a-zA-Z0-9_]+(?:\s+[a-zA-Z0-9_]+)*)")
RE_BUTTON_LINE = re.compile(r"^\s*(textbutton|imagebutton)\b")
RE_FOR_LOOP = re.compile(r"^\s*for\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+in\s+")
RE_MENU_START = re.compile(r"^(\s*)menu(?:\s+[a-zA-Z0-9_]+)?\s*:")
RE_MENU_CHOICE = re.compile(
    r"^(\s*)(\"[^\"]+\"|\'[^\']+\')(?:\s*\([^)]*\))?(?:\s+if\s+.*)?\s*:"
)
RE_TAG = re.compile(r"\{(/)?([a-zA-Z_]+)(?:=([^}]*))?\}")
RE_STRING_MATCH = re.compile(
    r'("""[\s\S]*?""")|'
    r"('''[\s\S]*?''')|"
    r'("(?:\\.|[^"\\\r\n])*")|'
    r"('(?:\\.|[^'\\\r\n])*')"
)
RE_NOQA = re.compile(
    r"#\s*(?:noqa|senpy:\s*ignore)(?:\[([a-zA-Z0-9_,\s]+)\]|:\s*([a-zA-Z0-9_,\s]+))?",
    re.IGNORECASE,
)
RE_JUMP_TARGET = re.compile(r"^\s*(?:jump|call)\s+(?!screen\b)(\.?[a-zA-Z_][a-zA-Z0-9_\.]*)")
RE_QUOTED_IDENTIFIER = re.compile(r'["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']')