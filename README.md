[English](README.md) | [Русский](README_ru.md)

# Senpy (`senpy-linter`)

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Ren'Py-6.99%20%7C%207%20%7C%208-ff69b4?logo=renpy&logoColor=white" alt="Ren'Py 6.99 / 7 / 8">
  <img src="https://img.shields.io/badge/Speed-77k%20lines%20in%200.3s-brightgreen" alt="Blazingly Fast">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License: MIT">
  <img src="https://img.shields.io/badge/Code%20Style-Ruff-000000.svg" alt="Ruff">
</p>

<p align="center">
  <a href="README.md"><b>English</b></a> | <a href="README.ru.md"><b>Русский</b></a>
</p>

<p align="center">
  <b>"Notice me, Senpy! (⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄)"</b><br>
  <i>Blazingly fast semantic linter, control-flow analyzer, and personal tsundere for Ren'Py visual novels.</i>
</p>

---

## Why Senpy?

The standard built-in `renpy lint` only checks for basic syntax and broken labels. It is **completely blind** to runtime Python execution bugs. As a result, developers and QA teams often discover catastrophic `NameError` or `KeyError` crashes only after 40 hours of manual playtesting.

**Senpy** bridges this gap:

* **Blazingly Fast:** Analyzes **77,000+ lines across 50 files in ~0.3 seconds** *(tested on DDLC: Blue Skies, warm SSD cache)*.
* **Intra-Menu Flow Analysis:** Traces `menu:` choices to catch variables defined in one branch but missing in another.
* **Save Game Protection:** Enforces state management rules, warning about variables assigned without a top-level `default`.
* **Screen Safety Guard:** Prevents dangerous state mutations inside reactive screens that cause lag, redraw loops, and broken rollbacks.
* **Zero-Footprint `.rpyc` Sandbox:** Automatically decompiles compiled `.rpyc` files into an ephemeral temporary sandbox without cluttering your game folder.
* **Safe Auto-Fixing (`--fix`):** Automatically patches deterministic syntax oversights like unclosed text tags.
* **Tsundere Mode (`--tsundere`):** Provides colorful, anime-style diagnostic feedback for your visual novel.

---

## Installation

Senpy works in two parts: the core analyzer (installed via pip) and the VS Code extension.

### 1. Install the Core Linter

=======
Open your terminal and install the package from PyPI:

```bash
pip install senpy-linter
```

### 2. Install the VS Code Extension

Go to the [Releases](https://github.com/Xilleet/senpy/releases) page of this repository.<br>
Download the latest senpy-vscode-X.X.X.vsix file.<br>
Open VS Code, go to the Extensions tab (Ctrl+Shift+X).<br>
Click the ... (Views and More Actions) menu at the top right of the Extensions panel.<br>
Select Install from VSIX... and choose the downloaded file.<br>

## Usage

Run Senpy from anywhere in your terminal by passing the path to your Ren'Py game folder:

```bash
# Analyze a Ren'Py game directory
senpy "path/to/game"

# Automatically apply safe fixes (e.g. unclosed dialogue tags)
senpy "path/to/game" --fix

# Ignore specific error codes
senpy "path/to/game" --ignore RPY104 RPY303

# Auto-decompile orphaned .rpyc files into a temporary sandbox
senpy "path/to/game" --decompile

# Limit the number of displayed error cards
senpy "path/to/game" --max-errors 30
```

## Diagnostics & Rules Reference

| Code | Category | Severity | Description |
|---|---|---|---|
| `RPY101` | Variables | 🔴 Error | Variable in text interpolation `[var]` is not declared via `default` or `define` (features fuzzy “did you mean?” suggestions). |
| `RPY102` | Python | 💥 Critical | Augmented assignment (`$ var += 1`) before declaration via `default` (guaranteed runtime `NameError`). |
| `RPY103` | Logic | 💥 Critical | Undeclared variable evaluated in an `if` / `elif` condition. |
| `RPY104` | State | ⚠️ Warning | Variable dynamically created via `$` without a top-level `default` (breaks save/load compatibility across patches). |
| `RPY201` | Screens | 💥 Critical | Direct state mutation inside a screen (causes lag, prediction loops, and breaks rollback). |
| `RPY202` | Screens | 🔴 Error | Screen accesses variable without a default (causes crash in the main menu or before game start). |
| `RPY301` | Dialogue | ⚠️ Warning | Unclosed or mismatched text tags (`{b}`, `{color}`, `{size}`) in dialogue. Fixable via `--fix`. |
| `RPY302` | Story | 💥 Critical | Jump or call to a non-existent label (causes `ScriptError`). |
| `RPY303` | Dead Code | ℹ️ Notice | Label is declared but never jumped to or called anywhere in the project. |
| `RPY304` | Formatting | 🔴 Error | Malformed hex color (e.g. `{#12345}`) or unknown color name in a `{color}` tag. |
| `RPY401` | Flow Graph | 💥 Critical | Variable is defined only in specific `menu:` choices but missing in others (crashes when the player takes an uninitialized path). |
| `RPY501` | Assets | 🔴 Error | Audio file referenced by `play music` or `play sound` is not found on disk or inside `.rpa` archives. |

## Examples in Action

### 1. Control-Flow Branching Crash (`RPY401`)

```renpy
label dungeon:
    menu:
        "Take the torch":
            $ has_torch = True
            "You grabbed a torch."

        "Walk in darkness":
            "You decided to risk it."

    # Merged path:
    if has_torch:  # <-- RPY401 triggered!
        "The light guides your way."
```

**Senpy output:**

```text
[WARNING] RPY401: Variable 'has_torch' is only defined in menu choice 'Take the torch',
but missing in 'Walk in darkness'. When choosing 'Walk in darkness', this condition will crash with NameError.
```

### 2. Screen Mutation Anti-Pattern (`RPY201`)

```renpy
screen shop():
    $ player_gold -= 10  # <-- RPY201 triggered!
```

**Senpy output:**

```text
Error [RPY201]: Direct state mutation 'player_gold' inside screen 'shop'.
Screens are evaluated predictively and continuously! Use screen Actions (e.g. SetVariable) instead.
```

### 3. Safe Auto-Fixing (`--fix` for `RPY301`)

**Before running `senpy --fix`:**

```renpy
"Attention: {b}danger zone!"
```

**After running `senpy --fix`:**

```renpy
"Attention: {b}danger zone!{/b}"
```

**Tsundere Mode (--tsundere)**
```bash
senpy path/to/game --tsundere
```

```text
(¬_¬ ) «П-подумаешь! Сканирую твою директорию: game/... Н-не то чтобы мне был интересен твой сценарий, бака!»

┌────────────────────────────────────────────────────────────────────────┐
│ game/gallery.rpy:81                                                    │
│   81 │ $ start = gallery_page * maxperpage                             │
│                                                                        │
│   (╯°□°)╯︵ ┻━┻ «Ты меняешь переменную ПРЯМО ВНУТРИ ЭКРАНА?!            │
│   Экраны так не работают, тупица!»                                     │
│   [WARNING] RPY201: Direct state mutation 'start' inside screen.       │
└────────────────────────────────────────────────────────────────────────┘

(⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄) «Я... я закрыла за тобой 3 открытых тега через --fix! Н-но не думай, что ты мне нравишься!»
```

## Configuration (`senpy.toml`)

Place a `senpy.toml` file in your game directory or workspace root to customize rules without passing CLI arguments:

```toml
[tool.senpy]
# Automatically decompile compiled .rpyc files into a temporary RAM sandbox
decompile = true

# Maximum error cards rendered in the console
max_errors = 50

# Ignore rules that don't match your workflow (e.g. dynamic routers)
ignore = [
    "RPY104",  # Ignore dynamic assignments
    "RPY303",  # Ignore unreachable labels
]
```

### Inline Suppression (`# noqa`)

You can suppress any diagnostic on a specific line using the standard `# noqa` syntax:

```renpy
"Warning: {b}unclosed style"  # noqa
$ dynamic_var = 1             # noqa: RPY104
```

## Zero-Footprint `.rpyc` Decompilation

When analyzing compiled distributions or mods, source `.rpy` files are often missing. Senpy detects orphaned `.rpyc` files and can decompile them on the fly:

1. Copies `.rpyc` files into a temporary OS sandbox directory (`%TEMP%` on Windows).
2. If `unrpyc` is not installed on your system, Senpy offers to download it automatically from GitHub into `~/.senpy/tools/`.
3. Runs analysis on the decompiled scripts in the temporary sandbox.
4. Cleans up and deletes the temporary sandbox immediately upon completion. Your game directory remains clean.

## Contributing

Contributions, bug reports, and rule suggestions are welcome!

Feel free to open an issue or submit a pull request on GitHub.

1. Fork the project.
2. Create your feature branch (`git checkout -b feature/AmazingFeature`).
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`).
4. Push to the branch (`git push origin feature/AmazingFeature`).
5. Open a pull request.

## License

Distributed under the MIT License. Free for commercial and non-commercial visual novel development.
