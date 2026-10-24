# Senpy Rules

Comprehensive guide to all semantic and static rules implemented in the **Senpy** Ren'Py linter.

---

### Navigation
- **Indentation & Code (RPY0xx)**: [RPY001](#rpy001) | [RPY002](#rpy002)
- **Variables & State (RPY1xx)**: [RPY101](#rpy101) | [RPY102](#rpy102) | [RPY103](#rpy103) | [RPY104](#rpy104) | [RPY105](#rpy105) | [RPY106](#rpy106) | [RPY107](#rpy107) | [RPY108](#rpy108) | [RPY109](#rpy109)
- **Screens & UI (RPY2xx)**: [RPY201](#rpy201) | [RPY202](#rpy202) | [RPY203](#rpy203) | [RPY204](#rpy204) | [RPY205](#rpy205) | [RPY206](#rpy206) | [RPY207](#rpy207)
- **Story Flow & Dialogue (RPY3xx)**: [RPY301](#rpy301) | [RPY302](#rpy302) | [RPY303](#rpy303) | [RPY304](#rpy304) | [RPY305](#rpy305) | [RPY306](#rpy306) | [RPY307](#rpy307) | [RPY308](#rpy308) | [RPY309](#rpy309) | [RPY310](#rpy310)
- **Branching & Conditions (RPY4xx)**: [RPY401](#rpy401) | [RPY402](#rpy402) | [RPY403](#rpy403) | [RPY404](#rpy404)
- **Assets & Media (RPY5xx)**: [RPY501](#rpy501) | [RPY502](#rpy502) | [RPY503](#rpy503) | [RPY504](#rpy504) | [RPY505](#rpy505)
- **Translations & Localization (RPY6xx)**: [RPY601](#rpy601) | [RPY602](#rpy602) | [RPY603](#rpy603)

---

## Indentation and Syntax (RPY0xx)

<a id="rpy001"></a>
### RPY001: Tab character in indentation
- **Severity**: `ERROR`
- **Why**: Ren'Py requires 4 spaces per indentation level. Tab characters (`\t`) cause indentation mismatches and `SyntaxError` across different text editors and operating systems.
- **Tip**: Fixable automatically with `--fix` or via Quick Fix (`Ctrl+.`).

```renpy
# Bad
label start:
	"Tab character used here!"

# Good
label start:
    "Standard 4 spaces used here."
```

---

<a id="rpy002"></a>
### RPY002: Smart/curly quotes in code statement
- **Severity**: `ERROR`
- **Why**: Typographic smart quotes (“ ” ‘ ’ « ») copied from text editors like MS Word into Python code statements break Python's lexical parser, causing a fatal `SyntaxError`.
- **Tip**: Fixable automatically with `--fix` or via Quick Fix (`Ctrl+.`).

```renpy
# Bad
$ status = “active”
if item == «key»: ...

# Good
$ status = "active"
if item == "key": ...
```

---

## Variables and State (RPY1xx)

<a id="rpy101"></a>
### RPY101: Unresolved variable in dialogue interpolation
- **Severity**: `ERROR`
- **Why**: Using `[var]` inside dialogue text when `var` is not declared via `default` or `define` crashes the game with a runtime `KeyError`.

```renpy
# Bad
"Hello, [player_namme]!"

# Good
default player_name = "Eileen"
"Hello, [player_name]!"
```

---

<a id="rpy102"></a>
### RPY102: Augmented assignment before declaration
- **Severity**: `ERROR`
- **Why**: Executing `+=`, `-=`, etc. before the variable exists causes an immediate runtime `NameError`.

```renpy
# Bad
label start:
    $ score += 10

# Good
default score = 0
label start:
    $ score += 10
```

---

<a id="rpy103"></a>
### RPY103: Undeclared variable in condition
- **Severity**: `ERROR`
- **Why**: Evaluating `if var:` will crash with `NameError` if `var` was never declared.

```renpy
# Bad
if has_key:
    jump secret_room

# Good
default has_key = False
label start:
    if has_key:
        jump secret_room
```

---

<a id="rpy104"></a>
### RPY104: Dynamic assignment without top-level 'default'
- **Severity**: `WARNING`
- **Why**: Creating variables on the fly (`$ var = 1`) without `default` breaks save-game portability across updates and triggers `NameError` on alternate story routes.
- **Tip**: Fix all occurrences automatically using `senpy --generate-defaults`.

```renpy
# Bad
label chapter_2:
    $ affection = 5

# Good
default affection = 0
label chapter_2:
    $ affection = 5
```

---

<a id="rpy105"></a>
### RPY105: Direct mutation of 'define' constant
- **Severity**: `ERROR`
- **Why**: `define` is strictly for constants (Characters, configurations). Reassigning them breaks Ren'Py rollback and save serialization.

```renpy
# Bad
define karma = 0
label start:
    $ karma += 1

# Good
default karma = 0  # Use default for mutable variables!
label start:
    $ karma += 1
```

---

<a id="rpy106"></a>
### RPY106: Usage of non-revertable Python types
- **Severity**: `WARNING`
- **Why**: Standard `import random` and Python's mutable `set()` are not tracked by Ren'Py's rollback engine, corrupting saves.

```renpy
# Bad
import random
$ inventory = set()

# Good
from renpy import random
$ inventory = []  # or renpy.revertable_set()
```

---

<a id="rpy107"></a>
### RPY107: Usage of deprecated / obsolete Ren'Py API
- **Severity**: `WARNING`
- **Why**: Calling obsolete Ren'Py functions (`LiveComposite`, `DynamicCharacter`, `im.*`, `ui.*`) harms rendering performance (CPU vs GPU) or breaks compatibility on Ren'Py 7/8.
- **Tip**: Fixable automatically via Quick Fix (`Ctrl+.`).

```renpy
# Bad
image natsuki mouth = LiveComposite((960, 960), (0, 0), "base.png")
define c = DynamicCharacter("char_name")

# Good
image natsuki mouth = Composite((960, 960), (0, 0), "base.png")
define c = Character("[char_name]")
```

---

<a id="rpy108"></a>
### RPY108: Type taint conflict or incompatible augmented assignment
- **Severity**: `ERROR` (for invalid `+=`) / `WARNING` (for type overwrites)
- **Why**: Reassigning incompatible types (e.g. `int` variable reassigned to `str`) or performing illegal augmented operations (e.g. `$ str_var += 1`) causes fatal runtime `TypeError`.

```renpy
# Bad
default score = 0
default player_name = "Eileen"
label start:
    $ player_name += 1       # Fatal TypeError: can only concatenate str to str!
    $ score = "High"         # Type taint: breaks subsequent numerical comparisons!

# Good
default score = 0
default player_name = "Eileen"
label start:
    $ player_name += "!"
    $ score = 100
```

---

a id="rpy109"></a>
RPY109: Init phase dependency graph violation
Severity: ERROR
Why: Ren'Py loads scripts in ascending alphabetical order of filenames during initialization. Evaluating functions or classes in a.rpy that are defined in z.rpy inside init python: causes an immediate crash with NameError on startup.

```renpy
# Bad
# game/a_setup.rpy
init python:
    configure_interface()   # Crashes with NameError: 'configure_interface' is not defined!

# game/z_helpers.rpy
init python:
    def configure_interface(): ...

# Good
# game/a_helpers.rpy
init python:
    def configure_interface(): ...

# game/z_setup.rpy
init python:
    configure_interface()
```

---

## Screens and UI (RPY2xx)

<a id="rpy201"></a>
### RPY201: Direct state mutation inside screen
- **Severity**: `WARNING`
- **Why**: Screens are evaluated continuously by Ren'Py's UI prediction. Direct Python mutations (`$ var += 1`) execute multiple times every frame and break rollback.

```renpy
# Bad
screen shop():
    $ player_gold -= 10

# Good
screen shop():
    textbutton "Buy" action SetVariable("player_gold", player_gold - 10)
```

---

<a id="rpy202"></a>
### RPY202: Screen accesses variable without 'default'
- **Severity**: `WARNING`
- **Why**: Screens can be evaluated before story start (e.g. in the main menu). Reading uninitialized variables crashes the engine.

```renpy
# Bad
screen hud():
    if show_tracker:
        text "Active"

# Good
default show_tracker = False
screen hud():
    if show_tracker:
        text "Active"
```

---

<a id="rpy203"></a>
### RPY203: Button without 'action'
- **Severity**: `WARNING`
- **Why**: Buttons without an `action` argument are dead UI elements that cannot be clicked.

```renpy
# Bad
textbutton "Confirm"

# Good
textbutton "Confirm" action Return()
```

---

<a id="rpy204"></a>
### RPY204: Call/Show to non-existent screen
- **Severity**: `ERROR`
- **Why**: Displaying or calling an undeclared screen terminates the game with `Exception: Screen is not known`.

```renpy
# Bad
call screen inventory_menuu

# Good
call screen inventory_menu
```

---

<a id="rpy205"></a>
### RPY205: Imperative Python loop inside screen
- **Severity**: `WARNING`
- **Why**: Python loops inside screens severely hurt UI prediction performance and cause frame drops.

```renpy
# Bad
screen inv():
    python:
        for item in items:
            pass

# Good
screen inv():
    for item in items:
        text item
```

---

<a id="rpy206"></a>
### RPY206: Direct function call in button action
- **Severity**: `ERROR`
- **Why**: Calling a function with parentheses `action heal_player()` executes it immediately during screen rendering and UI prediction, NOT upon user click.
- **Tip**: Fixable automatically via Quick Fix (`Ctrl+.`).

```renpy
# Bad
textbutton "Heal" action heal_player()

# Good
textbutton "Heal" action Function(heal_player)
```

---

<a id="rpy207"></a>
### RPY207: Invalid parameters in screen call / use
- **Severity**: `ERROR`
- **Why**: Passing missing required parameters or unknown keyword arguments to `use screen` or `call screen` causes a fatal runtime `Exception`.

```renpy
# Bad
screen inventory(category, sort_by="name"):
    ...

# Calling without required 'category' argument:
use inventory()

# Good
use inventory("weapons")
```

## Story Flow and Tags (RPY3xx)

<a id="rpy301"></a>
### RPY301: Unclosed text tag in dialogue
- **Severity**: `ERROR`
- **Why**: Unclosed tags like `{b}` or `{color}` bleed formatting into all subsequent lines of dialogue across the entire novel.
- **Tip**: Fixable automatically with `--fix` or via Quick Fix (`Ctrl+.`).

```renpy
# Bad
"Warning: {b}Hazardous area!"

# Good
"Warning: {b}Hazardous area!{/b}"
```

---

<a id="rpy302"></a>
### RPY302: Jump or Call to non-existent label
- **Severity**: `ERROR`
- **Why**: Jumping to a missing label terminates the novel with a `ScriptError`.
- **Tip**: Quick Fix (`Ctrl+.`) will suggest similar label names if a typo is detected.

```renpy
# Bad
jump bad_edd

# Good
jump bad_end
```

---

<a id="rpy303"></a>
### RPY303: Unreferenced / Dead label
- **Severity**: `INFO`
- **Why**: Label is declared but never referenced by any `jump` or `call`. It may be unreachable dead code or an abandoned draft.

```renpy
# Bad
label forgotten_draft:
    "Old scene never reached..."

# Good
# Connect with jump/call or remove dead script
```

---

<a id="rpy304"></a>
### RPY304: Malformed color in {color} tag
- **Severity**: `ERROR`
- **Why**: Invalid hex codes (e.g. `#12345`) or unknown color names crash the Ren'Py text renderer.

```renpy
# Bad
"{color=#12345}Text{/color}"

# Good
"{color=#123456}Text{/color}"
```

---

<a id="rpy305"></a>
### RPY305: Unescaped quotes inside dialogue
- **Severity**: `ERROR`
- **Why**: Quotes inside a dialogue string without escaping (`\"`) break Ren'Py's script parser during game initialization.

```renpy
# Bad
"She said "Hello" and smiled."

# Good
"She said \"Hello\" and smiled."
```

---

<a id="rpy306"></a>
### RPY306: Called label without 'return'
- **Severity**: `WARNING`
- **Why**: When a label is called via `call`, execution expects a `return`. Without it, control flow accidentally bleeds into unrelated scenes.

```renpy
# Bad
label sub_scene:
    "Dialogue..."

# Good
label sub_scene:
    "Dialogue..."
    return
```

---

<a id="rpy307"></a>
### RPY307: Duplicate label declaration
- **Severity**: `ERROR`
- **Why**: Declaring two labels with the exact same name across any project script causes a fatal `ScriptError` on startup.

```renpy
# Bad
label chapter_1:
    ...
label chapter_1:  # Duplicate label!
    ...

# Good
label chapter_1:
    ...
label chapter_2:
    ...
```

---

<a id="rpy308"></a>
### RPY308: Label preceded by regular statements (Fallthrough hazard)
- **Severity**: `WARNING`
- **Why**: Ending a scene without `jump` or `return` before the next label causes control flow to unintentionally fall right through into the next scene.

```renpy
# Bad
label scene_a:
    "End of scene A."
label scene_b:
    "Scene B starts immediately!"

# Good
label scene_a:
    "End of scene A."
    return
label scene_b:
    "Scene B starts!"
```

---

<a id="rpy309"></a>
### RPY309: Story island / isolated subgraph unreachable from 'start'
- **Severity**: `WARNING`
- **Why**: A group of scenes or labels references each other in a loop, but no entry point exists from `start`, `splashscreen`, or main menus. This represents unreachable dead content or orphaned story routes.

```renpy
# Bad: Loops into each other, but unreachable from start!
label route_draft_a:
    "Draft scene A"
    jump route_draft_b

label route_draft_b:
    "Draft scene B"
    jump route_draft_a

# Good: Connect route to story flow via jump/call
```

---

<a id="rpy310"></a>
RPY310: Invalid argument count or keyword in 'call' statement
Severity: ERROR
Why: Invoking a label via call my_label(...) with missing positional parameters or invalid keyword arguments triggers an immediate runtime TypeError.

```renpy
# Bad
label dungeon(difficulty, party_size=4):
    ...

label start:
    call dungeon()                     # Missing required 'difficulty' argument!
    call dungeon("hard", invalid=True) # Unexpected keyword argument!

# Good
label start:
    call dungeon("hard", party_size=2)
```

---

## Control Flow and Branching (RPY4xx)

<a id="rpy401"></a>
### RPY401: Variable defined in one menu choice but missing in another
- **Severity**: `WARNING`
- **Why**: Branching asymmetry: if Choice A assigns `$ torch = True` but Choice B does not, picking Choice B and later checking `if torch:` causes a fatal `NameError`.

```renpy
# Bad
menu:
    "Take torch":
        $ torch = True
    "Walk in dark":
        pass
if torch:
    "Lighting the way..."

# Good
default torch = False
menu:
    "Take torch":
        $ torch = True
    "Walk in dark":
        pass
```

---

<a id="rpy402"></a>
### RPY402: Empty menu choice
- **Severity**: `WARNING`
- **Why**: A choice block without statements immediately falls through into the next label or dialogue.

```renpy
# Bad
menu:
    "Give up":
    "Fight":
        "Battle!"

# Good
menu:
    "Give up":
        return
    "Fight":
        "Battle!"
```

---

<a id="rpy403"></a>
### RPY403: Always-false condition
- **Severity**: `WARNING`
- **Why**: Conditions like `if False:` or `if x and not x:` can never evaluate to true. The block is dead code.

```renpy
# Bad
if False:
    "This branch will never execute."

# Good
if has_secret_item:
    "Secret branch!"
```

---

<a id="rpy404"></a>
### RPY404: Variable in MAYBE_SET state evaluated after menu branch
- **Severity**: `WARNING`
- **Why**: If a variable is only defined in one choice of a `menu:`, picking an alternate choice and subsequently evaluating `if var:` or interpolating `[var]` will crash with `NameError` or `KeyError`.

```renpy
# Bad
menu:
    "Look into the chest":
        $ found_gem = True
    "Walk past":
        pass

if found_gem:   # RPY404: Crashes with NameError if player walked past!
    "You admire the gem."

# Good
default found_gem = False
menu:
    "Look into the chest":
        $ found_gem = True
    "Walk past":
        pass
```

---

## Assets and Media (RPY5xx)

<a id="rpy501"></a>
### RPY501: Missing audio file
- **Severity**: `ERROR`
- **Why**: Audio file referenced in `play` or `queue` was not found on disk, in `audio/`, or inside `.rpa` archives.

```renpy
# Bad
play music "bgm/missing_track.ogg"

# Good
play music "bgm/existing_track.ogg"
```

---

<a id="rpy502"></a>
### RPY502: Missing or mistyped sprite / background
- **Severity**: `WARNING`
- **Why**: Sprite attribute or background shown via `show` or `scene` does not exist in asset folders, `layeredimage` definitions, or `image` declarations.
- **Tip**: Quick Fix (`Ctrl+.`) will suggest the closest matching sprite or attribute name.

```renpy
# Bad
show sayori 99z_crazy_pose

# Good
show sayori 1a
```

---

<a id="rpy503"></a>
### RPY503: Unused media asset on disk
- **Severity**: `WARNING`
- **Why**: Image or audio files located in the project directory are never referenced in any script. Inflates build distribution size.

```renpy
# Bad: File 'game/images/unused_background.png' exists on disk but is never shown

# Good: Show the asset in script or remove the unused file
```

---

<a id="rpy504"></a>
### RPY504: Duplicate image declaration
- **Severity**: `WARNING`
- **Why**: Declaring the same image tag twice (via `image name = ...` or `image name:`) silently overrides the previous definition, potentially masking bugs.

```renpy
# Bad
image bg room = "day.png"
image bg room = "night.png"  # Silently overrides daytime room!

# Good
image bg room_day = "day.png"
image bg room_night = "night.png"
```

---

<a id="rpy505"></a>
### RPY505: Unregistered audio channel or voice loop
- **Severity**: `WARNING` (for voice loop) / `ERROR` (for unregistered channel)
- **Why**: Playing audio on a custom channel not registered via `renpy.music.register_channel()` causes a runtime `Exception`. Looping the `voice` channel causes audio overlap glitches during dialogue progression.

```renpy
# Bad
play ambient "rain.ogg"   # 'ambient' was never registered!
play voice "clip.ogg" loop # Voice channel should not loop!

# Good
init python:
    renpy.music.register_channel("ambient", mixer="sfx", loop=True)

play ambient "rain.ogg"
```

---

## Translations and Localization (RPY6xx)

<a id="rpy601"></a>
### RPY601: Variable mismatch in translation string
- **Severity**: `ERROR`
- **Why**: If a translated string alters or misspells a dialogue variable (`[var]`), rendering the translation causes a fatal `KeyError` at runtime.

```renpy
# Bad
old "Hello, [player_name]!"
new "Привет, [player]!"  # Typo in variable name!

# Good
old "Hello, [player_name]!"
new "Привет, [player_name]!"
```

---

<a id="rpy602"></a>
### RPY602: Formatting tag mismatch in translation string
- **Severity**: `WARNING`
- **Why**: Missing or altered formatting tags (`{b}`, `{color}`, `{i}`) in translation strings cause unclosed text tags and visual glitches.

```renpy
# Bad
old "Danger: {b}Hazard!{/b}"
new "Опасно: {b}Угроза!"  # Missing closing tag {/b}

# Good
old "Danger: {b}Hazard!{/b}"
new "Опасно: {b}Угроза!{/b}"
```

---

<a id="rpy603"></a>
### RPY603: Empty translation string ('new ""')
- **Severity**: `WARNING`
- **Why**: Leaving `new ""` empty for a non-empty original line will display an empty, blank dialogue window to players in that language.

```renpy
# Bad
old "Do you want to exit?"
new ""  # Player sees an empty dialogue box!

# Good
old "Do you want to exit?"
new "Вы хотите выйти?"