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
  <a href="https://github.com/Xilleet/senpy/actions"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/Xilleet/senpy/main/.github/badges/tests.json" alt="Тесты (автообновление через CI)"></a>
  <a href="RULES.md"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/Xilleet/senpy/main/.github/badges/rules.json" alt="Правила (автообновление через CI)"></a>
  <a href="ARCHITECTURE.md"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/Xilleet/senpy/main/.github/badges/lsp.json" alt="LSP-обработчики (автообновление через CI)"></a>
  <a href="https://github.com/Xilleet/senpy/actions"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/Xilleet/senpy/main/.github/badges/coverage.json" alt="Покрытие кода (автообновление через CI)"></a>
  <a href="https://github.com/Xilleet/senpy/actions"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/Xilleet/senpy/main/.github/badges/speed.json" alt="Скорость (автообновление через CI)"></a>
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

## Что нового

### 0.7.6 — Новые правила (RPY704-707, RPY801-802), улучшения правил, mypy, 100% fixtures

| Функция | Описание |
|---|---|
| **6 новых правил** | RPY704 (unused `default` variable), RPY705 (unused screen parameter), RPY706 (unused transform parameter), RPY707 (unused audio channel registration), RPY801 (duplicate translation string), RPY802 (inconsistent translation across files). Всего: 49 → **51 правил**. |
| **Улучшения правил** | RPY108: ловит несовместимые BinOp в выражениях (`"text" + 5`). RPY401: concrete fix suggestion (`$ var = 0`). RPY403: tautology detection (`if x or not x:`). RPY502: case-insensitive matching (`show Sayori` → предлагает `sayori`). |
| **100% fixture-покрытие** | Все 51 правила теперь имеют bad+good `.rpy` fixtures с auto-verified JSON snapshots. Было 23/45 (51%). |
| **mypy 264 → 32** | Vendor исключён, DiagnosticSink → SenpyAnalyzer (TYPE_CHECKING), pygls overrides, None guards. −88% ошибок. |
| **CLI flag validation** | `--fix+--check`, `--fix+--diff`, `--check+--diff` теперь exit с кодом 2 и понятным сообщением (без traceback). Warnings для no-op комбинаций. |
| **CI badges всегда обновляются** | Бейджи теперь обновляются на каждый push в main, даже если matrix-тест упал (через `if: always()`). Больше никаких stale green бейджей. |
| **Dependabot** | Еженедельные обновления зависимостей для pip + GitHub Actions, сгруппированные в один PR. |
| **RPY902 example plugin** | `examples/todo_comment_plugin/` — детектит `# TODO:`, `# FIXME:`, `# XXX:`, `# HACK:` комментарии. Второй example plugin рядом с `my_senpy_plugin` (RPY901). |

### 0.7.5 — Plugin autoload, CI hardening, BLAKE2b hash

| Функция | Описание |
|---|---|
| **Plugin autoload** | Установленные и доверенные плагины теперь загружаются автоматически при запуске `senpy`, `senpy rule list/show` или `senpy inspect`. Раньше пайплайн загрузки существовал, но не вызывался из CLI entrypoints — правила плагинов были невидимы. Теперь `senpy rule list` после `pip install -e examples/my_senpy_plugin` показывает `RPY901`. |
| **Pre-commit hook** | `.pre-commit-hooks.yaml` лежит в корне репо. Добавьте Senpy в любой проект на [pre-commit](https://pre-commit.com) 4-строчным конфигом (см. [Pre-commit Integration](#pre-commit-integration) ниже). Экспонируется только `--check` (non-mutating) — `--fix` зацикливался бы на Windows CRLF. |
| **BLAKE2b cache hash** | Ключи кэша файлов теперь используют BLAKE2b вместо MD5. Быстрее, без security-baggage. Старый `.senpy_cache/cache.pkl` инвалидится тихо (hash mismatch → cache miss → recompute, без crash). |
| **`_RWLock` timeout** | Read/write lock в LSP-сервере получил `acquire_read(timeout=...)` / `acquire_write(timeout=...)` — зависший клиент больше не вешает LSP навсегда. Полный мигрейт на библиотеку `readerwriterlock` отложен на post-1.0 (зафиксированный tradeoff). |
| **macOS Python matrix** | CI теперь прогоняет Ubuntu × Windows × macOS на Python 3.11/3.12/3.13 (9 jobs) + Python 3.14 beta на Ubuntu и Windows (experimental, `continue-on-error`). |
| **`SYSTEM_LABELS` в inspect** | `senpy inspect` больше не считает `start`, `splash_window`, `after_load`, `main_menu` и др. «unreferenced» — это системные лейблы, которые Ren'Py вызывает сам. |
| **`NON_ASSET_EXTENSIONS`** | `.rpy`, `.rpym`, `.rpyc`, `.rpa` больше не считаются «unused assets» по RPY503 — это код, не медиа. |
| **English-only codebase** | Все комментарии и докстринги в `senpy/` теперь на английском (pass Russian→English завершён в 0.7.3; 0.7.5 расширяет guard на `scripts/`). Тест `test_no_russian_comments.py` теперь сканирует и `scripts/`. |

### 0.7.4 — Introspection, форматы вывода, метаданные правил, strict mode, formatter rule

| Функция | Описание |
|---|---|
| **`senpy inspect` subcommand** | Дампит все символы, которые Senpy видит в проекте, как JSON: labels, screens, variables, transforms, images, jump_sources (reverse index), used_assets, diagnostics, unresolved (broken jumps / missing screens / unreferenced labels / unused assets), per-section stats. Заточен под дебаг hover/asset resolution и авторинг плагинов. Сокращения: `--summary`, `--unresolved`, `--label X`, `--screen X`, `--transform X`. |
| **Форматы вывода: rdjson + gitlab** | `--output-format rdjson` (Reviewdog NDJSON — по JSON-объекту на строку, пайпится в `reviewdog -f=rdjson`) и `--output-format gitlab` (GitLab Code Quality JSON array — fingerprint-stable для аннотаций в MR). Всего форматов: 7 (`text`, `json`, `sarif`, `junit`, `github`, `rdjson`, `gitlab`). |
| **`senpy rule` subcommand** | Просмотр метаданных правил без запуска анализатора: `senpy rule list [--format json] [--tag T] [--severity S]`, `senpy rule show CODE`. Флаги `--rules` и `--rule CODE` в основном CLI работают как alias'ы. |
| **Теги у правил** | У каждого правила в `RULES_DATABASE` теперь поле `tags` (28 тегов на 51 правило: `formatting`, `variables`, `state`, `rollback`, `deprecated`, `screen`, `assets`, `audio`, `translations`, `dead-code`, и т.д.). `senpy rule list --tag rollback` фильтрует по тегу (union-семантика). |
| **`--tag` / `--ignore-tag` фильтры** | Lint-режим принимает `--tag rollback state` (только эти правила) и `--ignore-tag dead-code` (заглушить эти правила). Сопоставление тегов case-insensitive; правило проходит `--tag`, если ЛЮБОЙ из его тегов совпал. |
| **`strict = true` config** | Поле `strict` в `SenpyConfig` теперь соблюдается (было задокументировано с 0.6.0, но не использовалось). С `strict = true` каждый диагностик, чей код НЕявно не переопределён в `[tool.senpy.severity]`, повышается до `ERROR`. Явные severity-override'ы выигрывают над strict. |
| **FMT-STRING-CONSISTENCY** | 8-е правило форматтера (7-е в коде, 8-е по ID). Нормализует внешние кавычки однострочных строковых литералов в CODE-строках к единому стилю. По умолчанию: `'hi'` → `"hi"` (конвенция Ren'Py). Настраивается через `string_style = "double" | "single" | "preserve"`. Диалоги и triple-quoted строки намеренно не трогаются. |
| **Format Style Guide (stub)** | `docs/FORMAT_STYLE_GUIDE.md` описывает 6 оригинальных правил форматтера. Полная версия (8 правил) — в 0.7.6. |

### 0.7.3 — Plugin trust UX, English-only codebase, динамические бейджи

| Функция | Описание |
|---|---|
| **Non-interactive plugin trust** | `--trust-plugin NAME` / `--untrust-plugin NAME` CLI-флаги пишут в `~/.senpy/trusted_plugins.json` и `sys.exit(0)` без запуска анализатора. Управление доверием теперь полностью scriptable. Default trust callback определяет LSP-режим (`--lsp` в argv) и decline'ит недоверенные плагины без prompting (нет `input()` hang в LSP). |
| **English-only codebase (pass Russian→English)** | Все русские комментарии и докстринги в `senpy/` переведены на английский одним механическим проходом: 52 файла, ~1057 строк изменено (additions = removals, без logic changes). `senpy/domain/tsundere.py` (намеренный Russian easter-egg) и `senpy/vendor/` whitelisted'ны. `tests/test_no_russian_comments.py` гарантирует инвариант. |
| **Динамические бейджи** | Пять бейджей автообновляются CI на каждый push в `main`: tests, rules (45), LSP handlers, coverage, speed. `scripts/update_badges.py` читает метрики и пишет JSON-файлы; README-бейджи — shields.io `endpoint?url=...` на raw JSON из `main`. |
| **6 новых CLI-флагов** | `--statistics`, `--add-noqa`, `--respect-gitignore`, `--config FILE` (с env-переменной `SENPY_CONFIG`), `--show-settings`, `--cache-dir`. |

### 0.7.2 — God-function splitting, DRY cleanup

| Функция | Описание |
|---|---|
| **God-function refactoring** | 12 длинных функций разбиты на focused helpers (≤60 строк, ≤80 для dispatch tables). Заметные: `_check_show_scene` (188 → 30 строк), `_check_audio_statement` (174 → 21 строка), `MermaidBuilder.build` (132 → 18 строк), `process_quoted_strings` (187 → 58 строк). Все public API без изменений; characterization-тесты прошли. |
| **DRY helpers** | Новые `senpy/core/paths.py` (28 LOC) и `senpy/core/progress.py` (24 LOC) централизуют `normalize_path` и `progress_print` — раньше копипастились между модулями. |
| **Первый динамический бейдж** | Бейдж `tests` автообновляется на `main` через `scripts/update_badges.py`. Ещё 4 бейджа приходят в 0.7.3. |

### 0.7.1 — Stabilization, dynamic badges, CONTRIBUTING refresh

| Функция | Описание |
|---|---|
| **Stale API cleanup** | Все вызовы `LanguageServer.show_message_log` (pygls 2.x удалил этот API) заменены на `_logger.debug/warning`. Stale `build_exe.bat` и `build_vsix_dev.bat` удалены. |
| **Doc-sync** | README «What's New» обновлён с 0.6.0 до 0.7.0; plugin-пример в README синхронизирован с `examples/my_senpy_plugin/`; битые ссылки в SECURITY.md починены. |
| **Internal-ID scrub hook** | `scripts/clean_internal_ids.py` (pre-commit hook) вычищает любые утёкшие внутренние task ID из комментариев, CHANGELOG, commit messages, докстрингов. `tests/test_clean_internal_ids.py` фиксирует контракт. |
| **Удаление `warnings.filterwarnings`** | Module-level global filterwarnings удалён из `core/analyzer.py` и `lsp/server.py`. Тесты запускаются с `-W error::SyntaxWarning`, чтобы ловить silent regressions. |

### 0.7.0 — Image/Audio/Video hover + автосгенерированные API docs

| Функция | Описание |
|---|---|
| **Превью картинок в hover** | Наведите курсор на `show sayori happy` или `scene bg forest` — увидите inline-превью спрайта/CG с метаданными размера. Парсер заголовков PNG/JPEG/WEBP/GIF/BMP написан вручную — без зависимости от Pillow. |
| **Audio hover** | Наведите на `play music bgm_calm` / `queue sound click` / `define audio.X = "…"` — увидите ссылку Play, которая открывает встроенный медиа-viewer VS Code. Алиасы раскрываются при индексации, не на каждый hover. |
| **Video hover** | Если у изображения или auto-discovered файла видео-расширение (`.mp4`, `.webm`, `.ogv`, `.avi`, `.mkv`), hover показывает ссылку «Open in default app» через новую VS Code-команду `senpy.openExternal`. |
| **Автосгенерированные API docs Ren'Py** | 754 записи автоматически собраны из RST-источников Ren'Py 8.5.3. Вместе с 221 курируемыми записями `RENPY_API_DOCS_ALL` содержит **975 символов** — рост в 4,4×. |
| **TextMate-грамматика для `.rpy`/`.rpym`** | 270-строчная грамматика со scope `source.renpy`, скопированная дословно из [renpy-magic](https://github.com/adiffx/renpy-magic) (MIT). Покрывает комментарии, строки, Ren'Py text-tag `{…}` и interpolation `[…]`, `python`/`init python` блоки, `$`-prefixed python-строки, labels, screens, transforms, image definitions, say statements, numbers, operators. |
| **Детектор потерянных видео** | `MEDIA_EXTENSIONS` расширена `.mp4`/`.avi`/`.mkv` — RPY503 (проверка неиспользуемых ассетов) теперь также флагует потерянные видеофайлы. |

Полный changelog: [CHANGELOG.md](https://github.com/Xilleet/senpy/blob/main/CHANGELOG.md)

---

## Почему вам это нужно

`renpy lint` ловит синтаксические ошибки, но не ловит те баги, которые
действительно доходят до игроков. Ниже — реальные баги, которые Senpy поймал
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

1. Проходит мимо `renpy lint` (который проверяет только синтаксис и цели
   label'ов).
2. Выживает в дев-плейтестах (тестировщики всегда выбирают «интересную»
   ветку).
3. Всплывает только после релиза — через отзывы в Steam, скриншоты в
   Discord или баг-репорты на itch.io.
4. Стоит часов отладки в духе «у меня всё работает», потому что игрок не
   может воспроизвести это у тебя на глазах.

Senpy ловит их на этапе линтера — ещё до того, как они дойдут до игроков.
**Вот почему вам это нужно.**

Полный список из 51 правила с примерами — см.  **[RULES.md](https://github.com/Xilleet/senpy/blob/main/RULES.md)**.

---

## Зачем нужен Senpy?

Встроенная команда `renpy lint` проверяет только базовый синтаксис и сломанные метки. Она слепа к ошибкам выполнения Python, рассинхронизации отката (rollback) и повреждению файлов сохранений. В результате фатальные `NameError` и `KeyError` часто обнаруживаются игроками лишь спустя десятки часов ручного тестирования.

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
| **Форматирование** | `Shift+Alt+F` | Запуск форматтера Senpy (8 правил) |
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
запускает `senpy --check` на каждом коммите. Добавьте в ваш
`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/Xilleet/senpy
    rev: v0.7.7   # используйте последний тег
    hooks:
      - id: senpy
```

Хук **только проверяет, не исправляет** — это намеренно.
Автофиксящий хук в комбинации с git `autocrlf` на Windows создаёт
бесконечный цикл (форматтер нормализует переводы строк, git
конвертирует обратно, форматтер запускается снова). Запускайте
`senpy --fix` вручную, если нужны автоисправления.

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
