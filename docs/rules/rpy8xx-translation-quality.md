---
title: RPY8xx — Translation Quality Rules
description: RPY8xx rules cover Ren'Py translation quality — duplicate translation strings in the same file (RPY801) and inconsistent translations across files in the same language (RPY802). These rules go beyond RPY6xx by detecting cross-string issues that signal copy-paste errors or translator drift.
tags:
  - rules
  - translations
  - quality
  - rpy8xx
---

# RPY8xx — Translation Quality Rules

The RPY8xx family covers **translation quality** — issues that
go beyond the per-string checks of RPY6xx. These rules detect
**cross-string** problems that signal copy-paste errors or
translator drift across files.

While RPY6xx catches "this string is broken", RPY8xx catches
"these strings disagree with each other" — bugs that confuse
players (same line shows different text in different scenes) and
break translation memory tools (Trados, memoQ, OmegaT).

---

## Rules in this family

### `RPY801` — Duplicate translation string in same file

**Severity:** `WARNING`

If the same `old` source string appears more than once in a
translation file, the second translation silently overrides the
first. The first translation is dead code — translators wasted
effort, and the override may be unintentional. Common copy-paste
error when duplicating translation blocks.

```renpy
# Bad — same file (game/tl/russian/script.rpy)
translate russian chapter1_a1b2:
    old "Hello"
    new "Привет"

translate russian chapter1_c3d4:
    old "Hello"
    new "Здравствуй"   # silently overrides "Привет"!

# Good — different source strings, no conflict
translate russian chapter1_a1b2:
    old "Hello"
    new "Привет"

translate russian chapter1_c3d4:
    old "Goodbye"
    new "Пока"
```

Why this is bad:

- The first translation ("Привет") is dead code — wasted effort.
- The override may be unintentional — the translator duplicated a
  block and forgot to change the source string.
- Translation memory tools get confused — they see two different
  translations for the same source and pick one arbitrarily.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy801)

---

### `RPY802` — Inconsistent translation across files in same language

**Severity:** `WARNING`

The same source string is translated to **different** `new` strings
in different files within the **same language directory**. This
confuses players (same line shows different text in different
scenes) and breaks translation memory tools.

```renpy
# Bad — game/tl/russian/common.rpy
translate russian chapter1_a1b2:
    old "Hello"
    new "Привет"

# Bad — game/tl/russian/dialogue.rpy (same language, different translation)
translate russian chapter1_c3d4:
    old "Hello"
    new "Здравствуй"   # inconsistent!

# Good — game/tl/russian/common.rpy
translate russian chapter1_a1b2:
    old "Hello"
    new "Привет"

# Good — game/tl/russian/dialogue.rpy (consistent)
translate russian chapter1_c3d4:
    old "Hello"
    new "Привет"   # consistent across files
```

Why this is bad:

- Player sees "Привет" in scene A and "Здравствуй" in scene B for
  the same English source — looks like a bug.
- Translation memory tools (Trados, memoQ) record one translation
  per source string. Inconsistency causes them to flag every
  occurrence as "needs review", multiplying translator effort.
- Some players will assume the localization is incomplete or
  machine-translated.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy802)

---

## How Senpy detects duplicates and inconsistencies

Senpy scans every `.rpy` file in `game/tl/<lang>/` for each
language:

1. **Per-file pass** (`RPY801`): For each file, build a
   `{old_string: new_string}` map. If an `old` appears twice,
   the second one's `new` overrides the first — report both.
2. **Cross-file pass** (`RPY802`): For each language, build a
   global `{old_string: set(new_strings)}` map across all files.
   If a single `old` maps to multiple distinct `new` strings,
   report all occurrences.

The cross-file pass is what catches the "translator worked on
file A and file B independently, didn't realize they were
translating the same source string differently" pattern.

---

## Common patterns caught

### Copy-paste error

Translator copies a `translate russian chapter1_a1b2:` block to
start a new translation, but forgets to change the `old "..."` line
to the new source string. They end up with two blocks translating
"Hello" to different strings — `RPY801` catches it.

### Translator drift

Translator works on `common.rpy` one week, `dialogue.rpy` the
next. They translate `"Hello"` as `"Привет"` in the first, then as
`"Здравствуй"` in the second (maybe they forgot the first
translation, or the second felt more appropriate at the time).
`RPY802` catches the inconsistency.

### CAT tool round-trip

A CAT tool exports `.po` files, a translator edits them, the build
script converts back to `.rpy`. If the CAT tool's segmentation
differs from the original `.rpy` structure, the same source string
might end up translated twice with slight variations — `RPY801`
flags it.

---

## Auto-fix summary

| Rule | Auto-fixable |
|---|---|
| `RPY801` | ❌ — requires translator to pick one translation |
| `RPY802` | ❌ — requires translator to pick one translation |

These rules detect but don't fix — picking the "right" translation
is a human judgment call.

---

## Worked example — fixing RPY802 inconsistency

You run Senpy:

```bash
senpy /path/to/game --tag translations
```

Output (excerpt):

```
game/tl/russian/common.rpy:14
 14 │     new "Привет"
 [WARNING] RPY802: Inconsistent translation across files
 "Hello" is translated as "Привет" here but as "Здравствуй" in
 game/tl/russian/dialogue.rpy:42. Pick one translation and use
 it consistently.

game/tl/russian/dialogue.rpy:42
 42 │     new "Здравствуй"
 [WARNING] RPY802: Inconsistent translation across files
 Same source string "Hello" — see game/tl/russian/common.rpy:14.
```

You decide which translation to keep. "Привет" is more casual and
fits the game's tone, so you update `dialogue.rpy`:

```renpy
# game/tl/russian/dialogue.rpy:42
translate russian chapter1_c3d4:
    old "Hello"
    new "Привет"   # ← was "Здравствуй", now consistent
```

Re-run Senpy to verify:

```bash
senpy /path/to/game --tag translations
# No more RPY802 reports for "Hello" in Russian.
```

---

## Tags

All RPY8xx rules are tagged `translations` (and indirectly related
to `quality`, though Senpy doesn't have a `quality` tag yet).

```bash
senpy /path/to/game --tag translations   # all translation rules
senpy /path/to/game --tag translations --info   # include HINT-level
```

---

## What's next?

- [RPY6xx — Translations](rpy6xx-translations.md) — per-string
  translation rules (variable mismatch, tag mismatch, empty
  strings).
- [Ren'Py Translation Checker](../renpy-translation-checker.md) —
  the full `--coverage` documentation and worked examples.
- [All 51 rules](index.md) — back to the navigator.
- [RULES.md in repo](https://github.com/Xilleet/senpy/blob/main/RULES.md)
  — canonical reference.
