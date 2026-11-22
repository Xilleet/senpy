# scripts/ — tooling for senpy

This directory holds **scripts** — not runtime code. None of
them are imported by `senpy` itself; they are run by hand (or by CI) to
regenerate generated modules, scrub stale data, sync docs, and drive
the corpus FP/FN pipeline. Outputs that must ship in the wheel are
committed to the repo after running; the scripts are not auto-run in
CI unless explicitly invoked.

Таблица ниже — что за что отвечает. Все команды запускать из корня
репозитория (`senpy/`), а не из `scripts/`.

---

## Inventory / Содержимое

| Script / Скрипт | Group / Группа | One-liner (EN) / Кратко (RU) |
| -- | -- | -- |
| [`fetch_renpy_docs.py`](#fetch_renpy_docspy) | API / Ren'Py docs | Parse Ren'Py Sphinx RST → generate `senpy/domain/renpy_api_generated.py` |
| [`update_renpy_api.py`](#update_renpy_apipy) | API / Ren'Py docs | Check + update the pinned Ren'Py docs source / version label |
| [`diff_renpy_api.py`](#diff_renpy_apipy) | API / Ren'Py docs | Diff two `renpy_api_generated.json` snapshots (working tree vs HEAD) |
| [`update_unrpyc_pin.py`](#update_unrpyc_pinpy) | Vendored libs | Update the pinned unrpyc commit + SHA256 in `senpy/cli/unrpyc.py` |
| [`check_cycles.py`](#check_cyclespy) | Codebase hygiene | Static detector of circular imports in `senpy/` |
| [`clean_internal_ids.py`](#clean_internal_idspy) | Codebase hygiene | Scrub internal task IDs from user-facing files |
| [`restructure_senpy.py`](#restructure_senpypy) | Codebase hygiene | Auto-restructure `senpy/` flat layout → hierarchical folders |
| [`sync_rule_count.py`](#sync_rule_countpy) | Docs / badges | Sync the rule count across all documentation files |
| [`update_badges.py`](#update_badgespy) | Docs / badges | Collect-only tests + write dynamic badge JSON to `.github/badges/` |
| [`push_badges_to_gist.py`](#push_badges_to_gistpy) | Docs / badges | Push `.github/badges/*.json` to a GitHub Gist (no commit-back) |
| [`collect_corpus.py`](#collect_corpuspy) | Corpus | Shallow-clone 15 OSS VN projects into `tests/_corpus/` (gitignored) |
| [`run_corpus.py`](#run_corpuspy) | Corpus | Run senpy on the corpus → per-project JSON + `tests/_corpus_baseline.json` |
| [`triage_corpus.py`](#triage_corpuspy) | Corpus | Triage corpus diagnostics into TP/FP/maybe-FP → `tests/_corpus_triage.json` (CSV + interactive) |

---

## API / Ren'Py docs / Документация Ren'Py

### `fetch_renpy_docs.py`

**EN:** Fetch Ren'Py documentation from GitHub and generate an API
definition module (`senpy/domain/renpy_api_generated.py`). Parses RST
docs for `config.*` / `gui.*` / `build.*` variables, style/transform
properties, classes, screen actions, and `:var:` namespace entries.
The output is a Python dict literal that ships in the wheel without
an extra JSON read at import time. Manually invoked by maintainers;
output is committed. Pin to a specific commit via
`senpy/domain/data/renpy_api_source.yaml`.

**RU:** Скачивает документацию Ren'Py с GitHub и генерирует модуль с
API-определениями (`senpy/domain/renpy_api_generated.py`). Парсит RST:
переменные `config.*` / `gui.*` / `build.*`, style/transform-properties,
классы, screen actions, `:var:` namespace entries. На выходе — Python
dict-literal, который едет в wheel без дополнительного JSON-чтения на
import. Запускается вручную, результат коммитится. Пин к конкретному
коммиту — через `senpy/domain/data/renpy_api_source.yaml`.

```bash
python scripts/fetch_renpy_docs.py            # writes generated module
python scripts/fetch_renpy_docs.py --dry-run  # print summary only
```

### `update_renpy_api.py`

**EN:** Update the pinned Ren'Py API docs source ref + regenerate the
JSON. Reads `senpy/domain/data/renpy_api_source.yaml`, verifies SHA256
of the downloaded docs, then delegates to `fetch_renpy_docs.py`. Use
`--check` in CI to fail when the pin drifts; use `--version X.Y.Z` to
set the version label.

**RU:** Обновляет запиненный источник документации Ren'Py и
регенерирует JSON. Читает `senpy/domain/data/renpy_api_source.yaml`,
проверяет SHA256 скачанного, делегирует генерацию в
`fetch_renpy_docs.py`. `--check` в CI падает при дрейфе пина;
`--version X.Y.Z` задаёт метку версии.

```bash
python scripts/update_renpy_api.py                  # check + update if changed
python scripts/update_renpy_api.py --check          # verify hashes only (no write)
python scripts/update_renpy_api.py --version 8.5.4  # set version label + update
python scripts/update_renpy_api.py --force          # regenerate even if unchanged
```

### `diff_renpy_api.py`

**EN:** Diff two `renpy_api_generated.json` snapshots and print a
human-readable summary (added/removed/changed entries). Default
workflow compares the working tree against `HEAD` after a
`fetch_renpy_docs.py` run, so you can sanity-check a regeneration
before committing.

**RU:** Сравнивает два `renpy_api_generated.json` и печатает
читаемый diff (added/removed/changed). По умолчанию — рабочее
дерево vs `HEAD` после `fetch_renpy_docs.py`, чтобы проверить
регенерацию перед коммитом.

```bash
python scripts/diff_renpy_api.py                        # working tree vs HEAD
python scripts/diff_renpy_api.py old.json new.json      # two explicit files
```

### `update_unrpyc_pin.py`

**EN:** Update the pinned unrpyc commit + SHA256 in
`senpy/cli/unrpyc.py`. Senpy pins unrpyc to a specific git commit
(not `master`) and verifies the SHA256 of the downloaded zip — this
script updates both constants in one command. Run it when bumping
the unrpyc pin (typically after a new unrpyc release or a security
fix).

**RU:** Обновляет запиненный unrpyc-коммит + SHA256 в
`senpy/cli/unrpyc.py`. Senpy пиннит unrpyc к конкретному коммиту (не
к `master`) и проверяет SHA256 zip — этот скрипт обновляет обе
константы одной командой. Запускать при бампе пина (после релиза
unrpyc или security-фикса).

```bash
python scripts/update_unrpyc_pin.py <new-commit-sha> <new-version-tag>
python scripts/update_unrpyc_pin.py --help   # full options
```

---

## Codebase hygiene / Гигиена кодовой базы

### `check_cycles.py`

**EN:** Static detector of circular imports in `senpy/`. Builds the
import graph by parsing each module's imports, then runs cycle
detection. Exit 0 (no cycles) or 1 (cycles found). Use `--verbose`
to print the full graph. Run in CI / pre-commit to catch
import-cycles early.

**RU:** Статический детектор циклических импортов в `senpy/`. Строит
граф импортов, ищет циклы. Exit 0 (чисто) или 1 (есть циклы). С
`--verbose` печатает полный граф. В CI / pre-commit — ловит циклы
на ранней стадии.

```bash
python scripts/check_cycles.py            # check, exit 0/1
python scripts/check_cycles.py --verbose  # print the full graph
```

### `clean_internal_ids.py`

**EN:** Scrub internal task IDs from
user-facing files (docstrings, comments, error messages). Internal
tracker references should not leak into shipped code. `--dry-run`
shows the diff; `--apply` writes changes; `--paths` restricts the
scope.

**RU:** Чистит внутренние task-ID из
пользовательских файлов (docstring'и, комментарии, error messages).
Внутренние ссылки на трекер не должны попадать в shipped-код.
`--dry-run` показывает diff; `--apply` применение; `--paths` ограничивает
область.

```bash
python scripts/clean_internal_ids.py --dry-run                            # show diff, write nothing
python scripts/clean_internal_ids.py --apply                              # write changes
python scripts/clean_internal_ids.py --apply --paths senpy/ tests/        # restrict scope
```

### `restructure_senpy.py`

**EN:** Auto-restructure `senpy/` from a flat layout (`senpy/*.py`)
into the hierarchical layout (`senpy/{core,rules,lsp,cli,formats,
domain}/*.py`). One-shot migration tool used during the original
restructure; kept for reference / re-runs after major refactors.
**Safety:** writes a migration plan first; `--dry-run` shows it
without moving files.

**RU:** Автоматически реструктурирует `senpy/` из плоской структуры
(`senpy/*.py`) в иерархическую (`senpy/{core,rules,lsp,cli,formats,
domain}/*.py`). Одноразовый миграционный скрипт (использовался при
исходной реструктуризации); оставлен для референса и повторных
запусков после крупных рефакторов. Сначала пишет план миграции;
`--dry-run` показывает его без перемещения файлов.

```bash
python scripts/restructure_senpy.py --dry-run   # show migration plan
python scripts/restructure_senpy.py --apply     # move files per plan
python scripts/restructure_senpy.py --help      # full options
```

---

## Docs / badges / Документация и бейджи

### `sync_rule_count.py`

**EN:** Sync the rule count across all documentation files
(README, docs, etc.) so the "N rules" headline stays consistent
with `senpy/rules/RULES_DATABASE`. Run after adding / removing a
rule. `--check` exits 1 if any file is stale (CI guard).

**RU:** Синхронизирует счётчик правил во всех документационных
файлах (README, docs, ...), чтобы заголовок "N правил" совпадал с
`senpy/rules/RULES_DATABASE`. Запускать после добавления / удаления
правила. `--check` падает, если какой-то файл устарел.

```bash
python scripts/sync_rule_count.py            # sync (update files)
python scripts/sync_rule_count.py --check     # exit 1 if stale
```

### `update_badges.py`

**EN:** Update dynamic badges for senpy — collects tests + coverage
+ speed metrics and writes the badge JSON to `.github/badges/`.
`--run` does the full run (tests + coverage + speed); bare invocation
does collect-only tests + static badges. `--check` exits 1 if any
badge would change (CI guard).

**RU:** Обновляет динамические бейджи — собирает метрики тестов /
покрытия / скорости и пишет badge-JSON в `.github/badges/`. Без
флагов — collect-only тесты + статические бейджи; `--run` — полный
прогон. `--check` падает, если любой бейдж изменился бы.

```bash
python scripts/update_badges.py            # collect-only tests + static badges
python scripts/update_badges.py --run      # full run (tests + coverage + speed)
python scripts/update_badges.py --check    # exit 1 if any badge would change
```

### `push_badges_to_gist.py`

**EN:** Push badge JSON files from `.github/badges/` to a GitHub
Gist. Replaces the old "commit-back to main" pattern that caused
merge conflicts between the maintainer's pushes and CI's
badge-update commits. With a Gist, CI writes badge JSON to a
separate storage that does not touch the `main` branch — no race
condition, no merge commits, no badge noise in the git log.
Requires `GITHUB_TOKEN` (or `GH_TOKEN`) env var.

**RU:** Пушит badge-JSON из `.github/badges/` в GitHub Gist. Заменяет
старый паттерн "коммит обратно в main", который вызывал merge
conflicts между пушами и CI-коммитами бейджей. Gist —
отдельное хранилище, не трогает `main`. Нужен `GITHUB_TOKEN` (или `GH_TOKEN`) в
env.

```bash
python scripts/push_badges_to_gist.py            # push all badge JSON to Gist
python scripts/push_badges_to_gist.py --dry-run  # show what would be pushed
```

---

## Corpus / Корпус

The corpus pipeline catches false positives / false negatives in
the senpy rule set against real-world VN code.

Пайплайн корпуса ловит FP/FN в правилах senpy на реальном VN-коде.

### `collect_corpus.py`

**EN:** Clone a curated corpus of 15 open-source Ren'Py VNs into
`tests/_corpus/<slug>/` (shallow clone, `--depth 1`). Idempotent —
skips projects that already have a `.git` dir unless `--force`
re-clones them. Records the cloned commit SHA in
`tests/_corpus/<slug>/.cloned_sha` so `run_corpus.py` can detect
upstream movement. `tests/_corpus/` is gitignored — VN bytes never
enter the repo.

**RU:** Клонирует корпус из 15 open-source VN на Ren'Py в
`tests/_corpus/<slug>/` (shallow, `--depth 1`). Идемпотентный —
пропускает уже клонированные, если не передан `--force` (тогда
удаляет и клонирует заново). Записывает SHA клонированного коммита
в `tests/_corpus/<slug>/.cloned_sha`, чтобы `run_corpus.py` мог
детектить upstream-movement. `tests/_corpus/` в `.gitignore` —
VN-байты не попадают в репо.

```bash
python scripts/collect_corpus.py                 # clone all 15
python scripts/collect_corpus.py --list          # print the catalog (no network)
python scripts/collect_corpus.py --only ddlc     # clone one by slug
python scripts/collect_corpus.py --force         # re-clone existing
python scripts/collect_corpus.py --dry-run        # plan only, no clone
```

### `run_corpus.py`

**EN:** Run senpy on each corpus project and emit per-project JSON
diagnostics to `tests/_corpus/<slug>/senpy_results.json` (gitignored
local artefact). Optionally regenerates `tests/_corpus_baseline.json`
(committed contract — anonymised counts: fingerprint, total,
by_code, by_severity). Without `--update-baseline`, compares the
run against the baseline and reports drift (exit 1 on delta — this
is what the weekly CI job catches). Auto-detects the
`game/` directory at any nesting depth and passes its parent as
`project_path` to `SenpyAnalyzer`.

**RU:** Запускает senpy на каждом проекте корпуса, пишет
per-project JSON diagnostics в `tests/_corpus/<slug>/
senpy_results.json` (gitignored, локальный артефакт). Опционально
регенерирует `tests/_corpus_baseline.json` (коммитится — анонимные
счётчики: fingerprint, total, by_code, by_severity). Без
`--update-baseline` сравнивает прогон с baseline и рапортует
дрейф (exit 1 при delta — это и ловит еженедельный CI job).
Auto-detect'ит каталог `game/` на любой глубине вложенности и
передаёт его родитель как `project_path` в `SenpyAnalyzer`.

```bash
python scripts/run_corpus.py                          # run all
python scripts/run_corpus.py --only gifting_game       # run one
python scripts/run_corpus.py --update-baseline         # regen baseline (committable)
python scripts/run_corpus.py --list                   # plan only (cloned? + game/ path)
python scripts/run_corpus.py --json-only gifting_game  # full JSON to stdout (for triage)
```

### `triage_corpus.py`

**EN:** Triage senpy corpus diagnostics into TP / FP / maybe-FP / skip.
Reads the per-project JSON written by `run_corpus.py` and lets a
maintainer classify every diagnostic against the actual VN source.
Hybrid interface: `--export-csv` dumps every diagnostic to
`tests/_corpus/_corpus_triage.csv` (gitignored) for offline labelling
in a spreadsheet; `--import-csv` reads the labelled CSV back and
writes `tests/_corpus_triage.json` (committed — anonymous triage
state, no VN source); `--slug <name>` walks one project
interactively (per-diagnostic prompt, EOF / `q` keeps current);
`--summary` prints per-project + overall TP / FP / maybe-FP /
unmarked counts. Downstream CORPUS-5 turns every FP / maybe-FP
into a RED pytest.

**RU:** Triage диагностик senpy на корпусе в TP / FP / maybe-FP /
skip. Читает per-project JSON от `run_corpus.py` и позволяет
 классифицировать каждый diagnostic против реального
VN-кода. Гибрид: `--export-csv` выгружает все diagnostic'и в
`tests/_corpus/_corpus_triage.csv` (gitignored) для оффлайн-разметки
в таблице; `--import-csv` читает размеченный CSV и пишет
`tests/_corpus_triage.json` (коммитится — анонимное triage-состояние,
без VN-кода); `--slug <name>` — интерактив по одному проекту
(per-diagnostic промпт, EOF / `q` сохраняет текущий статус);
`--summary` печатает per-project + общий TP / FP / maybe-FP /
unmarked. Дальнейший CORPUS-5 превращает каждый FP / maybe-FP в
RED pytest.

```bash
python scripts/triage_corpus.py --export-csv           # bulk dump to CSV (label offline)
python scripts/triage_corpus.py --import-csv            # read labelled CSV -> triage.json
python scripts/triage_corpus.py --slug gifting_game     # interactive triage for one project
python scripts/triage_corpus.py --summary               # per-project + overall counts
python scripts/triage_corpus.py --summary --status fp   # FP count only
```

---

## Conventions / Конвенции

- **Run from the repo root.** All commands above assume `cwd =
  senpy/` (the directory that contains `scripts/`, `senpy/`, `tests/`).

  Скрипты запускать из корня репо (`senpy/`).

- **Dry-run is your friend.** Every script that writes has a
  `--dry-run` / `--check` — run it before `--apply` to preview.

  У каждого пишущего скрипта есть `--dry-run` / `--check` —
  проверяйте перед `--apply`.
