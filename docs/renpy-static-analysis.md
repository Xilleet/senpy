---
title: Ren'Py Static Analysis — Five Levels of Bug Detection
description: Static analysis for Ren'Py visual novels means more than syntax checking. Five levels exist — syntax, references, semantics, control flow, and save/rollback safety. Senpy is the only Ren'Py static analyzer that covers all five. Learn what each level catches and why the built-in renpy lint focuses on the first two.
tags:
  - static-analysis
  - renpy
  - cluster-a
---

# Ren'Py Static Analysis

Static analysis for Ren'Py visual novels means checking your `.rpy`
scripts for bugs **without running the game**. There are five distinct
levels of static analysis, each catching a different class of bug.
Senpy is the only Ren'Py static analyzer that covers all five — the
built-in `renpy lint` focuses on the first two.

This page explains each level, what it catches, and why level 5 (save
and rollback safety) is the difference between "the game runs on my
machine" and "the game survives a player's save/load cycle".

---

## The five levels

| Level | What it analyses | Example caught bug | Catches it? |
|---|---|---|---|
| **1. Syntax** | Text-level tokens: tabs, quotes, encoding | Tab in indentation → `SyntaxError` | `renpy lint` + Senpy |
| **2. References** | Symbol table: labels, screens, files | `jump bad_edd` (typo) → `ScriptError` | `renpy lint` + Senpy |
| **3. Semantics** | Variable types, declarations, screen actions | `$ karma += 1` on `define` → save corrupts | **Senpy only** |
| **4. Control flow** | Branch-sensitive dataflow, MAYBE_SET, dead branches | Variable set in one `menu` choice → `NameError` | **Senpy only** |
| **5. Save & rollback** | Type revertability, `init` order, translation variables | `import random` → rollback desync | **Senpy only** |

The rest of this page walks through each level with a real example.

---

## Level 1 — Syntax

Checks the **text** of your `.rpy` files for things that won't parse or
that violate Ren'Py's indentation rules.

### What's checked

- **Tab characters** in indentation — Ren'Py requires 4 spaces. Tabs
  cause `SyntaxError` and break between editors. Senpy rule: `RPY001`.
- **Smart/curly quotes** in code (not dialogue) — `"hi"` instead of
  `"hi"`. Breaks Python parsing in `$`-statements and `init python:`
  blocks. Senpy rule: `RPY002`.
- **File encoding** — Ren'Py reads all `.rpy` as UTF-8. A file saved as
  Windows-1251 (common in Russian projects) crashes the game on load.
  Senpy rule: `RPY100`.
- **Unescaped quotes** in dialogue — `"She said "Hello" and smiled"`
  breaks the Ren'Py parser. Senpy rule: `RPY305`.
- **Unclosed text tags** — `"Warning: {b}Hazard!"` (missing `{/b}`)
  bleeds formatting into all subsequent dialogue. Senpy rule: `RPY301`.

### Example

```renpy
# Bad (RPY001)
label start:
        "Hello, world!"   # ← that's a TAB, not 4 spaces

# Bad (RPY301)
"Warning: {b}Hazard!"   # ← {b} never closed — bold leaks into next lines

# Bad (RPY100)
# file saved as Windows-1251 → crashes Ren'Py on load
```

### Why this matters

These are immediate crashes or visual glitches. They're easy to find by
running the game once, but catching them at lint time (before the dev
playtest cycle) saves time.

---

## Level 2 — References

Checks that all **named references** in your scripts point to things
that actually exist: labels, screens, transforms, images, audio files.

### What's checked

- **Broken `jump`/`call` targets** — `jump bad_edd` (typo for
  `bad_end`) → `ScriptError: Label 'bad_edd' is not defined` at
  runtime. Senpy rule: `RPY302`.
- **Calls to non-existent screens** — `call screen inventory_menuu`
  (typo) → `Exception: Screen 'inventory_menuu' is not known`. Senpy
  rule: `RPY204`.
- **Missing audio files** — `play music "bgm/non_existent.ogg"` when
  the file doesn't exist on disk or in any `.rpa` archive. Senpy rule:
  `RPY501`.
- **Unresolved sprites / transforms** — `show sayori 99z_crazy_pose`
  when neither the image nor any `layeredimage` defines that attribute.
  Senpy rule: `RPY502`.
- **Malformed color tags** — `"{color=#12345}"` (5 hex digits instead
  of 6) crashes the Ren'Py text renderer. Senpy rule: `RPY304`.
- **Duplicate label declarations** — same `label chapter_1:` in two
  files → `ScriptError` on startup. Senpy rule: `RPY307`.

### Example

```renpy
# Bad (RPY302)
jump bad_edd   # ← typo for bad_end → ScriptError at runtime

# Bad (RPY204)
call screen inventory_menuu   # ← typo for inventory_menu → Exception

# Bad (RPY501)
play music "bgm/missing_track.ogg"   # ← file doesn't exist → Exception
```

### Why this matters

These are immediate crashes when the player reaches the affected line.
`renpy lint` catches most of them (it has access to the symbol table
after `init python:` runs). Senpy catches them too — without needing
the Ren'Py SDK.

---

## Level 3 — Semantics

Checks that **variable usage** respects Ren'Py's domain model:
`default` vs `define`, screen actions, parameter signatures, type
invariants.

### What's checked

- **Undefined variable in dialogue** — `"Hello, [player_name]!"` when
  `player_name` was never declared → `KeyError` at runtime. Senpy rule:
  `RPY101`.
- **`+=` before declaration** — `$ score += 10` when `score` was never
  `default`ed → `NameError`. Senpy rule: `RPY102`.
- **Undeclared variable in condition** — `if has_key:` when `has_key`
  was never `default`ed or `define`d → `NameError`. Senpy rule:
  `RPY103`.
- **Dynamic assignment without `default`** — `$ affection = 5` inside
  a label without `default affection = 0` at top level → variable
  won't survive save/load across game updates. Senpy rule: `RPY104`.
- **`define` mutation** — `define karma = 0` then `$ karma += 1`
  breaks Ren'Py rollback and save serialization. Senpy rule: `RPY105`.
- **Non-revertable Python types** — `import random` (standard Python,
  not `from renpy import random`) or `$ inventory = set()` (mutable
  set, not `renpy.revertable_set()`) breaks rollback. Senpy rule:
  `RPY106`.
- **Deprecated Ren'Py API** — `LiveComposite`, `DynamicCharacter`,
  `im.*`, `ui.*` are obsolete. Senpy rule: `RPY107` (with QuickFix).
- **Type taint conflicts** — `default score = 0` then `$ score = "High"`
  overwrites the type, breaking all subsequent numerical comparisons.
  Senpy rule: `RPY108`.
- **Init phase dependency graph violation** — function called in
  `a_setup.rpy` `init python:` block but defined in `z_helpers.rpy`
  `init python:` block → `NameError` at game launch (alphabetical
  file load order). Senpy rule: `RPY109`.
- **Screen parameter mismatch** — `use inventory()` when the screen
  requires `use inventory("weapons")` → `Exception`. Senpy rule:
  `RPY207`.
- **`call` argument mismatch** — `call dungeon()` when the label
  requires `call dungeon("hard")` → `TypeError`. Senpy rule: `RPY310`.

### Example

```renpy
# Bad (RPY105 — save corrupts on rollback)
define karma = 0
label start:
    $ karma += 1   # ← define is for constants, not mutable state

# Bad (RPY109 — NameError at game launch)
# game/a_setup.rpy
init python:
    configure_interface()   # ← defined in z_helpers.rpy, but a < z alphabetically

# game/z_helpers.rpy
init python:
    def configure_interface(): ...
```

### Why this matters

These bugs **survive dev playtesting**. The developer plays the
"interesting" route, the variable is set in the order they expect, the
save file is fresh. Players find them: a player who takes a different
route, loads an old save after a game update, or hits rollback at the
wrong moment will see `NameError`, `KeyError`, or a corrupted save.

These are beyond `renpy lint`'s scope. It runs *after* the alphabetical
file load and inside the full Ren'Py environment, so it can't model
"what if the player skips `intro` and goes straight to
`continue_story`?"

---

## Level 4 — Control flow

Checks **branch-sensitive dataflow**: variables declared in some
branches but read after the branch, dead branches, story islands.

### What's checked

- **Menu branch asymmetry** — variable set in one `menu` choice but
  not another, then read after the `menu`. Crashes for players who pick
  the wrong choice. Senpy rules: `RPY401` (asymmetry) + `RPY404`
  (MAYBE_SET read).
- **Empty menu choice** — a choice with no statements falls through
  to the next dialogue. Senpy rule: `RPY402`.
- **Always-false conditions** — `if False:` or `if x and not x:` is
  dead code. Senpy rule: `RPY403`.
- **Story islands** — a group of labels reference each other in a loop
  but no entry point exists from `start`, `splashscreen`, or main menu.
  Unreachable dead content or orphaned story routes. Senpy rule:
  `RPY309`.
- **Unreferenced dead labels** — label declared but never reached by
  any `jump`/`call`. Senpy rule: `RPY303`.
- **Fallthrough hazard** — label ends without `jump` or `return` before
  the next label declaration, control flow bleeds into it. Senpy rule:
  `RPY308`.

### Example

```renpy
# Bad (RPY404 — crashes for players who walk past)
menu:
    "Take the gem":
        $ found_gem = True   # only set here
    "Walk past":
        pass

if found_gem:   # ← MAYBE_SET: crashes with NameError if player walked past
    "You admire the gem."

# Bad (RPY309 — story island)
label route_draft_a:
    "Draft scene A"
    jump route_draft_b

label route_draft_b:
    "Draft scene B"
    jump route_draft_a
# ↑ Loops into each other, but nothing in the game ever jumps INTO this loop.
#   Unreachable from start — dead content.
```

### Why this matters

These are the **hardest bugs to find by playtesting**. They only fire
when a player picks a specific choice (or sequence of choices), so the
developer who always picks the "interesting" path never sees them. By
the time a player hits the bug and reports it, the developer has to
reproduce the exact player's choice sequence — which is rarely
documented.

Senpy's `StoryFlowAnalyzer` (in `senpy/rules/flow.py`) builds a jump
graph and tracks `MAYBE_SET` state across branches. It can detect
these bugs statically, without running the game.

---

## Level 5 — Save & rollback safety, translations

Checks **Ren'Py-specific invariants** that no generic Python linter
can know about: rollback revertability, save-file persistence,
translation variable consistency.

### What's checked

- **Non-revertable types** in story state (RPY106, covered in level 3).
- **Translation variable mismatch** — `old "Hello, [player_name]!"` vs
  `new "Привет, [player]!"` (typo). Non-English players see
  `Привет, [player]!` literally because `[player]` doesn't exist.
  Senpy rule: `RPY601`.
- **Translation formatting tag mismatch** — `old "Danger: {b}Hazard!{/b}"`
  vs `new "Опасно: {b}Угроза!"` (missing `{/b}`). Tag leaks into next
  lines for that language. Senpy rule: `RPY602`.
- **Empty translation string** — `new ""` for a non-empty original →
  player sees a blank dialogue box. Senpy rule: `RPY603`.
- **Duplicate translation strings** — same `old "Hello"` translated to
  different `new "Privet"` and `new "Zdravstvuy"` in the same file.
  Second one silently overrides the first. Senpy rule: `RPY801`.
- **Inconsistent translation across files** — same `old "Hello"`
  translated to different strings in different files of the same
  language. Confuses players and translation memory tools. Senpy rule:
  `RPY802`.
- **Unregistered audio channels** — `play ambient "rain.ogg"` when
  `ambient` was never registered via `renpy.music.register_channel()`.
  Senpy rule: `RPY505`.

### Example

```renpy
# game/script.rpy
$ player_name = "Hero"
"Welcome, [player_name]!"     # ← original

# game/tl/russian/script.rpy
translate russian welcome_1:
    "Добро пожаловать, [player]!"   # ← typo: should be [player_name]
# RPY601 fires. Russian players see the literal text "Добро пожаловать, [player]!"
# (English players see "Welcome, Hero!" and don't notice anything.)
```

### Why this matters

These bugs only affect **non-English players** or **players on long
playthroughs** who save and load. They're invisible to the developer
(who plays in English, fresh saves) and to the translator (who works
on one file at a time, doesn't compare across files). They are also
the bugs that hurt reviews most — a player who sees `[player]` in
their localized dialogue thinks the game is broken.

`renpy lint` does **not** check translation files. Senpy does.

---

## Where Senpy sits

```
                    ┌─────────────────────────────────────┐
                    │  renpy lint (built-in)              │
                    │  ─────────────────────────          │
                    │  Level 1: Syntax                    │
                    │  Level 2: References                 │
                    │  + runtime init python checks        │
                    └─────────────────────────────────────┘
                              ⊂ (subset of)
                    ┌─────────────────────────────────────┐
                    │  Senpy                              │
                    │  ─────────────────────────          │
                    │  Level 1: Syntax                    │
                    │  Level 2: References                 │
                    │  Level 3: Semantics                 │
                    │  Level 4: Control flow              │
                    │  Level 5: Save & rollback safety    │
                    │           + translations             │
                    └─────────────────────────────────────┘
```

The two are **complementary**:

- `renpy lint` has access to the full Ren'Py runtime, so it can catch
  issues that require executing `init python:` blocks (e.g. circular
  image definitions resolved at init time).
- Senpy is a static analyzer, so it catches issues that require
  branch-sensitive dataflow analysis, save/rollback modeling, or
  translation file comparison — none of which `renpy lint` can do.

Run both. See [Senpy vs `renpy lint`](comparison.md) for the full
comparison.

---

## What's next?

- [**Senpy vs `renpy lint`**](comparison.md) — full 12-row comparison
  table.
- [**Ren'Py Error Checker**](renpy-error-checker.md) — map runtime
  error messages (`NameError`, `KeyError`, `AttributeError`,
  `ScriptError`) to the Senpy rule that catches them.
- [**All 53 rules**](rules/index.md) — browse by category.
- [**Configuration**](configuration.md) — `senpy.toml`, `.senpy-ignore`,
  `--select`, `--tag` filters, strict mode.
