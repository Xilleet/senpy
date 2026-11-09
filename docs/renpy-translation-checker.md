---
title: Ren'Py Translation Checker — Validate game/tl/ Files and Get Coverage Metrics
description: A Ren'Py translation checker finds bugs in your game/tl/ localization files before non-English players do. Senpy checks variable interpolation mismatches (RPY601), formatting tag mismatches (RPY602), empty new strings (RPY603), duplicate translations (RPY801), and inconsistent translations across files (RPY802). It also reports per-language completion percentages via --coverage.
tags:
  - translation
  - localization
  - renpy
  - cluster-d
---

# Ren'Py Translation Checker

A Ren'Py translation checker validates your `game/tl/` localization files
for bugs that the English build won't catch. Senpy's translation
checker covers five rule families and produces per-language
**translation coverage metrics** so you can see how complete each
localization is.

This page explains each rule, shows real before/after examples, and
walks through running the checker on a real project.

---

## Why a translation checker matters

Translation bugs are sneaky:

1. **They only affect non-English players.** The developer plays in
   English, the bug is invisible.
2. **They survive your own playtest.** The translator works on one
   `.rpy` file at a time, so cross-file inconsistencies are invisible
   without a tool.
3. **They look like "the game is broken" to the player.** A Russian
   player who sees `Добро пожаловать, [player]!` (literal `[player]`
   because the variable name was misspelled in the translation)
   thinks the game is broken, not the translation.
4. **They hurt reviews.** Localized reviews on Steam / itch.io often
   single out translation quality. A few `[var]` literals in dialogue
   is enough to sink a "Recommended" to "Not Recommended".

A translation checker catches these statically — you find the bug
before the translation ships, not after a player reviews it.

---

## The five translation rules

Senpy checks `game/tl/<lang>/*.rpy` translation files against the
original `.rpy` files. Five rules cover the most common bugs:

### `RPY601` — Variable mismatch in translation string

**Severity:** `ERROR`

The `old` line uses `[var1]` but the `new` line uses `[var2]` (typo)
or no variable at all. Non-English players see the literal `[var2]`
text because `var2` doesn't exist in the variable store.

```renpy
# Bad
old "Welcome, [player_name]!"
new "Привет, [player]!"   # ← typo: should be [player_name]

# Good
old "Welcome, [player_name]!"
new "Привет, [player_name]!"
```

### `RPY602` — Formatting tag mismatch

**Severity:** `WARNING`

The `old` line uses a Ren'Py text tag (`{b}`, `{i}`, `{color}`, etc.)
but the `new` line has a different set of tags — usually missing
the closing tag. The tag bleeds into all subsequent dialogue in that
language.

```renpy
# Bad
old "Danger: {b}Hazard!{/b}"
new "Опасно: {b}Угроза!"   # ← missing {/b}

# Good
old "Danger: {b}Hazard!{/b}"
new "Опасно: {b}Угроза!{/b}"
```

### `RPY603` — Empty translation string

**Severity:** `WARNING`

The `old` line has content but `new ""` is empty. Players in that
language see a blank dialogue box.

```renpy
# Bad
old "Do you want to exit?"
new ""

# Good
old "Do you want to exit?"
new "Вы хотите выйти?"
```

### `RPY801` — Duplicate translation string in same file

**Severity:** `WARNING`

The same `old "..."` source string appears more than once in the same
translation file. The second translation silently overrides the first.
Common copy-paste error.

```renpy
# Bad — same file
translate russian chapter1_a1b2:
    old "Hello"
    new "Привет"

translate russian chapter1_c3d4:
    old "Hello"
    new "Здравствуй"   # ← silently overrides "Привет" — first translation is dead

# Good — same source uses one consistent translation
translate russian chapter1_a1b2:
    old "Hello"
    new "Привет"

translate russian chapter1_c3d4:
    old "Goodbye"   # ← different source, no conflict
    new "Пока"
```

### `RPY802` — Inconsistent translation across files

**Severity:** `WARNING`

The same `old "..."` source string is translated to *different* `new`
strings in different files of the same language. Confuses players
(same line shows different text in different scenes) and breaks
translation memory tools (Trados, memoQ, OmegaT).

```renpy
# Bad — game/tl/russian/common.rpy
translate russian chapter1_a1b2:
    old "Hello"
    new "Привет"

# Bad — game/tl/russian/dialogue.rpy (same language, different translation)
translate russian chapter1_c3d4:
    old "Hello"
    new "Здравствуй"   # ← inconsistent! Player sees "Привет" in one
                       #   scene and "Здравствуй" in another.

# Good — pick one translation and use it consistently
# game/tl/russian/dialogue.rpy
translate russian chapter1_c3d4:
    old "Hello"
    new "Привет"   # ← consistent across files
```

---

## Translation coverage metrics

Beyond checking for bugs, Senpy reports **per-language completion
percentage**:

```bash
senpy /path/to/your/game --coverage
```

Output (excerpt):

```
Translation Coverage
═══════════════════════════════════════════════════════════════════════════
Language    Strings    Translated    Empty    Coverage
───────────────────────────────────────────────────────────────────────────
russian      1,243       1,201          42       96.6%
spanish      1,243         876         367       70.5%
german       1,243           0       1,243        0.0%
japanese     1,243       1,243           0      100.0%
───────────────────────────────────────────────────────────────────────────
```

- **Strings** — total `old "..."` lines across all original `.rpy` files
  (the strings that *should* be translated).
- **Translated** — `old/new` pairs where `new` is non-empty.
- **Empty** — `new ""` (RPY603 — empty translation string).
- **Coverage** — `Translated / Strings` as a percentage.

Use this to:

- **Track localization progress** — see which languages are ready to
  ship.
- **Find dead translations** — if `Translated > Strings` (shouldn't
  happen but can if a source string was removed), there's an orphan
  translation block.
- **Catch missing translations** — languages below 100% have `new ""`
  or missing `old/new` pairs that need to be filled in.

For the full output, including a per-file breakdown and missing
strings list, use:

```bash
senpy /path/to/game --coverage --output-format json --output-file coverage.json
```

The JSON output is suitable for piping into a dashboard or for CI
gating ("fail if Russian coverage < 95%").

---

## Worked example — finding a translation typo

You're localizing your game into Russian. The translator returns
`game/tl/russian/script.rpy`. You run Senpy before shipping the
build.

```bash
senpy /path/to/game
```

Output (excerpt):

```
game/tl/russian/script.rpy:42
 42 │     new "Добро пожаловать, [player]!"
 [ERROR] RPY601: Variable mismatch in translation string
 Translation uses [player] but original uses [player_name]. Variable
 does not exist — Russian players will see the literal [player] text.

game/tl/russian/script.rpy:107
107 │     new "Опасно: {b}Угроза!"
 [WARNING] RPY602: Formatting tag mismatch in translation string
 Translation has unclosed {b} tag — formatting will leak into next
 dialogue lines in this language.

game/tl/russian/dialogue.rpy:18
 18 │     new "Здравствуй"
 [WARNING] RPY802: Inconsistent translation across files
 "Hello" is translated as "Привет" in common.rpy but "Здравствуй"
 here. Pick one translation and use it consistently.

game/tl/russian/menu.rpy:31
 31 │     new ""
 [WARNING] RPY603: Empty translation string
 Original is "Do you want to exit?" but new is empty — players will
 see a blank dialogue box.

Coverage report:
russian      1,243       1,201          42       96.6%
```

You send the file back to the translator with this report. They fix
the four issues, the next run is clean, you ship.

---

## Filtering translation rules in CI

If you want CI to **only** run the translation checker (skip other
rules), use the `--tag` filter:

```bash
senpy /path/to/game --tag translations
```

This runs only the rules tagged `translations` (RPY601, RPY602,
RPY603, RPY801, RPY802).

To run everything *except* translation rules:

```bash
senpy /path/to/game --ignore-tag translations
```

See [Configuration — Tag filters](configuration.md#cli-flags) for
the full tag taxonomy.

---

## Integrating with translation workflows

### With a CAT tool (Trados, memoQ, OmegaT)

CAT tools work on bilingual files (`.tmx`, `.tbx`, `.xliff`). Senpy
doesn't generate these — but it can validate the *resulting*
`game/tl/<lang>/*.rpy` files after the CAT round-trip. Run Senpy
after each translation pass to catch:

- Variable names the CAT tool "auto-corrected" (e.g. `[player_name]`
  → `[player]` because the tool thought it was a typo).
- Tag mismatches from segment splitting (`{b}` in one segment, `{/b}`
  in another, with the segment boundary in between).
- Empty translations from segments the translator skipped.

### With Crowdin / Lokalise / POEditor

These tools produce `.po` or `.json` files that a build script
converts to Ren'Py `game/tl/` files. Run Senpy on the *generated*
`game/tl/` files, not on the source `.po` files — Senpy only reads
Ren'Py translation format.

### With `renpy.exec` in CI

The `renpy.exec` helper that ships with the Ren'Py SDK can extract
strings to translate (`renpy.exec extract`) and generate translation
templates. Run it first to produce `game/tl/none/` (the source
language), then run Senpy to validate the actual translations against
the source.

---

## What's next?

- [**All 53 rules**](rules/rpy6xx-translations.md) — RPY6xx family
  reference page.
- [**Configuration**](configuration.md) — how to silence noisy rules,
  configure severity overrides, set up `--tag translations` for CI.
- [**CLI reference**](cli-reference.md) — `--coverage`,
  `--output-format json`, `--tag translations`, `--ignore-tag`.
- [**Ren'Py GitHub Actions**](renpy-github-actions.md) — wire Senpy
  into CI to run the translation checker on every PR.
