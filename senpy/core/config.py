"""Senpy configuration — reading senpy.toml / pyproject.toml.

Extracted from senpy/_unrpyc_bootstrap.py in Phase 1.2 (0.5.3) to break
the circular dependency analyzer ↔ cli.

Previously load_config lived in _unrpyc_bootstrap.py, and analyzer.py did
`from senpy.cli.main import load_config` (cli simply re-exported it from
_unrpyc_bootstrap). This created a cycle:
    analyzer.py → cli.py → analyzer.py

Now load_config lives in this module (senpy/config.py), and everything depends
on it in one direction:
    analyzer.py → senpy.config
    cli.py → senpy.config
    _unrpyc_bootstrap.py → senpy.config (maybe?)

Public API:
    load_config(project_path: str) -> dict
    validate_config(raw: dict) -> dict    (: pydantic validation)
"""

from __future__ import annotations

import os
import tomllib

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from senpy.core.logging import get_logger

_logger = get_logger("config")


# =============================================================================
# Pydantic model for config validation
# =============================================================================


class SenpyConfig(BaseModel):
    """Pydantic schema for Senpy configuration ([tool.senpy] section).

    All fields are optional — if not specified in TOML, defaults are used.
    Unknown fields are ignored (extra='ignore') for forward-compat
    (new fields in future Senpy versions will not break old installs).
    """

    model_config = ConfigDict(
        extra="ignore",  # Unknown fields are ignored
        str_strip_whitespace=True,  # Strip strings automatically
        # strict=True — pydantic does NOT do type coercion (string "yes" does not
        # become bool True). For config this is important: if the user wrote
        # decompile = "yes" instead of decompile = true, that's a clear error
        # to surface, not something to silently interpret.
        strict=True,
    )

    # Scanning
    decompile: bool = False
    max_errors: int = 50
    info: bool = False
    errors_only: bool = False
    tsundere: bool = False
    unrpyc_path: str | None = None
    allow_image_overrides: bool | None = None
    strict: bool = False  # : all rules = ERROR

    # Rule filtering
    ignore: list[str] = Field(default_factory=list)
    select: list[str] = Field(default_factory=list)
    extend_select: list[str] = Field(default_factory=list)
    extend_ignore: list[str] = Field(default_factory=list)

    # Severity overrides: {"RPY104": "ERROR", ...}
    severity: dict[str, str] = Field(default_factory=dict)

    # Plugin execution — opt-in for 0.8.0 (default false). When False,
    # plugin rules are loaded and visible in `senpy rule list`, but
    # their check() methods are NOT invoked during analysis. When True,
    # registered Rule subclasses are invoked per-file during _analyze_file.
    # Default flips to True in 0.9.0 after the plugin API stabilises
    # (see T-003 in WORKLOG).
    enable_plugins: bool = False


def validate_config(raw: dict) -> dict:
    """Validates a raw config dict via pydantic.

    If the config is valid — returns a dict with defaults applied.
    If invalid — logs a WARNING and returns an empty dict (fallback).

    Args:
        raw: Raw dict from TOML ([tool.senpy] or [senpy] section).

    Returns:
        Validated dict with defaults, or an empty dict on error.
    """
    if not raw:
        # Empty config — return defaults
        return SenpyConfig().model_dump()

    try:
        config = SenpyConfig(**raw)
        return config.model_dump()
    except ValidationError as e:
        # Log a clear validation error message.
        # Previously (without pydantic) invalid fields were silently ignored,
        # which led to hours of debugging "why is my max_errors not working?".
        _logger.warning(
            "Config validation failed: %s. Falling back to default config. "
            "Check senpy.toml [tool.senpy] section for type errors.",
            e,
        )
        return {}


def load_config(project_path: str) -> dict:
    """Find and read the Senpy configuration.

    Searches for senpy.toml or pyproject.toml in this order:
        1. In project_path/
        2. In the parent directory of project_path/
        3. In the current working directory

    Returns the contents of the [tool.senpy] section (or [senpy] for senpy.toml),
    validated via pydantic.
    If no file is found or the TOML is invalid — returns an empty dict.

    Parse/read errors are logged as WARNING (previously they were silently
    swallowed via contextlib.suppress). Without logging the user does not
    understand why their config is being ignored — hours of debugging.

    After parsing the TOML the config is validated via pydantic.
    Invalid fields (e.g. max_errors = "a lot") are logged as WARNING,
    and an empty config is returned (fallback).

    Args:
        project_path: Path to the Ren'Py project or the folder with the config.

    Returns:
        Dict with the configuration. Empty dict if the config is not found or broken.
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
            # Validation via pydantic
            return validate_config(raw_config)
        except tomllib.TOMLDecodeError as e:
            # Log the broken TOML — the user should know why the config
            # is being ignored. Without this — hours of debugging "why are
            # my ignore rules not working?".
            _logger.warning(
                "TOMLDecodeError reading config %s: %s. Falling back to default (empty) config.",
                c,
                e,
            )
        except OSError as e:
            # Permission denied, disk error, etc. — also log it.
            _logger.warning(
                "OSError reading config %s: %s. Falling back to default (empty) config.",
                c,
                e,
            )
    return {}
