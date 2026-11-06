---
title: Ren'Py GitHub Actions — Run Senpy in CI with SARIF, JUnit, GitLab, and Reviewdog
description: Run Senpy in GitHub Actions to lint your Ren'Py visual novel on every PR. Generate SARIF for GitHub Code Scanning, JUnit XML for Jenkins, GitLab Code Quality JSON for MR annotations, or Reviewdog NDJSON for reviewdog. One-click workflow generator via `senpy --init-ci`. No Ren'Py SDK needed — `pip install senpy-linter` is enough.
tags:
  - ci
  - github-actions
  - sarif
  - cluster-f
---

# Ren'Py GitHub Actions

Run Senpy in **GitHub Actions** to lint your Ren'Py visual novel on
every pull request. Senpy is purpose-built for CI:

- `pip install senpy-linter` is enough — no Ren'Py SDK download, no
  headless Pygame setup, no Windows-specific install.
- 7 output formats, including **SARIF** (GitHub Code Scanning),
  **JUnit XML** (Jenkins / GitLab CI), **GitLab Code Quality JSON**
  (GitLab MR annotations), and **Reviewdog NDJSON** (reviewdog
  integration).
- One-click workflow generator: `senpy --init-ci` writes a
  ready-to-use `.github/workflows/senpy.yml`.

This page covers:

- The one-click workflow generator
- A complete GitHub Actions workflow example
- All 7 output formats and when to use each
- CI-friendly flags (`--check`, `--exit-zero`, `--fail-on-error`)
- Pre-commit hook for local linting

---

## One-click workflow generator

The fastest way to wire Senpy into CI:

```bash
senpy --init-ci
```

This writes `.github/workflows/senpy.yml` in your project with a
ready-to-use workflow:

- Triggers on every pull request to `main` / `master`.
- Runs on `ubuntu-latest`.
- Installs `senpy-linter` via `pip`.
- Runs `senpy game/ --output-format sarif --output-file senpy.sarif`.
- Uploads the SARIF to GitHub Code Scanning via
  `github/codeql-action/upload-sarif@v3`.

Commit the file and you're done. Every PR will run Senpy and surface
findings as GitHub Code Scanning alerts.

You can edit the generated file to:

- Run on more branches
- Pin to a specific Senpy version
- Add Slack / Discord notification
- Upload JUnit XML as a CI artifact

---

## The workflow explained

Here's the workflow `senpy --init-ci` generates, annotated:

```yaml
name: Senpy Code Scanning

on:
  pull_request:
    branches: [ "main", "master" ]

jobs:
  lint:
    runs-on: ubuntu-latest
    permissions:
      security-events: write   # required to upload SARIF to Code Scanning
      contents: read
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - run: pip install senpy-linter

      # Run Senpy. `continue-on-error: true` so the SARIF is uploaded
      # even if Senpy finds errors — you want to see all the findings
      # in the Code Scanning tab, not just the first one.
      - run: senpy game/ --output-format sarif --output-file senpy.sarif
        continue-on-error: true

      # Upload SARIF to GitHub Code Scanning. Findings appear in the
      # "Security" → "Code scanning alerts" tab of your repo, and as
      # inline annotations on the PR diff.
      - uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: senpy.sarif
```

### What this gives you

- **PR annotations** — every Senpy finding shows up as a comment on
  the PR diff at the exact line.
- **Code Scanning tab** — all findings aggregated at
  `https://github.com/<you>/<repo>/security/code-scanning`.
- **Auto-dismiss on fix** — when the next push fixes the finding,
  GitHub auto-closes the alert.
- **Branch protection** — you can require "no new Senpy findings" as
  a status check before merge.

---

## All 7 output formats

Senpy supports 7 output formats, each suited to a different CI
backend:

| Format | Flag | Use case |
|---|---|---|
| `text` | (default) | Human-readable terminal output (cards + summary table) |
| `json` | `--output-format json` | Custom integrations, dashboards, scripts |
| `sarif` | `--output-format sarif` | GitHub Code Scanning, Azure DevOps, SonarQube |
| `junit` | `--output-format junit` | Jenkins, GitLab CI, TeamCity — test result UI |
| `github` | `--output-format github` | GitHub Actions PR annotations (native workflow commands) |
| `rdjson` | `--output-format rdjson` | Reviewdog — `reviewdog -f=rdjson` |
| `gitlab` | `--output-format gitlab` | GitLab Code Quality — MR annotations with fingerprint-stable IDs |

### SARIF (for GitHub Code Scanning)

SARIF 2.1.0 is the industry-standard static analysis format. GitHub
Code Scanning natively ingests it — every Senpy finding becomes a
Code Scanning alert with file, line, rule, severity, and message.

```bash
senpy game/ --output-format sarif --output-file senpy.sarif
```

Then in your workflow:

```yaml
- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: senpy.sarif
```

### GitHub Actions PR annotations (native)

The `github` format emits GitHub workflow commands that GitHub
Actions turns into inline PR annotations:

```bash
senpy game/ --output-format github
```

Output (each line is one annotation):

```
::error file=script.rpy,line=42,col=5::RPY105: Direct mutation of 'define' constant
::warning file=script.rpy,line=58,col=5::RPY104: Dynamic assignment without 'default'
```

Use this if you don't want to upload SARIF — the annotations work
without any post-processing action.

### JUnit XML (for Jenkins / GitLab / TeamCity)

JUnit XML is the standard test result format. Many CI tools render
it natively as a test report (pass/fail counts, per-test details).

```bash
senpy game/ --output-format junit --output-file senpy-junit.xml
```

Each Senpy diagnostic becomes a "test case":

- `ERROR` severity → `<failure>` (test failed)
- `WARNING` severity → `<skipped>` (test skipped)
- All other severities → normal `<testcase>`

Upload as a CI artifact or use your CI's JUnit ingestion feature
(GitLab CI: `artifacts.reports.junit`, Jenkins: JUnit plugin).

### GitLab Code Quality JSON (for GitLab MR annotations)

GitLab's Code Quality report format. Findings appear as MR
annotations on the diff.

```bash
senpy game/ --output-format gitlab --output-file senpy-gitlab.json
```

Each finding gets a stable fingerprint (hash of file+line+rule), so
GitLab can track "this finding was here last CI run, this finding
is new".

In your `.gitlab-ci.yml`:

```yaml
senpy:
  image: python:3.11
  script:
    - pip install senpy-linter
    - senpy game/ --output-format gitlab --output-file senpy-gitlab.json
  artifacts:
    reports:
      codequality: senpy-gitlab.json
```

### Reviewdog NDJSON (for reviewdog integration)

[reviewdog](https://github.com/reviewdog/reviewdog) is a popular
review-automation tool. The `rdjson` format emits one JSON object per
line, suitable for piping into `reviewdog -f=rdjson`.

```bash
senpy game/ --output-format rdjson | reviewdog -f=rdjson -reporter=github-pr-review
```

In a workflow:

```yaml
- run: pip install senpy-linter
- run: |
    senpy game/ --output-format rdjson > senpy.rdjson
    cat senpy.rdjson | reviewdog -f=rdjson -reporter=github-pr-review -level=error
  env:
    REVIEWDOG_GITHUB_API_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### JSON (for custom integrations)

```bash
senpy game/ --output-format json --output-file senpy.json
```

Output schema:

```json
{
  "diagnostics": [
    {
      "file": "game/script.rpy",
      "line": 42,
      "col": 5,
      "end_col": 12,
      "code": "RPY105",
      "severity": "error",
      "message": "Direct mutation of 'define' constant"
    }
  ],
  "summary": {
    "total_lines": 35000,
    "fixed": 0,
    "time_sec": 0.342
  }
}
```

Use this for:

- Custom dashboards (Grafana, Kibana)
- Building a "lint dashboard" web page
- Comparing runs across commits to track technical debt

---

## CI-friendly flags

### `--check` (dry-run for `--fix`)

```bash
senpy game/ --fix --check
```

Reports what `--fix` would change, but **doesn't write**. Exits 1
if any fixable issues found — perfect for a CI step that blocks PRs
with unfixable style issues.

### `--diff`

```bash
senpy game/ --fix --diff
```

Prints a unified diff of what `--fix` would change. Useful for
reviewing auto-fixes before applying them.

### `--exit-zero` (non-blocking CI)

```bash
senpy game/ --exit-zero
```

Always exits 0, even if errors are found. Use for nightly reports or
non-blocking sweeps that gather findings without blocking the
pipeline. Diagnostics are still printed to stdout.

### `--statistics`

```bash
senpy game/ --statistics
```

Prints a summary table of diagnostics by rule code (count per rule,
sorted by frequency). Useful as a CI artifact — see which rules
account for most of your technical debt.

### `--show-fixes`

```bash
senpy game/ --fix --show-fixes
```

After `--fix` runs, prints a detailed list of what was fixed
(file:line: rule — fix title). Useful for CI logs and audit trails.

### `--add-noqa` (bulk suppress)

```bash
senpy game/ --add-noqa
```

Adds `# noqa` suppression comments to all fixable diagnostics. Use
when you have a large legacy codebase and want to suppress existing
noise without fixing it (and then enforce `noqa` discipline for new
code).

---

## Pre-commit hook

Senpy ships a [pre-commit](https://pre-commit.com) hook that runs
`senpy --check` on every commit. Add this to your
`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/Xilleet/senpy
    rev: v0.8.0   # use the latest tag
    hooks:
      - id: senpy
```

The hook is **non-mutating** — it only reports issues, never
auto-fixes them. This is deliberate: an auto-fixing hook combined
with git's `autocrlf` on Windows creates an infinite loop (the
formatter normalizes line endings, git converts them back, the
formatter runs again).

If you want auto-fixing, run `senpy --fix` manually before
committing.

---

## A complete CI recipe

This recipe runs Senpy on every PR, fails the build on new errors,
uploads SARIF for Code Scanning, and uploads JUnit XML as an
artifact for the test report UI.

```yaml
name: Senpy

on:
  pull_request:
    branches: [ main ]
  push:
    branches: [ main ]

permissions:
  contents: read
  security-events: write   # for SARIF upload

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: pip

      - name: Install Senpy
        run: pip install senpy-linter

      - name: Run Senpy (SARIF for Code Scanning)
        run: senpy game/ --output-format sarif --output-file senpy.sarif
        continue-on-error: true   # so the upload still happens

      - name: Upload SARIF to GitHub Code Scanning
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: senpy.sarif

      - name: Run Senpy (JUnit for test report)
        run: senpy game/ --output-format junit --output-file senpy-junit.xml

      - name: Upload JUnit XML as artifact
        uses: actions/upload-artifact@v4
        with:
          name: senpy-junit
          path: senpy-junit.xml

      - name: Run Senpy (blocking, no SARIF)
        # This step actually fails the build on errors.
        # We run it last so the SARIF + JUnit are uploaded first,
        # then the build fails if Senpy finds any ERRORs.
        run: senpy game/ --errors-only
```

Adjust to your needs:

- **Strict mode** — add `--strict` (or set `strict = true` in
  `senpy.toml`) to fail on any rule not explicitly downgraded.
- **Skip translation checks** — add `--ignore-tag translations` if
  you don't want translation rules in CI.
- **Coverage gate** — add a step that runs
  `senpy game/ --coverage --output-format json` and parses the JSON
  to fail if a language's coverage drops below a threshold.

---

## Caching

Senpy uses a two-tier disk cache (`.senpy_cache/`). In CI, you can
cache this across runs to speed up incremental analyses:

```yaml
- name: Cache .senpy_cache
  uses: actions/cache@v4
  with:
    path: .senpy_cache
    key: senpy-cache-${{ runner.os }}-${{ hashFiles('game/**/*.rpy') }}
    restore-keys: |
      senpy-cache-${{ runner.os }}-
```

For most CI workflows the cache hit isn't worth it (a fresh Senpy
run on a 70k-line project is ~3.5s), but for very large projects it
can save seconds.

---

## What's next?

- [**CLI reference**](cli-reference.md) — every flag, including
  `--init-ci`, `--output-format`, `--check`, `--diff`, `--exit-zero`.
- [**Configuration**](configuration.md) — `senpy.toml`, `.senpy-ignore`,
  severity overrides, strict mode.
- [**Install**](install.md) — `pip install senpy-linter`.
- [**All 51 rules**](rules/index.md) — to choose which rules to enable
  or disable in CI.
