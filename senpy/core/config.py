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

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from senpy.core.logging import get_logger
from senpy.rules.rules_info import RULES_DATABASE

_logger = get_logger("config")


# The four severities Senpy produces and consumes. Matches the set
# actually present in RULES_DATABASE (see rules_info.py). Used by the
# severity-dict validator to reject typos like "BLOCKER" or lowercase
# "error" before they silently fail to override a rule's severity.
_ALLOWED_SEVERITIES = frozenset({"ERROR", "WARNING", "INFO", "HINT"})


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
    # When None (default), auto-detect from project structure. When True,
    # suppress RPY504 warnings for intentional image overrides (e.g. mod
    # assets replacing base game images). When False, always warn.
    allow_image_overrides: bool | None = None
    # When False, disables both Tier 1 (symbol cache) and Tier 2 (diagnostic
    # cache). Equivalent to CLI --no-cache, but configurable via TOML.
    cache: bool = True
    strict: bool = False  # : all rules = ERROR

    # Rule filtering
    ignore: list[str] = Field(default_factory=list)
    select: list[str] = Field(default_factory=list)
    extend_select: list[str] = Field(default_factory=list)
    extend_ignore: list[str] = Field(default_factory=list)

    # Severity overrides: {"RPY104": "ERROR", ...}
    severity: dict[str, str] = Field(default_factory=dict)

    @field_validator("ignore", "select", "extend_select", "extend_ignore")
    @classmethod
    def _validate_rule_codes(cls, value: list[str]) -> list[str]:
        """Warn (do not reject) on rule codes absent from RULES_DATABASE.

        Why warn-not-reject: plugins register rule codes at runtime
        (see senpy/plugins/loader.py), and those codes are NOT in the
        built-in RULES_DATABASE at config-validation time. Rejecting
        would break any config that references a plugin rule. The
        validator's job is to surface typos (``RPY014`` instead of
        ``RPY104``) and clearly-nonexistent codes (``RPY999``) — the
        user decides what to do with the warning.

        Returns the list unchanged (forward-compat).
        """
        if not value:
            return value
        unknown = [c for c in value if c not in RULES_DATABASE]
        if unknown:
            _logger.warning(
                "Config: rule code(s) not in built-in RULES_DATABASE: %s. "
                "If this is a plugin rule, ignore this warning; otherwise "
                "check for a typo (e.g. RPY014 vs RPY104).",
                ", ".join(unknown),
            )
        return value

    @field_validator("severity")
    @classmethod
    def _validate_severity(cls, value: dict[str, str]) -> dict[str, str]:
        """Validate both keys (rule codes) and values (severities).

        Keys: same warn-not-reject contract as the rule-code filter
        above — plugin rules may override their own severity with a
        code not in the built-in database.

        Values: must be one of ERROR / WARNING / INFO / HINT. Invalid
        values (``"BLOCKER"``, lowercase ``"error"``) are dropped from
        the returned dict and a WARNING is logged naming the bad pair,
        because the consumer (``_apply_severity``) compares against the
        uppercase constants and would silently no-op otherwise.
        """
        if not value:
            return value
        unknown_keys = [k for k in value if k not in RULES_DATABASE]
        if unknown_keys:
            _logger.warning(
                "Config: severity key(s) not in built-in RULES_DATABASE: %s. "
                "If this is a plugin rule, ignore this warning; otherwise "
                "check for a typo.",
                ", ".join(unknown_keys),
            )
        bad_values = {k: v for k, v in value.items() if v not in _ALLOWED_SEVERITIES}
        if bad_values:
            _logger.warning(
                "Config: invalid severity value(s) (allowed: "
                "ERROR, WARNING, INFO, HINT): %s. "
                "These overrides will be dropped.",
                ", ".join(f"{k}={v!r}" for k, v in bad_values.items()),
            )
            # Drop the bad pairs so the consumer never sees an
            # unrecognised severity. Keep valid pairs and unknown-key
            # pairs (the latter may belong to a plugin rule).
            value = {k: v for k, v in value.items() if v in _ALLOWED_SEVERITIES}
        return value

    # Plugin execution — opt-in (default false). When False, plugin rules
    # are loaded and visible in `senpy rule list`, but their check()
    # methods are NOT invoked during analysis. When True, registered Rule
    # subclasses are invoked per-file during _analyze_file. Default stays
    # False until plugin API stabilises (post-1.0, see roadmap).
    enable_plugins: bool = False

    # User-extended Ren'Py built-in namespaces / screen actions. These
    # are MERGED with the defaults shipped in
    # `senpy/core/renpy_builtins.py` (BUILTIN_SYMBOLS / BUILTIN_ACTIONS)
    # at analyzer-init time, so the user does not need to redeclare
    # everything Senpy already knows about — only what is missing.
    #
    # `additional_builtins` covers runtime-provided namespaces like
    # ``iap`` (in-app purchases), ``updater``, ``build``, or any
    # user-installed Ren'Py library that registers a global name.
    # Adding a name here makes RPY202 / RPY103 / RPY104 treat it as
    # declared — same behaviour as ``renpy`` or ``persistent``.
    #
    # `additional_actions` covers user-defined or third-party screen
    # Action classes that can be called with ``()`` in the ``action``
    # slot of a screen button. Adding a name here stops RPY206 from
    # firing on ``action MyCustomAction()``.
    #
    # Both default to empty lists. Invalid identifiers (non-ASCII,
    # starting with a digit, etc.) are silently filtered at merge time
    # to avoid breaking the symbol table.
    additional_builtins: list[str] = Field(default_factory=list)
    additional_actions: list[str] = Field(default_factory=list)


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


def load_config(project_path: str, config_path: str | None = None) -> dict:
    """Find and read the Senpy configuration.

    Searches for senpy.toml or pyproject.toml in this order:
        1. If ``config_path`` is passed (CLI ``--config FILE``) — that file.
        2. If ``SENPY_CONFIG`` env var is set — that file.
        3. In project_path/
        4. In the parent directory of project_path/
        5. In the current working directory

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
        config_path: Optional explicit path to a senpy.toml config file
            (CLI ``--config FILE``). If passed, this file is tried first;
            if it does not exist or is invalid, the search falls back to
            the default candidates. Previously this parameter did not
            exist and ``--config`` was a dead flag (P1-5).

    Returns:
        Dict with the configuration. Empty dict if the config is not found or broken.
    """
    # Build the candidate list. Explicit config_path (CLI --config) and
    # SENPY_CONFIG env var take priority over the default search order.
    #
    # the missing-config-path warning fix: if the user passed an explicit ``--config /path`` and that
    # file does not exist, warn once before the fallback search. Without
    # this the user believes their config is applied (they typed the
    # flag deliberately) while in fact load_config silently falls back
    # to the default candidates and the override has no effect.
    if config_path and not os.path.isfile(config_path):
        _logger.warning(
            "Config: explicit --config %s not found; falling back to "
            "default search (senpy.toml / pyproject.toml in project, "
            "parent, and cwd).",
            config_path,
        )
    candidates: list[str] = []
    if config_path:
        candidates.append(config_path)
    env_config = os.environ.get("SENPY_CONFIG")
    if env_config:
        candidates.append(env_config)
    candidates.extend(
        [
            os.path.join(project_path, "senpy.toml"),
            os.path.join(project_path, "pyproject.toml"),
            os.path.join(os.path.dirname(project_path), "senpy.toml"),
            os.path.join(os.path.dirname(project_path), "pyproject.toml"),
            os.path.join(os.getcwd(), "senpy.toml"),
            os.path.join(os.getcwd(), "pyproject.toml"),
        ]
    )
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
