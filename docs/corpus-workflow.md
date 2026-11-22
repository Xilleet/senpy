# Corpus FP cleanup — contributor workflow

This document describes the **end-to-end workflow** for finding and fixing
false positives (FPs) in Senpy's rule set by running the analyzer against a
curated corpus of real open-source Ren'Py visual novels.

It is intended for contributors who want to make a high-impact contribution
to a static analyzer — real-world FP reports that drive rule fixes. No
prior knowledge of Senpy internals is required, but you should be
comfortable running Python scripts from a terminal and reading Ren'Py
source code.

---

## Table of contents

- [What this is](#what-this-is)
- [Prerequisites](#prerequisites)
- [Pipeline overview](#pipeline-overview)
- [Quick reference (TL;DR)](#quick-reference-tldr)
- [Step-by-step](#step-by-step)
  - [Step 1. Clone the corpus](#step-1-clone-the-corpus)
  - [Step 2. Run senpy on the corpus](#step-2-run-senpy-on-the-corpus)
  - [Step 3. Generate the baseline](#step-3-generate-the-baseline)
  - [Step 4. Triage diagnostics](#step-4-triage-diagnostics)
  - [Step 5. Verify RED tests](#step-5-verify-red-tests)
  - [Step 6. GREEN fixes](#step-6-green-fixes)
  - [Step 7. Update baseline after fixes](#step-7-update-baseline-after-fixes)
  - [Step 8. Regression tests](#step-8-regression-tests)
  - [Step 9. CI workflow](#step-9-ci-workflow)
  - [Step 10. Public badge](#step-10-public-badge)
- [TP/FP decision guide](#tpfp-decision-guide)
- [Current capabilities & limitations](#current-capabilities--limitations)
- [File inventory](#file-inventory)
- [Troubleshooting](#troubleshooting)

---

## What this is

Senpy ships with 53 lint rules (`RPY000`–`RPY802`) covering formatting,
variables/state, screens, dialogue, branching, assets, translations, and
dead code. Each rule has unit-level fixtures (`tests/fixtures/rules/RPYxxx/`
with `bad_*.rpy` + `bad_*.json` + `good_*.rpy` triples) that test the rule
in isolation on small synthetic snippets.

**Fixtures are necessary but not sufficient.** Real VN code uses idioms,
patterns, and combinations that synthetic fixtures don't always anticipate.
Rules that pass all unit fixtures can still produce false positives on
real projects — a regex that's too broad, an AST walker that misses a
node type, a built-in namespace that wasn't included in `BUILTIN_SYMBOLS`,
a screen-local variable scope that the rule doesn't distinguish from
global state, etc.

The **corpus FP cleanup pipeline** catches these real-world FPs by running
Senpy against a curated set of 15 open-source VN projects, comparing the
diagnostics against human judgement, and turning every confirmed FP into
a regression test that locks the eventual fix in place.

The pipeline does **not** replace unit fixtures — it complements them.
Unit fixtures cover the contract of each rule on minimal inputs; the
corpus covers the rule's behaviour on the messy, real-world combinations
that VN authors actually write.

---

## Prerequisites

- **Python 3.11+** (same as Senpy itself).
- **git** — used to shallow-clone the corpus VN projects from GitHub.
- **~2 GB free disk space** — 15 shallow clones, ~50–200 MB each.
- **`rich`** Python package — already in Senpy's dependencies; the
  corpus scripts use it for progress bars and summary tables.
- **`pytest`** — for running the RED/GREEN test suite.
- **A terminal that supports UTF-8 + ANSI colours** — the rich output
  includes Unicode markers (`✓`, `≈`, `B`) and colour codes. On Windows,
  Windows Terminal / VS Code integrated terminal / PowerShell 7 all work;
  legacy `cmd.exe` may render colours incorrectly.

No Ren'Py SDK installation is required — Senpy is a pure-Python static
analyzer that does not execute the games it analyzes.

---

## Pipeline overview

```
   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
   │ collect_    │     │ run_corpus  │     │ triage_     │
   │ corpus.py   │ ──> │ .py         │ ──> │ corpus.py   │
   │             │     │             │     │             │
   │ git clone   │     │ SenpyAnaly  │     │ TP / FP /   │
   │ 15 OSS VNs  │     │ zer.run()   │     │ maybe_fp /  │
   │ → tests/    │     │ → JSON +    │     │ skip labels │
   │   _corpus/  │     │   baseline  │     │ → triage.   │
   │   (gitignored)│   │             │     │   json      │
   └─────────────┘     └─────────────┘     └──────┬──────┘
                                                  │
                                                  ▼
                                       ┌──────────────────┐
                                       │ test_corpus_fp.py│
                                       │ (auto-discovery) │
                                       │                  │
                                       │ For every FP →   │
                                       │ parametrised RED │
                                       │ test (asserts    │
                                       │ rule does NOT    │
                                       │ fire)            │
                                       └────────┬─────────┘
                                                │
                                                ▼
                                       ┌──────────────────┐
                                       │ fix              │
                                       │ the rule         │
                                       │ (commit per fix) │
                                       └────────┬─────────┘
                                                │
                                                ▼
                                       ┌──────────────────┐
                                       │                  │
                                       │ regression tests │
                                       │ (synthetic       │
                                       │  fixtures)       │
                                       └────────┬─────────┘
                                                │
                                                ▼
                                       ┌──────────────────┐
                                       │                  │
                                       │ weekly cron      │
                                       │ (drift detection)│
                                       └────────┬─────────┘
                                                │
                                                ▼
                                       ┌──────────────────┐
                                       │                  │
                                       │ public corpus-   │
                                       │ count badge      │
                                       └──────────────────┘
```

**Dependency flow:** each step depends on the previous one's output.
Steps 1–5 are the **finding** phase (discover FPs); step 6 is the
**fixing** phase; steps 7–9 are the **locking-in** phase (regression
guard, CI, public badge).

---

## Quick reference (TL;DR)

Ten commands from a fresh clone to a closed FP:

```bash
# Finding phase (steps 1–5)
python scripts/collect_corpus.py                          # clone 15 VNs
python scripts/run_corpus.py --update-baseline            # write baseline.json
git add tests/_corpus_baseline.json
git commit -m "feat(corpus): baseline after first full corpus run"

python scripts/triage_corpus.py --slug gifting_game       # label FPs interactively
                                                         # (or --export-csv / --import-csv)
pytest tests/rules/test_corpus_fp.py -v                   # see RED tests

# Fixing phase (step 6)
# ...edit the rule code in senpy/rules/checkers/*.py or senpy/rules/python_ast.py...
pytest tests/rules/test_corpus_fp.py -v                   # see RED → GREEN
git commit -m "fix(rules): <one-line summary>"

# Locking-in phase (steps 7–9)
python scripts/run_corpus.py --update-baseline            # refresh baseline after fixes
git add tests/_corpus_baseline.json tests/_corpus_triage.json
git commit -m "fix(corpus): update baseline after CORPUS-6 GREEN fixes"
```

The rest of this document explains each step in detail.

---

## Step-by-step

### Step 1. Clone the corpus

**Command:**
```bash
python scripts/collect_corpus.py                 # clone all 15
python scripts/collect_corpus.py --list          # print catalog (no network)
python scripts/collect_corpus.py --only ddlc     # clone one by slug
python scripts/collect_corpus.py --force         # re-clone existing
python scripts/collect_corpus.py --dry-run       # plan only, no clone
```

**What it does:**

Shallow-clones (`--depth 1` — only the latest commit, no history) each
of the 15 OSS VN projects into `tests/_corpus/<slug>/`. The catalog is
defined in `scripts/collect_corpus.py:PROJECTS` — adding a new project
means editing one place.

**Idempotent:** if `<slug>/.git` already exists, the project is skipped
unless `--force` is passed (which removes and re-clones).

**SHA pinning:** the cloned HEAD SHA is recorded in
`tests/_corpus/<slug>/.cloned_sha` so `run_corpus.py` can detect
upstream movement (a re-clone is needed to pick up new commits — the
baseline fingerprint includes this SHA).

**Disk usage:** ~3 GB total for all 15 projects.

**License hygiene:** each project keeps its own `LICENSE` inside its
shallow clone. VN bytes never enter the Senpy repo — `tests/_corpus/`
is in `.gitignore`. Do not commit anything from `tests/_corpus/` (other
than the `.cloned_sha` files, which are tiny text files containing the
commit SHA — but those are gitignored too).

**The 15 projects:**

| Slug | Repo | Notes |
| ---- | ---- | ----- |
| `ddlc` | SecondThundeR/DokiDoki-RenPy | DDLC 1.1.1 decompiled (~35 .rpy) |
| `learntocode` | freeCodeCamp/LearnToCodeRPG | Educational VN (~60 .rpy) |
| `ddlc_mod_template` | Bronya-Rand/DDLCModTemplate2.0 | Mod template 2.0 (~40 .rpy) |
| `monika_after_story` | Monika-After-Story/MonikaModDev | Largest entry (~122 .rpy) |
| `ddlc_mod_template_zchrxh` | zchrxh/Doki-Doki-Mod-Template | Alternate mod template (~49 .rpy) |
| `renpy_template_ruolin` | RuolinZheng08/renpy-template | Starter template (~11 .rpy) |
| `renpy_vn_template_dual` | dualfighter1/Renpy-VN-Template | Simple VN template (~10 .rpy) |
| `bytes_of_love` | ufosc/VisualNovel | Student-built VN (~29 .rpy) |
| `avnovel` | crcdng/avnovel | Tiny demo (~4 .rpy) |
| `cross_channel` | MewX/cross-channel_chinese-localization_project | Largest .rpy count (~302 .rpy) |
| `love69` | luckykeeper/LOVE69_renpy_remaster | Localization-heavy (~29 .rpy) |
| `aqua_guardians` | sk66641/AquaGuardians | Small standalone (~10 .rpy) |
| `personal_space2` | qirien/personal-space2 | Indie VN with translations (~31 .rpy) |
| `cold_hands` | hud0shnik/cold_hands | Small modern VN (~8 .rpy) |
| `gifting_game` | alchemmist/gifting-game | Holiday-themed short VN (~4 .rpy) |

Run `python scripts/collect_corpus.py --list` to see the live catalog.

---

### Step 2. Run senpy on the corpus

**Command:**
```bash
python scripts/run_corpus.py                          # run all
python scripts/run_corpus.py --only gifting_game       # run one
python scripts/run_corpus.py --list                    # plan only (cloned? + game/ path)
python scripts/run_corpus.py --json-only gifting_game  # full JSON to stdout
```

**What it does:**

For each cloned project, this script:

1. **Auto-detects the project root.** Corpus projects nest `game/` at
   arbitrary depth (`gifting_game/game/`, `ddlc/ddlc-renpy-project/game/`,
   `bytes_of_love/BytesOfLove/game/`, etc.). A BFS search finds the
   shallowest `game/` directory and uses its parent as `project_path`.
   If no `game/` exists (some repos store `.rpy` directly in the root —
   e.g. `cross_channel`), the clone root is used as fallback.

2. **Runs `SenpyAnalyzer(project_path, no_cache=True).run(quiet=True).**
   `no_cache=True` forces a cold run on every invocation — the corpus
   directory is gitignored, so a stale Tier-2 cache would be invisible
   to git and could mask a regression.

3. **Writes per-project JSON** to `tests/_corpus/<slug>/senpy_results.json`
   (gitignored — local artefact for triage). Contains the full
   diagnostics list with repo-relative paths, line numbers, columns,
   rule codes, severities, and messages.

4. **Compares against baseline** (if `tests/_corpus_baseline.json`
   exists and `--update-baseline` was NOT passed). Reports drift:
   new diagnostics, disappeared diagnostics, fingerprint movement.

**Output format:**

After the run, a summary table is printed:

```
┌──────┬───────────────────────────────────────────────────┬────────────────┬─────────────┬─────────────┬─────────────┐
│      │ Slug                                              │ Status         │       Diags │       Files │       Codes │
├──────┼───────────────────────────────────────────────────┼────────────────┼─────────────┼─────────────┼─────────────┤
│ ✓    │ gifting_game                                      │ ran            │          53 │           4 │           7 │
│ ≈    │ monika_after_story                                │ skipped        │           - │           - │           - │
└──────┴───────────────────────────────────────────────────┴────────────────┴─────────────┴─────────────┴─────────────┘
```

Statuses: `✓ ran` (analyzed), `≈ skipped` (clone absent — run
`collect_corpus.py --only <slug>`), `B baseline` (analyzed + baseline
written in `--update-baseline` mode).

**Drift report:** in compare mode (default), drift is printed with
colour-coded deltas — green for `-N` (diagnostics decreased =
improvement), red for `+N` (regression), yellow for `NEW` (no baseline
entry yet), blue for fingerprint movement. Exit code 1 on any drift
(this is what the weekly CI job catches).

---

### Step 3. Generate the baseline

**Command:**
```bash
python scripts/run_corpus.py --update-baseline
```

**What it does:**

Regenerates `tests/_corpus_baseline.json` from the current run. The
baseline is the **committed contract** — anonymised per-project counts
only (no VN source bytes, no message text):

```json
{
  "gifting_game": {
    "fingerprint": "sha256:abc123def456...",
    "total": 53,
    "by_code": {"RPY104": 15, "RPY305": 16, "RPY503": 17, ...},
    "by_severity": {"WARNING": 50, "ERROR": 3}
  },
  ...
}
```

**`fingerprint`** is `git:` + the cloned commit SHA from
`tests/_corpus/<slug>/.cloned_sha`. The `git:` prefix (renamed from
`sha256:` in 0.9.3) clarifies that the value is a git commit identifier,
not a SHA-256 content hash — this matters when the fingerprint validation
guard (Batch 3) compares triage fingerprints against the manifest's
pinned commit. The fingerprint lets the CI job detect upstream movement
— a stale baseline against a moved commit is a smell, not necessarily a
regression (the VN project itself changed, so diagnostic counts are
expected to shift).

**Manifest:** `tests/_corpus_manifest.json` is the curated catalog that
pins each project to a specific commit and records its license:

```json
{
  "gifting_game": {
    "slug": "gifting_game",
    "repository": "alchemmist/gifting-game",
    "commit": "e36246547a25276a804c73fa43063bd91070d004",
    "license": "MIT",
    "renpy_version": null,
    "notes": "gifting-game VN (~4 .rpy). Holiday-themed short VN."
  }
}
```

`collect_corpus.py` updates the `commit` field automatically after each
clone. The `license` field is SPDX identifier (`MIT`, `Apache-2.0`,
`GPL-3.0`, `BSD-3-Clause`) or `none` (no LICENSE file) or `NOASSERTION`
(custom license GitHub cannot classify — maintainer must verify). The
`renpy_version` field is `null` until auto-detection lands in 0.11.0
(ARCH-10 RenPyVersionDetector).

**Commit it:**
```bash
git add tests/_corpus_baseline.json tests/_corpus_manifest.json
git commit -m "feat(corpus): baseline after first full corpus run (15 projects)"
```

The baseline is the "before" state. Future runs without
`--update-baseline` compare against it and report drift — this is what
the weekly CI regression job (CORPUS-8) uses to catch regressions
introduced by Senpy rule changes.

**When to update the baseline:**

- **After the first corpus run** — initialise the baseline.
- **After CORPUS-6 GREEN fixes** — the fixes reduce diagnostic counts;
  the baseline should reflect the new (lower) state.
- **After a Senpy release that legitimately changes diagnostics** —
  e.g. a new rule is added, or a rule's severity is overridden via
  `senpy.toml`. The baseline update commit should explain why counts
  changed.
- **Not casually** — if you're just experimenting with rule tweaks,
  don't update the baseline yet. Run in compare mode and review the
  drift first.

---

### Step 4. Triage diagnostics

This is step — for each diagnostic, decide whether
Senpy was right to fire (TP) or wrong (FP).

**What the statuses mean:**

| Status | Meaning | When to use |
| ------ | ------- | ----------- |
| `tp`   | True positive — Senpy caught a real bug/anti-pattern | Code really has the issue the rule warns about |
| `fp`   | False positive — Senpy fired on legitimate code | Code is correct, rule is wrong (this is what CORPUS-6 fixes) |
| `maybe_fp` | Uncertain — needs a closer look | Not yet decided, will revisit |
| `skip` | Out of scope or ambiguous | Cannot determine, unrelated noise |

**Interactive mode (recommended for small projects):**
```bash
python scripts/triage_corpus.py --slug gifting_game
```

Walks each diagnostic for the project, shows file:line:code:message,
**5 lines of source context** around the flagged line (with an `←` marker),
and a link to the rule's section in RULES.md:

```
gifting_game | game/olnewyear-5.rpy:675 [RPY202 WARNING]
    Screen 'file_slots' accesses undeclared variable 'CurrentScreenName'. Screens
    can be evaluated in the main menu or before game start, causing a crash.

    670 │ screen file_slots():
    671 │     # Comment
    672 │     text "Save"
    673 │     null
    674 │
    675 │ ←   if CurrentScreenName() == "save":
    676 │         pass
    677 │

    See RULES.md#rpy202 for rule semantics.
    [t]p  [f]p  [m]aybe-fp  [s]kip  [q]uit (keep current)  [e]dit note
    > f
    note (why FP/maybe? optional): CurrentScreenName() is a function call, not a variable access
```

The source context is read from the local corpus clone
(`tests/_corpus/<slug>/<file>`). If the file is not found (corpus not
cloned, or the VN project moved upstream and the file changed), the
prompt shows `(source file not found — clone corpus or file moved upstream)`
instead of the context block.

**Triage by rule code (recommended for pattern recognition):**
```bash
python scripts/triage_corpus.py --by-rule RPY305
```

Instead of walking one project at a time, this mode collects **all
diagnostics of one rule code across all 15 projects** and presents them
consecutively. This lets you build pattern recognition fast — e.g. all
RPY305 cases (multi-line dialogue) across the corpus are shown one after
another, making it obvious that they share a common FP pattern.

```
Triage by rule: RPY305 (47 cases across 8 project(s))
Ctrl-C aborts without saving; 'q' on a row keeps its current status.

[1/47]
  aqua_guardians | game/red_route.rpy:39 [RPY305 ERROR]
    ...
```

Use `--by-rule` when you want to:
- Verify that a suspected FP pattern (e.g. multi-line dialogue for
  RPY305, function calls for RPY202) is consistent across projects
- Triage all cases of one rule in a single session (faster than
  switching between projects)
- Build a mental model of what a rule catches in practice before
  deciding TP/FP

**CSV mode (recommended for bulk triage of large projects):**
```bash
python scripts/triage_corpus.py --export-csv
# opens tests/_corpus/_corpus_triage.csv (gitignored) — label the 'status' column
# in LibreOffice / Excel / Google Sheets with tp / fp / maybe_fp / skip + a note
python scripts/triage_corpus.py --import-csv
```

**Summary mode:**
```bash
python scripts/triage_corpus.py --summary               # per-project + overall counts
python scripts/triage_corpus.py --summary --status fp   # FP count only
```

**Writing good FP notes:**

The `note` field is critical — it's what tells CORPUS-6 what to actually
fix. Be specific about the rule's mistake:

✅ Good notes:
- `"CurrentScreenName() is a function call, not a variable access — RPY202 should not fire on call expressions"`
- `"$ what = ... inside screen assigns a local screen var, not a state mutation — RPY201 should not fire on $ local assignments"`
- `"config.searchpath is a built-in Ren'Py namespace — RPY202 should not fire on config.*"`

❌ Bad notes:
- `"looks wrong"` (not actionable — CORPUS-6 doesn't know what's wrong)
- `"fp"` (just restates the status — no information)
- `"maybe a bug"` (then it should be `maybe_fp`, not `fp`)

The note will appear in the RED test failure message when the FP case is
parametrised into `tests/rules/test_corpus_fp.py`, so it doubles as
documentation for whoever writes the GREEN fix.

**Start with small projects.** Don't try to triage all 17k+ diagnostics
at once. Recommended order (smallest first, to build up pattern
recognition):

```bash
python scripts/triage_corpus.py --slug renpy_vn_template_dual   # ~18 diags
python scripts/triage_corpus.py --slug avnovel                  # ~40 diags
python scripts/triage_corpus.py --slug gifting_game             # ~53 diags
python scripts/triage_corpus.py --slug renpy_template_ruolin    # ~54 diags
python scripts/triage_corpus.py --slug bytes_of_love            # ~61 diags
python scripts/triage_corpus.py --slug aqua_guardians           # ~74 diags
python scripts/triage_corpus.py --slug cold_hands               # ~155 diags
# ...then larger projects once you're confident
```

The roadmap target is **30–60 confirmed FP cases** to drive CORPUS-6.
With ~17 000 total diagnostics across the corpus, even a 0.5% FP rate
yields ~85 cases — so triaging 3–5 small projects fully should be
enough to find the target.

**Deciding TP vs FP — see the [TP/FP decision guide](#tpfp-decision-guide)
below.**

---

### Step 5. Verify RED tests

After you've labelled some FPs (via `--slug` or `--import-csv`), the
triage state is saved to `tests/_corpus_triage.json` (committed — no VN
source bytes, just anonymous diagnostic metadata + your labels + notes).

The test file `tests/rules/test_corpus_fp.py` **auto-discovers** FP
cases from `_corpus_triage.json` at import time — no test file editing
needed. Run:

```bash
pytest tests/rules/test_corpus_fp.py -v
```

You'll see one parametrised test case per FP, with a stable readable id:

```
tests/rules/test_corpus_fp.py::test_corpus_fp_case[gifting_game::olnewyear-5.rpy:675::RPY202]
tests/rules/test_corpus_fp.py::test_corpus_fp_case[gifting_game::olnewyear-5.rpy:914::RPY201]
tests/rules/test_corpus_fp.py::test_corpus_fp_case[gifting_game::olnewyear-5.rpy:990::RPY202]
```

**These tests are currently RED** — Senpy still fires the rule at the
labelled line, so the assertion `code not in diags_at_line` fails. This
is the intended state: each RED test is a contract that CORPUS-6 will
turn green by fixing the rule.

**Skip behaviour:** if the corpus clone is absent (typical CI machines,
developer machines that only ran a subset), the whole module skips with
a clear reason. If the clone exists but `_corpus_triage.json` has no
`fp` entries yet, a guard test fails with a message nudging you to run
`triage_corpus.py` — this prevents the FP pipeline from silently looking
green when it's actually unstaffed.

**How the test reproduces the FP:**

For each FP case, the test:
1. Reads the original VN source file from `tests/_corpus/<slug>/<file>`.
2. Copies it to a temporary `tmp_path/game/<basename>.rpy`.
3. Runs `SenpyAnalyzer(tmp_path, no_cache=True).run(quiet=True)`.
4. Checks whether the labelled rule code fires at the labelled line.
5. If yes → RED (test fails with the triage note in the failure message).
6. If no → GREEN (test passes — the rule was fixed).

The test uses the **whole source file** rather than a hand-extracted
snippet because Ren'Py is indentation-based and context-sensitive — a
line inside a `screen` block means something different from the same
line inside a `label`. Hand-extracted snippets risk losing the
enclosing block and flipping a TP into an FP (or vice versa).

---

### Step 6. GREEN fixes

For each FP, fix the rule so it no longer fires on the labelled line.

**Where to find the rule code:**

Rules are organized by domain prefix. Each prefix maps to a checker
module:

| Prefix | Domain | File |
| ------ | ------ | ---- |
| `RPY0xx` | Formatting | `senpy/rules/checkers/formatting.py` |
| `RPY1xx` | Variables & state | `senpy/rules/checkers/state.py` + `senpy/rules/python_ast.py` |
| `RPY2xx` | Screens & UI | `senpy/rules/checkers/screen.py` |
| `RPY3xx` | Dialogue & labels | `senpy/rules/checkers/dialogue.py` |
| `RPY4xx` | Control flow | `senpy/rules/flow.py` + `senpy/rules/checkers/state.py` |
| `RPY5xx` | Assets | `senpy/rules/checkers/asset.py` |
| `RPY6xx` | Translations | `senpy/rules/checkers/translation.py` |
| `RPY7xx` | Dead code | `senpy/rules/dead_code.py` |
| `RPY8xx` | Translation quality | `senpy/rules/checkers/translation.py` |
| `RPY107` | Deprecated APIs | `senpy/rules/deprecated.py` |

For rule semantics and what each rule is supposed to catch, see
**[RULES.md](../RULES.md)** — open it in a separate tab while fixing.

**Common FP fix patterns:**

| FP pattern | Fix location | Typical fix |
| ---------- | ------------ | ----------- |
| Rule fires on function call as if variable access | `screen.py` / `state.py` | Distinguish `ast.Call` from `ast.Name` in the AST walker |
| Rule fires on built-in namespace (`config.*`, `gui.*`, `audio.*`) | `senpy/core/renpy_builtins.py` | Add the namespace to `BUILTIN_SYMBOLS` (or `additional_builtins` in `senpy.toml`) |
| Rule fires on `$ X = ...` inside screen (local var) | `screen.py` | Scope-aware check — `$` inside `screen` body creates a screen-local, not a store mutation |
| Rule fires on `dict.keys()/.values()/.items()` as list | `senpy/core/type_inference.py` | Return correct view types (`dict_keys` / `dict_values` / `dict_items`) or `None` |
| Rule fires on deprecated API that's actually current | `senpy/rules/deprecated.py` | Remove from `DEPRECATED_APIS` or gate by Ren'Py version |
| Rule fires on for-loop target tuple unpacking | `senpy/text_utils.py:extract_for_targets` | Extend AST walker to handle `ast.Tuple` targets |

**Commit style:**

One commit per fix, conventional-commits format. Examples from the
repo's history:

```
fix(rules): correct augassign dict/bool type check and stop LSP fast-path counter leak
fix(rules): route screen.py RPY202/RPY207/RPY208 severity through RULE_SEVERITY
fix(rules): unify RPY204 generators + SUGGESTION_CUTOFF constants
fix(fp): bool arithmetic + dict view types + screen string masking
```

**After each fix:**

```bash
pytest tests/rules/test_corpus_fp.py -v           # the relevant case goes RED → GREEN
pytest tests/rules/test_fixtures.py -v            # don't break existing unit fixtures
pytest tests/rules/ -q                            # full rules regression
```

If a fix breaks an existing unit fixture, that's a signal — either your
fix is too broad (now misses real TPs) or the fixture was wrong (rare,
but possible). Investigate before committing.

**Don't fix everything in one commit.** One FP per commit makes review
tractable and lets the maintainer bisect if a regression appears later.

---

### Step 7. Update baseline after fixes

After a batch of GREEN fixes:

```bash
python scripts/run_corpus.py --update-baseline
git add tests/_corpus_baseline.json tests/_corpus_triage.json
git commit -m "fix(corpus): update baseline after CORPUS-6 GREEN fixes"
```

**Success criterion** (from roadmap): corpus diagnostics should decrease
by at least 5% vs the previous baseline. So if the previous baseline was
17 786 total diagnostics, the new baseline should be ≤16 897.

If the count went UP, that's a red flag — a fix was too broad and is now
catching more (potentially false) positives. Investigate before
committing the new baseline.

---

### Step 8. Regression tests

**Status: not yet implemented — this is the next step after CORPUS-6.**

`tests/rules/test_corpus_fp.py` is skip-if-corpus-absent, which means CI
machines without the corpus clone can't catch regressions to corpus FPs.
CORPUS-7 closes this gap with **synthetic fixtures** derived from real
FP cases — minimal `.rpy` snippets that reproduce the FP pattern without
using VN bytes (so they can ship in the repo).

**Target file:** `tests/regressions/test_post_090_corpus.py`

**Pattern:** for each FP class fixed in CORPUS-6, extract the minimal
reproducer (hand-shrink the original VN file to the smallest snippet
that still triggers the rule pre-fix and doesn't trigger it post-fix),
put it under `tests/fixtures/rules/RPYxxx/` as a `good_*.rpy` file, and
add a regression test that asserts the rule does NOT fire.

These tests run on every CI machine (no corpus clone needed) and lock
the fix in place forever.

---

### Step 9. CI workflow

**Status: not yet implemented.**

A weekly CI job that catches drift introduced by Senpy rule changes
against the committed baseline.

**Target file:** `.github/workflows/corpus-regression.yml`

**Spec:**
- Triggers: `schedule` (cron `0 6 * * 1` — Monday 06:00 UTC) +
  `workflow_dispatch` (manual run from GitHub Actions UI).
- Steps: checkout → setup-python 3.11 → `pip install -e .` →
  `python scripts/collect_corpus.py` →
  `python scripts/run_corpus.py` →
  `pytest tests/rules/test_corpus_fp.py`.
- On drift (delta vs baseline) — exit 1, report in job summary.

Weekly (not per-push) is deliberate — cloning 15 VN repos on every PR
would burn CI minutes and slow down merges. A weekly cadence catches
regressions within ≤7 days, which is acceptable for a one-maintainer
project.

---

### Step 10. Public badge

**Status: not yet implemented.**

A badge in the README showing the corpus size:

```markdown
![corpus](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/Xilleet/.../raw/corpus.json)
```

**Implementation:** extend `scripts/update_badges.py` to read
`PROJECTS` from `collect_corpus.py`, write the count to
`.github/badges/corpus.json`, push via the existing
`push_badges_to_gist.py` script.

---

## TP/FP decision guide

This section helps you decide whether a diagnostic is TP, FP, or
`maybe_fp`. When in doubt, mark `maybe_fp` and revisit after triaging
other cases — pattern recognition builds quickly.

### General principles

1. **Read the rule's intent in [RULES.md](../RULES.md).** Each rule has
   a "Why" section explaining what it's supposed to catch. If the code
   really has that issue → TP. If the rule misidentified the pattern →
   FP.

2. **Look at the actual VN source code at the flagged line** (and 5–10
   lines of context around it). Ren'Py is indentation-based and
   context-sensitive — a line inside a `screen` block means something
   different from the same line inside a `label`.

3. **Consider runtime behaviour.** Would this code actually crash /
   misbehave at runtime? If yes → likely TP. If the code runs fine →
   likely FP.

4. **Built-in namespaces are FP-prone.** `config.*`, `gui.*`, `audio.*`,
   `persistent.*`, `preferences.*`, `renpy.*`, `build.*`,
   `layeredimage.*` — all are built-in Ren'Py namespaces. Rules that
   flag access to these as "undeclared variable" (RPY202, RPY103) are
   FPs unless the specific attribute really doesn't exist.

### Per-rule guidance

| Rule | Typical TP | Typical FP |
| ---- | ---------- | ----------- |
| RPY001 (tabs) | File has tab indentation | Almost never FP |
| RPY002 (smart quotes) | Smart quotes in `$` / `python:` code | Almost never FP |
| RPY100 (non-UTF-8) | File is CP1251 / Shift-JIS | Almost never FP |
| RPY101 (broken `[var]`) | Variable really doesn't exist | Sometimes FP if var is built-in or `config.*` |
| RPY102 (`+=` before `default`) | Variable used before declared | FP if variable is a for-loop target |
| RPY103 (undeclared in condition) | Variable never declared via `default`/`define` | FP on built-in namespaces, for-loop targets inside `init python:` |
| RPY104 (dynamic assignment) | `$ x = 1` in label without `default x` | FP if `x` is screen-local or function parameter |
| RPY105 (define mutation) | `$ define_X += 1` (real rollback bug) | Almost never FP |
| RPY106 (non-revertable type) | `default x = open("file")` | FP if type is actually revertable (e.g. `revertable_set`) |
| RPY107 (deprecated API) | `LiveComposite()`, `im.Scale()`, `config.images_directory` | FP if API is actually current in the project's Ren'Py version |
| RPY108 (type taint) | `$ x = "str"; $ x += 1` (real TypeError) | FP on `bool + int`, `dict.keys().append()`, view types |
| RPY109 (init order) | Function used in `init python:` before defined | FP if function is built-in or imported |
| RPY110 (Python syntax error) | `$ x = (` (unclosed paren) — real SyntaxError | FP if it's a multi-line string opener the parser doesn't recognize (`$ x = """<newline>..."""` — see FIX-75 in roadmap) |
| RPY201 (state mutation in screen) | `$ store.x = 1` inside screen | FP on `$ x = ...` (screen-local var) |
| RPY202 (undeclared in screen) | Real undeclared variable access | FP on function calls (`X()` vs `X`), built-in namespaces |
| RPY203 (button no action) | `textbutton "X":` with no `action` | FP if action is on next line or in a complex expression |
| RPY204 (missing screen target) | `use nonexistent_screen` | Almost never FP |
| RPY205 (imperative loop in screen) | `for i in range(1000):` in screen | FP if loop is over a small fixed collection |
| RPY206 (function call in action) | `action my_func()` instead of `Function(my_func)` | FP if it's actually `Function(...)` syntax |
| RPY207 (screen param mismatch) | `use screen(extra_arg)` | Almost never FP |
| RPY208 (SetVariable leak) | `SetVariable("x", ...)` on non-screen var | FP if variable is genuinely screen-local |
| RPY301 (unclosed text tag) | `"Hello {b}world"` (no `{/b}`) | FP if tag is auto-closing (`{p}`, `{w}`, etc.) |
| RPY302 (broken jump/call) | `jump nonexistent_label` | FP on dynamic jumps (`jump expression`) |
| RPY303 (dead label) | Label never referenced | FP if label is a `jump expression` target or entry point |
| RPY304 (color tag without color) | `{color}text{/color}` (no color value) | Almost never FP |
| RPY305 (unescaped quotes in dialogue) | `"He said "hi""` | FP if quotes are actually escaped via `\"` |
| RPY306 (call without return) | `call label` with no `return` in callee | FP if label intentionally falls through |
| RPY307 (duplicate label) | Two `label start:` definitions | Almost never FP |
| RPY308 (fallthrough) | Label doesn't end with `return`/`jump` | FP if label is an `after_load` hook or similar |
| RPY309 (story island) | Label group unreachable from `start` | FP if labels are reachable via dynamic `jump expression` |
| RPY310 (call arguments) | `call label(extra_arg)` or missing required kwarg | FP if the label signature uses `*args` / `**kwargs` (parser may not infer them correctly) |
| RPY401 (branch asymmetry) | Variable set in one `menu` branch, not another | FP if variable is pre-declared via `default` |
| RPY402 (empty choice) | `"":` choice in `menu:` | Almost never FP |
| RPY403 (contradiction) | `if True and False:` | FP on complex conditions with runtime-dependent values |
| RPY404 (MAYBE_SET read) | Variable read after `if/else` where only one branch sets it | FP if variable is guaranteed to be set (e.g. via `default` + `if True:`) |
| RPY501 (missing audio) | `play music "nonexistent.ogg"` | FP if file is in `.rpa` archive (tracked for 0.9.4 RPA-1) |
| RPY502 (unresolved transform) | `show X at nonexistent_transform` | FP on built-in positions (`left`, `center`, `right`) or ATL keywords |
| RPY503 (unused asset) | `image bg_old = "old.png"` never `show`n | FP if asset is used via `renpy.show()` in Python, or via `LayeredImage` attributes |
| RPY504 (duplicate image) | Two `image bg room =` definitions | Almost never FP |
| RPY505 (unregistered channel) | `play channel_name "x.ogg"` without `register_channel` | Almost never FP |
| RPY601 (translation var mismatch) | `old "Hi [name]"` / `new "Привет [имя]"` (different vars) | Almost never FP |
| RPY602 (translation tag mismatch) | `old "{b}X"` / `new "X"` (missing tag) | Almost never FP |
| RPY603 (empty translation) | `new ""` | Almost never FP |
| RPY701 (unused define) | `define X = 1` never referenced | FP if `X` is used via `getattr(store, "X")` or string interpolation |
| RPY702 (unused transform) | `transform X:` never used in `show ... at` | FP if transform is used as base for another transform |
| RPY703 (unused screen) | `screen X():` never `show`n / `use`d | FP if screen is shown via `renpy.show_screen("X")` |
| RPY704 (unused default) | `default X = 0` never read | FP if `X` is read in translation files or via `getattr` |
| RPY705 (unused parameter) | `label X(unused_param):` | FP if parameter is part of a documented interface |
| RPY706 (unused parameter) | `screen X(unused_param):` | Same as RPY705 |
| RPY707 (unused channel) | Registered channel never played to | FP if channel is used via `renpy.music.play(..., channel="X")` |
| RPY801 (duplicate translation) | Same string translated twice in same language | Almost never FP |
| RPY802 (inconsistent translation) | Original dialogue doesn't match translation across files | FP if dialogue legitimately diverged (intentional rewording) |

### Concrete FP examples from the existing triage

These three FPs are already in `tests/_corpus_triage.json` (from
`gifting_game`) — use them as templates for your own triage decisions.

**Example 1: RPY202 on `CurrentScreenName()` — FP**

VN source:
```renpy
screen file_slots():
    text CurrentScreenName()
```

Rule says: "undeclared variable `CurrentScreenName`".
Reality: `CurrentScreenName()` is a **function call** (parens!), and the
function is defined in an `init python:` block. The rule saw the name
via regex and didn't distinguish call from variable access.

Note: `"CurrentScreenName() is a function call, not a variable access — RPY202 should not fire on call expressions"`

**Example 2: RPY201 on `$ what = ...` inside screen — FP**

VN source:
```renpy
screen history():
    $ what = "some text"
```

Rule says: "direct state mutation inside screen".
Reality: `$ X = ...` inside a `screen` block creates a **screen-local
variable**, not a store mutation. Ren'Py's screen language has its own
scope. The rule doesn't distinguish scope.

Note: `"$ what = ... inside screen assigns a local screen var, not a state mutation — RPY201 should not fire on $ local assignments"`

**Example 3 (hypothetical TP for contrast): RPY105 on `define` mutation**

VN source:
```renpy
define player_gold = 100

label spend:
    $ player_gold -= 50
```

Rule says: "mutating a `define`".
Reality: this is a **real bug** — mutating `define` constants breaks
rollback (`Exception: define player_gold is not revertable`).

Status: `tp`. No note needed for TPs (the rule's `message` already
explains why it fired).

---

## Current capabilities & limitations

### What the system does today

- **Clones 15 OSS VN projects** shallowly into `tests/_corpus/` (gitignored).
- **Runs all 53 Senpy rules** against each project via `SenpyAnalyzer.run()`.
  Every rule in `RULES_DATABASE` is exercised (rules with no matching
  pattern in a given project simply produce no diagnostics for that
  project — this is expected, not a gap).
- **Generates a committed baseline** (`tests/_corpus_baseline.json`) with
  per-project counts (total / by_code / by_severity) and a SHA
  fingerprint for upstream-movement detection.
- **Triages diagnostics** interactively (`--slug`) or via CSV export/import.
  Triage state persists to `tests/_corpus_triage.json` (committed — no
  VN bytes).
- **Auto-discovers FP cases** from `_corpus_triage.json` into
  `tests/rules/test_corpus_fp.py` as parametrised RED tests. No test
  file editing needed to add new FP cases.
- **Skip-if-corpus-absent** — the test module skips cleanly on machines
  without the corpus clone (CI machines, partial dev clones), so the
  main test suite isn't blocked.
- **Drift detection** — `run_corpus.py` (without `--update-baseline`)
  compares against the baseline and exits 1 on any delta. This is what
  the future CI job will use.
- **Rich UX** — progress bars, summary tables, colour-coded drift deltas
  in `collect_corpus.py` / `run_corpus.py`.
- **Inline source context in triage** — `triage_corpus.py --slug` and
  `--by-rule` show 5 lines of source code around each flagged line
  (with an `←` marker on the diagnostic line) plus a link to the rule's
  section in RULES.md. No need to open the VN source in a separate editor.
- **Triage by rule code** — `triage_corpus.py --by-rule RPYXXX` groups
  all diagnostics of one rule code across all 15 projects, letting the
  triager build pattern recognition faster.
- **SyntaxWarning suppression** — `ast.parse()` calls in the analyzer
  are wrapped in `parse_python_silent()` (see `senpy/text_utils.py`) so
  VN Python-strings with non-raw escapes (`"\s"` instead of `r"\s"`)
  don't flood stderr during a corpus run.

### What the system does NOT do yet

- **No CI integration** — corpus runs are local only.
  A weekly cron job is planned but not yet wired up.
- **No public badge** — corpus size isn't surfaced
  in the README.
- **No auto-preclassification** — every diagnostic is `unmarked` until
  you manually label it. Many obvious TPs (RPY001 tabs, RPY002 smart
  quotes, RPY107 deprecated APIs) and obvious FPs (RPY202 on built-in
  namespaces) could be auto-labelled by heuristic patterns, leaving
  only the uncertain cases for manual review. (Planned improvement.)
- **No regression tests from synthetic fixtures** (CORPUS-7 pending) —
  `test_corpus_fp.py` is skip-if-corpus-absent, so CI can't catch
  regressions to corpus FPs without the clone. Synthetic minimal
  fixtures derived from real FPs would close this gap.
- **Whole-file reproduction in tests** — the test copies the entire VN
  source file to a tmp game/ dir. For very large files (cross_channel
  has 302 .rpy files, some 4000+ lines), this is wasteful. A future
  iteration can switch to enclosing-block extraction (just the
  `screen`/`label`/`init python:` block containing the flagged line).
- **3 projects without a clear OSS license** — `ddlc_mod_template`,
  `renpy_template_ruolin`, `love69` have no LICENSE file in their repo.
  2 more (`monika_after_story`, `personal_space2`) have a custom license
  GitHub cannot classify (`NOASSERTION`). These are tracked in
  `tests/_corpus_manifest.json` with `license: "none"` / `"NOASSERTION"`
  and TODO notes. Before inviting public contributors to the corpus
  workflow, the maintainer should either obtain permission for these
  projects or replace them with licensed alternatives.
- **No fingerprint validation in RED tests** — `test_corpus_fp.py`
  doesn't yet verify that the cloned commit SHA matches the fingerprint
  recorded in `tests/_corpus_triage.json`. If a VN project updates
  upstream, the line numbers in the triage may no longer correspond to
  the labelled FP. (Planned for Batch 3 — fingerprint validation guard.)

---

## File inventory

### Committed (in the repo)

| Path | Purpose |
| ---- | ------- |
| `scripts/collect_corpus.py` | Shallow-clone 15 OSS VN projects; updates manifest commit field after each clone |
| `scripts/run_corpus.py` | Run senpy on the corpus, write JSON + baseline |
| `scripts/triage_corpus.py` | Interactive + CSV triage of diagnostics |
| `scripts/README.md` | One-liner per script (reference, not workflow) |
| `tests/rules/test_corpus_fp.py` | RED tests auto-discovered from triage.json |
| `tests/_corpus_manifest.json` | Curated manifest: slug / repository / pinned commit / license / renpy_version / notes per project |
| `tests/_corpus_baseline.json` | Committed baseline (anonymised counts, `git:` fingerprint prefix) |
| `tests/_corpus_triage.json` | Committed triage state (anonymous, with notes, `git:` fingerprint prefix) |
| `docs/corpus-workflow.md` | This document |
| `.gitignore` entry for `tests/_corpus/` | VN bytes never enter the repo |

### Gitignored (local only)

| Path | Purpose |
| ---- | ------- |
| `tests/_corpus/<slug>/` | Shallow-cloned VN source (15 projects, ~1.5–2 GB) |
| `tests/_corpus/<slug>/.cloned_sha` | Pinned commit SHA for upstream-movement detection |
| `tests/_corpus/<slug>/senpy_results.json` | Full diagnostics list per project (for triage) |
| `tests/_corpus/_corpus_triage.csv` | CSV export for bulk labelling in a spreadsheet |

### Generated at runtime (not stored)

| Path | Purpose |
| ---- | ------- |
| `tests/_corpus/<slug>/.senpy_cache/` | Senpy analyzer disk cache (Tier 1 + Tier 2). Safe to delete — `no_cache=True` in `run_corpus.py` bypasses it anyway. |

---

## Troubleshooting

### `python scripts/collect_corpus.py` fails on one project

**Symptom:** one project fails to clone (network error, rate limit,
repo moved), others succeed.

**Fix:** the script is idempotent — re-run it and it'll skip already-cloned
projects. If a specific project persistently fails:

```bash
python scripts/collect_corpus.py --only <failing_slug> --force
```

If the repo has moved or been deleted, open an issue — the catalog in
`scripts/collect_corpus.py:PROJECTS` needs updating.

### `python scripts/run_corpus.py` reports all projects as `NEW`

**Symptom:** every project shows `NEW — no baseline entry` in the drift
report.

**Cause:** first run, no baseline exists yet.

**Fix:** run with `--update-baseline` once to initialise it, then commit
`tests/_corpus_baseline.json`.

### `pytest tests/rules/test_corpus_fp.py` collects 0 tests

**Cause 1:** corpus clone is absent → the whole module skips. Run
`python scripts/collect_corpus.py` to clone.

**Cause 2:** corpus is present but `_corpus_triage.json` has no `fp`
entries → no parametrised cases are generated. Run
`python scripts/triage_corpus.py --slug <name>` and label some
diagnostics as `fp`.

A guard test (`test_triage_json_has_fp_cases_or_corpus_absent`) fails
loudly in cause 2 to nudge you towards triaging.

### SyntaxWarning noise during `run_corpus.py`

**Symptom:** stderr floods with `<unknown>:N: SyntaxWarning: "\s" is an
invalid escape sequence`.

**Status:** fixed in 0.9.3 — `ast.parse()` calls are wrapped in
`parse_python_silent()` (in `senpy/text_utils.py`) which suppresses
`SyntaxWarning` without affecting `SyntaxError` (which RPY110 needs).

If you still see these warnings, you may be running an older Senpy
version — `git pull` and re-run.

### `triage_corpus.py --slug <name>` shows "no senpy_results.json"

**Cause:** `run_corpus.py` wasn't run for that project, or
`tests/_corpus/<slug>/senpy_results.json` was deleted.

**Fix:**
```bash
python scripts/run_corpus.py --only <name>
python scripts/triage_corpus.py --slug <name>
```

### Corpus clone takes too much disk space

**Symptom:** `tests/_corpus/` exceeds 2 GB.

**Fix:** the clones are shallow (`--depth 1`), but some projects are
large. To clean up entirely:

```bash
rm -rf tests/_corpus/
python scripts/collect_corpus.py   # re-clone fresh
```

To remove just one project:

```bash
rm -rf tests/_corpus/<slug>/
```

The next `collect_corpus.py` run will re-clone only the missing ones.

### Triage state got out of sync with the actual VN source

**Symptom:** triage.json references diagnostics that no longer appear in
`senpy_results.json` after a re-clone (the VN project upstream changed).

**Fix:** `triage_corpus.py --import-csv` silently drops labels for
diagnostics that no longer exist in the result JSON (this is by design
— the corpus moved, the label is stale). Re-run triage for the affected
project:

```bash
python scripts/run_corpus.py --only <slug>
python scripts/triage_corpus.py --slug <slug>
```

The `fingerprint` field in both `baseline.json` and `triage.json` lets
you detect this — if the fingerprint moved, the upstream commit
changed.

---

## See also

- [RULES.md](../RULES.md) — what each of the 53 rules is supposed to catch
- [ARCHITECTURE.md](../ARCHITECTURE.md) — Senpy internals (analyzer pipeline, checkers, LSP)
- [CONTRIBUTING.md](../CONTRIBUTING.md) — general contributor guide (this doc is linked from section 6)
- [scripts/README.md](../scripts/README.md) — one-liner reference for every script in `scripts/`
- [docs/FORMAT_STYLE_GUIDE.md](FORMAT_STYLE_GUIDE.md) — analogous workflow doc for the formatter
