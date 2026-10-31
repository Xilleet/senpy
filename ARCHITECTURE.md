# Senpy Architecture

This document describes the internal architecture of Senpy — a semantic
linter, control-flow analyzer, and Language Server for Ren'Py visual novels.

## Overview

Senpy is a static analysis tool that understands Ren'Py's domain semantics:
`default` vs `define` (save persistence), `screen` actions (UI prediction),
rollback safety, translation interpolation, and control-flow branching.

Senpy performs **dataflow analysis** — tracking variable states (DECLARED, MAYBE_SET,
GUARANTEED) across `if/elif/else` and `menu:` branches to catch bugs that
only surface at runtime after specific player choices.

## Package Structure

```
senpy/
├── __init__.py              # Package entry, version re-export
├── __version__.py           # Single source for version
├── api.py                   # Public stable API (analyze_code, Diagnostic, Location)
├── text_utils.py            # Shared text utilities (_strip_comment, _get_logical_line)
│
├── cli/                     # Command-line interface
│   ├── __main__.py          # Entry point (calls main())
│   ├── main.py              # CLI orchestration: parse_args, run, render output
│   ├── format_dispatch.py   # `senpy format` subcommand handler
│   ├── commands.py          # Per-flag handlers (--traceback, --coverage, --stats, etc.)
│   └── unrpyc.py            # .rpyc decompilation, .rpa extraction, unrpyc download
│
├── core/                    # Analysis engine
│   ├── analyzer.py          # SenpyAnalyzer — the heart of the project
│   ├── cache.py             # Two-tier disk cache (SafeCacheUnpickler, CacheManager)
│   ├── cache_manifest.py    # Backward-compat re-export for cache_manifest
│   ├── config.py            # load_config() + pydantic SenpyConfig validation
│   ├── constants.py         # BUILTIN_SYMBOLS, BUILTIN_SCREENS, IGNORED_DIRS, etc.
│   ├── coverage.py          # Translation coverage metrics
│   ├── exceptions.py        # SenpyError hierarchy (8 domain exceptions)
│   ├── logging.py           # setup_logging(), get_logger() — library-style
│   ├── models.py            # Diagnostic, AnalysisResult, FileScope, RULE_SEVERITY
│   ├── scope.py             # ScopeStack, ScopeType (LABEL, SCREEN, etc.)
│   ├── signature.py         # parse_signature(), validate_call_arguments()
│   ├── sink.py              # DiagnosticSink Protocol (decouples checkers from analyzer)
│   └── symbols.py           # VariableSymbol, LabelSymbol, ScreenSymbol, etc.
│
├── domain/                  # Ren'Py domain knowledge
│   ├── assets.py            # AssetManager — image/audio file discovery, .rpa scanning
│   ├── renpy_api.py         # 220+ Ren'Py built-in API definitions (for hover/completion)
│   ├── rpa.py               # RPA archive reading (safe_load_rpa_index)
│   ├── text_tags.py         # {b}, {color}, [var] parser — RPY101/301/304 checks
│   └── tsundere.py          # Easter egg UI mode (Russian/English flavor text)
│
├── formats/                 # Output formats
│   ├── ci.py                # JUnit XML, GitHub Actions annotations
│   ├── html_report.py       # Standalone HTML report with Mermaid graph (CSP-protected)
│   ├── sarif.py             # SARIF 2.1.0 for GitHub Code Scanning
│   ├── stats.py             # Story analytics (word count, character stats, reading time)
│   ├── stubs.py             # Python type stubs (.pyi) generation for Pylance
│   ├── traceback.py         # Crash log parser (traceback.txt → human-readable explanation)
│   └── wiki.py              # Markdown documentation export
│
├── formatter/               # Code formatter (Black-style for Ren'Py)
│   ├── core.py              # Formatter class, FormatConfig, @register_rule decorator
│   └── rules/               # 8 formatter rules (indent, whitespace, quotes, spacing)
│
├── lsp/                     # Language Server Protocol implementation
│   ├── server.py            # pygls LanguageServer setup, _RWLock, symbol snapshot
│   └── handlers/            # Per-LSP-method handlers
│       ├── completion.py    # textDocument/completion
│       ├── diagnostics.py   # textDocument/publishDiagnostics
│       ├── hover.py         # textDocument/hover (Ren'Py API docs + jump targets)
│       ├── navigation.py    # definition, references, rename, document_symbols
│       ├── text_document.py # didOpen, didChange, didSave, didClose
│       └── workspace.py     # workspace/symbol, executeCommand
│
├── plugins/                 # Plugin system
│   ├── base.py              # Rule base class, RuleMeta, RuleContext
│   ├── loader.py            # entry_points discovery, trust-on-first-use
│   ├── registry.py          # @register_rule decorator, _REGISTERED_LINT_RULES
│   └── security.py          # PLUGIN_API_VERSION, check_api_version, trust store
│
├── rules/                   # Lint rules (45+ rules across 6 domains)
│   ├── base.py              # BaseChecker — abstract base for all checkers
│   ├── checkers/            # Per-domain checker modules
│   │   ├── formatting.py    # RPY0xx (tabs, smart quotes)
│   │   ├── state.py         # RPY1xx (variables, default/define, init order)
│   │   ├── screen.py        # RPY2xx (screen actions, UI prediction)
│   │   ├── dialogue.py      # RPY3xx (labels, jumps, text tags, fallthrough)
│   │   ├── asset.py         # RPY5xx (missing assets, unused media)
│   │   └── translation.py   # RPY6xx (translation variable/tag mismatch)
│   ├── dead_code.py         # RPY7xx (unused define/transform/screen)
│   ├── deprecated.py        # RPY107 (deprecated Ren'Py API)
│   ├── flow.py              # RPY4xx (branch dataflow, Mermaid graph builder)
│   ├── python_ast.py        # Python AST checker ($-statements, init python blocks)
│   └── rules_info.py        # RULES_DATABASE, dynamic rule count, --rules output
│
├── vendor/                  # Vendored dependencies (do not modify)
│   └── unrpyc/              # .rpyc decompiler (pinned commit, SHA256-verified)
│
├── senpy-vscode/            # VS Code extension (TypeScript)
│   ├── src/extension.ts     # Extension entry point, commands, crash watcher
│   ├── package.json         # Extension manifest, LSP configuration
│   └── language-configuration.json
├── tests                    # all tests
└── examples                 # examples and your plugins with new rules
```

## Dependency Flow

Dependencies flow **inward** — outer packages depend on inner, never the reverse:

```
                    ┌──────────────────────────────────┐
                    │          cli / lsp                │  ← Entry points
                    │  (orchestration, I/O, protocol)   │
                    └──────────┬───────────────────────┘
                               │
                    ┌──────────▼───────────────────────┐
                    │          rules / formats          │  ← Analysis & output
                    │  (checkers, flow, sarif, stats)   │
                    └──────────┬───────────────────────┘
                               │
                    ┌──────────▼───────────────────────┐
                    │            core                   │  ← Engine
                    │  (analyzer, cache, scope, sink)   │
                    └──────────┬───────────────────────┘
                               │
                    ┌──────────▼───────────────────────┐
                    │           domain                  │  ← Knowledge
                    │  (assets, text_tags, renpy_api)   │
                    └──────────────────────────────────┘
```

- `cli` and `lsp` are the two entry points (CLI and editor integration).
- `rules` and `formats` depend on `core` (for Diagnostic, SenpyAnalyzer).
- `core` depends on `domain` (for text tags, asset discovery).
- `domain` has no internal Senpy dependencies (only `core.constants`).
- `plugins` depends on `core` (exceptions, logging) — plugins are loaded
  at runtime, not at import time.
- `vendor` is isolated — no Senpy code imports from vendor at module level.

## Analysis Pipeline

`SenpyAnalyzer.run()` is the main entry point. 
It executes in 3 stages:

### Stage 1: Symbol Collection (`_collect_all_symbols`)

For each `.rpy` file:
1. Compute file hash (content-based, not just mtime).
2. **Tier 1 cache hit**: If hash matches cached entry, restore `FileScope`
   (labels, screens, variables, transforms, images) without re-parsing.
3. **Cache miss**: Parse file line-by-line, build `FileScope`, collect
   stage-1 diagnostics (RPY307 duplicate labels, RPY504 image overrides,
   RPY100 encoding errors).

After all files: call `_rebuild_aggregates()` to merge per-file scopes into
global registries (`self.variables`, `self.labels`, `self.screens`, etc.).

### Stage 2: Rule Analysis (`_analyze_all_files`)

For each `.rpy` file:
1. **Tier 2 cache hit**: If global symbol hash unchanged AND file hash
   matches, restore cached diagnostics instantly (~0.04s for 77k lines).
2. **Cache miss**: Run `_analyze_file()` — line-by-line dispatch to 6
   checkers (Formatting, Screen, Asset, Dialogue, State) + Python AST
   checker for `$`-statements and `init python` blocks.

Each checker receives a `DiagnosticSink` (Protocol) — it doesn't know
about `SenpyAnalyzer` directly, only the interface for adding diagnostics.

### Stage 3: Finalization (`_finalize_results`)

1. Post-analysis checks: unreachable labels (RPY309), unused assets
   (RPY503), unused declarations (RPY701/702/703).
2. Translation file analysis: for each `.rpy` in `game/tl/`, validate
   old/new pairs for variable interpolation (RPY601), formatting tags
   (RPY602), and empty strings (RPY603).
3. Severity overrides: apply user-configured severity changes from
   `senpy.toml [tool.senpy.severity]`.
4. Cache save: write `CacheManifest` with global symbol hash + per-file
   entries (diagnostics, scope, used assets, content hash).

## Two-Tier Cache

```
.senpy_cache/
├── cache.pkl          # CacheManifest (pickle, SafeCacheUnpickler)
└── decompiled/        # Decompilation sandbox for orphan .rpyc
```

**Tier 1** (symbol-level): If a file's content hash is unchanged, its
`FileScope` (collected symbols) is restored from cache. This skips
re-parsing but still runs all lint rules.

**Tier 2** (diagnostic-level): If the global symbol hash is also unchanged
(meaning no symbol was added/removed/renamed across the entire project),
cached diagnostics are restored directly. This is the fast path —
incremental analysis in ~0.04s for 77,000 lines.

`SafeCacheUnpickler` restricts unpickling to `senpy.core.cache` classes
only, with a module blocklist (`os`, `sys`, `subprocess`, etc.) as
defense-in-depth against cache poisoning.

## Rule Engine

Rules are organized by domain prefix:

| Prefix | Domain | Checker module | Example rules |
|--------|--------|----------------|---------------|
| RPY0xx | Formatting | `formatting.py` | RPY001 (tabs), RPY002 (smart quotes) |
| RPY1xx | Variables & state | `state.py` + `python_ast.py` | RPY104 (missing default), RPY105 (define mutation) |
| RPY2xx | Screens & UI | `screen.py` | RPY203 (button without action), RPY208 (SetVariable leak) |
| RPY3xx | Dialogue & labels | `dialogue.py` | RPY302 (jump to nonexistent label), RPY308 (fallthrough) |
| RPY4xx | Control flow | `flow.py` + `state.py` | RPY401 (branch asymmetry), RPY404 (MAYBE_SET read) |
| RPY5xx | Assets | `asset.py` | RPY501 (missing audio), RPY503 (unused media) |
| RPY6xx | Translations | `translation.py` | RPY601 (variable mismatch), RPY603 (empty translation) |
| RPY7xx | Dead code | `dead_code.py` | RPY701 (unused define), RPY703 (unused screen) |

Each checker inherits from `BaseChecker` and implements `check_line()`.
The `DiagnosticSink` Protocol decouples checkers from `SenpyAnalyzer` —
checkers only see the `_add_diagnostic()` and `_get_utf16_range()` methods.

### Python AST Analysis

`PythonAstChecker` in `python_ast.py` handles `$`-statements and
`init python:` blocks via Python's `ast` module:

1. Parse Python code with `ast.parse()`.
2. Walk top-level statements via `_walk_python_nodes()` dispatcher.
3. Each statement type has a dedicated visitor:
   - `_visit_assign` — RPY104/RPY105/RPY106/RPY108 (assignment checks)
   - `_visit_augassign` — RPY102/RPY105/RPY108 (+=, -= checks)
   - `_visit_mutating_methods` — RPY105/RPY102/RPY108 (.append(), .update())
   - `_visit_if_while` / `_visit_for` / `_visit_try` — recurse into bodies
4. Type inference via `infer_ast_type()` dispatch table (9 helpers, CC≤4).

### Control Flow Analysis

`StoryFlowAnalyzer` in `flow.py` builds a jump graph and detects:
- RPY401: Menu branch asymmetry (variable set in one choice, not another)
- RPY404: Reading a MAYBE_SET variable after a branch
- RPY403: Always-False conditions (logical contradictions)
- RPY309: Story islands (unreachable label groups)
- Mermaid graph generation for `--graph` / `--export-html`

## LSP Server

The LSP server (`lsp/server.py`) uses [pygls](https://github.com/openlawlibrary/pygls)
and implements 20+ LSP methods:

### Concurrency Model

A **Reader-Writer Lock** (`_RWLock` with writer preference) protects
shared analyzer state:
- Read operations (completion, hover, definition, references) acquire
  read lock — multiple readers run in parallel.
- Write operations (didChange, didSave, full re-analysis) acquire write
  lock — exclusive access.
- Writer preference: if a writer is waiting, new readers block. This
  prevents writer starvation under constant reader load (typical for LSP
  — client sends hover/completion continuously).

### Symbol Snapshot

`_symbol_snapshot` is a shallow copy of all project symbols (labels,
screens, transforms, variables, images, jump_sources). Refreshed after
each full project scan. Used by completion, rename, and references
handlers to see ALL symbols, even when `analyze_file_only` has cleared
symbols from other files.

### Per-URI Debounce

Each URI has its own `threading.Timer` for diagnostic scheduling. This
prevents rapid `didChange` events (typing) from triggering multiple
parallel analyses — only the last change within the debounce window
gets analyzed.

### LSP Methods

| Method | Description |
|--------|-------------|
| `textDocument/publishDiagnostics` | Real-time squiggles (~0.04s incremental) |
| `textDocument/completion` | Labels, screens, transforms, variables, image attributes |
| `textDocument/hover` | Ren'Py API docs (220+ functions) + jump target info |
| `textDocument/definition` | Go to label/screen/variable/asset |
| `textDocument/references` | All jump/call sites + text search for variables/transforms/screens |
| `textDocument/rename` | Rename label/variable/transform/screen (updates all references) |
| `textDocument/documentSymbol` | Outline view (labels, screens, transforms, images) |
| `textDocument/foldingRange` | Fold blocks (labels, screens, init python) |
| `textDocument/documentHighlight` | Highlight same symbol occurrences |
| `textDocument/documentColor` | Hex colors as clickable swatches |
| `textDocument/formatting` | Format document (8 formatter rules) |
| `textDocument/rangeFormatting` | Format selection |
| `textDocument/signatureHelp` | Parameter hints for `call label(...)` / `use screen(...)` |
| `textDocument/prepareCallHierarchy` | Find callers (jump/call graph) |
| `workspace/symbol` | Global symbol search (Ctrl+T) |

## Plugin System

Plugins are pip packages that declare an entry point:

```toml
[project.entry-points."senpy.plugins"]
my_rule = "my_senpy_plugin.rules:MyRule"
```

### Loading Pipeline

1. `discover_plugins()` — finds entry points via `importlib.metadata`.
2. `load_plugin()` — loads each plugin with isolation (failed plugin
   skipped, others continue).
3. API version check — plugin declares `PLUGIN_API_VERSION`, Senpy
   verifies compatibility (same major required).
4. Trust check — trust-on-first-use: first load in TTY prompts `[y/N]`,
   choice persisted to `~/.senpy/trusted_plugins.json`. Non-interactive
   (CI) skips untrusted plugins (fail-safe).
5. `register_loaded_plugins()` — registers Rule subclasses in
   `_REGISTERED_LINT_RULES`.

### Rule Base Class

```python
from senpy.plugins.base import Rule, RuleMeta, RuleContext
from senpy.plugins.registry import register_rule

@register_rule("RPY999")
class MyRule(Rule):
    meta = RuleMeta(
        code="RPY999",
        docs="Description of what this rule checks.",
        severity="WARNING",
        fixable=False,
        tags=["performance"],
    )

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        # ctx.file_path, ctx.lines, ctx.symbols, ctx.analyzer
        ...
```

## Formatter

The formatter (`formatter/`) applies 8 rules idempotently (formatting
already-formatted code produces zero changes):

| Rule | Description |
|------|-------------|
| FMT-INDENT | 4-space indentation (tabs → spaces) |
| FMT-TRAILING-WS | Remove trailing whitespace |
| FMT-EOF-NEWLINE | Ensure single newline at end of file |
| FMT-BLANK-LINES | Collapse multiple blank lines (max 2) |
| FMT-QUOTES | Smart/curly quotes → straight (in code, not dialogue) |
| FMT-OP-SPACING | Single space around binary operators |
| FMT-COMMA-SPACING | Space after comma, no space before |
| FMT-COLON-SPACING | No space before block-opening colon |

Skip mechanism: `# senpy: format off` / `# senpy: format on` /
`# senpy: format skip` comments disable formatting for specific blocks.

## Security

### Safe Unpickling

Cache files (`.senpy_cache/cache.pkl`) are loaded via `SafeCacheUnpickler`
which restricts `find_class()` to `senpy.core.cache` classes only. A
module blocklist (`os`, `sys`, `subprocess`, `socket`, `shutil`,
`pathlib`, `builtins`, `ctypes`, `multiprocessing`, `pickle`, `marshal`)
provides defense-in-depth even if someone adds a dangerous module to
the safe list.

### unrpyc Pinning

The vendored unrpyc is pinned to a specific git commit. Downloads are
verified against `UNRPYC_PINNED_SHA256`. If the SHA mismatches
(possible supply-chain attack), Senpy logs an ERROR and refuses to use
the downloaded file.

### LSP URI Validation

`_uri_to_path()` validates that:
1. URI scheme is `file:` (rejects `http:`, `https:`, `ftp:`).
2. If `workspace_root` is provided, the resolved path must be inside it
   (path traversal protection via `os.path.commonpath`).

### VS Code Extension

The extension uses `child_process.execFile` (not `exec`) with array
arguments — no shell interpolation, eliminating shell injection risk
from workspace paths.

## Exception Hierarchy

```
SenpyError (root, inherits Exception — NOT ValueError/TypeError)
├── ConfigError              — invalid TOML, unknown rule code
├── AnalysisError            — analysis pipeline errors
│   ├── ParseError           — .rpy/.rpyc parse failure
│   └── SymbolResolutionError — undefined label/screen/variable
├── CacheError               — corrupt pickle, version mismatch
├── PluginError              — plugin loading/execution failure
│   └── ApiVersionMismatchError — plugin API version incompatible
├── SecurityError            — URI scheme violation, path traversal
│                             (also inherits ValueError for backward compat)
└── DecompilationError       — unrpyc .rpyc decompilation failure
```

Callers can catch any Senpy domain error via `except SenpyError:` without
accidentally catching stdlib `ValueError`/`TypeError`.

## Configuration

### senpy.toml

```toml
[tool.senpy]
decompile = true          # Auto-decompile orphan .rpyc
max_errors = 50           # Max diagnostic cards in terminal
info = false              # Show INFO-level notices
errors_only = false       # Show only ERRORs
tsundere = false          # Easter egg mode
strict = false            # All rules = ERROR (future)

ignore = ["RPY303"]       # Blacklist (always ignored)
select = []               # Whitelist (run ONLY these)
extend_select = []        # Add to whitelist
extend_ignore = []        # Add to blacklist

[tool.senpy.severity]
RPY104 = "ERROR"          # Override severity
RPY308 = "INFO"
```

Configuration is validated via pydantic v2 (`SenpyConfig` model) with
`strict=True` — no type coercion (string `"yes"` does NOT become `True`).

### .senpy-ignore

Project-level bulk rule exclusions (one rule code per line, comments
with `#`):

```
# .senpy-ignore
RPY101  # typo in dialogue variable
RPY104
```

### Rule Selection

CLI flags (`--select`, `--extend-select`, `--extend-ignore`) follow
ruff/eslint semantics:
- `--select RPY101 RPY102` — run ONLY these rules.
- `--extend-select RPY103` — add to whitelist (only with `--select`).
- `--extend-ignore RPY104` — add to blacklist.

## Logging

Library-style logging via `senpy.core.logging`:
- `setup_logging(verbose=False, log_file=None)` — NullHandler by default
  (critical for LSP mode where stderr is reserved for protocol).
- `get_logger("plugins")` — returns `senpy.plugins` child logger.
- `verbose=True` adds StreamHandler to stderr.
- `log_file=<path>` adds FileHandler (UTF-8, append mode).

All `contextlib.suppress()` patterns were replaced with explicit
`try/except + logger.debug()` — suppressed exceptions are now
observable at DEBUG level.

## Testing

- **898 tests** across 65 test files (~15,700 lines).
- **Fixture-based**: `tests/fixtures/rules/RPYxxx/` with `bad_*.rpy` +
  `bad_*.json` (expected diagnostics) + `good_*.rpy` (should pass).
- **Characterization tests**: Subprocess-based CLI tests that verify
  end-to-end behavior (`senpy --version`, `senpy format`, `senpy test_game`).
- **Security tests**: `test_unrpyc_security.py`, `test_cache_security.py`,
  `test_lsp_uri_security.py`.
- **Cross-platform**: Subprocess tests use `sys.executable -m senpy.cli`
  (not bare `senpy`), force UTF-8 encoding, and set `PYTHONPATH` to
  work without `pip install -e .`.

## VS Code Extension

The extension (`senpy-vscode/`) is a TypeScript package that:
1. Launches the Senpy LSP server (bundled `senpy.exe` on Windows, or
   `python -m senpy.cli --lsp` on other platforms).
2. Provides commands: Story Flow Graph, Story Stats, Restart Language Server.
3. Watches for `traceback.txt` / `errors.txt` during playtesting —
   parses crash logs and shows actionable diagnostics.
4. Adds `bin/` directory to PATH for terminal usage.

The extension is distributed as a standalone VSIX with a bundled
PyInstaller binary — no Python installation required for end users.
