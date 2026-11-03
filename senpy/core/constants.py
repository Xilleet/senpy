from __future__ import annotations

import builtins
import re

# Default cutoff ratio for difflib.get_close_matches suggestions (e.g. "did
# you mean '...' ?"). Used by senpy.text_utils.suggest_similar() and all
# rule checkers that suggest closest matches for typos.
SUGGESTION_CUTOFF = 0.6

BUILTIN_SCREENS = {
    "say",
    "choice",
    "nvl",
    "main_menu",
    "navigation",
    "file_slots",
    "save",
    "load",
    "preferences",
    "confirm",
    "history",
    "help",
    "keyboard_help",
    "mouse_help",
    "gamepad_help",
    "input",
    "notify",
    "quick_menu",
    "dialog",
    "ctc",
}

# Ren'Py built-in color-named image keywords. These are valid `show` /
# `scene` targets that Ren'Py ships with out of the box (solid-color
# displayables). Used by AssetManager to seed `valid_images` and by
# RPY502 (missing sprite) to avoid flagging `show black` as a missing
# asset. NOT the same as RENPY_NAMED_TEXT_COLORS — see below.
RENPY_BUILTIN_COLOR_KEYWORDS = {"black", "white", "trueblack", "none"}

# Backwards-compatibility alias. Senpy 0.6.x and earlier referenced
# `BUILTIN_COLORS` in user-facing code paths (plugins, external
# integrations). Keep the old name until 1.0 to avoid breakage.
BUILTIN_COLORS = RENPY_BUILTIN_COLOR_KEYWORDS

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
    "dissolve",
    "fade",
    "pixellate",
    "vpunch",
    "hpunch",
    "pushright",
    "pushleft",
    "pushup",
    "pushdown",
    "wipeleft",
    "wiperight",
    "wipeup",
    "wipedown",
    "slideleft",
    "slideright",
    "slideup",
    "slidedown",
    "zoomin",
    "zoomout",
    "zoominout",
    "blinds",
    "squares",
    "irisin",
    "irisout",
    # Standard Ren'Py positions and base transforms
    "center",
    "truecenter",
    "left",
    "right",
    "top",
    "topleft",
    "topright",
    "offscreenleft",
    "offscreenright",
    "reset",
    "default",
    # Built-in Ren'Py transition classes (for calls with parameters: Dissolve(1.0), Fade(...))
    "Dissolve",
    "Fade",
    "Pixellate",
    "MoveTransition",
    "MultipleTransition",
    "CropMove",
    "PushMove",
    "ImageDissolve",
    "AlphaDissolve",
    "ComposeTransition",
    "Pause",
    *dir(builtins),
}

BUILTIN_ACTIONS = {
    "SetVariable",
    "SetField",
    "SetScreenVariable",
    "ToggleVariable",
    "ToggleField",
    "ToggleScreenVariable",
    "Show",
    "Hide",
    "Jump",
    "Return",
    "Function",
    "Play",
    "Stop",
    "Queue",
    "PauseAudio",
    "NullAction",
    "Call",
    "Notify",
    "Confirm",
    "Preference",
    "FileSave",
    "FileLoad",
    "FileDelete",
    "FileAction",
    "QuickSave",
    "QuickLoad",
    "Rollback",
    "Skip",
    "Help",
    "Quit",
    "OpenURL",
    "SelectedIf",
    "SensitiveIf",
    "With",
    "HideInterface",
    "ShowMenu",
    "MainMenu",
    "Start",
    "EndReplay",
    "If",
    "Language",
    "ShowTransient",
    "FilePage",
}

# Single source of truth for the version — senpy/__version__.py.
# Previously the version was hardcoded in 4 places (pyproject.toml, constants.py,
# server.py, package.json). Now everyone imports from here, and bump_version.py
# writes here. This resolves P1-13 and P2-16.
from senpy.__version__ import __version__ as SENPY_VERSION  # noqa: E402,F401

IGNORED_DIRS = {
    ".git",
    ".svn",
    ".hg",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".idea",
    ".vscode",
    "build",
    "dist",
    "out",
    "renpy",
    "lib",
    ".senpy_cache",
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
    "$",
    "python",
    "menu",
    "show",
    "scene",
    "hide",
    "play",
    "stop",
    "voice",
    "queue",
    "call",
    "jump",
    "return",
    "default",
    "define",
    "image",
    "screen",
    "init",
    "label",
    "transform",
    "style",
    "window",
    "if",
    "elif",
    "else",
    "while",
    "for",
    "pass",
    "pause",
    "camera",
    "with",
    "text",
    "color",
    "frame",
    "vbox",
    "hbox",
    "grid",
    "fixed",
    "viewport",
    "button",
    "textbutton",
    "imagebutton",
    "bar",
    "vbar",
    "null",
    "add",
    "key",
    "timer",
    "on",
    "action",
    "use",
    "has",
    "hotspot",
    "hotbar",
}

SELF_CLOSING_TAGS = {"w", "p", "nw", "fast", "space", "vspace"}
PAIR_TAGS = {"b", "i", "u", "s", "plain", "color", "size", "font", "alpha", "cps", "k", "a"}

# Color keywords accepted by the `{color=NAME}` text tag. Ren'Py maps
# these to RGB triples internally (e.g. `red` → `#FF0000`). Used by
# RPY304 (malformed color) and the dialogue text-tag checker to
# distinguish `red` (a valid color keyword) from `reed` (a typo that
# would crash the text renderer).
#
# Note: `black` and `white` appear in BOTH `RENPY_BUILTIN_COLOR_KEYWORDS`
# (above) and this set. This is intentional — they are valid in both
# contexts: `show black` (image keyword) and `{color=black}` (text tag
# color keyword). Ren'Py treats them the same way internally.
RENPY_NAMED_TEXT_COLORS = {
    "black",
    "white",
    "red",
    "green",
    "blue",
    "yellow",
    "cyan",
    "magenta",
    "gray",
    "grey",
    "orange",
    "purple",
    "brown",
    "pink",
    "lime",
    "navy",
}

# Backwards-compatibility alias (see BUILTIN_COLORS above for rationale).
NAMED_COLORS = RENPY_NAMED_TEXT_COLORS

MEDIA_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".gif",
    ".avif",
    ".mp3",
    ".ogg",
    ".wav",
    ".opus",
    ".flac",
    ".webm",
    ".ogv",
    ".mp4",
    ".avi",
    ".mkv",
}
AUDIO_EXTENSIONS = {".mp3", ".ogg", ".wav", ".opus", ".flac"}

# Image extensions supported by Ren'Py at runtime. Subset of MEDIA_EXTENSIONS
# restricted to formats VS Code's markdown image renderer can decode in hover.
# AVIF/BMP/GIF are part of MEDIA_EXTENSIONS (used by RPY503 unused-asset check)
# but excluded from image-hover because VS Code's markdown renderer may not
# decode them; for hover we want formats we can also get pixel dimensions for
# via the lightweight header parser in senpy/domain/image_size.py.
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

# Video extensions: hover shows a "Play in default app" link instead of an
# inline preview (VS Code's image viewer cannot decode these formats).
VIDEO_EXTENSIONS = {".mp4", ".webm", ".ogv", ".avi", ".mkv"}

SMART_QUOTES = {"“": '"', "”": '"', "«": '"', "»": '"', "‘": "'", "’": "'"}

SCREEN_LOCAL_IGNORE = {
    "start",
    "end",
    "cols",
    "slot",
    "i",
    "idx",
    "item",
    "page",
    "original",
    "fixed1",
    "fixed2",
    "fixed3",
    "currentTrack",
    "lastPlayed",
}

# Compiled regular expressions
RE_DEFAULT = re.compile(r"^\s*default\s+([^\W\d]\w*)(?:\s*=\s*(.*))?")
RE_DEFINE = re.compile(r"^\s*define\s+([^\W\d]\w*)(?:\s*=\s*(.*))?")
RE_DEFINE_AUDIO = re.compile(r"^\s*define\s+(?:audio\.)?([^\W\d]\w*)\s*=\s*[\"']([^\"']+)[\"']")
RE_IMAGE_DEF = re.compile(r"^\s*image\s+(\w+(?:\s+\w+)*)\s*(?:=|:)(.*)")
RE_LAYEREDIMAGE_START = re.compile(r"^(\s*)layeredimage\s+([^\W\d]\w*)(?:\s*\(.*?\))?\s*:")
RE_LAYEREDIMAGE_ATTR = re.compile(r"^\s*attribute\s+([^\W\d]\w*)")
RE_RETURN = re.compile(r"^\s*return\b")
RE_LABEL = re.compile(r"^\s*label\s+(\.?[^\W\d][\w\.]*)\s*(?:\((.*?)\))?\s*:")
RE_JUMP_CALL = re.compile(r"^\s*(jump|call)\s+(?!screen\b)(\.?[^\W\d][\w\.]*|\bexpression\b)")
RE_AUDIO_STATEMENT = re.compile(
    r"^\s*(play|queue)\s+([^\W\d]\w*)(?:\s+(.+))?",
    re.IGNORECASE,
)
RE_STOP_STATEMENT = re.compile(r"^\s*stop\s+([^\W\d]\w*)")
RE_INTERPOLATION = re.compile(r"\[([^\W\d]\w*)[^\]]*\]")
RE_CONDITION = re.compile(r"^\s*(?:if|elif|while)\s+(.+):$")
RE_PYTHON_BLOCK_START = re.compile(r"^(\s*)python(?:\s+early)?\s*:\s*(?:#.*)?$")
RE_INIT_PYTHON_START = re.compile(r"^(\s*)init(?:\s+-?\d+)?\s+python(?:\s+early)?\s*:\s*(?:#.*)?$")
RE_TRANSFORM = re.compile(r"^\s*transform\s+([^\W\d]\w*)(?:\s*\((.*?)\))?\s*:")
RE_SCREEN_START = re.compile(r"^(\s*)screen\s+([^\W\d]\w*)(?:\((.*?)\))?\s*:\s*(?:#.*)?$")
RE_SCREEN_CALL = re.compile(r"^\s*(?:show\s+screen|call\s+screen|use)\s+([^\W\d]\w*)")
RE_SCREEN_JUMP_ACTION = re.compile(
    r'\b(?:Jump|Call|renpy\.jump|renpy\.call)\s*\(\s*["\']([^\W\d][\w\.]*)["\']'
)
RE_SCREEN_SHOW_ACTION = re.compile(r'\b(?:ShowMenu|Show)\s*\(\s*["\']([^\W\d][\w\.]*)["\']')
RE_SHOW_SCENE = re.compile(r"^\s*(show|scene)\s+(?!expression\b|screen\b)(\w+(?:\s+\w+)*)")
RE_BUTTON_LINE = re.compile(r"^\s*(textbutton|imagebutton)\b")
RE_FOR_LOOP = re.compile(r"^\s*for\s+([^\W\d]\w*)\s+in\s+")
RE_MENU_START = re.compile(r"^(\s*)menu(?:\s+\w+)?\s*:")
RE_MENU_CHOICE = re.compile(r"^(\s*)(\"[^\"]+\"|\'[^\']+\')(?:\s*\([^)]*\))?(?:\s+if\s+.*)?\s*:")
RE_TAG = re.compile(r"\{(/)?([a-zA-Z_]+)(?:=([^}]*))?\}")
RE_STRING_MATCH = re.compile(
    r'("""[\s\S]*?""")|' r"('''[\s\S]*?''')|" r'("(?:\\.|[^"\\\r\n])*")|' r"('(?:\\.|[^'\\\r\n])*')"
)
RE_NOQA = re.compile(
    r"#\s*(?:noqa|senpy:\s*ignore)(?:\[([a-zA-Z0-9_,\s]+)\]|:\s*([a-zA-Z0-9_,\s]+))?",
    re.IGNORECASE,
)
RE_JUMP_TARGET = re.compile(r"^\s*(?:jump|call)\s+(?!screen\b)(\.?[^\W\d][\w\.]*)")
RE_QUOTED_IDENTIFIER = re.compile(r'["\']([^\W\d]\w*)["\']')
