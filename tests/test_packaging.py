"""Регрессионные тесты упаковки/дистрибуции Senpy (P0'-баги из аудита 0.5.1).

Эти тесты защищают от regressions, обнаруженных в аудите v0.5.1:

    P0'-1: LICENSE файл должен существовать и совпадать с pyproject.toml:14
    P0'-2: .gitignore должен существовать и НЕ игнорировать исходники
    P0'-3: CHANGELOG.md должен содержать секцию для текущей версии
    P0'-4: senpy-vscode/language-configuration.json должен существовать и быть валидным
    P0'-5: UNRPYC_PINNED_SHA256 должен быть не None (verification не no-op)
    P0'-6: Rule count должен быть консистентен между источниками

Все тесты — declarative checks файлов на диске. Не требуют pytest fixtures
или setup — только Path.exists() и чтение.

Запуск:
    pytest tests/test_packaging.py -v
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

# Пути относительно корня проекта (где pyproject.toml)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _PROJECT_ROOT / "pyproject.toml"
_LICENSE = _PROJECT_ROOT / "LICENSE"
_LICENSE_MD = _PROJECT_ROOT / "LICENSE.md"
_GITIGNORE = _PROJECT_ROOT / ".gitignore"
_CHANGELOG = _PROJECT_ROOT / "CHANGELOG.md"
_VERSION_PY = _PROJECT_ROOT / "senpy" / "__version__.py"
_LANG_CONFIG = _PROJECT_ROOT / "senpy-vscode" / "language-configuration.json"
_UNRPYC_BOOTSTRAP = _PROJECT_ROOT / "senpy" / "cli" / "unrpyc.py"
_MODELS_PY = _PROJECT_ROOT / "senpy" / "core" / "models.py"
_RULES_INFO_PY = _PROJECT_ROOT / "senpy" / "rules" / "rules_info.py"


# =============================================================================
# P0'-1: LICENSE file
# =============================================================================

class TestLicenseFile:
    """P0'-1: LICENSE файл должен существовать и совпадать с pyproject.toml:14."""

    def test_pyproject_references_license_file(self):
        """pyproject.toml должен содержать license = { file = "..." }."""
        with _PYPROJECT.open("rb") as f:
            config = tomllib.load(f)
        assert "license" in config["project"], (
            "pyproject.toml [project] должен содержать 'license' field"
        )
        assert "file" in config["project"]["license"], (
            "pyproject.toml [project.license] должен содержать 'file' field"
        )

    def test_license_file_exists_and_matches_pyproject(self):
        """LICENSE файл на диске должен совпадать с тем, что в pyproject.toml.

        Это фиксит P0'-1: ранее LICENSE.md существовал, но pyproject.toml:14
        ссылался на 'LICENSE' (без .md) — pip wheel падал с FileNotFoundError.
        """
        with _PYPROJECT.open("rb") as f:
            config = tomllib.load(f)
        license_path_str = config["project"]["license"]["file"]
        license_path = _PROJECT_ROOT / license_path_str
        assert license_path.exists(), (
            f"pyproject.toml ссылается на '{license_path_str}', но файл не найден. "
            f"Варианты фикса:\n"
            f"  1. Переименовать LICENSE.md → LICENSE\n"
            f"  2. Обновить pyproject.toml: license = {{ file = 'LICENSE.md' }}"
        )

    def test_license_contains_mit_text(self):
        """LICENSE должен содержать MIT License текст (если файл существует)."""
        with _PYPROJECT.open("rb") as f:
            config = tomllib.load(f)
        license_path = _PROJECT_ROOT / config["project"]["license"]["file"]
        if not license_path.exists():
            pytest.skip("LICENSE файл отсутствует — test_license_file_exists_and_matches_pyproject должен был упасть")
        content = license_path.read_text(encoding="utf-8")
        assert "MIT License" in content, "LICENSE должен содержать 'MIT License'"
        assert "Permission is hereby granted" in content, "LICENSE должен содержать стандартный MIT-текст"


# =============================================================================
# P0'-2: .gitignore
# =============================================================================

class TestGitignore:
    """P0'-2: .gitignore должен существовать и НЕ игнорировать исходники."""

    def test_gitignore_exists(self):
        """.gitignore файл должен существовать в корне проекта."""
        assert _GITIGNORE.exists(), (
            ".gitignore отсутствует. Артефакты (senpy.sarif, test_report.*, "
            "__pycache__/, .pytest_cache/) будут коммититься в репо."
        )

    @pytest.mark.parametrize("dangerous_pattern", [
        "senpy/analyzer.py",
        "senpy/cli.py",
        "senpy/server.py",
        "senpy/checkers.py",
        "senpy/python_ast.py",
        "senpy/flow.py",
        "senpy/analyzer.py",
        "senpy-vscode/src/extension.ts",
        "senpy-vscode/src/test/extension.test.ts",
        "bump_version.py",
        "publish_pypi.bat",
        "check.bat",
        "install_dev.bat",
        "run_check.bat",
        "reinstall.bat",
        "senpy.spec",
        "test_formatter_demo.py",
        "pyproject.toml",
        "README.md",
        "CHANGELOG.md",
        "RULES.md",
    ])
    def test_gitignore_does_not_ignore_source_files(self, dangerous_pattern: str):
        """.gitignore НЕ должен игнорировать реальные исходники проекта.

        Это критичная защита: ранее в .gitignore была строка 'senpy/analyzer.py',
        которая молча исключала из git главный модуль анализатора (1 719 строк).
        Аналогично — bump_version.py, senpy.spec, test_formatter_demo.py, и т.д.
        """
        if not _GITIGNORE.exists():
            pytest.skip(".gitignore отсутствует — test_gitignore_exists должен был упасть")
        content = _GITIGNORE.read_text(encoding="utf-8")
        for line_num, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            # Пропускаем комментарии и пустые строки
            if not stripped or stripped.startswith("#"):
                continue
            # Точное совпадение (не prefix-match)
            if stripped == dangerous_pattern:
                pytest.fail(
                    f".gitignore line {line_num}: '{dangerous_pattern}' "
                    f"игнорирует исходник проекта. Это сломает сборку/CI. "
                    f"Удалите эту строку из .gitignore."
                )

    @pytest.mark.parametrize("personal_pattern", [
        "Новая папка",
        "порядок.txt",
        "пост для реддита.txt",
        "аудит 0.4.5.md",
        "Семантический_линтер_Senpy_для_RenPy",
        "roadmap.txt",
        "rub_check.bat",
    ])
    def test_gitignore_does_not_contain_personal_files(self, personal_pattern: str):
        """.gitignore НЕ должен содержать личные файлы мейнтейнера.

        Личные файлы (Новая папка/, пост для реддита.txt, и т.д.) не должны
        быть в project gitignore. Используйте ~/.gitignore_global или
        .git/info/exclude для локальных исключений.
        """
        if not _GITIGNORE.exists():
            pytest.skip(".gitignore отсутствует")
        content = _GITIGNORE.read_text(encoding="utf-8")
        for line_num, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if personal_pattern in stripped:
                pytest.fail(
                    f".gitignore line {line_num}: '{stripped}' содержит личный "
                    f"файл '{personal_pattern}'. Перенесите в ~/.gitignore_global "
                    f"или .git/info/exclude."
                )

    def test_gitignore_excludes_artifacts(self):
        """.gitignore должен исключать известные артефакты."""
        if not _GITIGNORE.exists():
            pytest.skip(".gitignore отсутствует")
        content = _GITIGNORE.read_text(encoding="utf-8")
        required_patterns = [
            "__pycache__/",
            "*.py[cod]",
            ".pytest_cache/",
            "senpy.sarif",
            "test_report.json",
            "test_report.txt",
            ".ruff_cache/",
            "dist/",
            "build/",
            "*.egg-info/",
        ]
        missing = []
        for pattern in required_patterns:
            # Проверяем что pattern есть как non-comment line
            found = False
            for line in content.splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and stripped == pattern:
                    found = True
                    break
            if not found:
                missing.append(pattern)
        assert not missing, (
            f".gitignore не содержит обязательные паттерны: {missing}. "
            f"Эти артефакты будут коммититься в репо."
        )


# =============================================================================
# P0'-3: CHANGELOG.md
# =============================================================================

class TestChangelog:
    """P0'-3: CHANGELOG.md должен содержать секцию для текущей версии."""

    def _get_current_version(self) -> str:
        """Читает текущую версию из senpy/__version__.py."""
        content = _VERSION_PY.read_text(encoding="utf-8")
        match = re.search(r'__version__\s*=\s*["\'](\d+\.\d+\.\d+)["\']', content)
        assert match, f"Не удалось распарсить __version__ из {_VERSION_PY}"
        return match.group(1)

    def test_changelog_exists(self):
        """CHANGELOG.md файл должен существовать."""
        assert _CHANGELOG.exists(), "CHANGELOG.md отсутствует в корне проекта"

    def test_changelog_contains_current_version_section(self):
        """CHANGELOG.md должен содержать секцию для текущей версии."""
        if not _CHANGELOG.exists():
            pytest.skip("CHANGELOG.md отсутствует")
        current_version = self._get_current_version()
        content = _CHANGELOG.read_text(encoding="utf-8")
        # Ищем ## [X.Y.Z] или ## [X.Y.Z — date]
        pattern = rf"##\s*\[{re.escape(current_version)}\]"
        assert re.search(pattern, content), (
            f"CHANGELOG.md не содержит секцию для текущей версии "
            f"'{current_version}'. Найдено в senpy/__version__.py. "
            f"Добавьте '## [{current_version}] — <date>' в начало CHANGELOG.md."
        )

    def test_changelog_has_keepachangelog_format(self):
        """CHANGELOG.md должен следовать формату Keep a Changelog."""
        if not _CHANGELOG.exists():
            pytest.skip("CHANGELOG.md отсутствует")
        content = _CHANGELOG.read_text(encoding="utf-8")
        assert "Keep a Changelog" in content, (
            "CHANGELOG.md должен ссылаться на https://keepachangelog.com "
            "(это стандартный формат)."
        )
        assert "Semantic Versioning" in content, (
            "CHANGELOG.md должен ссылаться на https://semver.org "
            "(это стандарт versioning)."
        )


# =============================================================================
# P0'-4: senpy-vscode/language-configuration.json
# =============================================================================

class TestLanguageConfiguration:
    """P0'-4: language-configuration.json для VS Code .rpy support."""

    def test_file_exists(self):
        """Файл language-configuration.json должен существовать."""
        assert _LANG_CONFIG.exists(), (
            f"Ожидается {_LANG_CONFIG}. Без него VS Code не знает, что '#' — "
            f"комментарий, авто-отступы и bracket auto-close отключены для .rpy."
        )

    def test_file_is_valid_json(self):
        """Файл должен быть валидным JSON."""
        if not _LANG_CONFIG.exists():
            pytest.skip("language-configuration.json отсутствует")
        try:
            data = json.loads(_LANG_CONFIG.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            pytest.fail(f"language-configuration.json не валидный JSON: {e}")
        assert isinstance(data, dict), "JSON должен быть объектом (dict)"

    @pytest.mark.parametrize("required_key", [
        "comments",
        "brackets",
        "autoClosingPairs",
        "surroundingPairs",
    ])
    def test_required_keys_present(self, required_key: str):
        """Файл должен содержать все обязательные VS Code language keys."""
        if not _LANG_CONFIG.exists():
            pytest.skip("language-configuration.json отсутствует")
        data = json.loads(_LANG_CONFIG.read_text(encoding="utf-8"))
        assert required_key in data, (
            f"language-configuration.json должен содержать '{required_key}' key. "
            f"См. https://code.visualstudio.com/docs/languages/identifiers"
        )

    def test_hash_is_line_comment(self):
        """'#' должен быть lineComment для Ren'Py."""
        if not _LANG_CONFIG.exists():
            pytest.skip("language-configuration.json отсутствует")
        data = json.loads(_LANG_CONFIG.read_text(encoding="utf-8"))
        comments = data.get("comments", {})
        assert comments.get("lineComment") == "#", (
            "comments.lineComment должен быть '#' для Ren'Py"
        )

    def test_package_json_references_language_config(self):
        """package.json должен ссылаться на language-configuration.json."""
        package_json = _PROJECT_ROOT / "senpy-vscode" / "package.json"
        if not package_json.exists():
            pytest.skip("senpy-vscode/package.json отсутствует")
        data = json.loads(package_json.read_text(encoding="utf-8"))
        languages = data.get("contributes", {}).get("languages", [])
        for lang in languages:
            if lang.get("id") == "renpy":
                config_path = lang.get("configuration", "")
                assert "language-configuration.json" in config_path, (
                    f"package.json: contributes.languages[renpy].configuration "
                    f"должен ссылаться на language-configuration.json, "
                    f"сейчас: '{config_path}'"
                )
                return
        pytest.fail("package.json не содержит contributes.languages с id='renpy'")


# =============================================================================
# P0'-5: UNRPYC_PINNED_SHA256
# =============================================================================

class TestUnrpycPin:
    """P0'-5: UNRPYC_PINNED_SHA256 должен быть реальным значением, не None."""

    def test_pinned_commit_is_not_master(self):
        """UNRPYC_PINNED_COMMIT должен быть конкретным тегом/коммитом, не 'master'."""
        if not _UNRPYC_BOOTSTRAP.exists():
            pytest.skip("_unrpyc_bootstrap.py отсутствует")
        content = _UNRPYC_BOOTSTRAP.read_text(encoding="utf-8")
        match = re.search(
            r'UNRPYC_PINNED_COMMIT\s*=\s*["\']([^"\']+)["\']',
            content,
        )
        assert match, "UNRPYC_PINNED_COMMIT не найден в _unrpyc_bootstrap.py"
        commit = match.group(1)
        assert commit not in ("master", "main", "HEAD"), (
            f"UNRPYC_PINNED_COMMIT = '{commit}' — это ветка, не конкретный коммит. "
            f"Запустите: python scripts/update_unrpyc_pin.py"
        )

    def test_pinned_sha256_is_not_none(self):
        """UNRPYC_PINNED_SHA256 должен быть реальным SHA256, не None placeholder."""
        if not _UNRPYC_BOOTSTRAP.exists():
            pytest.skip("_unrpyc_bootstrap.py отсутствует")
        content = _UNRPYC_BOOTSTRAP.read_text(encoding="utf-8")
        match = re.search(
            r'UNRPYC_PINNED_SHA256\s*=\s*([^#\n]+?)(?:\s*#.*)?$',
            content,
            re.MULTILINE,
        )
        assert match, "UNRPYC_PINNED_SHA256 не найден в _unrpyc_bootstrap.py"
        value = match.group(1).strip()
        # None или None-подобные значения — fail
        assert value not in ("None", "None  # placeholder", 'None  # placeholder — будет вычислен при update'), (
            f"UNRPYC_PINNED_SHA256 = {value} — это placeholder. "
            f"Verification фактически no-op. "
            f"Запустите: python scripts/update_unrpyc_pin.py"
        )
        # Должно быть 64 hex символа
        clean = value.strip('"').strip("'")
        assert re.match(r'^[a-fA-F0-9]{64}$', clean), (
            f"UNRPYC_PINNED_SHA256 = '{clean}' — не похоже на SHA256 hex (64 символа). "
            f"Запустите: python scripts/update_unrpyc_pin.py"
        )


# =============================================================================
# P0'-6: Rule count consistency
# =============================================================================

class TestRuleCountConsistency:
    """P0'-6: Rule count должен быть консистентен между источниками."""

    def _get_actual_rule_count(self) -> int:
        """Считает правила из models.RULE_SEVERITY — canonical source."""
        if not _MODELS_PY.exists():
            pytest.skip("models.py отсутствует")
        content = _MODELS_PY.read_text(encoding="utf-8")
        # Считаем строки вида "RPYxxx": "SEVERITY",
        matches = re.findall(r'"(RPY\d{3})"\s*:\s*"', content)
        return len(set(matches))  # уникальные

    def test_rules_info_py_uses_dynamic_count(self):
        """rules_info.py НЕ должен хардкодить число правил.

        DOC-8a: фикс должен использовать f-string с len(RULES_DATABASE),
        чтобы число правил автоматически подтягивалось из dict'а.
        """
        if not _RULES_INFO_PY.exists():
            pytest.skip("rules_info.py отсутствует")
        content = _RULES_INFO_PY.read_text(encoding="utf-8")
        # Исправлен регэксп): ищем любую строку вида "All N Rules"
        # внутри любой Python-строки — это хардкод. Раньше регэксп требовал,
        # чтобы вся строка была "All N Rules", но реально хардкод встречается
        # как часть title="... (All 45 Rules)" — и тест его пропускал.
        hardcoded = re.findall(r'All\s+\d+\s+Rules', content, re.IGNORECASE)
        assert not hardcoded, (
            f"rules_info.py содержит хардкоженные числа правил: {hardcoded}. "
            f"Замените на f-string: f\"All {{len(RULES_DATABASE)}} Rules\" "
            f"или f\"... (All {{len(RULES_DATABASE)}} Rules)\""
        )

    def test_no_hardcoded_rule_count_in_senpy_toml(self):
        """senpy.toml НЕ должен хардкодить число правил в комментариях."""
        senpy_toml = _PROJECT_ROOT / "senpy.toml"
        if not senpy_toml.exists():
            pytest.skip("senpy.toml отсутствует")
        content = senpy_toml.read_text(encoding="utf-8")
        # Ищем "All N Rules" в комментариях
        hardcoded = re.findall(r'All\s+\d+\s+Rules', content, re.IGNORECASE)
        assert not hardcoded, (
            f"senpy.toml содержит хардкоженные числа правил в комментариях: {hardcoded}. "
            f"Уберите число из комментария или замените на динамический подсчёт."
        )

    def test_rule_count_is_at_least_45(self):
        """На момент аудита 0.5.1 в проекте 45 правил (RPY001-703)."""
        actual = self._get_actual_rule_count()
        assert actual >= 45, (
            f"Ожидается минимум 45 правил (RPY001-703), найдено {actual}. "
            f"Если добавлены новые правила — обновите порог."
        )


# =============================================================================
# Sanity checks
# =============================================================================

class TestSanity:
    """Базовые sanity checks упаковки."""

    def test_version_py_exists(self):
        """senpy/__version__.py должен существовать (single source of truth)."""
        assert _VERSION_PY.exists(), (
            "senpy/__version__.py отсутствует — это single source of truth для версии"
        )

    def test_pyproject_uses_dynamic_version(self):
        """pyproject.toml должен использовать dynamic = ['version']."""
        with _PYPROJECT.open("rb") as f:
            config = tomllib.load(f)
        assert "version" not in config["project"], (
            "pyproject.toml НЕ должен содержать static 'version' field. "
            "Используйте dynamic = ['version'] (см. ECO-9)."
        )
        assert "version" in config.get("project", {}).get("dynamic", []), (
            "pyproject.toml должен содержать dynamic = ['version'] в [project] секции"
        )

    def test_pyproject_has_required_metadata(self):
        """pyproject.toml должен содержать минимально необходимые метаданные."""
        with _PYPROJECT.open("rb") as f:
            config = tomllib.load(f)
        project = config["project"]
        required = ["name", "description", "requires-python", "license", "classifiers"]
        for field in required:
            assert field in project, f"pyproject.toml [project] missing '{field}'"
