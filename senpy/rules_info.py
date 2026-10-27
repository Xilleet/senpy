from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

RULES_DATABASE = {
    # ---------------- 000: Indentation & Code Formatting ----------------
    "RPY001": {
        "title": "Tab character in indentation",
        "severity": "ERROR",
        "why": "Ren'Py requires 4 spaces per indentation level. Tab characters ('\\t') cause indentation mismatches and SyntaxError across different editors and operating systems.",
        "bad": 'label start:\n\t"Tab character used here!"',
        "good": 'label start:\n    "Standard 4 spaces used here."',
    },
    "RPY002": {
        "title": "Smart/curly quotes in code statement",
        "severity": "ERROR",
        "why": "Typographic smart quotes (“ ” ‘ ’ « ») copied from text editors like MS Word into Python code statements cause a fatal SyntaxError.",
        "bad": "$ status = “active”\nif item == «key»: ...",
        "good": '$ status = "active"\nif item == "key": ...',
    },
    # ---------------- 100: Variables, Types & Rollback ----------------
    "RPY100": {
        "title": "File is not valid UTF-8",
        "severity": "ERROR",
        "why": "Ren'Py reads all .rpy scripts as UTF-8. A file saved in another encoding (e.g. Windows-1251) crashes the game on load. Senpy skips such files, so they must be re-saved as UTF-8.",
        "bad": "script.rpy saved in Windows-1251: bytes b'\\xcf\\xf0\\xe8\\xe2\\xe5\\xf2' instead of text",
        "good": "Re-save the file with UTF-8 encoding (VS Code: bottom-right status bar -> Save with Encoding -> UTF-8).",
    },
    "RPY101": {
        "title": "Unresolved variable in dialogue interpolation",
        "severity": "ERROR",
        "why": "Using [variable] in dialogue when it is not declared via 'default' or 'define' will crash the game with KeyError during text rendering.",
        "bad": '"Hello, [player_namme]!"  # Typo in variable name',
        "good": 'default player_name = "Eileen"\n"Hello, [player_name]!"',
    },
    "RPY102": {
        "title": "Augmented assignment before 'default' declaration",
        "severity": "ERROR",
        "why": "Doing +=, -=, etc. to a variable before it has been initialized causes an immediate runtime NameError when entering the scene.",
        "bad": "label start:\n    $ score += 10  # score does not exist yet!",
        "good": "default score = 0\nlabel start:\n    $ score += 10",
    },
    "RPY103": {
        "title": "Undeclared variable in condition",
        "severity": "ERROR",
        "why": "Evaluating 'if var:' or 'elif var:' crashes the engine with NameError if the variable was never declared.",
        "bad": "if has_key:\n    jump secret_room",
        "good": "default has_key = False\nlabel start:\n    if has_key:\n        jump secret_room",
    },
    "RPY104": {
        "title": "Dynamic assignment without top-level 'default'",
        "severity": "WARNING",
        "why": "Assigning variables on the fly ($ var = 1) without a top-level 'default' will corrupt save files upon game updates and cause NameError on other story branches.",
        "bad": "label chapter_2:\n    $ affection = 5  # No top-level default!",
        "good": "default affection = 0\nlabel chapter_2:\n    $ affection = 5",
    },
    "RPY105": {
        "title": "Direct mutation of 'define' constant",
        "severity": "ERROR",
        "why": "Variables declared with 'define' are static constants (characters, configurations). Modifying them breaks Ren'Py rollback and save persistence.",
        "bad": "define karma = 0\nlabel start:\n    $ karma += 1",
        "good": "default karma = 0  # Use default for mutable state!\nlabel start:\n    $ karma += 1",
    },
    "RPY106": {
        "title": "Usage of non-revertable Python types (random / mutable set)",
        "severity": "WARNING",
        "why": "Standard Python 'import random' and mutable 'set()' are not tracked by Ren'Py's rollback engine. Players rolling back will experience save desynchronization.",
        "bad": "import random\n$ inventory = set()",
        "good": "from renpy import random\n$ inventory = []  # or renpy.revertable_set()",
    },
    "RPY107": {
        "title": "Usage of deprecated / obsolete Ren'Py API",
        "severity": "WARNING",
        "why": "Calling obsolete Ren'Py functions (LiveComposite, DynamicCharacter, im.*, ui.*) harms rendering performance (CPU vs GPU) or breaks on Ren'Py 7/8.",
        "bad": 'image natsuki = LiveComposite((960, 960), (0, 0), "base.png")\ndefine c = DynamicCharacter("char_name")',
        "good": 'image natsuki = Composite((960, 960), (0, 0), "base.png")\ndefine c = Character("[char_name]")',
    },
    "RPY108": {
        "title": "Type taint conflict or incompatible augmented assignment",
        "severity": "ERROR",
        "why": "Assigning incompatible types (e.g. str to int) or performing operations like 'str += int' causes fatal runtime TypeErrors.",
        "bad": 'default player_name = "Eileen"\ndefault score = 0\nlabel start:\n    $ player_name += 1\n    $ score = "High"',
        "good": 'default player_name = "Eileen"\ndefault score = 0\nlabel start:\n    $ player_name += "!"\n    $ score = 100',
    },
    "RPY109": {
        "title": "Init phase dependency graph violation",
        "severity": "ERROR",
        "why": "Ren'Py loads files in alphabetical order. If 'a_file.rpy' calls a function in 'init python' that is defined in 'z_file.rpy', the game will crash on startup because 'z_file' hasn't loaded yet.",
        "bad": "# a_setup.rpy\ninit python:\n    setup_gui()  # Crashes!\n\n# z_helpers.rpy\ninit python:\n    def setup_gui(): ...",
        "good": "# a_helpers.rpy\ninit python:\n    def setup_gui(): ...\n\n# z_setup.rpy\ninit python:\n    setup_gui()",
    },
    # ---------------- 200: Screen Language & UI ----------------
    "RPY201": {
        "title": "Direct state mutation inside screen",
        "severity": "WARNING",
        "why": "Screens are evaluated continuously and predictively by the UI loop. Direct state mutations run repeatedly every frame and break rollback.",
        "bad": "screen shop():\n    $ player_gold -= 10  # Runs repeatedly during prediction!",
        "good": "screen shop():\n    textbutton 'Buy' action SetVariable('player_gold', player_gold - 10)",
    },
    "RPY202": {
        "title": "Screen accesses variable without 'default'",
        "severity": "WARNING",
        "why": "Screens can be evaluated before story start (e.g. in the main menu or prediction loop). Reading undeclared variables crashes the game.",
        "bad": "screen hud():\n    if show_quest_tracker: ...",
        "good": "default show_quest_tracker = False\nscreen hud():\n    if show_quest_tracker: ...",
    },
    "RPY203": {
        "title": "Button without 'action' argument",
        "severity": "WARNING",
        "why": "Buttons (textbutton, imagebutton) without an 'action' property are non-interactive dead UI elements.",
        "bad": 'textbutton "Confirm"  # Cannot be clicked!',
        "good": 'textbutton "Confirm" action Return()',
    },
    "RPY204": {
        "title": "Call/Show to non-existent screen",
        "severity": "ERROR",
        "why": "Calling or showing a screen that does not exist crashes the game with 'Exception: Screen is not known'.",
        "bad": "call screen inventory_menuu  # Typo!",
        "good": "call screen inventory_menu",
    },
    "RPY205": {
        "title": "Imperative Python loop inside screen",
        "severity": "WARNING",
        "why": "Writing imperative for/while loops in Python blocks inside screens severely hurts UI prediction and causes frame drops.",
        "bad": "screen inv():\n    python:\n        for item in items: ...",
        "good": "screen inv():\n    for item in items:\n        text item",
    },
    "RPY206": {
        "title": "Direct function call in button action",
        "severity": "ERROR",
        "why": "Directly calling a function with parentheses in action executes it immediately during screen render, not upon user click.",
        "bad": "textbutton 'Heal' action heal_player()  # Executes on screen show!",
        "good": "textbutton 'Heal' action Function(heal_player)  # Executes on click",
    },
    "RPY207": {
        "title": "Invalid arguments when showing or using a screen",
        "severity": "ERROR",
        "why": "Calling or using a screen with missing required parameters or unknown arguments causes a fatal runtime Exception.",
        "bad": "screen inv(sort_by):\n    ...\nuse inv()  # Missing required argument 'sort_by'!",
        "good": "screen inv(sort_by='name'):\n    ...\nuse inv()",
    },
    "RPY208": {
        "title": "Screen-local variable modified via global action or store mutation",
        "severity": "ERROR",
        "why": "Variables declared with 'default' inside a screen or screen parameters are screen-local. Using 'SetVariable' or '$ var = ...' modifies the global store instead of the screen variable, causing UI desynchronization and broken button interactions.",
        "bad": 'screen shop():\n    default selected_item = None\n    textbutton "Sword" action SetVariable("selected_item", "Sword")',
        "good": 'screen shop():\n    default selected_item = None\n    textbutton "Sword" action SetScreenVariable("selected_item", "Sword")',
    },
    # ---------------- 300: Dialogue & Control Flow ----------------
    "RPY301": {
        "title": "Unclosed or mismatched text tag in dialogue",
        "severity": "ERROR",
        "why": "Unclosed tags like {b} will bleed styles into all subsequent dialogues across the entire game.",
        "bad": '"Danger: {b}Hazardous area!"',
        "good": '"Danger: {b}Hazardous area!{/b}"',
    },
    "RPY302": {
        "title": "Jump or Call to non-existent label",
        "severity": "ERROR",
        "why": "Jumping to a label that does not exist immediately terminates the novel with ScriptError.",
        "bad": "jump bad_edd  # Typo",
        "good": "jump bad_end",
    },
    "RPY303": {
        "title": "Unreferenced / Dead label",
        "severity": "INFO",
        "why": "Label is declared but never called or jumped to anywhere in the project. It might be dead code or a forgotten draft.",
        "bad": "label forgotten_draft:\n    'Old scene never reached...'",
        "good": "# Connect to story flow with jump/call or remove dead script",
    },
    "RPY304": {
        "title": "Malformed color in {color} tag",
        "severity": "ERROR",
        "why": "Typo in hex code (e.g. #12345) or unknown color name causes the Ren'Py text renderer to crash.",
        "bad": '"{color=#12345}Text{/color}"',
        "good": '"{color=#123456}Text{/color}"',
    },
    "RPY305": {
        "title": "Unescaped quotes inside dialogue string",
        "severity": "ERROR",
        "why": 'Quotes inside a dialogue string without escaping (\\") break the string literal parser at startup.',
        "bad": '"She said "Hello" and smiled."',
        "good": '"She said \\"Hello\\" and smiled."',
    },
    "RPY306": {
        "title": "Called label without 'return' statement",
        "severity": "WARNING",
        "why": "Invoking a label via 'call' expects a 'return'. Without it, control flow accidentally bleeds into unrelated scenes.",
        "bad": "label sub_scene:\n    'Dialogue...'\n    # Missing return!",
        "good": "label sub_scene:\n    'Dialogue...'\n    return",
    },
    "RPY307": {
        "title": "Duplicate label declaration",
        "severity": "ERROR",
        "why": "Declaring two labels with the same name across any project script causes a fatal ScriptError on startup.",
        "bad": "label chapter_1:\n    ...\nlabel chapter_1:  # Duplicate!\n    ...",
        "good": "label chapter_1:\n    ...\nlabel chapter_2:\n    ...",
    },
    "RPY308": {
        "title": "Label preceded by regular statements (Fallthrough hazard)",
        "severity": "WARNING",
        "why": "Ending a scene without 'jump' or 'return' before the next label causes control flow to unintentionally fall right through into the next scene.",
        "bad": 'label scene_a:\n    "End of scene A."\nlabel scene_b:\n    "Scene B starts immediately!"',
        "good": 'label scene_a:\n    "End of scene A."\n    return\nlabel scene_b:\n    "Scene B starts!"',
    },
    "RPY309": {
        "title": "Story island / isolated subgraph unreachable from 'start'",
        "severity": "WARNING",
        "why": "A group of scenes references each other in a loop, but no entry point exists from 'start', 'splashscreen', or main menus. This represents unreachable dead content or orphaned story routes.",
        "bad": "label route_a:\n    jump route_b\nlabel route_b:\n    jump route_a",
        "good": "# Connect route to story flow via jump or call from start",
    },
    "RPY310": {
        "title": "Invalid argument count or keyword in 'call' statement",
        "severity": "ERROR",
        "why": "Calling a label with too few, too many, or unknown keyword arguments crashes the game with an immediate TypeError.",
        "bad": "label forest(time, weather):\n    ...\ncall forest('day')  # Missing 'weather' argument!",
        "good": "label forest(time, weather='sunny'):\n    ...\ncall forest('day')",
    },
    # ---------------- 400: Branching & Conditions ----------------
    "RPY401": {
        "title": "Variable defined in one menu choice but missing in another",
        "severity": "WARNING",
        "why": "If Choice A defines a variable but Choice B does not, choosing Choice B and later reading the variable causes a fatal NameError.",
        "bad": 'menu:\n    "Take torch":\n        $ torch = True\n    "Walk in dark":\n        pass\nif torch: ...  # Crashes if dark was chosen!',
        "good": 'default torch = False\nmenu:\n    "Take torch":\n        $ torch = True\n    "Walk in dark":\n        pass',
    },
    "RPY402": {
        "title": "Empty menu choice",
        "severity": "WARNING",
        "why": "A menu choice was defined without any body statements, causing the story to immediately fall through.",
        "bad": 'menu:\n    "Give up":\n    "Fight":\n        "Battle!"',
        "good": 'menu:\n    "Give up":\n        return\n    "Fight":\n        "Battle!"',
    },
    "RPY403": {
        "title": "Always-false or contradictory condition",
        "severity": "WARNING",
        "why": "Conditions like 'if False:' or 'if x and not x:' can never be true. The code block will never execute.",
        "bad": "if False:\n    'This story branch is dead.'",
        "good": "if has_secret_item:\n    'Secret branch!'",
    },
    "RPY404": {
        "title": "Variable in MAYBE_SET state evaluated after menu branch",
        "severity": "WARNING",
        "why": "If a variable is only defined in one choice of a menu, choosing an alternate path and subsequently evaluating the variable or interpolating it will crash with NameError or KeyError.",
        "bad": 'menu:\n    "Take torch":\n        $ torch = True\n    "Wait":\n        pass\nif torch: ...',
        "good": 'default torch = False\nmenu:\n    "Take torch":\n        $ torch = True\n    "Wait":\n        pass\nif torch: ...',
    },
    # ---------------- 500: Assets & Media ----------------
    "RPY501": {
        "title": "Missing audio file",
        "severity": "ERROR",
        "why": "Audio file referenced in play/queue music/sound/voice does not exist on disk, in 'audio/', or inside .rpa archives.",
        "bad": 'play music "bgm/missing_track.ogg"',
        "good": 'play music "bgm/existing_track.ogg"',
    },
    "RPY502": {
        "title": "Missing or mistyped sprite / background",
        "severity": "WARNING",
        "why": "Sprite pose or background shown via 'show' or 'scene' is missing from image declarations, layered images, and asset folders.",
        "bad": "show sayori 99z_crazy_pose",
        "good": "show sayori 1a",
    },
    "RPY503": {
        "title": "Unused media asset on disk",
        "severity": "WARNING",
        "why": "Image or audio files located in the project directory are never referenced in any script. Increases build distribution size.",
        "bad": "# File 'game/images/unused_background.png' exists on disk but is never shown",
        "good": "# Show the asset in script or remove unused file from project",
    },
    "RPY504": {
        "title": "Duplicate / overridden image declaration",
        "severity": "WARNING",
        "why": "Declaring the same image tag twice (via 'image name = ...' or 'image name:') silently overrides the previous definition.",
        "bad": 'image bg room = "day.png"\nimage bg room = "night.png"  # Silently overrides daytime room!',
        "good": 'image bg room_day = "day.png"\nimage bg room_night = "night.png"',
    },
    "RPY505": {
        "title": "Unregistered audio channel or voice loop",
        "severity": "WARNING",
        "why": "Playing audio on a channel not registered via renpy.music.register_channel() causes a runtime Exception. Looping the voice channel causes audio overlap glitches.",
        "bad": 'play ambient "rain.ogg"\nplay voice "clip.ogg" loop',
        "good": 'init python:\n    renpy.music.register_channel("ambient", mixer="sfx", loop=True)\nplay ambient "rain.ogg"',
    },
    # ---------------- 600: Translations & Localization ----------------
    "RPY601": {
        "title": "Variable mismatch in translation string",
        "severity": "ERROR",
        "why": "If a translated string alters or misspells a dialogue variable ([var]), rendering the translation causes a fatal KeyError at runtime.",
        "bad": 'old "Hello, [player_name]!"\nnew "Привет, [player]!"  # Typo in variable name!',
        "good": 'old "Hello, [player_name]!"\nnew "Привет, [player_name]!"',
    },
    "RPY602": {
        "title": "Formatting tag mismatch in translation string",
        "severity": "WARNING",
        "why": "Missing or altered formatting tags ({b}, {color}, {i}) in translation strings cause unclosed text tags and visual glitches.",
        "bad": 'old "Danger: {b}Hazard!{/b}"\nnew "Опасно: {b}Угроза!"  # Missing closing tag {/b}',
        "good": 'old "Danger: {b}Hazard!{/b}"\nnew "Опасно: {b}Угроза!{/b}"',
    },
    "RPY603": {
        "title": "Empty translation string ('new \"\"')",
        "severity": "WARNING",
        "why": "Leaving 'new \"\"' empty for a non-empty original line will display an empty, blank dialogue window to players in that language.",
        "bad": 'old "Do you want to exit?"\nnew ""  # Player sees empty dialogue box!',
        "good": 'old "Do you want to exit?"\nnew "Вы хотите выйти?"',
    },
}


def show_rules_table():
    table = Table(title="Senpy Linter Rules Reference (All 40 Rules)", border_style="dim")
    table.add_column("Rule", style="bold cyan")
    table.add_column("Severity", justify="center")
    table.add_column("Description", style="bright_white")

    for code, info in sorted(RULES_DATABASE.items()):
        sev_style = (
            "bold red"
            if info["severity"] == "ERROR"
            else "bold yellow"
            if info["severity"] == "WARNING"
            else "bold blue"
        )
        table.add_row(code, f"[{sev_style}]{info['severity']}[/{sev_style}]", info["title"])

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
    text.append(f"Severity: {info['severity']}\n\n", style=sev_style)
    text.append(f"{info['why']}\n\n", style="bright_white")

    text.append("❌ BAD PRACTICE:\n", style="bold red")
    text.append(f"{info['bad']}\n\n", style="dim red")

    text.append("✔ GOOD PRACTICE:\n", style="bold green")
    text.append(f"{info['good']}\n", style="bright_green")

    console.print(Panel(text, title=f"Rule {code}", border_style="cyan", expand=False))
