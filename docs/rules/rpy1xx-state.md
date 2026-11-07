---
title: RPY1xx — Variables, State & API Rules
description: RPY1xx rules cover Ren'Py variable declarations and state management — undefined variables (RPY101-RPY103), default vs define (RPY104-RPY105), non-revertable types (RPY106), deprecated APIs (RPY107), type taint conflicts (RPY108), init phase load order (RPY109), and Python syntax errors (RPY110). These are the rules that catch save corruption and rollback desync.
tags:
  - rules
  - state
  - rpy1xx
---

# RPY1xx — Variables & State Rules

The RPY1xx family covers **variable usage and state management** —
the rules that catch the hardest bugs in Ren'Py: save corruption,
rollback desync, and `NameError` on save load.

These bugs survive dev playtesting (the developer plays the
"interesting" route, the variable is set in the order they expect,
the save is fresh) and only surface when a player:

- Takes a different route
- Loads an old save after a game update
- Triggers rollback at the wrong moment
- Plays on a non-English build (for translation variables)

`renpy lint` does **not** catch these — it runs *after* the
alphabetical file load and inside the full Ren'Py environment, so it
can't model "what if the player skips `intro` and goes straight to
`continue_story`?"

---

## Rules in this family

### `RPY101` — Unresolved variable in dialogue interpolation

**Severity:** `ERROR`

Using `[var]` inside dialogue text when `var` is not declared via
`default` or `define` crashes the game with a runtime `KeyError`.

```renpy
# Bad — typo: player_namme (not player_name)
"Hello, [player_namme]!"

# Good
default player_name = "Eileen"
"Hello, [player_name]!"
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy101)

---

### `RPY102` — Augmented assignment before declaration

**Severity:** `ERROR`

Executing `+=`, `-=`, etc. before the variable exists causes an
immediate runtime `NameError`.

```renpy
# Bad — score is never declared before +=
label start:
    $ score += 10   # NameError: name 'score' is not defined

# Good
default score = 0
label start:
    $ score += 10
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy102)

---

### `RPY103` — Undeclared variable in condition

**Severity:** `ERROR`

Evaluating `if var:` will crash with `NameError` if `var` was never
declared.

```renpy
# Bad
if has_key:   # NameError if has_key was never default'd
    jump secret_room

# Good
default has_key = False
label start:
    if has_key:
        jump secret_room
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy103)

---

### `RPY104` — Dynamic assignment without top-level `default`

**Severity:** `WARNING` | **Auto-fix:** ✅ (`--defaults` generates the missing `default` lines)

Creating variables on the fly (`$ var = 1`) without `default` breaks
save-game portability across updates and triggers `NameError` on
alternate story routes.

```renpy
# Bad — variable won't survive save/load
label chapter_2:
    $ affection = 5

# Good
default affection = 0
label chapter_2:
    $ affection = 5
```

**Auto-fix:** Run `senpy /path/to/game --defaults` to generate a
`senpy_defaults.rpy` file with `default` declarations for every
RPY104 variable in your project. Review and merge.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy104)

---

### `RPY105` — Direct mutation of `define` constant

**Severity:** `ERROR`

`define` is strictly for constants (Characters, configurations).
Reassigning them breaks Ren'Py rollback and save serialization.

```renpy
# Bad — mutates a define, save corrupts on rollback
define karma = 0
label start:
    $ karma += 1

# Good — use default for mutable variables
default karma = 0
label start:
    $ karma += 1
```

Symptom if not fixed: `Exception: define karma is not revertable` on
rollback, or save files silently corrupt after loading an old save.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy105)

---

### `RPY106` — Usage of non-revertable Python types

**Severity:** `WARNING`

Standard `import random` and Python's mutable `set()` are not
tracked by Ren'Py's rollback engine, corrupting saves.

```renpy
# Bad
import random
$ inventory = set()

# Good
from renpy import random
$ inventory = []  # or renpy.revertable_set()
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy106)

---

### `RPY107` — Usage of deprecated / obsolete Ren'Py API

**Severity:** `WARNING` | **Auto-fix:** ✅ (QuickFix in VS Code)

Calling obsolete Ren'Py functions (`LiveComposite`, `DynamicCharacter`,
`im.*`, `ui.*`) harms rendering performance (CPU vs GPU) or breaks
compatibility on Ren'Py 7/8.

```renpy
# Bad
image natsuki mouth = LiveComposite((960, 960), (0, 0), "base.png")
define c = DynamicCharacter("char_name")

# Good
image natsuki mouth = Composite((960, 960), (0, 0), "base.png")
define c = Character("[char_name]")
```

QuickFix (`Ctrl+.` in VS Code) suggests the modern replacement.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy107)

---

### `RPY108` — Type taint conflict or incompatible augmented assignment

**Severity:** `ERROR` (for invalid `+=`) / `WARNING` (for type overwrites)

Reassigning incompatible types (e.g. `int` variable reassigned to
`str`) or performing illegal augmented operations (e.g.
`$ str_var += 1`) causes fatal runtime `TypeError`. Also catches
incompatible collection method invocations (e.g. `list.add()` should
be `list.append()`).

```renpy
# Bad
default score = 0
default player_name = "Eileen"
label start:
    $ player_name += 1       # TypeError: can only concatenate str to str
    $ score = "High"         # Type taint: breaks numerical comparisons
    $ inventory.add("sword")  # AttributeError: 'list' has no .add()

# Good
default score = 0
default player_name = "Eileen"
default inventory = []
label start:
    $ player_name += "!"
    $ score = 100
    $ inventory.append("sword")
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy108)

---

### `RPY109` — Init phase dependency graph violation

**Severity:** `ERROR`

Ren'Py loads scripts in ascending alphabetical order of filenames
during initialization. Evaluating functions or classes in `a.rpy`
that are defined in `z.rpy` inside `init python:` causes an immediate
crash with `NameError` on startup.

```renpy
# Bad — file order: a_setup.rpy comes before z_helpers.rpy alphabetically
# game/a_setup.rpy
init python:
    configure_interface()   # NameError: 'configure_interface' is not defined!

# game/z_helpers.rpy
init python:
    def configure_interface(): ...

# Good — reverse the alphabetical order
# game/a_helpers.rpy
init python:
    def configure_interface(): ...

# game/z_setup.rpy
init python:
    configure_interface()
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy109)

---

## Common patterns caught

### Save corruption on rollback

`RPY105` + `RPY106` together cover the most insidious class of bug:
**saves that corrupt silently** when a player rolls back. The game
appears to work in dev (fresh saves, no rollback), but a player who
saves, plays for hours, rolls back to an earlier choice, and saves
again ends up with a save that won't load after the next game update.

### `NameError` on save load

`RPY104` covers the case where a variable is created with `$`
inside a label, but the player saves *after* that label and loads
*before* it (e.g. by starting a new game from a save mid-story, or
after a game update that rearranges labels). The variable doesn't
exist in the loaded save's persistent state.

### Init order crashes

`RPY109` catches the "NameError on game launch" class of bug —
caused by Ren'Py's alphabetical file load order interacting with
`init python:` blocks that reference each other across files. The
developer's machine loads them in a particular order, but a fresh
checkout on a new machine might load them differently.

### Python syntax errors

`RPY110` catches invalid Python syntax in `$`-statements and
`init python:` blocks — e.g. `$ x = )` would crash Ren'Py with a
`SyntaxError` traceback. Without Senpy, this bug only surfaces when
the player reaches the affected line.

---

## Auto-fix summary

| Rule | Auto-fixable | How |
|---|---|---|
| `RPY104` | ✅ | `senpy --defaults` generates a `senpy_defaults.rpy` with all missing `default` declarations |
| `RPY107` | ✅ | QuickFix in VS Code (`Ctrl+.`) suggests the modern replacement API |

---

## Tags

All RPY1xx rules are tagged `variables`, `state`, or both. RPY105
and RPY106 are also tagged `rollback`. RPY107 is tagged `deprecated`.

```bash
senpy /path/to/game --tag state rollback   # run only state + rollback rules
senpy /path/to/game --ignore-tag deprecated   # skip deprecated API checks
```

---

## What's next?

- [RPY2xx — Screens & UI](rpy2xx-screens.md) — screen actions, UI prediction.
- [RPY4xx — Branching](rpy4xx-flow.md) — `MAYBE_SET` reads after menu branches.
- [All 52 rules](index.md) — back to the navigator.
- [RULES.md in repo](https://github.com/Xilleet/senpy/blob/main/RULES.md)
  — canonical reference with full examples for every RPY1xx rule.
