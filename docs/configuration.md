---
title: Senpy Configuration — senpy.toml, .senpy-ignore, Severity Overrides, Tag Filters
description: Configure Senpy with senpy.toml — set rule severities, ignore noisy rules, enable strict mode, override severities per rule. Use .senpy-ignore for project-level bulk exclusions and CLI flags (--select, --tag, --ignore-tag) for one-off runs.
tags:
  - configuration
  - reference
---

# Configuration

Senpy is configurable through three layers:

1. **`senpy.toml`** — project-level config, sits next to your
   `game/` directory.
2. **`.senpy-ignore`** — bulk rule exclusion file (one rule code per
   line).
3. **CLI flags** — `--select`, `--ignore`, `--tag`, `--ignore-tag`,
   `--strict`, and more — for one-off runs or CI overrides.

Layers compose: CLI flags override `senpy.toml`, which overrides
defaults. `.senpy-ignore` adds to the `ignore` list in `senpy.toml`.

This page is the canonical reference for all three layers.

---

## `senpy.toml`

The main config file. Place it in your project root (next to
`game/`) — Senpy finds it automatically.

```toml
[tool.senpy]

# =============================================================================
# Scanning & execution
# =============================================================================

# Automatically decompile orphaned .rpyc files into a sandbox without asking.
# Useful when analyzing game distributions or mods without source code.
decompile = true

# Maximum number of detailed error cards to print in the terminal (default: 50).
# Set higher for CI logs; lower for interactive use.
max_errors = 50

# Show informational notices (e.g. unreferenced labels, RPY303) in the terminal.
# INFO-level diagnostics are hidden by default; set to true to see them.
info = false

# Show only critical ERRORs, suppressing WARNINGs and INFO notices.
# Useful for non-blocking CI that only cares about hard errors.
errors_only = false

# Enable tsundere character UI output mode (Easter egg).
# B-Baka! It's not like I want to check your visual novel!
tsundere = false

# Strict mode: every diagnostic whose code is NOT explicitly overridden in
# [tool.senpy.severity] is promoted to ERROR. Use this in CI to fail on
# any new rule Senpy adds.
# Default: false (warnings don't fail CI).
strict = false

# Custom path to unrpyc script or binary (leave commented if using auto-detect).
# unrpyc_path = "tools/unrpyc.py"

# Allow intentional image overrides by mod assets (suppresses RPY504).
# allow_image_overrides = true

# =============================================================================
# Rule suppression & severity
# =============================================================================

# Custom severity overrides for specific rules.
# [tool.senpy.severity]
# RPY104 = "ERROR"   # Elevate dynamic assignments to build-breaking
# RPY308 = "INFO"    # Demote label fallthrough to informational
# RPY701 = "HINT"    # Keep unused defines as hints (not warnings)

# List of diagnostic codes to completely ignore across the whole project.
# ignore = [
#     "RPY303",  # Ignore unreferenced labels (useful if project relies on dynamic routers)
#     "RPY504",  # Ignore image overrides/redefinitions
# ]

# Whitelist (run ONLY these rules). Empty = run all.
# select = []

# Add to the whitelist (only with select).
# extend_select = []

# Add to the blacklist (extends the ignore list above).
# extend_ignore = []
```

### `decompile`

```toml
decompile = true
```

Default: `true`. When Senpy finds an orphaned `.rpyc` file (no
corresponding `.rpy` source), it copies the `.rpyc` into a sandbox
temporary directory, decompiles it using the vendored `unrpyc`
(pinned to a specific commit, SHA256-verified), and analyzes the
decompiled output. Your project directory is never modified.

Set to `false` to skip `.rpyc` files entirely (faster, but misses
content from compiled-only mods).

### `max_errors`

```toml
max_errors = 50
```

Maximum number of detailed diagnostic cards to print in the
terminal. Senpy still counts and totals all diagnostics — this only
affects how many get a full Panel card in the output.

For CI logs, set higher (200+) to see all findings. For interactive
use, keep at 50 to avoid terminal spam.

### `info`

```toml
info = false
```

Default: `false`. INFO-level diagnostics (e.g. `RPY303` unreferenced
labels) are hidden by default. Set to `true` to see them.

Equivalent to the `--info` CLI flag.

### `errors_only`

```toml
errors_only = false
```

Default: `false`. Set to `true` to show only ERROR-level diagnostics,
suppressing WARNINGs and INFOs. Useful for non-blocking CI that only
cares about hard errors.

Equivalent to the `--errors-only` CLI flag.

### `tsundere`

```toml
tsundere = false
```

Easter egg. Set to `true` for tsundere-flavored output messages.
Disabled in CI by default.

### `strict`

```toml
strict = false
```

Default: `false`. When `true`, every diagnostic whose code is **not
explicitly overridden** in `[tool.senpy.severity]` is promoted to
`ERROR`. Explicit severity overrides win over strict.

Use this in CI to fail on any new rule Senpy adds — your project
opts into "any new rule is a build-breaking error" semantics, with
the option to downgrade specific rules you don't care about.

```toml
[tool.senpy]
strict = true

[tool.senpy.severity]
# Downgrade rules you don't care about — these override strict.
RPY303 = "INFO"     # unreferenced labels are noise
RPY701 = "HINT"     # unused defines are not build-breaking
RPY702 = "HINT"
RPY703 = "HINT"
```

With this config, every rule is ERROR (strict), except `RPY303`
(INFO), `RPY701` / `RPY702` / `RPY703` (HINT).

### `ignore`

```toml
ignore = [
    "RPY303",  # Ignore unreferenced labels (project uses dynamic routers)
    "RPY504",  # Ignore image overrides/redefinitions (intentional mod assets)
]
```

List of rule codes to completely ignore across the whole project.
Case-insensitive (normalized to uppercase).

### `select` and `extend_select`

```toml
select = ["RPY101", "RPY102", "RPY103"]   # run ONLY these rules
extend_select = ["RPY104"]                 # add to the whitelist
```

`select` whitelists — only the listed rules run, all others are
disabled. `extend_select` adds to the whitelist (only meaningful with
`select`).

Use this for focused audits (e.g. "only run variable checks today").

### `extend_ignore`

```toml
extend_ignore = ["RPY104"]
```

Adds to the `ignore` list. Useful in CI when you want to add a rule
to the blacklist without modifying `senpy.toml`:

```bash
senpy game/ --extend-ignore RPY104
```

### `[tool.senpy.severity]`

Per-rule severity overrides:

```toml
[tool.senpy.severity]
RPY104 = "ERROR"   # Elevate to build-breaking
RPY308 = "INFO"    # Demote fallthrough to info
RPY701 = "HINT"    # Keep unused defines as hints
```

Valid severities:

- `ERROR` — red, build-breaking (exit 1 in CLI)
- `WARNING` — yellow, visible by default
- `INFO` — blue, hidden by default (use `--info` or `info = true`)
- `HINT` — cyan, hidden by default (same as INFO)

---

## `.senpy-ignore`

A simpler alternative to `ignore` in `senpy.toml`. Create a
`.senpy-ignore` file in your project root (next to `senpy.toml`):

```text
# .senpy-ignore — one rule code per line
RPY101  # typo in dialogue variable
RPY104
# RPY105  # commented out — rule will fire
RPY301
```

Format:

- One rule code per line.
- Lines starting with `#` are full-line comments.
- Inline comments (after the rule code) are allowed.
- Codes are case-insensitive (normalized to uppercase).

`.senpy-ignore` adds to the `ignore` list from `senpy.toml`. Use it
when:

- You want rule exclusions in a separate file from main config.
- You want to commit rule exclusions separately from other config
  (e.g. for a "lint baseline" PR).
- You have a long list of exclusions that clutter `senpy.toml`.

---

## CLI flags

CLI flags override `senpy.toml`. Useful for one-off runs and CI
overrides.

### `--config FILE`

```bash
senpy game/ --config /path/to/custom-senpy.toml
```

Use a custom config file instead of the default `senpy.toml` in the
project root. Can also be set via the `SENPY_CONFIG` environment
variable.

### `--show-settings`

```bash
senpy game/ --show-settings
```

Print the resolved configuration (from `senpy.toml` + CLI flags) and
exit. Useful for debugging "which rules are enabled?".

### `--select` and `--extend-select`

```bash
senpy game/ --select RPY101 RPY102 RPY103
senpy game/ --select RPY101 --extend-select RPY104
```

Whitelist — run only the listed rules. `--extend-select` adds to
the whitelist (only with `--select`).

### `--ignore` and `--extend-ignore`

```bash
senpy game/ --ignore RPY303 RPY504
senpy game/ --extend-ignore RPY104
```

Blacklist — skip the listed rules. `--extend-ignore` adds to the
blacklist (extends `senpy.toml`'s `ignore` list and `.senpy-ignore`).

### `--tag TAG [TAG ...]`

```bash
senpy game/ --tag rollback state
```

Run **only** rules with the given tags. Tag matching is
case-insensitive; a rule passes if **any** of its tags is in the
list.

Available tags (28 total, here are the most useful):

| Tag | What it covers |
|---|---|
| `formatting` | RPY001, RPY002 (tabs, smart quotes) |
| `variables` | RPY101, RPY102, RPY103 (variable declarations) |
| `state` | RPY104, RPY105, RPY106 (default/define, mutations, revertable types) |
| `rollback` | RPY105, RPY106 (save/rollback safety) |
| `screen` | RPY201–RPY208 (screen actions, UI prediction) |
| `dialogue` | RPY301, RPY305 (text tags, quotes) |
| `story` | RPY302, RPY303, RPY308, RPY309 (jump/call/labels/fallthrough) |
| `branching` | RPY401–RPY404 (menu asymmetry, MAYBE_SET, contradictions) |
| `assets` | RPY501–RPY503 (audio, images, unused) |
| `audio` | RPY501, RPY505 (audio files, channels) |
| `translations` | RPY601–RPY603, RPY801, RPY802 (translation files) |
| `dead-code` | RPY303, RPY701–RPY707, RPY902 (unused labels/defines/transforms/etc.) |
| `deprecated` | RPY107 (deprecated Ren'Py API) |
| `accessibility` | RPY901 (translation-wrapped dialogue) |
| `productivity` | RPY902 (TODO comments) |

See the full tag list with:

```bash
senpy rule list --format json | python -c "import json,sys; rules=json.load(sys.stdin); print(sorted({t for r in rules for t in r.get('tags',[])}))"
```

### `--ignore-tag TAG [TAG ...]`

```bash
senpy game/ --ignore-tag dead-code
```

Skip rules with the given tags. Useful to silence a whole category
without enumerating individual rule codes.

### `--errors-only`

```bash
senpy game/ --errors-only
```

Show only ERROR-level diagnostics. Equivalent to `errors_only = true`
in `senpy.toml`.

### `--info`

```bash
senpy game/ --info
```

Show INFO-level diagnostics (hidden by default). Equivalent to
`info = true` in `senpy.toml`.

### `--max-errors NUM`

```bash
senpy game/ --max-errors 200
```

Override `max_errors` from `senpy.toml`.

### `--no-cache`

```bash
senpy game/ --no-cache
```

Disable the disk cache (`.senpy_cache/`). Every run does a full
re-analysis. Useful for benchmarking or for CI runs where the cache
isn't persistent.

### `--cache-dir DIR`

```bash
senpy game/ --cache-dir /tmp/senpy-cache
```

Use a custom cache directory instead of `.senpy_cache/` in the
project root. Useful for CI with a shared cache between runs.

### `--clear-cache`

```bash
senpy game/ --clear-cache
```

Clear the project cache directory (`.senpy_cache/`) and exit. Use
this if you suspect the cache is corrupted (rare — the cache uses
BLAKE2b hashes and silently invalidates on mismatch).

### `--respect-gitignore`

```bash
senpy game/ --respect-gitignore
```

Skip files matching patterns in `.gitignore`. Reduces noise in large
repos with vendor directories, build artifacts, etc.

---

## Inline suppression (`# noqa`)

For per-line suppression, add a `# noqa` comment to the offending
line:

```renpy
"Warning: {b}unclosed style"  # noqa
$ dynamic_var = 1             # noqa: RPY104
```

`# noqa` (no rule code) suppresses **all** rules on that line.
`# noqa: RPY104` suppresses only `RPY104`.

### `--add-noqa` (bulk suppress)

```bash
senpy game/ --add-noqa
```

Automatically adds `# noqa` comments to all fixable diagnostics.
Useful for suppressing existing noise without fixing it (then
enforce `noqa` discipline for new code).

---

## Worked example: strict CI config

This is a typical "strict CI" config for a visual novel project that
wants to fail the build on any new rule Senpy adds, but downgrades
cosmetic rules to non-blocking:

```toml
# senpy.toml
[tool.senpy]
strict = true                # all rules are ERROR unless overridden
decompile = true
max_errors = 200             # CI logs can be longer
info = false
errors_only = false

[tool.senpy.severity]
# Cosmetic / housekeeping rules — downgrade to HINT (won't fail CI).
RPY303 = "HINT"   # unreferenced labels
RPY701 = "HINT"   # unused define
RPY702 = "HINT"   # unused transform
RPY703 = "HINT"   # unused screen
RPY704 = "HINT"   # unused default
RPY705 = "HINT"   # unused screen parameter
RPY706 = "HINT"   # unused transform parameter
RPY707 = "HINT"   # unused audio channel
RPY801 = "WARNING"   # duplicate translation (not blocking, but worth fixing)
RPY802 = "WARNING"   # inconsistent translation

# Rules to ignore entirely.
ignore = [
    "RPY100",  # UTF-8 encoding — we have legacy files in Windows-1251
]
```

CI workflow:

```yaml
- run: pip install senpy-linter
- run: senpy game/ --output-format sarif --output-file senpy.sarif
  continue-on-error: true
- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: senpy.sarif
- run: senpy game/   # blocking — fails CI on ERROR
```

The first run produces SARIF for Code Scanning (so you see all
findings). The second run actually fails the build on ERROR-level
diagnostics.

---

## What's next?

- [**CLI reference**](cli-reference.md) — every flag and subcommand.
- [**All 51 rules**](rules/index.md) — to choose which rules to
  enable / disable / downgrade.
- [**Ren'Py GitHub Actions**](renpy-github-actions.md) — wire this
  config into a CI workflow.
