---
title: All Senpy Rules — 51 Rules Across 8 Categories
description: Senpy includes 51 specialized lint rules for Ren'Py visual novels, organized into 8 categories by prefix (RPY0xx through RPY8xx). Browse by category or search for a specific rule. Each rule links to the canonical RULES.md reference in the repository.
tags:
  - rules
  - reference
---

# All Senpy Rules

Senpy includes **51 specialized lint rules** for Ren'Py visual novels,
organized into 8 categories by prefix. This page is a navigator —
each category links to its detail page on this site, and each rule
links to its canonical entry in
[`RULES.md`](https://github.com/Xilleet/senpy/blob/main/RULES.md) in
the repository.

Browse by category, by severity, or by tag. To find a rule by code
in the terminal:

```bash
senpy rule show RPY104    # show one rule in detail
senpy rule list           # table of all 51 rules
senpy rule list --tag rollback    # filter by tag
```

---

## By category

| Category | Rules | Page |
|---|---|---|
| **RPY0xx** — Indentation & syntax | RPY001, RPY002, RPY100 | [RPY0xx — Formatting](rpy0xx-formatting.md) |
| **RPY1xx** — Variables & state | RPY101–RPY109 (9 rules) | [RPY1xx — State](rpy1xx-state.md) |
| **RPY2xx** — Screens & UI | RPY201–RPY208 (8 rules) | [RPY2xx — Screens](rpy2xx-screens.md) |
| **RPY3xx** — Story flow & dialogue | RPY301–RPY310 (10 rules) | [RPY3xx — Story](rpy3xx-story.md) |
| **RPY4xx** — Branching & logic | RPY401–RPY404 (4 rules) | [RPY4xx — Flow](rpy4xx-flow.md) |
| **RPY5xx** — Assets & media | RPY501–RPY505 (5 rules) | [RPY5xx — Assets](rpy5xx-assets.md) |
| **RPY6xx** — Translations | RPY601–RPY603 (3 rules) | [RPY6xx — Translations](rpy6xx-translations.md) |
| **RPY7xx** — Dead code | RPY701–RPY707 (7 rules) | [RPY7xx — Dead Code](rpy7xx-deadcode.md) |
| **RPY8xx** — Translation quality | RPY801, RPY802 (2 rules) | [RPY8xx — Translation Quality](rpy8xx-translation-quality.md) |

---

## By severity

### ERROR (build-breaking — fails CI)

These rules fail the build in CI (unless `--exit-zero` or
`errors_only = false` in `senpy.toml`):

- `RPY001` — Tab character in indentation
- `RPY002` — Smart/curly quotes in code statements
- `RPY100` — File is not valid UTF-8
- `RPY101` — Unresolved variable in dialogue interpolation
- `RPY102` — Augmented assignment before declaration
- `RPY103` — Undeclared variable in condition
- `RPY105` — Direct mutation of `define` constant
- `RPY108` — Type taint conflict or incompatible augmented assignment
- `RPY109` — Init phase dependency graph violation
- `RPY204` — Call/Show to non-existent screen
- `RPY206` — Direct function call in button action
- `RPY207` — Invalid parameters in screen call / use
- `RPY208` — Screen-local variable modified via global action
- `RPY301` — Unclosed text tag in dialogue
- `RPY302` — Jump or Call to non-existent label
- `RPY304` — Malformed color in `{color}` tag
- `RPY305` — Unescaped quotes inside dialogue string
- `RPY307` — Duplicate label declaration
- `RPY310` — Invalid argument count or keyword in `call` statement
- `RPY501` — Missing audio file
- `RPY505` (channel part) — Unregistered audio channel
- `RPY601` — Variable mismatch in translation string

### WARNING (visible by default, doesn't fail CI)

- `RPY104` — Dynamic assignment without top-level `default`
- `RPY106` — Usage of non-revertable Python types
- `RPY107` — Usage of deprecated / obsolete Ren'Py API
- `RPY201` — Direct state mutation inside screen
- `RPY202` — Screen accesses variable without `default`
- `RPY203` — Button without `action`
- `RPY205` — Imperative Python loop inside screen
- `RPY302` — (also reported as WARNING when a similar label exists)
- `RPY306` — Called label without `return`
- `RPY308` — Label preceded by regular statements (fallthrough hazard)
- `RPY309` — Story island / isolated subgraph unreachable from `start`
- `RPY401` — Variable defined in one menu choice but missing in another
- `RPY402` — Empty menu choice
- `RPY403` — Always-false condition
- `RPY404` — Variable in MAYBE_SET state evaluated after menu branch
- `RPY502` — Missing or mistyped sprite / background
- `RPY503` — Unused media asset on disk
- `RPY504` — Duplicate image declaration
- `RPY505` (voice loop part) — Voice channel loop
- `RPY602` — Formatting tag mismatch in translation string
- `RPY603` — Empty translation string (`new ""`)
- `RPY801` — Duplicate translation string
- `RPY802` — Inconsistent translation across files

### HINT (hidden by default, use `--info` to see)

- `RPY701` — Unused `define` constant
- `RPY702` — Unused `transform` definition
- `RPY703` — Unused `screen` definition
- `RPY704` — Unused `default` variable
- `RPY705` — Unused screen parameter
- `RPY706` — Unused transform parameter
- `RPY707` — Unused audio channel registration

### INFO (hidden by default, use `--info` to see)

- `RPY303` — Unreferenced / Dead label

---

## By tag

Senpy tags rules with 28 tags. Filter with `--tag` / `--ignore-tag`:

```bash
senpy /path/to/game --tag rollback state
senpy /path/to/game --ignore-tag dead-code
senpy /path/to/game --tag translations
```

| Tag | Rules it covers |
|---|---|
| `formatting` | RPY001, RPY002 |
| `variables` | RPY101, RPY102, RPY103 |
| `state` | RPY104, RPY105, RPY106 |
| `rollback` | RPY105, RPY106 |
| `deprecated` | RPY107 |
| `screen` | RPY201–RPY208 |
| `dialogue` | RPY301, RPY305 |
| `story` | RPY302, RPY303, RPY308, RPY309 |
| `branching` | RPY401–RPY404 |
| `assets` | RPY501–RPY503 |
| `audio` | RPY501, RPY505 |
| `translations` | RPY601, RPY602, RPY603, RPY801, RPY802 |
| `dead-code` | RPY303, RPY701–RPY707 |
| `accessibility` | RPY901 (plugin) |
| `productivity` | RPY902 (plugin) |

To see all tags:

```bash
senpy rule list --format json | python -c "import json,sys; rules=json.load(sys.stdin); print(sorted({t for r in rules for t in r.get('tags',[])}))"
```

---

## Quick browse

Browse a single category:

- [RPY0xx — Formatting](rpy0xx-formatting.md) — tabs, smart quotes, file encoding
- [RPY1xx — Variables & State](rpy1xx-state.md) — `default` vs `define`, init order, type taint
- [RPY2xx — Screens & UI](rpy2xx-screens.md) — screen actions, UI prediction, dead buttons
- [RPY3xx — Story Flow](rpy3xx-story.md) — tags, jumps, labels, fallthrough
- [RPY4xx — Branching](rpy4xx-flow.md) — menu asymmetry, MAYBE_SET, dead branches
- [RPY5xx — Assets & Media](rpy5xx-assets.md) — audio, images, transforms, channels
- [RPY6xx — Translations](rpy6xx-translations.md) — `game/tl/` variable/tag/empty checks
- [RPY7xx — Dead Code](rpy7xx-deadcode.md) — unused define/transform/screen/default/params
- [RPY8xx — Translation Quality](rpy8xx-translation-quality.md) — duplicates, inconsistencies

For the canonical reference with full code examples, see
[`RULES.md`](https://github.com/Xilleet/senpy/blob/main/RULES.md) in
the repository. Each rule on this site links to its `RULES.md` anchor
for the source of truth.
