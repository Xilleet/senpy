# Senpy Rules Reference

Comprehensive guide to all semantic rules implemented in the **Senpy** Ren'Py linter.

---

### Navigation
- [RPY101](#rpy101) | [RPY102](#rpy102) | [RPY103](#rpy103) | [RPY104](#rpy104) | [RPY105](#rpy105) | [RPY106](#rpy106)
- [RPY201](#rpy201) | [RPY202](#rpy202) | [RPY203](#rpy203) | [RPY204](#rpy204) | [RPY205](#rpy205)
- [RPY301](#rpy301) | [RPY302](#rpy302) | [RPY303](#rpy303) | [RPY304](#rpy304) | [RPY305](#rpy305) | [RPY306](#rpy306)
- [RPY401](#rpy401) | [RPY402](#rpy402) | [RPY403](#rpy403)
- [RPY501](#rpy501) | [RPY502](#rpy502) | [RPY504](#rpy504)

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
- **Why**: Executing `+=`, `-=`, etc. before the variable exists causes an immediate `NameError`.

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
default karma = 0
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
- **Why**: Unescaped quotes inside dialogue break Ren'Py's script parser during game initialization.

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

## Control Flow (RPY4xx)

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
- **Why**: Conditions like `if False:` or `if x and not x:` can never be evaluated to true. The block is dead code.

---

## Assets and Media (RPY5xx)

<a id="rpy501"></a>
### RPY501: Missing audio file
- **Severity**: `ERROR`
- **Why**: Audio file referenced in `play music/sound/voice` was not found on disk or inside `.rpa` archives.

---

<a id="rpy502"></a>
### RPY502: Missing or mistyped sprite / background
- **Severity**: `WARNING`
- **Why**: Image shown via `show` or `scene` does not exist in asset folders or `image` declarations.

---

<a id="rpy504"></a>
### RPY504: Duplicate image declaration
- **Severity**: `ERROR`
- **Why**: Declaring the same image name twice silently overwrites the previous definition.

```renpy
# Bad
image bg room = "day.png"
image bg room = "night.png"

# Good
image bg room_day = "day.png"
image bg room_night = "night.png"
```