---
title: RPY4xx — Branching & Logic Rules
description: RPY4xx rules cover Ren'Py branching and logic — menu branch asymmetry (RPY401), empty menu choices (RPY402), always-false conditions (RPY403), and MAYBE_SET variable reads after branches (RPY404). These catch bugs that only surface when a player picks a specific choice.
tags:
  - rules
  - branching
  - flow
  - rpy4xx
---

# RPY4xx — Branching & Logic Rules

The RPY4xx family covers **branch-sensitive dataflow** — the rules
that catch bugs only some players see. These are the hardest bugs
to find by playtesting, because the developer always picks the
"interesting" route and never sees the bug.

Senpy's `StoryFlowAnalyzer` (in `senpy/rules/flow.py`) tracks
variable state (`DECLARED`, `MAYBE_SET`, `GUARANTEED`) across
`if/elif/else` and `menu:` branches. It can detect when a variable
is set in one branch but read after the branch — crashing for
players who took the other branch.

---

## Rules in this family

### `RPY401` — Variable defined in one menu choice but missing in another

**Severity:** `WARNING`

Branching asymmetry: if Choice A assigns `$ torch = True` but
Choice B does not, picking Choice B and later checking `if torch:`
causes a fatal `NameError`.

```renpy
# Bad — torch only set in one branch
menu:
    "Take torch":
        $ torch = True
    "Walk in dark":
        pass
if torch:   # NameError if player walked in dark!
    "Lighting the way..."

# Good — declare with default
default torch = False
menu:
    "Take torch":
        $ torch = True
    "Walk in dark":
        pass
if torch:
    "Lighting the way..."
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy401)

---

### `RPY402` — Empty menu choice

**Severity:** `WARNING`

A choice block without statements immediately falls through into
the next label or dialogue.

```renpy
# Bad — "Give up" has no body, falls through
menu:
    "Give up":
    "Fight":
        "Battle!"

# Good
menu:
    "Give up":
        return
    "Fight":
        "Battle!"
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy402)

---

### `RPY403` — Always-false condition

**Severity:** `WARNING`

Conditions like `if False:` or `if x and not x:` can never evaluate
to true. The block is dead code.

```renpy
# Bad
if False:
    "This branch will never execute."

# Good
if has_secret_item:
    "Secret branch!"
```

Senpy also detects tautologies (`if x or not x:` — always true) and
contradictions (`if x and not x:` — always false).

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy403)

---

### `RPY404` — Variable in MAYBE_SET state evaluated after menu branch

**Severity:** `WARNING`

If a variable is only defined in one choice of a `menu:`, picking an
alternate choice and subsequently evaluating `if var:` or
interpolating `[var]` will crash with `NameError` or `KeyError`.

```renpy
# Bad — found_gem only set in one choice
menu:
    "Look into the chest":
        $ found_gem = True
    "Walk past":
        pass

if found_gem:   # RPY404: crashes if player walked past!
    "You admire the gem."

# Good — declare with default
default found_gem = False
menu:
    "Look into the chest":
        $ found_gem = True
    "Walk past":
        pass
```

`RPY404` is closely related to `RPY401`:

- `RPY401` reports at the **assignment** site (the `menu` choice
  that's missing the assignment).
- `RPY404` reports at the **read** site (the `if var:` after the
  menu).

You'll often see both fire for the same bug — fix the assignment
side first (add a `default var = False`), then the read side
becomes safe.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy404)

---

## Common patterns caught

### Player reports "NameError after a choice"

The player picked Choice B, then later in the game hit
`NameError: name 'X' is not defined`. The variable `X` was only
set in Choice A's body. The developer never saw it because they
always pick Choice A.

`RPY401` reports at the menu (the assignment side).
`RPY404` reports at the read site (the `if X:` after the menu).

Both should fire — fix `RPY401` first by adding `default X = ...`
at the top level.

### "Why does this branch never run?"

A player reports a branch they expected to see is unreachable.
Possible cause: `if False:` or `if x and not x:`. `RPY403` catches
these statically.

### "Empty choice just falls through"

`RPY402` catches `menu` choices with no body. The player sees the
choice, picks it, and the next thing they see is the dialogue
*after* the menu — the choice did nothing.

---

## How Senpy detects MAYBE_SET

Senpy's `StoryFlowAnalyzer` tracks three states for every
variable at every point in the script:

- `DECLARED` — the variable has a `default` or `define` declaration.
  Safe to read.
- `GUARANTEED` — the variable has been assigned (e.g. inside a
  label that the game jumps to, after the assignment line). Safe
  to read.
- `MAYBE_SET` — the variable was assigned in some branches but
  not others. Reading it is unsafe — `NameError` for players who
  took the other branch.

`RPY404` fires when a `MAYBE_SET` variable is read after a
branch. The fix is to either:

- Add a `default var = ...` at the top level (promotes `MAYBE_SET`
  → `DECLARED` everywhere).
- Assign the variable in every branch (promotes `MAYBE_SET` →
  `GUARANTEED` after the branch).

---

## Auto-fix summary

| Rule | Auto-fixable | How |
|---|---|---|
| `RPY401` | ✅ (suggestion) | Reports include a concrete fix suggestion (`$ var = 0`) |
| `RPY404` | ❌ | Manual — add `default var = ...` |
| `RPY402` | ❌ | Manual — add a body or `return` to the empty choice |
| `RPY403` | ❌ | Manual — remove the dead branch or fix the condition |

For `RPY401` and `RPY104` (related — both about missing `default`
declarations), `senpy --defaults` generates a `senpy_defaults.rpy`
file with `default` declarations for every RPY104 and RPY401
variable in your project.

---

## Tags

All RPY4xx rules are tagged `branching`.

```bash
senpy /path/to/game --tag branching   # only branching rules
```

---

## What's next?

- [RPY1xx — Variables & State](rpy1xx-state.md) — `default` vs
  `define`, the underlying mechanism for `RPY401` / `RPY404`.
- [RPY3xx — Story Flow](rpy3xx-story.md) — story islands and
  fallthrough.
- [All 52 rules](index.md) — back to the navigator.
- [RULES.md in repo](https://github.com/Xilleet/senpy/blob/main/RULES.md)
  — canonical reference.
