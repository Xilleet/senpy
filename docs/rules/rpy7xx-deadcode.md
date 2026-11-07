---
title: RPY7xx — Dead Code Detection Rules
description: RPY7xx rules cover Ren'Py dead code detection — unused define (RPY701), unused transform (RPY702), unused screen (RPY703), unused default (RPY704), unused screen parameter (RPY705), unused transform parameter (RPY706), and unused audio channel registration (RPY707).
tags:
  - rules
  - dead-code
  - rpy7xx
---

# RPY7xx — Dead Code Detection Rules

The RPY7xx family covers **dead code detection** — declarations
that exist but are never referenced. These rules are severity
`HINT` (hidden by default — use `--info` or `info = true` to see
them), because dead code is cosmetic: it doesn't crash the game,
but it bloats the project and confuses future maintainers.

These rules are most useful during:

- **Pre-release audit** — find leftover content from cut routes.
- **Refactoring** — verify that "I removed the only use of this,
  is it safe to delete the declaration?"
- **Onboarding** — a new contributor can run Senpy to see what's
  actually used vs what's dead.

---

## Rules in this family

### `RPY701` — Unused `define` constant

**Severity:** `HINT`

A `define` statement declares a constant, but if no code
references it, it adds dead weight to the project and may confuse
future maintainers.

```renpy
# Bad — never referenced anywhere
define DEBUG_MODE = False

# Good — used somewhere in the codebase
define DEBUG_MODE = False
# ... later:
if DEBUG_MODE:
    "Debug info"
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy701)

---

### `RPY702` — Unused `transform` definition

**Severity:** `HINT`

A `transform` is declared but never applied to any `show`/`scene`
statement via `at <transform>`. Dead code that increases project
size without benefit.

```renpy
# Bad — never applied
transform slide_in:
    easein 0.5 xoffset 100
# ...no `show X at slide_in` anywhere

# Good — applied
transform slide_in:
    easein 0.5 xoffset 100
show eileen at slide_in
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy702)

---

### `RPY703` — Unused `screen` definition

**Severity:** `HINT`

A `screen` is declared but never shown via `show screen`, `call
screen`, or `use` statement. Dead UI code increases maintenance
burden and may hide stale logic.

```renpy
# Bad — never called
screen debug_overlay():
    text "Debug info"
# ...no `show screen debug_overlay` anywhere

# Good
screen debug_overlay():
    text "Debug info"
# ...later:
show screen debug_overlay
```

Note: screens referenced dynamically (via string expressions like
`show screen "debug_" + name`) are exempt — Senpy can't statically
resolve dynamic references.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy703)

---

### `RPY704` — Unused `default` variable

**Severity:** `HINT`

A `default` variable is declared but never referenced anywhere in
the project. Unlike `define` constants (RPY701), `default` variables
**persist across saves** — an unused one wastes save-file space
and increases cognitive load.

```renpy
# Bad — never read
default unused_setting = "never referenced"
default debug_counter = 0
label start:
    return

# Good
default player_gold = 100
label start:
    $ player_gold -= 10
    return
```

Note: variables referenced in dialogue interpolation (`[var]`) count
as used.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy704)

---

### `RPY705` — Unused screen parameter

**Severity:** `HINT`

A parameter declared in `screen name(unused_param):` but never
referenced in the screen body. Clutters the signature and suggests
a forgotten refactor.

```renpy
# Bad — `unused_currency` never used in screen body
screen shop(unused_currency, gold):
    text "Gold: [gold]"

# Good — both parameters used
screen shop(currency, gold):
    text "Currency: [currency], Gold: [gold]"
```

Convention: prefix with `_` (e.g. `_unused`) to suppress
intentionally-unused parameters.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy705)

---

### `RPY706` — Unused `transform` parameter

**Severity:** `HINT`

A parameter declared in `transform slide(unused_speed):` but never
referenced in the transform body. Same rationale as `RPY705` —
cluttered signature, forgotten refactor.

```renpy
# Bad
transform slide_in(unused_speed):
    easein 0.5 xoffset 0

# Good
transform slide_in(speed):
    easein speed xoffset 0
```

Prefix with `_` to suppress intentionally-unused parameters.

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy706)

---

### `RPY707` — Unused audio channel registration

**Severity:** `HINT`

A channel registered via `renpy.music.register_channel("name", ...)`
but never used in any `play`/`queue`/`stop` statement. The
registration runs at init time and has no effect if nothing plays on
the channel.

```renpy
# Bad — channel registered, never played
init python:
    renpy.music.register_channel("ambient", mixer="sfx", loop=True)
label start:
    "No audio played on ambient channel."
    return

# Good — channel registered and used
init python:
    renpy.music.register_channel("ambient", mixer="sfx", loop=True)
label start:
    play ambient "rain.ogg"
    return
```

→ [Full reference](https://github.com/Xilleet/senpy/blob/main/RULES.md#rpy707)

---

## Common patterns caught

### Cut content leftover

After a major rewrite, you remove the `jump route_c` from the
story but forget to remove the `define`, `transform`, `screen`,
`default` declarations that supported it. `RPY701`–`RPY704` flag
them.

### Forgotten refactor

You change a screen's signature to add a parameter, but forget to
use it in the body. `RPY705` flags it.

### Old audio system

You used to play audio on a custom channel, then switched to
built-in channels. The `register_channel` call is still in `init
python:` but nothing plays on it. `RPY707` flags it.

---

## Auto-fix summary

None of the RPY7xx rules are auto-fixable — removing dead code is a
judgment call. Senpy reports, the developer decides.

For bulk cleanup:

```bash
# Get the list of all dead-code diagnostics
senpy /path/to/game --tag dead-code --info

# Or as JSON for scripting
senpy /path/to/game --tag dead-code --output-format json --output-file dead-code.json
```

Then review the JSON and delete the declarations you confirm are
dead.

---

## Tags

All RPY7xx rules are tagged `dead-code`. `RPY707` is also tagged
`audio`.

```bash
senpy /path/to/game --tag dead-code   # only dead-code rules
senpy /path/to/game --ignore-tag dead-code   # skip dead-code rules
```

Useful for CI:

```bash
# Fail CI if any new dead code is introduced (compare to baseline)
senpy /path/to/game --tag dead-code --info --output-format json > current.json
diff baseline.json current.json
```

---

## What's next?

- [RPY5xx — Assets & Media](rpy5xx-assets.md) — unused assets on
  disk (related but for files, not code).
- [RPY3xx — Story Flow](rpy3xx-story.md) — `RPY303` (unreferenced
  labels) is similar in spirit but for labels, not declarations.
- [All 52 rules](index.md) — back to the navigator.
- [RULES.md in repo](https://github.com/Xilleet/senpy/blob/main/RULES.md)
  — canonical reference.
