---
title: RPY3xx — Story Flow & Dialogue Rules
description: RPY3xx rules cover Ren'Py story flow and dialogue — unclosed text tags (RPY301), broken jumps (RPY302), dead labels (RPY303), color tag issues (RPY304), unescaped quotes (RPY305), missing return (RPY306), duplicate labels (RPY307), fallthrough (RPY308), story islands (RPY309), and call argument mismatch (RPY310).
tags:
  - rules
  - story
  - dialogue
  - rpy3xx
---

# RPY3xx — Story Flow & Dialogue Rules

The RPY3xx family covers **story flow and dialogue** — labels,
jumps, text tags, and call signatures. These rules catch the
"navigate-the-game" bugs: broken jumps, missing labels, fallthrough
hazards, and story islands.

---

## Rules in this family

### `RPY301` — Unclosed text tag in dialogue

**Severity:** `ERROR` | **Auto-fix:** ✅ (`--fix`)

Unclosed tags like `{b}` or `{color}` bleed formatting into all
subsequent lines of dialogue across the entire novel.

```renpy
# Bad — {b} never closed
"Warning: {b}Hazardous area!"

# Good
"Warning: {b}Hazardous area!{/b}"
```

Auto-fix: `senpy --fix` inserts the matching `{/tag}` at the end of
the dialogue.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy301)

---

### `RPY302` — Jump or Call to non-existent label

**Severity:** `ERROR` (or `WARNING` if a similar label exists)

Jumping to a missing label terminates the novel with a `ScriptError`.

```renpy
# Bad — typo for bad_end
jump bad_edd

# Good
jump bad_end
```

QuickFix (`Ctrl+.` in VS Code) will suggest similar label names if a
typo is detected.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy302)

---

### `RPY303` — Unreferenced / Dead label

**Severity:** `INFO` (hidden by default, use `--info`)

Label is declared but never referenced by any `jump` or `call`. It
may be unreachable dead code or an abandoned draft.

```renpy
# Bad — forgotten draft, never reached
label forgotten_draft:
    "Old scene never reached..."

# Good — connect it to the story or remove
jump forgotten_draft   # somewhere
# or delete the label
```

Senpy exempts system labels (`start`, `splash_window`, `after_load`,
`main_menu`) — these are called automatically by Ren'Py.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy303)

---

### `RPY304` — Malformed color in `{color}` tag

**Severity:** `ERROR`

Invalid hex codes (e.g. `#12345` — 5 digits) or unknown color names
crash the Ren'Py text renderer.

```renpy
# Bad — 5 hex digits
"{color=#12345}Text{/color}"

# Good — 6 hex digits
"{color=#123456}Text{/color}"
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy304)

---

### `RPY305` — Unescaped quotes inside dialogue

**Severity:** `ERROR`

Quotes inside a dialogue string without escaping (`\"`) break
Ren'Py's script parser during game initialization.

```renpy
# Bad — inner quotes break parser
"She said "Hello" and smiled."

# Good — escape with backslash
"She said \"Hello\" and smiled."
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy305)

---

### `RPY306` — Called label without `return`

**Severity:** `WARNING`

When a label is called via `call`, execution expects a `return`.
Without it, control flow accidentally bleeds into unrelated scenes.

```renpy
# Bad — call sub_scene, but sub_scene has no return
label sub_scene:
    "Dialogue..."

label next_scene:
    # ↑ control flow bleeds here!

# Good
label sub_scene:
    "Dialogue..."
    return
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy306)

---

### `RPY307` — Duplicate label declaration

**Severity:** `ERROR`

Declaring two labels with the exact same name across any project
script causes a fatal `ScriptError` on startup.

```renpy
# Bad
label chapter_1:
    ...
label chapter_1:   # ← Duplicate label!
    ...

# Good
label chapter_1:
    ...
label chapter_2:
    ...
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy307)

---

### `RPY308` — Label preceded by regular statements (fallthrough hazard)

**Severity:** `WARNING`

Ending a scene without `jump` or `return` before the next label
causes control flow to unintentionally fall right through into the
next scene.

```renpy
# Bad — scene_a has no jump/return, scene_b runs immediately after
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

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy308)

---

### `RPY309` — Story island / isolated subgraph unreachable from `start`

**Severity:** `WARNING`

A group of scenes or labels references each other in a loop, but
no entry point exists from `start`, `splashscreen`, or main menus.
This represents unreachable dead content or orphaned story routes.

```renpy
# Bad — Loops into each other, but unreachable from start!
label route_draft_a:
    "Draft scene A"
    jump route_draft_b

label route_draft_b:
    "Draft scene B"
    jump route_draft_a

# Good — Connect the route to story flow via jump/call
label main_route:
    jump route_draft_a   # somewhere
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy309)

---

### `RPY310` — Invalid argument count or keyword in `call` statement

**Severity:** `ERROR`

Invoking a label via `call my_label(...)` with missing positional
parameters or invalid keyword arguments triggers an immediate
runtime `TypeError`.

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

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy310)

---

## Common patterns caught

### Broken jumps

`RPY302` is the most common story-flow bug — typos in `jump` /
`call` targets. Senpy's QuickFix suggests the closest matching label
name, so fixing typos is one keystroke.

### Story islands

`RPY309` catches the "draft that never got connected" pattern.
Common after a major rewrite: a route was cut but the labels weren't
removed, and they loop into each other but nothing in the main
story jumps into them.

### Fallthrough hazards

`RPY308` is subtle — the game appears to work, but scenes bleed
into each other. Most visible when a developer "tests scene_a in
isolation" and sees scene_b's content play immediately after.

---

## Auto-fix summary

| Rule | Auto-fixable | How |
|---|---|---|
| `RPY301` | ✅ | `--fix` inserts the matching `{/tag}` |
| `RPY302` | ✅ | QuickFix suggests the closest label name |

---

## Tags

| Rule | Tags |
|---|---|
| `RPY301`, `RPY305` | `dialogue` |
| `RPY302`, `RPY303`, `RPY308`, `RPY309` | `story` |
| `RPY303` | also `dead-code` |
| `RPY307` | `story` |
| `RPY310` | `story` |

```bash
senpy /path/to/game --tag story   # only story-flow rules
senpy /path/to/game --tag dialogue   # only dialogue-tag rules
```

---

## What's next?

- [RPY4xx — Branching](rpy4xx-flow.md) — menu asymmetry, MAYBE_SET.
- [RPY2xx — Screens & UI](rpy2xx-screens.md) — screen actions, UI bugs.
- [All 52 rules](index.md) — back to the navigator.
- [RULES.md in repo](https://github.com/Xilleet/senpy/blob/main/RULES.md)
  — canonical reference.
