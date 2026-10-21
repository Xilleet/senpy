[English](README.md) | [Русский](README_ru.md)

# Senpy (`senpy-linter`)

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Ren'Py-6.99%20%7C%207%20%7C%208-ff69b4?logo=renpy&logoColor=white" alt="Ren'Py 6.99 / 7 / 8">
  <img src="https://img.shields.io/badge/Rules-33%20Semantic%20Rules-orange" alt="33 Rules">
  <img src="https://img.shields.io/badge/Speed-77k%20lines%20in%203.5s-brightgreen" alt="Speed: 77k lines in 3.5s">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License: MIT">
  <img src="https://img.shields.io/badge/Code%20Style-Ruff-000000.svg" alt="Ruff">
</p>

<p align="center">
  <a href="README.md"><b>English</b></a> | <a href="README_ru.md"><b>Русский</b></a>
</p>

<p align="center">
  <b>"Notice me, Senpy! (⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄)"</b><br>
  <i>Fast semantic linter, control-flow analyzer, and language server for Ren'Py visual novels.</i>
</p>

---

## Why Senpy?

The standard built-in `renpy lint` command only checks for basic syntax errors and broken label targets. It is blind to deep runtime Python execution issues, rollback desynchronizations, and save-file corruptions. Consequently, critical `NameError` and `KeyError` crashes often slip into production builds and are only discovered after dozens of hours of manual playtesting.

**Senpy** provides comprehensive static semantic analysis without requiring the Ren'Py SDK runtime:

* **High Throughput:** Analyzes **77,000+ lines across 50 files in ~3.5 seconds** on commercial-scale visual novels with cold start, and responds in **10–15 ms** incrementally in editor sessions.
* **Save Game & Rollback Safety:** Catches dangerous `define` constant mutations (`RPY105`), non-revertable Python types (`RPY106`), and assignments missing top-level `default` declarations (`RPY104`).
* **Branching Dataflow Analysis:** Traces `menu:` choices to ensure variables are consistently defined across all possible story paths, preventing runtime crashes on alternative routes (`RPY401`).
* **Screen Safety Guard:** Flags direct state mutations and imperative Python loops inside reactive screens that cause lag, redraw loops, and broken rollbacks (`RPY201`, `RPY205`).
* **Modern & Legacy Image Semantics:** Fully validates both modern Ren'Py 7/8 `layeredimage` constructs (arbitrary attribute order, attribute removal syntax like `-coat`, ATL property separation) and classic Ren'Py 6.99 `image` definitions (`RPY502`).
* **Translation Validator (TL-Checker):** Audits `game/tl/` localization files using state-machine pair matching to detect broken interpolation variables (`[var]`), tag mismatches, and blank translated strings (`RPY601`–`RPY603`).
* **Deprecated API Detection:** Identifies obsolete Ren'Py calls (`LiveComposite`, `DynamicCharacter`, software-rendered `im.*`, legacy `ui.*`) and provides one-click modern replacements (`RPY107`).
* **Hardened RPA Sandbox:** Safely inspects `.rpa` archive indexes using pickle opcode whitelisting to prevent arbitrary code execution (RCE) and decompression bombs when auditing third-party mods.
* **Interactive Story Graph:** Builds a directed control-flow graph (CFG) of scenes, detecting dead ends (fallthrough hazards), and renders an interactive, zoomable graph in VS Code.
* **LSP & Editor Integration:** Full Language Server Protocol support for VS Code and Cursor, providing live diagnostics, exact character ranges, and automated Quick Fixes (`Ctrl+.`).

---

## Installation

Senpy consists of the core Python CLI/LSP analyzer and an optional VS Code extension.

### 1. Core Analyzer (CLI / LSP)

Install the package via pip:

```bash
pip install senpy-linter
```

### 2. VS Code Extension

1. Navigate to the [Releases](https://github.com/Xilleet/senpy/releases) page.
2. Download the latest `senpy-vscode-X.X.X.vsix` package.
3. Open VS Code, open the Extensions tab (`Ctrl+Shift+X`).
4. Click the `...` menu (Views and More Actions) at the top right of the Extensions panel.
5. Select **Install from VSIX...** and pick the downloaded file.

---

## Usage

Analyze your Ren'Py project by running `senpy` against your project root or `game/` directory:

```bash
# Analyze a Ren'Py game directory
senpy "path/to/game"

# Automatically apply safe fixes (unclosed tags, smart quotes, tab indents)
senpy "path/to/game" --fix

# Generate 'senpy_defaults.rpy' to declare all missing default variables
senpy "path/to/game" --generate-defaults

# Export story flow as a Mermaid.js diagram to terminal or file
senpy "path/to/game" --graph
senpy "path/to/game" --graph-file "story_graph.md"

# Output diagnostics in JSON format for CI/CD pipelines
senpy "path/to/game" --format json --output-file report.json

# Auto-decompile orphaned .rpyc files in an isolated temporary sandbox
senpy "path/to/game" --decompile

# Ignore specific rule codes
senpy "path/to/game" --ignore RPY104 RPY303

# Show detailed documentation and code examples for a specific rule
senpy --rule RPY107

# List all 33 available rules
senpy --rules

# Enable anime-style tsundere diagnostic messages
senpy "path/to/game" --tsundere
```

---

## Rules Overview

Senpy includes **33 specialized semantic rules** tailored to Ren'Py scripting:

| Series | Category | Description |
| :--- | :--- | :--- |
| **RPY0xx** | Indentation & Formatting | Tab characters in indents (`RPY001`), typographic smart quotes in code (`RPY002`). |
| **RPY1xx** | Variables, State & APIs | Missing `[var]` references, NameError on `+=`, undeclared variables in `if`, `define` mutations, non-revertable types, deprecated APIs (`RPY107`). |
| **RPY2xx** | Screens & UI Performance | Predictive state mutations, variables without `default` in screens, dead buttons, missing screens, imperative loops, function calls in `action` (`RPY206`). |
| **RPY3xx** | Dialogue & Story Flow | Unclosed `{b}` tags, broken jump/call targets, dead labels, malformed hex colors, unescaped dialogue quotes, missing returns, duplicate labels, fallthroughs (`RPY308`). |
| **RPY4xx** | Branching & Logic | Inconsistent variables in `menu:` choices (`RPY401`), empty choices, always-false or contradictory conditions. |
| **RPY5xx** | Assets & Media | Missing audio files, unresolved sprites/layered image attributes, unused assets on disk (`RPY503`), duplicate image declarations. |
| **RPY6xx** | Translations & Localization | Variable mismatches in `game/tl/` (`RPY601`), formatting tag mismatches, blank translation strings. |

For full descriptions, rationale, and bad/good examples, read the complete **[Rules Documentation](RULES.md)**.

---

## Examples in Action

### 1. Branching Asymmetry in Menus (`RPY401`)

```renpy
label dungeon:
    menu:
        "Take the torch":
            $ has_torch = True
            "You grabbed a torch."

        "Walk in darkness":
            "You decided to risk it."

    if has_torch:
        "The light guides your way."
```

```text
[WARNING] RPY401: Variable 'has_torch' is only defined in menu choice 'Take the torch',
but missing in 'Walk in darkness'. When choosing 'Walk in darkness', this condition will crash with NameError.
```

### 2. Variable Mismatch in Translations (`RPY601`)

```renpy
# game/tl/russian/script.rpy
translate russian strings:
    old "Welcome back, [player_name]!"
    new "С возвращением, [player]!"  # Typo in variable name
```

```text
[ERROR] RPY601: Variable mismatch in translation (lost: [player_name]; typo/extra: [player]).
Will crash with KeyError at runtime!
```

### 3. Deprecated Ren'Py API with Auto-Fix (`RPY107`)

```renpy
image natsuki mouth = LiveComposite((960, 960), (0, 0), "natsuki/0.png")
```

```text
[WARNING] RPY107: Deprecated Ren'Py API 'LiveComposite'. This function is obsolete or outdated. Use 'Composite' instead.
```
*Pressing `Ctrl+.` in VS Code suggests:* `Replace 'LiveComposite' with 'Composite'`.

### 4. Direct State Mutation in Screens (`RPY201`)

```renpy
screen shop():
    $ player_gold -= 10
```

```text
[WARNING] RPY201: Direct state mutation 'player_gold' inside screen 'shop'.
Screens are evaluated predictively and continuously! Use screen Actions (e.g., SetVariable) instead.
```

---

## Configuration (`senpy.toml`)

Configure analysis settings project-wide using a `senpy.toml` or `pyproject.toml` file placed in your game directory or workspace root:

```toml
[tool.senpy]
# Automatically decompile compiled .rpyc files into an isolated sandbox
decompile = true

# Maximum diagnostic cards printed in the terminal report
max_errors = 50

# Ignore rules that do not match your project architecture
ignore = [
    "RPY104",  # Dynamic assignments without default
    "RPY303",  # Unreferenced labels (e.g. invoked via dynamic routers)
]
```

### Inline Diagnostic Suppression (`# noqa`)

Suppress specific warnings on individual lines using standard `# noqa` syntax:

```renpy
"Warning: {b}unclosed style"  # noqa
$ dynamic_var = 1             # noqa: RPY104
$ temp_calc = 100             # senpy: ignore[RPY104]
```

---

## Safe Sandbox Decompilation

When analyzing game distributions or mods without source code, Senpy detects standalone `.rpyc` files:

1. Copies `.rpyc` files into an isolated OS temporary directory.
2. Prompts to download or locate `unrpyc` automatically if it is not present on the system.
3. Analyzes decompiled scripts entirely within the temporary sandbox.
4. Cleans up and removes all temporary files immediately upon completion, leaving your project directory unmodified.

---

## Contributing

Contributions, bug reports, and rule suggestions are welcome.

1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/NewRule`).
3. Commit your changes (`git commit -m 'feat: add RPY701 check'`).
4. Ensure test suite passes (`pytest`).
5. Open a pull request.

---

## License

Distributed under the MIT License. Free for commercial and non-commercial visual novel development.