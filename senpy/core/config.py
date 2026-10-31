"""Конфигурация Senpy — чтение senpy.toml / pyproject.toml.

Вынесено из senpy/_unrpyc_bootstrap.py в Фазе 1.2 (0.5.3) для разрыва
циклической зависимости analyzer ↔ cli.

Раньше load_config лежала в _unrpyc_bootstrap.py, и analyzer.py делал
`from senpy.cli.main import load_config` (cli просто реэкспортировал её из
_unrpyc_bootstrap). Это создавало цикл:
    analyzer.py → cli.py → analyzer.py

Теперь load_config в этом модуле (senpy/config.py), и все зависят от него
однонаправленно:
    analyzer.py → senpy.config
    cli.py → senpy.config
    _unrpyc_bootstrap.py → senpy.config (возможно?)

Public API:
    load_config(project_path: str) -> dict
    validate_config(raw: dict) -> dict    (CLI-16: pydantic валидация)
"""
from __future__ import annotations

import os
import tomllib

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from senpy.core.logging import get_logger

_logger = get_logger("config")


# =============================================================================
# pydantic-модель для валидации конфига
# =============================================================================

class SenpyConfig(BaseModel):
    """Pydantic-схема конфигурации Senpy ([tool.senpy] секция).

    Все поля опциональны — если не указаны в TOML, используются дефолты.
    Неизвестные поля игнорируются (extra='ignore') для forward-compat
    (новые поля в будущих версиях Senpy не сломают старые инсталляции).
    """

    model_config = ConfigDict(
        extra="ignore",  # Неизвестные поля игнорируются
        str_strip_whitespace=True,  # Стрипаем строки автоматически
        # strict=True — pydantic НЕ делает type coercion (string "yes" не
        # становится bool True). Для конфига это важно: если юзер написал
        # decompile = "yes" вместо decompile = true, это явная ошибка,
        # которую надо показать, а не молча интерпретировать.
        strict=True,
    )

    # Сканирование
    decompile: bool = False
    max_errors: int = 50
    info: bool = False
    errors_only: bool = False
    tsundere: bool = False
    unrpyc_path: str | None = None
    allow_image_overrides: bool | None = None
    strict: bool = False  # RULE-16: все правила = ERROR

    # Rule filtering (CLI-1)
    ignore: list[str] = Field(default_factory=list)
    select: list[str] = Field(default_factory=list)
    extend_select: list[str] = Field(default_factory=list)
    extend_ignore: list[str] = Field(default_factory=list)

    # Severity overrides: {"RPY104": "ERROR", ...}
    severity: dict[str, str] = Field(default_factory=dict)


def validate_config(raw: dict) -> dict:
    """CLI-16: валидирует raw config dict через pydantic.

    Если конфиг валиден — возвращает dict с применёнными дефолтами.
    Если невалиден — логирует WARNING и возвращает пустой dict (fallback).

    Args:
        raw: Raw dict из TOML (секция [tool.senpy] или [senpy]).

    Returns:
        Валидированный dict с дефолтами, или пустой dict при ошибке.
    """
    if not raw:
        # Пустой конфиг — возвращаем дефолты
        return SenpyConfig().model_dump()

    try:
        config = SenpyConfig(**raw)
        return config.model_dump()
    except ValidationError as e:
        # CLI-16: логируем понятное сообщение об ошибке валидации.
        # Раньше (без pydantic) невалидные поля молча игнорировались, что
        # приводило к часам дебага "почему мой max_errors не работает?".
        _logger.warning(
            "Config validation failed: %s. Falling back to default config. "
            "Check senpy.toml [tool.senpy] section for type errors.",
            e,
        )
        return {}


def load_config(project_path: str) -> dict:
    """Найти и прочитать конфигурацию Senpy.

    Ищет senpy.toml или pyproject.toml в порядке:
        1. В project_path/
        2. В родительской директории project_path/
        3. В текущей рабочей директории

    Возвращает содержимое секции [tool.senpy] (или [senpy] для senpy.toml),
    провалидированное через pydantic (CLI-16).
    Если ни один файл не найден или TOML невалиден — возвращает пустой dict.

    Ошибки парсинга/чтения логируются как WARNING (раньше молча
    проглатывались через contextlib.suppress). Без логирования пользователь
    не понимает почему его конфиг игнорируется — несколько часов дебага.

    После парсинга TOML конфиг валидируется через pydantic.
    Невалидные поля (например, max_errors = "много") логируются как WARNING,
    возвращается пустой конфиг (fallback).

    Args:
        project_path: Путь к Ren'Py-проекту или папке с конфигом.

    Returns:
        Dict с конфигурацией. Пустой dict если конфиг не найден или битый.
    """
    candidates = [
        os.path.join(project_path, "senpy.toml"),
        os.path.join(project_path, "pyproject.toml"),
        os.path.join(os.path.dirname(project_path), "senpy.toml"),
        os.path.join(os.path.dirname(project_path), "pyproject.toml"),
        os.path.join(os.getcwd(), "senpy.toml"),
        os.path.join(os.getcwd(), "pyproject.toml"),
    ]
    for c in candidates:
        if not os.path.isfile(c):
            continue
        try:
            with open(c, "rb") as f:
                data = tomllib.load(f)
            raw_config = data.get("tool", {}).get("senpy", data.get("senpy", {}))
            # Валидация через pydantic
            return validate_config(raw_config)
        except tomllib.TOMLDecodeError as e:
            # Логируем битый TOML — юзер должен знать почему конфиг
            # игнорируется. Без этого — часы дебага "почему мои ignore-правила
            # не работают?".
            _logger.warning(
                "TOMLDecodeError reading config %s: %s. Falling back to "
                "default (empty) config.",
                c, e,
            )
        except OSError as e:
            # Permission denied, disk error, etc. — тоже логируем.
            _logger.warning(
                "OSError reading config %s: %s. Falling back to "
                "default (empty) config.",
                c, e,
            )
    return {}
