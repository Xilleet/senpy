---
title: RPY6xx — Translation Rules (game/tl/ files)
description: RPY6xx rules cover Ren'Py translation file validation — variable mismatch (RPY601), formatting tag mismatch (RPY602), and empty translation strings (RPY603). These rules check game/tl/<lang>/*.rpy files against the original scripts and catch bugs that only affect non-English players.
tags:
  - rules
  - translations
  - rpy6xx
---

# RPY6xx — Translation Rules

The RPY6xx family covers **translation file validation** — checks
on `game/tl/<lang>/*.rpy` files against the original `.rpy` files.
These rules catch bugs that only affect non-English players, which
means the developer (who plays in English) never sees them.

For deeper coverage (duplicates, inconsistencies across files),
see [RPY8xx — Translation Quality](rpy8xx-translation-quality.md).

For coverage metrics, see [Ren'Py Translation Checker](../renpy-translation-checker.md).

---

## Rules in this family

### `RPY601` — Variable mismatch in translation string

**Severity:** `ERROR`

If a translated string alters or misspells a dialogue variable
(`[var]`), rendering the translation causes a fatal `KeyError` at
runtime.

```renpy
# Bad — typo: should be [player_name]
old "Hello, [player_name]!"
new "Привет, [player]!"

# Good
old "Hello, [player_name]!"
new "Привет, [player_name]!"
```

Symptom if not fixed: non-English players see the literal
`[player]` text in their dialogue. The English build works fine.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy601)

---

### `RPY602` — Formatting tag mismatch in translation string

**Severity:** `WARNING`

Missing or altered formatting tags (`{b}`, `{color}`, `{i}`) in
translation strings cause unclosed text tags and visual glitches.

```renpy
# Bad — missing closing {/b}
old "Danger: {b}Hazard!{/b}"
new "Опасно: {b}Угроза!"

# Good
old "Danger: {b}Hazard!{/b}"
new "Опасно: {b}Угроза!{/b}"
```

Symptom if not fixed: the formatting tag (`{b}`) leaks into all
subsequent dialogue in that language. The English build works fine
because the `old` line has the closing tag.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy602)

---

### `RPY603` — Empty translation string (`new ""`)

**Severity:** `WARNING`

Leaving `new ""` empty for a non-empty original line will display
an empty, blank dialogue window to players in that language.

```renpy
# Bad — players see blank dialogue
old "Do you want to exit?"
new ""

# Good
old "Do you want to exit?"
new "Вы хотите выйти?"
```

Symptom: non-English players see an empty dialogue box where the
English player sees text. Easy to miss in playtesting because the
developer plays in English.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy603)

---

## How Senpy finds translation bugs

Senpy scans every `.rpy` file in `game/tl/<lang>/` and compares
each `old "..."` / `new "..."` pair against:

- The original `.rpy` file's dialogue lines (to verify `old` matches
  a real source string).
- The variable names in the `old` line vs the `new` line
  (`RPY601`).
- The formatting tags in the `old` line vs the `new` line
  (`RPY602`).
- The non-emptiness of `new` (`RPY603`).

The check runs at the **finalization stage** of analysis (after all
original `.rpy` files have been parsed), so it has access to the
full set of source strings.

---

## Coverage metrics

Beyond catching bugs, Senpy reports per-language completion
percentage:

```bash
senpy /path/to/game --coverage
```

Output (excerpt):

```
Translation Coverage
═══════════════════════════════════════════════════════════════════════════
Language    Strings    Translated    Empty    Coverage
───────────────────────────────────────────────────────────────────────────
russian      1,243       1,201          42       96.6%
spanish      1,243         876         367       70.5%
japanese     1,243       1,243           0      100.0%
───────────────────────────────────────────────────────────────────────────
```

The "Empty" column directly corresponds to `RPY603` reports — every
`new ""` is one empty translation string.

See [Ren'Py Translation Checker](../renpy-translation-checker.md)
for the full `--coverage` documentation.

---

## Common patterns caught

### Translator typo on variable name

The most common RPY601 cause. The translator (or CAT tool) sees
`[player_name]` and either:

- Typoes it as `[player]` or `[playername]`.
- Auto-corrects it (some CAT tools "fix" snake_case identifiers).
- Replaces it with the player's actual name placeholder for the
  target language (e.g. `[nom]` in French), which doesn't exist in
  Ren'Py's variable store.

### Tag lost in segment splitting

CAT tools split long strings at sentence boundaries. If `{b}` is
in one segment and `{/b}` is in another, the translation file ends
up with one half of the tag — `RPY602` catches it.

### Skipped segments

Translators sometimes skip segments they're unsure about, leaving
`new ""` as a placeholder. `RPY603` catches every empty translation.

---

## Auto-fix summary

| Rule | Auto-fixable |
|---|---|
| `RPY601` | ❌ — needs translator action |
| `RPY602` | ❌ — needs translator action |
| `RPY603` | ❌ — needs translator action |

Translation bugs are inherently human — Senpy can detect them but
not fix them. The fix is for the translator to revisit the flagged
strings.

---

## Tags

All RPY6xx rules are tagged `translations`:

```bash
senpy /path/to/game --tag translations   # only translation rules
senpy /path/to/game --ignore-tag translations   # skip translation rules
```

Useful in CI when you want to run translation checks only on PRs
that touch `game/tl/`:

```yaml
- name: Translation check
  if: contains(github.event.head_commit.modified, 'game/tl/')
  run: senpy game/ --tag translations --errors-only
```

---

## What's next?

- [RPY8xx — Translation Quality](rpy8xx-translation-quality.md) —
  duplicates and inconsistencies across files.
- [Ren'Py Translation Checker](../renpy-translation-checker.md) —
  the full `--coverage` documentation and worked examples.
- [All 53 rules](index.md) — back to the navigator.
- [RULES.md in repo](https://github.com/Xilleet/senpy/blob/main/RULES.md)
  — canonical reference.
