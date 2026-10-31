<p align="center">
  <a href="README.md"><b>English</b></a> | <a href="README_ru.md"><b>Русский</b></a>
</p>

# Senpy (`senpy-linter`)

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/Ren'Py-6.99%20%7C%207%20%7C%208-ff69b4?logo=renpy&logoColor=white" alt="Ren'Py 6.99 / 7 / 8">
  <img src="https://img.shields.io/badge/Rules-45-orange" alt="45 Rules">
  <img src="https://img.shields.io/badge/Speed-77k%20lines%20in%200.04s%20(cached)-brightgreen" alt="Speed: 77k lines in 0.04s">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License: MIT">
  <br>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-blue" alt="Platform: Windows | Linux | macOS">
  <img src="https://img.shields.io/badge/LSP-20%2B%20handlers-purple" alt="LSP: 20+ handlers">
  <img src="https://img.shields.io/badge/Plugins-API%20v1.0-teal" alt="Plugin API v1.0">
  <img src="https://img.shields.io/badge/tests-689%20passed-success" alt="689 tests passed">
</p>

<p align="center">
  <b>"Notice me, Senpy! (⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄)"</b><br>
  <i>Fast semantic linter, control-flow analyzer, and language server for Ren'Py visual novels.</i>
</p>

![](https://github.com/Xilleet/senpy/blob/main/docs/images/senpy-lsp-demo.gif)

---

## Quick Install

**CLI / CI / Linux / macOS:**
```bash
pip install senpy-linter
```

**VS Code Extension (Windows, zero Python setup):**
Download the latest `senpy-vscode-X.X.X.vsix` from the [Releases](https://github.com/Xilleet/senpy/releases) page → Install from VSIX in VS Code.

---

## What's New in 0.6.0

| Feature | Description |
|---|---|
| **Plugin System** | Write your own lint rules as pip packages. Senpy discovers them automatically via `entry_points`. [Plugin Guide →](https://github.com/Xilleet/senpy/blob/main/examples/my_senpy_plugin/MY_SENPY_PLUGIN_README.md) |
| **Plugin Security** | Trust-on-first-use model. First load prompts `[y/N]`, persists to `~/.senpy/trusted_plugins.json`. CI skips untrusted (fail-safe). |
| **Color Swatches** | `textDocument/documentColor` — hex colors (`#ff0000`) shown as clickable swatches in VS Code with color picker. |
| **Format on Save** | `textDocument/formatting` — Shift+Alt+F in VS Code runs Senpy's formatter (8 rules: indent, quotes, op/comma/colon spacing, trailing-WS, EOF, blank-lines). |
| **Signature Help** | `textDocument/signatureHelp` — parameter hints for `call label(...)` and `use screen(...)`. |
| **Call Hierarchy** | `textDocument/prepareCallHierarchy` — right-click label → "Find Callers" / "Find References" across project. |
| **Public API** | `senpy.api` module — stable contract for plugin developers and library users: `analyze_code(code) → list[Diagnostic]`. |
| **New Output Formats** | `--output-format junit` (XML for CI), `--output-format github` (PR annotations). |
| **`--show-fixes`** | Detailed report of what `--fix` changed (file:line: rule — fix title). |

Full changelog: [CHANGELOG.md](https://github.com/Xilleet/senpy/blob/main/CHANGELOG.md)

---

## Why You Need This

`renpy lint` catches syntax errors, but does not catch the bugs that actually
ship to players. These are real bugs that Senpy would have caught before
release:

### Bug 1 — Save-breaking `define` mutation

```renpy
define player_gold = 100

label spend_gold:
    $ player_gold -= 50    # ← mutates a `define`
    "You have [player_gold] gold."
```

**Symptom:** Game works in dev. Players report `Exception: define player_gold is not revertable`
on rollback, or save files silently corrupt after loading an old save.

**Senpy catches it:** `RPY105` (define mutation) fires at lint time.

---

### Bug 2 — `NameError` after loading a save

```renpy
label start:
    jump intro

label intro:
    $ greeted = True
    "Hello!"

label continue_story:
    if greeted:    # ← `greeted` not declared with `default`
        "Hi again!"
```

**Symptom:** Game works on first playthrough. Players who load a save at
`continue_story` (skipping `intro`) hit `NameError: name 'greeted' is not defined`.

**Senpy catches it:** `RPY104` (dynamic assignment without `default`).

---

### Bug 3 — Branch asymmetry (uninitialized read)

```renpy
label branch_demo:
    menu:
        "Take the sword":
            $ has_sword = True
        "Leave it":
            pass       # ← has_sword never set in this branch

    if has_sword:       # ← MAYBE_SET read
        "You swing!"
```

**Symptom:** Game works for players who take the sword. Players who leave it
hit `NameError: name 'has_sword' is not defined` (or in rollback, the variable
silently retains a previous playthrough's value).

**Senpy catches it:** `RPY404` (reading MAYBE_SET variable) and `RPY401`
(branch asymmetry).

---

### Bug 4 — Wrong collection method (`AttributeError` at runtime)

```renpy
label add_item:
    $ inventory.add("sword")    # ← list has no .add() method
```

**Symptom:** `AttributeError: 'list' object has no attribute 'add'` the first
time a player picks up an item. Tested paths miss it; untested paths crash.

**Senpy catches it:** `RPY108` (incompatible collection method) with QuickFix
suggesting `.append()`.

---

### Bug 5 — Unused image asset (dead weight in your build)

```renpy
# 200 image definitions, only 30 ever shown on screen
image bg_old_castle = "old_castle.png"   # ← left over from cut content
image bg_old_forest = "old_forest.png"   # ← unused
```

**Symptom:** Build size balloons. Players download 500MB instead of 200MB.
Nobody notices until a Steam reviewer complains about download size.

**Senpy catches it:** `RPY701` (unused define), `RPY702` (unused transform),
`RPY703` (unused screen).

---

### Bug 6 — Translation interpolation breakage

```renpy
# game/script.rpy
$ player_name = "Hero"
"Welcome, [player_name]!"     # ← English source

# game/tl/russian/script.rpy
translate russian welcome_1:
    "Добро пожаловать, [player]!"   # ← typo: player instead of player_name
```

**Symptom:** Russian players see `Добро пожаловать, [player]!` literally
(interpolation variable doesn't exist). English build works fine.

**Senpy catches it:** `RPY601` (broken interpolation variable in translation).

---

### The pattern

Every bug above:

1. Slips past `renpy lint` (which only checks syntax + label targets).
2. Survives dev playtesting (devs always pick the "interesting" branch).
3. Surfaces only after release — via Steam reviews, Discord screenshots,
   or itch.io bug reports.
4. Costs hours of "works on my machine" debugging because the player can't
   reproduce it in front of you.

Senpy catches them at lint time — before they ship. **That's why you need it.**

For the full list of 45+ rules with examples, see **[RULES.md](https://github.com/Xilleet/senpy/blob/main/RULES.md)**.

---

## Why Senpy?

The standard built-in `renpy lint` command only checks for basic syntax errors and broken label targets. It is blind to deep runtime Python execution issues, rollback desynchronizations, and save-file corruptions. Consequently, critical `NameError` and `KeyError` crashes often slip into production builds and are only discovered after dozens of hours of manual playtesting.

**Senpy** provides comprehensive static semantic analysis without requiring the Ren'Py SDK runtime:

* **Zero-Setup Standalone VSIX:** Windows extension packages bundle a self-contained runtime — writers and narrative designers don't need Python, virtual environments, or `pip` installed.
* **High Throughput & Disk Serialization:** Analyzes **77,000+ lines in ~3.5s on cold start and 0.04s incrementally** via two-tier `.senpy_cache/` disk serialization.
* **Save Game & Rollback Safety:** Catches dangerous `define` mutations (`RPY105`), non-revertable types (`RPY106`), dynamic assignments missing `default` (`RPY104`), and type-taint conflicts (`RPY108`).
* **Init Phase Dependency Graph:** Analyzes alphabetical file loading order in `init python:` to prevent runtime `NameError` crashes on startup (`RPY109`).
* **Arity & Signature Checking:** Verifies parameter counts and keyword arguments on `call label(...)` (`RPY310`) and `use screen(...)` (`RPY207`).
* **Branching Dataflow Analysis:** Traces nested `if/elif/else` and `menu:` branches to ensure variables aren't evaluated in an uninitialized `MAYBE_SET` state (`RPY401`, `RPY404`).
* **Screen & UI Action Inspector:** Catches predictive state mutations (`RPY201`), imperative loops (`RPY205`), dead buttons (`RPY203`), function calls in actions (`RPY206`), and inspects string targets in screen Actions (`SetVariable`, `ToggleVariable`, `Show`, `ShowMenu`, `Hide`) for typos and missing declarations (`RPY202`, `RPY204`).
* **ATL Transforms & Transitions:** Validates custom and built-in positions/transforms in `show ... at <transform>` and transitions in `with <transition>`, catching runtime `NameError` typos with QuickFix suggestions (`RPY502`).
* **Collection Method Guard:** Detects incompatible method invocations on known types (`list.add()` → `.append()`, `dict.append()`, `str.pop()`) before runtime `AttributeError` crashes occur (`RPY108`).
* **Translation Validator & Coverage:** Audits `game/tl/` formatting, catches broken interpolation variables (`RPY601`), and calculates localization completion metrics via `senpy --coverage`.
* **Runtime Crash Inspector:** Parses `traceback.txt` post-mortem crash logs, explaining failures in human-readable terms (`senpy --traceback`).
* **Dead Code Detection:** Finds unused `define` constants (`RPY701`), unused `transform` definitions (`RPY702`), and unused `screen` definitions (`RPY703`).

---

## LSP & VS Code Features

Senpy includes a full **Language Server Protocol** implementation with 20+ handlers:

| Feature | Shortcut | Description |
|---|---|---|
| **Diagnostics** | automatic | Real-time error/warning squiggles (~0.04s incremental cache) |
| **Go to Definition** | `F12` | Jump to label/screen/variable/asset definitions |
| **Hover** | hover | Docs for 220+ Ren'Py API functions |
| **Autocomplete** | `Ctrl+Space` | Labels, screens, transforms, variables, image attributes |
| **Document Symbols** | `Ctrl+Shift+O` | Outline view with labels/screens/transforms |
| **Workspace Symbol** | `Ctrl+T` | Global symbol search across all files |
| **Rename** | `F2` | Rename label → updates all `jump`/`call` references |
| **Find All References** | `Shift+F12` | All jump/call sites for a label |
| **Code Folding** | automatic | Collapse `label`/`screen`/`menu`/`init` blocks |
| **Document Highlight** | cursor | Highlight all occurrences of word in file |
| **QuickFix** | `Ctrl+.` | Auto-fix suggestions (tabs→spaces, smart quotes, unclosed tags) |
| **Color Swatches** | `0.6.0+` | Hex color literals shown as clickable color picker |
| **Format Document** | `Shift+Alt+F` | Run Senpy formatter (8 rules) |
| **Format Selection** | `Ctrl+K Ctrl+F` | Format selected range |
| **Signature Help** | `0.6.0+` | Parameter hints for `call label(...)` / `use screen(...)` |
| **Call Hierarchy** | `0.6.0+` | Right-click → "Find Callers" / "Find References" |
| **Story Graph** | command | Interactive Mermaid.js flowchart of all labels and jumps |

![](https://github.com/Xilleet/senpy/blob/main/docs/images/senpy-vscode-autocomplete.png)

---

## Plugin System

Senpy 0.6.0 introduces a **plugin system** — write your own lint rules as pip packages.

### Quick start

```bash
# 1. Create a plugin project (see example below)
cd examples/my_senpy_plugin
pip install -e .

# 2. Run Senpy — it discovers your plugin automatically
senpy /path/to/game
# First run: "Plugin 'my-senpy-plugin' wants to load. Trust and enable? [y/N]"
```

### Write your own rule in 30 lines

```python
from senpy.api import Diagnostic
from senpy.plugins import Rule, RuleContext, RuleMeta, register_rule

PLUGIN_API_VERSION = "1.0"

@register_rule("RPY902")
class TodoCommentRule(Rule):
    meta = RuleMeta(
        code="RPY902",
        docs="Detects TODO comments left in code",
        severity="HINT",
        tags=["productivity"],
    )

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        diags = []
        for i, line in enumerate(ctx.lines, start=1):
            if "TODO" in line.upper():
                diags.append(Diagnostic(
                    file_path=ctx.file_path, line_number=i,
                    line_content=line, code="RPY902",
                    message=f"TODO comment: {line.strip()}",
                    severity="HINT",
                ))
        return diags
```

Full guide: **[Plugin Development README](https://github.com/Xilleet/senpy/blob/main/examples/my_senpy_plugin/MY_SENPY_PLUGIN_README.md)**

---

## Usage

```bash
# Analyze a Ren'Py game directory
senpy "path/to/game"

# Automatically apply safe fixes (unclosed tags, smart quotes, tab indents)
senpy "path/to/game" --fix

# Show what was fixed (detailed report)
senpy "path/to/game" --fix --show-fixes

# Calculate translation completion metrics
senpy "path/to/game" --coverage

# Generate project documentation (GDD / Wiki)
senpy "path/to/game" --export-wiki "PROJECT_WIKI.md"

# Generate Python type stubs (.pyi) for Pylance / MyPy
senpy "path/to/game" --stubs

# Inspect a Ren'Py runtime crash log
senpy --traceback "path/to/traceback.txt"

# One-click GitHub Actions workflow generator
senpy --init-ci

# Generate 'senpy_defaults.rpy' for missing default variables
senpy "path/to/game" --defaults

# Export story flow as Mermaid.js diagram
senpy "path/to/game" --graph-file "story_graph.md"

# Generate HTML report with interactive story graph
senpy "path/to/game" --export-html "report.html"

# Output in SARIF, JSON, JUnit XML, or GitHub Actions format
senpy "path/to/game" --output-format sarif --output-file senpy.sarif
senpy "path/to/game" --output-format json
senpy "path/to/game" --output-format junit
senpy "path/to/game" --output-format github

# List all available rules
senpy --rules

# Enable tsundere mode
senpy "path/to/game" --tsundere
```

![](https://github.com/Xilleet/senpy/blob/main/docs/images/senpy-cli-diagnostics.png)

![](https://github.com/Xilleet/senpy/blob/main/docs/images/senpy-summary-table.png)

![](https://github.com/Xilleet/senpy/blob/main/docs/images/senpy-cli-warnings.png)

---

## Rules Overview

Senpy includes **45 specialized semantic rules** across 8 categories:

| Series | Category | Description |
| :--- | :--- | :--- |
| **RPY0xx** | Indentation & Formatting | Tab characters (`RPY001`), smart quotes in code (`RPY002`). |
| **RPY1xx** | Variables, State & APIs | Missing `[var]` references, `NameError` on `+=`, `define` mutations, deprecated APIs (`RPY107`), type taints (`RPY108`), init load order (`RPY109`). |
| **RPY2xx** | Screens & UI | Predictive mutations (`RPY201`), dead buttons (`RPY203`), missing screens (`RPY204`), imperative loops (`RPY205`), parameter mismatches (`RPY207`). |
| **RPY3xx** | Dialogue & Story Flow | Unclosed tags (`RPY301`), broken jumps (`RPY302`), dead labels (`RPY303`), duplicate labels (`RPY307`), story islands (`RPY309`), call args (`RPY310`). |
| **RPY4xx** | Branching & Logic | Menu branch asymmetry (`RPY401`), empty choices (`RPY402`), contradictions (`RPY403`), `MAYBE_SET` reads (`RPY404`). |
| **RPY5xx** | Assets & Media | Missing audio (`RPY501`), unresolved sprites (`RPY502`), unused assets (`RPY503`), unregistered channels (`RPY505`). |
| **RPY6xx** | Translations | Variable mismatches (`RPY601`), tag mismatches (`RPY602`), empty strings (`RPY603`). |
| **RPY7xx** | Dead Code | Unused `define` (`RPY701`), unused `transform` (`RPY702`), unused `screen` (`RPY703`). |

Full descriptions, rationale, and examples: **[RULES.md](https://github.com/Xilleet/senpy/blob/main/RULES.md)**

---

## Configuration (`senpy.toml`)

```toml
[tool.senpy]
decompile = true
max_errors = 50

ignore = [
    "RPY104",  # Dynamic assignments without default
    "RPY303",  # Unreferenced labels (dynamic routers)
]

[tool.senpy.severity]
RPY104 = "ERROR"   # Elevate to build-breaking
RPY308 = "INFO"    # Demote fallthrough to info
```

### Inline Suppression (`# noqa`)

```renpy
"Warning: {b}unclosed style"  # noqa
$ dynamic_var = 1             # noqa: RPY104
```

---

## GitHub Actions Integration

```bash
senpy --init-ci  # generates .github/workflows/senpy.yml
```

Or manually create `.github/workflows/senpy.yml`:

```yaml
name: Senpy Code Scanning
on:
  pull_request:
    branches: [ "main", "master" ]
jobs:
  lint:
    runs-on: ubuntu-latest
    permissions:
      security-events: write
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install senpy-linter
      - run: senpy game/ --output-format sarif --output-file senpy.sarif
        continue-on-error: true
      - uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: senpy.sarif
```

---

## Safe Sandbox Decompilation

When analyzing game distributions or mods without source code, Senpy detects standalone `.rpyc` files:

1. Copies `.rpyc` into an isolated OS temporary directory.
2. Prompts to download `unrpyc` automatically if not present.
3. Analyzes decompiled scripts entirely within the sandbox.
4. Cleans up — your project directory stays unmodified.

---

## Troubleshooting: Common Errors Caught by Senpy

Senpy catches runtime crashes before you launch the game. Here are common errors and the Senpy rules that prevent them:

| Runtime Error | Senpy Rule | What it catches |
| :--- | :---: | :--- |
| `NameError: name 'x' is not defined` on load | `RPY104` | `$ x = 1` inside a label without a top-level `default x = 0` — variable won't survive save/load |
| `NameError: name 'x' is not defined` in `if` | `RPY103` | `if x:` where `x` was never declared via `default` or `define` |
| `NameError: name 'x' is not defined` after `menu` | `RPY401` | Variable defined in one `menu:` branch but missing in another — crashes if player picks the wrong path |
| `NameError` on game launch (`init` phase) | `RPY109` | Function/class used in `init python:` before it's defined (alphabetical file load order violation) |
| `KeyError: 'player_name'` in dialogue | `RPY101` | Typo in `[player_name]` interpolation — variable doesn't exist |
| `KeyError` in translation string | `RPY601` | Translation `new "..."` has different `[var]` than original `old "..."` |
| `TypeError: unsupported operand type(s) for +=` | `RPY108` | Type taint conflict (e.g., `str += int`) or invalid method like `list.append()` on a `dict` |
| `AttributeError: 'list' object has no attribute 'add'` | `RPY108` | Wrong method on collection type (e.g., `my_list.add()` instead of `.append()`) |
| `ScriptError: Label 'xxx' is not defined` | `RPY302` | `jump xxx` or `call xxx` to a label that doesn't exist |
| `SyntaxError: tab/indent mismatch` | `RPY001` | Tab characters in indentation (Ren'Py requires 4 spaces) |
| Game crashes after loading a save | `RPY104` / `RPY105` | Variable created with `$` instead of `default`, or `define` constant mutated |
| Screen UI freezes / FPS drops | `RPY201` / `RPY205` | Direct state mutation inside screen or heavy `for`/`while` loops in screen language |

> **Tip:** Run `senpy path/to/game --fix` to auto-fix the safe ones (`RPY001`, `RPY002`, `RPY301`), or use **QuickFix** (`Ctrl+.`) directly in VS Code.

---

## Contributing

Contributions, bug reports, and rule suggestions are welcome.

1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/NewRule`).
3. Commit your changes (`git commit -m 'feat: add RPY901 check'`).
4. Ensure test suite passes (`pytest`).
5. Open a pull request.

Want to write a plugin instead of contributing to core? See the **[Plugin Development Guide](https://github.com/Xilleet/senpy/blob/main/examples/my_senpy_plugin/MY_SENPY_PLUGIN_README.md)**.

---

## License

Distributed under the MIT License. Free for commercial and non-commercial visual novel development.
