# Changelog

All notable changes to Senpy are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.6] — Core & Other God-functions Refactor (internal, not tagged)

### Architecture

Internal refactor of `core/analyzer.py`, `domain/text_tags.py`,
`formats/stats.py` + 2 new modules. No user-visible changes — all lint rules,
diagnostics, and behavior identical. 6 god-functions split into 14 helpers.

* **`_check_unused_declarations` (97 lines → thin wrapper):** Moved to new
  module `senpy/rules/dead_code.py` — RPY701/702/703 (unused define/transform/screen).
* **`_analyze_tl_file` + `_parse_tl_pairs` + `_validate_tl_pairs` (~180 lines →
  thin wrappers):** Moved to new module `senpy/rules/checkers/translation.py`
  — RPY601/602/603 (translation validation).
* **`run()` (181 lines → 35 lines + 4 helpers):** `_run_reset` (state reset),
  `_collect_all_symbols` (Tier 1 cache symbol collection),
  `_analyze_all_files` (Tier 2 cache rule analysis),
  `_finalize_results` (post-checks + TL validation + severity + cache save).
* **`_analyze_file` (139 lines → 118 lines + 2 helpers):**
  `_read_file_lines` (in-memory/stage1/disk with error handling),
  `_write_fixed_file` (write modified lines for --fix).
* **`process_quoted_strings` (218 lines, CC=35 → 180 lines + 2 helpers):**
  `_check_interpolation_vars` (RPY101 undeclared variable check),
  `_check_color_tag` (RPY304 hex/named color validation).
* **`collect_story_stats` (131 lines → 83 lines + 3 helpers):**
  `_count_extend_words` (extend "..." word counting),
  `_parse_dialogue_line` (dialogue matching + char_stats update),
  `_build_story_stats` (percentage calculation + StoryStats result).

### New Modules

* `senpy/rules/dead_code.py` — dead code detection (RPY701/702/703)
* `senpy/rules/checkers/translation.py` — translation file analysis (RPY601/602/603)

### Notes

* **Analyzer rewrite deferred to 0.8.0** — splitting analyzer into
  `SenpyProject` + `AnalysisPipeline` + `SymbolRegistry` requires SSA (φ-functions)
  to be useful. Current extract method is preparation.
* **Monkey-patch `builtins.open` for `--diff` preserved** — removing it requires
  (analyzer.run() with dry_run_callback). TODO in `_setup_diff_interception`.
* **Not tagged** — internal refactor.

## [0.6.5] — AST & Checkers God-functions Refactor

### Architecture

Internal refactor of rule engine internals — `rules/python_ast.py`,
`rules/checkers/screen.py`, `rules/checkers/dialogue.py`,
`rules/checkers/state.py`. All lint rules,
diagnostics, and behavior identical. 7 god-functions split into 31
testable helpers.

* **`infer_ast_type` (145 lines, CC=62 → 44 lines, CC≈9 + 9 helpers):**
  The most complex function in the project is now a simple dispatch table
  delegating to `_infer_constant`, `_infer_name`, `_infer_collection`,
  `_infer_unaryop`, `_infer_binop`, `_infer_ifexp`, `_infer_call`,
  `_infer_builtin_function`, `_infer_method_call`. Each helper has CC ≤ 4.
  Return type unchanged (`str | None`) — all callers work without modification.
  TODO(future): Replace with Type Lattice (`TypeHint.join()`) in 0.8.0 (SSA).
* **`_visit_augassign` (145 lines → 18 lines + 3 helpers):**
  `_check_augassign_name` (RPY105/RPY102/RPY108 for Name target),
  `_check_augassign_type_conflict` (RPY108 type compatibility),
  `_check_augassign_subscript` (RPY105/RPY102 for Subscript target).
* **`_visit_assign` (133 lines → 30 lines + 4 helpers):**
  `_check_assign_set_usage` (RPY106), `_check_assign_name_target` (RPY104/RPY108),
  `_check_assign_subscript_target` (RPY105/RPY102), `_check_assign_tuple_target` (RPY104).
* **`_visit_mutating_methods` (128 lines → 22 lines + 2 helpers):**
  `_check_mutating_method_call` (RPY105/RPY102 for .append/.update),
  `_check_invalid_method_call` (RPY108 for list.add → .append).
* **`screen.py:check_line` (219 lines → 37 lines + 4 helpers):**
  `_check_screen_variable_actions` (RPY202/RPY208),
  `_check_screen_action_targets` (RPY204),
  `_check_screen_buttons` (RPY203/RPY206),
  `_check_screen_call_targets` (RPY204/RPY207).
* **`dialogue.py:check_line` (204 lines → 40 lines + 4 helpers):**
  `_check_label_fallthrough` (RPY308),
  `_check_jump_call_targets` (RPY302/RPY306/RPY310),
  `_check_dynamic_jump_targets` (RPY302 via Jump/Call actions),
  `_check_unescaped_quotes` (RPY305).
* **`state.py:check_line` (184 lines → 50 lines + 5 helpers):**
  `_manage_if_elif_else_stack` (if/elif/else control flow tracking),
  `_check_menu_block` (menu: handling), `_check_python_inline` ($ code),
  `_check_python_block` (python: block), `_check_condition` (if/elif/while).

### Tests

* 898 passed (unchanged from 0.6.4 — existing fixture tests for all
  RPY1xx/2xx/3xx/4xx rules served as characterization safety net).
* No new test files — fixture coverage was already sufficient.

### Notes

* **Type Lattice (`TypeHint.join()`) deferred to 0.8.0** — it requires SSA
  (φ-functions at merge points) to be useful beyond `IfExp`. Current extract
  method is preparation: each helper is isolated, making future replacement
  straightforward. TODO comment added in `infer_ast_type`.
* **7 god-functions → 31 helpers** — cyclomatic complexity

## [0.6.4] — CLI God-functions Refactor (internal, not tagged)

### Architecture

Internal refactor of `cli/main.py` (+ new `format_dispatch.py`).
No user-visible changes — all CLI flags, output formats, and behavior identical.
All 5 god-functions split into testable helpers with characterization tests.

* **`main()`:** Extracted `_dispatch_subcommand`
  (subcommand registry, extensible for future `check`/`lsp`/`graph`/`ci`/`clean`),
  `_handle_early_exits` (--version/--lsp/--rules/--rule/--traceback/--init-ci/
  --coverage/--clear-cache), `_setup_rule_filters` (combines --ignore/--extend-ignore/
  config/.senpy-ignore), `_print_scan_banner`, `_setup_diff_interception`,
  `_run_analysis`, `_handle_post_analysis`, `_handle_output_format`,
  `_handle_check_mode`, `_handle_diff_mode`.
* **`parse_args()`:** Extracted `_add_general_args`,
  `_add_rules_args`, `_add_lint_args` (16 flags), `_add_export_args`, `_add_tools_args`.
* **`render_text()`:** Extracted
  `_render_diagnostic_cards`, `_render_summary_table`, `_render_fixable_report`,
  `_render_summary_line`.
* **`_dispatch_format()`:** Extracted to new module
  `senpy/cli/format_dispatch.py` with `dispatch_format()` function. `_dispatch_format`
  in main.py is now a thin re-export wrapper for backward compatibility.
* **`discover_files()`:** Extracted
  `_find_rpy_files`, `_find_orphaned_rpyc`, `_decompile_sandbox`.

### Tests

* 96 characterization tests added (898 total):
  - `test_format_dispatch_characterization.py` (14 tests)
  - `test_discover_files_characterization.py` (8 tests)
  - `test_render_text_characterization.py` (18 tests)
  - `test_parse_args_characterization.py` (45 tests)
  - `test_main_characterization.py` (11 tests, subprocess-based, cross-platform)

### Notes

* **Monkey-patch `builtins.open` for `--diff` preserved** (not removed). Removing
  it requires `analyzer.run()` to accept a `dry_run_callback` parameter, which is
  part of ARCH-13..15 (0.6.6 Core refactor). TODO comment added in
  `_setup_diff_interception`.
* **Subprocess tests use `python -m senpy.cli`** (via `sys.executable`) instead of
  bare `senpy` command — works without `pip install -e .` and on Windows without
  senpy.exe in PATH. Also forces UTF-8 encoding (avoids cp1251 crash on Russian
  Windows) and sets PYTHONPATH to repo root (so `import senpy` works from any cwd).
* **Not tagged** — internal refactor,. Next tagged release
  (0.6.5) will include these commits.

## [0.6.3]

### Exception hierarchy

* **Domain exception hierarchy** (`senpy/core/exceptions.py`): New module with `SenpyError` base class and 8 domain exceptions (`ConfigError`, `AnalysisError`, `ParseError`, `SymbolResolutionError`, `CacheError`, `PluginError`, `SecurityError`, `DecompilationError`). `SecurityError` also inherits from `ValueError` for backward compat with LSP-19 callers. `ApiVersionMismatchError` now inherits from `PluginError`. 27 TDD tests.
* **Migrate `contextlib.suppress()` to `try/except + logger.debug`** (8 files, 20 sites): All silent exception suppression now logs at DEBUG level. Files: `core/signature.py` (2), `core/cache.py` (2), `rules/python_ast.py` (9), `formats/traceback.py` (1), `formats/stubs.py` (1), `domain/assets.py` (1), `domain/tsundere.py` (1), `cli/unrpyc.py` (4). 6 TDD tests.
* **Domain exceptions instead of silent return**: `_uri_to_path` now raises `SecurityError` (was `ValueError`). `download_unrpyc` SHA mismatch now logs ERROR (was silent `return None`). Backward compat preserved. 5 TDD tests.

### LSP Killer-Features

* **`textDocument/rename` for variables/transforms/screens** (`senpy/lsp/handlers/navigation.py`): Previously rename only worked for labels. Now also supports variables (default/define), transforms (transform X:), and screens (screen X():). Uses whole-word text search across all `.rpy` files in project. 4 TDD tests.
* **`textDocument/references` for variables/transforms/screens**: Same extension as LSP-17. `include_declaration` flag respected. 5 TDD tests (including backward compat for label references).

### CLI UX

* **`--select` / `--extend-select` / `--extend-ignore` flags** (`senpy/cli/main.py`): Ruff/eslint-style rule filtering. `--select RPY101 RPY102` runs ONLY these rules. `--extend-select` adds to whitelist (only effective with `--select`). `--extend-ignore` adds to blacklist. Config keys `select`, `extend_select`, `extend_ignore` in `senpy.toml` also supported. 9 TDD tests.
* **`.senpy-ignore` file** (`senpy/cli/main.py`): Project-level bulk rule exclusions. One rule code per line, comments with `#` (full-line and inline), case-insensitive (normalized to uppercase). File searched in project root. 13 TDD tests.
* **Pydantic config validation** (`senpy/core/config.py`): `senpy.toml` `[tool.senpy]` section now validated via pydantic v2 (`SenpyConfig` model). Invalid types (e.g. `max_errors = "много"`) log WARNING and fall back to defaults. `strict=True` mode — no type coercion. Unknown fields ignored for forward-compat. Added `pydantic>=2.0` to dependencies. 11 TDD tests.

### Tests
* 801 passed.

### Notes
* This release combines 0.6.2 (skipped as separate tag) and 0.6.3 work. Git history between v0.6.1 and v0.6.3 contains all commits.
* **Breaking change for advanced users**: `load_config()` now returns pydantic-validated dict with all default fields populated (was raw TOML dict). If your code does exact dict comparison on config, update to check specific keys.

## [0.6.2]

### Security

* **Workspace containment check in `_uri_to_path`** (`senpy/lsp/server.py`): Added `file:` scheme validation (http/https/ftp/empty URIs now raise `ValueError`) + optional `workspace_root` parameter with path-traversal protection via `os.path.realpath()` + `os.path.commonpath()`. Backward-compatible. 11 TDD tests.
* **Shell injection fix in VS Code extension** (`senpy-vscode/src/extension.ts`): Replaced 2× `cp.exec` with template-string interpolation by `cp.execFile` with array args. Added `windowsHide: true`.
* **Symlink-loop protection in `os.walk`** (6 sites): Added explicit `followlinks=False` to all `os.walk()` calls in `cli/main.py:817,831`, `cli/unrpyc.py:182`, `core/analyzer.py:717`, `domain/assets.py:22,57`.
* **Subprocess timeout for unrpyc probe** (`senpy/cli/unrpyc.py:190`): Added `timeout=30` to `subprocess.run([sys.executable, "-m", "unrpyc", "--help"], ...)`.

### Logging

* **`senpy/core/logging.py`** — centralized logging setup. `setup_logging(verbose, log_file, level)` + `get_logger(name)`. Library-style: `NullHandler` by default (critical for LSP mode where stderr is reserved for protocol). `propagate=True` for pytest caplog. 14 TDD tests.
* **Migrate `print()` to `logger` in `plugins/loader.py`**: 5× `print("[senpy.plugins] WARNING: ...", file=sys.stderr)` → `_logger.warning(...)`. 4 TDD tests.

### CI Safety

* **Release smoke-test** (`.github/workflows/release.yml`): Expanded `Verify senpy.exe` step from 2 lines to full smoke-test — binary exists, `--version`, runs `test_game --no-cache --output-format json`, validates JSON output structure.
* **Weekly unrpyc update check** (`.github/workflows/unrpyc-check.yml`): New scheduled workflow (Monday 09:00 UTC). Compares unrpyc master SHA256 vs pinned. If different — opens GitHub Issue with label `unrpyc-update,dependencies`. Does NOT auto-PR.

### Documentation

* **`CONTRIBUTING.md`** — quick start, project layout, how to add a lint rule (6 steps), formatter rule, TDD discipline, Conventional Commits, PR checklist, release process. Explicit "releases cut exclusively by maintainer" policy.
* **`SECURITY.md`** — supported versions, private reporting via GitHub Security Advisories, response timeline (48h/7d/30d), scope, list of existing security features, hardening checklist for plugin authors, coordinated disclosure policy.
* **`.github/ISSUE_TEMPLATE/`** — 3 templates: bug_report.yml, feature_request.yml, false_positive.yml.
* **`.github/PULL_REQUEST_TEMPLATE.md`** — type-of-change checkboxes, backlog ref, TDD RED/GREEN/REFACTOR checklist, smoke-test section.
* **README "Why You Need This" section** — 6 real-world bugs that `renpy lint` misses and Senpy catches: save-breaking define mutation (RPY105), NameError after save load (RPY104), branch asymmetry (RPY401/404), wrong collection method (RPY108), unused assets (RPY701/702/703), translation breakage (RPY601).

### Misc

* **Log `TOMLDecodeError` in `load_config`** (`senpy/core/config.py`): Replaced `contextlib.suppress(TOMLDecodeError, OSError)` with explicit try/except + `logger.warning`. 4 TDD tests.

### Tests
* 759 passed.

## [0.6.1]

### Fixed
* **PyInstaller entry point fix** (`senpy.spec`, `senpy/cli/__main__.py`): Root cause of VSIX/LSP crashes. `senpy.spec` pointed to `senpy/cli/main.py` which only *defines* `main()` but doesn't call it. Changed to `senpy/cli/__main__.py` which actually executes `main()`. Also wrapped `__main__.py` in `try/except` to catch and display any future import errors instead of silently crashing.
* **Python 3.14 `@dataclass` compatibility** (`senpy/core/cache.py`): Inlined `CachedFileEntry` and `CacheManifest` dataclasses back into `cache.py`. Python 3.14 changed `dataclasses._is_type()` to access `sys.modules` during decoration, which crashed with `AttributeError` when loading `cache_manifest.py` during `__init__.py` chain. `cache_manifest.py` kept as backward-compat re-export.
* **Old cache module redirect** (`senpy/core/cache.py`): Added `_MODULE_REDIRECTS` dict in `SafeCacheUnpickler`. Old `cache.pkl` files (created before 0.5.5) referenced `senpy.cache`, `senpy.models`, etc. which no longer exist. Now redirected to `senpy.core.*` paths automatically.
* **Hover on `show/scene/hide` attributes** (`senpy/lsp/handlers/hover.py`): Hovering over sprite attributes (e.g., `1b` in `show sayori 1b`) no longer incorrectly shows `define b = DynamicCharacter(...)`. Added guard that checks if cursor is within image tag tokens.
* **Clickable jump targets in hover** (`senpy/lsp/handlers/hover.py`): "Jumps to: `credits2`, `hideconsole`" links are now clickable and navigate to the target label's definition, same as "Declared at" links.
* **`--version` output buffering** (`senpy/cli/main.py`): Changed `sys.exit(0)` to `return 0` for `--version` flag. Fixes PyInstaller on Windows not flushing stdout buffer before process exit when output is captured by a pipe.
* **`executablePath` validation** (`senpy-vscode/src/extension.ts`): Added `fs.existsSync()` check. If user configures `executablePath` but the file doesn't exist (e.g., dev path not present on user machine), Senpy now silently falls back to bundled binary instead of crashing.

### Added
* **"Senpy: Restart Language Server" command** (`senpy-vscode/package.json`, `extension.ts`): New command available via `Ctrl+Shift+P`. Stops and restarts the LSP server without reloading the VS Code window.
* **`--show-fixes` CLI flag** (`senpy/cli/main.py`): Shows detailed list of applied fixes (`file:line: rule — fix_title`) when used with `--fix`.
* **`--output-format junit` and `--output-format github`** (`senpy/cli/main.py`): JUnit XML format for CI systems (Jenkins, GitLab). GitHub Actions `::error file=X,line=N::message` annotations for PR reviews.

### Changed
* **Build scripts consolidation**: Replaced `build_exe.bat` and `build_vsix_dev.bat` with a single `reinstall.bat` that handles the full build cycle (PyInstaller → TypeScript compile → VSIX package → install).
* **`senpy.spec`**: Added `collect_all('senpy')` to ensure all submodules (including dynamically imported `senpy.plugins.*` and `senpy.formatter.rules.*`) are bundled into `senpy.exe`.

## [0.6.0]

### Plugin System (EXT-1..7, EXT-11)
* **EXT-7: `senpy.api` public module** — explicitly stable API for plugin developers and library users. Re-exports `Diagnostic`, `RULE_SEVERITY`, `AnalysisResult`, adds `Location` dataclass and `analyze_code(code: str) -> list[Diagnostic]` high-level one-liner function. Internal modules (`senpy.core.*`, `senpy.rules.*`) may change between minor versions, but `senpy.api` stays backward-compatible within the same major.
* **EXT-3: `Rule` base class** with `RuleMeta` (ESLint-style: `code`, `docs`, `severity`, `fixable`, `tags`, `deprecated`, `replaced_by`) and `RuleContext` (`file_path`, `lines`, `symbols`, optional `analyzer` and `config`).
* **EXT-2: `@register_rule("RPYxxx")` decorator** for lint rules (previously only existed for formatter rules).
* **EXT-1: Plugin loading via `[project.entry-points."senpy.plugins"]`** — `discover_plugins()`, `load_plugin()`, `load_all_plugins()`, `register_loaded_plugins()`. Plugins discovered via `importlib.metadata.entry_points`. Each plugin loaded with isolation (failed plugin skipped, others continue).
* **EXT-11: `examples/my_senpy_plugin/`** — working example plugin (RPY901: flags dialogue without `_()` for translation). Includes `pyproject.toml` with entry_points declaration, comprehensive README (454 lines) covering installation, trust flow, plugin authoring, QuickFix, testing, PyPI publishing, debugging.

### Plugin Security (SEC-P1, SEC-P2)
* **SEC-P1: `PLUGIN_API_VERSION = "1.0"`** — each plugin declares which Senpy plugin API version it targets. `check_api_version()` verifies compatibility (same major required; plugin minor > Senpy minor rejected). Incompatible plugins are skipped with a warning, not crashed.
* **SEC-P2: Trust-on-first-use security model**. Trust store at `~/.senpy/trusted_plugins.json` (or `$SENPY_HOME/trusted_plugins.json`). First plugin load in TTY prompts `[y/N]`; choice persisted. Non-interactive (CI, no TTY) skips untrusted plugins (fail-safe). Pre-trust API: `trust_plugin(name)`, `untrust_plugin(name)`, `is_plugin_trusted(name)`, `get_trusted_plugins()`.

### LSP Killer-Features (LSP-1, LSP-2, LSP-5, LSP-6)
* **LSP-1: `textDocument/documentColor` + `colorPresentation`** — hex colors (`#rrggbb`, `#rrggbbaa`) in `.rpy` files shown as color swatches in VS Code. Detects colors in `{color=#...}` tags, `Solid("#...")`, `Color("#...")`, and init python literals. Skips `#` comments. Clicking a swatch opens VS Code's color picker; selecting a new color updates the literal via `colorPresentation`.
* **LSP-2: `textDocument/formatting` + `rangeFormatting`** — Shift+Alt+F (Format Document) and Ctrl+K Ctrl+F (Format Selection) in VS Code now run the Senpy formatter. Integrates all 8 formatter rules (FMT-INDENT, FMT-TRAILING-WS, FMT-EOF-NEWLINE, FMT-BLANK-LINES, FMT-QUOTES, FMT-OP-SPACING, FMT-COMMA-SPACING, FMT-COLON-SPACING). Idempotent: formatting already-formatted code produces no edits.
* **LSP-6: `textDocument/signatureHelp`** — parameter hints for `call label(...)` and `use screen(...)`. When typing `call my_label(`, VS Code shows the label's signature (e.g. `my_label(name, age)`). Active parameter tracking via comma counting (cursor on 2nd param highlights it). Falls back to analyzer when snapshot is stale.
* **LSP-5: `textDocument/prepareCallHierarchy` + `incomingCalls` + `outgoingCalls`** — right-click on label → "Find Callers" shows all `jump`/`call` sites across the project (via `jump_sources` reverse index). "Find References" shows all outgoing jumps (via `LabelSymbol.outgoing_jumps`). Killer feature for VN — navigate the call graph visually.

### Formatter Stage 2 (FMT-1, FMT-3, FMT-4, FMT-5, FMT-6)
* **FMT-1: `FMT-QUOTES`** — smart/curly quotes (`“”`, `‘’`, `«»`) → straight quotes in CODE statements. Dialogue lines (starting with `"` or `'`) preserve smart quotes (stylistic).
* **FMT-3: `FMT-OP-SPACING`** — binary operators (`+ - * / % = == != < > <= >= += -= *= /= // ** << >> & | ^`) → single space around. Unary preserved (`-5` stays `-5`, not `- 5`). String contents untouched.
* **FMT-4: `FMT-COMMA-SPACING`** — comma followed by word/quote/opening-bracket → add space. Trailing comma before `) ] }` → leave (no space). String contents untouched.
* **FMT-5: `FMT-COLON-SPACING`** — remove space before block-opening colon (`if x :` → `if x:`). Dict colons `{a:1}` and slice colons `a[1:2]` untouched. String contents untouched.
* **FMT-6: Idempotency tests** — all 4 new rules + combined interaction + skip-block preservation covered (37 tests total in `tests/test_0_6_0_subprint.py`).

### CLI UX (CLI-3, CLI-10, CLI-19)
* **CLI-3: `--show-fixes`** — detailed list of applied fixes (`file:line: rule — fix_title`). Without `--fix`, shows "0 fixes applied". Useful for CI logs and audit.
* **CLI-10: `--output-format junit`** — JUnit XML output for CI systems (Jenkins, GitLab CI, TeamCity). Groups diagnostics by file into `<testsuite>` elements with `<failure>`/`<skipped>` tags.
* **CLI-10: `--output-format github`** — GitHub Actions `::error file=X,line=N::message` annotations. GitHub automatically renders these as PR annotations with clickable file:line links.
* **CLI-19: `--defaults` flag** (already existed, verified with tests) — generates `senpy_defaults.rpy` with `default x = 0` for variables created via `$ x = 1` without `default` declaration (RPY104).

### Tests
* 689 passed (548 existing + 141 new across 6 test files).
* Coverage 77.37% (without vendored unrpyc, which is excluded from `pyproject.toml [tool.coverage.run] omit`).

### Notes
* This is a **feature release**: plugin system + 4 LSP killer-features + 4 formatter rules + CLI UX. No breaking changes to existing API — all new features are additive.
* Plugin system is foundation for community contributions: anyone can now write a lint rule as a pip package and Senpy picks it up automatically (with trust prompt).
* LSP features bring Senpy closer to parity with rust-analyzer / pyright for Ren'Py development.

## [0.5.8]

### Security
* **AUD-001: Defense-in-depth blocklist в `SafeUnpickler.find_class`** (`senpy/vendor/unrpyc/decompiler/magic.py`).
  Добавлен `_DANGEROUS_MODULES_BLOCKLIST` (frozenset из 11 модулей: `os`, `sys`, `subprocess`, `socket`, `shutil`, `pathlib`, `builtins`, `ctypes`, `multiprocessing`, `pickle`, `marshal`). Если кто-то случайно добавит опасный модуль в `safe_modules`, `SafeUnpickler` отклонит его и вернёт `FakeClass` вместо `__import__('os')`. Сверка подтвердила: Senpy уже использовал `SafeUnpickler` через `pickle_safe_loads` (main path безопасен) — фикс закрывает defense-in-depth риск. 5 новых тестов в `tests/test_aud_001_security.py`.

### Packaging
* **AUD-002: `lsprotocol` добавлен в `pyproject.toml [project] dependencies`**. Раньше `pip install senpy-linter` падал на `from lsprotocol import types as lsp`, потому что зависимость отсутствовала в METADATA.
* **AUD-003: Синхронизированы `pyproject.toml` и `senpy/requirements.txt`**. В `pyproject.toml` установлены compatible-release constraints (`rich~=15.0`, `pygls~=2.1`, `lsprotocol>=2025.0.0`). `requirements.txt` остаётся dev lock file с `==` pinned версиями.
* **AUD-004: Удалён `types_or: [python, text]` из `.pre-commit-hooks.yaml`**. Hook никогда не запускался для `.rpy` файлов, потому что `.rpy` не имеет типа `python` или `text`. Теперь hook корректно фильтрует через `files: \.(rpy|rpym)$`.

### Documentation
* **DOC-7: Исправлен unclosed `<img>` тег в `README.md`** (строка 10). Сломанный HTML рендерился криво на GitHub.
* **DOC-8: Унифицировано число правил во всех источниках**. `senpy/rules/rules_info.py:show_rules_table()` теперь использует `f"... (All {len(RULES_DATABASE)} Rules)"` вместо хардкода «45» (DOC-8a). README badge уже был «45». `senpy.toml` использует «All Senpy Rules» без числа с 0.5.2.
* **DOC-8a: Динамический подсчёт числа правил** через `len(RULES_DATABASE)`. Если завтра добавят 46-е правило — заголовок автоматически обновится, ничего править не нужно. Также исправлен регэксп в `test_rules_info_py_uses_dynamic_count` (он пропускал хардкод внутри `title="... (All 45 Rules)"`).
* **DOC-9a: Добавлена секция «Dead Code Detection (RPY7xx)» в `RULES.md`** с описаниями RPY701 (unused `define`), RPY702 (unused `transform`), RPY703 (unused `screen`). Навигация в начале `RULES.md` обновлена. RPY701/702/703 добавлены в EN cheat sheet в `senpy.toml`.

### CI
* **CI-1 (НЕ добавлен): Ruff lint в CI — сознательный отказ мейнтейнера**. Ruff's придирки к пустым строкам и стилю не меняют сути рабочего кода, а цена gate превышает пользу. Шапка `ci.yml` обновлена с явным обоснованием. Ruff доступен локально через `pyproject.toml [tool.ruff]` для желающих.
* **CI-3: Coverage gate добавлен в CI**. `pytest tests/ -v --tb=short` → `pytest tests/ --cov=senpy --cov-fail-under=75 --tb=short`. Порог 75% (текущий coverage 77% без vendor). Поднимем до 80% после QUA-7 (типизация 95%+). `senpy/vendor/*` добавлен в `pyproject.toml [tool.coverage.run] omit` — vendored unrpyc — чужой код.
* **CI-4: macOS добавлен в matrix** (Python 3.12, 1 добавочный job). Safety net для контрибьюторов на macOS (path separators, case-sensitivity FS, framework Python). Не полный matrix 3×3=9 jobs — экономит минуты.

### Decisions (отказ от задач)
* **QUA-1, QUA-2, QUA-5 — НЕ сделаны** (сознательный отказ вместе с CI-1): ruff не включается ни в CI, ни в ручной workflow. `ruff check --fix` и `ruff format` переписали бы 34+ файлов косметически без функциональной пользы и ухудшили blame-историю. Если в будущем ruff снова включат — задачи вернутся.

### Tests
* 553 passed (548 existing + 5 новых security-тестов в `tests/test_aud_001_security.py`).
* Coverage 77.37% без vendor (vendored unrpyc исключён из подсчёта).

### Notes
* Это stability & cleanup релиз: закрыты все P0 из аудита v0.5.7 (AUD-001..004), CI gates налажены, документация актуализирована. Никаких breaking changes, никаких новых фич — подготовка фундамента под 0.6.0 (LSP killer-features + plugin system).

## [0.5.7]

### Changed
* **Разбиты 3 god-функции:**
  * `rules/checkers/asset.py:AssetChecker.check_line` (352 → 23 строки dispatcher): извлечены `_check_show_scene()` (RPY502: show/scene/ATL/transitions) и `_check_audio_statement()` (RPY501/RPY505: play/queue/stop)
  * `rules/flow.py:StoryFlowAnalyzer.analyze_menu_flow` (151 → 25 строк dispatcher): извлечены `_parse_menu_choices()`, `_analyze_choice_body()`, `_merge_menu_branches()`
  * `rules/flow.py:StoryFlowAnalyzer.generate_mermaid_graph` (133 → 8 строк dispatcher): вынесен в модульный класс `MermaidBuilder` (`build()` метод). Тонкий диспетчер сохранён для обратной совместимости (`core/analyzer.py:1559` вызывает `self.flow.generate_mermaid_graph()`)

### Notes
* Это минорный рефакторинг-релиз: поведение неизменно, 497 тестов зелёные.

## [0.5.6]

### Changed
* **Разбиты 3 god-функции (Phase 3):**
  * `cli/main.py:main()` (719 → 220 строк): извлечены `parse_args()`, `filter_diagnostics()`, `render_sarif()`, `render_json()`, `render_text()`, `discover_files()`
  * `rules/python_ast.py:_walk_python_nodes` (479 → 30 строк dispatcher): извлечены 8 `_visit_*` методов
  * `core/analyzer.py:_collect_symbols` (378 → 80 строк dispatcher): извлечены 7 `_collect_*` методов

### Fixed
* `_collect_screen_transform`: early return делал transform-обработку dead code (исправлено)
* `current_screen` context не сбрасывался для non-screen top-level строк (исправлено)

## [0.5.5]

### Changed

Реструктуризация senpy/ в 7 подпакетов (Phase 2):

- core/ (11 файлов): analyzer, cache, cache_manifest, config, constants, coverage, models, scope, signature, sink, symbols
- rules/ (4 файла): python_ast, flow, deprecated, rules_info
- rules/checkers/ (5 файлов): formatting, screen, asset, dialogue, state (split из checkers.py)
- rules/base.py: BaseChecker + IfBlockContext
- lsp/ (1 файл): server
- cli/ (3 файла): main, commands, unrpyc + __main__.py для python -m senpy.cli
- formats/ (7 файлов): sarif, html_report, wiki, stubs, ci, traceback, stats
- domain/ (5 файлов): renpy_api, text_tags, assets, rpa, tsundere
- text_utils.py остаётся в корне (используется всеми)
- Backward compat: senpy/__init__.py re-exports ключевые имена. Старые импорты from senpy import SenpyAnalyzer продолжают работать.
- CacheManager.ALLOWED_MODULES обновлён с новыми путями senpy.core.* (для pickle backward compat).

### Performance

~17% ускорение холодного прогона на больших проектах до рефакторинга (77k строк: 4.2s → 3.5s). Меньше циклических импортов.

### Tests

434 теста проходят (vs 425 в 0.5.3): +9 тестов после реструктуризации.
test_imports.py обновлён с новыми путями модулей.
test_packaging.py обновлён с новыми путями файлов.


## [0.5.4] ⚠️ YANKED

> **Важно:** Этот релиз был опубликован на PyPI и сразу же отозван (*yanked*). Версия содержит критическую ошибку сборки. **Не используйте её в проектах.**

### Причина отзыва
Шаг `publish-pypi` в CI/CD выполнился успешно, но последующий шаг `build-vsix` завершился ошибкой. 

В рамках реструктуризации в версии 0.5.4 файл `senpy/cli.py` был перенесен в `senpy/cli/main.py`. Однако конфигурационный файл `senpy.spec` для PyInstaller не был обновлен и продолжал ссылаться на старый путь, из-за чего сборка артефакта упала.

Поскольку PyPI иммутабелен (неизменяем), опубликованный релиз 0.5.4 нельзя перезаписать или удалить — его можно было только пометить как **yanked**.


## [0.5.3]

### Added
- **`senpy/config.py`** (new file) — вынесена `load_config()` из `_unrpyc_bootstrap.py`. Чистая функция чтения `senpy.toml`/`pyproject.toml`, без зависимостей от analyzer/cli. Разрывает цикл `analyzer ↔ cli` (Фаза 1.2).
- **`senpy/sink.py`** (new file) — `DiagnosticSink` Protocol. Определяет минимальный контракт для объектов, принимающих diagnostics: `_add_diagnostic()`, `_get_utf16_range()`, `fixable_count`, `fixed_count`, `fix`. Позволяет чекерам/AST/flow зависеть от Protocol, а не от `SenpyAnalyzer` (Фазы 1.3-1.5).
- **`senpy/text_utils.py`** (new file) — вынесена `_strip_comment()` из `analyzer.py`. Чистая функция удаления `#`-комментариев с учётом кавычек/hex-цветов, без зависимостей. Разрывает lazy-импорт циклы `checkers → analyzer` и `flow → analyzer` (Фаза 1.3).
- **`senpy/cache_manifest.py`** (new file) — вынесены `CachedFileEntry` и `CacheManifest` dataclasses из `cache.py`. Не имеют зависимостей от analyzer. Разрывает импортный цикл `analyzer ↔ cache` (Фаза 1.6).
- **`scripts/check_cycles.py`** (new file) — статический детектор циклических импортов через AST. Парсит все `.py` в `senpy/`, строит граф, ищет циклы через DFS. Игнорирует `if TYPE_CHECKING:` блоки (type hints, не runtime). Фаза 1.7 — safety net для архитектуры.
- **`check_cycles.bat`** (new file, корень проекта) — Windows-обёртка для `check_cycles.py`. Двойной клик в Explorer → проверка → пауза → закрытие.
- **`tests/test_imports.py`** (81 тест) — characterization tests для всех public импортов Senpy. Safety net: после реструктуризации 0.5.4 (перемещение файлов по папкам) все эти импорты должны продолжать работать через re-exports.

### Changed
- **`senpy/_unrpyc_bootstrap.py`**: `def load_config` заменён на `from senpy.config import load_config` (реэкспорт для backward compat). Старый импорт `from senpy._unrpyc_bootstrap import load_config` продолжает работать.
- **`senpy/cli.py`**: `load_config` теперь импортируется из `senpy.config`, не из `_unrpyc_bootstrap`.
- **`senpy/analyzer.py`**:
  - `from senpy.cli import load_config` → `from senpy.config import load_config` (разрыв цикла analyzer ↔ cli)
  - `def _strip_comment` заменён на `from senpy.text_utils import _strip_comment` (реэкспорт для backward compat)
- **`senpy/checkers.py`**:
  - `TYPE_CHECKING` импорт `SenpyAnalyzer` заменён на `from senpy.sink import DiagnosticSink`
  - Все 3 `__init__` метода (`BaseChecker`, `DialogueChecker`, `StateChecker`) теперь принимают `DiagnosticSink` вместо `SenpyAnalyzer`
  - Lazy импорт `_strip_comment` теперь из `senpy.text_utils`
- **`senpy/python_ast.py`**:
  - `TYPE_CHECKING` импорт `SenpyAnalyzer` заменён на `from senpy.sink import DiagnosticSink`
  - `PythonAstChecker.__init__` теперь принимает `DiagnosticSink`
  - Убран `TYPE_CHECKING` из typing импорта (больше не нужен)
- **`senpy/flow.py`**:
  - `TYPE_CHECKING` импорт `SenpyAnalyzer` заменён на `from senpy.sink import DiagnosticSink`
  - `StoryFlowAnalyzer.__init__` теперь принимает `DiagnosticSink`
  - Lazy импорт `_strip_comment` теперь из `senpy.text_utils`
- **`senpy/cache.py`**:
  - `CachedFileEntry` и `CacheManifest` импортируются из нового `senpy.cache_manifest` (реэкспорт для backward compat)
  - `SafeCacheUnpickler.ALLOWED_MODULES` обновлён: добавлен `"senpy.cache_manifest"` (для новых кэшей) рядом с `"senpy.cache"` (для старых, сериализованных до рефакторинга)
- **`.github/workflows/ci.yml`**: добавлен новый job `check-cycles` — запускается первым (~5 секунд), до matrix-тестов. Если найден цикл — CI падает быстро, не тратя минуты на тесты. `test` и `build-check` теперь зависят от `check-cycles` (`needs: [check-cycles]`).

### Removed
- **`senpy/python_ast.py`**: удалён dead code `AstChecker = PythonAstChecker` alias (P1'-11 из аудита v0.5.1) — нигде не импортировался, только путал.

### Architecture
- **Разорваны все 5 циклических зависимостей** из аудита v0.5.1 (через `analyzer.py`):
  - ✅ `analyzer ↔ cli` (Фаза 1.2 — `load_config` → `senpy/config.py`)
  - ✅ `analyzer ↔ checkers` (Фаза 1.3 — `DiagnosticSink` Protocol + `_strip_comment` → `text_utils.py`)
  - ✅ `analyzer ↔ python_ast` (Фаза 1.4 — `DiagnosticSink` Protocol)
  - ✅ `analyzer ↔ flow` (Фаза 1.5 — `DiagnosticSink` Protocol)
  - ✅ `analyzer ↔ cache` (Фаза 1.6 — `cache_manifest.py` extraction)
- `analyzer.py` больше не входит ни в один цикл. Граф импортов теперь **ациклический**.
- **Note**: разрыв **импортных** циклов. Runtime coupling частично остаётся (чекеры дёргают `self.analyzer.screens`, `compute_global_hash` обращается к `analyzer.labels` и т.д.) — полная развязка запланирована на 0.5.5 (`SymbolProvider` Protocol, вместе с разбиением `_collect_symbols`).

### Tests
- **`tests/test_imports.py`** (81 тест) — characterization tests для всех public импортов:
  - `TestCoreImports` (5) — SenpyAnalyzer, Diagnostic, RULE_SEVERITY, CacheManager, SENPY_VERSION
  - `TestEntrypoints` (3) — cli.main, 10 handlers, 20 LSP handlers
  - `TestCheckers` (4) — BaseChecker, 5 чекеров, PythonAstChecker, StoryFlowAnalyzer
  - `TestDomain` (7) — RENPY_API_DOCS, text_tags, AssetManager, tsundere, DEPRECATED_APIS, BUILTIN_*
  - `TestSymbolsAndScope` (3) — 5 Symbol классов, Scope/ScopeStack, SignatureInfo
  - `TestIOFormats` (9) — sarif, html_report, wiki, stubs, ci, traceback, stats, coverage, RULES_DATABASE
  - `TestFormatter` (3) — Formatter, FormatConfig, 4 правила, idempotency
  - `TestVendoredUnrpyc` (2) — decompile_rpyc, exceptions
  - `TestSenpyPackageInit` (2) — import senpy, __version__
  - `TestModuleIntegrity` (35) — все 35 модулей импортируемы
  - `TestNoCircularImports` (5) — analyzer ↔ {cli, checkers, python_ast, flow, cache} в любом порядке
- **Всего теперь 425 тестов** (vs 344 в v0.5.2): +81 новых characterization test.
- **Все 425 тестов проходят** локально и в CI (Python 3.11/3.12/3.13 × Ubuntu/Windows).

### Lessons learned (из worklog)
- **При реэкспорте `from X import Y` ставьте импорт на место бывшей функции** (в середине файла), не вверху со всеми импортами — иначе Python может попасть в циклическую инициализацию модулей.
- **`if TYPE_CHECKING:` блоки не создают runtime циклов** — это только type hints. `check_cycles.py` корректно их игнорирует.
- **Локальный pytest ≠ CI pytest** — на чистом CI могут всплыть import-баги, замаскированные локально rootdir detection. Всегда прогонять `pytest tests/` перед коммитом.

## [0.5.2]

### Added
- **`tests/test_packaging.py`** (459 строк, 46 регрессионных тестов) — safety net для всех P0'-багов из аудита 0.5.1:
  - `TestLicenseFile` — проверка что LICENSE существует и совпадает с `pyproject.toml:14`
  - `TestGitignore` — проверка что .gitignore НЕ игнорирует исходники (20 параметризованных тестов) + не содержит личных файлов (7 тестов) + исключает артефакты
  - `TestChangelog` — проверка что CHANGELOG содержит секцию для текущей версии
  - `TestLanguageConfiguration` — проверка `senpy-vscode/language-configuration.json`
  - `TestUnrpycPin` — проверка `UNRPYC_PINNED_SHA256` is not None
  - `TestRuleCountConsistency` — проверка что нет хардкоженных "All N Rules" в `senpy.toml` и `rules_info.py`
  - `TestSanity` — проверка `__version__.py`, `pyproject.toml` metadata
- **`senpy-vscode/language-configuration.json`** — VS Code language configuration для .rpy:
  - `#` как line comment
  - brackets: `{}`, `[]`, `()`
  - autoClosingPairs + surroundingPairs
  - `autoCloseBefore` для `,)]}'"; \n\t`
  - `indentationRules` для Ren'Py keywords (label/screen/menu/init python/transform/layeredimage/def/class/if/elif/else/for/while/with/on/when)
  - `folding.markers` для `# region` / `# endregion`
  - `onEnterRules` для auto-продолжения `#` комментариев
- **`tests/test_vscode_extension.py`** — 20 тестов для VS Code extension integration (UX-EXT-1..7)
- **`tests/test_p0_cli.py`** (расширен) — 9 regression тестов для P0-1, P0-2, P0-3

### Changed
- **`CHANGELOG.md`** — добавлены секции `[0.5.0]` и `[0.5.1]` (ранее отсутствовали, ECO-8)
- **`tests/conftest.py`** — больше НЕ подменяет `item._nodeid` через private pytest API (P0'-9). Использует `item.user_title` для отчётов, nodeid остаётся оригинальным. Это чинит `-k` фильтрацию и IDE интеграции.
- **`senpy.toml:60`** — убрано хардкоженное "All 41 Rules" из комментария (P0'-6). Заменено на "All Senpy Rules".
- **`senpy/_unrpyc_bootstrap.py:48`** — `UNRPYC_PINNED_SHA256` заполнен реальным значением для unrpyc v2.0.4 (P0'-5): `df7446d89f68a9a94a62378248da875e9e75e983bf81de53d92b2c19f359673e`
- **`tests/test_rename.py`, `tests/test_ux_ext_5_6_7.py`, `tests/test_vscode_extension.py`, `tests/test_workspace_symbol.py`** — заменён `from tests.test_lsp import ...` на `from test_lsp import ...` (стандартный pytest pattern). Без этого CI на Ubuntu падал с `ModuleNotFoundError: No module named 'tests'`.

### Fixed
- **P0'-1**: `LICENSE` файл отсутствовал — `pyproject.toml:14` ссылался на него. Создан `LICENSE` (MIT, Copyright 2024-2026 Xilleet). `LICENSE.md` переименован в `LICENSE` (без расширения, по конвенции OSS).
- **P0'-2**: `.gitignore` отсутствовал или содержал опасные записи (`senpy/analyzer.py`, `bump_version.py`, `senpy.spec`, и т.д. — 9 строк игнорировали исходники) + личные пути мейнтейнера (`Новая папка/`, `пост для реддита.txt`, и т.д. — 11 строк). Создан чистый `.gitignore` (99 строк), полностью заменяющий старый.
- **P0'-3**: `CHANGELOG.md` не содержал секций для 0.5.0 и 0.5.1. Добавлены обе секции с детальным описанием изменений.
- **P0'-4**: `senpy-vscode/language-configuration.json` отсутствовал — `package.json:contributes.languages` ссылался на него. Создан полный language configuration (8 ключей).
- **P0'-5**: `UNRPYC_PINNED_SHA256 = None` — placeholder, verification фактически no-op. Заполнен реальным SHA256 для unrpyc v2.0.4 (`df7446d8...`).
- **P0'-6**: Rule count discrepancy — `senpy.toml` говорил "All 41 Rules", `rules_info.py` — "All 40 Rules", фактически 45 в `models.RULE_SEVERITY`. Убраны хардкоженные числа.
- **P0'-9**: `tests/conftest.py:23` переписывал `item._nodeid` через private pytest API — ломал `-k` фильтрацию и IDE интеграции. Исправлено: используется `item.user_title`.
- **CI regression**: 4 test-файла (`test_rename`, `test_ux_ext_5_6_7`, `test_vscode_extension`, `test_workspace_symbol`) использовали `from tests.test_lsp import ...`, что падает в CI на Ubuntu с `ModuleNotFoundError: No module named 'tests'`. Fixed: стандартный pytest pattern `from test_lsp import ...`.

### Removed
- **4 дублирующих `.bat` файла**:
  - `check.bat` — дублировал `ruff check` (теперь в CI)
  - `reinstall.bat` (корневой) — байт-в-байт дубликат `senpy-vscode/reinstall.bat`
  - `run_check.bat` — дублировал CI pipeline (Ruff + pytest + pip install)
  - `senpy/update_reqs.bat` — генерировал `requirements.txt` через pipreqs, конкурирующий с `pyproject.toml [project.dependencies]`

### Security
- `UNRPYC_PINNED_SHA256` теперь реально проверяется (раньше был None placeholder). Defence-in-depth от MITM/compromised GitHub теперь работает.

## [0.5.1]

### Added
- **5 new LSP handlers** in `senpy/server.py`:
  - `textDocument/foldingRange` (UX-1) — сворачивание label/screen/menu/init python/transform блоков. 8 тестов в `tests/test_folding_range.py`.
  - `textDocument/rename` + `textDocument/prepareRename` (UX-2) — переименование меток с обновлением всех `jump`/`call` ссылок через `jump_sources` обратный индекс. `prepare_provider=True` для VS Code preview перед F2. 5 тестов в `tests/test_rename.py`.
  - `workspace/symbol` (UX-3) — глобальный поиск меток/экранов/трансформов через Ctrl+T. 7 тестов в `tests/test_workspace_symbol.py`.
  - `textDocument/documentHighlight` (UX-5) — подсветка всех упоминаний переменной/метки/экрана/трансформа в текущем файле.
  - `initialized` (UX-12) — kickoff diagnostics сразу после LSP init, без 300ms задержки.
- **3 new rules** (RPY7xx — Dead Code Detection, RULE-3/4/5 выполнены раньше плана 0.7.0):
  - `RPY701` (HINT) — неиспользуемая `define`-константа (мёртвый код). `analyzer.py:381-397`.
  - `RPY702` (HINT) — неиспользуемый `transform` (мёртвый код). `analyzer.py:399-413`.
  - `RPY703` (HINT) — неиспользуемый `screen` (мёртвый код). `analyzer.py:415-440`.
  - Все три правила автоматически **отключаются** при `analyzer.has_dynamic_jumps = True` (когда в коде есть `renpy.jump()`, `renpy.call()` или `dynamic_jump`) — динамические jump'ы делают статический unreachable-анализ ненадёжным.
  - 10 тестов в `tests/test_rules_rpy7xx.py`, включая edge-case с `call screen` (считается использованием).
- **Formatter MVP** (`senpy/formatter/`, EXT-8, 421 строка) — opinionated .rpy code formatter в стиле Black:
  - 4 правила: `FMT-INDENT` (tab → 4 spaces), `FMT-TRAILING-WS`, `FMT-EOF-NEWLINE`, `FMT-BLANK-LINES` (collapse 3+ подряд пустых до 2).
  - `@register_rule("FMT-XXX")` декоратор для декларативной регистрации правил (ESLint-style).
  - Skip-механика: `# senpy: format off` / `# senpy: format on` блоки + `# senpy: format skip` для одной строки.
  - Subcommand `senpy format [PATHS...]` с флагами `--check`, `--diff`, `--stdin-filename`.
  - Idempotency: `format(format(x)) == format(x)` — обязательно свойство, тестируется в `tests/test_formatter_idempotency.py` (12 тестов, все pass).
  - Реализован в соответствии с архитектурой Part 3 предыдущего аудита.
- **Vendored unrpyc** в `senpy/vendor/unrpyc/` (ECO-5, выполнено раньше плана 0.6.0):
  - Полный исходник unrpyc (MIT, Yuri K. Schlesner, CensoredUsername, Jackmcbarn) встроен в пакет.
  - Декомпиляция .rpyc теперь in-process через `from senpy.vendor.unrpyc import decompile_rpyc` — без subprocess overhead.
  - Decoupling от доступности GitHub / CensoredUsername-аккаунта.
  - `senpy/vendor/unrpyc/__init__.py` (51 строка) — public API: `decompile_rpyc(rpyc_path) -> str`.
  - 4 теста в `tests/test_vendored_unrpyc.py`.
- **`_unrpyc_bootstrap.py`** (356 строк) — выделено из `cli.py`: download/search/verify/extract unrpyc, .rpa extraction. Включает `_verify_unrpyc_sha256()` и `_safe_zip_extract()` (Zip Slip protection).
- **`_cli_commands.py`** (340 строк) — выделено из `cli.py`: 10 handler'ов (`handle_traceback`, `handle_init_ci`, `handle_coverage`, `handle_clear_cache`, `handle_stats`, `handle_export_wiki`, `handle_export_html`, `handle_graph`, `handle_defaults`, `handle_stubs`).
- **`examples/test_formatter_demo.py`** — demo-скрипт для ручного тестирования formatter'а.
- **`scripts/update_unrpyc_pin.py`** — maintainer script для обновления pinned unrpyc commit + SHA256 (ECO-4).
- **`tests/test_vscode_extension.py`** (382 строки, 20 тестов) — UX-EXT-1..7: проверки `language-configuration.json`, `package.json` reference, prepare_rename handler, `synchronize` для `.senpy.toml`.
- **`tests/test_lsp_race.py`** (116 строк) — race condition тесты для LSP (concurrent did_change + did_save).
- **`tests/test_p0_cli.py`** (281 строка, 9 тестов) — регрессии для P0-1, P0-2, P0-3.

### Changed
- **`server.py`** вырос с 734 до 1 396 строк (+662, +90 %) — 5 новых LSP handler'ов + инфраструктура.
- **`analyzer.py`** вырос с 1 520 до 1 719 строк (+199) — RPY701-703 + `_check_unused_declarations()`.
- **`python_ast.py`** вырос с 1 076 до 1 277 строк (+201).
- **`flow.py:check_story_islands`** — O(N²) → O(N+E) через pre-computed `incoming_jumps` dict (PERF-1, выполнено в 0.4.8, подтверждено в 0.5.1).
- **`_analyze_tl_file()`** разбит на 3 метода (P1-6 done): `_analyze_tl_file` (19 строк, было 154) + `_parse_tl_pairs` (статический) + `_validate_tl_pairs`.
- **`_normalize_path()`** helper (P0-6 fix) — единая нормализация путей в 4 местах `server.py`.
- **`_symbol_snapshot`** в `server.py` — fast-read snapshot для `rename`, `workspace_symbol`, `document_highlight`, `prepare_rename`. Snapshot берётся в `run_full_project_diagnostics` и не блокируется `analyze_file_only`, что позволяет F2/Ctrl+T работать во время typing.
- **`UNRPYC_PINNED_COMMIT = "v2.0.4"`** — pinned к конкретному тегу (был master-ветка). SHA256 verification structure ready, но `UNRPYC_PINNED_SHA256 = None` placeholder — нужно заполнить через `python scripts/update_unrpyc_pin.py`.

### Fixed
- **P0-5**: `hover` в LSP падал на `IndexError` при out-of-range line (`server.py:596`). Добавлен guard, matching `definition()` и `references()`.
- **P0-6**: `code_action` filename-fallback мог выбрать QuickFix из неправильного файла в multi-module проектах (`server.py:239-242`). Добавлен `_normalize_path()` helper, унифицированы 4 места нормализации, удалён небезопасный basename-fallback.

### Known Issues (to be fixed in 0.5.2)
- `LICENSE` файл отсутствует в корне — `pyproject.toml:14` ссылается на него, PyPI-публикация сломана.
- `.gitignore` файл отсутствует — артефакты (`senpy.sarif`, `test_report.*`, `__pycache__/`) коммитятся в репо.
- `CHANGELOG.md` — секции [0.5.0] и [0.5.1] добавлены этим релизом (раньше отсутствовали).
- `senpy-vscode/language-configuration.json` отсутствует — `package.json` ссылается на него, тесты падают (TDD RED phase).
- `UNRPYC_PINNED_SHA256 = None` placeholder — verification фактически no-op. Нужно запустить `python scripts/update_unrpyc_pin.py`.
- Rule count discrepancy: `senpy.toml` говорит "All 41 Rules", `rules_info.py` — "All 40 Rules", фактически 45 в `models.RULE_SEVERITY`.
- `tests/conftest.py:23` переписывает `item._nodeid` через private pytest API — ломает `-k` фильтрацию.
- God-функции выросли: `_walk_python_nodes` 404→538, `analyze_menu_flow` 145→285, `_collect_symbols` 340→379, `AssetChecker.check_line` 317→354, `cli.py:main()` 680→721, `sys.exit()` в cli.py 14→25, server.py globals 8→10.

### Tests
- 12 новых тест-файлов, 88 новых тест-функций (+76 %). Всего теперь 33 файла, 204 тест-функции.
- pytest pass rate: 99.6 % (284/285). 1 failed (`test_vscode_extension.py::test_file_exists` — TDD RED для language-configuration.json), 7 skipped (RED phase related tests).

## [0.5.0]

### Added
- **Formatter MVP architecture** — подпакет `senpy/formatter/` с `Formatter` class, `FormatConfig`, `FormatContext`, `register_rule` decorator (см. [0.5.1] для деталей реализации).
- **Subcommand `senpy format`** с флагами `--check`, `--diff`, `--stdin-filename`.
- **`examples/test_formatter_demo.py`** — demo-скрипт.
- Базовая структура `senpy/formatter/{__init__,core,rules/{__init__,indent,whitespace}}.py`.

### Changed
- Начало частичного рефакторинга P1-1: `cli.py` теперь пересылает `sys.argv[1] == "format"` в `_dispatch_format()` до основного argparse.
- `_cli_commands.py` (340 строк) выделен из `cli.py` — 10 handler'ов для traceback/init_ci/coverage/clear_cache/stats/export_wiki/export_html/graph/defaults/stubs.
- `_unrpyc_bootstrap.py` (356 строк) выделен из `cli.py` — unrpyc download/search/verify/extract + .rpa extraction.

## [0.4.8]

### Added
- **CI/CD infrastructure** (ECO-1):
  - `.github/workflows/ci.yml`: matrix tests on Python 3.11/3.12/3.13 × Ubuntu/Windows
  - `.github/workflows/release.yml`: auto PyPI publish via Trusted Publishing (OIDC) on `v*.*.*` tags
  - Ruff lint + format check in CI
  - Coverage report upload to Codecov
  - Wheel + VSIX build verification
- **CLI flags** (UX-15):
  - `--version` — prints Senpy version and exits
  - `--check` — dry-run for `--fix`, exit 1 if fixable issues found (CI-friendly)
  - `--diff` — shows unified diff of what `--fix` would change, without writing
  - `--exit-zero` — always exit 0, even with errors (for non-blocking CI runs)
- **`senpy/__version__.py`** as single source of truth for version (ECO-9)
- **`LICENSE`** file (MIT) — was referenced in README but missing (ECO-6)
- **`.gitignore`** — was missing, artifacts like `senpy.sarif`, `test_report.*`, `__pycache__/`, `.pytest_cache/` were getting committed (ECO-2)
- **`scripts/update_unrpyc_pin.py`** — maintainer script to update pinned unrpyc commit + SHA256 (ECO-4)
- **`[tool.ruff]`** config in `pyproject.toml` for self-linting (ECO-10)
- **`[tool.mypy]`** config in `pyproject.toml` for gradual type checking (ECO-10)
- **`[tool.coverage]`** config in `pyproject.toml` for coverage reporting (ECO-10)
- **18 classifiers** + **8 keywords** + **6 project URLs** in `pyproject.toml` (ECO-10)

### Changed
- **`bump_version.py`** rewritten to read/write `senpy/__version__.py` instead of patching 4 files via regex (ECO-9). Also fixed `contentatch.end()` typo in original.
- **`pyproject.toml`** now uses `dynamic = ["version"]` reading from `senpy.__version__.__version__` (ECO-9)
- **`senpy/cli.py` `download_unrpyc()`** now downloads pinned commit + verifies SHA256 + uses safe zip extraction (ECO-4)
- **README badge** "Python 3.10+" → "Python 3.11+" to match `requires-python = ">=3.11"` (DOC-1)
- **`flow.py:check_story_islands`** — O(N²) → O(N+E) via pre-computed `incoming_jumps` dict (PERF-1)

### Fixed
- **P0-1**: `--output-file` was silently ignored for text format (cli.py:847-852). Now writes to file via `_ReplaceConsole` context manager. Also creates parent directory if missing.
- **P0-2**: `--stats` discarded first analyzer and re-scanned project, losing RPA-decompiled files (cli.py:647-648). Now reuses existing analyzer.
- **P0-3**: `--traceback` couldn't find `errors.txt` — `const="traceback.txt"` was too narrow (cli.py:411-416). Now auto-discovers via `find_latest_traceback` + resolves relative paths.
- **P0-4**: `existing_rpy_files` used basenames, breaking multi-module projects where `game/script.rpy` and `mods/script.rpy` collided (cli.py:547-552). Now uses `os.path.relpath` for uniqueness + parallel `existing_rpy_basenames` for `.rpyc` dedup.
- **P0-5**: `hover` in LSP crashed with `IndexError` on out-of-range line (server.py:596). Added guard, matching `definition()` and `references()`.
- **P0-6**: `code_action` filename-fallback could pick QuickFix from wrong file in multi-module projects (server.py:239-242). Added `_normalize_path()` helper, unified 4 normalization sites, removed unsafe basename-fallback.
- **P0-7**: `senpy-vscode/src/extensions.txt` had wrong extension (should be `.ts`) and extra `s` in name. Build was broken. Renamed to `extension.ts`.
- **P0-8**: `tests/test_analyzer.py:151` hardcoded `all_29_rules` — passed trivially, missing 13 new rules. Now uses dynamic count from `models.RULE_SEVERITY` + `MEGA_UNCOVERED_RULES` with explanations.
- **P0-9**: `senpy-vscode/reinstall.bat` hardcoded `D:\translator\vers\Senpy\senpy-vscode` path. Replaced with `%~dp0`.
- **P0-10**: `check.bat` said "Проверка ScreenTale через Ruff" — copy-paste leftover from another project. Fixed to "Senpy".
- **P0-11**: `html_report.py:148` had `securityLevel: 'loose'` allowing XSS via Mermaid node names. Fixed with 4-layer defense:
  - `securityLevel: 'strict'` (disables HTML in nodes)
  - CSP meta-tag in `<head>` (blocks inline scripts except trusted CDNs)
  - `textContent` instead of `innerHTML` in catch block
  - Python-side `<`/`>` escaping in `js_safe_graph`

### Security
- **ECO-4**: unrpyc download now pinned to specific commit + SHA256 verification + Zip Slip protection
  - Previously: `UNRPYC_GITHUB_ZIP = ".../archive/refs/heads/master.zip"` (always latest, no verification)
  - Now: `UNRPYC_PINNED_COMMIT` + `UNRPYC_PINNED_SHA256` + `_verify_unrpyc_sha256()` + `_safe_zip_extract()`
  - Run `python scripts/update_unrpyc_pin.py` to update pin

### Tests
- Added `tests/test_p0_cli.py` with 9 regression tests for P0-1, P0-2, P0-3
- `test_mega_broken_script_catches_all_rules` now dynamically checks all 42 rules (was 29)

## [0.4.7]

### Added
- 13 new rules: RPY100, RPY107-109, RPY207-208, RPY309-310, RPY404, RPY505, RPY601-603
- VS Code extension with bundled Python runtime (Windows VSIX)
- `senpy --init-ci` for one-click GitHub Actions workflow generation
- `senpy --stubs` for Python type stubs generation
- `senpy --export-html` for standalone HTML report with Mermaid story graph
- `senpy --tsundere` mode for anime-style diagnostic messages
- `# noqa` and `# senpy: ignore[RPYxxx]` inline suppression
- SARIF output format for GitHub Code Scanning
- Two-tier disk cache (`.senpy_cache/`) for incremental analysis
- `SafeCacheUnpickler` and `SafeRPAUnpickler` for RCE protection
- Path Traversal protection for `.rpa` archive extraction
- `senpy.toml` configuration file support
- `[tool.senpy.severity]` for per-rule severity overrides

### Changed
- Major refactor: 13 old dictionaries → 5 object registries (`variables`, `labels`, `screens`, `images`, `transforms`)
- `_differential_purge_file` for incremental cache invalidation
- Cross-file symbol resolution in LSP `definition()` handler

[0.5.1]: https://github.com/Xilleet/senpy/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/Xilleet/senpy/compare/v0.4.8...v0.5.0
[0.4.8]: https://github.com/Xilleet/senpy/compare/v0.4.7...v0.4.8
[0.4.7]: https://github.com/Xilleet/senpy/releases/tag/v0.4.7
