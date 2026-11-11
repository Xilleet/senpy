<p align="center">
  <a href="README.md"><b>English</b></a> | <a href="README_ru.md"><b>Русский</b></a>
</p>

# Senpy (`senpy-linter`)

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="https://www.renpy.org/"><img src="https://img.shields.io/badge/Ren'Py-6.99%20%7C%207%20%7C%208-ff69b4?logo=renpy&logoColor=white" alt="Ren'Py 6.99 / 7 / 8"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="Лицензия: MIT"></a>
  <br>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-blue" alt="Платформы: Windows | Linux | macOS">
  <img src="https://img.shields.io/badge/Plugins-API%20v1.0-teal" alt="API плагинов v1.0">
  <a href="https://github.com/Xilleet/senpy/actions"><img src="https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/Xilleet/0f6886d60299e1afccce9e892db22085/raw/tests.json" alt="Тесты (автообновление через CI)"></a>
  <a href="RULES.md"><img src="https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/Xilleet/0f6886d60299e1afccce9e892db22085/raw/rules.json" alt="Правила (автообновление через CI)"></a>
  <a href="ARCHITECTURE.md"><img src="https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/Xilleet/0f6886d60299e1afccce9e892db22085/raw/lsp.json" alt="LSP-обработчики (автообновление через CI)"></a>
  <a href="https://github.com/Xilleet/senpy/actions"><img src="https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/Xilleet/0f6886d60299e1afccce9e892db22085/raw/coverage.json" alt="Покрытие кода (автообновление через CI)"></a>
  <a href="https://github.com/Xilleet/senpy/actions"><img src="https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/Xilleet/0f6886d60299e1afccce9e892db22085/raw/speed.json" alt="Скорость (автообновление через CI)"></a>
  <a href="https://github.com/Xilleet/senpy/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Xilleet/senpy/ci.yml?branch=main&label=CI" alt="Статус CI"></a>
</p>

<p align="center">
  <b>«Notice me, Senpy! (⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄)»</b><br>
  <i>Senpy — быстрый статический анализатор, семантический линтер, инструмент для анализа потока управления, а также языковой сервер для VS Code, предназначенный для визуальных новелл на движке Ren'Py. Позволяет обнаруживать неопределенные переменные, неработающие метки (labels), ошибки в логике потока управления, проблемы с откатом (rollback) или сохранением игры, ошибки в переводах и многое другое.</i>
</p>

![](https://github.com/Xilleet/senpy/blob/main/docs/images/senpy-lsp-demo.gif)

---

## Быстрая установка

**CLI / CI / Linux / macOS:**
```bash
pip install senpy-linter
```

**Расширение для VS Code (Windows, без установки Python):**
Скачайте `senpy-vscode-X.X.X.vsix` со страницы [Releases](https://github.com/Xilleet/senpy/releases) → Установить из VSIX в VS Code.

---

## Статус: заморозка фичей → 1.0

Senpy 0.9.0 production-stable для пользователей. До 1.0 фокус — на
hardening архитектуры и стабилизации контракта `senpy.api` —
**без новых правил, без новых фичей, без новых форматов вывода**.

Почему: ядро накопило architectural debt, на который changelog намекает. Симптомы видны в коде: facade-врапперы в `analyzer.py`,
стирающие типизацию, LSP-стейт в module-level globals (97
cyclic-import workarounds через `TYPE_CHECKING` / lazy import),
oversized-модули (`python_ast.py` 2143 строки, `lsp/handlers/navigation.py`
1326 строк), тесты, coupled с internals (485 импортов из
`senpy.core/rules/cli/lsp` против 18 из публичного `senpy.api`).
Хочу закрыть это системно до объявления 1.0 API stability.

**Что принимается во время заморозки:** bug fixes, false-positive
репорты, security advisories, улучшения документации.

**Что отложено до post-1.0:** новые правила (расширение RPY0xx–RPY8xx,
RPY9xx plugin ecosystem), новые форматы вывода, новые CLI-генераторы,
расширение форматтера, sandbox R&D, editor-клиенты вне VS Code.

---

## Что нового

### 0.9.0 — Security hardening + soundness + FP-фиксы из фидбэка пользователей

Minor-релиз: закрыты **6 задач** из post-0.8.4 плюс
**4 false-positive фикса** из фидбэка. Два новых
public API:
- **Trust store schema v2** с авто-миграцией из v1 — добавлено
  поле `audit_warnings` для будущего plugin import-time audit.
- **Runtime-расширение Ren'Py builtins через `senpy.toml [tool.senpy]`**
  — списки `additional_builtins` / `additional_actions` позволяют
  объявлять сторонние namespace'ы (например `iap`, `updater`) и
  кастомные Action-классы, чтобы RPY202 / RPY103 / RPY206 на них не
  срабатывали.

**1964 теста** (было 1836 в 0.8.4, +128). Новых правил нет — все
изменения: correctness-fixes, security-hardening и инфраструктура для
будущих plugin audit / branch-clear / cross-process cache lock (запланированы на 0.9.1).

| Область | Что было сломано | Что изменилось |
|---|---|---|
| **Trust store schema** | Нет versioning schema — любое изменение формата молча «обнуляло» trust для всех ранее доверенных плагинов. | Schema bumped to v2, auto-migration при чтении, добавлено поле `audit_warnings` для R-P0-1. |
| **Унификация терминаторов** | Три источника правды: `RE_TERMINATOR` (вкл. `call`) и два inline-regex'а в `state.py` / `flow.py` (без `call`). Могли разойтись. | `RE_BRANCH_TERMINATOR` вынесен в `core/constants.py`. Inline regex'ы заменены. Поведение не изменилось (чистый refactor). |
| **Severity RPY000** | Синтетический `RPY000` («Senpy internal error») отсутствовал в `RULES_DATABASE` — `senpy rule show RPY000` печатал "Unknown rule code", а `_apply_severity` понижал до WARNING. | Зарегистрирован в `RULES_DATABASE` с `severity=ERROR` и `tags=["internal"]`. `senpy rule list` показывает отдельную секцию "Internal". RULES.md получил секцию "Internal (RPY000)". |
| **`generate_defaults_file` error handling** | `open(out_file, "w")` без try/except — `OSError` (read-only `game/`, disk full, path too long) валил CLI с raw traceback. | Ловит `OSError`, логирует WARNING, записывает `failed_writes`, возвращает `("", 0)`. Exit code = 1. |
| **`_write_fixed_file` UnicodeEncodeError** | Ловил только `OSError` — `--fix`-ран с lone surrogate поднимал `UnicodeEncodeError`, классифицировался как RPY000, exit code 0. | Ловит `(OSError, UnicodeEncodeError)`. Atomic write через `tempfile.mkstemp` + `os.replace`. Read-only файлы детектируются заранее. |
| **RPY202 FP на `achievement.X`** | `BUILTIN_SYMBOLS` не содержал `achievement` — Ren'Py ships it as runtime-provided namespace. Добавлен. | Ren'Py builtins консолидированы в `senpy/core/renpy_builtins.py` (single source of truth). Расширение через `senpy.toml additional_builtins`. |
| **RPY206 FP на `GamepadCalibrate()`** | `BUILTIN_ACTIONS` не содержал `GamepadCalibrate` — задокументированный Ren'Py action. Добавлен. | Та же консолидация в `renpy_builtins.py`. Расширение через `additional_actions`. |
| **RPY202 FP на tuple-unpacking for-loops в screens** | `RE_FOR_LOOP` regex матчил только `for x in ...:` (один идентификатор) — silently пропускал `for i, (a, b, c) in enumerate(...)`. | AST-based хелпер `extract_for_targets` в `text_utils.py` покрывает все Python for-target shapes. |
| **RPY103 FP на for-loop targets в `init python:` / label body** | For-loop targets регистрировались только внутри screens; `init python:` и label bodies их пропускали. RPY103 срабатывал на `if fn.lower()...:` внутри `for fn in ...:`. | `extract_for_targets` интегрирован в три точки: `StateChecker.check_line`, `_check_python_block`, `_check_python_inline`. Плюс `_handle_init_python_block` теперь принимает `scope_stack`. |
| **`init python hide:` не распознавался `RE_INIT_PYTHON_START`** | Regex не включал `hide` keyword — `init python hide:` блоки молча падали в per-line `check_line` dispatch вместо AST-анализа. | Добавлен `(?:\s+hide)?` в паттерн. RPY110 (Python syntax error) теперь срабатывает и в `init python hide:` блоках. |
| **RPY103/RPY202 stacked дубликаты диагностик** | Одна переменная, упомянутая N раз в одном if-condition, давала N диагностик на одной строке — все на колонке первого вхождения. Визуально: одна squiggly на неправильной колонке. | `seen` set в `_check_undeclared_vars_in_condition` — каждая пара (line, var_name) даёт максимум одну диагностику. Разные undeclared vars всё ещё получают свои. |

**Дополнительно**: atomic writes в `CacheManager.save_manifest` и
`_write_trust_store` (устранён race при конкурентных вызовах), фикс
LSP `Timer.cancel()` race через generation counter, LSP
`autoload_plugins` в `start_lsp()`, тесты cache invalidation при
branch-switch, тест JPEG long APP markers, фикс конфликта docs deps
(`pymdown-extensions` 13.0), удалён мёртвый `_purge_file_symbols`,
фикс обработки UTF-8 BOM.

Полные детали в [`CHANGELOG.md`](CHANGELOG.md#090).

---

### 0.8.4 — Очистка edge-cases: string-literal masking, thread safety, checker isolation

Patch-релиз, закрывающий **19 задач** (edge cases, code quality, partial features) + 2 post-0.8.3 follow-up фикса. **1836 тестов** (было 1816 в 0.8.3, +20). Новых правил нет — все изменения это correctness fixes, isolation hardening, и dead-code removal.

| Область | Что было сломано | Что изменилось |
|---|---|---|
| **`--show-settings` / `--cache-dir`** | N1: `--show-settings` игнорировал `--config`. N2: `--cache-dir` не покрывал sandbox dirs. | Оба wired (P1-5 follow-up). |
| **RPY701 `is_character`** | Substring `"Character" in clean` матчил `NotCharacterRelated()` и string literals. | Regex `\b(?:Character\|DynamicCharacter)\s*\(`. |
| **RPY505 voice loop** | `\bloop\b` матчился внутри `"my loop song.ogg"`. | `strip_string_literals` перед regex. |
| **RPY707 channel** | `register_channel` regex матчился внутри dialogue strings. | `strip_string_literals` перед regex. |
| **RPY707 tie-breaker** | Multi-file channel: declaration line зависел от dict iteration order. | Детерминированный: sort по `(file_path, line_idx)`. |
| **RPY107 triple-quotes** | `_is_in_quotes` не обрабатывал `"""docstrings"""`. | Triple-quote detection. |
| **Plugin `PLUGIN_API_VERSION`** | Без декларации загружался с DEBUG (opt-out). | WARNING + skip (opt-in, fail-safe). |
| **Plugin `_PLUGINS_LOADED`** | Module-level boolean без lock — race condition. | `threading.Lock` вокруг check-and-set. |
| **`SecurityError(ValueError)`** | Наследование от `ValueError` нарушает design principle. | `DeprecationWarning`; будет убрано в 1.0. |
| **Built-in checker isolation** | `_analyze_file` без `try/except` — один баг крашил весь run. | `try/except` + synthesized `RPY000` + continue. |
| **`check_line` signature** | `BaseChecker` (7 args, `tuple[str, bool]`) vs `StateChecker` (8 args, `tuple[int, bool]`). | Унифицировано: 8 args, `tuple[int, bool]`. |
| **GitHub Actions `%`** | `render_github` не экранировал `%` → `%25`. | Добавлен escape. |
| **`render_github` double-print** | Аннотации печатались в stdout AND `--output-file`. | Stdout suppressed when `--output-file` set. |
| **Warnings via stdout** | `console.print` загрязнял JSON/SARIF output. | Роутинг в `stderr`. |
| **Dead unrpyc probe** | `subprocess.run([python, "-m", "unrpyc", "--help"])` — dead code. | Удалён + `import subprocess`. |
| **LSP mode detection** | `"--lsp" in sys.argv` substring check. | `re.match(r"--lsp(?:=\|$)", arg)`. |
| **`--check`/`--diff` doc** | Non-text formats `sys.exit()` до `--check`/`--diff` — недокументировано. | Документировано. |
| **RPA index regression** | `_read_rpa_index` activation ordering — нет regression test. | Regression test добавлен. |

---

### 0.8.3 — Hotfix: сломанные контракты, мёртвые CLI-флаги, консистентность LSP snapshot

Patch-релиз, закрывающий **15 багов** (сломанные контракты, реальные баги с юзер-импактом, edge cases). **1816 тестов** (было 1777 в 0.8.2, +39). Новых правил нет — все изменения это correctness fixes и enforcement CLI-контрактов.

| Область | Что было сломано | Что изменилось |
|---|---|---|
| **Pre-commit hook** | `entry: senpy --check` фейлился только на фиксабельных issue — нефиксабельные ERROR проходили молча. | Переключено на `--errors-only` (фейлится на любом ERROR). |
| **`--strict` / `--fail-on-error`** | Документированы, но отсутствуют в `args.py` — `argparse exit 2`. | Оба флага объявлены и wired; `--strict` промоутит все диагностики в ERROR; `--fail-on-error` + `--exit-zero` rejected. |
| **`--cache-dir` / `--config`** | Распарсены, но никогда не доходили до `CacheManager` / `load_config`. | Wired через `SenpyAnalyzer` constructor; `SENPY_CONFIG` env var поддерживается. |
| **`--statistics` / `--respect-gitignore`** | No-ops (summary table всегда печатается; file discovery использует `IGNORED_DIRS`). | Удалены для честности CLI-контракта. |
| **Production logging** | `setup_logging()` не вызывался — WARNING+ записи шли через `lastResort` на stderr, ломая LSP JSON-RPC transport. | Wired в `cli.runner.main()` и `lsp.server.start_lsp()`. |
| **RPY308/RPY309 terminators** | `$ renpy.full_restart()` / `$ renpy.quit()` не распознавались (whitespace + `$`); `pass` инконсистентно считался terminator. | Унифицированный `RE_TERMINATOR` regex в `constants.py`; `pass` — не terminator. |
| **RPY502 GIF/BMP** | Хардкод `(".png", ".webp", ".jpg", ".jpeg")` без `.gif`/`.bmp` — hover работал, но `show` триггерил RPY502. | Заменён на `IMAGE_EXTENSIONS`. |
| **LSP `prepare_rename`** | Возвращал `None` для variables/transforms/screens — VS Code F2 ничего не делал. | Возвращает Range для всех rename-supported типов символов. |
| **LSP `references`** | Читал live analyzer state — после `did_change`, labels из других файлов исчезали. | Переключено на `_symbol_snapshot` (консистентно с `rename`/`prepare_rename`). |
| **LSP `document_symbols`** | Мутировал `analyzer.file_scopes` под read lock (нарушение `_RWLock` контракта). | Возвращает `[]` если scope missing; нет мутации. |
| **Plugin isolation** | `check()` возвращающий `[None]` или `["string"]` крашил analyzer. | `isinstance(diag, Diagnostic)` validation; bad elements skip с WARNING. |
| **`.senpy-ignore` filename** | `SENPY_OWN_FILES` содержал `.senpyignore` (без дефиса) — реальный `.senpy-ignore` попадал в `senpy inspect` output. | Добавлен `.senpy-ignore`; `.senpyignore` оставлен для backward compat. |

Также: RPY109 fixture был вакуумным (single-file, но RPY109 срабатывает только cross-file) — заменён на реальный cross-file fixture; `--no-cache` parity test добавлен (ловит cache-write bugs); вакуумный `or True` assertion убран из cache characterization test.

---

### 0.8.2 — Очистка ложных срабатываний + фикс CRLF/Windows

Patch-релиз, закрывающий **9 классов ложных срабатываний**, обнаруженных прогоном Senpy 0.8.1 на корпусе из 5 реальных open-source Ren'Py проектов (~174k LOC): DDLC, LearnToCodeRPG, cross_channel локализация, DDLCModTemplate, renpy-template. **1777 тестов** (было 1646 в 0.8.1). Новых правил нет — только исправления корректности. Верификация на корпусе: 8968 → 8485 диагностик (-483 ложных, -5.4%).

| Правило | Что было сломано | Что изменилось |
|---|---|---|
| **RPY309** | Метки, достигаемые из `start` через fall-through (без `return` между соседними метками), попадали в "story islands unreachable from start". | Новое поле `fall_through_to` на `LabelSymbol`, по которому идёт BFS достижимости. 515 ложных срабатываний устранено в cross_channel. |
| **RPY503** | Ассеты, ссылавшиеся через `gui.button_properties("X")` и паттерн `[prefix_]`, попадали в "unused". | Каждая строка сканируется на media-asset литералы; `[prefix_]` разворачивается в 8 стандартных префиксов состояний. 101 ложное срабатывание устранено. |
| **RPY206** | `FilePagePrevious()`, `FilePageNext()`, `InvertSelected()` и ещё 44 built-in screen action фабрики попадали в "executes immediately". | Allowlist `BUILTIN_ACTIONS` расширен с 42 до 91 записи — покрывает всю библиотеку screen actions из доков Ren'Py. |
| **RPY102** | Переменная, присвоенная в теле `if` и использованная в том же теле (например, в вложенном `for`), попадала в "undeclared before declaration". | Каждое тело `if`/`while`/`for`/`try` получает свою копию `local_scope`; присвоенные имена добавляются по мере обхода. |
| **RPY109** | Переменные из `init python:` (приоритет 0) попадали в "init phase dependency violation" при использовании в `init 998 python:` в алфавитно более ранних файлах. | Приоритет init извлекается; alphabetical-check пропускается, если приоритет ссылающегося блока > 0. |
| **RPY110** | `$`-утверждение, открывающее triple-quoted string на одной строке и закрывающее на другой, вызывало "Python syntax error". | `_get_logical_line` теперь джоинит физические строки, пока открыта triple-quoted string, с кумулятивным трекингом состояния. |
| **RPY103** | Параметры экрана, объявленные через `init -501 screen game_menu(title, scroll=None):`, не регистрировались в local scope. | `RE_SCREEN_START` расширен опциональным матчем префикса `init <N> `. |
| **RPY502** | Картинки, зарегистрированные через `renpy.image(NAME, ...)` в `init python:` блоках, не были видны статическому анализатору. | Статический evaluator обходит AST init-python, вычисляет name-аргумент (строковые литералы, loop-переменные, простая конкатенация) и регистрирует картинку. 88 ложных срабатываний устранено в learntocode. |
| **LSP snapshot** | После `did_change` → `analyze_file_only` hover/completion/rename/references читали из устаревшего snapshot — новые символы были невидимы до `did_save`. | `_refresh_symbol_snapshot()` теперь вызывается после `analyze_file_only`. |

Также исправлено: CRLF line endings ломают `textwrap.dedent` на Windows (новый хелпер `dedent_python()`), RPA `_read_rpa_index` активирован (был мёртвым кодом), бейдж тестов больше не желтеет от ожидаемых skip'ов.

---

### 0.8.1 — Хотфикс: закрыты 5 архитектурных кластеров багов

Patch-релиз, закрывающий 19 багов, выявленных после 0.8.0. **1646 тестов** (было 1487 в 0.8.0). Новых правил нет — только исправления корректности и три инфраструктурных теста, которые автоматически ловят регрессии тех же классов в будущем.

| Кластер | Что было сломано | Что изменилось |
|---|---|---|
| **Ложные срабатывания на строковых литералах** | Substring-проверки и regex-сканирования на сырых Ren'Py-строках матчили идентификаторы внутри диалогов или Python-строк. RPY302/202/204 срабатывали на строках вида `"The Jump('foo') action is interesting."`. | Новый хелпер `strip_string_literals()` применяется в каждой точке вызова checker'а — маскирует содержимое литералов пробелами, сохраняя позиции колонок. |
| **Неполное восстановление кэша** | Tier 1/Tier 2 cache hits молча теряли `noqa_maps`, `missing_defaults`, `has_dynamic_jumps` и флаг `enable_plugins`. Cold и warm запуски выдавали разные диагностики. | Per-file персистентность + `enable_plugins` в environment fingerprint. Тест `test_cold_warm_equivalence` навсегда закрепляет контракт. |
| **Поломка исходника QuickFix'ом** | `--fix` и LSP QuickFix создавали невалидный код: RPY401 уничтожал пункты меню, RPY002 дублировал indent, RPY206 терял `action` префикс и аргументы. | Явный контракт range/replacement; `test_quickfix_preserves_validity` прогоняется на всех `bad_*.rpy` фикстурах. |
| **Пробелы в propagation состояния** | `did_close` не отменял pending timers; `analyze_menu_flow` игнорировал pre-menu `guaranteed_vars`; LSP rename переписывал все whole-word вхождения независимо от symbol kind. | Каждый propagation path закрыт; `test_run_idempotency` работает как catch-all guard. |
| **Точность LSP rename** | Rename переменной `score` переписывал и `label score:`, и `jump score`, и natural-language упоминания в диалогах. | Kind-specific predicates фильтруют raw text-search матчи по контексту перед эмиссией `TextEdit`. |

---

### 0.8.0 — Production-stable: security hardening, soundness fixes, plugin API contract

| Функция | Описание |
|---|---|
| **JUnit XML escaping** | `diag.code` и `diag.line_content` теперь HTML-эскейпятся в элементах `<failure>`/`<skipped>`. Исходный код с `<`, `>`, `&` больше не ломает весь JUnit-отчёт для Jenkins/GitLab CI/TeamCity. |
| **`--fix` write failures surfaced** | `_write_fixed_file` больше не проглатывает молча `OSError` (read-only файл, диск полный, permission denied). Неудачные записи логируются как WARNING, фиксируются в `AnalysisResult.failed_writes` и форсируют non-zero exit code — молчаливая потеря данных больше невозможна. |
| **XSS в HTML-отчёте** | `diag.code` и `diag.severity` теперь HTML-эскейпятся перед интерполяцией. Malicious plugin rule code больше не может выполнить JavaScript при открытии `senpy --export-html` в браузере. CSS variable lookup также санитизирован. |
| **Path traversal в LSP hover** | `_resolve_relative_to_game` теперь использует `realpath` + `commonpath` containment check. Malicious `.rpy` с `image evil = "images/../../etc/passwd"` больше не может раскрыть размер/путь системного файла через hover. |
| **Plugin code collision rejected** | `register_loaded_plugins()` теперь отклоняет plugin rules с `code`, конфликтующим с built-in `RULES_DATABASE`. Раньше коллизия фильтровалась только в `senpy rule list` — plugin rule всё равно запускался при анализе. Диапазон `RPY9xx` формально зарезервирован для плагинов. |
| **`--exit-zero` для всех форматов** | Раньше только `render_text` honour'ил `--exit-zero`; остальные 6 рендереров (sarif, json, junit, github, rdjson, gitlab) игнорировали флаг, ломая non-blocking CI workflows вида `senpy --exit-zero --format sarif`. Общий `_exit_code` helper теперь применяет флаг консистентно. |
| **CI бейджи перенесены в Gist** | CI job `update-badges` больше не коммитит `chore(badge): update dynamic badges [skip ci]` обратно в `main` (что вызывало merge-конфликты). Badge JSON пушится в GitHub Gist через API; `main` не трогается. |
| **Сайт документации на MkDocs Material** | Новый `docs/` сайт с 13 страницами (install, configuration, CLI reference, formatter, plugin development, comparison, renpy-* гайды). Деплоится на GitHub Pages через `docs.yml` workflow. |
| **GitHub Release notes авто-генерация** | Release workflow собирает тело релиза из соответствующей `## [X.Y.Z]` секции CHANGELOG + header template — release notes больше не рассинхронизируются с changelog. |
| **`bump_version.py` расширен** | Теперь обновляет 4 hardcoded упоминания версии (`.pre-commit-hooks.yaml`, `.github/release-header.md`, `docs/install.md`, `docs/index.md`), которые раньше устаревали каждый релиз. |
| **Архитектурная чистка** | God-file `SenpyAnalyzer` разбит на `FileCollector` + `AnalysisPipeline` + `SymbolTable` (38 characterization-тестов как safety net). `cli/main.py` разбит на 10 модулей. RWLock миграция завершена. Coverage gate поднят до 80%. |
| **Документация синхронизирована** | `SECURITY.md`, `ARCHITECTURE.md`, `senpy-vscode/README.md`, `docs/comparison.md`, `docs/FORMAT_STYLE_GUIDE.md`, `docs/formatter.md` — всё синхронизировано с текущим кодом. |

Полный changelog: [CHANGELOG.md](https://github.com/Xilleet/senpy/blob/main/CHANGELOG.md)

---

## Почему вам это нужно

`renpy lint` ловит синтаксические ошибки и ошибки ссылок, но баги, которые
действительно доходят до игроков, выходят за рамки его проверки. Ниже — реальные баги, которые Senpy поймал
бы ещё на этапе линтера, до релиза:

### Баг 1 — Поломка сейвов через мутацию `define`

```renpy
define player_gold = 100

label spend_gold:
    $ player_gold -= 50    # ← мутирует `define`
    "У вас [player_gold] золота."
```

**Симптом:** В дев-сборке всё работает. Игроки получают
`Exception: define player_gold is not revertable` при откате, либо файлы
сохранений тихо повреждаются после загрузки старого сейва.

**Senpy ловит:** `RPY105` (мутация define) срабатывает на этапе линтера.

---

### Баг 2 — `NameError` после загрузки сейва

```renpy
label start:
    jump intro

label intro:
    $ greeted = True
    "Привет!"

label continue_story:
    if greeted:    # ← `greeted` не объявлен через `default`
        "Привет снова!"
```

**Симптом:** В первом прохождении всё работает. Игроки, загрузившие сейв
на `continue_story` (минуя `intro`), получают
`NameError: name 'greeted' is not defined`.

**Senpy ловит:** `RPY104` (динамическое присваивание без `default`).

---

### Баг 3 — Асимметрия веток (чтение неинициализированной переменной)

```renpy
label branch_demo:
    menu:
        "Взять меч":
            $ has_sword = True
        "Не брать":
            pass       # ← has_sword не присвоен в этой ветке

    if has_sword:       # ← чтение MAYBE_SET
        "Вы замахиваетесь!"
```

**Симптом:** Работает у игроков, взявших меч. Игроки, прошедшие вторую
ветку, получают `NameError: name 'has_sword' is not defined` (или при откате
переменная тихо сохраняет значение из предыдущего прохождения).

**Senpy ловит:** `RPY404` (чтение MAYBE_SET-переменной) и `RPY401`
(асимметрия веток).

---

### Баг 4 — Неверный метод коллекции (`AttributeError` в рантайме)

```renpy
label add_item:
    $ inventory.add("sword")    # ← у list нет метода .add()
```

**Симптом:** `AttributeError: 'list' object has no attribute 'add'` при
первой попытке игрока подобрать предмет. Протестированные пути это обходят;
нетестированные — падают.

**Senpy ловит:** `RPY108` (несовместимый метод коллекции) с QuickFix,
предлагающим `.append()`.

---

### Баг 5 — Неиспользуемые ассеты (лишний вес в сборке)

```renpy
# 200 определений image, на экране показывается только 30
image bg_old_castle = "old_castle.png"   # ← осталось от вырезанного контента
image bg_old_forest = "old_forest.png"   # ← не используется
```

**Симптом:** Размер сборки раздувается. Игроки качают 500 МБ вместо 200 МБ.
Никто не замечает, пока рецензент в Steam не пожалуется на размер загрузки.

**Senpy ловит:** `RPY701` (неиспользуемый define), `RPY702` (неиспользуемый
transform), `RPY703` (неиспользуемый screen).

---

### Баг 6 — Поломка интерполяции в переводах

```renpy
# game/script.rpy
$ player_name = "Герой"
"Welcome, [player_name]!"     # ← английский оригинал

# game/tl/russian/script.rpy
translate russian welcome_1:
    "Добро пожаловать, [player]!"   # ← опечатка: player вместо player_name
```

**Симптом:** Русскоязычные игроки видят `Добро пожаловать, [player]!`
буквально (переменная интерполяции не существует). Английская сборка
работает нормально.

**Senpy ловит:** `RPY601` (битая переменная интерполяции в переводе).

---

### Закономерность

Каждый из багов выше:

1. Проходит мимо `renpy lint` (который фокусируется на синтаксисе и
   ссылках).
2. Выживает в дев-плейтестах (тестировщики всегда выбирают «интересную»
   ветку).
3. Всплывает только после релиза — через отзывы в Steam, скриншоты в
   Discord или баг-репорты на itch.io.
4. Стоит часов отладки в духе «у меня всё работает», потому что игрок не
   может воспроизвести это у тебя на глазах.

Senpy ловит их на этапе линтера — ещё до того, как они дойдут до игроков.
**Вот почему вам это нужно.**

Полный список из 53 правила с примерами — см.  **[RULES.md](https://github.com/Xilleet/senpy/blob/main/RULES.md)**.

---

## Зачем нужен Senpy?

Встроенная команда `renpy lint` проверяет синтаксис, ссылки и изображения. Однако она не покрывает ошибки выполнения Python, рассинхронизацию отката (rollback) и повреждение файлов сохранений. В результате фатальные `NameError` и `KeyError` часто обнаруживаются игроками лишь спустя десятки часов ручного тестирования.

**Senpy помогает находить такие проблемы до запуска игры:**

- **Высокая скорость и дисковый кэш:** анализирует **более 77 000 строк в 50 файлах за ~3.5 секунды на холодном старте и за 0.04 секунды из кэша**.
- **Граф зависимостей фазы init (RPY109):** отслеживает алфавитный порядок загрузки файлов в `init python:` и ловит падения с `NameError` до старта игры.
- **Трекинг конфликтов типов (RPY108):** выявляет несовместимые `+=` (`str += int`) и опасные перезаписи типов (`int` → `str`), ломающие откат назад.
- **Проверка сигнатур параметров (RPY310, RPY207):** сверяет аргументы при вызовах `call label(...)` и `use screen(...)`.
- **Анализ развилок меню (RPY401, RPY404):** находит переменные, объявленные только в одной ветке `menu:`, и ловит их чтение в статусе `MAYBE_SET`.
- **Контроль сохранений и отката (RPY104–RPY106):** защищает от мутаций констант `define`, нативного `random` и переменных без `default`.
- **Мёртвый код (RPY701–703):** находит неиспользуемые `define`, `transform` и `screen` объявления.
- **Метрики локализации (`--coverage`):** рассчитывает процент готовности перевода по каждому языку в `game/tl/`.
- **Постморт-анализ крашей (`--traceback`):** сопоставляет логи падений (`traceback.txt`) с кодом новеллы и объясняет причины сбоя сценаристу.
- **Безопасное автоисправление (`--fix`):** автоматически исправляет однозначные синтаксические недочёты.
- **Режим цундэрэ (`--tsundere`):** выводит диагностические сообщения в аниме-стилистике.

---

## Senpy vs встроенного `renpy lint`

В Ren'Py есть встроенная команда `lint` (`renpy.exe lint`), но она запускает весь Pygame-движок и ловит только синтаксические проблемы. Senpy — это отдельный статический анализатор, который работает без Ren'Py SDK и ловит другой класс багов.

| Аспект | Встроенный `renpy lint` | Senpy |
|---|---|---|
| **Подход** | Запускает Pygame-движок, исполняет блоки `init python:` | Статический анализ, без SDK |
| **Скорость на 70k строк** | 30–40 секунд | ~3.5 с холодного старта / 0.04 с инкрементально |
| **Безопасность сохранений и отката** | ❌ | ✅ `RPY104`, `RPY105`, `RPY106` |
| **Обнаружение несовпадений в переводах** | ❌ | ✅ `RPY601`, `RPY602`, `RPY603` |
| **Визуализация графа истории** | ❌ | ✅ `senpy --graph` |
| **Обнаружение мёртвого кода** | ❌ | ✅ `RPY701`–`RPY707` |
| **Анализ потока данных в развилках** | ❌ | ✅ `RPY401`, `RPY404` |
| **Граф зависимостей фазы init** | ❌ | ✅ `RPY109` |
| **Готовность к CI (GitHub Actions, SARIF)** | Нужен headless Ren'Py SDK в CI | `pip install senpy-linter` + SARIF-вывод |
| **Интеграция с IDE** | ❌ | ✅ LSP для VS Code (20+ обработчиков) |
| **Что ловит** | Синтаксические ошибки, сломанные `jump`/`call`-цели, отсутствующие изображения | + повреждения сохранений, рассинхрон отката, баги переводов, мёртвый код, конфликты типов, порядок init |
| **Распространение** | Поставляется вместе с Ren'Py SDK | PyPI (`senpy-linter`) + расширение на Open VSX + GitHub Releases |

Эти два инструмента **дополняют друг друга, а не заменяют**. Senpy ловит класс багов, недоступный встроенному `lint` (семантика, сохранения/откат, переводы, поток управления). Запускайте оба: встроенный `lint` для SDK-уровневых проверок, Senpy для всего остального.

---

## Senpy vs `vscode-language-renpy` (официальное расширение)

`vscode-language-renpy` — **официальное** расширение Ren'Py для VS Code (152 ⭐, поддерживается командой Ren'Py). Оно даёт подсветку синтаксиса и базовые сниппеты. Senpy добавляет поверх этого **семантический анализ** — понимает переменные, поток управления, экраны и файлы переводов, а не просто текст.

| Возможность | `vscode-language-renpy` | Senpy |
|---|---|---|
| Подсветка синтаксиса | ✅ | ✅ |
| Языковая конфигурация (скобки, комментарии) | ✅ | ✅ |
| Сниппеты | ✅ базовые | ❌ |
| **Диагностика в реальном времени** | ❌ | ✅ 49+ правил, на каждое нажатие |
| **Переход к определению** | ❌ | ✅ метки, экраны, трансформы, define |
| **Поиск ссылок** | ❌ | ✅ по всему проекту |
| **Документация при наведении** | ❌ | ✅ Ren'Py API + превью ассетов |
| **Переименование символа** | ❌ | ✅ метки, экраны |
| **Семантические токены** | ❌ | ✅ |
| **Визуализация графа истории** | ❌ | ✅ Mermaid-диаграмма развилок |
| **Проверки безопасности сохранений и отката** | ❌ | ✅ |
| **Валидатор переводов** | ❌ | ✅ обнаружение несовпадений в `game/tl/` + покрытие |

Эти два расширения **дополняют друг друга и могут стоять параллельно**. Если нужны и подсветка синтаксиса (официальное), и семантическая диагностика (Senpy) — ставьте оба.

---

## LSP и интеграция с VS Code

Senpy включает полноценную реализацию **Language Server Protocol** с 20+ обработчиками:

| Функция | Горячие клавиши | Описание |
|---|---|---|
| **Диагностика** | автоматически | Ошибки и предупреждения в реальном времени (~0.04с из кэша) |
| **Переход к определению** | `F12` | Переход к метке/экрану/переменной/ассету |
| **Hover** | наведение | Документация для 220+ функций Ren'Py API |
| **Автодополнение** | `Ctrl+Space` | Метки, экраны, трансформы, переменные, атрибуты спрайтов |
| **Символы документа** | `Ctrl+Shift+O` | Дерево меток/экранов/трансформов в файле |
| **Символы проекта** | `Ctrl+T` | Глобальный поиск по всем файлам |
| **Переименование** | `F2` | Переименование метки → обновление всех `jump`/`call` |
| **Найти упоминания** | `Shift+F12` | Все jump/call к метке |
| **Сворачивание кода** | автоматически | Сворачивание `label`/`screen`/`menu`/`init` блоков |
| **Подсветка вхождений** | курсор | Подсветка всех упоминаний слова в файле |
| **QuickFix** | `Ctrl+.` | Автоисправления (табы→пробелы, кавычки, теги) |
| **Цветовые свотчи** | `0.6.0+` | Hex-цвета как кликабельные квадратики с палитрой |
| **Форматирование** | `Shift+Alt+F` | Запуск форматтера Senpy (9 правил) |
| **Подсказки параметров** | `0.6.0+` | Параметры для `call label(...)` / `use screen(...)` |
| **Иерархия вызовов** | `0.6.0+` | ПКМ → «Найти вызывающих» / «Найти ссылки» |
| **Граф сюжета** | команда | Интерактивная блок-схема Mermaid.js всех меток и переходов |

![](https://github.com/Xilleet/senpy/blob/main/docs/images/senpy-vscode-autocomplete.png)

---

## Система плагинов

Senpy 0.6.0 представляет **систему плагинов** — пишите свои правила линтера как pip-пакеты.

### Быстрый старт

```bash
# 1. Создайте проект плагина (см. пример ниже)
cd examples/my_senpy_plugin
pip install -e .

# 2. Запустите Senpy — плагин обнаружится автоматически
senpy /path/to/game
# Первый запуск: "Plugin 'my-senpy-plugin' wants to load. Trust and enable? [y/N]"
```

### Напишите своё правило за 30 строк

Это правило (из `examples/my_senpy_plugin/`) флагует строки диалогов,
не обёрнутые в `_()` для перевода:

```python
from senpy.api import Diagnostic
from senpy.plugins import Rule, RuleContext, RuleMeta, register_rule

PLUGIN_API_VERSION = "1.0"


@register_rule("RPY901")
class HardcodedDialogueRule(Rule):
    meta = RuleMeta(
        code="RPY901",
        docs="Обнаруживает строки диалогов без _() для перевода",
        severity="WARNING",
        tags=["translations", "accessibility"],
    )

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        diags = []
        for line_no, raw in enumerate(ctx.lines, start=1):
            stripped = raw.lstrip(" \t")
            if not stripped or stripped[0] not in ('"', "'"):
                continue
            if stripped.startswith('_("') or stripped.startswith("_('"):
                continue  # уже переведено
            diags.append(
                Diagnostic(
                    file_path=ctx.file_path,
                    line_number=line_no,
                    line_content=raw.rstrip(),
                    code="RPY901",
                    message=f"Жёстко заданный диалог без _() для перевода",
                    severity="WARNING",
                )
            )
        return diags
```

Полный гайд: **[README по разработке плагинов](https://github.com/Xilleet/senpy/blob/main/examples/my_senpy_plugin/MY_SENPY_PLUGIN_README.md)**

---

## Использование

```bash
# Проверить каталог игры
senpy "path/to/game"

# Применить безопасные исправления (теги, кавычки, табы)
senpy "path/to/game" --fix

# Показать, что было исправлено (детальный отчёт)
senpy "path/to/game" --fix --show-fixes

# Посчитать процент готовности перевода в game/tl/
senpy "path/to/game" --coverage

# Сгенерировать документацию (диздок) проекта в Markdown
senpy "path/to/game" --export-wiki "PROJECT_WIKI.md"

# Создать заглушки типов (.pyi) для Pylance / MyPy
senpy "path/to/game" --stubs

# Разобрать краш-лог игры
senpy --traceback "path/to/traceback.txt"

# Создать GitHub Actions workflow в 1 клик
senpy --init-ci

# Создать файл «senpy_defaults.rpy» для защиты файлов сохранений
senpy "path/to/game" --defaults

# Выгрузить граф сюжета в файл Mermaid.js
senpy "path/to/game" --graph-file "story_graph.md"

# Генерация HTML-отчёта с интерактивным графом сюжета
senpy "path/to/game" --export-html "report.html"

# Вывод в формате SARIF, JSON, JUnit XML или GitHub Actions
senpy "path/to/game" --output-format sarif --output-file senpy.sarif
senpy "path/to/game" --output-format json
senpy "path/to/game" --output-format junit
senpy "path/to/game" --output-format github

# Перечислить все доступные правила
senpy --rules

# Включить режим цундэрэ
senpy "path/to/game" --tsundere
```


![](https://github.com/Xilleet/senpy/blob/main/docs/images/senpy-cli-diagnostics.png)

![](https://github.com/Xilleet/senpy/blob/main/docs/images/senpy-summary-table.png)

![](https://github.com/Xilleet/senpy/blob/main/docs/images/senpy-cli-warnings.png)

---

## Справочник диагностик

Senpy включает **51 специализированное семантическое правило** с 28 тегами:

| Серия | Категория | Описание |
| :--- | :--- | :--- |
| **RPY0xx** | Отступы и синтаксис | Табуляция (`RPY001`), типографские кавычки (`RPY002`). |
| **RPY1xx** | Состояние и переменные | Переменные в диалогах, `NameError` на `+=`, мутации `define`, устаревший API (`RPY107`), конфликты типов (`RPY108`), порядок загрузки init (`RPY109`). |
| **RPY2xx** | Экраны и UI | Предиктивные мутации (`RPY201`), мёртвые кнопки (`RPY203`), циклы в экранах (`RPY205`), параметры экранов (`RPY207`). |
| **RPY3xx** | Сюжет и диалоги | Незакрытые теги (`RPY301`), прыжки в никуда (`RPY302`), дубликаты меток (`RPY307`), сюжетные острова (`RPY309`), параметры вызовов (`RPY310`). |
| **RPY4xx** | Развилки и логика | Асимметрия в `menu:` (`RPY401`), пустые выборы (`RPY402`), противоречия (`RPY403`), чтение `MAYBE_SET` (`RPY404`). |
| **RPY5xx** | Ресурсы и медиа | Потерянные аудиофайлы (`RPY501`), ненайденные спрайты (`RPY502`), неиспользуемые ассеты (`RPY503`), незарегистрированные каналы (`RPY505`). |
| **RPY6xx** | Локализация | Рассинхрон переменных (`RPY601`), рассинхрон тегов (`RPY602`), пустые строки (`RPY603`). |
| **RPY7xx** | Мёртвый код | Неиспользуемые `define` (`RPY701`), неиспользуемые `transform` (`RPY702`), неиспользуемые `screen` (`RPY703`). |

Подробные пояснения и примеры кода: **[RULES.md](https://github.com/Xilleet/senpy/blob/main/RULES.md)**

---

## Настройка (`senpy.toml`)

```toml
[tool.senpy]
decompile = true
max_errors = 50

ignore = [
    "RPY104",  # Игнорировать динамические присваивания
    "RPY303",  # Игнорировать метки, недостижимые статически
]

[tool.senpy.severity]
RPY104 = "ERROR"   # Повысить до критической
RPY308 = "INFO"    # Понизить до информационной
```

### Подавление отдельных предупреждений (`# noqa`)

```renpy
"Warning: {b}unclosed style"  # noqa
$ dynamic_var = 1              # noqa: RPY104
```

### Подавление на уровне проекта (`.senpy-ignore`)

Для массового исключения правил создайте файл `.senpy-ignore` в корне
проекта (рядом с `senpy.toml`). Каждая строка — код правила для
подавления:

```text
# .senpy-ignore — по одному коду правила на строку
RPY101  # опечатка в переменной диалога
RPY104
# RPY105  # закомментировано — правило сработает
RPY301
```

Строки, начинающиеся с `#`, — комментарии. Внутристрочные комментарии
(после кода правила) разрешены. Коды нечувствительны к регистру
(нормализуются к верхнему).

---

## Интеграция с GitHub Actions

```bash
senpy --init-ci  # генерирует .github/workflows/senpy.yml
```

Или создайте файл `.github/workflows/senpy.yml` вручную:

```yaml
name: Senpy Code Scanning
on:
  pull_request:
    branches: [ "main", "master" ]
jobs:
  lint:
    runs-on: ubuntu-latest
    permissions:
      security-events: write
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install senpy-linter
      - run: senpy game/ --output-format sarif --output-file senpy.sarif
        continue-on-error: true
      - uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: senpy.sarif
```

---

## Интеграция с pre-commit

Senpy поставляет [pre-commit](https://pre-commit.com) хук, который
запускает `senpy --errors-only` на каждом коммите. Добавьте в ваш
`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/Xilleet/senpy
    rev: v0.8.4   # используйте последний тег
    hooks:
      - id: senpy
```

Хук **только проверяет, не исправляет**. Используется `--errors-only`,
чтобы гейт фейлился (exit 1) на любой ERROR-диагностике, включая
нефиксабельные (неопределённые переменные, мёртвые label'ы и т.д.).
WARNING и INFO скрыты из лога pre-commit; для полной картины
запускайте `senpy` вручную без `--errors-only`.

Только проверять — это намеренно. Автофиксящий хук в комбинации с
git `autocrlf` на Windows создаёт бесконечный цикл (форматтер
нормализует переводы строк, git конвертирует обратно, форматтер
запускается снова). Запускайте `senpy --fix` вручную, если нужны
автоисправления.

---

## Декомпиляция `.rpyc` без изменения каталога игры

В готовых сборках и модификациях исходные `.rpy` могут отсутствовать, в это же время Senpy:

1. Копирует `.rpyc` во временный каталог операционной системы.
2. Предлагает загрузить `unrpyc` из GitHub, если он не установлен.
3. Выполняет анализ скриптов во временной песочнице.
4. По завершении удаляет песочницу. Каталог игры остаётся нетронутым.

---

## Устранение неполадок: частые ошибки, которые предотвращает Senpy

Senpy перехватывает ошибки времени выполнения (runtime crashes) еще до запуска игры. Вот список распространенных ошибок и правил Senpy, которые их предотвращают:

| Ошибка времени выполнения | Правило Senpy | Что именно ловит |
| :--- | :---: | :--- |
| `NameError: name 'x' is not defined` при загрузке | `RPY104` | `$ x = 1` внутри метки без глобального `default x = 0` — переменная не сохранится при загрузке сохранения |
| `NameError: name 'x' is not defined` в условии `if` | `RPY103` | `if x:`, где `x` никогда не объявлялась через `default` или `define` |
| `NameError: name 'x' is not defined` после `menu` | `RPY401` | Переменная задана только в одной ветке `menu:`, но отсутствует в другой — игра крашнется, если игрок выберет не тот путь |
| `NameError` при запуске игры (фаза `init`) | `RPY109` | Использование функции/класса в `init python:` до их объявления (нарушение алфавитного порядка загрузки файлов) |
| `KeyError: 'player_name'` в диалоге | `RPY101` | Опечатка в интерполяции `[player_name]` — такой переменной не существует |
| `KeyError` в строке перевода | `RPY601` | В переводе `new "..."` используются другие `[var]`, чем в оригинале `old "..."` |
| `TypeError: unsupported operand type(s) for +=` | `RPY108` | Конфликт типов (type taint, например, `str += int`) или невалидный метод (например, `list.append()` для `dict`) |
| `AttributeError: 'list' object has no attribute 'add'` | `RPY108` | Неверный метод для типа коллекции (например, `my_list.add()` вместо `.append()`) |
| `ScriptError: Label 'xxx' is not defined` | `RPY302` | `jump xxx` или `call xxx` на метку, которой не существует |
| `SyntaxError: tab/indent mismatch` | `RPY001` | Символы табуляции в отступах (Ren'Py требует 4 пробела) |
| Игра крашится после загрузки сохранения | `RPY104` / `RPY105` | Переменная создана через `$` вместо `default`, или константа `define` была изменена (мутировала) |
| Зависание интерфейса (Screen UI) / просадки FPS | `RPY201` / `RPY205` | Прямая мутация состояния внутри `screen` или тяжелые циклы `for`/`while` в языке экранов |

> **Совет:** Запустите `senpy path/to/game --fix` для автоматического исправления безопасных ошибок (`RPY001`, `RPY002`, `RPY301`), или используйте **QuickFix** (`Ctrl+.`) прямо в VS Code.

---

## Участие в разработке

Приветствуются вклад в проект, сообщения об ошибках и предложения новых правил.

1. Сделайте форк репозитория.
2. Создайте ветку: `git checkout -b feature/NewRule`.
3. Зафиксируйте изменения: `git commit -m 'feat: add RPY901 check'`.
4. Убедитесь, что все тесты проходят (`pytest`).
5. Откройте Pull Request.

Хотите написать плагин вместо контрибуции в ядро? См. **[Гайд по разработке плагинов](https://github.com/Xilleet/senpy/blob/main/examples/my_senpy_plugin/MY_SENPY_PLUGIN_README.md)**.

---

## О Senpy

Senpy — это passion-проект: мне понадобился семантический линтер для визуальной новеллы на Ren'Py, а ничего подобного не существовало.
Поэтому я его сделал.

**Как это делается:** Я читаю и ревьюю Python-код свободно, но не люблю
набирать boilerplate вручную. Поэтому я поручаю AI-инструментам набор кода,
а сам занимаюсь:

- Архитектурой (какие правила добавлять, как должен работать LSP-сервер)
- Ревью кода (каждая строка — я ловлю баги, которые AI пропускает)
- Тестированием на реальных проектах Ren'Py
- Триаджем баг-репортов и фиксами
- Релиз-менеджментом

AI не решает что делать, не пушит код, не выбирает фичи. Это делаю я.

Если вам интересен этот workflow — обсудим в
[Discussions](https://github.com/Xilleet/senpy/discussions). Если нашли
баг — [репортите](https://github.com/Xilleet/senpy/issues), я читаю каждый
issue и фиксю то, что важно пользователям.

Также загляните в [ScreenTale](https://github.com/Xilleet/ScreenTale) —
другой инструмент для Ren'Py от меня же.
(на данный момент он немного заброшен, но работает)

---

## Другие проекты с именем «senpy»

Имя `senpy` разделяется с несколькими неродственными проектами. Если вы попали сюда в поисках одного из них — вот список для различения:

| Проект | Что это | Ссылка |
|---|---|---|
| **Senpy (этот репо)** | Семантический линтер и статический анализатор для визуальных новелл на Ren'Py | https://github.com/Xilleet/senpy |
| `pypi.org/project/senpy` | Сервер для анализа тональности (словари Marl/Onyx/NIF) | https://pypi.org/project/senpy/ |
| `ACasey13/senpy` | Python-пакет для Neyer D-оптимального тестирования чувствительности | https://github.com/ACasey13/senpy |
| SCIA Engineer `senpy` | Python-фреймворк для генерации XML-данных SCIA Engineer | https://www.scia.net/en/support/addons/senpy-python-framework-generate-scia-engineer-data |
| *Senpy: A framework for semantic sentiment and emotion* | Научная статья, ScienceDirect | https://www.sciencedirect.com/science/article/abs/pii/S0950705119305313 |

Проект `Xilleet/senpy` — единственный, связанный с Ren'Py. Совпадение названий неудачное — если вы пришли сюда из поиска по анализу тональности или тестированию чувствительности, пожалуйста, перейдите по соответствующей ссылке выше.

---

## Лицензия

Проект распространяется по лицензии MIT. Его можно свободно использовать при разработке визуальных новелл как в коммерческих, так и в некоммерческих целях.
