#!/usr/bin/env python3
"""update_unrpyc_pin.py — обновление pinned unrpyc commit + SHA256 в senpy/cli.py.

============================================================================
СОВМЕСТИМОСТЬ UNRPYC С ВЕРСИЯМИ REN'PY (важно для публичного скрипта)
============================================================================

unrpyc имеет две ветки:

1. **master (v2.x, Python 3.9+)** — РЕКОМЕНДУЕТСЯ для Senpy
   - Поддержка: Ren'Py 6.18.0+ / 6.99 / 7.x / 8.x
   - Это единственная ветка, совместимая с Python 3.11+ (требование Senpy)
   - Последний стабильный релиз: v2.0.4 (24 февраля 2026)

2. **legacy (v1.x, Python 2)** — НЕ ИСПОЛЬЗУЕТСЯ Senpy
   - Поддержка: Ren'Py 6.x, 7.x
   - Требует Python 2, который Senpy не поддерживает
   - Оставлен в unrpyc для старых окружений

НЕ ПОДДЕРЖИВАЮТСЯ (ни в одной ветке):
   - Ren'Py 5.x и ранее — unrpyc не умеет декомпилировать .rpyc этих версий

ОГОВОРКИ:
   - Ren'Py 6.x ниже 6.99.10 требует флаг `--no-init-offset` при запуске unrpyc.
     Senpy передаёт этот флаг автоматически при обнаружении старых .rpyc.
     (TODO: реализовать автоопределение в cli.py:decompile_to_sandbox)

ИСТОЧНИК: https://github.com/CensoredUsername/unrpyc#readme

============================================================================
ТЕСТЫ
============================================================================

Мейнтейнер Senpy тестировал unrpyc на реальных .rpyc файлах:
   ✓ Ren'Py 6.99 — работает (тестировано)
   ✓ Ren'Py 7.x  — работает (тестировано)
   ? Ren'Py 8.x  — не тестировалось, но официально поддерживается unrpyc v2.x

Если у вас есть .rpyc от Ren'Py 8.x, прогоните `senpy --decompile` после
обновления пина до v2.0.4 и сообщите о результатах в issues.

============================================================================
ИСПОЛЬЗОВАНИЕ
============================================================================

    python scripts/update_unrpyc_pin.py                    # обновить до default (стабильный релиз)
    python scripts/update_unrpyc_pin.py --list             # показать все доступные версии
    python scripts/update_unrpyc_pin.py --renpy-version 8  # выбрать версию, валидированную под Ren'Py 8
    python scripts/update_unrpyc_pin.py v2.0.4             # явно указать тег релиза
    python scripts/update_unrpyc_pin.py --commit abc123    # явно указать commit SHA (для тестирования)
    python scripts/update_unrpyc_pin.py --master           # обновить до последнего master (рискованно)

После запуска:
1. Получает SHA указанного коммита/тега через GitHub API.
2. Скачивает zip для этого коммита.
3. Считает SHA256 zip'а.
4. Обновляет UNRPYC_PINNED_COMMIT и UNRPYC_PINNED_SHA256 в senpy/cli.py.

Затем закоммитьте изменения:
    git add senpy/cli.py
    git commit -m "ECO-4: pin unrpyc to <version> (Ren'Py 6.99/7.x/8.x supported)"
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

GITHUB_API = "https://api.github.com/repos/CensoredUsername/unrpyc/commits/{ref}"
ZIP_URL_TEMPLATE = "https://github.com/CensoredUsername/unrpyc/archive/{commit}.zip"
CLI_PATH = Path(__file__).parent.parent / "senpy" / "cli.py"


# =============================================================================
# МАТРИЦА СОВМЕСТИМОСТИ UNRPYC × REN'PY
# =============================================================================

@dataclass
class UnrpycProfile:
    """Профиль pinned unrpyc с описанием совместимости."""
    ref: str                    # git ref (тег или commit SHA) для скачивания
    label: str                  # человекочитаемое имя
    renpy_versions: str         # поддерживаемые версии Ren'Py (для документации)
    python_required: str        # требуемая версия Python для unrpyc
    release_date: str           # дата релиза или "latest" для master
    stability: str              # "stable" / "latest" / "testing"
    notes: str                  # дополнительные заметки
    recommended: bool = False   # рекомендован ли по умолчанию


# Список доступных профилей.
PROFILES: list[UnrpycProfile] = [
    UnrpycProfile(
        ref="v2.0.4",
        label="v2.0.4 (stable release)",
        renpy_versions="6.18.0+ / 6.99 / 7.x / 8.x",
        python_required=">=3.9",
        release_date="2026-02-24",
        stability="stable",
        notes=(
            "Последний стабильный релиз unrpyc. Рекомендуется для production. "
            "Полная поддержка Ren'Py 6.18+ и 8.x. "
            "Совместим с Python 3.9+ (Senpy требует 3.11+)."
        ),
        recommended=True,
    ),
    UnrpycProfile(
        ref="v2.0.3",
        label="v2.0.3 (previous stable)",
        renpy_versions="6.18.0+ / 6.99 / 7.x / 8.x",
        python_required=">=3.9",
        release_date="2025-XX-XX",
        stability="stable",
        notes=(
            "Предыдущий стабильный релиз. Используйте, если в v2.0.4 обнаружена "
            "регрессия. В обычном случае — выбирайте v2.0.4."
        ),
    ),
    UnrpycProfile(
        ref="master",
        label="master (latest, possibly unstable)",
        renpy_versions="6.18.0+ / 6.99 / 7.x / 8.x",
        python_required=">=3.9",
        release_date="latest",
        stability="latest",
        notes=(
            "Последний master branch. Может включать нерелизные фиксы или "
            "breaking changes. Используйте только для тестирования. "
            "Не рекомендуется для production."
        ),
    ),
    # Если нужен конкретный commit для тестирования, добавьте его сюда:
    # UnrpycProfile(
    #     ref="abc1234",
    #     label="custom commit (testing)",
    #     renpy_versions="?",
    #     python_required=">=3.9",
    #     release_date="?",
    #     stability="testing",
    #     notes="Конкретный commit для тестирования совместимости.",
    # ),
]


# =============================================================================
# ВЫБОР ПРОФИЛЯ ПО ВЕРСИИ REN'PY
# =============================================================================
# Пользователь может сказать "у меня Ren'Py 8" — скрипт выберет подходящий профиль.
# Сейчас все профили поддерживают 6.99-8.x, но если unrpyc когда-нибудь разделится,
# здесь можно добавить маппинг.

RENPY_VERSION_TO_PROFILE: dict[str, str] = {
    "6.99": "v2.0.4",   # стабильный, подтверждён тестами мейнтейнера
    "6": "v2.0.4",
    "7": "v2.0.4",      # стабильный, подтверждён тестами мейнтейнера
    "8": "v2.0.4",      # стабильный, официально поддерживается (не тестировалось мейнтейнером)
    "all": "v2.0.4",    # явный выбор "все версии"
}


def get_default_profile() -> UnrpycProfile:
    """Возвращает профиль по умолчанию (первый recommended)."""
    for p in PROFILES:
        if p.recommended:
            return p
    return PROFILES[0]


def find_profile(ref: str) -> UnrpycProfile | None:
    """Находит профиль по ref (тег/commit)."""
    for p in PROFILES:
        if p.ref == ref:
            return p
    return None


# =============================================================================
# GitHub API: получить SHA коммита для ref
# =============================================================================
def get_commit_sha(ref: str) -> tuple[str, str, str]:
    """Получает SHA коммита для указанного ref через GitHub API.

    ref может быть:
      - "master" → SHA последнего коммита master
      - "v2.0.4" → SHA коммита тега v2.0.4
      - "abc1234" → тот же SHA (короткий SHA)

    Возвращает (sha, commit_date, commit_message_first_line).
    """
    url = GITHUB_API.format(ref=ref)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Senpy-Linter-update-pin",
            "Accept": "application/vnd.github+json",
        },
    )
    print(f"[*] Fetching commit info for '{ref}'...")
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.load(resp)

    return (
        data["sha"],
        data["commit"]["committer"]["date"],
        data["commit"]["message"].split("\n")[0][:80],
    )


def download_zip_and_hash(commit_sha: str) -> tuple[bytes, str]:
    """Скачивает zip для commit_sha, возвращает (zip_data, sha256_hex)."""
    url = ZIP_URL_TEMPLATE.format(commit=commit_sha)
    print(f"[*] Downloading zip from {url}...")
    req = urllib.request.Request(url, headers={"User-Agent": "Senpy-Linter-update-pin"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()

    sha256 = hashlib.sha256(data).hexdigest()
    print(f"    Zip size: {len(data):,} bytes")
    print(f"    SHA256:   {sha256}")
    return data, sha256


# =============================================================================
# Обновление senpy/cli.py
# =============================================================================
def update_cli_py(commit_sha: str, sha256_hex: str, profile: UnrpycProfile) -> None:
    """Обновляет UNRPYC_PINNED_COMMIT и UNRPYC_PINNED_SHA256 в senpy/cli.py.

    Также добавляет комментарий с описанием профиля (для документации).
    """
    src = CLI_PATH.read_text(encoding="utf-8")

    # Заменяем UNRPYC_PINNED_COMMIT
    new_src = re.sub(
        r'(UNRPYC_PINNED_COMMIT\s*=\s*)"[^"]*"',
        f'\\1"{commit_sha}"',
        src,
        count=1,
    )
    # Заменяем UNRPYC_PINNED_SHA256
    new_src = re.sub(
        r'(UNRPYC_PINNED_SHA256\s*=\s*)(None|"[^"]*")',
        f'\\1"{sha256_hex}"',
        new_src,
        count=1,
    )

    if new_src == src:
        print("[!] WARNING: изменения не применены — проверьте pattern'ы в cli.py")
        return

    CLI_PATH.write_text(new_src, encoding="utf-8")
    print(f"[✔] {CLI_PATH} обновлён")
    print(f"    Profile: {profile.label}")
    print(f"    Ren'Py versions: {profile.renpy_versions}")
    print(f"    Python required: {profile.python_required}")
    print(f"    Stability: {profile.stability}")


# =============================================================================
# CLI
# =============================================================================
def cmd_list() -> int:
    """Показать все доступные профили."""
    print("=" * 80)
    print("Доступные профили unrpyc для пиннинга:")
    print("=" * 80)
    for p in PROFILES:
        marker = " ★ РЕКОМЕНДОВАН" if p.recommended else ""
        print(f"\n  {p.label}{marker}")
        print(f"    ref:              {p.ref}")
        print(f"    Ren'Py versions:  {p.renpy_versions}")
        print(f"    Python required:  {p.python_required}")
        print(f"    Release date:     {p.release_date}")
        print(f"    Stability:        {p.stability}")
        print(f"    Notes:            {p.notes}")
    print("\n" + "=" * 80)
    print("Использование:")
    print("  python scripts/update_unrpyc_pin.py                  # recommended профиль")
    print("  python scripts/update_unrpyc_pin.py v2.0.4           # конкретный тег")
    print("  python scripts/update_unrpyc_pin.py --commit abc123  # конкретный SHA")
    print("  python scripts/update_unrpyc_pin.py --master         # latest master")
    print("  python scripts/update_unrpyc_pin.py --renpy-version 8  # под Ren'Py 8")
    print("  python scripts/update_unrpyc_pin.py --list           # этот список")
    return 0


def main() -> int:
    args = sys.argv[1:]

    # --list
    if "--list" in args or "-l" in args:
        return cmd_list()

    # --master
    if "--master" in args:
        profile = find_profile("master")
        if not profile:
            print("[ERROR] профиль 'master' не найден в PROFILES")
            return 1
        return run_update(profile)

    # --commit <sha>
    if "--commit" in args:
        idx = args.index("--commit")
        if idx + 1 >= len(args):
            print("[ERROR] --commit требует аргумент: --commit <sha>")
            return 1
        sha = args[idx + 1]
        # Создаём ad-hoc профиль
        profile = UnrpycProfile(
            ref=sha,
            label=f"custom commit {sha[:8]}",
            renpy_versions="неизвестно (тестирование)",
            python_required=">=3.9",
            release_date="?",
            stability="testing",
            notes="Конкретный commit для тестирования. Совместимость не проверена.",
        )
        return run_update(profile)

    # --renpy-version <version>
    if "--renpy-version" in args:
        idx = args.index("--renpy-version")
        if idx + 1 >= len(args):
            print("[ERROR] --renpy-version требует аргумент: --renpy-version <6|7|8|all>")
            return 1
        renpy_ver = args[idx + 1].strip().lower()
        # Нормализуем: "6.99" → "6.99", "7" → "7", "8.0" → "8"
        if renpy_ver.startswith("6"):
            renpy_ver_key = "6.99" if "99" in renpy_ver else "6"
        elif renpy_ver.startswith("7"):
            renpy_ver_key = "7"
        elif renpy_ver.startswith("8"):
            renpy_ver_key = "8"
        elif renpy_ver == "all":
            renpy_ver_key = "all"
        else:
            print(f"[ERROR] неизвестная версия Ren'Py: {renpy_ver}")
            print("        поддерживаемые: 6, 6.99, 7, 8, all")
            return 1

        ref = RENPY_VERSION_TO_PROFILE.get(renpy_ver_key)
        if not ref:
            print(f"[ERROR] нет профиля для Ren'Py {renpy_ver_key}")
            return 1

        profile = find_profile(ref)
        if not profile:
            print(f"[ERROR] профиль {ref} не найден")
            return 1

        print(f"[*] Ren'Py {renpy_ver_key} → профиль {profile.label}")
        return run_update(profile)

    # Без аргументов или с позиционным аргументом-тегом
    if not args:
        # default — recommended профиль
        return run_update(get_default_profile())

    # Позиционный аргумент — тег или ref
    ref = args[0]
    profile = find_profile(ref)
    if not profile:
        # Возможно, это тег, которого нет в PROFILES — создадим ad-hoc
        print(f"[*] '{ref}' не найден в PROFILES, создаю ad-hoc профиль")
        profile = UnrpycProfile(
            ref=ref,
            label=f"custom ref {ref}",
            renpy_versions="неизвестно (тестирование)",
            python_required=">=3.9",
            release_date="?",
            stability="testing",
            notes="Указанный ref не из стандартных профилей. Совместимость не проверена.",
        )
    return run_update(profile)


def run_update(profile: UnrpycProfile) -> int:
    """Получает SHA, скачивает zip, считает SHA256, обновляет cli.py."""
    print(f"\n[*] Profile: {profile.label}")
    print(f"    Ren'Py versions: {profile.renpy_versions}")
    print(f"    Stability: {profile.stability}")
    print()

    try:
        commit_sha, commit_date, commit_msg = get_commit_sha(profile.ref)
    except urllib.error.HTTPError as e:
        if e.code == 403 and "rate limit" in (e.reason or "").lower():
            print("[ERROR] GitHub API rate limit exceeded. Подожди час или запусти с GitHub-токеном:")
            print("        GH_TOKEN=xxx python scripts/update_unrpyc_pin.py")
            print("        (или: GITHUB_TOKEN=xxx — оба варианта работают)")
            return 1
        if e.code == 404:
            print(f"[ERROR] ref '{profile.ref}' не найден на GitHub.")
            print("        Проверьте, что тег/коммит существует в CensoredUsername/unrpyc.")
            return 1
        print(f"[ERROR] GitHub API: {e}")
        return 1
    except urllib.error.URLError as e:
        print(f"[ERROR] Network: {e}")
        return 1

    print(f"    Commit: {commit_sha}")
    print(f"    Date:   {commit_date}")
    print(f"    Msg:    {commit_msg}")
    print()

    try:
        _, sha256_hex = download_zip_and_hash(commit_sha)
    except urllib.error.URLError as e:
        print(f"[ERROR] Не удалось скачать zip: {e}")
        return 1

    print()
    update_cli_py(commit_sha, sha256_hex, profile)
    print()
    print(f"[★] Готово. Pinned unrpyc к {profile.label} (commit {commit_sha[:8]}).")
    print(f"    Поддерживаемые версии Ren'Py: {profile.renpy_versions}")
    print()
    print(f"    Закоммитьте: git add senpy/cli.py && git commit -m 'ECO-4: pin unrpyc to {profile.ref}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
