---
title: Senpy CLI Reference — Every Flag and Subcommand
description: Complete reference for the senpy command-line interface. All 30+ flags across 5 argument groups (general, rules, analysis, export, tools) plus the three subcommands (format, inspect, rule). Examples for every common use case.
tags:
  - cli
  - reference
---

# Senpy CLI Reference

The `senpy` command has 30+ flags organized in 5 argument groups, plus
3 subcommands. This page is the canonical reference.

```bash
senpy --version                  # show version
senpy --rules                    # list all 51 rules
senpy path/to/game               # analyze the project (default)
senpy path/to/game --fix         # auto-fix safe errors
senpy format path/to/game/       # format .rpy files (subcommand)
senpy inspect path/to/game/      # dump project symbols as JSON (subcommand)
senpy rule list                  # browse rule metadata (subcommand)
senpy rule show RPY104           # show one rule detail (subcommand)
```

---

## Argument groups

### General

| Flag | Description |
|---|---|
| `--version` | Print Senpy version and exit |
| `path` (positional) | Path to Ren'Py project or `game/` directory (default: `.`) |
| `--respect-gitignore` | Skip files matching patterns in `.gitignore` |
| `--config FILE` | Path to custom `senpy.toml` (env: `SENPY_CONFIG`) |
| `--show-settings` | Print resolved config + exit |

### Rules & documentation

| Flag | Description |
|---|---|
| `--rules` | List all 51 rules and descriptions |
| `--rule CODE` | Show detailed explanation for a rule (e.g. `--rule RPY104`) |

### Analysis & autofix

| Flag | Description |
|---|---|
| `--fix` | Auto-fix safe errors (`RPY001` tabs, `RPY002` smart quotes, `RPY301` unclosed tags) |
| `--check` | Dry-run for `--fix`: report what would change, don't write. Exit 1 if any fixable issue. |
| `--diff` | Show unified diff of what `--fix` would change |
| `--coverage` | Display translation coverage metrics for `game/tl/` |
| `--stats` | Calculate story & character dialogue statistics, word count, reading time |
| `--defaults` | Generate `senpy_defaults.rpy` with `default` declarations for all `RPY104` variables |
| `--errors-only` | Show only ERROR-level diagnostics |
| `--info` | Show INFO-level diagnostics (hidden by default) |
| `--ignore CODE [CODE ...]` | Ignore specific rule codes |
| `--select CODE [CODE ...]` | Run ONLY these rules (whitelist) |
| `--extend-select CODE [CODE ...]` | Add to `--select` whitelist |
| `--extend-ignore CODE [CODE ...]` | Add to `--ignore` blacklist |
| `--tag TAG [TAG ...]` | Run ONLY rules with these tags (e.g. `--tag rollback state`) |
| `--ignore-tag TAG [TAG ...]` | Skip rules with these tags |
| `--max-errors NUM` | Maximum diagnostic cards in terminal (default: 50) |
| `--no-cache` | Disable disk cache |
| `--clear-cache` | Clear `.senpy_cache/` and exit |
| `--cache-dir DIR` | Custom cache directory |
| `--exit-zero` | Always exit 0, even with errors (non-blocking CI) |
| `--show-fixes` | Show detailed list of fixes applied by `--fix` |
| `--statistics` | Print summary table: count per rule, sorted by frequency |
| `--add-noqa` | Add `# noqa` comments to all fixable diagnostics |
| `--tsundere` | Enable tsundere UI mode (Easter egg) |

### Visualization & reports

| Flag | Description |
|---|---|
| `--export-html FILE` | Generate standalone HTML report with interactive story graph |
| `--export-wiki [FILE]` | Generate project documentation (characters, variables, endings) in Markdown (default: `PROJECT_WIKI.md`) |
| `--graph` | Generate Mermaid.js story flow diagram (printed to stdout) |
| `--graph-file FILE` | Save Mermaid.js story diagram to a file |
| `--output-format FORMAT` | Output format: `text` (default), `json`, `sarif`, `junit`, `github`, `rdjson`, `gitlab` (alias: `--format`) |
| `--output-file FILE` | Save report to a specific file |

### Tools & integrations

| Flag | Description |
|---|---|
| `--lsp` | Run as Language Server (for editor integration) |
| `--init-ci` | Generate `.github/workflows/senpy.yml` (one-click CI) |
| `--traceback [FILE]` | Inspect a runtime crash log (`traceback.txt` or `errors.txt`); default file: `traceback.txt` |
| `--stubs [DIR]` | Generate Python type stubs (`.pyi`) for Pylance / MyPy (default: `typings/`) |
| `--decompile` | Decompile orphaned `.rpyc` files into a sandbox |
| `--unrpyc PATH` | Custom path to `unrpyc.py` or unrpyc executable |
| `--trust-plugin NAME` | Trust a plugin by name (adds to `~/.senpy/trusted_plugins.json`) |
| `--untrust-plugin NAME` | Remove a plugin from the trust store |

---

## Subcommands

Senpy has three subcommands for distinct workflows:

### `senpy format` — code formatter

Format `.rpy` files in place (like `black` for Python). 9 opinionated
formatter rules. See [Formatter](formatter.md) for the full style
guide.

```bash
senpy format game/script.rpy        # format one file
senpy format game/                   # format all .rpy files recursively
senpy format game/ --check           # CI: exit 1 if any file would change
senpy format game/ --diff            # show what would change
```

### `senpy inspect` — symbol dump

Dump all symbols Senpy sees in the project as JSON. Useful for
debugging hover/asset resolution and for plugin authoring.

```bash
senpy inspect game/                      # full JSON dump
senpy inspect game/ --summary            # just section stats
senpy inspect game/ --unresolved         # broken jumps / missing screens / unreferenced labels / unused assets
senpy inspect game/ --label my_label     # show one label + its callers/callees
senpy inspect game/ --screen my_screen   # show one screen + its parameters
senpy inspect game/ --transform my_tf    # show one transform + its uses
```

Output is JSON — pipe into `jq` or save to a file.

### `senpy rule` — rule metadata browser

Browse rule metadata without running the analyzer.

```bash
senpy rule list                       # table of all 51 rules
senpy rule list --format json         # JSON output
senpy rule list --tag rollback        # filter by tag
senpy rule list --severity ERROR      # filter by severity
senpy rule show RPY104                 # show one rule in detail
```

---

## Common command patterns

### First run — see what's wrong

```bash
senpy /path/to/game
```

Default behavior: scan the project, print one Panel per diagnostic
(up to `max_errors`), summary table, summary line. Exit 1 if any
ERROR-level diagnostic.

### Auto-fix safe errors

```bash
senpy /path/to/game --fix --show-fixes
```

`--fix` applies mechanically safe fixes:

- `RPY001` — tabs → 4 spaces
- `RPY002` — smart quotes → straight (in code, not dialogue)
- `RPY301` — insert missing closing tag

`--show-fixes` prints a detailed list of what was fixed (file:line:
rule — fix title).

### Generate missing `default` declarations

```bash
senpy /path/to/game --defaults
# writes senpy_defaults.rpy next to your project
```

For every `RPY104` (dynamic assignment without `default`), generate
a `default var = ...` line. Inspect and merge into your project.

### Translation coverage report

```bash
senpy /path/to/game --coverage
# per-language: Strings / Translated / Empty / Coverage %
```

Useful before release to see which languages are ready to ship.

### Story graph

```bash
senpy /path/to/game --graph-file story.md
# writes Mermaid.js markdown — open in any Mermaid viewer

senpy /path/to/game --export-html report.html
# standalone HTML report with interactive graph + diagnostics
```

See [Ren'Py Story Graph](renpy-story-graph.md).

### CI lint with SARIF

```bash
senpy /path/to/game --output-format sarif --output-file senpy.sarif
# upload senpy.sarif via github/codeql-action/upload-sarif@v3
```

See [Ren'Py GitHub Actions](renpy-github-actions.md) for the full
workflow.

### Inspect a runtime crash

```bash
senpy --traceback /path/to/traceback.txt
# parses the crash log, explains the failure, links to the rule
```

### Generate CI workflow

```bash
senpy --init-ci
# writes .github/workflows/senpy.yml
```

### Filter by tag

```bash
senpy /path/to/game --tag rollback state   # only run rollback + state rules
senpy /path/to/game --ignore-tag dead-code # skip dead-code rules
senpy /path/to/game --tag translations     # only run translation rules
```

### Strict mode (one-off)

```bash
senpy /path/to/game --strict
# every rule not explicitly downgraded is ERROR
```

Or in `senpy.toml`:

```toml
[tool.senpy]
strict = true
```

### Non-blocking CI sweep

```bash
senpy /path/to/game --exit-zero --statistics
# always exits 0, prints summary table for review
```

### Generate Python type stubs

```bash
senpy /path/to/game --stubs
# writes .pyi files in typings/ for Pylance / MyPy
```

Useful for IDE autocomplete when working with Ren'Py-specific Python
extensions.

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | No errors found (or `--exit-zero` was used) |
| `1` | One or more ERROR-level diagnostics found |
| `2` | Invalid CLI usage (e.g. `--fix+--check+--diff` together) — prints a clear message, no traceback |

---

## Environment variables

| Variable | Description |
|---|---|
| `SENPY_CONFIG` | Path to custom `senpy.toml` (same as `--config`) |
| `SENPY_HOME` | Override `~/.senpy/` for trust store and other user data (default: `~/.senpy/`) |

---

## What's next?

- [**Configuration**](configuration.md) — `senpy.toml`, `.senpy-ignore`,
  severity overrides, strict mode.
- [**Formatter**](formatter.md) — `senpy format` style guide.
- [**Plugin development**](plugin-development.md) — write your own
  rules as pip packages.
- [**Install**](install.md) — `pip install senpy-linter`.
