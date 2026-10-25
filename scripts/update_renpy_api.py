"""
Служебный скрипт автоматической синхронизации и обновления базы Ren'Py API.
Запуск: python scripts/update_renpy_api.py
Поддерживает многопоточную быструю загрузку с живым прогресс-баром.
"""
from __future__ import annotations

import ast
import faulthandler
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

faulthandler.enable()

API_FILE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "senpy", "renpy_api.py")
)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from senpy.renpy_api import RENPY_API_DOCS, RENPY_DOC_VERSION

RELEASES_URL = "https://api.github.com/repos/renpy/renpy/releases/latest"
CONTENTS_API_URL = "https://api.github.com/repos/renpy/renpy/contents/renpy/exports?ref={ref}"
RAW_BASE_URL = "https://raw.githubusercontent.com/renpy/renpy/{ref}/renpy/exports/{filename}"
RAW_LEGACY_URL = "https://raw.githubusercontent.com/renpy/renpy/{ref}/renpy/exports.py"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Senpy-Updater"}

KNOWN_EXPORT_FILES = [
    "statementexports.py",
    "displayexports.py",
    "sayexports.py",
    "scriptexports.py",
    "fetchexports.py",
    "commonexports.py",
]


def fetch_text(url: str) -> str | None:
    """Загружает текстовый файл по URL (urllib + curl fallback)."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        try:
            res = subprocess.run(["curl", "-sSL", url], capture_output=True, text=True, check=False)
            if res.returncode == 0 and res.stdout:
                return res.stdout
        except (subprocess.SubprocessError, OSError):
            return None
    return None


def get_latest_version() -> str | None:
    """Определяет последний релизный тег Ren'Py."""
    data_str = fetch_text(RELEASES_URL)
    if data_str:
        try:
            data = json.loads(data_str)
            tag = data.get("tag_name", "").lstrip("v").strip()
            if tag:
                return tag
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass

    try:
        req = urllib.request.Request("https://github.com/renpy/renpy/releases/latest", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            tag = resp.geturl().rstrip("/").split("/")[-1].lstrip("v").strip()
            if tag and tag[0].isdigit():
                return tag
    except (urllib.error.URLError, TimeoutError, OSError):
        pass
    return None


def clean_sphinx_doc(doc: str) -> tuple[str, str]:
    """Вычищает служебные директивы Sphinx (:doc:, :ref:, :func:) из docstring."""
    cleaned = re.sub(r':(?:doc|name|args):[^\n]*\n', '', doc)
    cleaned = re.sub(r':(?:doc|ref|func|class|meth):`([^`<]+)(?:<[^>]+>)?`', r'`\1`', cleaned)
    cleaned = re.sub(r'\.\.\s+(?:raw|versionadded|versionchanged)::.*', '', cleaned)

    paragraphs = [p.strip() for p in cleaned.strip().split("\n\n") if p.strip()]
    if not paragraphs:
        return "", ""

    short_doc = paragraphs[0].replace("\n", " ").strip()
    details = "\n\n".join(paragraphs[1:]).strip() if len(paragraphs) > 1 else ""
    return short_doc, details


def parse_python_exports(source_code: str) -> dict[str, dict[str, str]]:
    """Парсит Python-файл через AST и извлекает функции renpy.* с сигнатурами."""
    extracted = {}
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return extracted

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            func_key = f"renpy.{node.name}"
            try:
                args_str = ast.unparse(node.args)
            except AttributeError:
                args_str = "..."

            sig = f"renpy.{node.name}({args_str})"
            docstring = ast.get_docstring(node)
            if not docstring:
                continue

            short_doc, details = clean_sphinx_doc(docstring)
            if not short_doc:
                continue

            entry = {
                "signature": sig,
                "doc": short_doc,
                "url": f"https://www.renpy.org/doc/html/other.html#{func_key}",
            }
            if details:
                entry["details"] = details

            extracted[func_key] = entry

    return extracted


def fetch_all_export_sources(ref: str) -> list[str]:
    """Скачивает исходники экспорта параллельно с живой индикацией прогресса."""
    sources: list[str] = []

    api_url = CONTENTS_API_URL.format(ref=ref)
    api_data_str = fetch_text(api_url)

    file_targets: list[tuple[str, str]] = []  # (filename, url)
    if api_data_str:
        try:
            items = json.loads(api_data_str)
            if isinstance(items, list):
                for item in items:
                    name = item.get("name", "")
                    if name.endswith(".py") and not name.startswith("__"):
                        dl_url = item.get("download_url") or RAW_BASE_URL.format(ref=ref, filename=name)
                        file_targets.append((name, dl_url))
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

    if not file_targets:
        for fname in KNOWN_EXPORT_FILES:
            file_targets.append((fname, RAW_BASE_URL.format(ref=ref, filename=fname)))

    total = len(file_targets)
    print(f"[*] Скачивание {total} модулей exports (параллельно в 6 потоков):")

    def download_worker(target: tuple[str, str]) -> tuple[str, str | None]:
        fname, u = target
        return fname, fetch_text(u)

    completed = 0
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(download_worker, target) for target in file_targets]
        for future in as_completed(futures):
            completed += 1
            fname, content = future.result()
            if content and len(content) > 100:
                sources.append(content)
                status = "OK"
            else:
                status = "Пропущен/Пуст"
            print(f"    [{completed:>2}/{total}] {fname:<25} ... {status}")

    if not sources:
        print("[*] Попытка загрузки устаревшего exports.py...")
        legacy_url = RAW_LEGACY_URL.format(ref=ref)
        content = fetch_text(legacy_url)
        if content:
            sources.append(content)

    return sources


def serialize_api_module(version: str, docs: dict[str, dict[str, str]]) -> str:
    """Генерирует форматированный код для senpy/renpy_api.py."""
    lines = [
        'from __future__ import annotations',
        '',
        '# Версия документации Ren\'Py, зафиксированная в этой базе',
        f'RENPY_DOC_VERSION = "{version}"',
        '',
        'RENPY_API_DOCS: dict[str, dict[str, str]] = {',
    ]

    for key in sorted(docs.keys()):
        item = docs[key]
        lines.append(f'    "{key}": {{')
        for field in ("signature", "doc", "details", "example", "url"):
            if item.get(field):
                val = repr(item[field])
                lines.append(f'        "{field}": {val},')
        lines.append('    },')

    lines.append('}\n')

    helper_code = '''def get_renpy_api_hover(symbol: str) -> str | None:
    """Возвращает форматированный Markdown для подсказки Hover по символу Ren'Py API."""
    entry = RENPY_API_DOCS.get(symbol)
    if not entry:
        return None

    md = [
        f"**Ren'Py Engine API** — `{symbol}`\\n",
        f"```renpy\\n{entry['signature']}\\n```\\n",
        entry["doc"],
    ]
    if entry.get("details"):
        md.append(f"\\n{entry['details']}")
    if entry.get("example"):
        md.append(f"\\n**Example:**\\n```renpy\\n{entry['example']}\\n```")
    if entry.get("url"):
        md.append(f"\\n[Open Ren'Py Documentation ↗]({entry['url']})")

    return "\\n".join(md)
'''
    lines.append(helper_code)
    return "\n".join(lines)


def run_updater():
    print("=" * 65)
    print("  SENPY — Синхронизация базы документации Ren'Py API")
    print("=" * 65)
    print(f"[*] Локальная база: v{RENPY_DOC_VERSION} ({len(RENPY_API_DOCS)} символов)")
    print("[*] Проверка релизов на GitHub...")

    latest_tag = get_latest_version() or "master"
    print(f"[✔] Актуальная версия Ren'Py на GitHub: v{latest_tag}")

    is_newer = (latest_tag != RENPY_DOC_VERSION)
    prompt = (
        f"[?] Доступна новая версия v{latest_tag}! Синхронизировать API? [Y/n]: "
        if is_newer else
        f"[?] Версия v{latest_tag} уже совпадает. Принудительно обновить функции? [y/N]: "
    )

    ans = input(prompt).strip().lower()
    if is_newer and ans not in ("", "y", "yes", "да", "д"):
        print("[*] Отменено.\n")
        return
    elif not is_newer and ans not in ("y", "yes", "да", "д"):
        print("[*] Всё актуально, изменений нет.\n")
        return

    sources = fetch_all_export_sources(latest_tag)
    if not sources:
        print("[*] Тег релиза не найден в raw, переключение на ветку master...")
        sources = fetch_all_export_sources("master")

    if not sources:
        print("[!] Не удалось загрузить файлы экспорта с GitHub.\n")
        return

    print(f"\n[✔] Загружено модулей: {len(sources)}")
    print("[*] Парсинг AST и извлечение функций...")

    parsed_funcs: dict[str, dict[str, str]] = {}
    for src in sources:
        parsed_funcs.update(parse_python_exports(src))

    print(f"[✔] Извлечено {len(parsed_funcs)} функций renpy.*")

    updated_db = dict(RENPY_API_DOCS)
    added_count = 0
    updated_count = 0

    for key, new_item in parsed_funcs.items():
        if key in updated_db:
            updated_db[key]["signature"] = new_item["signature"]
            if "details" in new_item and "details" not in updated_db[key]:
                updated_db[key]["details"] = new_item["details"]
            updated_count += 1
        else:
            updated_db[key] = new_item
            added_count += 1

    print(f"[*] Результат: +{added_count} новых функций, {updated_count} обновлено.")

    new_file_content = serialize_api_module(latest_tag, updated_db)
    with open(API_FILE_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_file_content)

    print(f"\n[✔] Успех! Файл '{API_FILE_PATH}' обновлён.")
    print(f"    Итого символов в базе: {len(updated_db)} (версия v{latest_tag})\n")


if __name__ == "__main__":
    try:
        run_updater()
    except KeyboardInterrupt:
        print("\n[*] Обновление прервано пользователем.")
    except (urllib.error.URLError, OSError, json.JSONDecodeError, RuntimeError) as e:
        print(f"\n[!] Ошибка: {e}")
    input("Нажмите Enter, чтобы закрыть...")