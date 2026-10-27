# Changelog

All notable changes to Senpy are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.4.8]: https://github.com/Xilleet/senpy/compare/v0.4.7...HEAD
[0.4.7]: https://github.com/Xilleet/senpy/releases/tag/v0.4.7
