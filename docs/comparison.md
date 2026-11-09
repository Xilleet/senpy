---
title: Senpy vs renpy lint vs vscode-language-renpy — When to Use Each
description: Senpy is not a replacement for renpy lint or vscode-language-renpy. The three tools cover different layers of Ren'Py development. This page is the full 12-row comparison of what each catches, where each shines, and when to run which.
tags:
  - comparison
  - reference
---

# Senpy vs `renpy lint` vs `vscode-language-renpy`

There are three tools a Ren'Py developer reaches for, and they're
**complementary, not replacements**:

1. **`renpy lint`** — the built-in lint command shipped with the Ren'Py
   SDK. Runs the full Pygame runtime and checks syntax + reference
   integrity. Slow (30–40s on a 70k-line project) but has access to
   the full Ren'Py environment.
2. **`vscode-language-renpy`** — the official VS Code extension
   (152 ⭐, maintained by the Ren'Py team). Provides syntax highlighting
   and basic snippets.
3. **Senpy** — a standalone static analyzer, semantic linter,
   control-flow analyzer, and Language Server. Catches a class of bugs
   the other two can't see (semantics, save/rollback safety,
   translations, control flow, dead code).

This page compares them across 12 dimensions and explains when to use
which.

---

## Senpy vs `renpy lint`

The built-in `renpy lint` is bundled with the Ren'Py SDK. Run it via
`renpy.exe lint /path/to/game` (Windows) or `./renpy.sh lint /path/to/game`
(Linux/macOS).

| Aspect | `renpy lint` | Senpy |
|---|---|---|
| **Approach** | Launches Pygame runtime, executes `init python:` blocks | Static analysis, no SDK required |
| **Speed on 70k LOC** | 30–40 seconds | ~3.5s cold / 0.04s incremental |
| **Save / rollback safety** | ❌ | ✅ `RPY104`, `RPY105`, `RPY106` |
| **Translation mismatch detection** | ❌ | ✅ `RPY601`, `RPY602`, `RPY603`, `RPY801`, `RPY802` |
| **Story graph visualization** | ❌ | ✅ `senpy --graph` / `--export-html` |
| **Dead code detection** | ❌ | ✅ `RPY701`–`RPY707` |
| **Branching dataflow analysis** | ❌ | ✅ `RPY401`, `RPY404` |
| **Init phase dependency graph** | ❌ | ✅ `RPY109` |
| **CI-ready (GitHub Actions, SARIF)** | Needs headless Ren'Py SDK in CI | `pip install senpy-linter` + SARIF output |
| **IDE integration** | ❌ | ✅ LSP for VS Code / VSCodium / Cursor / GitLab Web IDE / Eclipse Theia (20+ handlers) |
| **What it catches** | Syntax errors, broken `jump`/`call` targets, missing images | + Save corruption, rollback desync, translation bugs, dead code, type taint, init order |
| **Distribution** | Bundled with Ren'Py SDK | PyPI (`senpy-linter`) + Open VSX extension + GitHub Releases |

### When to use `renpy lint`

- **Quick syntax check before testing in Ren'Py.** Fast feedback
  that you haven't broken anything obvious.
- **SDK-level checks.** Things that require executing `init python:`
  blocks (e.g. circular image definitions resolved at init time,
  missing `define` constants used in `init python:`).
- **First-time project setup.** Run `renpy lint` once after creating a
  new project to verify the template is clean.

### When to use Senpy

- **Catching runtime crashes before release.** Anything that involves
  save/load, rollback, branch choices, translation files.
- **CI on every PR.** No headless Pygame setup needed.
- **Real-time editor feedback.** 20+ LSP handlers in VS Code /
  VSCodium / Cursor.
- **Translation checks.** Variable mismatch, tag mismatch, empty
  strings, duplicates, inconsistencies.
- **Story graph visualization.** Find dead ends, unreachable routes,
  story islands.
- **Dead code audit.** Unused `define`/`transform`/`screen`/`default`/
  parameters/channels.

### The two are complementary

`renpy lint` runs the full Ren'Py environment, so it can catch
issues that require executing `init python:` blocks (e.g. circular
image definitions, missing `define` constants used in init). Senpy
is a static analyzer, so it can catch issues that require
branch-sensitive dataflow analysis, save/rollback modeling, or
translation file comparison — none of which `renpy lint` can do.

**Run both.** `renpy lint` for SDK-level checks, Senpy for everything
else.

---

## Senpy vs `vscode-language-renpy`

The official `vscode-language-renpy` extension is the Ren'Py team's
VS Code extension. It provides syntax highlighting and basic
snippets.

| Capability | `vscode-language-renpy` | Senpy |
|---|---|---|
| Syntax highlighting | ✅ | ✅ (TextMate grammar copied from renpy-magic, MIT) |
| Language configuration (brackets, comments) | ✅ | ✅ |
| Snippets | ✅ basic | ❌ |
| **Real-time diagnostics** | ❌ | ✅ 53 rules, runs on every keystroke |
| **Go-to-definition** | ❌ | ✅ labels, screens, transforms, defines |
| **Find references** | ❌ | ✅ across the whole project |
| **Hover docs** | ❌ | ✅ 975 Ren'Py API entries + asset previews |
| **Rename symbol** | ❌ | ✅ labels, screens, transforms, defines |
| **Semantic tokens** | ❌ | ✅ |
| **Story graph visualization** | ❌ | ✅ Mermaid diagram of branching routes |
| **Save / rollback safety checks** | ❌ | ✅ |
| **Translation validator** | ❌ | ✅ `game/tl/` mismatch detection + coverage |

### When to use `vscode-language-renpy`

- **You just want syntax highlighting.** If you don't need semantic
  analysis, the official extension is lighter weight.
- **You want official snippets.** Senpy doesn't ship snippets (yet).

### When to use Senpy

- **You want real-time diagnostics.** Squiggles on every keystroke,
  QuickFix on `Ctrl+.`, no need to run a CLI command.
- **You want go-to-definition / find references / rename.** These
  require semantic analysis, which the official extension doesn't
  provide.
- **You want save/rollback safety checks in your editor.** `RPY104`,
  `RPY105`, `RPY106` fire in real time as you type.
- **You want a story graph.** `Ctrl+Shift+P` → "Senpy: Show Story
  Graph" opens a Mermaid.js flowchart.

### The two are complementary — install both

The official extension handles syntax highlighting (which Senpy
also does, but the official one has more refined grammar rules from
years of community feedback). Senpy adds semantic analysis on top.

Install both side-by-side — no conflicts. The official extension
handles highlighting, Senpy handles diagnostics and navigation.

---

## Quick decision guide

| You want to… | Use |
|---|---|
| Quickly check syntax before testing in Ren'Py | `renpy lint` |
| Catch save-corruption bugs before release | Senpy |
| Catch translation variable mismatches | Senpy |
| Visualize story branches | Senpy |
| Get real-time squiggles in VS Code | Senpy |
| Get syntax highlighting in VS Code | `vscode-language-renpy` (or Senpy, both work) |
| Run lint in CI without a Ren'Py SDK | Senpy |
| Find dead code (unused defines/transforms/screens) | Senpy |
| Find broken jump/call targets | Both — they overlap here |
| Inspect a `traceback.txt` after a crash | Senpy (`senpy --traceback`) |
| Generate `senpy_defaults.rpy` for missing defaults | Senpy |
| Get translation coverage metrics per language | Senpy (`senpy --coverage`) |
| Get Ren'Py API documentation on hover | Senpy |
| Rename a label across all files | Senpy |
| Get parameter hints when calling a label | Senpy |

---

## Maturity and ecosystem

| Aspect | `renpy lint` | `vscode-language-renpy` | Senpy |
|---|---|---|---|
| **Maintainer** | Ren'Py team (Tom "PyTom" Rothamel) | Ren'Py team (community) | Solo maintainer (Xilleet) |
| **Age** | Since Ren'Py's beginning | Since ~2018 | Since 2026 (8 days old at SEO audit time) |
| **GitHub stars** | n/a (part of Ren'Py SDK) | 152 | 0–50 (new) |
| **License** | Ren'Py license (MIT-compatible for the SDK) | MIT | MIT |
| **Distribution** | Bundled with Ren'Py SDK | VS Code Marketplace | PyPI + Open VSX + GitHub Releases |
| **Test suite** | Ren'Py's own | Small | 1646 tests, 100% fixture coverage (53/53 rules) |
| **Stability** | Stable, slow-moving | Stable | Beta (0.7.x), fast-moving |

Senpy is newer and has a solo maintainer, but the test suite is
comprehensive (1646 tests, 100% fixture coverage for all 53 rules,
characterization tests for the CLI, security tests for cache/URI/unrpyc).
The rule set is documented in [RULES.md](https://github.com/Xilleet/senpy/blob/main/RULES.md)
and the architecture in [ARCHITECTURE.md](https://github.com/Xilleet/senpy/blob/main/ARCHITECTURE.md).

---

## What's next?

- [**Ren'Py Linter**](renpy-linter.md) — what linters catch, why the
  built-in one isn't enough.
- [**Ren'Py Static Analysis**](renpy-static-analysis.md) — the five
  levels of static analysis.
- [**Ren'Py VS Code Extension**](renpy-vscode-extension.md) — Senpy
  LSP features.
- [**All 53 rules**](rules/index.md) — browse the full rule set.
