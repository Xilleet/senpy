---
title: Senpy — Static Analyzer and Semantic Linter for Ren'Py
description: Senpy is a fast static analyzer, semantic linter, control-flow analyzer and VS Code language server for Ren'Py visual novels. Find undefined variables, broken labels, save corruption, and translation errors before release — without the Ren'Py SDK.
tags:
  - home
  - linter
  - static-analysis
  - renpy
  - visual-novel
---

# Senpy — Static Analyzer for Ren'Py

<p align="center">
  <a href="https://pypi.org/project/senpy-linter/"><img src="https://img.shields.io/pypi/v/senpy-linter.svg?logo=python&logoColor=white" alt="PyPI version"></a>
  <a href="https://pypi.org/project/senpy-linter/"><img src="https://img.shields.io/pypi/dm/senpy-linter.svg?label=PyPI%20downloads" alt="PyPI downloads"></a>
  <a href="https://open-vsx.org/extension/xilleet/senpy-vscode"><img src="https://img.shields.io/badge/Open%20VSX-0.8.4-success?logo=eclipse&logoColor=white" alt="Open VSX"></a>
  <a href="https://github.com/Xilleet/senpy/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Xilleet/senpy/ci.yml?branch=main&label=CI" alt="CI Status"></a>
  <a href="https://github.com/Xilleet/senpy"><img src="https://img.shields.io/github/stars/Xilleet/senpy?style=social" alt="GitHub stars"></a>
</p>

**Senpy** finds bugs in your Ren'Py visual novel before your players do —
without requiring the Ren'Py SDK. It is a fast, standalone static analyzer,
semantic linter, control-flow analyzer, and Language Server that catches
the class of bugs that go beyond `renpy lint`'s scope:

- **Undefined variables** that crash on save/load or alternate routes
- **Broken labels** from `jump`/`call` typos
- **Save corruption** from mutating `define` constants
- **Rollback desync** from non-revertable Python types
- **Translation errors** in `game/tl/` files (variable mismatch, empty
  strings, missing tags)
- **Control-flow bugs** — `MAYBE_SET` reads after menu branches, story
  islands unreachable from `start`
- **Dead code** — unused `define`, `transform`, `screen`, default variables,
  transform/screen parameters, audio channels
- **Init order violations** — `NameError` at game launch from alphabetical
  file load order

It runs as a **CLI** (one-shot analysis), an **LSP server** (real-time
diagnostics in VS Code / VSCodium / Cursor / Neovim), or a **CI step**
(SARIF / JUnit / GitHub Actions / GitLab Code Quality / Reviewdog output).

---

## Install

```bash
pip install senpy-linter
```

Or install the VS Code extension via [Open VSX](https://open-vsx.org/extension/xilleet/senpy-vscode).

See [Install](install.md) for all three installation paths (Python CLI, VS Code extension via Open VSX, VSIX from GitHub Releases).

---

## What can Senpy detect?

Senpy includes **53 rules** across 8 categories. Each rule maps to a
real Ren'Py runtime failure that goes beyond `renpy lint`'s scope:

| Category | Rules | Example caught bug |
|---|---|---|
| **Indentation & syntax** | RPY001, RPY002, RPY100 | Tab characters, smart quotes, non-UTF-8 files |
| **Variables & state** | RPY101–RPY109 | `NameError` on save load, `define` mutation, init order, type taint |
| **Screens & UI** | RPY201–RPY208 | State mutation inside screen, dead button, `SetVariable` leak |
| **Story flow** | RPY301–RPY310 | Unclosed `{b}` tags, broken `jump`, duplicate labels, call signature mismatch |
| **Branching & logic** | RPY401–RPY404 | Menu branch asymmetry, `MAYBE_SET` reads, always-false conditions |
| **Assets & media** | RPY501–RPY505 | Missing audio, unresolved sprites, unused assets, unregistered channels |
| **Translations** | RPY601–RPY603, RPY801–RPY802 | Variable mismatch, tag mismatch, empty `new`, duplicates, inconsistencies |
| **Dead code** | RPY701–RPY707 | Unused `define`/`transform`/`screen`/`default`/parameters/channels |

Full rule reference with examples: see [Rules](rules/index.md) or the
canonical [RULES.md](https://github.com/Xilleet/senpy/blob/main/RULES.md)
in the repository.

---

## Why Senpy?

The built-in `renpy lint` command launches the entire Pygame runtime and
only catches syntax-level issues. It is blind to deep runtime Python
execution issues, rollback desynchronizations, and save-file corruptions.

Senpy is a **standalone static analyzer** — it parses `.rpy` files
without launching Ren'Py. That gives three advantages:

1. **Speed.** 77,000 lines analyzed in ~3.5s on cold start, 0.04s
   incrementally (with two-tier `.senpy_cache/` disk serialization).
   The built-in `renpy lint` takes 30–40s on the same input because it
   has to execute `init python:` blocks.
2. **Depth.** Senpy performs **dataflow analysis** — it tracks variable
   state (`DECLARED`, `MAYBE_SET`, `GUARANTEED`) across `if/elif/else` and
   `menu:` branches. This catches bugs that only surface when a player
   picks a specific route, loads a save mid-game, or triggers rollback.
3. **CI-ready.** `pip install senpy-linter` is enough — no Ren'Py SDK
   download, no headless Pygame, no Windows-specific setup. Output
   formats include SARIF (GitHub Code Scanning), JUnit XML, GitLab Code
   Quality, Reviewdog NDJSON, GitHub Actions annotations, and plain
   JSON for custom integrations.

The two tools are **complementary, not replacements**. Run both: built-in
`lint` for SDK-level checks, Senpy for semantic, save/rollback, translation,
control-flow, and dead-code analysis. See [Senpy vs `renpy lint`](comparison.md)
for the full 12-row comparison.

---

## Where to next?

Choose your entry point:

- **I'm new to Ren'Py linting** → [Ren'Py Linter](renpy-linter.md) —
  what linters exist, what they catch, why the built-in one isn't
  enough.
- **I want to understand static analysis for Ren'Py** →
  [Ren'Py Static Analysis](renpy-static-analysis.md) — the five levels
  of analysis (syntax → semantic → control-flow → dataflow →
  save/rollback safety) and where Senpy sits.
- **My game crashes on a specific error** → [Ren'Py Error Checker](renpy-error-checker.md) —
  map common `NameError`/`KeyError`/`AttributeError`/`ScriptError`
  messages to the Senpy rule that catches them.
- **I want real-time diagnostics in my editor** →
  [Ren'Py VS Code Extension](renpy-vscode-extension.md) — 20+ LSP
  handlers, autocomplete, go-to-definition, hover, rename, story graph.
- **I'm localizing a visual novel** →
  [Ren'Py Translation Checker](renpy-translation-checker.md) — variable
  mismatch detection, formatting tag checks, `--coverage` metrics,
  consistency across files in the same language.
- **I want to visualise story branches** →
  [Ren'Py Story Graph](renpy-story-graph.md) — Mermaid.js flowchart of
  all labels and `jump`/`call` edges, dead-end detection, unreachable
  subgraph detection.
- **I want Senpy in CI** → [Ren'Py GitHub Actions](renpy-github-actions.md) —
  `senpy --init-ci` one-click workflow, SARIF for Code Scanning,
  Reviewdog integration, GitLab MR annotations.

---

## Quick start

```bash
# Install
pip install senpy-linter

# Analyze your Ren'Py game
senpy /path/to/your/game

# Auto-fix safe errors (unclosed tags, smart quotes, tabs)
senpy /path/to/your/game --fix

# Generate a one-click GitHub Actions workflow for SARIF scanning
senpy --init-ci

# Get translation coverage metrics for game/tl/
senpy /path/to/your/game --coverage

# Export the story flow as a Mermaid.js diagram
senpy /path/to/your/game --graph-file story.md

# Inspect a runtime traceback
senpy --traceback /path/to/traceback.txt
```

Full CLI reference: [CLI reference](cli-reference.md).

---

## Project

Senpy is open source, MIT-licensed, and developed on GitHub at
[`Xilleet/senpy`](https://github.com/Xilleet/senpy). The Python package
is `senpy-linter` on [PyPI](https://pypi.org/project/senpy-linter/). The
VS Code extension is `xilleet.senpy-vscode` on
[Open VSX](https://open-vsx.org/extension/xilleet/senpy-vscode).

- Source: <https://github.com/Xilleet/senpy>
- Issues: <https://github.com/Xilleet/senpy/issues>
- Discussions: <https://github.com/Xilleet/senpy/discussions>
- Changelog: [CHANGELOG.md](https://github.com/Xilleet/senpy/blob/main/CHANGELOG.md)
- Architecture (for contributors): [ARCHITECTURE.md](https://github.com/Xilleet/senpy/blob/main/ARCHITECTURE.md)
- Security policy: [SECURITY.md](https://github.com/Xilleet/senpy/blob/main/SECURITY.md)

> The name "senpy" is shared with a few unrelated projects (sentiment
> analysis, Neyer sensitivity testing, SCIA Engineer XML framework). This
> is the only one related to Ren'Py. See the
> [disambiguation note](https://github.com/Xilleet/senpy#other-projects-named-senpy)
> in the repository README if you arrived here by mistake.
