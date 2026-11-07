---
title: RPY2xx — Screens & UI Rules
description: RPY2xx rules cover Ren'Py screen language — direct state mutation (RPY201), undeclared screen variables (RPY202), dead buttons (RPY203), missing screens (RPY204), imperative loops (RPY205), function calls in actions (RPY206), parameter mismatch (RPY207), and SetVariable leaks (RPY208).
tags:
  - rules
  - screen
  - rpy2xx
---

# RPY2xx — Screens & UI Rules

The RPY2xx family covers **Ren'Py screen language** — the `screen`
DSL that renders UI elements like menus, dialogue boxes, and HUD
overlays. Screens are tricky because they're evaluated continuously
by Ren'Py's UI prediction engine, so imperative Python code can fire
multiple times per frame.

These rules catch the most common UI bugs: dead buttons, screen
freezes, FPS drops, and crashes when a screen tries to display.

---

## Rules in this family

### `RPY201` — Direct state mutation inside screen

**Severity:** `WARNING`

Screens are evaluated continuously by Ren'Py's UI prediction. Direct
Python mutations (`$ var += 1`) execute multiple times every frame
and break rollback.

```renpy
# Bad — executes every frame, breaks rollback
screen shop():
    $ player_gold -= 10

# Good — use a screen action
screen shop():
    textbutton "Buy" action SetVariable("player_gold", player_gold - 10)
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy201)

---

### `RPY202` — Screen accesses variable without `default`

**Severity:** `WARNING`

Screens can be evaluated before story start (e.g. in the main
menu). Reading uninitialized variables crashes the engine.

```renpy
# Bad — show_tracker not declared
screen hud():
    if show_tracker:
        text "Active"

# Good
default show_tracker = False
screen hud():
    if show_tracker:
        text "Active"
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy202)

---

### `RPY203` — Button without `action`

**Severity:** `WARNING`

Buttons without an `action` argument are dead UI elements that
cannot be clicked.

```renpy
# Bad — button does nothing on click
textbutton "Confirm"

# Good
textbutton "Confirm" action Return()
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy203)

---

### `RPY204` — Call/Show to non-existent screen

**Severity:** `ERROR`

Displaying or calling an undeclared screen terminates the game with
`Exception: Screen is not known`.

```renpy
# Bad — typo
call screen inventory_menuu

# Good
call screen inventory_menu
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy204)

---

### `RPY205` — Imperative Python loop inside screen

**Severity:** `WARNING`

Python loops inside screens severely hurt UI prediction performance
and cause frame drops.

```renpy
# Bad — Python for loop in screen
screen inv():
    python:
        for item in items:
            pass

# Good — declarative Ren'Py for loop
screen inv():
    for item in items:
        text item
```

The declarative form uses Ren'Py's screen DSL, which is optimized
for UI prediction. The `python:` block bypasses it and runs as
plain Python.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy205)

---

### `RPY206` — Direct function call in button action

**Severity:** `ERROR` | **Auto-fix:** ✅ (QuickFix in VS Code)

Calling a function with parentheses `action heal_player()` executes
it immediately during screen rendering and UI prediction, NOT upon
user click.

```renpy
# Bad — function runs during screen render, not on click
textbutton "Heal" action heal_player()

# Good — wrapped in Function(), runs on click
textbutton "Heal" action Function(heal_player)
```

QuickFix (`Ctrl+.` in VS Code) wraps the call in `Function(...)`.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy206)

---

### `RPY207` — Invalid parameters in screen call / use

**Severity:** `ERROR`

Passing missing required parameters or unknown keyword arguments to
`use screen` or `call screen` causes a fatal runtime `Exception`.

```renpy
# Bad — missing required 'category' argument
screen inventory(category, sort_by="name"):
    ...

use inventory()

# Good
use inventory("weapons")
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy207)

---

### `RPY208` — Screen-local variable modified via global action

**Severity:** `ERROR` | **Auto-fix:** ✅ (QuickFix in VS Code)

Variables declared with `default` inside a screen or screen
parameters are screen-local. Using `SetVariable` or `$ var = ...`
modifies the global store instead of the screen variable, causing
UI desynchronization and broken button interactions.

```renpy
# Bad — SetVariable modifies global, not screen-local
screen shop():
    default selected_item = None
    textbutton "Pick Sword" action SetVariable("selected_item", "Sword")

# Good — SetScreenVariable modifies screen-local
screen shop():
    default selected_item = None
    textbutton "Pick Sword" action SetScreenVariable("selected_item", "Sword")
```

QuickFix (`Ctrl+.` in VS Code) replaces `SetVariable` with
`SetScreenVariable`.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy208)

---

## Common patterns caught

### Screen freezes / FPS drops

`RPY201` + `RPY205` together cover the two main causes of FPS drops
in screen-heavy Ren'Py games:

- `RPY201` — direct `$ var = ...` mutation in a screen body executes
  every frame. Ten such lines can drop FPS by 30%.
- `RPY205` — Python `for`/`while` loops in screens bypass UI
  prediction. Move loops to `python:` blocks at init time, or
  rewrite as declarative `for` in the screen DSL.

### Dead UI

`RPY203` + `RPY206` together catch buttons that don't work:

- `RPY203` — `textbutton` without `action` argument.
- `RPY206` — `action heal_player()` (with parens) runs the function
  immediately instead of on click — button appears to do nothing.

### Wrong-variable bug

`RPY208` is subtle — the screen variable doesn't change when you
click the button, even though the action fires. Use
`SetScreenVariable` instead of `SetVariable` for screen-local
variables.

---

## Auto-fix summary

| Rule | Auto-fixable | How |
|---|---|---|
| `RPY206` | ✅ | QuickFix wraps `action f()` → `action Function(f)` |
| `RPY208` | ✅ | QuickFix replaces `SetVariable` → `SetScreenVariable` |

---

## Tags

All RPY2xx rules are tagged `screen`.

```bash
senpy /path/to/game --tag screen   # run only screen rules
senpy /path/to/game --ignore-tag screen   # skip screen rules
```

---

## What's next?

- [RPY1xx — Variables & State](rpy1xx-state.md) — `default` vs
  `define` for variables used in screens.
- [RPY3xx — Story Flow](rpy3xx-story.md) — labels, jumps, fallthrough.
- [All 52 rules](index.md) — back to the navigator.
- [RULES.md in repo](https://github.com/Xilleet/senpy/blob/main/RULES.md)
  — canonical reference.
