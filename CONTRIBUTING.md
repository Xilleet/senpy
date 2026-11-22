# Contributing to Senpy

First of all: **thank you** for considering a contribution. Senpy is a
one-maintainer project, so every bug report, fix, and doc improvement
matters.

This document covers:

- [Quick start](#quick-start)
- [Good first issues](#good-first-issues) — where to start if you want to help
- [Solo-maintainer expectations](#solo-maintainer-expectations) — read this before opening a PR
- [Project layout](#project-layout)
- [How to add a new lint rule](#how-to-add-a-new-lint-rule)
- [How to add a new formatter rule](#how-to-add-a-new-formatter-rule)
- [How to add a new fixture](#how-to-add-a-new-fixture) — even without writing a rule
- [Testing](#testing)
- [Commit style and pull requests](#commit-style-and-pull-requests)
- [Releases](#releases)
- [Code of conduct](#code-of-conduct)

---

## Status: feature freeze → 1.0

Senpy 0.9.0 is **production-stable**. Until 1.0 is focusing on
architecture hardening and `senpy.api` contract stabilization. **No new rules,
no new features, no new output formats** are accepted during the freeze.

What **is** accepted during the freeze:

- **Bug fixes** (rule false positives, crashes, wrong diagnostics).
- **Security advisories** (see [SECURITY.md](SECURITY.md)).
- **Documentation improvements** (this file, README, RULES.md, ARCHITECTURE.md).
- **New fixtures for edge cases** not yet covered by the existing 52 fixture
  directories.
- **New plugin examples** in `examples/` (plugins don't touch the core).
- **New example .rpy files** in `examples/` showing rule categories.
- **Translations** of the docs into other languages (Japanese, Chinese,
  Spanish, etc. — for the itch.io / Lemma Soft audience).

What is **deferred to post-1.0**:

- New core rules (RPY0xx–RPY8xx expansion). Track candidates in the roadmap.
- New output formats (`checkstyle`, `sonar`, `azure-pipelines`).
- Formatter extensions (the 8 `FMT-*` rules listed in `docs/FORMAT_STYLE_GUIDE.md`).
- Sandbox R&D for plugins.
- Editor clients beyond VS Code.

If you want to add a new rule and the freeze is still in effect, **write it
as a plugin** — see `examples/my_senpy_plugin/` for a template. Plugin rules
don't touch the Senpy core and don't need to be useful in
your own project.

---

## Good first issues

If you want to contribute but don't know where to start, here is a list of
**low-risk, well-scoped** tasks that are genuinely useful and don't require
deep knowledge of the analyzer internals. Pick one, leave a comment on the
relevant issue (or open one if it doesn't exist), and we'll guide you.

> **All 53 rules (RPY000–RPY802) already have fixtures.** The old "rules —
> fixture coverage" table that listed 10 rules as "missing" or "partial" was
> accurate as of 0.6.x but is no longer true: every user-facing rule has at
> least one `bad_*.rpy` + `bad_*.json` + `good_*.rpy` triple under
> `tests/fixtures/rules/RPYxxx/`. The auto-discovery harness in
> `tests/rules/test_fixtures.py` runs them all automatically.

### 1. Report a false positive (no code required)

The single most valuable contribution for a static analyzer is **real-world
false positive reports**. If you use Senpy on your Ren'Py project and a rule
fires on code you consider correct:

1. Open an issue using the **"Rule false positive"** template
   (`.github/ISSUE_TEMPLATE/false_positive.yml`).
2. Paste a **minimal** reproducer — strip everything not needed to trigger
   the rule.
3. Explain why you think the code is correct (Ren'Py doc references help).
4. Include your Senpy version (`senpy --version`) and Ren'Py version.

The maintainer will triage, write a RED test from your reproducer, then a
GREEN fix. You get credited in the CHANGELOG.

### 2. Doc typo / clarity fixes

If you spot a typo, awkward phrasing, or unclear explanation in `README.md`,
`README_ru.md`, `RULES.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md`, or
`SECURITY.md` — just open a PR. These are merged fast and don't need an issue
first.

Specific known doc gaps (good targets for a small PR):

- `README.md` claims `python_ast.py` is 2143 lines — actually 1772 (the type
  inference was extracted to `core/type_inference.py`).
- `README.md` claims `lsp/handlers/navigation.py` is 1326 lines — actually 40
  (it's a thin re-export shim; the real logic is in 6 sub-modules).
- `README.md` says "51 specialized semantic rules" vs `docs/index.md` "53
  rules" — `len(RULES_DATABASE) == 53`, the lower count is stale.
- `README.md` marks "Semantic tokens ✅" but `textDocument/semanticTokens` is
  not registered — should be "❌ (planned)".
- `docs/renpy-linter.md` claims `.rpa` archives are read to check that assets
  exist inside them — actually only filenames are indexed, content is not
  validated. This is tracked as RPA-1 in the roadmap for 0.9.4.

### 3. New example .rpy files

The `examples/` directory has two plugin examples (`my_senpy_plugin/` and
`todo_comment_plugin/`) plus a formatter demo. Useful additions:

- `examples/rules_demo.rpy` — a single file showing each rule category
  (RPY0xx, RPY1xx, RPY2xx, ...) with inline comments explaining what each
  rule catches. Run `senpy examples/rules_demo.rpy` to see all diagnostics.
- `examples/format_before.rpy` + `examples/format_after.rpy` — a before/after
  pair showing what `senpy format` does.
- `examples/plugin_*.py` — a new plugin example. Good candidates:
  - **MP3 detector plugin**: flag `play music "track.mp3"` when Ren'Py
    recommends `.ogg` / `.opus` for longer tracks.
  - **Untranslated string plugin**: flag `textbutton "Save"` (a hardcoded UI
    string in a `screen` block) when `_()` wrapping is missing for i18n.
  - **Label naming convention plugin**: enforce `label chapter_N_start:`
    naming for projects that want chapter-based structure.

Each new plugin example should include a `*_README.md` explaining what the
plugin does, how to install it (`pip install -e examples/<name>`), and how
to trust it (`senpy --trust-plugin <name>`).

### 4. New fixture edge cases

Every rule has fixtures, but **edge cases are not equally covered**. If you
want to deepen the test suite, pick a rule and add fixtures for cases not
covered by the existing `bad_*.rpy` / `good_*.rpy` files:

| Rule | Edge case not yet covered | Fixture to add |
| ---- | ------------------------- | -------------- |
| RPY103 | Deeply nested tuple unpacking in `for` (`for (a, (b, (c, d))) in ...:`) | `tests/fixtures/rules/RPY103/bad_nested_tuple.rpy` |
| RPY106 | `default x = open("file")` (file handle — non-revertable) | `tests/fixtures/rules/RPY106/bad_file_handle.rpy` |
| RPY108 | Type taint through `if/else` where branches assign incompatible types | `tests/fixtures/rules/RPY108/bad_if_else_taint.rpy` |
| RPY301 | `{a}` anchor tag inside `{b}{/b}` (nested tags) | `tests/fixtures/rules/RPY301/bad_nested_anchor.rpy` |
| RPY302 | `Jump("label")` inside multiline dialogue string | `tests/fixtures/rules/RPY302/bad_jump_in_multiline.rpy` |
| RPY401 | Menu where one choice terminates with `call screen` (non-terminator) | `tests/fixtures/rules/RPY401/good_call_screen_terminating.rpy` |
| RPY502 | Inline ATL block on `show` (not a top-level transform) | `tests/fixtures/rules/RPY502/bad_inline_atl.rpy` |
| RPY503 | Asset referenced only via `renpy.show("X")` in Python | `tests/fixtures/rules/RPY503/good_python_only_asset.rpy` |
| RPY803 | Translation `new` significantly shorter than `old` (post-1.0 rule candidate, but fixture can land now as a characterization test) | `tests/fixtures/rules/RPY803/bad_short_translation.rpy` |

The fixture harness auto-discovers any new `bad_*.rpy` + `bad_*.json` +
`good_*.rpy` triple in `tests/fixtures/rules/RPYxxx/`. No test file editing
needed. See [How to add a new fixture](#how-to-add-a-new-fixture) below.

### 5. Translations

`README.md` is English, `README_ru.md` is Russian. If you are a native
speaker of another language common in the VN community (Japanese, Chinese,
Korean, Spanish, Portuguese, French, German) — translating the README is a
high-value, low-effort contribution. Keep the badge URLs and the code
blocks unchanged; only translate the prose.

A new `README_<lang>.md` should:

- Add a language switcher link at the top of `README.md`, `README_ru.md`, and
  the new file (the three-line `<p align="center">` block).
- Use the same heading structure (so anchor links work cross-language).
- Translate idiomatic phrases naturally — don't translate "feature freeze"
  literally if your language has a better idiom.

### 6. Corpus FP cleanup (advanced)

Senpy ships with a curated corpus of 15 open-source Ren'Py VN projects
(~17 000 diagnostics total) used to catch false positives that
unit-level fixtures miss. The full workflow — clone, run, triage,
write RED tests, fix the rule, lock in with regression fixtures — is
documented end-to-end in **[docs/corpus-workflow.md](docs/corpus-workflow.md)**.

The single most valuable contribution for a static analyzer is
real-world FP reports that drive rule fixes. Every confirmed FP becomes
a parametrised RED test in `tests/rules/test_corpus_fp.py` (auto-discovered
from `tests/_corpus_triage.json` — no test file editing needed).

Quick start:

```bash
python scripts/collect_corpus.py                   # clone 15 OSS VNs (~3 GB)
python scripts/run_corpus.py --update-baseline     # write baseline.json
python scripts/triage_corpus.py --slug gifting_game # label FPs interactively
                                                    # (or --export-csv / --import-csv)
pytest tests/rules/test_corpus_fp.py -v             # see RED tests
```

Start with small projects (`renpy_vn_template_dual` ~18 diags,
`avnovel` ~40, `gifting_game` ~53) — pattern recognition builds
quickly. The roadmap target is 30–60 confirmed FP cases per corpus
sweep.

See [TP/FP decision guide](docs/corpus-workflow.md#tpfp-decision-guide)
in the workflow doc for concrete per-rule guidance and worked examples.

#### Proposing a new VN for the corpus

If you know of an open-source Ren'Py VN project that:

- is on GitHub with an OSS license (MIT, Apache, GPL, CC-BY, etc.),
- has >1k lines of `.rpy` code,
- you have permission to reference (or own it),

— open an issue proposing it. The maintainer will add it to
`scripts/collect_corpus.py:PROJECTS` (one-place catalog edit) and
shallow-clone it into `tests/_corpus/<project>/` on the next run.

Already in the corpus (15 projects as of 0.9.3): DDLC, LearnToCodeRPG,
DDLCModTemplate 2.0, Monika After Story, alternate DDLC mod template
(zchrxh), renpy-template (RuolinZheng), Renpy-VN-Template (dualfighter1),
BytesOfLove (ufosc), avnovel, cross_channel Chinese localization,
LOVE69 Ren'Py remaster, AquaGuardians, personal-space2, cold_hands,
gifting-game.

### 7. VS Code extension features (TypeScript)

The VS Code extension is in `senpy-vscode/`. Useful TypeScript-side
contributions:

- **Status bar item** showing the number of diagnostics in the current file
  (click to jump to the next one).
- **"Format with senpy" command** in the editor context menu (right-click →
  "Format with senpy" — runs `senpy format` on the current file via the LSP
  `textDocument/formatting` capability, which is already wired).
- **QuickFix preview** — when hovering a QuickFix, show the before/after diff
  in a webview before applying it.
- **Story graph command palette** — `senpy.showStoryGraph` opens a webview
  with Mermaid. Add a "Save as PNG" button (Mermaid 10 supports
  `mermaid.render` to SVG/PNG in browser).

These are **post-1.0** candidates but the extension is not under the same
freeze as the Python core — small UX improvements are welcome.

---

## Solo-maintainer expectations

**Senpy is a one-maintainer project.** This section sets realistic
expectations so you don't get frustrated and the maintainer doesn't burn
out.

### Review time

- Bug reports and feature requests: **acknowledged within ~1 week**.
- Small PRs (typo, fixture, doc fix): **reviewed within 1–2 weeks**.
- Larger PRs (new plugin example, formatter change): **2–4 weeks**,
  sometimes longer. The maintainer reviews every line of every PR and runs
  the change against real Ren'Py projects before merging.

If a PR sits for longer than that, please **ping with a comment** — the
maintainer sometimes loses notifications. Do not open a duplicate PR.

### What gets merged fast

- TDD-style PRs with fixtures (the test file *is* the spec).
- Single-purpose PRs (one rule, one fix, one doc section).
- PRs that follow the existing code style (we don't enforce `ruff format`,
  but match the file you're editing).
- PRs that update `CHANGELOG.md` under `[Unreleased]`.

### What gets rejected or stalled

- PRs without tests (the maintainer will ask for them).
- PRs that mix unrelated changes (a bug fix + a new feature + a refactor).
- PRs that break the existing `DiagnosticSink` Protocol contract or
  introduce import cycles (run `python scripts/check_cycles.py` locally).
- PRs that introduce security-sensitive code (`pickle`, `subprocess`, `eval`,
  network) without a clear justification and a security test.
- **PRs that add new core rules during the feature freeze** (see above —
  write a plugin instead).

### "Good enough" is good enough

The maintainer would rather merge a PR that solves a problem on 80% of
cases and is easy to read than spend three rounds of review pushing for a
"perfect" 100%. If your PR has minor style issues, the maintainer may
**fix them after merge** rather than blocking the PR. Don't be offended —
that's faster for everyone.

### Plugins are the delegation path

If you want a feature that doesn't fit any existing rule domain, or that
only makes sense for your specific Ren'Py project — **write it as a plugin,
not a core rule**. The plugin system exists exactly for this. Plugin rules:

- Don't need maintainer review to be useful (you can use them in your own
  project immediately).
- Don't risk breaking the Senpy core if they have a bug.
- Don't add to the maintainer's review burden.
- Can be promoted to core rules post-1.0 if they prove widely useful.

See `examples/my_senpy_plugin/` and
[Plugin Development README](examples/my_senpy_plugin/MY_SENPY_PLUGIN_README.md)
for a working template. There is also a second example at
`examples/todo_comment_plugin/` that shows a different plugin pattern
(matching `# TODO` / `# FIXME` comments as RPY902).

---

## Quick start

```bash
# 1. Clone
git clone https://github.com/Xilleet/senpy.git
cd senpy

# 2. Install in editable mode with dev dependencies
pip install -e .

# 3. Run tests to confirm setup
pytest tests/

# 4. Try the CLI
senpy test_game --no-cache

# 5. Try the LSP (optional, needs VS Code)
# Open the `senpy-vscode/` folder in VS Code, press F5 to launch Extension Development Host.
```

Requirements:

- Python 3.11+ (3.12 and 3.13 are also tested in CI; 3.14 is experimental).
- Node.js 20+ (only if you touch the VS Code extension).
- PyInstaller (only for release builds; not needed for development).

For LSP testing, you also need `pygls` and `lsprotocol` — `pip install -e .`
pulls them in via `pyproject.toml`'s `dependencies` list.

---

## Project layout

```
senpy/
├── senpy/                       # Main Python package
│   ├── api.py                   # Public stable API: analyze_code, Diagnostic, ...
│   ├── __version__.py           # Single source of truth for version
│   ├── text_utils.py           # Shared text helpers (extract_for_targets, strip_string_literals)
│   ├── cli/                     # Command-line interface
│   │   ├── __main__.py          # Entry point (calls main())
│   │   ├── main.py              # Thin back-compat shim — re-exports public API
│   │   ├── args.py              # argparse builders (parse_args + 5 _add_*_args)
│   │   ├── filters.py           # Diagnostic filtering (--ignore, --select, --tag)
│   │   ├── renderers.py         # 7 output renderers (text, json, sarif, junit, github, rdjson, gitlab)
│   │   ├── early_exits.py       # --version, --help, --check, --diff validation
│   │   ├── runner.py            # main() orchestrator + analysis run + post-analysis handlers
│   │   ├── commands.py          # Per-subcommand implementations
│   │   ├── discover.py          # File discovery (.rpy + .rpyc orphans + .rpa archives)
│   │   ├── format_dispatch.py   # `senpy format` subcommand handler
│   │   ├── inspect_dispatch.py  # `senpy inspect` subcommand handler
│   │   ├── rule_dispatch.py     # `senpy rule list/show` subcommand handler
│   │   ├── unrpyc.py            # .rpyc decompilation via vendored unrpyc + .rpa extraction
│   │   └── _console.py          # Shared Rich Console instance (leaf module)
│   ├── core/                    # Core analysis engine
│   │   ├── analyzer.py          # SenpyAnalyzer — public facade
│   │   ├── analysis_pipeline.py # Per-file analysis orchestration (split from analyzer in 0.8.0)
│   │   ├── file_collector.py    # Stage 1: per-file symbol collection (split in 0.8.0)
│   │   ├── file_discovery.py    # Walk project, find .rpy files
│   │   ├── symbol_table.py      # Stage 2: aggregate per-file scopes into global indexes
│   │   ├── cache.py             # Two-tier disk cache + cross-process lock (R-P0-8)
│   │   ├── cache_manifest.py    # CacheManifest / CachedFileEntry dataclasses
│   │   ├── config.py            # load_config() — reads senpy.toml
│   │   ├── constants.py         # Regexes, RE_BRANCH_TERMINATOR, BUILTIN_COLORS, etc.
│   │   ├── exceptions.py        # SenpyError hierarchy
│   │   ├── logging.py           # setup_logging(), get_logger()
│   │   ├── models.py            # Diagnostic, RuleInfo, etc.
│   │   ├── paths.py             # normalize_path, _relpath_to_cwd helpers
│   │   ├── progress.py          # progress_print for CLI progress bars
│   │   ├── protocols.py         # DiagnosticSinkAnd* Protocols (runtime-checkable)
│   │   ├── renpy_builtins.py    # BUILTIN_SYMBOLS, BUILTIN_ACTIONS (+ senpy.toml extension)
│   │   ├── scope.py             # Variable scope tracking (ScopeStack, ScopeType)
│   │   ├── signature.py         # Call signature inference
│   │   ├── sink.py              # DiagnosticSink
│   │   ├── symbols.py           # VariableSymbol, LabelSymbol, ScreenSymbol, ...
│   │   ├── type_inference.py    # infer_ast_type + binop compat checks (extracted from python_ast)
│   │   └── coverage.py          # Translation coverage metrics
│   ├── domain/                  # Ren'Py domain knowledge
│   │   ├── assets.py            # AssetManager — image/audio file discovery, .rpa scanning
│   │   ├── rpa.py               # safe_load_rpa_index (security: SafeRPAUnpickler)
│   │   ├── renpy_api.py         # Curated Ren'Py built-in API definitions (with examples)
│   │   ├── renpy_api_generated.py  # Auto-generated from RST docs (754 entries)
│   │   ├── data/                # Source data: renpy_api_source.yaml, renpy_api_generated.json
│   │   ├── image_size.py        # PNG/JPEG/GIF/WebP dimension reader (mirrors renpy-magic)
│   │   ├── text_tags.py         # {b}, {i}, {color=...} parser
│   │   └── tsundere.py          # Easter egg banner :)
│   ├── rules/                   # Lint rules
│   │   ├── base.py              # BaseChecker, IfBlockContext
│   │   ├── checkers/            # Per-domain checker modules
│   │   │   ├── state.py         # RPY1xx (state mutations) + if/elif/else stack
│   │   │   ├── screen.py        # RPY2xx (screen UI)
│   │   │   ├── dialogue.py      # RPY3xx (dialogue/labels/jumps)
│   │   │   ├── flow.py          # RPY4xx (branch dataflow) + Mermaid builder + menu flow
│   │   │   ├── formatting.py    # RPY0xx (style)
│   │   │   ├── asset.py         # RPY5xx (assets/transforms)
│   │   │   └── translation.py   # RPY6xx (translations) + RPY8xx (translation consistency)
│   │   ├── deprecated.py        # RPY107 (deprecated APIs) + DEPRECATED_APIS table
│   │   ├── python_ast.py         # Python AST visitor for $-statements (RPY102/104/105/106/108/110/201/208/403)
│   │   ├── rules_info.py        # RULES_DATABASE (53 entries) + dynamic rule count
│   │   └── dead_code.py         # RPY701-707 (unused defines/screens/transforms/labels/parameters)
│   ├── formatter/               # Code formatter (like Black for Ren'Py)
│   │   ├── core.py              # register_rule decorator, Formatter class
│   │   └── rules/               # FMT-INDENT, FMT-QUOTES, FMT-OP-SPACING, ... (9 rules)
│   ├── formats/                 # Output formats
│   │   ├── html_report.py       # HTML report with Mermaid graphs (CSP-hardened)
│   │   ├── wiki.py              # Wiki export
│   │   ├── stats.py             # Story analytics
│   │   ├── sarif.py             # SARIF 2.1.0 for CI
│   │   ├── traceback.py         # Crash log parser
│   │   ├── ci.py                # JUnit XML + GitHub Actions annotations
│   │   ├── gitlab.py            # GitLab Code Quality JSON
│   │   ├── rdjson.py            # Reviewdog NDJSON
│   │   ├── inspect.py           # `senpy inspect` JSON output
│   │   └── stubs.py             # Type stubs generator (`senpy --stubs`)
│   ├── lsp/                     # LSP server (pygls 2.1)
│   │   ├── server.py            # SenpyLSPServer + 19 @feature handlers
│   │   └── handlers/            # Per-LSP-method handlers (split in 0.6.0)
│   │       ├── _shared.py       # Shared helpers (URI validation, utf16 ranges)
│   │       ├── asset_hover.py   # Image/audio preview in hover
│   │       ├── call_hierarchy.py # prepare/incoming/outgoing calls
│   │       ├── completion.py    # textDocument/completion (context-aware)
│   │       ├── definition.py    # textDocument/definition (F12)
│   │       ├── diagnostics.py   # publishDiagnostics + range_formatting (stub)
│   │       ├── document_symbols.py # textDocument/documentSymbols (outline)
│   │       ├── hover.py         # textDocument/hover (API docs + asset preview)
│   │       ├── navigation.py    # Thin shim re-exporting the 6 modules above
│   │       ├── references.py    # textDocument/references (Shift+F12)
│   │       ├── rename.py        # prepare_rename + rename
│   │       ├── text_document.py # didOpen/didChange/didSave/didClose
│   │       └── workspace.py     # workspace/symbol (Ctrl+T) + executeCommand
│   ├── plugins/                 # Plugin system (R-P0-1 audit activated)
│   │   ├── audit.py             # AST-based import-time audit (subprocess/socket/eval/...)
│   │   ├── autoload.py          # One-shot autoload (idempotent, thread-safe)
│   │   ├── base.py              # Rule base class with RuleMeta
│   │   ├── loader.py            # entry_points discovery + trust prompt + audit
│   │   ├── registry.py          # @register_rule decorator
│   │   └── security.py          # API version check + trust store (schema v2)
│   └── vendor/                  # Vendored dependencies (do not modify directly)
│       └── unrpyc/              # .rpyc decompiler (pinned commit, SHA256-verified)
├── senpy-vscode/                # VS Code extension (TypeScript)
├── tests/                       # pytest test suite (2200+ tests)
│   ├── _helpers/                # Shared test fixtures (paths, lsp, quickfix, subprint)
│   ├── assets/                  # RPA archive + image size tests
│   ├── cli/                     # CLI dispatch + subcommand tests
│   ├── core/                    # Analyzer, cache, config, state propagation tests
│   ├── fixtures/rules/          # RPY001-RPY802 fixture triples (52 directories)
│   ├── formats/                 # Output format tests (sarif, rdjson, gitlab, html, mermaid)
│   ├── integration/             # End-to-end: ruff clean, packaging, pre-commit hooks
│   ├── lsp/                     # LSP server tests (hover, completion, rename, references)
│   ├── perf/                    # Performance benchmarks
│   ├── plugins/                 # Plugin system tests (audit, TOFU, autoload, collision)
│   ├── regressions/             # Per-release regression suites (0.6.x → 0.9.x)
│   ├── rules/                   # Rule-specific tests (false positives, fixtures, quickfix)
│   ├── security/                # Trust store, SafeRPAUnpickler, unrpyc security
│   └── conftest.py              # Shared pytest fixtures
├── scripts/                     # Maintenance scripts
│   ├── check_cycles.py          # Import cycle detector (CI-1)
│   ├── clean_internal_ids.py    # Remove stale internal IDs from .senpy_cache
│   ├── fetch_renpy_docs.py      # Regenerate renpy_api_generated.py from Ren'Py RST docs
│   ├── push_badges_to_gist.py   # Push dynamic badges JSON to GitHub Gist (CI)
│   ├── restructure_senpy.py    # One-shot restructure (archived; do not run)
│   ├── sync_rule_count.py       # Verify rule count in docs matches RULES_DATABASE
│   ├── update_badges.py         # Generate dynamic badges (tests + rules + LSP + coverage + speed)
│   ├── update_renpy_api.py      # Update pin: fetch RST SHA256, regenerate JSON
│   └── update_unrpyc_pin.py     # Update pinned unrpyc SHA256
├── docs/                        # Documentation site (mkdocs Material)
├── examples/                    # Example plugins + formatter demo
│   ├── my_senpy_plugin/         # Minimal plugin template (RPY901)
│   ├── todo_comment_plugin/     # TODO/FIXME comment detector (RPY902)
│   └── test_formatter_demo.py   # Manual formatter demo script
├── test_game/                   # Tiny Ren'Py project for smoke tests
├── pyproject.toml               # Build + project metadata + [tool.senpy] config
├── senpy.toml                   # Default config (with comments)
├── bump_version.py              # Version bumper (single source: __version__.py)
├── run_tests.py                # Thin wrapper for `pytest tests/`
├── mkdocs.yml                   # Documentation site config
├── requirements-docs.txt        # MkDocs Material + plugins
├── RULES.md                     # Per-rule documentation (auto-synced)
├── ARCHITECTURE.md              # Internal architecture overview
├── CHANGELOG.md                 # Release history (Keep a Changelog format)
├── SECURITY.md                  # Security policy + plugin audit description
└── CONTRIBUTING.md              # This file
```

---

## How to add a new lint rule

> **Feature freeze:** new core rules (RPY0xx–RPY8xx) are **not accepted**
> until 1.0. Write your rule as a plugin instead (see `examples/my_senpy_plugin/`).
> The instructions below are for post-1.0 or for maintainers doing a rule
> extension on an existing code.

There are two ways: a **core rule** (in `senpy/rules/`) or a **plugin rule**
(distributed as a separate pip package). For core rules:

> **When to choose plugin over core?** If your rule only makes sense for a
> specific Ren'Py project (your visual novel, your mod), or if you're not
> sure whether the maintainer will accept it into core — **write it as a
> plugin first**. You can use it in your own project immediately, without
> waiting for review. If it turns out to be widely useful, you can later
> propose promoting it to core. See
> [`examples/my_senpy_plugin/`](examples/my_senpy_plugin/) for a template.

### 1. Pick a rule code

Rule codes follow a 3-digit prefix by domain:

| Prefix | Domain                  | Example file                |
| ------ | ----------------------- | --------------------------- |
| RPY0xx | Style / formatting      | `rules/checkers/formatting.py` |
| RPY1xx | State / Python execution | `rules/checkers/state.py`   |
| RPY2xx | Screens / UI            | `rules/checkers/screen.py`  |
| RPY3xx | Dialogue / labels / jumps | `rules/checkers/dialogue.py` |
| RPY4xx | Branch dataflow         | `rules/checkers/flow.py` (also has the Mermaid builder + menu flow analysis) |
| RPY5xx | Assets / transforms     | `rules/checkers/asset.py`   |
| RPY6xx | Translations            | `rules/checkers/translation.py` |
| RPY7xx | Dead code               | `rules/dead_code.py`        |
| RPY8xx | Translation consistency | `rules/checkers/translation.py` (same module as RPY6xx) |
| RPY9xx | Plugin-defined          | plugins                     |

Pick the next free number in the appropriate range. Look at
`senpy/rules/rules_info.py` — `RULES_DATABASE` is the single source of truth
for both the rule count and the severity. (Do NOT edit `senpy/core/models.py`
— the `RULE_SEVERITY` there is derived from `RULES_DATABASE`.)

### 2. Register the rule in `RULES_DATABASE`

Edit `senpy/rules/rules_info.py`:

```python
RULES_DATABASE: dict[str, RuleInfo] = {
    ...
    "RPY705": {
        "title": "Pass-only label",
        "severity": "WARNING",  # ERROR / WARNING / INFO / HINT
        "tags": ["dead-code", "label"],  # arbitrary categories for filtering
        "why": "A label whose body consists only of `pass` does nothing.",
        "bad": "label empty_ending:\n    pass\n",
        "good": "label empty_ending:\n    $ persistent.seen_empty_ending = True\n    return\n",
    },
    ...
}
```

`RULE_SEVERITY` in `senpy/core/models.py` is **derived** from this dict at
import time — do not edit it directly.

### 3. Write the checker class

Checkers are **classes** (not functions) inheriting from `BaseChecker`. The
contract is in `senpy/core/protocols.py` (`DiagnosticSinkAndSymbols` and
domain-specific extensions). Example pattern:

```python
# senpy/rules/dead_code.py
from senpy.rules.base import BaseChecker
from senpy.core.models import Diagnostic
from senpy.core.scope import ScopeStack


class DeadCodeChecker(BaseChecker):
    """RPY7xx — dead code detection."""

    # Narrow self.analyzer to the intersection this checker actually uses.
    # BaseChecker types it as DiagnosticSinkAndSymbols; add FlowProvider /
    # AssetProvider as needed (see other checkers for examples).
    analyzer: DiagnosticSinkAndSymbols

    def check_line(
        self,
        file_path: str,
        idx: int,
        next_idx: int,
        raw_line: str,
        clean_line: str,
        scope_stack: ScopeStack,
        noqa_map: dict[int, set[str] | None],
        lines: list[str],
    ) -> tuple[int, bool]:
        """Process one line. Returns (consumed_until_idx, file_modified).

        Most checkers return (next_idx, False) — they only inspect the
        line and emit diagnostics via self.analyzer._add_diagnostic(...).
        Checkers that consume multiple lines (like `python:` blocks or
        `menu:` blocks) return a higher `consumed_until_idx` so the
        analyzer skips the consumed lines.
        """
        stripped = clean_line.strip()
        # Detection logic here
        if is_pass_only_label(stripped, lines, idx):
            self.analyzer._add_diagnostic(
                Diagnostic(
                    file_path=file_path,
                    line_number=idx + 1,
                    line_content=stripped,
                    code="RPY705",
                    message="Label contains only 'pass' — remove or add real logic.",
                    severity="WARNING",
                ),
                noqa_map,
            )
        return next_idx, False
```

Wire it into the analyzer. Most checkers are instantiated in
`senpy/core/analysis_pipeline.py:_analyze_file()` — look at how an existing
checker in the same domain is invoked. The `StateChecker`, `ScreenChecker`,
`AssetChecker`, `DialogueChecker`, `FormattingChecker`, and
`TranslationChecker` are all instantiated there and called per line.

### 4. Add fixtures (TDD)

Create test fixtures under `tests/fixtures/rules/RPY705/`:

```
tests/fixtures/rules/RPY705/
├── bad_pass_only_label.rpy       # Example that triggers the rule
├── bad_pass_only_label.json      # Expected diagnostics
└── good_label_with_logic.rpy     # Example that does NOT trigger
```

The `.json` file format (note: `line` is 1-indexed, `message_fragment` is a
substring that must appear in the diagnostic message):

```json
[
  {
    "code": "RPY705",
    "line": 2,
    "message_fragment": "pass"
  }
]
```

The fixture harness in `tests/rules/test_fixtures.py` auto-discovers any new
`bad_*.rpy` + `bad_*.json` + `good_*.rpy` triple under
`tests/fixtures/rules/RPYxxx/` — no test file editing needed. Run:

```bash
pytest tests/rules/test_fixtures.py -k RPY705 -v
```

### 5. Document the rule

Add an entry to `RULES.md` under the appropriate section. Format:

```markdown
### RPY705 — Pass-only label

**Severity:** WARNING
**Quick fix:** None

A `label` whose body consists only of a `pass` statement is dead code.

#### Bad
```renpy
label empty_ending:
    pass
```

#### Good
```renpy
label empty_ending:
    $ persistent.seen_empty_ending = True
    return
```
```

If the rule is in a new domain (e.g. a new RPY8xx code), also add a section
to `docs/rules/rpy8xx-translations.md`.

### 6. Verify rule count sync

If you added a new rule code, the rule count badge in README will auto-update
(via `rules_info.py` dynamic count), but the documentation files (`README.md`,
`README_ru.md`, `docs/rules/index.md`) hard-code the count and must be
synced. Verify and auto-fix:

```bash
python scripts/sync_rule_count.py --check  # CI runs this — fails if out of sync
python scripts/sync_rule_count.py           # writes the correct count to all docs
```

---

## How to add a new formatter rule

> **Feature freeze:** new formatter rules (`FMT-*`) are **not accepted** until
> 1.0. The 8 candidates listed in `docs/FORMAT_STYLE_GUIDE.md` are tracked
> for post-1.0. The instructions below are for post-1.0.

Formatter rules live in `senpy/formatter/rules/`. Each is a small module with
a `@register_rule` decorator over a **function** (not a class):

```python
# senpy/formatter/rules/comment_align.py
from __future__ import annotations

from senpy.formatter.core import FormatConfig, FormatContext, register_rule


@register_rule("FMT-COMMENT-ALIGN")
def align_comments(contexts: list[FormatContext], config: FormatConfig) -> list[FormatContext]:
    """Align inline comments with the surrounding code."""
    for ctx in contexts:
        if ctx.skip:
            continue
        # Your formatting logic — mutate ctx.raw / ctx.indent as needed
        # ...
    return contexts
```

The function receives a list of `FormatContext` objects (one per line)
and a `FormatConfig`. It mutates the contexts in place and returns the
same list. Rules are applied in registration order (order matters — see
`senpy/formatter/core.py` module docstring).

Add idempotency tests in `tests/formats/test_formatter_idempotency.py` —
formatting already-formatted code must produce zero changes.

---

## How to add a new fixture

Even during the feature freeze, **new fixtures for edge cases of existing
rules are welcome**. This is the single most valuable code contribution a
newcomer can make — it directly improves the test suite and forces you to
understand one rule end-to-end.

### 1. Pick a rule and an edge case

Browse `tests/fixtures/rules/RPYxxx/` and look at the existing `bad_*.rpy`
files. What's NOT covered? See the table in [Good first issues](#4-new-fixture-edge-cases)
for suggestions, or pick your own.

### 2. Create the fixture triple

```
tests/fixtures/rules/RPYxxx/
├── bad_<descriptive_name>.rpy       # Minimal .rpy that triggers the rule
├── bad_<descriptive_name>.json      # Expected diagnostics
└── good_<descriptive_name>.rpy      # Same scenario, but rule should NOT fire
```

The `.rpy` file should be **minimal** — strip everything not needed to
trigger the rule. The `good_*.rpy` should be the same code with the issue
fixed, so the diff between bad and good is obvious.

The `.json` format:

```json
[
  {
    "code": "RPYxxx",
    "line": 3,
    "message_fragment": "substring of the diagnostic message"
  }
]
```

- `code` — must match the rule code exactly.
- `line` — 1-indexed line number where the diagnostic is expected.
- `message_fragment` — a substring that must appear in the diagnostic
  message (case-sensitive). Used to verify the rule fired for the right
  reason, not just any reason.

If the rule fires multiple times on the same file, list each expected
diagnostic as a separate array entry. Order does not matter (the harness
sorts).

### 3. Run the fixture harness

The harness auto-discovers your new triple — no test file editing needed:

```bash
pytest tests/rules/test_fixtures.py -k RPYxxx -v
```

If your `bad_*.rpy` triggers the rule as expected and your `good_*.rpy`
does NOT trigger it, the test passes. If your `bad_*.rpy` does not trigger
the rule (false negative), the harness will report "expected N
diagnostics, got 0" — check that your `.rpy` file actually triggers the
rule via `senpy path/to/bad_*.rpy`.

### 4. Update CHANGELOG

Add an entry under `[Unreleased] → Added` (or `Fixed` if the fixture
exposes a real bug):

```markdown
- **New fixture for RPYxxx edge case: <description>.**
  `tests/fixtures/rules/RPYxxx/bad_<name>.rpy` covers a case not previously
  tested. No code change — fixture only.
```

---

## Testing

### Run the full suite

```bash
pytest tests/ -v
```

The full suite is ~2200 tests and takes ~45s on a modern machine. The
cross-process cache stress tests (`tests/core/test_cache_lock_stress.py`)
add another ~60s — they are excluded from the default test matrix in CI and
run in a dedicated `cache-stress` job.

### Run with coverage

```bash
pytest tests/ --cov=senpy --cov-report=term-missing
```

The CI gate is 85%. Aim to not decrease it with your PR. Coverage is
measured on the `senpy/` package only (not `vendor/`).

### TDD discipline

For bug fixes and new features, follow **RED → GREEN → REFACTOR**:

1. **RED**: Write a test that fails (reproduces the bug, or specifies the new behavior).
2. **GREEN**: Write the minimum code to make it pass.
3. **REFACTOR**: Clean up without changing behavior. Tests stay green.

Do not commit code without tests. The maintainer will ask for tests in code
review if missing.

### Property-based tests (advanced)

For parser/formatter/SSA, consider `hypothesis`-based tests. See
`tests/formats/test_formatter_idempotency.py` for an example pattern.

### Testing the VS Code extension

```bash
cd senpy-vscode
npm install
npm run compile     # esbuild bundle
npm test            # existing tests in src/test/
```

For manual testing: open `senpy-vscode/` in VS Code, press `F5` to launch
Extension Development Host. Open a `.rpy` file and try hover, completions,
format-on-save.

### Testing the LSP server

The LSP tests require `pygls` and `lsprotocol` (installed automatically via
`pip install -e .`). The test suite lives in `tests/lsp/` and includes
end-to-end tests via `tests/_helpers/lsp.py` (a real LSP client fixture).

---

## Commit style and pull requests

### Commit messages

Use the **Conventional Commits** format (without strict enforcement):

```
type(scope): short summary

Optional longer description.
```

Where `type` is one of: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`,
`perf`, `security`.

Examples:

```
feat(rules): add RPY705 — pass-only label detection

Closes #123. Adds a new dead-code rule that flags labels whose body
consists only of a `pass` statement.

Fixtures cover the basic case and a label with a docstring-only body.
```

```
security(lsp): validate file: scheme in _uri_to_path

Previously _uri_to_path accepted any URI scheme, including http: and
https:. A malicious LSP client could trick Senpy into making network
requests or reading unexpected paths.
```

### Pull request checklist

Before opening a PR:

- [ ] Tests added (TDD) and pass locally: `pytest tests/`
- [ ] No regressions in existing tests
- [ ] `RULES.md` updated if you added/changed a rule
- [ ] `CHANGELOG.md` has an entry under `[Unreleased]`
- [ ] Code follows existing style (we don't enforce ruff, but match the file you're editing)
- [ ] No `print()` statements left in code (use `logger` from `senpy.core.logging`)
- [ ] If you touched `pyproject.toml` — verify `python -m build` works
- [ ] If you touched `senpy-vscode/` — verify `npm run compile` works
- [ ] Commit messages follow Conventional Commits
- [ ] Run `python scripts/sync_rule_count.py --check` if you added a rule

### Pull request template

See `.github/PULL_REQUEST_TEMPLATE.md` — it will auto-fill when you open a PR.

### Branch naming

- `feat/<short-description>` — new features
- `fix/<short-description>` — bug fixes
- `docs/<short-description>` — documentation only
- `release/vX.Y.Z` — release preparation

### One PR = one logical change

If you fixed a bug AND added a feature, that's two PRs. Split them. This
makes review faster and git history cleaner.

---

## Releases

**Releases are cut exclusively by the maintainer.** No contributor —
external or otherwise — can trigger a release. The release pipeline is
gated behind a `vX.Y.Z` git tag, and only the maintainer pushes tags.

### Why this matters

Senpy is a one-maintainer project. Releasing means publishing to PyPI
(where versions are immutable — you cannot re-upload the same version
number once published) and uploading a VSIX to GitHub Releases (where
users download it). A botched release cannot be silently rolled back.
Therefore the maintainer personally:

- decides when to release,
- bumps the version (`python bump_version.py <new-version>` — updates
  `senpy/__version__.py` + propagates to `pyproject.toml` and
  `senpy-vscode/package.json`),
- writes the changelog,
- pushes the tag,
- verifies the published artifacts before announcing.

### What CI does automatically

- On every push to `main` or PR: runs `pytest` (ci.yml). Blocks merge if
  tests fail.
- On tag `v*.*.*` push: builds wheel + sdist + VSIX, runs smoke-test on
  `senpy.exe`, publishes to PyPI + GitHub Release (release.yml).

CI never publishes on its own — **the tag push is the trigger**, and only
the maintainer can push tags. Even a merged PR does not trigger a release;
only the maintainer's manual `git tag vX.Y.Z && git push origin vX.Y.Z` does.

### Release process (maintainer-only)

1. Confirm all tests green on `main`.
2. Update `senpy/__version__.py` (single source of truth) via
   `python bump_version.py <new-version>`.
3. Update `CHANGELOG.md` with the new version section.
4. Run `python -m build` locally to verify packaging works.
5. Commit: `git commit -am "release vX.Y.Z"`.
6. Tag: `git tag vX.Y.Z && git push origin main --tags`.
7. Watch the `release.yml` workflow in Actions tab. It runs:
   - tests (pre-release check),
   - cross-process cache stress tests,
   - build (wheel + sdist),
   - build-vsix (PyInstaller + smoke-test + vsce package),
   - publish-pypi (uploads to PyPI),
   - github-release (uploads VSIX + wheel to GitHub Releases).
8. Verify on PyPI (`https://pypi.org/project/senpy-linter/`) and on the
   GitHub Releases page that artifacts landed.
9. If anything went wrong: **PyPI versions are immutable** — you have to
   bump the patch version (e.g. 0.6.2 → 0.6.3) and re-release. Yanking is
   possible but does not remove the file from existing installs.

### What contributors can do

Contributors **cannot**:

- push tags (branch protection on `main` + tags),
- trigger release workflow manually (no `workflow_dispatch` on `release.yml`),
- publish to PyPI (only the maintainer's `PYPI_API_TOKEN` secret works),
- create GitHub Releases (requires `contents: write` permission, only
  the `github-actions` bot has it inside the workflow).

Contributors **can**:

- open PRs (which run CI but never trigger release),
- propose a release in a Discussion or Issue ("I think we should cut 0.9.1
  because X is fixed"),
- maintain their own fork with custom tags (irrelevant to upstream).

---

## Code of conduct

Be kind. Be patient. Assume good faith. The maintainer is one person doing
this in their free time.

### Be patient with review

The maintainer sometimes takes 1–4 weeks to review a PR (see
[Solo-maintainer expectations](#solo-maintainer-expectations)).
If your PR sits for longer than that,
**ping with a comment** instead of opening a duplicate.

### Don't aim for "perfect" — aim for "shipped"

The maintainer would rather merge a "good enough" PR today and improve it
in a follow-up than wait three months for a "perfect" one. If your PR has
rough edges, open it anyway and explain them in the description. The
maintainer will either merge as-is and fix the edges, or suggest a small
change list.

### Don't be precious about your code

Once a PR is merged, the code is **ours**. The maintainer (and
other future contributors) will refactor it, rename things, move it around.
This is normal and don't take it personally — your contribution is still
credited in the commit history and (if you want) in `CHANGELOG.md`.

### Security reports

If someone is being unkind in an issue or PR, email the maintainer
privately (see [SECURITY.md](SECURITY.md) for the channel). We will block
repeat offenders.

Security vulnerabilities are **not** reported via public GitHub Issues —
see [SECURITY.md](SECURITY.md) for the private reporting channel.

---

## Questions?

- **Bug reports / feature requests**: [GitHub Issues](https://github.com/Xilleet/senpy/issues)
- **General questions**: [GitHub Discussions](https://github.com/Xilleet/senpy/discussions)
- **Security**: see [SECURITY.md](SECURITY.md) — do NOT open public issues for security reports.

Thank you for contributing!
