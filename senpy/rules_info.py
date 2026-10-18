from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

RULES_DATABASE = {
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
    "RPY201": {
        "title": "Direct state mutation inside screen",
        "severity": "WARNING",
        "why": "Screens are evaluated continuously and predictively by the UI loop. Direct state mutations run repeatedly every frame and break rollback.",
        "bad": "screen shop():\n    $ player_gold -= 10  # Runs every frame!",
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
        "why": "Label is declared but never called or jumped to anywhere in the project. It might be dead code or forgotten draft.",
        "bad": "label forgotten_draft:\n    'Old scene never reached...'",
        "good": "# Connect to story flow with jump/call or remove",
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
        "why": "Quotes inside a dialogue string without escaping (\\\") break the string literal parser at startup.",
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
    "RPY501": {
        "title": "Missing audio file",
        "severity": "ERROR",
        "why": "Audio file referenced in play music/sound/voice does not exist on disk or inside .rpa archives.",
        "bad": 'play music "bgm/missing_track.ogg"',
        "good": 'play music "bgm/existing_track.ogg"',
    },
    "RPY502": {
        "title": "Missing or mistyped sprite / background",
        "severity": "WARNING",
        "why": "Sprite pose or background shown via 'show' or 'scene' is missing from image declarations and asset folders.",
        "bad": "show sayori 99z_crazy_pose",
        "good": "show sayori 1a",
    },
    "RPY504": {
        "title": "Duplicate image declaration",
        "severity": "ERROR",
        "why": "Declaring the same image tag twice (via 'image name = ...' or 'image name:') causes one definition to silently overwrite the other.",
        "bad": 'image bg room = "day.png"\nimage bg room = "night.png"',
        "good": 'image bg room_day = "day.png"\nimage bg room_night = "night.png"',
    },
}


def show_rules_table():
    table = Table(title="Senpy Linter Rules Reference", border_style="dim")
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
        "\n[dim]Run 'senpy --rule <CODE>' (e.g. 'senpy --rule RPY104') for detailed explanation and examples.[/dim]\n"
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