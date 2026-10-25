<p align="center">
  <a href="README.md"><b>English</b></a> | <a href="README_ru.md"><b>Русский</b></a>
</p>

# Senpy (`senpy-linter`)

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Ren'Py-6.99%20%7C%207%20%7C%208-ff69b4?logo=renpy&logoColor=white" alt="Ren'Py 6.99 / 7 / 8">
  <img src="https://img.shields.io/badge/Rules-40%20Semantic%20Rules-orange" alt="40+ Rules">
  <img src="https://img.shields.io/badge/Speed-77k%20lines%20in%200.04s%20(cached)-brightgreen" alt="Speed: 77k lines in 0.04s">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License: MIT">
  <img src="https://img.shields.io/badge/Code%20Style-Ruff-000000.svg" alt="Ruff">
</p>

<p align="center">
  <b>"Notice me, Senpy! (⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄)"</b><br>
  <i>Fast semantic linter, control-flow analyzer, and language server for Ren'Py visual novels.</i>
</p>

---

## Why Senpy?

The standard built-in `renpy lint` command only checks for basic syntax errors and broken label targets. It is blind to deep runtime Python execution issues, rollback desynchronizations, and save-file corruptions. Consequently, critical `NameError` and `KeyError` crashes often slip into production builds and are only discovered after dozens of hours of manual playtesting.

**Senpy** provides comprehensive static semantic analysis without requiring the Ren'Py SDK runtime:

* **Zero-Setup Standalone VSIX:** Windows extension packages bundle a self-contained runtime—writers and narrative designers don't need Python, virtual environments, or `pip` installed.
* **High Throughput & Disk Serialization:** Analyzes **77,000+ lines in ~3.5s on cold start and 0.04s incrementally** via two-tier `.senpy_cache/` disk serialization.
* **Save Game & Rollback Safety:** Catches dangerous `define` mutations (`RPY105`), non-revertable types (`RPY106`), dynamic assignments missing `default` (`RPY104`), and type-taint conflicts (`RPY108`).
* **Init Phase Dependency Graph:** Analyzes alphabetical file loading order in `init python:` to prevent runtime `NameError` crashes on startup (`RPY109`).
* **Arity & Signature Checking:** Verifies parameter counts and keyword arguments on `call label(...)` (`RPY310`) and `use screen(...)` (`RPY207`).
* **Branching Dataflow Analysis:** Traces nested `if/elif/else` and `menu:` branches to ensure variables aren't evaluated in an uninitialized `MAYBE_SET` state (`RPY401`, `RPY404`).
* **Screen & UI Action Inspector:** Catches predictive state mutations (`RPY201`), imperative loops (`RPY205`), dead buttons (`RPY203`), function calls in actions (`RPY206`), and inspects string targets in screen Actions (`SetVariable`, `ToggleVariable`, `Show`, `ShowMenu`, `Hide`) for typos and missing declarations (`RPY202`, `RPY204`).
* **ATL Transforms & Transitions:** Validates custom and built-in positions/transforms in `show ... at <transform>` and transitions in `with <transition>`, catching runtime `NameError` typos with QuickFix suggestions (`RPY502`).
* **Collection Method Guard:** Detects incompatible method invocations on known types (`list.add()` ➔ `.append()`, `dict.append()`, `str.pop()`) before runtime `AttributeError` crashes occur (`RPY108`).
* **Translation Validator & Coverage:** Audits `game/tl/` formatting, catches broken interpolation variables (`RPY601`), and calculates localization completion metrics via `senpy --coverage`.
* **Runtime Crash Inspector:** Parses `traceback.txt` post-mortem crash logs, explaining failures in human-readable terms (`senpy --traceback`).
* **LSP & VS Code Superpowers:** Real-time diagnostics (~0.04s incremental cache), full-spectrum Go-to-Definition (`F12`), Document Symbols / Breadcrumbs (`Ctrl+Shift+O`), hover docs for 220+ Ren'Py APIs, QuickFix (`Ctrl+.`), and interactive story maps.

---

## Installation

Senpy can be used either as an **all-in-one standalone VS Code extension** (zero Python setup required on Windows) or as a **Python CLI / CI tool**.

### Option A: VS Code Extension (Recommended for VN Writers)

> **No Python installation or terminal setup required on Windows!** The VSIX package bundles a fully self-contained Senpy engine.

1. Download the latest `senpy-vscode-X.X.X.vsix` from the [Releases](https://github.com/Xilleet/senpy/releases) page.
2. In VS Code, open the Extensions panel (`Ctrl+Shift+X`).
3. Click the `...` menu (Views and More Actions) in the top-right corner of the Extensions panel.
4. Select **Install from VSIX...** and pick the downloaded file.
5. *(Bonus)* All `senpy` commands (like `senpy --coverage` or `senpy --export-wiki`) will automatically work directly inside VS Code's integrated terminal!

---

### Option B: Standalone CLI & CI/CD (pip)

For Linux/macOS users, command-line power users, or automated GitHub Actions workflows:

```bash
pip install senpy-linter
```


---

## Usage

Analyze your Ren'Py project by running `senpy` against your project root or `game/` directory:

```bash
# Analyze a Ren'Py game directory
senpy "path/to/game"

# Automatically apply safe fixes (unclosed tags, smart quotes, tab indents)
senpy "path/to/game" --fix

# Calculate translation completion metrics across all languages in game/tl/
senpy "path/to/game" --coverage

# Generate project documentation (GDD / Wiki) covering characters, state, and endings
senpy "path/to/game" --export-wiki "PROJECT_WIKI.md"

# Generate Python type stubs (.pyi) for Pylance / MyPy in VS Code
senpy "path/to/game" --stubs

# Inspect a Ren'Py runtime crash log (traceback.txt or errors.txt)
senpy --traceback "path/to/traceback.txt"

# One-click GitHub Actions workflow generator with CodeQL SARIF scanning
senpy --init-ci

# Generate 'senpy_defaults.rpy' to declare all missing default variables
senpy "path/to/game" --defaults

# Export story flow as an interactive Mermaid.js diagram
senpy "path/to/game" --graph-file "story_graph.md"

# Generate an autonomous HTML report with pan/zoom story graph and diagnostics
senpy "path/to/game" --export-html "report.html"

# Clear disk cache (.senpy_cache)
senpy --clear-cache

# List all 40 available rules
senpy --rules

# Enable anime-style tsundere diagnostic messages
senpy "path/to/game" --tsundere
```

---

## Rules Overview

Senpy includes **40 specialized semantic rules** tailored to Ren'Py scripting:

| Series | Category | Description |
| :--- | :--- | :--- |
| **RPY0xx** | Indentation & Formatting | Tab characters in indents (`RPY001`), typographic smart quotes in code (`RPY002`). |
| **RPY1xx** | Variables, State & APIs | Missing `[var]` references, NameError on `+=`, undeclared variables in `if`, `define` mutations, non-revertable types, deprecated APIs (`RPY107`), type taints & invalid collection methods (`RPY108`), init load order (`RPY109`). |
| **RPY2xx** | Screens & UI Performance | Predictive state mutations, undeclared variables in conditions & actions (`RPY202`), dead buttons, missing screens in calls & UI actions (`RPY204`), imperative loops, direct function calls in `action` (`RPY206`), screen parameter mismatches (`RPY207`). |
| **RPY3xx** | Dialogue & Story Flow | Unclosed `{b}` tags, broken jump/call targets, dead labels, malformed hex colors, unescaped quotes, missing returns, duplicate labels, fallthroughs (`RPY308`), story islands (`RPY309`), call parameter mismatches (`RPY310`). |
| **RPY4xx** | Branching & Logic | Branch asymmetry in menus & if/else (`RPY401`), empty choices (`RPY402`), contradictory conditions (`RPY403`), reading uninitialized `MAYBE_SET` variables (`RPY404`). |
| **RPY5xx** | Assets & Media | Missing audio files, unresolved sprites, layered image attributes, undefined transforms (`at`) & transitions (`with`) (`RPY502`), unused assets (`RPY503`), duplicate image declarations, unregistered audio channels (`RPY505`). |
| **RPY6xx** | Translations & Localization | Variable mismatches in `game/tl/` (`RPY601`), formatting tag mismatches (`RPY602`), blank translation strings (`RPY603`). |

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

# Override rule severity levels to fit your studio standards or CI policies (ERROR, WARNING, HINT, INFO)
[tool.senpy.severity]
RPY104 = "ERROR"   # Elevate missing defaults to build-breaking errors
RPY308 = "INFO"    # Demote label fallthrough to informational notices
```

## GitHub Actions Integration

Senpy fully supports the standard **SARIF** output format, allowing you to automatically scan your visual novel for errors every time someone submits a Pull Request. GitHub will natively highlight bugs and crash risks directly in the code review interface!

To enable this in one click, run:

```bash
senpy --init-ci
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

      - name: Install Python & Senpy
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install senpy-linter

      - name: Run Senpy Analysis
        run: senpy game/ --format sarif --output-file senpy.sarif
        continue-on-error: true

      - name: Upload SARIF report
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: senpy.sarif
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