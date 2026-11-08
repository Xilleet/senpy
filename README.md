<p align="center">
  <a href="README.md"><b>English</b></a> | <a href="README_ru.md"><b>Русский</b></a>
</p>

# Senpy (`senpy-linter`)

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="https://www.renpy.org/"><img src="https://img.shields.io/badge/Ren'Py-6.99%20%7C%207%20%7C%208-ff69b4?logo=renpy&logoColor=white" alt="Ren'Py 6.99 / 7 / 8"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="License: MIT"></a>
  <br>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-blue" alt="Platforms: Windows | Linux | macOS">
  <img src="https://img.shields.io/badge/Plugins-API%20v1.0-teal" alt="Plugin API v1.0">
  <a href="https://github.com/Xilleet/senpy/actions"><img src="https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/Xilleet/0f6886d60299e1afccce9e892db22085/raw/tests.json" alt="Tests (auto-updated by CI)"></a>
  <a href="RULES.md"><img src="https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/Xilleet/0f6886d60299e1afccce9e892db22085/raw/rules.json" alt="Rules (auto-updated by CI)"></a>
  <a href="ARCHITECTURE.md"><img src="https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/Xilleet/0f6886d60299e1afccce9e892db22085/raw/lsp.json" alt="LSP Handlers (auto-updated by CI)"></a>
  <a href="https://github.com/Xilleet/senpy/actions"><img src="https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/Xilleet/0f6886d60299e1afccce9e892db22085/raw/coverage.json" alt="Coverage (auto-updated by CI)"></a>
  <a href="https://github.com/Xilleet/senpy/actions"><img src="https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/Xilleet/0f6886d60299e1afccce9e892db22085/raw/speed.json" alt="Speed (auto-updated by CI)"></a>
  <a href="https://github.com/Xilleet/senpy/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Xilleet/senpy/ci.yml?branch=main&label=CI" alt="CI Status"></a>
</p>

<p align="center">
  <b>"Notice me, Senpy! (⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄)"</b><br>
  <i>Senpy — Fast static analyzer, semantic linter, control-flow analyzer and VS Code language server for Ren'Py visual novels. Detects undefined variables, broken labels, control-flow bugs, rollback/save issues, translation errors, and more.</i>
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
## What's New

### 0.8.2 — False-positive cleanup + CRLF/Windows fix

A patch release that closes **9 false-positive classes** discovered by running Senpy 0.8.1 on a 5-project corpus of real open-source Ren'Py games (~174k LOC): DDLC, LearnToCodeRPG, cross_channel localization, DDLCModTemplate, renpy-template. **1777 tests** (up from 1646 in 0.8.1). No new rules — all changes are correctness fixes. Corpus verification: 8968 → 8485 diagnostics (-483 false positives, -5.4%).

| Rule | What Was Broken | What Changed |
|---|---|---|
| **RPY309** | Labels reached from `start` via fall-through (no `return` between adjacent labels) were reported as "story islands unreachable from start". | New `fall_through_to` edge on `LabelSymbol`, followed in the reachability BFS. 515 false positives eliminated in cross_channel alone. |
| **RPY503** | Assets referenced via `gui.button_properties("X")` style calls and `[prefix_]` state-prefix patterns were reported as unused. | Every line is now scanned for media-asset string literals; `[prefix_]` is expanded to the 8 standard state prefixes. 101 false positives eliminated. |
| **RPY206** | `FilePagePrevious()`, `FilePageNext()`, `InvertSelected()` and 44 other built-in screen action factories were flagged as "executes immediately". | `BUILTIN_ACTIONS` allowlist extended from 42 to 91 entries, covering the complete Ren'Py screen action library. |
| **RPY102** | A variable assigned inside an `if` body and used in the SAME body (e.g. in a nested `for` loop) was flagged as "undeclared before declaration". | Each `if`/`while`/`for`/`try` body now gets its own copy of `local_scope`; assigned names are added as they are visited. |
| **RPY109** | Variables defined in `init python:` (priority 0) were reported as "init phase dependency violation" when referenced in `init 998 python:` blocks in alphabetically earlier files. | The init priority is now extracted and the alphabetical-order check is skipped when the referencing block has priority > 0. |
| **RPY110** | A `$` statement opening a triple-quoted string on one line and closing it on another triggered "Python syntax error". | `_get_logical_line` now joins physical lines while a triple-quoted string is open, with cumulative state tracking. |
| **RPY103** | Screen parameters declared via `init -501 screen game_menu(title, scroll=None):` were not registered in the local scope. | `RE_SCREEN_START` extended to optionally match the `init <N> ` prefix. |
| **RPY502** | Images registered via `renpy.image(NAME, ...)` calls in `init python:` blocks were not visible to the static analyzer. | A static evaluator walks the init-python AST, evaluates the name argument (string literals, loop variables, simple concatenation), and registers the image. 88 false positives eliminated in learntocode. |
| **LSP snapshot** | After `did_change` → `analyze_file_only`, hover/completion/rename/references read from a stale snapshot — newly added symbols were invisible until `did_save`. | `_refresh_symbol_snapshot()` is now called after `analyze_file_only`. |

Also fixes: CRLF line endings breaking `textwrap.dedent` on Windows (new `dedent_python()` helper), RPA `_read_rpa_index` activated (was dead code), and the tests badge no longer turns yellow on expected skips.

---

### 0.8.1 — Hotfix: 5 Architectural Bug Clusters Resolved

A patch release that fixes 19 bugs discovered after the 0.8.0 release. **1,646 tests** are now included (up from 1,487 in 0.8.0). No new rules have been added — this release focuses strictly on correctness fixes and introduces three infrastructure tests designed to automatically catch future regressions of the same classes.

| Cluster | What Was Broken | What Changed |
|---|---|---|
| **False Positives on String Literals** | Substring checks and regex scanning on raw Ren'Py strings incorrectly matched identifiers inside dialogues or Python strings. RPY302/202/204 triggered on strings like `"The Jump('foo') action is interesting."`. | A new `strip_string_literals()` helper is now applied at every checker invocation point. It masks literal contents with spaces while preserving column positions. |
| **Incomplete Cache Restoration** | Tier 1/Tier 2 cache hits silently lost `noqa_maps`, `missing_defaults`, `has_dynamic_jumps`, and the `enable_plugins` flag. Cold and warm runs produced inconsistent diagnostics. | Per-file persistence has been implemented, and `enable_plugins` is now included in the environment fingerprint. The `test_cold_warm_equivalence` test permanently enforces this contract. |
| **Source Corruption by QuickFix** | `--fix` and LSP QuickFix generated invalid code: RPY401 destroyed menu items, RPY002 duplicated indentation, and RPY206 dropped the `action` prefix along with its arguments. | A strict range/replacement contract was introduced; `test_quickfix_preserves_validity` is now executed against all `bad_*.rpy` fixtures. |
| **State Propagation Gaps** | `did_close` failed to cancel pending timers; `analyze_menu_flow` ignored pre-menu `guaranteed_vars`; LSP rename modified all whole-word occurrences regardless of the symbol kind. | Every propagation path is now properly closed; `test_run_idempotency` acts as a catch-all guard. |
| **LSP Rename Precision** | Renaming a variable named `score` would erroneously overwrite `label score:`, `jump score`, and natural-language mentions within dialogues. | Kind-specific predicates now filter raw text-search matches based on context before issuing a `TextEdit`. |

---

### 0.8.0 — Production-stable: security hardening, soundness fixes, plugin API contract

| Feature | Description |
|---|---|
| **JUnit XML escaping** | `diag.code` and `diag.line_content` are now HTML-escaped in `<failure>`/`<skipped>` elements. Source code with `<`, `>`, `&` no longer breaks the whole JUnit report for Jenkins/GitLab CI/TeamCity parsers. |
| **`--fix` write failures surfaced** | `_write_fixed_file` no longer silently swallows `OSError` (read-only file, disk full, permission denied). Failed writes are logged at WARNING, recorded in `AnalysisResult.failed_writes`, and force a non-zero CLI exit code — silent data loss is no longer possible. |
| **XSS in HTML report** | `diag.code` and `diag.severity` are now HTML-escaped before interpolation. A malicious plugin rule code can no longer execute JavaScript when the user opens `senpy --export-html` output in a browser. CSS variable lookup also sanitised. |
| **Path traversal in LSP hover** | `_resolve_relative_to_game` now uses `realpath` + `commonpath` containment check. A malicious `.rpy` with `image evil = "images/../../etc/passwd"` can no longer disclose system file size/path via hover. |
| **Plugin code collision rejected** | `register_loaded_plugins()` now rejects plugin rules whose `code` collides with a built-in `RULES_DATABASE` entry. Previously the collision was only filtered in `senpy rule list` — the plugin rule still ran during analysis. `RPY9xx` range formally reserved for plugins. |
| **`--exit-zero` for all formats** | Previously only `render_text` honoured `--exit-zero`; the other six renderers (sarif, json, junit, github, rdjson, gitlab) ignored it, breaking non-blocking CI workflows like `senpy --exit-zero --format sarif`. A shared `_exit_code` helper now applies the flag consistently. |
| **CI badges moved to Gist** | The `update-badges` CI job no longer commits `chore(badge): update dynamic badges [skip ci]` back to `main` (which caused merge conflicts). Badge JSON is pushed to a GitHub Gist via API; `main` is never touched. |
| **MkDocs Material documentation site** | New `docs/` site with 13 pages (install, configuration, CLI reference, formatter, plugin development, comparison, renpy-* guides). Deployed to GitHub Pages via `docs.yml` workflow. |
| **GitHub Release notes auto-generated** | Release workflow builds the release body from the matching `## [X.Y.Z]` CHANGELOG section + header template — release notes are never out of sync with the changelog. |
| **`bump_version.py` extended** | Now updates 4 hardcoded version mentions (`.pre-commit-hooks.yaml`, `.github/release-header.md`, `docs/install.md`, `docs/index.md`) that previously drifted every release. |
| **Architecture cleanup** | `SenpyAnalyzer` god-file split into `FileCollector` + `AnalysisPipeline` + `SymbolTable` (38 characterization tests guard the split). `cli/main.py` split into 10 modules. RWLock migration complete. Coverage gate raised to 80%. |
| **Docs sync** | `SECURITY.md`, `ARCHITECTURE.md`, `senpy-vscode/README.md`, `docs/comparison.md`, `docs/FORMAT_STYLE_GUIDE.md`, `docs/formatter.md` all synced with current code state. |

Full changelog: [CHANGELOG.md](https://github.com/Xilleet/senpy/blob/main/CHANGELOG.md)

---

## Why You Need This

`renpy lint` catches syntax and reference errors, but the bugs that actually
ship to players go beyond its scope. These are real bugs that Senpy would have caught before
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

1. Slips past `renpy lint` (which focuses on syntax and references).
2. Survives dev playtesting (devs always pick the "interesting" branch).
3. Surfaces only after release — via Steam reviews, Discord screenshots,
   or itch.io bug reports.
4. Costs hours of "works on my machine" debugging because the player can't
   reproduce it in front of you.

Senpy catches them at lint time — before they ship. **That's why you need it.**

For the full list of 52 rules with examples, see **[RULES.md](https://github.com/Xilleet/senpy/blob/main/RULES.md)**.

---

## Why Senpy?

The standard built-in `renpy lint` command checks for syntax errors, broken references, and image/sprite issues. However, it does not cover deep runtime Python execution issues, rollback desynchronizations, or save-file corruptions. Consequently, critical `NameError` and `KeyError` crashes often slip into production builds and are only discovered after dozens of hours of manual playtesting.

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

## Senpy vs built-in `renpy lint`

Ren'Py ships with a built-in `lint` command (`renpy.exe lint`), but it launches the entire Pygame runtime and only catches syntax-level issues. Senpy is a standalone static analyzer that runs without the Ren'Py SDK and catches a different class of bugs.

| Aspect | Ren'Py built-in `lint` | Senpy |
|---|---|---|
| **Approach** | Launches Pygame runtime, executes `init python:` blocks | Static analysis, no SDK required |
| **Speed on 70k LOC** | 30–40 seconds | ~3.5s cold / 0.04s incremental |
| **Save / rollback safety** | ❌ | ✅ `RPY104`, `RPY105`, `RPY106` |
| **Translation mismatch detection** | ❌ | ✅ `RPY601`, `RPY602`, `RPY603` |
| **Story graph visualization** | ❌ | ✅ `senpy --graph` |
| **Dead code detection** | ❌ | ✅ `RPY701`–`RPY707` |
| **Branching dataflow analysis** | ❌ | ✅ `RPY401`, `RPY404` |
| **Init phase dependency graph** | ❌ | ✅ `RPY109` |
| **CI-ready (GitHub Actions, SARIF)** | Needs headless Ren'Py SDK in CI | `pip install senpy-linter` + SARIF output |
| **IDE integration** | ❌ | ✅ LSP for VS Code (20+ handlers) |
| **What it catches** | Syntax errors, broken `jump`/`call` targets, missing images | + Save corruption, rollback desync, translation bugs, dead code, type taint, init order |
| **Distribution** | Bundled with Ren'Py SDK | PyPI (`senpy-linter`) + Open VSX extension + GitHub Releases |

The two tools are **complementary, not replacements**. Senpy catches a class of bugs that built-in `lint` cannot see (semantic, save/rollback, translation, control-flow). Run both: built-in `lint` for SDK-level checks, Senpy for everything else.

---

## Senpy vs `vscode-language-renpy` (official extension)

`vscode-language-renpy` is the **official** Ren'Py extension for VS Code (152 ⭐, maintained by the Ren'Py team). It provides syntax highlighting and basic snippets. Senpy provides **semantic analysis** on top of that — it understands variables, control flow, screens, and translation files, not just text.

| Capability | `vscode-language-renpy` | Senpy |
|---|---|---|
| Syntax highlighting | ✅ | ✅ |
| Language configuration (brackets, comments) | ✅ | ✅ |
| Snippets | ✅ basic | ❌ |
| **Real-time diagnostics** | ❌ | ✅ 49+ rules, runs on every keystroke |
| **Go-to-definition** | ❌ | ✅ labels, screens, transforms, defines |
| **Find references** | ❌ | ✅ across the whole project |
| **Hover docs** | ❌ | ✅ renpy API + asset previews |
| **Rename symbol** | ❌ | ✅ labels, screens |
| **Semantic tokens** | ❌ | ✅ |
| **Story graph visualization** | ❌ | ✅ Mermaid diagram of branching routes |
| **Save / rollback safety checks** | ❌ | ✅ |
| **Translation validator** | ❌ | ✅ `game/tl/` mismatch detection + coverage |

The two extensions are **complementary and can be installed side-by-side**. If you want both syntax highlighting (official) and semantic diagnostics (Senpy), install both.

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
| **Format Document** | `Shift+Alt+F` | Run Senpy formatter (9 rules) |
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

### Write Your Own Rule in 30 Lines

This rule (from `examples/my_senpy_plugin/`) flags dialogue lines that are not wrapped in `_()` for translation:

```python
from senpy.api import Diagnostic
from senpy.plugins import Rule, RuleContext, RuleMeta, register_rule

PLUGIN_API_VERSION = "1.0"


@register_rule("RPY901")
class HardcodedDialogueRule(Rule):
    meta = RuleMeta(
        code="RPY901",
        docs="Detects dialogue lines without _() for translation",
        severity="WARNING",
        tags=["translations", "accessibility"],
    )

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        diags = []
        for line_no, raw in enumerate(ctx.lines, start=1):
            stripped = raw.lstrip(" \t")
            if not stripped or stripped[0] not in ('"', "'"):
                continue
            if stripped.startswith('_("') or stripped.startswith("_('"):
                continue  # already translated
            diags.append(
                Diagnostic(
                    file_path=ctx.file_path,
                    line_number=line_no,
                    line_content=raw.rstrip(),
                    code="RPY901",
                    message=f"Hardcoded dialogue without _() for translation",
                    severity="WARNING",
                )
            )
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

Senpy includes **51 specialized semantic rules** across 28 tags:

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

### Project-level Suppression (`.senpy-ignore`)

For bulk rule exclusions, create a `.senpy-ignore` file in the project
root (next to `senpy.toml`). Each line is a rule code to suppress:

```text
# .senpy-ignore — one rule code per line
RPY101  # typo in dialogue variable
RPY104
# RPY105  # commented out — rule will fire
RPY301
```

Lines starting with `#` are comments. Inline comments (after the rule
code) are allowed. Codes are case-insensitive (normalized to uppercase).

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

## Pre-commit Integration

Senpy ships a [pre-commit](https://pre-commit.com) hook that runs
`senpy --errors-only` on every commit. Add this to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/Xilleet/senpy
    rev: v0.8.2   # use the latest tag
    hooks:
      - id: senpy
```

The hook is **non-mutating** — it only reports issues, never auto-fixes
them. It uses `--errors-only` so the gate fails (exit 1) on any
ERROR-severity diagnostic, including unfixable ones (undefined
variables, dead labels, etc.). WARNINGs and INFO notices are hidden
from the pre-commit log; run `senpy` manually without `--errors-only`
for the full picture.

The non-mutating choice is deliberate: an auto-fixing hook combined
with git's `autocrlf` on Windows creates an infinite loop (the
formatter normalizes line endings, git converts them back, the
formatter runs again). Run `senpy --fix` manually if you want
auto-fixes.

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

## About Senpy

Senpy is a passion project — I needed a semantic linter for my own Ren'Py
visual novel, and none existed. So I built one.

**How it's made:** I read and review Python code fluently, but I don't enjoy
typing boilerplate. So I let AI tools do the typing, while I do:

- Architecture (what rules to add, how the LSP server should work)
- Code review (every line — I catch bugs the AI misses)
- Testing on real Ren'Py projects
- Bug report triage and fixes
- Release management

The AI doesn't decide what to build, doesn't push code, doesn't choose
features. I do. The AI is my fast typist.

If you're curious about this workflow, I'm happy to discuss in
[Discussions](https://github.com/Xilleet/senpy/discussions). If you find a
bug, [report it](https://github.com/Xilleet/senpy/issues) — I read every
issue and fix what matters to users.

Also check out [ScreenTale](https://github.com/Xilleet/ScreenTale), another
tool from me.

---

## Other projects named "senpy"

The name `senpy` is shared with several unrelated projects. If you landed here looking for one of those, here's a disambiguation:

| Project | What it is | Link |
|---|---|---|
| **Senpy (this repo)** | Semantic linter and static analyzer for Ren'Py visual novels | https://github.com/Xilleet/senpy |
| `pypi.org/project/senpy` | Sentiment analysis server (Marl/Onyx/NIF vocabularies) | https://pypi.org/project/senpy/ |
| `ACasey13/senpy` | Python package for Neyer sensitivity testing | https://github.com/ACasey13/senpy |
| SCIA Engineer `senpy` | Python framework to generate SCIA Engineer XML data | https://www.scia.net/en/support/addons/senpy-python-framework-generate-scia-engineer-data |
| *Senpy: A framework for semantic sentiment and emotion* | Academic paper, ScienceDirect | https://www.sciencedirect.com/science/article/abs/pii/S0950705119305313 |

This project (`Xilleet/senpy`) is the only one related to Ren'Py. The naming collision is unfortunate — if you came here from a search for sentiment analysis or sensitivity testing, please follow the corresponding link above.

---

## License

Distributed under the MIT License. Free for commercial and non-commercial visual novel development.
