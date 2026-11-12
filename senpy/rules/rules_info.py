from __future__ import annotations

from typing import TypedDict

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


class RuleInfo(TypedDict):
    """Schema of a single entry in ``RULES_DATABASE``.

    Introducing a ``TypedDict`` lets mypy narrow ``RULES_DATABASE[code]``
    from the unified ``dict[str, str | list[str] | ...]`` value type that
    emerges from a plain dict literal. Without it, ``info["title"]`` is
    inferred as ``str | list[str] | ...`` and breaks both
    ``Table.add_row`` (``[arg-type]``) and ``RULE_SEVERITY``'s
    ``dict[str, str]`` annotation (``[misc]``).
    """

    title: str
    severity: str
    tags: list[str]
    why: str
    bad: str
    good: str


RULES_DATABASE: dict[str, RuleInfo] = {
    # ---------------- 000: Internal (Senpy signals, not user rules) --------
    # RPY000 is emitted by AnalysisPipeline._analyze_all_files when a
    # built-in checker raises an unhandled exception during analysis. It
    # is not triggered by anything in user .rpy code — it signals a bug
    # in Senpy itself. Registered in RULES_DATABASE (rather than being an
    # ad-hoc code) so that:
    #   - `senpy rule show RPY000` prints a real description instead of
    #     "Unknown rule code";
    #   - RULE_SEVERITY (derived from this dict) returns "ERROR" for
    #     RPY000 instead of falling back to the "WARNING" default that
    #     _apply_severity uses for unknown codes;
    #   - the rule list groups it under an explicit "Internal" section so
    #     users understand it is a Senpy signal, not a rule they can fix
    #     by editing their .rpy file.
    "RPY000": {
        "title": "Senpy internal error",
        "severity": "ERROR",
        "tags": ["internal"],
        "why": (
            "An unexpected exception occurred inside Senpy while analyzing a file. "
            "This is a bug in Senpy itself, not in your .rpy code — please report it "
            "at https://github.com/Xilleet/senpy/issues with the file that triggered "
            "the error, the exception traceback printed to stderr, and the Senpy "
            "version (`senpy --version`)."
        ),
        "bad": (
            "# RPY000 is not triggered by user code — it is emitted by Senpy\n"
            "# when an internal checker raises an unhandled exception.\n"
            "# If you see it, your .rpy file exposed a Senpy bug; please report it."
        ),
        "good": (
            "# Suppress on a specific line if you cannot fix Senpy right away:\n"
            "label start:\n"
            "    $ risky_call()  # noqa: RPY000\n"
            "\n"
            "# Or run with --select RPY000 to surface only internal errors\n"
            "# when reproducing a bug report."
        ),
    },
    # ---------------- 000: Indentation & Code Formatting ----------------
    "RPY001": {
        "title": "Tab character in indentation",
        "severity": "ERROR",
        "tags": ["formatting", "syntax"],
        "why": "Ren'Py requires 4 spaces per indentation level. Tab characters ('\\t') cause indentation mismatches and SyntaxError across different editors and operating systems.",
        "bad": 'label start:\n\t"Tab character used here!"',
        "good": 'label start:\n    "Standard 4 spaces used here."',
    },
    "RPY002": {
        "title": "Smart/curly quotes in code statement",
        "severity": "ERROR",
        "tags": ["formatting", "syntax"],
        "why": "Typographic smart quotes (“ ” ‘ ’ « ») copied from text editors like MS Word into Python code statements cause a fatal SyntaxError.",
        "bad": "$ status = “active”\nif item == «key»: ...",
        "good": '$ status = "active"\nif item == "key": ...',
    },
    # ---------------- 100: Variables, Types & Rollback ----------------
    "RPY100": {
        "title": "File is not valid UTF-8",
        "severity": "ERROR",
        "tags": ["encoding", "io"],
        "why": "Ren'Py reads all .rpy scripts as UTF-8. A file saved in another encoding (e.g. Windows-1251) crashes the game on load. Senpy skips such files, so they must be re-saved as UTF-8.",
        "bad": "script.rpy saved in Windows-1251: bytes b'\\xcf\\xf0\\xe8\\xe2\\xe5\\xf2' instead of text",
        "good": "Re-save the file with UTF-8 encoding (VS Code: bottom-right status bar -> Save with Encoding -> UTF-8).",
    },
    "RPY101": {
        "title": "Unresolved variable in dialogue interpolation",
        "severity": "ERROR",
        "tags": ["variables", "dialogue"],
        "why": "Using [variable] in dialogue when it is not declared via 'default' or 'define' will crash the game with KeyError during text rendering.",
        "bad": '"Hello, [player_namme]!"  # Typo in variable name',
        "good": 'default player_name = "Eileen"\n"Hello, [player_name]!"',
    },
    "RPY102": {
        "title": "Augmented assignment before 'default' declaration",
        "severity": "ERROR",
        "tags": ["variables", "state"],
        "why": "Doing +=, -=, etc. to a variable before it has been initialized causes an immediate runtime NameError when entering the scene.",
        "bad": "label start:\n    $ score += 10  # score does not exist yet!",
        "good": "default score = 0\nlabel start:\n    $ score += 10",
    },
    "RPY103": {
        "title": "Undeclared variable in condition",
        "severity": "ERROR",
        "tags": ["variables", "state"],
        "why": "Evaluating 'if var:' or 'elif var:' crashes the engine with NameError if the variable was never declared.",
        "bad": "if has_key:\n    jump secret_room",
        "good": "default has_key = False\nlabel start:\n    if has_key:\n        jump secret_room",
    },
    "RPY104": {
        "title": "Dynamic assignment without top-level 'default'",
        "severity": "WARNING",
        "tags": ["variables", "state", "rollback"],
        "why": "Assigning variables on the fly ($ var = 1) without a top-level 'default' will corrupt save files upon game updates and cause NameError on other story branches.",
        "bad": "label chapter_2:\n    $ affection = 5  # No top-level default!",
        "good": "default affection = 0\nlabel chapter_2:\n    $ affection = 5",
    },
    "RPY105": {
        "title": "Direct mutation of 'define' constant",
        "severity": "ERROR",
        "tags": ["variables", "state", "rollback"],
        "why": "Variables declared with 'define' are static constants (characters, configurations). Modifying them breaks Ren'Py rollback and save persistence.",
        "bad": "define karma = 0\nlabel start:\n    $ karma += 1",
        "good": "default karma = 0  # Use default for mutable state!\nlabel start:\n    $ karma += 1",
    },
    "RPY106": {
        "title": "Usage of non-revertable Python types (random / mutable set)",
        "severity": "WARNING",
        "tags": ["variables", "rollback"],
        "why": "Standard Python 'import random' and mutable 'set()' are not tracked by Ren'Py's rollback engine. Players rolling back will experience save desynchronization.",
        "bad": "import random\n$ inventory = set()",
        "good": "from renpy import random\n$ inventory = []  # or renpy.revertable_set()",
    },
    "RPY107": {
        "title": "Usage of deprecated / obsolete Ren'Py API",
        "severity": "WARNING",
        "tags": ["deprecated"],
        "why": "Calling obsolete Ren'Py functions (LiveComposite, DynamicCharacter, im.*, ui.*) harms rendering performance (CPU vs GPU) or breaks on Ren'Py 7/8.",
        "bad": 'image natsuki = LiveComposite((960, 960), (0, 0), "base.png")\ndefine c = DynamicCharacter("char_name")',
        "good": 'image natsuki = Composite((960, 960), (0, 0), "base.png")\ndefine c = Character("[char_name]")',
    },
    "RPY108": {
        "title": "Type taint conflict or incompatible augmented assignment",
        "severity": "ERROR",
        "tags": ["variables", "types"],
        "why": "Assigning incompatible types (e.g. str to int) or performing operations like 'str += int' causes fatal runtime TypeErrors.",
        "bad": 'default player_name = "Eileen"\ndefault score = 0\nlabel start:\n    $ player_name += 1\n    $ score = "High"',
        "good": 'default player_name = "Eileen"\ndefault score = 0\nlabel start:\n    $ player_name += "!"\n    $ score = 100',
    },
    "RPY109": {
        "title": "Init phase dependency graph violation",
        "severity": "ERROR",
        "tags": ["init-order", "python"],
        "why": "Ren'Py loads files in alphabetical order. If 'a_file.rpy' calls a function in 'init python' that is defined in 'z_file.rpy', the game will crash on startup because 'z_file' hasn't loaded yet.",
        "bad": "# a_setup.rpy\ninit python:\n    setup_gui()  # Crashes!\n\n# z_helpers.rpy\ninit python:\n    def setup_gui(): ...",
        "good": "# a_helpers.rpy\ninit python:\n    def setup_gui(): ...\n\n# z_setup.rpy\ninit python:\n    setup_gui()",
    },
    "RPY110": {
        "title": "Python syntax error in $-statement or init python block",
        "severity": "ERROR",
        "tags": ["python", "syntax"],
        "why": "Invalid Python syntax in a `$`-statement or `init python:` block will cause a SyntaxError at runtime, crashing the game. Catching this at lint time prevents a crash that would only surface when the player reaches that line.",
        "bad": "label start:\n    $ x = )  # SyntaxError!",
        "good": "label start:\n    $ x = 1  # Valid",
    },
    # ---------------- 200: Screen Language & UI ----------------
    "RPY201": {
        "title": "Direct state mutation inside screen",
        "severity": "WARNING",
        "tags": ["screen", "state", "rollback"],
        "why": "Screens are evaluated continuously and predictively by the UI loop. Direct state mutations run repeatedly every frame and break rollback.",
        "bad": "screen shop():\n    $ player_gold -= 10  # Runs repeatedly during prediction!",
        "good": "screen shop():\n    textbutton 'Buy' action SetVariable('player_gold', player_gold - 10)",
    },
    "RPY202": {
        "title": "Screen accesses variable without 'default'",
        "severity": "WARNING",
        "tags": ["screen", "variables"],
        "why": "Screens can be evaluated before story start (e.g. in the main menu or prediction loop). Reading undeclared variables crashes the game.",
        "bad": "screen hud():\n    if show_quest_tracker: ...",
        "good": "default show_quest_tracker = False\nscreen hud():\n    if show_quest_tracker: ...",
    },
    "RPY203": {
        "title": "Button without 'action' argument",
        "severity": "WARNING",
        "tags": ["screen", "ui"],
        "why": "Buttons (textbutton, imagebutton) without an 'action' property are non-interactive dead UI elements.",
        "bad": 'textbutton "Confirm"  # Cannot be clicked!',
        "good": 'textbutton "Confirm" action Return()',
    },
    "RPY204": {
        "title": "Call/Show to non-existent screen",
        "severity": "ERROR",
        "tags": ["screen", "flow"],
        "why": "Calling or showing a screen that does not exist crashes the game with 'Exception: Screen is not known'.",
        "bad": "call screen inventory_menuu  # Typo!",
        "good": "call screen inventory_menu",
    },
    "RPY205": {
        "title": "Imperative Python loop inside screen",
        "severity": "WARNING",
        "tags": ["screen", "performance"],
        "why": "Writing imperative for/while loops in Python blocks inside screens severely hurts UI prediction and causes frame drops.",
        "bad": "screen inv():\n    python:\n        for item in items: ...",
        "good": "screen inv():\n    for item in items:\n        text item",
    },
    "RPY206": {
        "title": "Direct function call in button action",
        "severity": "ERROR",
        "tags": ["screen", "ui"],
        "why": "Directly calling a function with parentheses in action executes it immediately during screen render, not upon user click.",
        "bad": "textbutton 'Heal' action heal_player()  # Executes on screen show!",
        "good": "textbutton 'Heal' action Function(heal_player)  # Executes on click",
    },
    "RPY207": {
        "title": "Invalid arguments when showing or using a screen",
        "severity": "ERROR",
        "tags": ["screen", "arguments"],
        "why": "Calling or using a screen with missing required parameters or unknown arguments causes a fatal runtime Exception.",
        "bad": "screen inv(sort_by):\n    ...\nuse inv()  # Missing required argument 'sort_by'!",
        "good": "screen inv(sort_by='name'):\n    ...\nuse inv()",
    },
    "RPY208": {
        "title": "Screen-local variable modified via global action or store mutation",
        "severity": "ERROR",
        "tags": ["screen", "state"],
        "why": "Variables declared with 'default' inside a screen or screen parameters are screen-local. Using 'SetVariable' or '$ var = ...' modifies the global store instead of the screen variable, causing UI desynchronization and broken button interactions.",
        "bad": 'screen shop():\n    default selected_item = None\n    textbutton "Sword" action SetVariable("selected_item", "Sword")',
        "good": 'screen shop():\n    default selected_item = None\n    textbutton "Sword" action SetScreenVariable("selected_item", "Sword")',
    },
    # ---------------- 300: Dialogue & Control Flow ----------------
    "RPY301": {
        "title": "Unclosed or mismatched text tag in dialogue",
        "severity": "ERROR",
        "tags": ["dialogue", "text-tags"],
        "why": "Unclosed tags like {b} will bleed styles into all subsequent dialogues across the entire game.",
        "bad": '"Danger: {b}Hazardous area!"',
        "good": '"Danger: {b}Hazardous area!{/b}"',
    },
    "RPY302": {
        "title": "Jump or Call to non-existent label",
        "severity": "ERROR",
        "tags": ["flow", "labels"],
        "why": "Jumping to a label that does not exist immediately terminates the novel with ScriptError.",
        "bad": "jump bad_edd  # Typo",
        "good": "jump bad_end",
    },
    "RPY303": {
        "title": "Unreferenced / Dead label",
        "severity": "INFO",
        "tags": ["dead-code", "labels"],
        "why": "Label is declared but never called or jumped to anywhere in the project. It might be dead code or a forgotten draft.",
        "bad": "label forgotten_draft:\n    'Old scene never reached...'",
        "good": "# Connect to story flow with jump/call or remove dead script",
    },
    "RPY304": {
        "title": "Malformed color in {color} tag",
        "severity": "ERROR",
        "tags": ["dialogue", "text-tags", "colors"],
        "why": "Typo in hex code (e.g. #12345) or unknown color name causes the Ren'Py text renderer to crash.",
        "bad": '"{color=#12345}Text{/color}"',
        "good": '"{color=#123456}Text{/color}"',
    },
    "RPY305": {
        "title": "Unescaped quotes inside dialogue string",
        "severity": "ERROR",
        "tags": ["dialogue", "syntax"],
        "why": 'Quotes inside a dialogue string without escaping (\\") break the string literal parser at startup.',
        "bad": '"She said "Hello" and smiled."',
        "good": '"She said \\"Hello\\" and smiled."',
    },
    "RPY306": {
        "title": "Called label without 'return' statement",
        "severity": "WARNING",
        "tags": ["flow", "labels"],
        "why": "Invoking a label via 'call' expects a 'return'. Without it, control flow accidentally bleeds into unrelated scenes.",
        "bad": "label sub_scene:\n    'Dialogue...'\n    # Missing return!",
        "good": "label sub_scene:\n    'Dialogue...'\n    return",
    },
    "RPY307": {
        "title": "Duplicate label declaration",
        "severity": "ERROR",
        "tags": ["labels", "syntax"],
        "why": "Declaring two labels with the same name across any project script causes a fatal ScriptError on startup.",
        "bad": "label chapter_1:\n    ...\nlabel chapter_1:  # Duplicate!\n    ...",
        "good": "label chapter_1:\n    ...\nlabel chapter_2:\n    ...",
    },
    "RPY308": {
        "title": "Label preceded by regular statements (Fallthrough hazard)",
        "severity": "WARNING",
        "tags": ["flow", "labels"],
        "why": "Ending a scene without 'jump' or 'return' before the next label causes control flow to unintentionally fall right through into the next scene.",
        "bad": 'label scene_a:\n    "End of scene A."\nlabel scene_b:\n    "Scene B starts immediately!"',
        "good": 'label scene_a:\n    "End of scene A."\n    return\nlabel scene_b:\n    "Scene B starts!"',
    },
    "RPY309": {
        "title": "Story island / isolated subgraph unreachable from 'start'",
        "severity": "WARNING",
        "tags": ["flow", "dead-code"],
        "why": "A group of scenes references each other in a loop, but no entry point exists from 'start', 'splashscreen', or main menus. This represents unreachable dead content or orphaned story routes.",
        "bad": "label route_a:\n    jump route_b\nlabel route_b:\n    jump route_a",
        "good": "# Connect route to story flow via jump or call from start",
    },
    "RPY310": {
        "title": "Invalid argument count or keyword in 'call' statement",
        "severity": "ERROR",
        "tags": ["flow", "arguments"],
        "why": "Calling a label with too few, too many, or unknown keyword arguments crashes the game with an immediate TypeError.",
        "bad": "label forest(time, weather):\n    ...\ncall forest('day')  # Missing 'weather' argument!",
        "good": "label forest(time, weather='sunny'):\n    ...\ncall forest('day')",
    },
    # ---------------- 400: Branching & Conditions ----------------
    "RPY401": {
        "title": "Variable defined in one menu choice but missing in another",
        "severity": "WARNING",
        "tags": ["flow", "variables", "branching"],
        "why": "If Choice A defines a variable but Choice B does not, choosing Choice B and later reading the variable causes a fatal NameError.",
        "bad": 'menu:\n    "Take torch":\n        $ torch = True\n    "Walk in dark":\n        pass\nif torch: ...  # Crashes if dark was chosen!',
        "good": 'default torch = False\nmenu:\n    "Take torch":\n        $ torch = True\n    "Walk in dark":\n        pass',
    },
    "RPY402": {
        "title": "Empty menu choice",
        "severity": "WARNING",
        "tags": ["flow", "menu", "branching"],
        "why": "A menu choice was defined without any body statements, causing the story to immediately fall through.",
        "bad": 'menu:\n    "Give up":\n    "Fight":\n        "Battle!"',
        "good": 'menu:\n    "Give up":\n        return\n    "Fight":\n        "Battle!"',
    },
    "RPY403": {
        "title": "Always-false or contradictory condition",
        "severity": "WARNING",
        "tags": ["flow", "dead-code", "branching"],
        "why": "Conditions like 'if False:' or 'if x and not x:' can never be true. The code block will never execute.",
        "bad": "if False:\n    'This story branch is dead.'",
        "good": "if has_secret_item:\n    'Secret branch!'",
    },
    "RPY404": {
        "title": "Variable in MAYBE_SET state evaluated after menu branch",
        "severity": "WARNING",
        "tags": ["flow", "variables", "branching"],
        "why": "If a variable is only defined in one choice of a menu, choosing an alternate path and subsequently evaluating the variable or interpolating it will crash with NameError or KeyError.",
        "bad": 'menu:\n    "Take torch":\n        $ torch = True\n    "Wait":\n        pass\nif torch: ...',
        "good": 'default torch = False\nmenu:\n    "Take torch":\n        $ torch = True\n    "Wait":\n        pass\nif torch: ...',
    },
    # ---------------- 500: Assets & Media ----------------
    "RPY501": {
        "title": "Missing audio file",
        "severity": "ERROR",
        "tags": ["assets", "audio"],
        "why": "Audio file referenced in play/queue music/sound/voice does not exist on disk, in 'audio/', or inside .rpa archives.",
        "bad": 'play music "bgm/missing_track.ogg"',
        "good": 'play music "bgm/existing_track.ogg"',
    },
    "RPY502": {
        "title": "Missing or mistyped sprite / background",
        "severity": "WARNING",
        "tags": ["assets", "images"],
        "why": "Sprite pose or background shown via 'show' or 'scene' is missing from image declarations, layered images, and asset folders.",
        "bad": "show sayori 99z_crazy_pose",
        "good": "show sayori 1a",
    },
    "RPY503": {
        "title": "Unused media asset on disk",
        "severity": "WARNING",
        "tags": ["assets", "dead-code"],
        "why": "Image or audio files located in the project directory are never referenced in any script. Increases build distribution size.",
        "bad": "# File 'game/images/unused_background.png' exists on disk but is never shown",
        "good": "# Show the asset in script or remove unused file from project",
    },
    "RPY504": {
        "title": "Duplicate / overridden image declaration",
        "severity": "WARNING",
        "tags": ["assets", "images"],
        "why": "Declaring the same image tag twice (via 'image name = ...' or 'image name:') silently overrides the previous definition.",
        "bad": 'image bg room = "day.png"\nimage bg room = "night.png"  # Silently overrides daytime room!',
        "good": 'image bg room_day = "day.png"\nimage bg room_night = "night.png"',
    },
    "RPY505": {
        "title": "Unregistered audio channel or voice loop",
        "severity": "WARNING",
        "tags": ["assets", "audio"],
        "why": "Playing audio on a channel not registered via renpy.music.register_channel() causes a runtime Exception. Looping the voice channel causes audio overlap glitches.",
        "bad": 'play ambient "rain.ogg"\nplay voice "clip.ogg" loop',
        "good": 'init python:\n    renpy.music.register_channel("ambient", mixer="sfx", loop=True)\nplay ambient "rain.ogg"',
    },
    # ---------------- 600: Translations & Localization ----------------
    "RPY601": {
        "title": "Variable mismatch in translation string",
        "severity": "ERROR",
        "tags": ["translations", "variables"],
        "why": "If a translated string alters or misspells a dialogue variable ([var]), rendering the translation causes a fatal KeyError at runtime.",
        "bad": 'old "Hello, [player_name]!"\nnew "Привет, [player]!"  # Typo in variable name!',
        "good": 'old "Hello, [player_name]!"\nnew "Привет, [player_name]!"',
    },
    "RPY602": {
        "title": "Formatting tag mismatch in translation string",
        "severity": "WARNING",
        "tags": ["translations", "text-tags"],
        "why": "Missing or altered formatting tags ({b}, {color}, {i}) in translation strings cause unclosed text tags and visual glitches.",
        "bad": 'old "Danger: {b}Hazard!{/b}"\nnew "Опасно: {b}Угроза!"  # Missing closing tag {/b}',
        "good": 'old "Danger: {b}Hazard!{/b}"\nnew "Опасно: {b}Угроза!{/b}"',
    },
    "RPY603": {
        "title": "Empty translation string ('new \"\"')",
        "severity": "WARNING",
        "tags": ["translations"],
        "why": "Leaving 'new \"\"' empty for a non-empty original line will display an empty, blank dialogue window to players in that language.",
        "bad": 'old "Do you want to exit?"\nnew ""  # Player sees empty dialogue box!',
        "good": 'old "Do you want to exit?"\nnew "Вы хотите выйти?"',
    },
    # 7xx: Dead Code Detection
    "RPY701": {
        "title": "Unused define constant",
        "severity": "HINT",
        "tags": ["dead-code", "variables"],
        "why": "A 'define' constant that is never referenced anywhere in the project is dead code. It increases cognitive load and should be removed.",
        "bad": "define unused_const = 100\nlabel start:\n    return",
        "good": "define used_const = 100\nlabel start:\n    $ x = used_const\n    return",
    },
    "RPY702": {
        "title": "Unused transform",
        "severity": "HINT",
        "tags": ["dead-code", "transforms"],
        "why": "A 'transform' that is never used in 'show/scene at' is dead code. It may indicate a forgotten animation or leftover from refactoring.",
        "bad": "transform unused_slide:\n    easein 0.5 xoffset 0\nlabel start:\n    return",
        "good": "transform slide_in:\n    easein 0.5 xoffset 0\nlabel start:\n    show bg at slide_in\n    return",
    },
    "RPY703": {
        "title": "Unused screen",
        "severity": "HINT",
        "tags": ["dead-code", "screen"],
        "why": "A 'screen' that is never called via 'call screen', 'use', or 'Show' action is dead code. It may indicate a forgotten UI element or leftover from refactoring.",
        "bad": 'screen unused_screen():\n    textbutton "Do nothing" action NullAction()\nlabel start:\n    return',
        "good": 'screen my_screen():\n    textbutton "Start" action Start()\nlabel start:\n    call screen my_screen\n    return',
    },
    "RPY704": {
        "title": "Unused default variable",
        "severity": "HINT",
        "tags": ["dead-code", "variables"],
        "why": "A 'default' variable that is never referenced anywhere in the project is dead code. Unlike 'define' constants (RPY701), 'default' variables persist across saves — an unused one wastes save-file space and increases cognitive load.",
        "bad": "default unused_var = 0\nlabel start:\n    return",
        "good": "default player_gold = 100\nlabel start:\n    $ player_gold -= 10\n    return",
    },
    "RPY705": {
        "title": "Unused screen parameter",
        "severity": "HINT",
        "tags": ["dead-code", "screen"],
        "why": "A parameter declared in `screen name(unused_param):` but never referenced in the screen body is dead code. It clutters the signature and suggests a forgotten refactor (parameter was once used, then the code was removed). Prefix with '_' (e.g. `_unused`) to suppress intentionally-unused params.",
        "bad": 'screen shop(unused_currency):\n    text "Welcome"',
        "good": 'screen shop(currency):\n    text "Gold: [currency]"',
    },
    "RPY706": {
        "title": "Unused transform parameter",
        "severity": "HINT",
        "tags": ["dead-code", "transforms"],
        "why": "A parameter declared in `transform slide(unused_speed):` but never referenced in the transform body is dead code. Same rationale as RPY705 — cluttered signature, forgotten refactor. Prefix with '_' to suppress.",
        "bad": "transform slide_in(unused_speed):\n    easein 0.5 xoffset 0",
        "good": "transform slide_in(speed):\n    easein speed xoffset 0",
    },
    "RPY707": {
        "title": "Unused audio channel registration",
        "severity": "HINT",
        "tags": ["dead-code", "audio"],
        "why": 'A channel registered via `renpy.music.register_channel("name", ...)` but never used in any `play`/`queue`/`stop` statement is dead code. The registration runs at init time and has no effect if nothing plays on the channel. Remove the registration or use the channel.',
        "bad": 'init python:\n    renpy.music.register_channel("ambient", mixer="sfx", loop=True)\nlabel start:\n    "No audio played on ambient channel."\n    return',
        "good": 'init python:\n    renpy.music.register_channel("ambient", mixer="sfx", loop=True)\nlabel start:\n    play ambient "rain.ogg"\n    return',
    },
    "RPY801": {
        "title": "Duplicate translation string",
        "severity": "WARNING",
        "tags": ["translations", "dead-code"],
        "why": "If the same `old` source string appears more than once in a translation file, the second translation silently overrides the first. The first translation is dead code — translators wasted effort, and the override may be unintentional. Common copy-paste error when duplicating translation blocks.",
        "bad": 'translate russian chapter1_a1b2:\n    old "Hello"\n    new "Privet"\n\ntranslate russian chapter1_c3d4:\n    old "Hello"\n    new "Zdravstvuy"  # overrides "Privet" silently',
        "good": 'translate russian chapter1_a1b2:\n    old "Hello"\n    new "Privet"\n\ntranslate russian chapter1_c3d4:\n    old "Goodbye"\n    new "Poka"  # different source, no conflict',
    },
    "RPY802": {
        "title": "Inconsistent translation across files in same language",
        "severity": "WARNING",
        "tags": ["translations", "io"],
        "why": "The same source string is translated to DIFFERENT new strings in different files within the SAME language directory. This confuses players (same line shows different text in different scenes) and breaks translation memory tools. Pick one translation and use it consistently.",
        "bad": 'game/tl/russian/common.rpy:\n    old "Hello"\n    new "Privet"\n\ngame/tl/russian/dialogue.rpy:\n    old "Hello"\n    new "Zdravstvuy"  # inconsistent!',
        "good": 'game/tl/russian/common.rpy:\n    old "Hello"\n    new "Privet"\n\ngame/tl/russian/dialogue.rpy:\n    old "Hello"\n    new "Privet"  # consistent across files',
    },
}


def show_rules_table():
    # Dynamic count of rules. Previously the number was hardcoded
    # in the title — this got out of sync with RULES_DATABASE when new
    # rules were added. Now the number is pulled from the dict itself,
    # which we iterate over.
    table = Table(
        title=f"Senpy Linter Rules Reference (All {len(RULES_DATABASE)} Rules)",
        border_style="dim",
    )
    table.add_column("Rule", style="bold cyan")
    table.add_column("Severity", justify="center")
    table.add_column("Tags", style="dim")
    table.add_column("Description", style="bright_white")

    for code, info in sorted(RULES_DATABASE.items()):
        sev_style = (
            "bold red"
            if info["severity"] == "ERROR"
            else "bold yellow"
            if info["severity"] == "WARNING"
            else "bold blue"
        )
        tags_str = ", ".join(info.get("tags", []))
        table.add_row(
            code,
            f"[{sev_style}]{info['severity']}[/{sev_style}]",
            tags_str,
            info["title"],
        )

    console.print(table)
    console.print(
        "\n[dim]Run 'senpy --rule <CODE>' (e.g. 'senpy --rule RPY107') for detailed explanation and examples.[/dim]\n"
    )


def show_rule_detail(code: str):
    if code not in RULES_DATABASE:
        console.print(
            f"[bold red]Unknown rule code:[/bold red] '{code}'. Run 'senpy --rules' to see all available rules."
        )
        return

    info = RULES_DATABASE[code]
    sev_style = (
        "bold red"
        if info["severity"] == "ERROR"
        else "bold yellow"
        if info["severity"] == "WARNING"
        else "bold blue"
    )

    text = Text()
    text.append(f"{code}: {info['title']}\n", style="bold cyan")
    text.append(f"Severity: {info['severity']}\n", style=sev_style)
    tags = info.get("tags", [])
    if tags:
        text.append(f"Tags: {', '.join(tags)}\n\n", style="dim")
    else:
        text.append("\n", style="dim")
    text.append(f"{info['why']}\n\n", style="bright_white")

    text.append("❌ BAD PRACTICE:\n", style="bold red")
    text.append(f"{info['bad']}\n\n", style="dim red")

    text.append("✔ GOOD PRACTICE:\n", style="bold green")
    text.append(f"{info['good']}\n", style="bright_green")

    console.print(Panel(text, title=f"Rule {code}", border_style="cyan", expand=False))
