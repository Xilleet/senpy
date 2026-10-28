# Changelog

All notable changes to Senpy are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.2] — 2026-10-28

### Added
- **`tests/test_packaging.py`** (459 строк, 46 регрессионных тестов):
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

## [0.5.1] — 2026-10-28

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

## [0.5.0] — 2026-10-27

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

## [0.4.7] — 2026-10-26

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
