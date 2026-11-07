---
title: Ren'Py Linter — Find Bugs in Visual Novel Scripts Before Release
description: A Ren'Py linter finds script bugs before your players do. The built-in renpy lint catches syntax and reference errors, but does not specialize in deep semantic bugs. Senpy is a semantic linter that detects undefined variables, broken labels, save corruption, rollback desync, translation errors, and dead code — without requiring the Ren'Py SDK.
tags:
  - linter
  - renpy
  - getting-started
  - cluster-a
---

# Ren'Py Linter

A Ren'Py linter checks your visual novel scripts for bugs before you
ship them to players. Ren'Py ships with its own `renpy.exe lint` command,
but it focuses on syntax errors, broken `jump`/`call` targets, and
image/sprite references. A **semantic linter** like Senpy goes further — it understands Ren'Py's
domain model (variables, screens, translations, save persistence,
rollback) and catches the class of bugs that survive `renpy lint` and
only surface after release, when a player picks the wrong route or
loads an old save.

This page explains what a Ren'Py linter can and cannot catch, where the
built-in one stops, and where Senpy takes over.

---

## What does a Ren'Py linter check?

A complete Ren'Py linter checks five layers, in increasing depth:

| Layer | What it checks | Example bug | Caught by |
|---|---|---|---|
| **1. Syntax** | Tab indentation, smart quotes, file encoding, unescaped quotes | Tab in indentation → `SyntaxError` | `renpy lint` + Senpy |
| **2. References** | `jump`/`call` targets exist, `show` sprites exist, `play` audio exists | `jump bad_edd` (typo) → `ScriptError` | `renpy lint` + Senpy |
| **3. Semantics** | Variables declared before use, `define` not mutated, screen actions valid | `$ karma += 1` on `define` → save corruption on rollback | **Senpy only** |
| **4. Control flow** | Branch asymmetry, `MAYBE_SET` reads, dead branches, story islands | Variable set in one `menu` choice but read after both → `NameError` for some players | **Senpy only** |
| **5. Translation & save safety** | Translation variable mismatch, formatting tag mismatch, non-revertable types | `new "Hello, [player]"` (typo for `[player_name]`) → `KeyError` for non-English players | **Senpy only** |

The built-in `renpy lint` covers layers 1 and 2. Senpy covers all five.

---

## Where `renpy lint` stops and Senpy continues

The built-in `renpy lint` command launches the entire Pygame runtime and
executes `init python:` blocks. This gives it access to the full Ren'Py
environment — but it also makes it slow (30–40 seconds on a 70k-line
project) and blind to anything that happens at runtime after init:

- **Save file corruption** — `define player_gold = 100` mutated with
  `$ player_gold -= 50` corrupts saves on rollback. `renpy lint` doesn't
  catch this because the mutation only triggers when a player saves and
  loads.
- **Rollback desync** — using standard `random` or mutable `set()` breaks
  Ren'Py's rollback engine. `renpy lint` doesn't model rollback state.
- **Branch asymmetry** — `$ has_sword = True` in one menu choice but not
  another. `renpy lint` doesn't do branch-sensitive dataflow analysis.
- **Translation variable mismatch** — `new "Привет, [player]"` when the
  original was `"Hello, [player_name]!"`. `renpy lint` doesn't compare
  old/new string variables.
- **Dead code** — unused `define`/`transform`/`screen`. `renpy lint`
  checks unused images, but does not report unused defines, transforms,
  screens, or parameters.
- **Init order violations** — `NameError` at game launch because
  `configure_interface()` is called in `a_setup.rpy` but defined in
  `z_helpers.rpy`. `renpy lint` runs *after* the alphabetical file load,
  so it can't see this class of bug.

These bugs slip past `renpy lint`, survive dev playtesting (because
developers always pick the "interesting" branch), and surface only after
release — via Steam reviews, Discord screenshots, or itch.io bug reports.

---

## A 30-second example

Here is a `.rpy` file that `renpy lint` will pass, but Senpy will flag
with three rules:

```renpy
define player_gold = 100   # constant — but we mutate it later

label spend_gold:
    $ player_gold -= 50    # ← mutates a define constant!
    "You have [player_gold] gold."

label chest_event:
    menu:
        "Take the gem":
            $ found_gem = True   # only set in this branch
        "Walk past":
            pass

    if found_gem:    # ← MAYBE_SET read: crashes if player walked past
        "You admire the gem."

label forgotten_draft:    # ← never referenced by any jump/call
    "Old scene from a cut route."
```

### What Senpy reports

| Line | Rule | Severity | What it says |
|---|---|---|---|
| 4 | `RPY105` | ERROR | Direct mutation of `define` constant `player_gold` — breaks rollback and save serialization |
| 12 | `RPY404` | WARNING | `found_gem` is in MAYBE_SET state — defined only in one `menu` branch, evaluated after |
| 17 | `RPY303` | INFO | Label `forgotten_draft` is never referenced — dead code or abandoned draft |

### What `renpy lint` reports

Nothing. This code passes the built-in lint. The bugs only surface when:

- A player saves after `spend_gold`, then loads → save corrupts on
  rollback (`RPY105`).
- A player picks "Walk past" → `NameError: name 'found_gem' is not
  defined` (`RPY404`).
- A reviewer reads the source → `forgotten_draft` is dead weight
  (`RPY303`).

---

## How to use Senpy as a Ren'Py linter

### Install

```bash
pip install senpy-linter
```

### Run

```bash
senpy /path/to/your/renpy/game
```

### Output

Senpy prints:

1. One **Panel card** per diagnostic — file path, line, code, severity,
   message, and a snippet of the offending line.
2. A **summary table** — count of diagnostics per rule, sorted by
   frequency.
3. A **summary line** — "Found 4 error(s), 12 warning(s) across 87 file(s)
   (35,000 lines) in 0.342s".

You can also request other output formats:

```bash
senpy /path/to/game --output-format sarif --output-file senpy.sarif  # for GitHub Code Scanning
senpy /path/to/game --output-format json                              # for custom integrations
senpy /path/to/game --output-format github                            # for PR annotations
senpy /path/to/game --output-format junit --output-file junit.xml    # for Jenkins / GitLab
```

See [Output formats](renpy-github-actions.md) for all 7 formats.

### Auto-fix safe errors

Some errors are mechanically fixable:

```bash
senpy /path/to/game --fix
```

Fixes: tab → 4 spaces (`RPY001`), smart quotes → straight (`RPY002`),
unclosed text tags (`RPY301`). Mutating fixes are never applied
automatically — only safe, idempotent ones.

### Generate missing `default` declarations

If you have a lot of `$ var = ...` without `default` (RPY104), Senpy
can generate a starter file:

```bash
senpy /path/to/game --defaults
# writes senpy_defaults.rpy with `default` declarations for all RPY104 vars
```

Inspect the generated file and merge into your project.

---

## Senpy vs `renpy lint` — when to use which

| Use case | Tool |
|---|---|
| Quick syntax check before testing in Ren'Py | `renpy lint` — fast, gives you a "launch the game" baseline |
| Catching runtime crashes before release | **Senpy** — semantic, save/rollback, control-flow |
| CI on every PR | **Senpy** — `pip install senpy-linter`, no Ren'Py SDK needed in CI |
| Pre-release sanity sweep | Both — they catch different classes of bugs |

The two are **complementary, not replacements**. Run `renpy lint` for
SDK-level checks (it has access to the full Ren'Py environment), and
Senpy for everything else (semantic, save/rollback, translation,
control-flow, dead code). For the full 12-row comparison, see
[Senpy vs `renpy lint`](comparison.md).

---

## Common Ren'Py linting questions

### Is Senpy a drop-in replacement for `renpy lint`?

No. They overlap on layers 1–2 (syntax + reference checks), but diverge
on layers 3–5 (semantics, control flow, translation/save safety). Use
both — `renpy lint` for SDK-level checks, Senpy for semantic analysis.

### Does Senpy require the Ren'Py SDK?

No. Senpy is a standalone Python package (`pip install senpy-linter`).
It parses `.rpy` files directly. The bundled `senpy.exe` in the Windows
VSIX is a PyInstaller binary that includes its own Python — no install
needed on the user's machine.

### Can Senpy run in CI without a headless Ren'Py SDK?

Yes. That's the main reason Senpy exists — `renpy lint` in CI requires
downloading the Ren'Py SDK, setting up a headless X server on Linux, and
working around Pygame initialization. Senpy runs as a plain `pip install`
with no headless setup.

### Does Senpy support `.rpyc` files?

Yes. Senpy detects standalone `.rpyc` files (e.g. in a mod you don't
have source for), decompiles them in a sandbox using the vendored
`unrpyc` (pinned to a specific commit, SHA256-verified), and analyzes
the decompiled output. Your project directory is never modified — the
sandbox is in a temporary directory that is cleaned up after analysis.

### Does Senpy support `.rpa` archives?

Yes. Senpy can read the index of `.rpa` archives to check that audio
and image files referenced in scripts actually exist inside the
archive. This catches the "image file exists in archive but path is
wrong" class of bug.

### How fast is Senpy?

On a 70,000-line / 50-file project:

- **Cold start**: ~3.5 seconds
- **Incremental** (cache hit): ~0.04 seconds

Cache is on disk at `.senpy_cache/cache.pkl`, content-hashed (BLAKE2b).
Safe — `SafeCacheUnpickler` blocks dangerous modules (`os`, `sys`,
`subprocess`, etc.) even if added to the safe list.

---

## What's next?

- [**Ren'Py Static Analysis**](renpy-static-analysis.md) — the five
  layers of analysis in depth, with examples of bugs each layer catches.
- [**Ren'Py Error Checker**](renpy-error-checker.md) — map common
  runtime errors (`NameError`, `KeyError`, `AttributeError`,
  `ScriptError`) to the Senpy rule that catches them.
- [**Senpy vs `renpy lint`**](comparison.md) — the full 12-row
  comparison.
- [**All 51 rules**](rules/index.md) — browse the rule reference.
- [**CLI reference**](cli-reference.md) — every flag and subcommand.
