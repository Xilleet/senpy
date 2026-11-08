# Changelog

<a id="up"></a>

All notable changes to Senpy are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

### Navigation

- **Current (0.8.x)**: [Unreleased](#unreleased) | [0.8.3](#083) | [0.8.2](#082) | [0.8.1](#081) | [0.8.0](#080)

- **0.7.x**: [0.7.7](#077) | [0.7.6](#076) | [0.7.5](#075) | [0.7.4](#074) | [0.7.3](#073) | [0.7.2](#072) | [0.7.1](#071) | [0.7.0](#070)

- **0.6.x**: [0.6.6](#066) | [0.6.5](#065) | [0.6.4](#064) | [0.6.3](#063) | [0.6.2](#062) | [0.6.1](#061) | [0.6.0](#060)

- **0.5.x**: [0.5.8](#058) | [0.5.7](#057) | [0.5.6](#056) | [0.5.5](#055) | [0.5.4 ⚠️](#054) | [0.5.3](#053) | [0.5.2](#052) | [0.5.1](#051) | [0.5.0](#050)

- **0.4.x**: [0.4.8](#048) | [0.4.7](#047)

---

<a id="unreleased"></a>

## [Unreleased]

### Fixed

- **`--show-settings` now honors `--config FILE`.** `--show-settings` in
  `senpy/cli/early_exits.py` called `load_config(project_path)` without
  passing `config_path` — it bypassed the `--config` wiring from P1-5
  and showed the default config even when the user passed a custom file.
  Now calls `load_config(project_path, config_path=args.config)`.

- **`--cache-dir` now covers decompiled/rpa_extracted sandbox.**
  `discover_files` in `senpy/cli/discover.py` hardcoded
  `<project>/.senpy_cache/decompiled` and `<project>/.senpy_cache/rpa_extracted`
  — the `--cache-dir` flag (wired into `CacheManager` in P1-5) did not
  redirect these sandbox directories. CI with `--cache-dir /shared/cache`
  still polluted `<project>/.senpy_cache/` with sandbox artifacts. Now
  uses `args.cache_dir` (if passed) as the base for both sandboxes;
  falls back to `<project>/.senpy_cache/` when `--cache-dir` is not
  passed (default behavior unchanged).

- **RPY701 `is_character` heuristic no longer uses loose substring match.**
  `file_collector.py:353` used `"Character" in clean or
  "DynamicCharacter" in clean` — a substring check that matched
  `NotCharacterRelated()` (function name containing "Character" as a
  substring) and string literals like `"Some Character string"`. The
  result: RPY701 (unused define) skipped these false-positive
  "characters", producing false negatives (genuinely unused constants
  were not reported). Replaced with `_RE_CHARACTER_CALL` regex
  (`\b(?:Character|DynamicCharacter)\s*\(`) which requires a word
  boundary + optional whitespace + `(` — the actual Ren'Py
  character-definition call pattern. New test module
  `tests/test_is_character_heuristic.py` (4 tests): real Character
  call → is_character=True, DynamicCharacter → True, NotCharacterRelated
  → False (substring false positive eliminated), string literal with
  "Character" → False.

- **`_PLUGINS_LOADED` now protected by `threading.Lock`.** `autoload.py`
  had a module-level boolean `_PLUGINS_LOADED` without a lock. Two
  concurrent `autoload_plugins()` calls could both see `False` and both
  load plugins (race condition). LSP doesn't call autoload from worker
  threads now, but the lock is cheap insurance against future changes.
  Added `_PLUGINS_LOADED_LOCK` and wrapped the check-and-set in `with`.

- **GitHub Actions `%` now escaped to `%25` in `render_github`.**
  `render_github` escaped `\n` → space and `::` → space, but did NOT
  escape `%` → `%25` per the workflow command spec. Messages like
  `RPY104: 50% complete` were truncated/mangled at the `%`. Added `%`
  escape in both stdout and `--output-file` paths.

- **RPY707 declaration line now deterministic for multi-file channels.**
  `_emit_unused_channel_diagnostic` in `dead_code.py` iterated
  `register_lines.items()` — dict insertion order, which is not
  contracted as deterministic for multi-file channel registration.
  If one channel was registered in multiple files, the chosen declaration
  line depended on file processing order. Added deterministic tie-breaker:
  sort candidates by `(file_path, line_idx)` and take the first match
  (lowest lexicographically).

---

<a id="083"></a>

## [0.8.3] — Hotfix: broken contracts, dead CLI flags, LSP snapshot consistency

A patch release closing **15 bugs** across P0 (broken contracts), P1
(real user-impact bugs), and P2 (edge cases). All P0 and P1 tasks from
the post-0.8.2 audit are now closed. **1816 tests** (up from 1777 in
0.8.2, +39). No new rules — all changes are correctness fixes and CLI
contract enforcement. The release focuses on three themes: (1) CLI
flags that were documented but silently did nothing, (2) LSP handlers
that read stale or inconsistent state, (3) analyzer crashes from
unchecked plugin output.

### Fixed

- **Pre-commit hook now fails on ERROR diagnostics.** The published
  `.pre-commit-hooks.yaml` used `entry: senpy --check`, which only
  exits 1 when `fixable_count > 0`. Projects with unfixable
  ERROR-severity diagnostics (e.g. RPY104 undefined variables, RPY303
  dead labels) silently passed the pre-commit gate, defeating its
  purpose. Changed `entry` to `senpy --errors-only`, which filters
  output to ERROR severity and computes the exit code from
  `error_count` (1 if any ERROR, unless `--exit-zero`). WARNINGs and
  INFO notices are hidden from the pre-commit log; users who want the
  full picture run `senpy` manually without `--errors-only`.
  Documentation in `README.md`, `README_ru.md`, and
  `docs/renpy-github-actions.md` updated to match. The `--check` CLI
  flag itself is unchanged (still a dry-run for `--fix`); only the
  pre-commit hook entry was switched.

- **Production logging now initialized.** `setup_logging()` was
  implemented and documented but never called from production code.
  As a result, WARNING+ log records (broken plugins, invalid config
  TOML, analysis warnings) hit Python's `lastResort` handler — a
  `_StderrHandler` at WARNING level — and wrote unformatted messages
  to stderr. In LSP mode stderr is the JSON-RPC transport, so any
  WARNING corrupted the protocol. Wired `setup_logging(verbose=False)`
  into `cli.runner.main()` (at the very top, before `autoload_plugins`
  which emits plugin-loading warnings) and into
  `lsp.server.start_lsp()` (defense-in-depth for direct invocation).
  The `verbose=False` default installs a `NullHandler` that swallows
  records silently; `--verbose` / `--log-file` CLI flags are not yet
  wired (planned follow-up). The `senpy.core.logging` module docstring
  updated to reflect the actual wiring.

- **`--strict` and `--fail-on-error` CLI flags now declared.** Both flags
  were documented (`docs/cli-reference.md`, `docs/configuration.md`,
  `docs/renpy-github-actions.md`) but absent from `args.py` — running
  `senpy /path --strict` exited with `argparse: error: unrecognized
  arguments: --strict` (exit 2). `--strict` promotes every diagnostic
  to ERROR severity (except those explicitly downgraded via
  `[tool.senpy.severity]` in `senpy.toml`); the CLI flag overrides the
  config value. `--fail-on-error` makes the default behavior (exit 1 on
  any ERROR) explicit for self-documenting CI scripts — it is a no-op
  by itself, but pairs with `--strict` to make the CI contract obvious.
  `--fail-on-error` + `--exit-zero` is now rejected with exit code 2
  (the flags contradict each other). New constructor argument
  `SenpyAnalyzer(strict=bool|None)` — `None` (default) uses config,
  `True`/`False` overrides. `docs/cli-reference.md` extended with an
  "Explicit fail-on-error" section.

- **`.senpy-ignore` filename corrected in `SENPY_OWN_FILES`.** The
  frozenset in `senpy/domain/assets.py` listed `".senpyignore"` (no
  hyphen), but production code (`cli/filters.py:56`) writes and reads
  `.senpy-ignore` (with hyphen), matching the docs. As a result,
  `.senpy-ignore` leaked into `known_assets` and appeared in
  `senpy inspect` JSON output as a spurious "unused asset". The test
  `test_asset_manager_index.py::_make_project` created `.senpyignore`
  (no hyphen) — passing vacuously. Fixed: added `.senpy-ignore` to
  `SENPY_OWN_FILES`, kept `.senpyignore` for backward compat (rare
  manual creation), updated the test fixture to create the real
  `.senpy-ignore` file, added a regression test that asserts
  `.senpy-ignore` does not leak into `known_assets`.

- **Vacuous `or True` assertion removed from cache characterization test.**
  `tests/test_analyzer_characterization.py::test_cache_enabled_creates_cache_dir`
  had `assert (tmp_path / ".senpy_cache").exists() or True` with a misleading
  comment "cache may be in different location". CacheManager hardcodes
  `cache_dir = <project>/.senpy_cache` (cache.py:145) — there is no
  "different location". The `or True` made the assertion always pass,
  silently masking any regression that broke cache creation. Removed
  `or True`, replaced with a real assertion + an additional check that
  `cache.pkl` manifest exists (proves `save_manifest` ran, not just
  `ensure_cache_dir`). Updated the comment to explain the cache creation
  path: `analysis_pipeline.py:294` → `save_manifest` → `ensure_cache_dir`.

- **RPY308/RPY309 terminator detection unified via `RE_TERMINATOR`.** Two
  related bugs in label-terminator detection:
  - **P1-1:** `$ renpy.full_restart()` and `$ renpy.quit()` were not
    recognized as terminators. `dialogue.py` (RPY308) and
    `file_collector.py` (RPY309) used `startswith(("renpy.full_restart",
    "renpy.quit", ...))` which does not match the real line
    `    $ renpy.full_restart()` (leading whitespace + `$` prefix). RPY308
    false-fired on fall-through after `$ renpy.full_restart()`; RPY309
    false-skipped setting `fall_through_to`.
  - **P2-7:** `file_collector.py` included `"pass"` in the terminator
    tuple, but `dialogue.py` did not. In Ren'Py `pass` is a no-op —
    control flow DOES fall through. The inconsistency meant RPY309
    failed to set `fall_through_to` when the previous label ended with
    `pass`, masking fall-through hazards.
  Fix: extracted `RE_TERMINATOR` regex and `is_terminator_line()` helper
  into `senpy/core/constants.py` (based on the regex already used in
  `state.py:155-159`). The regex handles leading whitespace, optional `$`
  prefix, word boundaries, and the full set of terminating renpy.* calls
  (`quit`, `full_restart`, `utter_restart`, `jump`, `jump_out_of_context`).
  Deliberately does NOT match `pass` (no-op). Applied to RPY308
  (`dialogue.py`) and RPY309 (`file_collector.py`); StateChecker left
  unchanged (its regex serves RPY401 menu-branch termination, where
  `call` semantics differ — out of scope). New test module
  `tests/test_terminator_detection.py` (9 tests): `$ renpy.full_restart()`,
  `$ renpy.quit()`, `$ renpy.utter_restart()`, `$ renpy.jump()`, sanity
  that RPY308 still fires on real fall-through, `pass` as non-terminator
  (RPY308 fires + RPY309 no-island).

- **RPY502 false positive on GIF/BMP images fixed.**
  `AssetManager._index_valid_images` in `senpy/domain/assets.py` hardcoded
  the image extension tuple as `(".png", ".webp", ".jpg", ".jpeg")` —
  missing `.gif` and `.bmp`. Meanwhile, `IMAGE_EXTENSIONS` in
  `senpy/core/constants.py` includes all six. The split caused
  `image_name_to_path` (LSP hover) to register GIF/BMP images correctly,
  but `valid_images` (RPY502 validation) to miss them — so `show foo bar`
  triggered RPY502 "unknown image" when `images/foo bar.gif` existed.
  Replaced the hardcoded tuple with `IMAGE_EXTENSIONS`, keeping
  `valid_images` consistent with `image_name_to_path`. New test module
  `tests/test_rpy502_gif_bmp.py` (5 tests): GIF/BMP in `images/` does
  not trigger RPY502, GIF/BMP appear in `valid_images`, sanity that
  RPY502 still fires on genuinely missing images.

- **RPY109 fixture no longer vacuous.** The
  `tests/fixtures/rules/RPY109/bad_init_order.rpy` fixture had both
  `init python:` blocks in a single file, but RPY109 only fires on
  cross-file violations (`python_ast.py:739-740: if def_file == file_path:
  continue`). The snapshot was `[]` — `test_rule_fixture` passed
  vacuously, masking the absence of a cross-file fixture. Renamed the
  file to `good_init_order_same_file.rpy` (positive — same-file, RPY109
  must NOT fire, which is correct). Deleted the empty `bad_init_order.json`
  snapshot. Added cross-file fixture files
  (`tests/fixtures/rpy109_cross_file/a_caller.rpy` +
  `z_definer.rpy`) and a new test module
  `tests/test_rpy109_cross_file_fixture.py` (2 tests): RPY109 fires
  when `a_caller.rpy` references `z_definer.rpy`'s function (alphabetical
  order wrong), and does NOT fire when files are renamed to correct order.
  The fixture files live under `tests/fixtures/rpy109_cross_file/` (not
  `tests/fixtures/rules/RPY109/`) to avoid `test_rule_fixture`'s rglob
  picking them up as one-file positive fixtures — `test_rule_fixture`
  cannot test multi-file rules.

- **`--no-cache` parity test added.** `tests/test_cache_lifecycle.py`
  had `test_cold_warm_equivalence` (cold vs warm run, both with cache
  enabled) but no test comparing `no_cache=True` vs `no_cache=False` on
  the same fresh project. A bug in the cache-write path (e.g.
  `_finalize_results` skipping `save_manifest`, or `CachedFileEntry`
  storing stale diagnostics) would have passed all existing tests
  silently. Added two tests to `test_cache_lifecycle.py`:
  `test_no_cache_equals_cold_cache` — runs the same project with
  `no_cache=True` (cache disabled, nothing written to disk) and
  `no_cache=False` (cold run, cache written), asserts identical
  diagnostics + analyzer state (missing_defaults, referenced_labels,
  has_dynamic_jumps, user_symbols, total_lines, fixable_count,
  fixed_count). Also asserts the cache directory is created by
  `no_cache=False` and NOT created by `no_cache=True` (sanity check
  that the flag actually controls the cache). Plus
  `test_cache_parity_no_cache_vs_cache` (parametrized) — guards against
  either mode silently producing empty/degenerate diagnostics. Together
  with `test_cold_warm_equivalence` they form a full parity guard:
  cold→warm (cache-restore bugs) + no-cache→cache (cache-write bugs).

- **Dead CLI flags wired or removed.** Four flags were declared in
  `args.py` but never reached their consumers:
  - `--cache-dir DIR` — now wired through `SenpyAnalyzer(cache_dir=...)`
    to `CacheManager(cache_dir=...)`. The cache is written to the custom
    directory instead of the hardcoded `<project>/.senpy_cache`. Useful
    for CI with a shared cache between runs.
  - `--config FILE` — now wired through `SenpyAnalyzer(config_path=...)`
    to `load_config(project_path, config_path=...)`. The `SENPY_CONFIG`
    env var also works as an alternative. Previously `--config` was
    parsed but `load_config(args.path)` ignored it.
  - `--statistics` — removed. The summary table was always printed in
    `render_text` (the flag was a no-op). Removing it makes the CLI
    contract honest; users who passed `--statistics` got no error but
    also no extra behavior.
  - `--respect-gitignore` — removed. File discovery uses `IGNORED_DIRS`
    (hardcoded set in `constants.py`), not `.gitignore` parsing. The
    flag was a no-op.
  New constructor args on `SenpyAnalyzer`: `cache_dir: str | None`,
  `config_path: str | None`. `load_config` gained `config_path` param
  and `SENPY_CONFIG` env var support. Docs updated: `cli-reference.md`,
  `configuration.md`, `renpy-github-actions.md`, `renpy-error-checker.md`
  — removed sections for the deleted flags, added sections for
  `--cache-dir` and `--config`. New test module
  `tests/test_dead_cli_flags.py` (11 tests): `--cache-dir` parsed +
  creates cache at custom location, `--config` parsed + loads custom
  file + `SENPY_CONFIG` env var works, `--statistics` and
  `--respect-gitignore` rejected with exit 2, attrs absent after parse.

- **LSP `prepare_rename` now returns Range for variables/transforms/screens.**
  `prepare_rename` in `senpy/lsp/handlers/navigation.py` returned a Range
  only for labels — for variables, transforms, and screens it returned
  `None`. But `rename` already supported all four symbol types (labels
  via `_rename_label`, variables/transforms/screens via
  `_rename_symbol_via_text_search`). VS Code does not start an F2 rename
  session if `prepareRename` returns `None` — the user pressed F2 on a
  variable, nothing happened, and they concluded "renaming doesn't work
  for variables". The fix broadens the eligibility check: if the word
  under the cursor is in any of the four rename-supported snapshot sets
  (labels, variables, transforms, screens), return its Range. The Range
  calculation (UTF-16 positions for VS Code) is unchanged. Words that
  are not symbols (strings, comments, keywords) still return `None` —
  F2 does not start on arbitrary text. New test module
  `tests/test_prepare_rename_non_label.py` (5 tests): variable,
  `define` constant, `transform` declaration, non-symbol word → None,
  label still works (regression guard).

- **LSP `references` for labels now uses symbol snapshot, not live analyzer.**
  `references` in `senpy/lsp/handlers/navigation.py` (lines 740-752) read
  `server_mod._active_analyzer.labels` and `_active_analyzer.jump_sources`
  (live analyzer state). After `did_change → analyze_file_only`, the live
  analyzer's label registry is rebuilt for the edited file only — labels
  from other files disappear from the live registry until the next full
  analysis. `_symbol_snapshot` is refreshed on `did_open`, `did_save`, and
  `did_change_watched_files` and retains labels from all files. Other
  handlers (`rename`, `prepare_rename`, `incoming_calls`, `outgoing_calls`,
  `workspace_symbol`) already used the snapshot — `references` was the
  outlier. Replaced `_active_analyzer.labels` →
  `_symbol_snapshot["labels"]` and `_active_analyzer.jump_sources` →
  `_symbol_snapshot["jump_sources"]`. New test module
  `tests/test_references_snapshot.py` (3 tests): references finds label
  jump sites after simulated `analyze_file_only` (the bug scenario),
  declaration included/excluded per `context.include_declaration`.

- **LSP `document_symbols` no longer mutates analyzer under read lock.**
  `document_symbols` in `senpy/lsp/handlers/navigation.py` (lines 838-841)
  had a fallback: if `file_scopes[norm_path]` was missing, it called
  `analyzer._collect_symbols(file_path)` to populate it on the fly. But
  `document_symbols` is registered with `@_with_analysis_lock` (read
  lock), and `_collect_symbols` mutates `analyzer.file_scopes` and
  `analyzer._stage1_lines` — violating the `_RWLock` contract (readers
  must not write). The race scenario: `did_open` schedules
  `run_full_project_diagnostics` with a 300ms debounce; if
  `document_symbols` arrived in those 300ms, the handler mutated shared
  state under a read lock. Removed the fallback: if the scope is missing,
  return `[]`. The scheduled full analysis will populate the scope; VS
  Code re-requests the outline on `did_change`/`did_save`, so the user
  sees it within ~1s. New test module
  `tests/test_document_symbols_no_mutation.py` (3 tests): returns `[]`
  when scope missing (no `_collect_symbols` call), returns symbols when
  scope present (happy path), does not populate `file_scopes` (no
  side-effect mutation).

- **Plugin `check()` return-type now validated.** `analysis_pipeline.py`
  iterated over the list returned by a plugin's `check()` and called
  `_add_diagnostic_by_file(diag)` on each element without type
  validation. If a plugin returned `[None]`, `["string"]`, or any list
  with non-`Diagnostic` elements, `_add_diagnostic_by_file` crashed with
  `AttributeError: 'NoneType'/'str' object has no attribute 'file_path'`.
  The crash happened OUTSIDE the `try/except` around `check()` — that
  try/except only catches exceptions raised BY `check()`, not exceptions
  raised while iterating its return value. The result: one bad plugin
  killed the entire analysis run, violating the "plugin isolation"
  contract. Added `isinstance(diag, Diagnostic)` check inside the loop:
  non-`Diagnostic` elements are logged as WARNING and skipped; valid
  diagnostics from the same plugin and from other plugins are preserved.
  New test module `tests/test_plugin_check_return_validation.py`
  (5 tests): `[None]` does not crash, `["string"]` does not crash,
  `[None, "str", Diagnostic]` keeps the valid Diagnostic, good plugin
  still works (sanity), bad plugin does not kill other plugins
  (isolation).

---

<a id="082"></a>

## [0.8.2] — False-positive cleanup + CRLF/Windows fix

Patch release closing 9 false-positive classes discovered by running
Senpy 0.8.1 on a 5-project corpus of real open-source Ren'Py games
(~174k LOC): DDLC, LearnToCodeRPG, cross_channel localization,
DDLCModTemplate, renpy-template. **1777 tests** (up from 1646 in
0.8.1, +131). No new rules; all changes are correctness fixes that
eliminate false positives without weakening true-positive coverage.

Corpus verification: 8968 → 8485 diagnostics (-483 false positives,
-5.4%) across the 5 projects. The remaining diagnostics are confirmed
true positives.

### False-positive fixes (from corpus findings)

- **RPY309 fall-through reachability**: labels reached from `start`
  via fall-through (no `return` between adjacent labels) were reported
  as "story islands unreachable from start". Fixed by adding a
  `fall_through_to` edge to `LabelSymbol` and following it in the
  reachability BFS. The edge is computed at collection time by
  checking the last non-blank line before each new label declaration.
  Empirical scope: 515 false positives eliminated in cross_channel
  alone.
- **RPY503 GUI auto-discovery + `[prefix_]` substitution**: assets
  referenced via `gui.button_properties("X")` style calls and
  `[prefix_]` state-prefix patterns (e.g.
  `"gui/button/check_[prefix_]foreground.png"`) were reported as
  unused. Fixed by scanning every line (not just `$`/`python:` blocks)
  for media-asset string literals and expanding `[prefix_]` to the
  8 standard state prefixes. Empirical scope: 101 false positives
  eliminated.
- **RPY206 incomplete allowlist**: `FilePagePrevious()`,
  `FilePageNext()`, `InvertSelected()` and 44 other Ren'Py built-in
  screen action factories were flagged as "executes immediately during
  screen render". Fixed by extending `BUILTIN_ACTIONS` from 42 to 91
  entries, covering the complete screen action library documented at
  https://www.renpy.org/doc/html/screen_actions.html.
- **RPY102 intra-branch sequencing**: a variable assigned inside an
  `if` body and used in the SAME body (e.g. in a nested `for` loop)
  was flagged as "undeclared before declaration". Fixed by giving
  each `if`/`while`/`for`/`try` body its own copy of `local_scope`
  and adding assigned names to it as they are visited, so subsequent
  statements in the same branch see them.
- **RPY109 init priority ignored**: variables defined in
  `init python:` (priority 0) were reported as "init phase dependency
  violation" when referenced in `init 998 python:` blocks in
  alphabetically earlier files. Fixed by extracting the init priority
  from `RE_INIT_PYTHON_START` and skipping the alphabetical-order
  check when the referencing block has priority > 0 (it runs after
  default-priority blocks).
- **RPY110 multi-line triple-quoted strings**: a `$` statement opening
  a triple-quoted string on one line and closing it on another
  triggered "Python syntax error: invalid syntax". Fixed by extending
  `_get_logical_line` to join physical lines while a triple-quoted
  string is open, with cumulative state tracking via the new
  `_has_unclosed_string()` helper.
- **RPY103 screen params in `init <N>` blocks**: screen parameters
  declared via `init -501 screen game_menu(title, scroll=None):` were
  not registered in the local scope, causing RPY103 to fire on every
  use inside the screen body. Fixed by extending `RE_SCREEN_START` to
  optionally match the `init <N> ` prefix.
- **RPY502 dynamic `renpy.image()` registration**: images registered
  via `renpy.image(NAME, ...)` calls in `init python:` blocks were
  not visible to the static analyzer, causing RPY502 to fire on every
  `show`/`scene` reference. Fixed by a static evaluator that walks the
  init-python AST, finds `renpy.image(X, ...)` calls, and evaluates X
  when it is a string literal, a loop variable from a list-literal
  iterable, or a simple concatenation of these. Empirical scope: 88
  false positives eliminated in learntocode alone.
- **LSP snapshot staleness after `analyze_file_only`**: after
  `did_change` → `analyze_file_only`, the live `analyzer.labels` was
  updated for the edited file but `_symbol_snapshot` was NOT refreshed
  (only `run_full_project_diagnostics` refreshed it). Hover,
  completion, rename, and references read from the snapshot → newly
  added symbols were invisible until `did_save` triggered a full scan.
  Fixed by calling `_refresh_symbol_snapshot()` after
  `analyze_file_only` in `run_single_file_diagnostics`.

### Infrastructure fixes

- **CRLF line endings break `textwrap.dedent`**: on Windows, files
  opened with `newline=""` (which `file_collector.py` does to preserve
  original line endings) keep `\r\n`. When joined init-python block
  lines are fed to `textwrap.dedent`, the `\r`-only lines (empty lines
  on CRLF) make the common margin collapse to `''` — dedent removes
  nothing, `ast.parse` fails with "unexpected indent", and every
  init-python-dependent check (RPY109, RPY110, RPY502 dynamic
  `renpy.image()` extraction) silently skips the block. Fixed by the
  `dedent_python()` helper in `senpy/text_utils.py` which normalizes
  `\r\n` / `\r` → `\n` before `textwrap.dedent`. Applied in 3 call
  sites. Regression test `test_crlf_line_endings.py` covers both the
  helper (unit-level, platform-independent) and the full analyzer path.
- **RPA `_read_rpa_index` activated**: the function existed with
  correct exception handling (`TypeError`, `AttributeError`,
  `zlib.error`, `pickle.UnpicklingError`, `OSError`, `ValueError`) but
  was unreachable — the `.rpa` extension was in
  `NON_ASSET_EXTENSIONS` and the call site sat after the skip filter.
  Fixed by moving the `_read_rpa_index` call BEFORE the
  `NON_ASSET_EXTENSIONS` skip. The `.rpa` file itself stays in the
  skip list (it's a build artifact, not a directly-used asset) but its
  contents are now registered as known assets.
- **Badge yellow-on-skip policy removed**: the tests badge turned
  yellow whenever any test was skipped, even if all real tests passed.
  The Senpy suite has ~50 expected skips by design (POSIX-only tests
  on Windows, encoding-error fixtures, QuickFix-validity fixtures for
  rules without QuickFixes). Fixed by changing the badge color policy:
  `failed > 0` → red; `failed == 0` → brightgreen. Skips are never
  mentioned in the message and never affect color.

### Architectural additions

- `LabelSymbol.fall_through_to: str | None` — new field on the
  slotted dataclass, persisted in the cache hash
  (`compute_global_hash`) so that adding/removing a `return` between
  two labels in file A invalidates file B's cached RPY309 diagnostics.
- `senpy.text_utils.dedent_python(code)` — public helper that
  normalizes CRLF/LF before `textwrap.dedent`. Used everywhere
  `textwrap.dedent` was previously called on file content.
- `senpy.text_utils._has_unclosed_string(s)` — helper used by
  `_get_logical_line` to detect multi-line string constructs.
- `senpy.core.constants.BUILTIN_ACTIONS` — extended from 42 to 91
  entries, covering the complete Ren'Py screen action library.
- `senpy.core.constants.RE_SCREEN_START` — extended to optionally
  match `init <N> screen NAME(params):`.
- `senpy.core.constants.RE_INIT_PYTHON_START` — now captures the
  priority number as group 2.

---

<a id="081"></a>

## [0.8.1] — Hotfix release: 5 architectural bug-pattern clusters closed

Patch release closing 19 P1/P2 bugs identified in the post-0.8.0 external
audit and reconnaissance report. 1646 tests (up from 1487 in 0.8.0, +159).
No new rules; the release is purely correctness fixes plus three
architectural investments that automatically catch future regressions of
the same bug classes.

### Background — five architectural bug patterns

The auditor identified five recurring patterns behind most of the
bugs. Each pattern was closed by a single architectural fix, not by
patching the individual bugs one at a time:

- **String literals confused with code** — substring checks and regex
  scans on raw Ren'Py lines matched identifiers that lived inside
  dialogue text, Python string constants, or image names. Closed by
  the `strip_string_literals()` helper applied at every checker call
  site.
- **Cache incomplete restore** — Tier 1/Tier 2 cache hits restored
  `diagnostics` and `scope` but silently dropped `noqa_maps`,
  `missing_defaults`, `has_dynamic_jumps`, and the `enable_plugins`
  config flag. Closed by per-file persistence plus
  `test_cold_warm_equivalence` — any future forget-to-restore bug
  fails the test automatically.
- **QuickFix range ≠ replacement** — `fix_replacement` included the
  line indent while the LSP `TextEdit` range did not, or the range
  covered only the prefix of a call expression while the replacement
  dropped the rest. Closed by an explicit range/replacement contract
  enforced by `test_quickfix_preserves_validity`.
- **State not propagated** — `did_close` did not cancel pending
  per-URI timers; `analyze_menu_flow` did not forward
  `already_guaranteed` from `StateChecker.guaranteed_vars`;
  `_rename_symbol_via_text_search` ignored its `symbol_kind`
  parameter. Closed by plugging each propagation path with
  `test_run_idempotency` as the catch-all guard.
- **Rename precision** — LSP rename of a variable rewrote every
  whole-word occurrence, including label declarations, jump targets,
  and natural-language mentions in dialogue. Closed by kind-specific
  predicates that filter raw text-search matches by context.

### Cache soundness (cold/warm equivalence)

- **Tier 2 cache restores `# noqa` directives**: `analyzer._noqa_maps`
  is now recomputed via `build_noqa_map(lines)` on every Tier 2 cache
  hit. Previously, suppressed cross-file diagnostics (RPY701-707,
  RPY802) re-fired on warm runs because `_noqa_maps[path]` was empty.
- **Tier 2 cache restores `missing_defaults`**: per-file snapshot
  persisted in the new `CachedFileEntry.missing_defaults` field and
  re-merged on cache hit. `generate_defaults_file()` now produces the
  same output on cold and warm runs.
- **Tier 1 cache restores `has_dynamic_jumps`**: per-file flag added
  to `FileScope.has_dynamic_jumps`, aggregated in
  `SymbolTable.rebuild_from_scopes()`. Warm runs no longer lose the
  flag and re-enable RPY701-707 on projects with dynamic jumps.
- **Environment fingerprint includes `enable_plugins`**: toggling the
  `enable_plugins` config flag now invalidates the Tier 2 cache. A
  warm run after enabling plugins no longer serves stale
  no-plugins-run results.
- **Cache backward compatibility hardened**: loading a manifest
  written by an older Senpy version (one that lacks the new
  `fixable_count`/`fixed_count`/`missing_defaults` fields on
  `CachedFileEntry`) no longer crashes. The `getattr(entry, ...)` fallback
  applies silently via `test_cache_backward_compat_missing_fixable_count`.
- **Malformed RPA archives no longer crash `_read_rpa_index`**: the
  except clause now catches `TypeError` (non-dict pickle root) and
  `AttributeError` (non-str dict keys) in addition to the previous
  set. Activation of `_read_rpa_index` from the production path is
  tracked separately for 0.8.2.

### QuickFix correctness (no more broken source after `--fix` or LSP)

- **RPY401 QuickFix no longer destroys menu choices**: the fix now
  inserts a new line in the missing branch's body (with proper
  indentation) instead of replacing the choice text with
  `$ var = 0` — the choice line stays intact, the trailing `:` is
  preserved.
- **RPY002 QuickFix no longer duplicates indent**: the LSP `TextEdit`
  range now covers the entire line (matching the replacement), so the
  editor no longer preserves the leading indent outside the range and
  then prepends the indent included in the replacement. Trailing
  newline also stripped from the replacement.
- **RPY206 QuickFix no longer drops `action` prefix or args**: the
  range now extends to the matching closing `)` of the call
  (depth-counted to handle nested parens), and the replacement
  preserves the `action ` prefix and original arguments:
  `action Function(myfunc, arg1, arg2)` instead of
  `Function(myfunc)arg1, arg2)`.
- **`test_quickfix_preserves_validity`** runs on every `bad_*.rpy`
  fixture that produces a fixable diagnostic, asserting the resulting
  source parses as Python (for `$`/`python:` lines) or has balanced
  quotes and brackets (for Ren'Py screen/menu lines). Future
  QuickFix-damage bugs fail this test before they ship.

### LSP precision (rename and asset refresh)

- **`did_close` cancels pending per-URI change timer**: a stale
  timer that was scheduled before `did_close` no longer fires 150ms
  later and re-adds the closed document to `in_memory_files`.
- **`did_change_watched_files` refreshes `AssetManager`**: external
  additions/removals of `.png`/`.ogg`/`.mp3`/`.wav` (via file
  manager, git pull, asset pipeline) now trigger a debounced
  `AssetManager.index()` refresh. Hover cards and RPY501-503 stay
  accurate across long-lived LSP sessions.
- **LSP rename respects `symbol_kind`**: `_rename_symbol_via_text_search`
  now filters raw text-search matches by context before emitting
  `TextEdit`s. Renaming a variable no longer touches label
  declarations, jump targets, screen actions, or natural-language
  mentions in dialogue that happen to share the same textual token.
  Renaming a transform no longer touches variables; renaming a
  screen no longer touches transforms.

### Static analysis precision (no more false positives on dialogue)

- **`strip_string_literals()` helper introduced** in
  `senpy/text_utils.py`: masks the content of `"..."` and `'...'`
  literals with spaces, preserving column positions of code outside
  literals. Applied before every substring check and regex scan in
  `file_collector._collect_misc`, `dialogue._check_dynamic_jump_targets`,
  `screen._check_screen_variable_actions`, and
  `screen._check_screen_action_targets`. Future rules that match
  identifiers via substring or regex must apply the helper first.
- **RPY302 no longer fires on dialogue mentioning `Jump('foo')`**: a
  dialogue line like `"The syntax Jump('missing_label') is
  interesting."` no longer triggers a false positive for a
  non-existent label.
- **RPY204 no longer fires on `Show(...)` in screen text dialog**:
  `text "Press Show('missing_screen') to continue."` no longer
  triggers a false positive for a non-existent screen.
- **RPY202 no longer fires on `SetVariable(...)` in screen text
  dialog**: `text "Press SetVariable('undeclared_var', 1) to
  debug."` no longer triggers a false positive for an undeclared
  variable.
- **RPY303 no longer masked by quoted identifiers in Python strings**:
  `$ config.label_overrides = "unused_label"` no longer adds
  `unused_label` to `referenced_labels` — the label is correctly
  flagged as unused.
- **`has_dynamic_jumps` no longer flipped by dialogue mentions of
  `renpy.jump()`**: a dialogue line like
  `e "Use renpy.jump() to switch scenes."` no longer suppresses
  RPY701-707 across the entire project.
- **Menu flow honours pre-menu `guaranteed_vars`**: a variable
  assigned before `menu:` is no longer flagged as MAYBE_SET after the
  menu — `merge_flow_branches` now receives `already_guaranteed`
  from `StateChecker.guaranteed_vars`, matching the existing `if`
  block path.

### Architectural investments (regression guards)

Three infrastructure tests added in 0.8.1 automatically catch future
bugs of the same class without manual auditing:

- **`test_cold_warm_equivalence`**: cold and warm runs on the same
  project must produce identical diagnostic sets and identical
  analyzer state (`missing_defaults`, `referenced_labels`,
  `has_dynamic_jumps`, `user_symbols`, `total_lines`,
  `fixable_count`, `fixed_count`). Any future forget-to-restore bug
  fails this test.
- **`test_run_idempotency`**: two consecutive `run()` calls on the
  same analyzer instance must produce identical state. Any future
  forget-to-reset bug in `_run_reset` fails this test.
- **`test_quickfix_preserves_validity`**: every QuickFix in the
  project must produce syntactically valid source after the LSP
  `TextEdit` is applied. Any future QuickFix-damage bug fails this
  test.

### Known limitations carried to 0.8.2

The following audit findings are NOT closed in 0.8.1 and are tracked
for 0.8.2:

- **Python AST analyses assignments without conditionality** —
  `extract_assigned_names` uses `ast.walk` and treats conditional
  assignments (inside `if`/`for`/`while`) as guaranteed. Requires
  proper SSA-style flow analysis, planned for 0.9+.
- **`collect_from_python_block` via `ast.walk`** — same root cause as
  the AST conditionality issue. Same target release.
- **`_read_rpa_index` activation** — the hardening (TypeError /
  AttributeError handling) is in 0.8.1, but the function itself is
  still dead code (`.rpa` is in `NON_ASSET_EXTENSIONS`). Decision
  about whether Senpy should index RPA archives at all is tracked as
  A18 for 0.8.2.

### wontfix

- **`_consume_block` aborts on top-level comment** — investigated
  but found NOT to be reproducible on syntactically valid Python
  code. Any top-level comment inside an indent-0 `init python:`
  block immediately followed by body-level code is a Python syntax
  error (RPY110) — the current behaviour (breaking on such
  comments) is therefore defensible. Marked wontfix with explicit
  justification in the roadmap.

### Test suite

- **1646 tests pass** (up from 1487 in 0.8.0, +159). Test count growth:
  - 22 unit tests for the `strip_string_literals()` helper.
  - 16 regression tests for the dialogue false-positive cluster.
  - 5 regression tests for the QuickFix damage cluster.
  - 16 fixture-parametrised tests for QuickFix validity.
  - 6 regression tests for cache state restoration.
  - 3 regression tests for RPA malformed archive handling.
  - 3 infrastructure tests (idempotency, backward compat, cold/warm
    equivalence).
  - 5 regression tests for LSP event handling (did_close timer,
    watched_files refresh).
  - 2 regression tests for menu flow `guaranteed_vars` propagation.
  - 7 regression tests for rename precision + severity overrides.

---

<a id="080"></a>

## [0.8.0] — Production-stable: security hardening, soundness fixes, plugin API contract

First release declared production-stable. 1487 tests (up from 1331 in 0.7.7,
+156). Closes all P0/P1 audit findings (security, soundness, CLI contracts)
identified in the comprehensive audit at commit 40789b7. The 0.7.7 release
was a documentation/SEO stub for Open VSX publishing — this is the first
substantive release since 0.7.6, containing 117 commits (55 significant
after filtering badge-noise and merges), including a new MkDocs Material
documentation site, security hardening across CLI/LSP/HTML report, and
the complete RWLock migration.

### Security

- **JUnit XML escaping**: `diag.code` and `diag.line_content` are now
  HTML-escaped via `_xml_escape` in `<failure>`/`<skipped>` elements —
  previously, source code with `<`, `>`, `&` broke the whole report for
  Jenkins/GitLab CI/TeamCity parsers.
- **`--fix` write failures surfaced**: `_write_fixed_file` no longer
  silently swallows `OSError` (read-only file, disk full, permission
  denied). Each failed write is logged at WARNING, recorded in
  `AnalysisResult.failed_writes`, and forces a non-zero CLI exit code —
  silent data loss is no longer possible.
- **XSS in HTML report**: `diag.code` and `diag.severity` are now
  HTML-escaped before interpolation into the diagnostic card. A malicious
  plugin rule code (e.g. `'RPY001"><img src=x onerror=alert(1)>'`) can
  no longer execute in the browser when the user opens
  `senpy --export-html` output. The CSS variable lookup
  `var(--{severity})` is also sanitised to a safe CSS identifier.
- **Path traversal in LSP asset hover**: `_resolve_relative_to_game`
  now uses `os.path.realpath` + `os.path.commonpath` containment check.
  A malicious `.rpy` with `image evil = "images/../../etc/passwd"` can
  no longer disclose system file size/path via hover.
- **Plugin code collision rejected at runtime**: `register_loaded_plugins()`
  now rejects plugin rules whose `code` collides with a built-in
  `RULES_DATABASE` entry. Previously the collision was only filtered
  client-side in `senpy rule list` — the plugin rule still ran during
  `analyzer.run()`, producing duplicate diagnostics. The `RPY9xx` range
  is formally reserved for plugin rules.

### Changed — CLI

- **`--exit-zero` honoured by every output format**: previously only
  `render_text` respected the flag; the other six renderers (sarif,
  json, junit, github, rdjson, gitlab) returned `1 if error_count > 0
  else 0` unconditionally, breaking non-blocking CI workflows like
  `senpy --exit-zero --format sarif`. A shared `_exit_code(args,
  error_count)` helper now applies the flag consistently.
- **CI badges moved to GitHub Gist**: the `update-badges` CI job no
  longer commits `chore(badge): update dynamic badges [skip ci]` back
  to `main` (which caused merge conflicts with maintainer pushes). Badge
  JSON is now pushed to a GitHub Gist via API; `main` is never touched.
  README badge URLs point at the gist's raw JSON.
- **`bump_version.py` extended**: now updates 4 hardcoded version mentions
  (`.pre-commit-hooks.yaml`, `.github/release-header.md`, `docs/install.md`,
  `docs/index.md`) that previously drifted every release.

### Changed — Architecture (internal, no API break)

- **`SenpyAnalyzer` god-file split**: extracted `FileCollector` (file
  discovery, I/O, symbol collection — 14 `_collect_*` methods),
  `AnalysisPipeline` (per-file analysis, plugin rule dispatch,
  `--fix` writer — 12 methods), `SymbolTable` (15+ symbol attrs),
  `_console` shared module. 38 characterization tests guard the split.
  `SenpyAnalyzer` is now a thin facade with pass-through wrappers.
- **`cli/main.py` god-file split**: extracted `args`, `filters`,
  `renderers`, `early_exits`, `runner`, `commands`, `discover`,
  `format_dispatch`, `inspect_dispatch`, `rule_dispatch`.
- **RWLock migration complete**: legacy module-level `_analysis_lock`
  removed; reader-writer lock is the single synchronization mechanism.
  `did_close` now holds the write lock when mutating `in_memory_files`.
- **`Protocol`-based checker contracts**: `DiagnosticSink`,
  `NoqaMapProvider`, typed `BaseChecker` via Protocol intersections
  (not concrete analyzer). `RULE_SEVERITY` derived from
  `RULES_DATABASE` (eliminates drift).
- **`AssetManager` stale class-level cache removed**: cache that
  survived file deletions in LSP is gone; asset state is now per-run.
- **`dry_run_callback` replaces `builtins.open` monkey-patch**: `--diff`
  mode no longer patches `builtins.open` globally; the analyzer accepts
  a callback that captures what `--fix` would write without touching
  the disk.
- **Coverage gate raised to 80%**; multiple checkers split for lower
  cyclomatic complexity (`check_unused_declarations` CC 53→2,
  `check_condition` split, `check_init_dependency` split into 3,
  `_check_jump_call_targets` split, `AssetManager.index` split,
  `validate_call_arguments` split, `validate_tl_pairs` split,
  `check_cross_language_consistency` split, `_check_binop_incompatible`
  split, `check_story_islands` split, `folding_range` split).

### Fixed

- **Tier 2 cache hit restores `fixable_count` and `fixed_count`**:
  previously, a warm run with a cache hit lost these counters, making
  `--check` output inconsistent between cold and warm runs.
- **Differential purge keeps cross-file shared symbols**: purging a
  file for re-analysis no longer removes its contribution to shared
  sets (`referenced_labels`, `user_symbols`, `declared_symbols`) that
  other files' diagnostics depend on.
- **Plugin trust store atomic write**: a failure during trust-store
  write no longer truncates the file (content is preserved).
- **`PLUGIN_API_VERSION` checked at module level** (in addition to
  instance level) — a plugin with a wrong API version is rejected
  earlier.
- **`# noqa` honoured in `dead_code` and translation rules**:
  previously, plugin-rule diagnostics from these checkers ignored
  inline `# noqa` directives.
- **Plugin rules wired into the analyzer**: the `_run_plugin_rules`
  path was not actually invoked during `analyzer.run()` (gated by
  `enable_plugins` config, default false in 0.8.0).
- **Call hierarchy ranges point at jump lines** (not label
  declarations); labels are now indexed per-file, fixing
  cross-file rename/reference.
- **Range formatting capability removed** from LSP (was not
  supported by the formatter; advertising it caused VS Code to
  show a broken "Format Selection" command).
- **`did_close` holds write lock** when mutating `in_memory_files`
  (race condition with concurrent `did_change`).
- **HTML report shows real elapsed time** (was hardcoded `0.0`).

### Documentation

- **MkDocs Material site**: new documentation site at `docs/` with 13
  pages (install, configuration, CLI reference, formatter, plugin
  development, comparison, renpy-linter/error-checker/static-analysis/
  story-graph/translation-checker/vscode-extension/github-actions).
  Built with MkDocs Material theme; deployed via `.github/workflows/docs.yml`
  to GitHub Pages. Includes custom CSS, favicon, and Senpy brand icon
  from the Open VSX extension.
- **`SECURITY.md` synced with code**: real HTML report CSP documented
  (was `default-src 'none'`, actually `default-src 'self'; script-src
  'self' 'unsafe-inline' ...`); new "No Plugin Sandbox Exists" section
  (hardening checklist is advisory, not enforced); TOFU placeholder
  added (trust-check runs after load — fix planned).
- **`ARCHITECTURE.md` synced**: `SafeCacheUnpickler` described as
  allowlist-only (was incorrectly documented as having a blocklist);
  rule count 45→51; formatter count 8→9; `format skip` directive
  removed from docs (not implemented).
- **`senpy-vscode/README.md`**: rule count 33+→51.
- **`docs/comparison.md`**: test count 1331→1487.
- **`docs/FORMAT_STYLE_GUIDE.md`**: formatter count 8→9.
- **`docs/formatter.md`**: removed `# senpy: format skip` example (not
  implemented); replaced with a note that `format off`/`on` is the only
  toggle.
- **Plugin example README**: new "Rule code ranges (contract)" section
  documenting `RPY0xx`–`RPY8xx` (built-in) vs `RPY9xx` (plugin) ranges.

### CI / Release infrastructure

- **GitHub Release notes auto-generated from CHANGELOG**: the release
  workflow now builds the release body from the matching `## [X.Y.Z]`
  section in `CHANGELOG.md` + a header template (`.github/release-header.md`),
  so release notes are never out of sync with the changelog.
- **CI badges served from GitHub Gist**: badge JSON is pushed to a Gist
  via API instead of committing back to `main` (eliminates merge-conflict
  churn with maintainer pushes).
- **macOS CI matrix** (added in 0.7.5, retained): Ubuntu × Windows × macOS
  across Python 3.11/3.12/3.13, plus Python 3.14 beta (experimental).

### Migration notes

- **Plugin authors**: if your plugin used a built-in code (`RPY001`–`RPY8xx`),
  it will now be rejected at load time with a WARNING. Switch to an unused
  `RPY9xx` code.
- **CI users**: `senpy --exit-zero --format sarif` now correctly exits 0
  even with errors (was exit 1). `senpy --fix` on a read-only file now
  exits non-zero (was silent success).
- **No breaking API changes** for plugin authors or library users.

---

<a id="077"></a>

## [0.7.7] — Documentation, SEO & Open VSX publishing

Documentation and discoverability release. All 1331 tests pass unchanged. This release focuses on making
Senpy findable by users who don't already know the name.

### Documentation — README

- **New comparison section**: `Senpy vs built-in renpy lint` —
  12-row table covering approach, speed, save/rollback safety,
  translation mismatch detection, story graph, dead code, branching
  dataflow, init phase dependency, CI-readiness, IDE integration, what
  each tool catches, and distribution. Closes the comparative search
  intent for `renpy linter`, `renpy lint alternative`, `renpy static
  analysis` queries.
- **New comparison section**: `Senpy vs vscode-language-renpy`
  (official extension) — 12-row table covering syntax highlighting,
  language configuration, snippets, real-time diagnostics, go-to-def,
  find references, hover docs, rename, semantic tokens, story graph,
  save/rollback safety, translation validator. Positions Senpy as
  complementary to the official extension, not a replacement. Closes
  the `renpy vscode extension`, `renpy lsp`, `renpy language server`
  query cluster.
- **New disambiguation footer**: `Other projects named "senpy"` —
  lists the 4 unrelated projects that share the name `senpy` (PyPI
  sentiment-analysis server, `ACasey13/senpy` Neyer sensitivity
  testing, SCIA Engineer `senpy` XML framework, ScienceDirect academic
  paper). Reduces bounce rate from users who landed here by mistake and
  helps Google disambiguate the brand.

### Changed — `senpy-vscode/package.json`

- **`displayName`**: `senpy-vscode` → `Senpy — Ren'Py Linter & Language
  Server` (was the package name; now SEO-friendly).
- **`description`**: panch-line removed, replaced with SEO-rich
  description mentioning undefined variables, broken labels,
  control-flow bugs, save/rollback issues, translation errors.
- **`categories`**: `["Other"]` → `["Programming Languages", "Linters",
  "Formatters"]`.
- **`keywords`**: added 15 SEO keywords (`renpy`, `ren'py`, `visual
  novel`, `linter`, `static analysis`, `language server`, `lsp`, `code
  quality`, `game development`, `translation`, `localization`, `save
  safety`, `rollback`, `story graph`, `rpy`).
- **`galleryBanner`**: added (`#1f1f28`, dark theme).
- **`icon`**: added (`images/icon.png`, 256×256).
- **`license`**: `SEE LICENSE IN LICENSE`.
- **`bugs`**, **`homepage`**: added, pointing to GitHub.
- **Bugfix**: `npm-runall` → `npm-run-all` (typo in `devDependencies`
  that would break `npm install`).

### Changed — `senpy-vscode/README.md`

Replaced the 2-line stub with a full Marketplace-ready README: badges,
why-Senpy, key features, screenshots (via absolute GitHub URLs so `vsce`
includes them in `.vsix`), installation instructions, comparison tables
with built-in lint and `vscode-language-renpy`, full detection list by
RPY1xx–RPY8xx category, who-is-Senpy-for, configuration, links to
GitHub/PyPI/Habr/Lemma Soft Forums.

### Publishing — Open VSX Registry

Extension `xilleet.senpy-vscode` 0.7.7 published to Open VSX
(https://open-vsx.org/extension/xilleet/senpy-vscode). Available for
auto-discovery in VSCodium, Cursor, GitLab Web IDE, and Eclipse Theia.
112 cumulative downloads at release time. VS Code Marketplace
publication is blocked due to Microsoft Azure DevOps sanctions on
Russian accounts — Open VSX is used as the primary registry, GitHub
Releases as the secondary distribution channel for VS Code users.

### Known limitations

- `senpy.exe` (36 MB PyInstaller bundle) is still bundled inside the
  `.vsix`. This makes the package large and triggered scanning
  rejections on first Open VSX upload attempts. Long-term solution:
  move `senpy.exe` to a separate GitHub Release asset and download on
  first run. Tracked as a backlog item.
- Namespace `xilleet` on Open VSX is not yet verified (claim pending
  manual review by Eclipse Foundation administrators via GitHub issue
  in `EclipseFdn/open-vsx.org`).

---

<a id="076"></a>

## [0.7.6] — New rules (RPY704-707, RPY801-802), rule improvements, mypy hardening, fixture coverage 100%

Feature patch release. Six new lint rules, four rule improvements, 100%
fixture coverage (45/45 → 51/51 rules), mypy errors reduced from 264 to 32
(−88%), and CI badges now update even when a matrix job fails. All 1331
tests pass, ruff check clean, 0 import cycles across 87 modules.

### New Rules — Dead Code (RPY704-707)

Four new rules in the dead-code domain, extending RPY701-703 (unused
define/transform/screen):

| Rule | Severity | What |
|---|---|---|
| **RPY704** | HINT | Unused `default` variable — declared but never referenced. Complement to RPY701 (which covers `define` constants). |
| **RPY705** | HINT | Unused screen parameter — `screen shop(unused_param, gold):` where `unused_param` is never used in the body. |
| **RPY706** | HINT | Unused transform parameter — same logic as RPY705 for transforms. Required extending `TransformSymbol` with a `signature` field. |
| **RPY707** | HINT | Unused audio channel registration — `renpy.music.register_channel("name")` but no `play`/`queue`/`stop` on that channel. |

All four are HINT severity (dead code, not bugs). RPY705/706 check
parameter usage anywhere in the file (approximation — a proper
cross-reference requires parsing the screen/transform body block by
indent. Documented as a limitation; accepted for v1).

### New Rules — Translation Quality (RPY801-802)

Two new rules for translation file quality, extending RPY601-603:

| Rule | Severity | What |
|---|---|---|
| **RPY801** | WARNING | Duplicate translation string — same `old` source text appears twice in a file. Second translation silently overrides the first (dead code). |
| **RPY802** | WARNING | Inconsistent translation across files — same source string translated differently in different files within the same language directory (e.g. `game/tl/russian/common.rpy` vs `game/tl/russian/dialogue.rpy`). |

RPY802 is a cross-file check — it requires a new `check_cross_language_consistency()`
function that collects all translation pairs across all `game/tl/<lang>/`
files and flags inconsistent translations within each language.

### Rule Improvements — RPY108, RPY401, RPY403, RPY502

| Rule | Improvement |
|---|---|
| **RPY108** | Now catches incompatible binary operations inside expressions (`$ result = "text" + 5`, `$ x = [1,2] - 3`). Previously only caught type conflicts at the assignment level. New `_check_binop_incompatible()` helper checks all `BinOp` AST nodes. |
| **RPY401** | Now provides a concrete fix suggestion: `fix_replacement = "$ var = 0"` + actionable message ("Add '$ var = 0' to this branch or use 'default var' at top level"). |
| **RPY403** | Now detects tautologies (`if x or not x:` — always True) and always-true literals (`if "non-empty":`). Dual to the existing contradiction check (`if x and not x:`). |
| **RPY502** | Case-insensitive matching for image tags and attributes. `show Sayori` now suggests `sayori` (case mismatch), and `show sayori Happy` suggests `happy`. Falls back to difflib fuzzy match if no case-insensitive exact match. |

### Fixture Coverage — 45/45 → 51/51 (100%)

Before this release, 22 of 45 rules had no fixture tests. All 51 rules
now have at least one bad + one good `.rpy` fixture file, auto-verified
via snapshot JSON. This includes:

- RPY100 (file not valid UTF-8) — special binary fixture in cp1251 encoding
- RPY503 (unused media asset) — documented limitation (requires real
  image files on disk, which the fixture framework doesn't copy; covered
  by unit tests in `test_asset_checker.py` instead)
- RPY802 (cross-language inconsistency) — fixture documents the bad case
  but can't trigger it in CI (requires multi-file structure); covered by
  unit tests in `test_translation_rpy8xx.py` instead

New script: `scripts/create_wl440_fixtures.py` — idempotent generator
for all fixture files. Run once, then `pytest --update-snapshots` to
auto-generate JSON snapshots.

### mypy Hardening — 264 → 32 errors (−88%)

Three-phase approach to reduce mypy errors before the 0.8.0 architecture
split (WL-200):

| Phase | What | Errors before | Errors after |
|---|---|---|---|
| **Phase 1** | Exclude vendored unrpyc from mypy; fix 2 trivial errors in `cli/main.py` | 264 | 168 |
| **Phase 2a** | Replace `DiagnosticSink` Protocol with `SenpyAnalyzer` via `TYPE_CHECKING` in BaseChecker, StateChecker, DialogueChecker, PythonAstChecker, StoryFlowAnalyzer, MermaidBuilder | 168 | 60 |
| **Phase 2b** | Fix pygls `LanguageServer` imports (`type: ignore`); add None guards for `FlowBranch \| None`; fix AST node narrowing; fix `float`/`int` assignment; fix `Optional` access | 60 | **32** |

Remaining 32 errors are mostly `arg-type` (function signature mismatches)
and `union-attr` (Optional access without guard) in `python_ast.py`,
`state.py`, `sarif.py`, `lsp/` handlers. These require deeper type
narrowing or API stubs — deferred to WL-201 Phase 2c or WL-634 (ISP
Protocol split, post-WL-200).

**Architectural compromise (Phase 2a):** Replacing `DiagnosticSink` Protocol
with `SenpyAnalyzer` is a pragmatic fix, not the correct architecture. The
Protocol was too narrow (declared only diagnostics methods, but checkers
use variables/labels/screens/assets). Proper fix is ISP (Interface
Segregation Principle) split into `DiagnosticSink`, `SymbolProvider`,
`AssetProvider`, `FlowProvider` — tracked as WL-634, planned for 0.8.0.

### CLI — Flag combination validation

New `_validate_flag_combinations()` function catches user mistakes
before analysis starts:

- `--fix + --check` → error (can't apply and dry-run simultaneously)
- `--fix + --diff` → error (can't apply and only-show-diff)
- `--check + --diff` → error (two dry-run modes is ambiguous)
- `--extend-select` without `--select` → warning (no-op)
- `--extend-ignore` without `--ignore` → warning (no-op)
- `--add-noqa + --fix` → warning (both target fixable diagnostics)

Hard errors exit with code 2 and a clear message (no traceback).

### CI — Badges always update; Dependabot; macOS matrix

| Change | What |
|---|---|
| **Badges `if: always()`** | `update-badges` job now runs even when a matrix test fails. Previously, one failed macOS job blocked badge updates → stale green badge. Now badges always reflect the latest test run. |
| **Dependabot** | `.github/dependabot.yml` — weekly updates for pip deps + GitHub Actions. Groups related updates into one PR. |
| **macOS × Python 3.11/3.13** | CI matrix expanded from 6 to 14 jobs (Ubuntu/Windows/macOS × 3.11/3.12/3.13 + Ubuntu/Windows × 3.14-beta experimental). |
| **Python 3.14 classifier** | Added to `pyproject.toml` classifiers. |

### Example Plugin — RPY902 (todo_comment_plugin)

New example plugin in `examples/todo_comment_plugin/`:
`RPY902` — detects `# TODO:`, `# FIXME:`, `# XXX:`, `# HACK:` comments
left in `.rpy` files. HINT severity (reminders, not bugs). Case-insensitive,
word-boundary aware (`# todolist` doesn't fire, `# TODO:` does).

### Tests

- **1331 tests pass** (up from 1203 in 0.7.5; +128 from new rules + fixtures + mypy fixes)
- Ruff check clean. 0 import cycles across 87 modules.
- Coverage stable at ~82%.
- mypy: 32 errors (down from 263 in 0.7.5; baseline, non-blocking).

### Internal

No public APIs changed (except: 6 new rule codes in RULES_DATABASE,
RULE_SEVERITY, TSUNDERE_FLAVORS, and tsundere messages). All new rules
are HINT or WARNING — none are ERROR, so existing CI gates are unaffected.

---

<a id="075"></a>

## [0.7.5] — Plugin autoload, CI hardening, BLAKE2b hash, doc-sync

Patch release: four independent threads — closes the CI plugin-smoke
regression from 0.7.4's pre-commit commit, hardens the cache hash, expands
the CI matrix to macOS, and refreshes stale documentation across the project.
No new rules, no new LSP handlers, no public API changes. All 1218 tests
pass, ruff check clean, 0 import cycles across 87 modules.

### Plugins — autoload installed trusted plugins in CLI entrypoints

The 0.6.0 plugin system shipped with a loader pipeline (`discover_plugins`
→ `load_plugin` → `load_all_plugins` → `register_loaded_plugins`) that
was correct in isolation — and never called from production code. The
plugin-smoke CI job added in commit `39d71f6` ("feat: macOS CI matrix,
Python 3.14 beta, RWLock timeout, plugin smoke test") caught the gap by
asserting that `senpy rule list --format json` includes `RPY901` after
`pip install -e examples/my_senpy_plugin`. The assertion failed in CI
because no code path invoked the loader, so plugin rules stayed in the
`_REGISTERED_LINT_RULES` registry empty.

This release closes that gap with a new `senpy/plugins/autoload.py`
module that wraps the loader pipeline in an idempotent one-shot function:

```python
from senpy.plugins.autoload import autoload_plugins

autoload_plugins()  # called once per process, from cli/main.py:main()
                    # and from cli/rule_dispatch.py:dispatch_rule()
```

Design:

* **Idempotent.** Module-level `_PLUGINS_LOADED` flag short-circuits
  subsequent calls. Tests that need a fresh load can call
  `reset_autoload_state()` (or pass `force=True`).
* **Safe.** A broken plugin (import error, missing `meta`, bad
  `PLUGIN_API_VERSION`) is skipped with a `_logger.warning` — the
  linter never crashes. Isolation was already in `load_all_plugins`;
  autoload extends it to the entry-point wrapper.
* **Trust-on-first-use preserved.** Production callers pass
  `trust_callback=None`, which falls back to the existing
  `_default_trust_callback` (TTY prompt, trust store, LSP-mode decline).
  Tests inject `trust_callback=lambda name: True` to bypass trust
  without writing to `~/.senpy/trusted_plugins.json`.

After autoload, plugin rules are visible in `senpy rule list/show`
and in `senpy inspect` output. The `cli/rule_dispatch.py` `_filter_rules`
function now merges built-in `RULES_DATABASE` with rules from
`get_registered_lint_rules()`. On code collision (plugin ships
`code="RPY001"`), the built-in wins — the canonical source for
`code/severity/docs/why/bad/good` must always point at the built-in
definition. Plugin rule dicts have `why/bad/good` set to placeholder
strings because `RuleMeta` only carries `docs`.

Plugin rules are NOT yet wired into the analyzer's per-file check loop
(`SenpyAnalyzer._analyze_file` runs `BaseChecker` line-by-line, not
`Rule.check(ctx)`). That wiring is a separate task tracked for 0.8.0,
after the `SenpyAnalyzer` split (god-class refactoring) makes the
analyzer extensible without risking the existing checkers.

### Pre-commit hook — `.pre-commit-hooks.yaml` (non-mutating only)

Senpy is now usable as a [pre-commit](https://pre-commit.com) hook in
any project, with a 4-line config:

```yaml
repos:
  - repo: https://github.com/Xilleet/senpy
    rev: v0.7.5   # Use the latest tag
    hooks:
      - id: senpy
```

Only `senpy --check` (non-mutating) is exposed as a hook. A `senpy --fix`
auto-fixing hook would create an infinite loop on Windows when combined
with `ruff-format` (CRLF ↔ LF conversion via git's `autocrlf`). This
was the lesson from the 0.7.1 `ruff-format` hook rollback —
documented in the worklog and in the hook file's own comment block.
Users who want auto-fix can run `senpy --fix` manually or wire up a
local hook with their own line-ending strategy.

The README (both `README.md` and `README_ru.md`) gained a
"Pre-commit Integration" section showing the config.

### Cache — BLAKE2b file hash

`senpy/core/cache.py:compute_file_hash` switched from MD5 to BLAKE2b.
MD5 was not security-critical (used only for cache invalidation, not
authentication), but BLAKE2b is faster on modern CPUs and carries no
crypto-analytic baggage.

Old `.senpy_cache/cache.pkl` files invalid silently: the stored MD5
hash no longer matches the freshly-computed BLAKE2b, so the cache
manager treats the entry as a cache miss and recomputes. No crash, no
user-visible warning. The next cache write uses BLAKE2b.

Tests: `tests/test_cache_hash.py` (113 lines, ~10 cases) covers both
the algorithm pin and the cross-version invalidation path.

### LSP — `_RWLock` gains `acquire_read(timeout=...)` / `acquire_write(timeout=...)`

The hand-rolled `_RWLock` in `senpy/lsp/server.py:117` previously had
no timeout — a stuck client could hold the read or write lock
indefinitely, hanging the entire LSP server. This release adds
`acquire_read(timeout: float | None = None)` and
`acquire_write(timeout: float | None = None)`, implemented via
`threading.Condition.wait(timeout=remaining)` with a
`time.monotonic()` deadline. Returns `True` on acquired, `False` on
timeout.

Full migration to the `readerwriterlock` PyPI library (which provides
reentrant locks, debug-assertions, and timeout out of the box) is
**deferred to post-1.0** as a documented tradeoff. The hand-rolled
lock is small (~80 LOC), well-tested (`tests/test_lsp_rwlock.py`),
and the migration would add a new runtime dependency for marginal
benefit. The comment block at `_RWLock` (added in this release)
records the rationale.

### CI — macOS matrix, Python 3.14 beta

The `test` matrix grew from 6 jobs (Ubuntu + Windows × 3.11/3.12/3.13)
to 14:

* Ubuntu × {3.11, 3.12, 3.13} — 3 jobs
* Windows × {3.11, 3.12, 3.13} — 3 jobs
* macOS × {3.11, 3.12, 3.13} — 3 jobs (NEW — VN developers often use macOS)
* Ubuntu × 3.14-beta — 1 job (`continue-on-error: true`, experimental)
* Windows × 3.14-beta — 1 job (`continue-on-error: true`, experimental)

Python 3.14 is in beta until October 2026. Dependencies (`pydantic`
C extensions, `pygls`) may not fully support it yet. The
`continue-on-error` flag means a 3.14 failure does not block PRs.
When 3.14 goes stable, the flag is removed in a separate patch.

`pyproject.toml` classifiers include `Programming Language :: Python :: 3.14`
so PyPI shows the experimental support.

### `senpy inspect` — `SYSTEM_LABELS`

`senpy/formats/inspect.py` and `senpy/core/constants.py` gained a
`SYSTEM_LABELS` set: `start`, `splash_window`, `after_load`,
`main_menu`, `before_main_menu`, `quit`, `after_load`, etc. These are
labels Ren'Py calls automatically based on `config.start_callback`,
`config.after_load_callback`, and the splash-window protocol. `senpy
inspect` no longer reports them in the `unresolved.unreferenced_labels`
list — they are referenced by Ren'Py itself, not by user code.

### `senpy/domain/assets.py` — `NON_ASSET_EXTENSIONS`

A new `NON_ASSET_EXTENSIONS: frozenset[str]` declares file extensions
that are part of the Ren'Py project structure but are NOT game assets:
`.rpy` (source code), `.rpym` (module source), `.rpyc` (compiled
bytecode), `.rpyb` (older bytecode), `.rpymc` (compiled module), `.rpa`
(Ren'Py archive — Ren'Py loads its contents at runtime). The asset
checker skips these in unused-asset detection, so RPY503 no longer
flags `script.rpy` as an "unused media file".

The `.rpa` entry is marked "temporary, until the .rpa-aware asset
checker lands" — currently `.rpa` files are scanned for their
contents (which may include assets) but not flagged as assets
themselves.

### Codebase hygiene — English-only scripts

`scripts/check_cycles.py`, `run_tests.py`, and `bump_version.py` were
translated from Russian comments to English. The
`tests/test_no_russian_comments.py` guard was extended to scan
`scripts/` in addition to `senpy/`. The guard's state machine tracks
triple-quote nesting so Russian text inside string literals (e.g. in
test fixtures) is not flagged — only `#` comments and `"""…"""`
docstrings.

### Documentation — doc-sync across the project

Stale documentation caught by the pre-release doc-sync checklist
(worklog §2.5):

* `SECURITY.md`: "currently 0.6.x" → "currently 0.7.x"; supported
  versions table updated (0.7.x active, 0.6.x critical-only, <0.6
  unsupported).
* `README.md` / `README_ru.md`: "What's New" section now covers all
  five 0.7.x patch releases (0.7.1 through 0.7.5), each with a
  feature table. Previously only 0.7.0 and 0.6.0 were listed.
* `ARCHITECTURE.md`: Package Structure tree updated to include all
  modules added since 0.7.0 (`cli/discover.py`, `cli/inspect_dispatch.py`,
  `cli/rule_dispatch.py`, `formats/inspect.py`, `formats/rdjson.py`,
  `formats/gitlab.py`, `lsp/handlers/asset_hover.py`,
  `formatter/rules/string_consistency.py`, `plugins/autoload.py`,
  `core/paths.py`, `core/progress.py`, `domain/image_size.py`,
  `domain/renpy_api_generated.py`). Formatter table extended with
  `FMT-STRING-CONSISTENCY` (was missing since 0.7.4). Plugin loading
  pipeline documented with the new autoload step.
* `RULES.md`: Missing `RPY100` (File is not valid UTF-8) added between
  `RPY002` and `RPY101`. Navigation updated. Total documented rules:
  45 (was 44 — closes the `DOC-9a` gap from the v2 audit).
* `pyproject.toml`: `Programming Language :: Python :: 3.14` classifier
  was already added in commit `39d71f6` (macOS matrix commit); this
  release just confirms it ships in the tagged 0.7.5.

### Tests

* **1218 tests pass** (up from 1203 in 0.7.4; +15 from
  `tests/test_plugin_autoload.py`). All 15 new tests cover the
  autoload pipeline: idempotency, force-reruns-discovery,
  broken-plugin isolation, registry integration, dispatch_rule
  integration (rule list/show with plugin codes),
  collision-resolution (built-in wins on code conflict),
  tag/severity filters respect plugin rules, idempotency across
  multiple dispatch_rule calls.
* Ruff check clean. 0 import cycles across 87 modules (+1 new:
  `senpy/plugins/autoload.py`).
* Coverage stable at 81.74% (no regression — the new module is
  fully covered by the new test file).
* mypy: 263 errors total (169 outside vendor) — same baseline as
  0.7.4. The new module is fully typed; no new mypy regressions.

### Internal

The plugin system is now actually usable end-to-end from a user perspective (install + trust + `senpy rule list` shows the plugin rule) — the only remaining gap is wiring plugin `Rule.check(ctx)` into the analyzer's lint loop, which is tracked for 0.8.0 (after the `SenpyAnalyzer` god-class split makes the analyzer extensible without risking the existing `BaseChecker` line-by-line checkers).

---

<a id="074"></a>

## [0.7.4] — Introspection, output formats, rule metadata, strict mode, formatter rule

Six additive features in one patch release. No public API removed,
no rule severity changes (except opt-in `strict = true`). All changes
are backward-compatible — existing flags (`--rules`, `--rule`,
`--output-format sarif/json/junit/github`) continue to work.

### New subcommand — `senpy inspect`

Dumps all symbols Senpy sees in a project as JSON. Built for debugging
hover/asset resolution issues, plugin authoring, and regression
testing. A parallel mini-CLI (like `senpy format`): shares only
`SenpyAnalyzer` + cache with the main CLI, has its own arg parser and
render path.

```bash
senpy inspect [PATH]                # full JSON to stdout
senpy inspect game/ --summary       # only stats section (quick overview)
senpy inspect game/ --unresolved    # only broken jumps / missing screens / etc.
senpy inspect game/ --label start   # details of one label (auto --with-source)
senpy inspect game/ --screen shop
senpy inspect game/ --transform fade
senpy inspect game/ --no-cache      # cold run for fresh-state debugging
senpy inspect game/ --with-source   # include code_line/body for all symbols
senpy inspect game/ --decompile     # opt-in .rpyc/.rpa extraction
senpy inspect game/ -o dump.json    # write to file instead of stdout
```

JSON structure: `labels`, `screens`, `variables`, `transforms`,
`images`, `jump_sources` (reverse index of jump targets),
`used_assets`, `diagnostics`, `unresolved` (broken_jumps,
missing_screens, unreferenced_labels, unused_assets), `stats`
(per-section counters for quick overview without jq).

The 4 shortcut flags (`--summary`, `--unresolved`, `--label`,
`--screen`) cover the common debugging queries without requiring jq
on Windows. `--label`/`--screen`/`--transform` single-lookups
auto-enable `--with-source` (if you're looking at one symbol, you
want to see its source).

### Architecture — `discover_files` extracted to `senpy/cli/discover.py`

The 4 file-discovery functions (`discover_files` + 3 helpers:
`_find_rpy_files`, `_find_orphaned_rpyc`, `_decompile_sandbox`) were
moved from `senpy/cli/main.py` (~160 lines) into a new
`senpy/cli/discover.py` module. This lets `senpy inspect` reuse the
full pipeline (existing `.rpy` files + `.rpyc` orphans + `.rpa`
extraction + decompilation) without coupling to the main CLI's
argparse Namespace.

The only behavioral change: `_decompile_sandbox` (and `discover_files`
through it) gained an `interactive: bool = True` parameter. When
`interactive=False` (used by `senpy inspect`), the "Decompile them
into a sandbox? [y/N]" prompt is suppressed — only explicit
`--decompile` or `config['decompile']` triggers decompilation. The
main CLI passes `interactive=True`, preserving existing behavior.
All 8 existing characterization tests for `discover_files` continue
to pass without modification (mock-targets updated to point at the
new module).

### Determinism — `senpy inspect` ignores `config['decompile']`

`senpy inspect` is deterministic by design: the same `senpy inspect
PATH` command must produce the same JSON regardless of any
`senpy.toml` settings that happen to live in PATH or its ancestors.
The main CLI honors `config['decompile']` because the user explicitly
invoked lint and likely wants the project analyzed as fully as
possible. Inspect, however, must not silently start decompiling
`.rpyc` files just because a `senpy.toml` somewhere up the directory
tree says `decompile = true` — that would pollute the JSON output
with unrpyc's `[Preparing]`/`[Decompiling]` progress lines.

Decompile is opt-in for inspect: pass `--decompile` explicitly.
`--unrpyc` still honors `config['unrpyc_path']` (it's a pure
configuration: which unrpyc to use, not a behavior toggle).

This was caught during user testing on Windows: a project with
`decompile = true` in its `senpy.toml` triggered unrpyc decompilation
silently when running `senpy inspect PATH`. The test
`test_inspect_ignores_config_decompile_setting` now mocks
`find_unrpyc_executable` to return a fake command, so the regression
is caught on any platform (Linux CI runners don't have unrpyc
installed, so the bug was hidden before).

### Output formats — `rdjson` (Reviewdog) and `gitlab` (GitLab Code Quality)

Two new values for `--output-format`, expanding the CI integration
surface from 5 to 7 formats (`text`, `json`, `sarif`, `junit`,
`github`, `rdjson`, `gitlab`).

```bash
senpy game/ --output-format rdjson            # Reviewdog NDJSON (one issue per line)
senpy game/ --output-format rdjson -o r.json  # write to file
senpy game/ --output-format gitlab            # GitLab Code Quality JSON array
senpy game/ --output-format gitlab -o gl.json # write to file
```

* **`rdjson`** — Reviewdog Diagnostic Format (NDJSON). One JSON
  object per line, suitable for piping into `reviewdog -f=rdjson`.
  Severity mapping: `ERROR`/`WARNING`/`INFO` pass through unchanged;
  `HINT` becomes `INFO` (Reviewdog has no HINT level). Columns are
  1-based. Each finding carries `code.value` (rule id) and `code.url`
  (RULES.md anchor) for known rules; the URL is omitted for unknown
  codes (e.g. plugin rules).
* **`gitlab`** — GitLab Code Quality JSON report (top-level array).
  Suitable as a CI artifact for merge-request annotations. Severity
  mapping: `ERROR` → `major`, `WARNING` → `minor`, `HINT`/`INFO` →
  `info`. Each finding carries a `fingerprint` (`md5(code|path|line|message)`)
  for stable deduplication across runs — pinned by tests so a future
  algorithm change won't silently re-open every GitLab finding.

Both formats support `--output-file` and respect `--quiet` mode.

### Rule metadata — `tags` field, `senpy rule` subcommand, `--tag` filter

Three coupled changes that share the same `RULES_DATABASE` extension.

**Tags.** Every rule in `RULES_DATABASE` now has a `tags` field
(`list[str]`). The taxonomy covers 21 tags across all 45 rules:
`formatting`, `syntax`, `encoding`, `io`, `variables`, `state`,
`rollback`, `deprecated`, `types`, `init-order`, `python`, `screen`,
`ui`, `performance`, `arguments`, `dialogue`, `text-tags`, `colors`,
`flow`, `labels`, `branching`, `menu`, `dead-code`, `assets`, `audio`,
`images`, `translations`, `transforms`.

Examples:

| Rule  | Tags                                      |
|-------|-------------------------------------------|
| RPY104 | `variables`, `state`, `rollback`         |
| RPY107 | `deprecated`                              |
| RPY205 | `screen`, `performance`                   |
| RPY501 | `assets`, `audio`                         |
| RPY701 | `dead-code`, `variables`                  |

`show_rules_table()` (the `senpy --rules` view) now includes a Tags
column. `show_rule_detail()` (`senpy --rule CODE`) lists the tags in
the panel header.

**`senpy rule` subcommand.** Browse rule metadata without running
the analyzer:

```bash
senpy rule list                              # text table of all rules
senpy rule list --format json                # machine-readable
senpy rule list --tag rollback               # filter by tag (union)
senpy rule list --tag audio --tag images     # multiple tags = union
senpy rule list --severity ERROR             # filter by severity
senpy rule list -o rules.json                # write to file
senpy rule show RPY104                       # detail (text)
senpy rule show RPY104 --format json         # detail (JSON)
senpy rule show rpy104                       # case-insensitive
```

JSON output adds a `code` field to each entry (in `RULES_DATABASE`
the code is the dict key, not a value — JSON consumers need it as a
field to sort/group programmatically). The existing `--rules` and
`--rule CODE` flags on the main CLI continue to work as aliases.

**`--tag` / `--ignore-tag` CLI filters for lint mode.** Two new flags:

```bash
senpy game/ --tag rollback state             # run only rollback+state rules
senpy game/ --ignore-tag dead-code           # silence all dead-code rules
senpy game/ --tag variables --ignore-tag rollback   # combine
```

Tag matching is case-insensitive; a rule passes `--tag` if ANY of
its tags is in the requested list. Rules missing from
`RULES_DATABASE` (e.g. plugin rules with unknown codes) are dropped
by `--tag` (conservative — they have no tags to match) but kept by
default.

### Strict mode — `strict = true` config field is now enforced

The `strict` field on `SenpyConfig` has been documented as "all rules
= ERROR" since 0.6.0 (`ARCHITECTURE.md:424`) but was never actually
read by the analyzer. This release closes that gap.

```toml
# senpy.toml
[senpy]
strict = true
```

With `strict = true`, every diagnostic whose code is NOT explicitly
overridden in `[tool.senpy.severity]` is promoted to `ERROR`.
Explicit severity overrides have priority — otherwise strict mode
would silently re-promote a rule the user explicitly demoted, making
strict unusable for projects with one or two noisy rules.

`strict = false` (default) → no behaviour change.

### Formatter — `FMT-STRING-CONSISTENCY` (7th formatter rule)

Normalizes the outer quotes of single-line string literals in CODE
lines to a consistent style. Default: `'hi'` → `"hi"` (Ren'Py
convention).

```python
# senpy.toml or via FormatConfig
[tool.senpy.formatter]  # future section; currently FormatConfig field
string_style = "double"  # default | "single" | "preserve"
```

NOT touched (intentional non-goals):

* Dialogue lines (first non-whitespace char is `'` or `"`) — Ren'Py
  dialogue convention is independent of code style.
* Triple-quoted strings — too easy to break.
* Strings where conversion would require escaping the new outer
  quote inside the body (e.g. `'he said "hi"'` is left alone —
  converting would require escaping the inner `"`, breaking
  idempotency).
* Skip blocks (`# senpy: format off`).

Rule order in `senpy/formatter/rules/__init__.py`: indent →
blank-lines → trailing-ws → quotes → op-spacing → comma-spacing →
colon-spacing → **string-consistency** → eof-newline (last).

### Tests

* **1173 tests pass** (up from 1036 in 0.7.3, +84 from 0.7.4 inspect;
  +137 total this release). New test files:
  - `tests/test_inspect.py` (27): assertion-based + size invariants
    on the JSON structure. Verifies `stats.labels ==
    len(data.labels)`, every broken-jump target is NOT in labels,
    every unreferenced label IS in labels, JSON is serializable (no
    sets, no tuples).
  - `tests/test_inspect_cli.py` (18): subcommand parsing, all 4
    shortcut flags, `--no-cache`, `--with-source`, `--output-file`,
    `--decompile`, dispatch routing, plus regression tests for the
    `config['decompile']` and `interactive=False` determinism.
  - `tests/test_discover.py` (8): `interactive=False` suppresses
    prompt on TTY, `interactive=True` preserves prompt behavior,
    explicit `--decompile` and `config['decompile']` still honored
    when `interactive=False`, module importable without circular
    dependency.
  - `tests/test_strict_mode.py` (4): `strict=true` promotes
    WARNING/HINT to ERROR, `strict=false` preserves defaults,
    explicit severity overrides win over strict, default-when-absent.
  - `tests/test_rdjson.py` (13): NDJSON structure, severity mapping,
    1-based columns, code.url for known/unknown rules, unicode
    preservation, newline-in-message escaping, path fallback.
  - `tests/test_gitlab.py` (17): JSON array structure, field
    mapping, severity mapping, fingerprint stability/uniqueness,
    fingerprint algorithm pinning (md5 of code|path|line|message),
    unicode and quote escaping.
  - `tests/test_rule_cli.py` (19): `senpy rule list` (text/json,
    `--tag`, `--severity`, `-o`), `senpy rule show` (text/json,
    unknown code, case-insensitive), `--help`, no-subcommand.
  - Plus 7 new `--tag` / `--ignore-tag` tests in
    `tests/test_cli_select_ignore.py` and 12 new
    `FMT-STRING-CONSISTENCY` tests in
    `tests/test_formatter_idempotency.py::TestStringConsistency`,
    and 11 new `render_rdjson`/`render_gitlab` tests in
    `tests/test_render_formats.py`. Four characterization tests in
    `tests/test_0_6_0_subprint.py` updated to reflect the new
    string-consistency behaviour (string content preserved; only
    outer quotes change).
* Ruff check clean. 0 import cycles across 86 modules
  (+6 new: `senpy/cli/discover.py`, `senpy/cli/inspect_dispatch.py`,
  `senpy/cli/rule_dispatch.py`, `senpy/formats/inspect.py`,
  `senpy/formats/rdjson.py`, `senpy/formats/gitlab.py`,
  `senpy/formatter/rules/string_consistency.py` — counted as +6
  because `discover.py` + `inspect_dispatch.py` + `inspect.py` were
  already in 0.7.4-sprint earlier commits; this changelog entry
  covers the whole 0.7.4 release).
* Coverage stable.

<a id="073"></a>
[up](#up)

## [0.7.3] — Plugin trust UX, English-only codebase, expanded badges

Patch release: three independent threads. Plugin trust management
becomes scriptable (no more `input()` hang in LSP mode), the `senpy/`
source tree is now English-only comments, and the dynamic badge set
grows from 1 to 5. No new rules, no new LSP handlers, no public API
changes. All 1036 tests pass, ruff check clean, 0 import cycles.

### Plugins — non-interactive trust management

The 0.6.0 trust-on-first-use model called `input()` on first load.
This breaks in two scenarios: LSP mode (`senpy --lsp` — stdio is the
JSON-RPC transport, not a TTY; `input()` would hang the server
silently) and CI/piped stdin (the existing non-TTY fail-safe declines
without any trace of why the plugin was skipped).

Both fixed by two complementary changes:

* **`_default_trust_callback` in `senpy/plugins/loader.py`** detects
  LSP mode by checking `"--lsp" in sys.argv` and declines untrusted
  plugins without prompting — a `_logger.warning` points the user at
  `senpy --trust-plugin NAME`. Non-TTY (CI, piped stdin) keeps the
  existing fail-safe decline. The trust-store lookup at the top of
  the callback still short-circuits to `True` for pre-trusted
  plugins, so a one-time trust is enough for both CLI and LSP.

* **`--trust-plugin NAME` / `--untrust-plugin NAME` CLI flags** in
  `senpy/cli/main.py` write to `~/.senpy/trusted_plugins.json` and
  `sys.exit(0)` without running the analyzer. Trust management is
  now fully scriptable. `--untrust-plugin` exits 0 even if the
  plugin was not in the store, so it is safe to call from scripts
  that don't track trust state.

### Codebase hygiene — English-only comments (CLEAN-2)

All Russian comments and docstrings in `senpy/` translated to
English in a single mechanical pass: **52 files, ~1057 lines
changed** (additions = removals, no logic changes — only `# …`
comments and `"""…"""` docstring contents; no code, no string
literals, no semantics). `senpy/domain/tsundere.py` (easter-egg
mode, intentionally Russian) and `senpy/vendor/` (vendored unrpyc)
are whitelisted and skipped. Reviewers can verify no executable
line changed by filtering the patch on `^-[^-]` / `^\+[^+]`.

### Tests — guards against regression

* **`tests/test_no_russian_comments.py`** (new): scans every `.py`
  file in `senpy/` (excluding `vendor/` and `tsundere.py`) for
  Cyrillic characters (`[а-яА-ЯёЁ]`) inside `#` comments or `"""`
  docstrings. A simple state machine tracks triple-quote nesting;
  string literals in code are intentionally not flagged. On
  violation the test fails with a list of `file:line: content`
  (truncated to 120 chars per line) so the regression can be
  translated in one pass. Modeled after the CLEAN-1 guard from 0.7.1.

* **`tests/test_clean_internal_ids.py`** (new, 13 cases across 3
  classes): unit and integration tests for
  `scripts/clean_internal_ids.py` (added in 0.7.1 as a pre-commit
  hook, but with no test coverage at the time). Covers the four
  cleanup strategies (comment prefix, mid-sentence mention,
  string-literal ID, commit-message prefix), the three CLI modes
  (`--dry-run`, `--apply`, `--paths`), and the whitelist
  (`CHANGELOG.md`, worklog, `senpy/vendor/**`). The script's
  contract is now locked in.

### CI / DX — dynamic badge expansion

The 0.7.1 release shipped one dynamic badge (tests). This release
grows the set to **five**, all auto-updated by the existing
`update-badges` CI job on every push to `main`:

| Badge | Source | Color |
|---|---|---|
| `tests` | pytest collect/run | brightgreen (all pass), yellow (skipped), red (failed) |
| `rules` | `len(RULES_DATABASE)` | orange |
| `LSP` | public functions in `senpy/lsp/handlers/*.py` (via `ast`) | purple |
| `coverage` | `pytest --cov` TOTAL % | brightgreen ≥80 %, yellow ≥60 %, red otherwise |
| `speed` | synthetic ~20K-line .rpy benchmark, cold + warm | brightgreen <0.1 s warm, green <1 s, yellow otherwise |

`scripts/update_badges.py` gained three new builders
(`_build_rules_badge`, `_build_lsp_badge`, `_build_speed_badge`).
The speed builder generates a deterministic
(`random.seed(42)`) synthetic VN project — 6 characters, 200
labels of ~100 lines each, 6 menus, with `show/scene/jump/menu/audio`
commands mirroring real VN projects (not thousands of
`define`/`transform` in one file) — and runs `SenpyAnalyzer` cold
+ warm, reporting both times in the badge message. The LSP builder
parses each handler file with `ast` and counts public `FunctionDef`
nodes (27 as of this release), robustly skipping malformed files.
The `update-badges` CI job auto-commits all five JSON files back to
`main` with `[skip ci]` to avoid a loop; README badges are
shields.io `endpoint?url=…` pointing at raw JSON on `main`.

### READMEs

Both `README.md` and `README_ru.md` now display all five dynamic
badges plus the existing static ones (Python, Ren'Py, License,
Platform, Plugin API, CI status). Previous README had only tests +
CI + external Codecov. The new block gives a one-glance view of
project health: rule count, LSP handler count, coverage, cold/warm
analysis speed on a 20K-line project.

### Tests

* **1036 tests pass** (up from 1035 in 0.7.2). The +1 is the
  CLEAN-2 guard; the 13 CLEAN-1 cases also land in this release.
* Ruff check clean. Ruff format check non-blocking (Windows CRLF,
  unchanged from 0.7.1).
* 0 import cycles across 79 modules (no new modules this release).
* Coverage **80.9 %** (up from 80.76 % in 0.7.1), without
  `senpy/vendor/`. Bump comes from the new tests.

### Internal

No public APIs changed, no plugin API changes. The CLEAN-1
pre-commit hook and the new CLEAN-2 guard test together enforce the
two codebase-hygiene invariants going forward: no internal task
IDs in user-facing files, no Russian text in comments or
docstrings. Both are now machine-checked.

<a id="072"></a>
[up](#up)

## [0.7.2] — God-function splitting, DRY cleanup

No new rules, no new LSP handlers, no user-visible behavior changes.
The entire release is internal refactoring: splitting 12 god-functions
into small, testable helpers and extracting 4 shared DRY utilities.

### Architecture — god-function splitting

12 functions (188–111 lines each) were split into dispatchers (≤30–59 lines)
delegating to focused helpers. All 1035 tests pass, ruff clean, 0 import
cycles. Public APIs unchanged — plugins and external code are not affected.

**LSP handlers** (5): `hover`, `definition`, `completions`, `signature_help`,
`document_symbols` — each now a short dispatcher with per-symbol-type helpers.

**Rule checkers** (4): `_check_show_scene` (the largest, 188→30),
`_check_audio_statement` (174→21), `check_screen_mutation` (114→34),
`MermaidBuilder.build` (132→18) — tag matching, audio validation, screen
mutation detection, and Mermaid graph generation are now separate helpers.

**Core** (3): `_analyze_file` (122→59), `process_quoted_strings` (187→58),
`collect_story_stats` (83→19) — the main per-file analysis loop, dialogue
string tag matching, and story statistics collection.

### Architecture — DRY utilities

4 shared utilities extracted to eliminate code duplication:

* `SUGGESTION_CUTOFF` constant in `core/constants.py` — 11 hardcoded `0.6`
  values now reference a single constant.
* `suggest_similar()` / `suggest_match()` in `text_utils.py` — generalized
  from `suggest_similar_symbol`, accepts any iterable, parameterized cutoff.
* `normalize_path()` in `core/paths.py` (new module) — replaces 8 inline
  `os.path.normcase(os.path.abspath(...))` copies across 5 files.
* `progress_print()` in `core/progress.py` (new module) — replaces 4 inline
  `print(msg.ljust(75)...)` copies across 2 files.

### Architecture — thin-wrapper cleanup

Removed 3 thin-wrapper methods from `SenpyAnalyzer` that were left over
from the 0.6.6 extract refactoring. Callers now import the actual functions
from `senpy.rules.dead_code` and `senpy.rules.checkers.translation` directly.
`_parse_tl_pairs` kept as a deprecated `@staticmethod` for backward compat.

### Remaining god-functions

14 functions ≥80 lines remain. They are either mechanical code (argparse
setup, symbol collection loops), complex logic requiring SSA for a
meaningful split, or LSP handlers at exactly 80 lines. Deferred to 0.8.0
(SSA + SymbolRegistry) or 0.7.3 (LSP handlers).

### Tests

* 1035 tests pass (unchanged from 0.7.1).
* Ruff check clean. Ruff format check non-blocking (Windows CRLF issue).
* 0 import cycles across 79 modules (+2 new: `core/paths.py`, `core/progress.py`).

<a id="071"></a>
[up](#up)

## [0.7.1] — Stabilization, dynamic badges, CONTRIBUTING refresh

Stabilization release: no user-visible behavior changes, no new rules,
no new LSP handlers. The focus is on documentation accuracy, CI feedback
loops, contributor onboarding, and removal of stale code paths that
caused real bugs.

### Bug fixes (LSP)

* **Fix: `textDocument/completion` and `textDocument/codeAction` crashed
  with `AttributeError: 'LanguageServer' object has no attribute
  'show_message_log'`**. The `pygls~=2.1` migration in 0.6.x removed
  `LanguageServer.show_message_log` (replaced by `window_log_message`),
  but 6 call sites in `senpy/lsp/handlers/completion.py` (5 sites) and
  `senpy/lsp/handlers/diagnostics.py` (1 site) were still calling the
  removed API. Every `textDocument/completion` request and every
  `codeAction` request would crash the handler and emit a traceback to
  the VS Code "Senpy Language Server" output panel. Replaced all 6
  call sites with `_logger.debug(...)` / `_logger.warning(...)` (lazy
  formatting) via `senpy.core.logging`. This was the root cause of the
  "VSIX works in release but crashes when built via dev scripts" reports
  — the bundled `senpy.exe` had the same bug, but VS Code was hiding the
  crash for some API versions while showing it for others.
* **Fix: `build_exe.bat` produced a binary that silently exited with
  code 0 and no output**. `build_exe.bat` used `senpy\cli\__init__.py`
  as the PyInstaller entry point, but that file only does
  `from senpy.cli.main import main` — it never calls `main()`. The
  resulting `senpy.exe` would start, import senpy, exit immediately,
  and VS Code would restart the language server in a tight loop. The
  correct entry point is `senpy\cli\__main__.py` (which has
  `if __name__ == "__main__": sys.exit(main())`). Removed the stale
  `build_exe.bat` and `build_vsix_dev.bat` scripts; `senpy-vscode/reinstall.bat`
  is now the only local-build path and uses the correct entry point plus
  `--collect-all senpy` to bundle every submodule (including the
  dynamically-imported `senpy.lsp.handlers.*` and 0.7.0 additions like
  `senpy.domain.image_size` and `senpy.domain.renpy_api_generated`).

### Architecture

* **Removed global `warnings.filterwarnings("ignore", category=SyntaxWarning)`
  from module level** in `senpy/core/analyzer.py` and `senpy/lsp/server.py`.
  This call was added in commit 63ad210 (2026-10-22, "decompose monolithic
  analyzer into checker pipeline") and was a global side-effect on import:
  any host process that did `import senpy` or `import senpy.api` would
  silently lose all `SyntaxWarning`s for the entire process. This is bad
  for a library published on PyPI — it pollutes the host's warning
  configuration. Investigation (running all 1035 tests with
  `-W error::SyntaxWarning`) confirmed Senpy does not trigger
  `SyntaxWarning` anywhere in normal operation. The filter was unnecessary
  defense against a problem that no longer exists; removed entirely along
  with the corresponding `E402` per-file-ignores in `pyproject.toml`.

### CI / DX

* **Dynamic test-count badge**: README badges for tests, CI status, and
  coverage are now live. The static `tests-689 passed` badge is replaced
  by a shields.io `endpoint?url=...` badge that reads
  `.github/badges/tests.json` from the `main` branch. A new `update-badges`
  CI job (in `ci.yml`) runs after `test` + `build-check` on every push to
  `main`, executes `scripts/update_badges.py --run` to count tests, and
  auto-commits the updated JSON back to `main` with `[skip ci]` to avoid
  a loop. README badges (`README.md` and `README_ru.md`) for CI status
  (`github/actions/workflow/status`) and coverage (`codecov/c/github/...`)
  added as well. Coverage upload via `codecov-action@v4` now uses
  `disable_search: true` for a faster, deterministic upload.
* **`scripts/update_badges.py`**: idempotent JSON badge generator.
  Two modes: collect-only (default, fast — ~1–2s, used as pre-commit
  hook if desired) and `--run` (full pytest, ~30s, used in CI). Color
  logic: brightgreen when all collected tests passed, yellow when
  some skipped or pass < collected, red when 0 passed or pytest failed
  to collect. `--check` mode exits 1 if the badge file would change
  (for CI guard mode, future use).
* **Pre-commit hooks tightened**: `.pre-commit-config.yaml` updated
  to use `ruff` (lint, with `--fix`) and `ruff-format` for Python
  formatting. The `trailing-whitespace` and `end-of-file-fixer` hooks
  now exclude `*.md` files (editors like VS Code routinely add trailing
  whitespace to markdown tables, fixing on every commit was noise).
  Custom `clean-internal-ids` hook (CLEAN-1) continues to catch
  leaks of internal task IDs (DOC-1, CLI-17, etc.) before they reach
  the repo.

### Documentation

* **README.md / README_ru.md "What's New" section rewritten**: the
  old single-subsection `## What's New in 0.6.0` is now
  `## What's New` with two subsections — `### 0.7.0` (Image/Audio/Video
  hover, auto-generated Ren'Py API docs, TextMate grammar, orphaned
  video detection) and `### 0.6.0` (Plugin system, LSP killer-features
  from 0.6.0). The previous README was misleading users into thinking
  the latest version was 0.6.0.
* **Plugin example unified**: the README "Write your own rule in 30
  lines" example used a fictional `RPY902` `TodoCommentRule` that did
  not exist anywhere in the repo. The actual example in
  `examples/my_senpy_plugin/` is `RPY901` `HardcodedDialogueRule`.
  README now uses the real example, so users can copy-paste a working
  rule. Both `README.md` and `README_ru.md` updated.
* **ARCHITECTURE.md test count updated**: was "898 tests across 65 test
  files (~15,700 lines)", now "1035 tests across 69 test files
  (~17,800 lines)".
* **SECURITY.md test references fixed**: was pointing to a non-existent
  `tests/test_aud_001_security.py` (a leftover from an internal audit
  task that was renamed). Replaced with the real test files:
  `tests/test_cache_security.py`, `tests/test_lsp_uri_security.py`,
  `tests/test_unrpyc_security.py`, `tests/test_vendored_unrpyc.py`.
* **CONTRIBUTING.md expanded** with two new sections:
  - **"Good first issues"**: a concrete table of 10 lint rules that lack
    fixture tests (RPY201, 202, 203, 205, 301, 401, 403, 404, 502, 505),
    plus doc fixes and example .rpy files as low-risk contributions.
  - **"Solo-maintainer expectations"**: explicit review-time SLAs (1 week
    for bug reports, 1–2 weeks for small PRs, 2–4 weeks for large PRs),
    what gets merged fast vs. what gets rejected, and explicit
    encouragement to write domain-specific checks as plugins rather
    than core rules (the plugin system is the delegation path for a
    one-maintainer project).
  The "How to add a new lint rule" section now opens with a callout
  block recommending the plugin route for project-specific rules.
  Code of Conduct expanded with "Be patient with review", "Don't aim
  for perfect — aim for shipped", and "Don't be precious about your
  code" guidance.

### Tests

* **1035 tests pass** (up from 1010 in 0.7.0). All green on Python
  3.11 / 3.12 / 3.13 across Ubuntu, Windows, and macOS (3.12 only).
* Verified with `-W error::SyntaxWarning` (treating warnings as errors)
  — no `SyntaxWarning` is raised anywhere in the test suite, confirming
  the `warnings.filterwarnings` removal was safe.
* Coverage remains at ~81% (without `senpy/vendor/`).

### Internal cleanup

* `build_exe.bat` and `build_vsix_dev.bat` deleted from the repo root.
  These were the source of the "silent binary exit" bug above. The
  working replacement is `senpy-vscode/reinstall.bat` (which uses the
  correct PyInstaller entry point and `--collect-all senpy`).
* `pyproject.toml`: added `N802` (function name should be lowercase)
  and `UP038` (isinstance tuple → `X | Y`) to the `ignore` list. `N802`
  would fire on `ast.NodeVisitor.visit_*` methods (e.g. `visit_If`,
  `visit_ImportFrom`) which are part of the Python AST visitor API and
  cannot be renamed. `UP038` is a deprecated ruff rule (already removed
  in ruff 0.16+) but kept in `ignore` for compatibility with contributors
  running older ruff versions.

### Known issues / not closed in this release

* **`ruff format --check` in CI is non-blocking** (`continue-on-error:
  true`). The blocking step caused an infinite loop on Windows due to
  CRLF ↔ LF conflicts (`pyproject.toml` says `line-ending = "lf"`, but
  git on Windows with default `core.autocrlf` converts to CRLF in the
  working tree, and the `ruff-format` pre-commit hook reformatting every
  commit triggered the cycle). To make this blocking safely, add a
  `.gitattributes` file with `* text=auto eol=lf` first. Tracked as a
  follow-up; not blocking for 0.7.1.

<a id="070"></a>
[up](#up)

## [0.7.0] — renpy-magic-inspired features

This release (for a long time) with user-visible features sourced from competitive analysis
of [renpy-magic](https://github.com/adiffx/renpy-magic) (MIT, Copyright (c)
2026 Allure Diffusion). After this release, Senpy matches or exceeds
renpy-magic on every dimension the analysis identified — and remains ahead
on rules (45+ vs 5), dataflow, caching, plugins, and CLI.

### VS Code extension

* **TextMate grammar for `.rpy`/`.rpym`**: 270-line grammar with
  scope `source.renpy`, copied verbatim from renpy-magic (MIT). Covers
  comments, strings, Ren'Py-specific text-tag `{…}` and interpolation `[…]`
  escapes, `python`/`init python` blocks with indent-backreference end
  pattern, `$`-prefixed python lines, labels, screens, transforms, image
  definitions, say statements, numbers, operators, and built-in
  classes/actions. Wired into `senpy-vscode/package.json` via
  `contributes.grammars`. MIT attribution in
  `senpy-vscode/THIRD_PARTY_NOTICES.md` (ships in VSIX via `.vscodeignore`
  exception).

### LSP — hover preview

* **Image hover**: hover over `show sayori happy` or
  `scene bg forest` to see an inline preview of the referenced sprite or
  CG, with size metadata. Image dimensions are read by a hand-rolled
  PNG/JPEG/WEBP (VP8/VP8L/VP8X)/GIF/BMP header parser
  (`senpy/domain/image_size.py`, 190 LOC) — no Pillow dependency. Hover
  clamps to a 400×200 bounding box, preserving aspect ratio.
* **Audio hover**: hover over
  `play music bgm_calm` / `queue sound click` / `define audio.X = "..."`
  to get a Play audio link that opens VS Code's built-in media viewer.
  Aliases (`define audio.X = "f.ogg"`) are resolved at index time, not
  per-hover (avoids renpy-magic's source-file re-read anti-pattern).
* **Video hover**: when an image declaration
  or auto-discovered file has a video extension (`.mp4`, `.webm`, `.ogv`,
  `.avi`, `.mkv`), hover shows a "Play in default app" link via a new
  `senpy.openExternal` VS Code command (VS Code's image viewer cannot
  decode these formats).

### LSP — API documentation

* **Auto-generated Ren'Py API docs**: 754 entries auto-fetched
  from Ren'Py 8.5.3 RST sources (`scripts/fetch_renpy_docs.py`, Python
  port of renpy-magic's `fetch-renpy-docs.ts`). Covers `config.*` (304),
  `gui.*` (107), `build.*` (19), `renpy.*` (13), style/transform
  properties (163), classes (5), functions (7). Combined with the 221
  curated entries, `RENPY_API_DOCS_ALL` has **975 symbols** — a 4.4×
  increase. Curated entries win on key collision (they have examples +
  verified URLs the generated data lacks). The merge happens at import
  time, ~5ms one-time cost.

### Architecture

* `ImageSymbol.image_path: str | None` field — extracted at parse time
  from `image name = "path"` or `Transform("path", ...)` declarations so
  hover does not have to re-read source files.
* `AssetManager.image_name_to_path` / `audio_name_to_path` maps plus
  `resolve_image_path` / `resolve_audio_path` / `is_video_file` /
  `register_audio_alias` methods — mirror Ren'Py's image auto-discovery
  (`images/foo/bar.png` → keys `"foo bar"` and `"foo_bar"`).
* `MEDIA_EXTENSIONS` extended with `.mp4`/`.avi`/`.mkv` — RPY503
  (unused-asset check) now also flags orphaned video files.
* New modules: `senpy/domain/image_size.py` (190 LOC),
  `senpy/lsp/handlers/asset_hover.py` (252 LOC),
  `senpy/domain/renpy_api_generated.py` (4890 LOC, 754 entries).

### Tests

* 1010 (!) tests pass, 0 regressions. Ruff clean on all touched files.
* `test_lsp_asset_hover.py` (44 tests): image-size parser unit
  tests, clamp-to-hover-box aspect tests, `_extract_string_literal` edge
  cases, image/audio/video hover integration, regression tests for
  existing variable/label/API hover.
* `test_lsp_21_api_docs.py` (68 tests): RST directive regex
  unit tests, `collect_description` edge cases, end-to-end RST parsing,
  `.rpy` action-source parsing, serializer output, generated-module
  sanity, merge logic (curated wins on collision), hover integration,
  backward compat.

<a id="066"></a>
[up](#up)

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

<a id="065"></a>
[up](#up)

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

<a id="064"></a>
[up](#up)

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

<a id="063"></a>
[up](#up)

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

<a id="062"></a>
[up](#up)

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

<a id="061"></a>
[up](#up)

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

<a id="060"></a>
[up](#up)

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

<a id="058"></a>
[up](#up)

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

<a id="057"></a>
[up](#up)

## [0.5.7]

### Changed
* **Разбиты 3 god-функции:**
  * `rules/checkers/asset.py:AssetChecker.check_line` (352 → 23 строки dispatcher): извлечены `_check_show_scene()` (RPY502: show/scene/ATL/transitions) и `_check_audio_statement()` (RPY501/RPY505: play/queue/stop)
  * `rules/flow.py:StoryFlowAnalyzer.analyze_menu_flow` (151 → 25 строк dispatcher): извлечены `_parse_menu_choices()`, `_analyze_choice_body()`, `_merge_menu_branches()`
  * `rules/flow.py:StoryFlowAnalyzer.generate_mermaid_graph` (133 → 8 строк dispatcher): вынесен в модульный класс `MermaidBuilder` (`build()` метод). Тонкий диспетчер сохранён для обратной совместимости (`core/analyzer.py:1559` вызывает `self.flow.generate_mermaid_graph()`)

### Notes
* Это минорный рефакторинг-релиз: поведение неизменно, 497 тестов зелёные.

<a id="056"></a>
[up](#up)

## [0.5.6]

### Changed
* **Разбиты 3 god-функции (Phase 3):**
  * `cli/main.py:main()` (719 → 220 строк): извлечены `parse_args()`, `filter_diagnostics()`, `render_sarif()`, `render_json()`, `render_text()`, `discover_files()`
  * `rules/python_ast.py:_walk_python_nodes` (479 → 30 строк dispatcher): извлечены 8 `_visit_*` методов
  * `core/analyzer.py:_collect_symbols` (378 → 80 строк dispatcher): извлечены 7 `_collect_*` методов

### Fixed
* `_collect_screen_transform`: early return делал transform-обработку dead code (исправлено)
* `current_screen` context не сбрасывался для non-screen top-level строк (исправлено)

<a id="055"></a>
[up](#up)

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

<a id="054"></a>
[up](#up)

## [0.5.4] ⚠️ YANKED

> **Важно:** Этот релиз был опубликован на PyPI и сразу же отозван (*yanked*). Версия содержит критическую ошибку сборки. **Не используйте её в проектах.**

### Причина отзыва
Шаг `publish-pypi` в CI/CD выполнился успешно, но последующий шаг `build-vsix` завершился ошибкой.

В рамках реструктуризации в версии 0.5.4 файл `senpy/cli.py` был перенесен в `senpy/cli/main.py`. Однако конфигурационный файл `senpy.spec` для PyInstaller не был обновлен и продолжал ссылаться на старый путь, из-за чего сборка артефакта упала.

Поскольку PyPI иммутабелен (неизменяем), опубликованный релиз 0.5.4 нельзя перезаписать или удалить — его можно было только пометить как **yanked**.

<a id="053"></a>
[up](#up)

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
  - `analyzer ↔ cli` (Фаза 1.2 — `load_config` → `senpy/config.py`)
  - `analyzer ↔ checkers` (Фаза 1.3 — `DiagnosticSink` Protocol + `_strip_comment` → `text_utils.py`)
  - `analyzer ↔ python_ast` (Фаза 1.4 — `DiagnosticSink` Protocol)
  - `analyzer ↔ flow` (Фаза 1.5 — `DiagnosticSink` Protocol)
  - `analyzer ↔ cache` (Фаза 1.6 — `cache_manifest.py` extraction)
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

<a id="052"></a>
[up](#up)

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

<a id="051"></a>
[up](#up)

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

<a id="050"></a>
[up](#up)

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

<a id="048"></a>
[up](#up)

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

<a id="047"></a>
[up](#up)

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
