---
title: Ren'Py Error Checker — Map Runtime Crashes to Lint Rules
description: When Ren'Py crashes with NameError, KeyError, AttributeError, or ScriptError, the error message tells you what broke but not which line of which .rpy file caused it. Senpy is a Ren'Py error checker that maps each common runtime error to a lint rule, so you can find and fix the bug before release.
tags:
  - errors
  - checker
  - renpy
  - cluster-b
---

# Ren'Py Error Checker

When your Ren'Py visual novel crashes with `NameError`,
`KeyError`, `AttributeError`, or `ScriptError`, the error message tells
you *what* broke — but not *which line of which .rpy file caused it*.
And once a player hits the crash, you can't reproduce it without
knowing their exact choice sequence.

Senpy is a **Ren'Py error checker** that maps each common runtime
error to a specific lint rule, so you can find the bug statically,
before release — without needing the player's save file or choice
sequence.

This page is a reference: open it when a player sends you a crash
report, find the error message, follow the link to the Senpy rule
that would have caught it.

---

## How to use this page

1. Find the error message your player reported (or that you saw in
   `traceback.txt`) in the left column below.
2. The Senpy rule column tells you which RPY code catches this class
   of bug.
3. Click the rule link for the full rule reference, or run
   `senpy --rule RPYxxx` to see the rule detail in your terminal.
4. Run `senpy /path/to/your/game` to find all instances of this bug.

You can also run Senpy directly on a `traceback.txt`:

```bash
senpy --traceback /path/to/traceback.txt
# parses the crash log, explains the failure, and links to the rule
# that would have prevented it
```

---

## Common runtime errors → Senpy rules

| Runtime error | Senpy rule | What it catches |
|---|---|---|
| `NameError: name 'x' is not defined` on save load | `RPY104` | `$ x = 1` inside a label without a top-level `default x = 0`. Variable won't survive save/load across game updates. |
| `NameError: name 'x' is not defined` in `if` | `RPY103` | `if x:` where `x` was never declared via `default` or `define`. |
| `NameError: name 'x' is not defined` after `menu` | `RPY401` | Variable defined in one `menu:` branch but missing in another — crashes if player picks the wrong path. |
| `NameError: name 'x' is not defined` after menu, with `pass` in one branch | `RPY404` | Same as `RPY401` but caught at the read site (MAYBE_SET state). |
| `NameError` on game launch (`init` phase) | `RPY109` | Function/class used in `init python:` block in file `a_setup.rpy` but defined in `z_helpers.rpy`. Ren'Py loads files alphabetically, so `a < z` and the call crashes. |
| `KeyError: 'player_name'` in dialogue | `RPY101` | Typo in `[player_name]` interpolation — variable doesn't exist. |
| `KeyError` in translation string (non-English players only) | `RPY601` | Translation `new "..."` has different `[var]` than the original `old "..."`. |
| `TypeError: unsupported operand type(s) for +=` | `RPY108` | Type taint conflict (e.g. `str += int`) or invalid method like `list.append()` on a `dict`. |
| `AttributeError: 'list' object has no attribute 'add'` | `RPY108` | Wrong method on collection type (e.g. `my_list.add()` instead of `.append()`). |
| `AttributeError` on screen variable | `RPY208` | Screen-local variable modified via global `SetVariable` action instead of `SetScreenVariable`. |
| `ScriptError: Label 'xxx' is not defined` | `RPY302` | `jump xxx` or `call xxx` to a label that doesn't exist. QuickFix suggests similar names. |
| `ScriptError: Screen 'xxx' is not known` | `RPY204` | `call screen xxx` or `show screen xxx` for a screen that doesn't exist. |
| `SyntaxError: tab/indent mismatch` | `RPY001` | Tab characters in indentation (Ren'Py requires 4 spaces). |
| `SyntaxError` from smart quotes in code | `RPY002` | Smart/curly quotes `"`/`"` instead of straight `"`. |
| `Exception: define x is not revertable` on rollback | `RPY105` | Mutating a `define` constant with `$ x += 1` or `$ x = ...`. |
| `Exception` from non-revertable type on rollback | `RPY106` | `import random` (Python's stdlib) or `$ x = set()` (mutable set). Use `from renpy import random` and `renpy.revertable_set()`. |
| Game crashes after loading a save | `RPY104` / `RPY105` | Variable created with `$` instead of `default`, or `define` constant mutated. |
| Screen UI freezes / FPS drops | `RPY201` / `RPY205` | Direct state mutation inside screen or heavy `for`/`while` loops in screen language. |
| Dead button (click does nothing) | `RPY203` | `textbutton "Confirm"` without `action Return()`. |
| Button executes function immediately, not on click | `RPY206` | `textbutton "Heal" action heal_player()` — parens make it a call, not a callback. Use `Function(heal_player)`. |
| Color tag breaks the text renderer | `RPY304` | `"{color=#12345}"` — 5 hex digits instead of 6. |
| Quotes inside dialogue break parser | `RPY305` | `"She said "Hello" and smiled."` — unescaped inner quotes. |
| Duplicate label crashes game on launch | `RPY307` | Two `label chapter_1:` declarations across your project. |
| Fallthrough: scene A bleeds into scene B | `RPY308` | Label `scene_a` ends without `jump`/`return`, label `scene_b` declared immediately after. |
| `call` to label missing required arguments | `RPY310` | `call dungeon()` when `label dungeon(difficulty)` requires `difficulty`. |
| `use screen` with wrong parameters | `RPY207` | `use inventory()` when `screen inventory(category)` requires `category`. |
| Missing audio file | `RPY501` | `play music "bgm/missing.ogg"` — file not on disk or in any `.rpa`. |
| Sprite not found | `RPY502` | `show sayori 99z_crazy_pose` — attribute doesn't exist in any image/layeredimage. QuickFix suggests closest match. |
| Image override silently masks another image | `RPY504` | `image bg room = "day.png"` and `image bg room = "night.png"` — second one silently overrides the first. |
| Audio channel not registered | `RPY505` | `play ambient "rain.ogg"` when `ambient` was never registered via `renpy.music.register_channel()`. |
| Translation tag mismatch (non-English) | `RPY602` | `old "{b}Hazard!{/b}"` vs `new "{b}Угроза!"` (missing `{/b}`). |
| Empty translation string (non-English) | `RPY603` | `new ""` for a non-empty `old "..."` → player sees blank dialogue. |
| Duplicate translation in same file | `RPY801` | Same `old "Hello"` translated twice in one file — second silently overrides first. |
| Inconsistent translation across files | `RPY802` | Same `old "Hello"` translated to different strings in different files of the same language. |
| Unused `define` constant (dead code) | `RPY701` | `define DEBUG_MODE = False` declared but never referenced anywhere. |
| Unused `transform` (dead code) | `RPY702` | `transform slide_in:` declared but never applied via `show X at slide_in`. |
| Unused `screen` (dead code) | `RPY703` | `screen debug_overlay():` declared but never shown. |
| Unused `default` variable (dead code) | `RPY704` | `default unused_setting = "..."` declared but never read. Wastes save-file space. |
| Unused screen parameter | `RPY705` | `screen shop(unused_currency, gold):` — `unused_currency` never referenced. |
| Unused transform parameter | `RPY706` | `transform slide_in(unused_speed):` — `unused_speed` never referenced. |
| Unused audio channel registration | `RPY707` | `renpy.music.register_channel("ambient", ...)` but no `play ambient` anywhere. |
| File not valid UTF-8 (game crashes on load) | `RPY100` | File saved as Windows-1251 or another encoding. Re-save as UTF-8. |
| Augmented assignment before default declaration | `RPY102` | `$ score += 10` before any `default score = 0`. |
| Conditional evaluates undeclared variable | `RPY103` | `if has_key:` where `has_key` was never declared. |
| Variable defined in one menu choice but missing in another | `RPY401` | Menu branch asymmetry — `NameError` for players who pick the wrong choice. |
| Empty menu choice falls through | `RPY402` | `menu: "Give up":` (no statements) — falls through into the next block. |
| Always-false condition | `RPY403` | `if False:` or `if x and not x:` — dead branch. |
| Story island (unreachable from start) | `RPY309` | Group of labels referencing each other in a loop, with no entry point from `start`. |
| Dead label (never referenced) | `RPY303` | `label forgotten_draft:` declared but never reached by any `jump`/`call`. |
| Called label has no `return` | `RPY306` | `call sub_scene` then `sub_scene` ends without `return` — control flow bleeds into the next label. |

---

## Worked example — `NameError` on save load

Player reports:

> I started the game on day 1, played for 5 hours, saved, quit, came back
> the next day, loaded my save, and got `NameError: name 'greeted' is not
> defined`.

You check the script:

```renpy
label start:
    jump intro

label intro:
    $ greeted = True   # ← set with $, no `default greeted = ...` at top level
    "Hello!"

label continue_story:
    if greeted:    # ← crashes on save load if player skips intro
        "Hi again!"
```

The player saved at `continue_story` after the `intro` label had set
`greeted = True`. On save load, Ren'Py restores the persistent state
from the save file — but `greeted` was created with `$`, not `default`,
so it's not part of the persistent state. The variable doesn't exist
in the loaded save, and `if greeted:` throws `NameError`.

Run Senpy:

```bash
senpy /path/to/game
```

Output (excerpt):

```
script.rpy:5
  5 │     $ greeted = True
  [WARNING] RPY104: Dynamic assignment without top-level 'default'
  Variable 'greeted' is created via $ inside a label but never declared
  with `default`. It will not survive save/load across game updates.

script.rpy:9
  9 │     if greeted:
  [ERROR] RPY103: Undeclared variable in condition
  'greeted' is not declared via `default` or `define` — NameError on
  first access, or on save load if the variable was set in a previous
  label.
```

Fix:

```renpy
default greeted = False   # ← declares as persistent, save-safe

label start:
    jump intro

label intro:
    $ greeted = True
    "Hello!"

label continue_story:
    if greeted:
        "Hi again!"
```

Or generate the missing `default`s automatically:

```bash
senpy /path/to/game --defaults
# writes senpy_defaults.rpy with `default greeted = False` and every
# other RPY104 variable in your project
```

---

## Worked example — `KeyError` in translation

Player reports (translated from Russian):

> I'm playing the Russian version. After the welcome scene, the dialogue
> showed me the literal text "Добро пожаловать, [player]!" instead of
> my character's name.

You check `game/tl/russian/script.rpy`:

```renpy
translate russian welcome_1:
    old "Welcome, [player_name]!"
    new "Добро пожаловать, [player]!"   # ← typo: should be [player_name]
```

The `new` line uses `[player]`, but the `old` line uses
`[player_name]`. Ren'Py's interpolation engine looks up the variable
name in the translation — `[player]` doesn't exist, so it's left
literal.

Run Senpy:

```bash
senpy /path/to/game
```

Output (excerpt):

```
game/tl/russian/script.rpy:3
  3 │     new "Добро пожаловать, [player]!"
  [ERROR] RPY601: Variable mismatch in translation string
  Translation uses [player] but original uses [player_name]. Variable
  does not exist — Russian players will see the literal [player] text.
```

Fix:

```renpy
translate russian welcome_1:
    old "Welcome, [player_name]!"
    new "Добро пожаловать, [player_name]!"
```

---

## Inspecting a `traceback.txt` after a crash

If you have a `traceback.txt` from a player (or from your own
playtest), Senpy can parse it and explain the crash:

```bash
senpy --traceback /path/to/traceback.txt
```

Output:

- The full traceback, parsed.
- A human-readable explanation of what failed.
- The Senpy rule that would have caught the bug (if any).
- A pointer to the source line that triggered it.

This is useful for triage — you don't need to read a Python traceback
to figure out which Ren'Py rule to enable.

---

## Generating `default` declarations

If your project has accumulated many `$ var = ...` lines without
`default` (RPY104), Senpy can generate a starter file with all the
missing declarations:

```bash
senpy /path/to/game --defaults
```

Writes `senpy_defaults.rpy` next to your project:

```renpy
# Auto-generated by `senpy --defaults`. Review before merging.
default affection = 0
default has_key = False
default found_gem = False
# ... one per RPY104 variable
```

Inspect the file, adjust the initial values to fit your game's
logic, and merge into your project.

---

## What's next?

- [**All 52 rules**](rules/index.md) — browse by category.
- [**Ren'Py Linter**](renpy-linter.md) — overview of what linters catch.
- [**Configuration**](configuration.md) — how to silence noisy rules,
  promote warnings to errors, and use `strict` mode in CI.
- [**CLI reference**](cli-reference.md) — every flag, including
  `--traceback`, `--defaults`, `--fix`, `--cache-dir`, `--config`.
