---
title: RPY0xx — Indentation & Syntax Rules
description: RPY0xx rules cover Ren'Py indentation and syntax issues — tab characters (RPY001), smart quotes in code (RPY002), and non-UTF-8 file encoding (RPY100). These are the only rules that overlap with renpy lint.
tags:
  - rules
  - formatting
  - rpy0xx
---

# RPY0xx — Indentation & Syntax Rules

The RPY0xx family covers **text-level syntax** issues — the only
rules that overlap with `renpy lint`. Senpy reports them at the
file-parsing stage, before any semantic analysis.

These rules are mostly auto-fixable (`RPY001`, `RPY002`) or
actionable in your editor (`RPY100` — re-save with UTF-8 encoding).

---

## Rules in this family

### `RPY001` — Tab character in indentation

**Severity:** `ERROR` | **Auto-fix:** ✅ (`--fix`)

Ren'Py requires 4 spaces per indentation level. Tab characters cause
indentation mismatches and `SyntaxError` across different text
editors and operating systems.

```renpy
# Bad
label start:
	"Hello, world!"   # ← TAB character

# Good
label start:
    "Hello, world!"   # ← 4 spaces
```

Auto-fix: `senpy --fix` converts all tabs to 4 spaces. Or use
QuickFix in VS Code (`Ctrl+.`).

→ [Full reference in RULES.md](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy001)

---

### `RPY002` — Smart/curly quotes in code statements

**Severity:** `ERROR` | **Auto-fix:** ✅ (`--fix`)

Smart quotes (`"`, `"`, `'`, `'`) in **code** lines (not dialogue)
break Python parsing in `$`-statements and `init python:` blocks.
Dialogue lines are not affected — smart quotes in dialogue are
intentional (e.g. `"She said "Hello"."`).

```renpy
# Bad — code line with smart quotes
$ player_name = "Eileen"   # ← should be straight quotes

# Good
$ player_name = "Eileen"

# Dialogue — smart quotes are FINE here (RPY002 doesn't fire)
"Hello, "world"!"
```

Auto-fix: `senpy --fix` replaces smart quotes with straight quotes in
code lines. Dialogue is preserved.

→ [Full reference in RULES.md](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy002)

---

### `RPY100` — File is not valid UTF-8

**Severity:** `ERROR` | **Auto-fix:** ❌ (manual editor action)

Ren'Py reads all `.rpy` scripts as UTF-8. A file saved in another
encoding (e.g. Windows-1251, common in Russian projects) crashes the
game on load. Senpy skips such files, so they must be re-saved as
UTF-8.

```renpy
# Bad — file saved as Windows-1251
# bytes: b'\xcf\xf0\xe8\xe2\xe5\xf2' (not valid UTF-8)
# Senpy shows: RPY100 File is not valid UTF-8

# Good — same file re-saved as UTF-8
"Hello, world!"
```

**Fix:** Re-save the file with UTF-8 encoding in your editor.

- VS Code: bottom-right status bar → "Select Encoding" → "Save with Encoding" → UTF-8.
- Notepad++: Encoding menu → "Convert to UTF-8".
- Sublime Text: File → "Save with Encoding" → "UTF-8".

→ [Full reference in RULES.md](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy100)

---

## Auto-fix summary

| Rule | Auto-fixable | What `--fix` does |
|---|---|---|
| `RPY001` | ✅ | Convert tabs to 4 spaces |
| `RPY002` | ✅ | Replace smart quotes with straight in code lines |
| `RPY100` | ❌ | Re-save as UTF-8 in your editor |

To auto-fix everything fixable in your project:

```bash
senpy /path/to/game --fix --show-fixes
```

---

## Tag

All three rules are tagged `formatting`:

```bash
senpy /path/to/game --tag formatting   # run only these rules
senpy /path/to/game --ignore-tag formatting   # skip these rules
```

---

## What's next?

- [RPY1xx — Variables & State](rpy1xx-state.md) — `default`/`define`,
  init order, type taint.
- [All 53 rules](index.md) — back to the navigator.
- [RULES.md in repo](https://github.com/Xilleet/senpy/blob/main/RULES.md)
  — canonical reference with full examples.
