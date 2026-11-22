"""RED→GREEN tests for config validation (rule codes + severity + explicit path).

Three roadmap items in senpy/core/config.py:

  * the rule-code validation fix — ``ignore`` / ``select`` / ``extend_select`` / ``extend_ignore``
    accept any string, so a typo (``RPY014`` instead of ``RPY104``) or a
    non-existent code (``RPY999``) is accepted silently — the rule never
    fires because the filter matches nothing. Fix: a pydantic
    ``field_validator`` against ``RULES_DATABASE`` keys, logging a WARNING
    for unknown codes (not rejecting — forward-compat for plugin codes
    that are not in the built-in database yet).

  * the severity-dict validation fix — ``severity`` dict accepts any keys AND any values:
    ``{"RPY999": "BLOCKER"}`` or ``{"RPY104": "error"}`` (lowercase) pass
    silently. Fix: a ``field_validator`` that checks keys the same way as
    the rule-code validation fix and values against the four allowed severities (ERROR /
    WARNING / INFO / HINT), logging a WARNING and dropping the bad pair.

  * the missing-config-path warning fix — ``load_config`` silently falls back when an explicit
    ``--config /nonexistent.toml`` is passed but the file does not
    exist. The user believes their config is applied, but it is not.
    Fix: log a WARNING once before the fallback search starts.

The forward-compat contract (WARN, not reject) is critical: plugins
register rule codes outside the built-in RULES_DATABASE at runtime, so
rejecting an unknown code would break configs that reference plugin
rules. The validator must accept every code and only warn.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from senpy.core.config import load_config, validate_config
from senpy.core.logging import setup_logging


@pytest.fixture(autouse=True)
def reset_logging():
    """Clean logger config — NullHandler, propagate=True (caplog works)."""
    setup_logging()
    yield


# ===========================================================================
# the rule-code validation fix: rule-code validation in ignore / select / extend_select / extend_ignore
# ===========================================================================


def test_validate_config_warns_on_unknown_rule_code_in_ignore(caplog):
    """An unknown rule code in ``ignore`` must log a WARNING (not silently pass).

    RED today: ``ignore = ["RPY999"]`` is accepted verbatim; the user
    believes RPY999 is suppressed, but RPY999 does not exist so nothing
    is suppressed and there is no signal that the code is wrong.
    """
    config = {"ignore": ["RPY999"]}
    with caplog.at_level(logging.WARNING, logger="senpy.config"):
        validated = validate_config(config)
    # Forward-compat: the code is still in the output (plugin rules may
    # register it at runtime); the point is that a WARNING was logged.
    assert validated["ignore"] == ["RPY999"], (
        "unknown codes must NOT be dropped from the config (forward-compat "
        "for plugin rules) — only warned about"
    )
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "no WARNING logged for unknown rule code in ignore — the rule-code validation fix not applied"
    msg = warnings[0].getMessage()
    assert "RPY999" in msg, f"warning must name the unknown code; got: {msg!r}"


def test_validate_config_warns_on_typo_rule_code_in_select(caplog):
    """A typo (RPY014 instead of RPY104) in ``select`` must warn.

    This is the canonical the rule-code validation fix example: the user mistyped the rule
    code and never realises their select filter matches nothing.
    """
    config = {"select": ["RPY014"]}
    with caplog.at_level(logging.WARNING, logger="senpy.config"):
        validate_config(config)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert (
        warnings
    ), "no WARNING logged for typo rule code in select — the rule-code validation fix not applied"
    msg = warnings[0].getMessage()
    assert "RPY014" in msg, f"warning must name the typo code; got: {msg!r}"


def test_validate_config_does_not_warn_on_known_rule_code(caplog):
    """A known rule code in any of the four filter fields must NOT warn."""
    config = {
        "ignore": ["RPY104"],
        "select": ["RPY101"],
        "extend_select": ["RPY102"],
        "extend_ignore": ["RPY105"],
    }
    with caplog.at_level(logging.WARNING, logger="senpy.config"):
        validate_config(config)
    rule_warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING and "RPY" in r.getMessage()
    ]
    assert not rule_warnings, "known rule codes must not produce a WARNING; got: " + str(
        [r.getMessage() for r in rule_warnings]
    )


def test_validate_config_warns_on_each_filter_field(caplog):
    """Each of the four filter fields must be validated independently.

    A typo in ``extend_select`` or ``extend_ignore`` must be caught
    too — not just ``ignore`` and ``select``.
    """
    config = {
        "ignore": ["RPY900"],
        "select": ["RPY901"],
        "extend_select": ["RPY902"],
        "extend_ignore": ["RPY903"],
    }
    with caplog.at_level(logging.WARNING, logger="senpy.config"):
        validate_config(config)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    # All four codes must be mentioned (one warning per code, or one
    # warning listing all four — either is acceptable as long as all
    # four appear across the captured warnings).
    combined = " ".join(r.getMessage() for r in warnings)
    for code in ("RPY900", "RPY901", "RPY902", "RPY903"):
        assert code in combined, f"{code} must be mentioned in a warning; combined: {combined!r}"


# ===========================================================================
# the severity-dict validation fix: severity dict — validate keys AND values
# ===========================================================================


def test_validate_config_warns_on_unknown_severity_key(caplog):
    """An unknown rule code as a severity key must warn.

    ``{"RPY999": "ERROR"}`` — the key is an unknown code; the user
    thinks they are overriding RPY999's severity, but RPY999 does not
    exist.
    """
    config = {"severity": {"RPY999": "ERROR"}}
    with caplog.at_level(logging.WARNING, logger="senpy.config"):
        validate_config(config)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert (
        warnings
    ), "no WARNING for unknown severity key — the severity-dict validation fix not applied"
    combined = " ".join(r.getMessage() for r in warnings)
    assert "RPY999" in combined, f"warning must name the unknown key; got: {combined!r}"


def test_validate_config_warns_on_invalid_severity_value(caplog):
    """An invalid severity value must warn.

    ``{"RPY104": "BLOCKER"}`` — BLOCKER is not a Senpy severity (the
    allowed set is ERROR / WARNING / INFO / HINT). The override is
    silently ignored today because no rule consumes the value.
    """
    config = {"severity": {"RPY104": "BLOCKER"}}
    with caplog.at_level(logging.WARNING, logger="senpy.config"):
        validate_config(config)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert (
        warnings
    ), "no WARNING for invalid severity value — the severity-dict validation fix not applied"
    combined = " ".join(r.getMessage() for r in warnings)
    assert "BLOCKER" in combined, f"warning must name the bad value; got: {combined!r}"


def test_validate_config_warns_on_lowercase_severity_value(caplog):
    """A lowercase severity value must warn (Senpy uses uppercase).

    ``{"RPY104": "error"}`` — common typo from users used to other
    linters. Today accepted silently; the severity override has no
    effect because the consumer compares against the uppercase
    constant.
    """
    config = {"severity": {"RPY104": "error"}}
    with caplog.at_level(logging.WARNING, logger="senpy.config"):
        validate_config(config)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert (
        warnings
    ), "no WARNING for lowercase severity — the severity-dict validation fix not applied"
    combined = " ".join(r.getMessage() for r in warnings)
    assert "error" in combined, f"warning must name the lowercase value; got: {combined!r}"


def test_validate_config_does_not_warn_on_valid_severity(caplog):
    """A valid severity override must NOT warn."""
    config = {
        "severity": {
            "RPY104": "ERROR",
            "RPY308": "INFO",
            "RPY101": "WARNING",
            "RPY302": "HINT",
        }
    }
    with caplog.at_level(logging.WARNING, logger="senpy.config"):
        validate_config(config)
    sev_warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "severity" in r.getMessage().lower()
    ]
    assert not sev_warnings, "valid severity overrides must not warn; got: " + str(
        [r.getMessage() for r in sev_warnings]
    )


# ===========================================================================
# the missing-config-path warning fix: load_config warns when explicit --config path is missing
# ===========================================================================


def test_load_config_warns_on_missing_explicit_config_path(tmp_path: Path, caplog, monkeypatch):
    """An explicit ``--config /nonexistent.toml`` must warn before fallback.

    RED today: ``load_config(project, config_path="/nonexistent.toml")``
    silently skips the missing file and falls back to the default
    candidates. The user believes their config is applied.

    We isolate CWD so no ``senpy.toml`` / ``pyproject.toml`` is found
    in the cwd, and the project dir has none either, so the fallback
    produces an empty config — but the WARNING must still be emitted.
    """
    empty_cwd = tmp_path / "empty_cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)

    project = tmp_path / "my_project"
    project.mkdir()

    bogus_config = str(tmp_path / "does_not_exist.toml")

    with caplog.at_level(logging.WARNING, logger="senpy.config"):
        load_config(str(project), config_path=bogus_config)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    missing_warnings = [
        r
        for r in warnings
        if "does_not_exist.toml" in r.getMessage()
        or "not found" in r.getMessage().lower()
        or "explicit" in r.getMessage().lower()
    ]
    assert missing_warnings, (
        "no WARNING logged when explicit --config path is missing — "
        "the missing-config-path warning fix not applied"
    )
    msg = missing_warnings[0].getMessage()
    assert "does_not_exist.toml" in msg, f"warning must name the missing file; got: {msg!r}"


def test_load_config_no_warning_when_explicit_path_exists(tmp_path: Path, caplog, monkeypatch):
    """An explicit ``--config <existing>`` must NOT produce the missing-path warning.

    Guards against a regression where the warning fires even for
    present files.
    """
    empty_cwd = tmp_path / "empty_cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)

    project = tmp_path / "my_project"
    project.mkdir()
    config_file = tmp_path / "my_config.toml"
    config_file.write_text("[senpy]\nmax_errors = 10\n", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="senpy.config"):
        result = load_config(str(project), config_path=str(config_file))

    missing_warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING
        and ("not found" in r.getMessage().lower() or "explicit" in r.getMessage().lower())
    ]
    assert not missing_warnings, (
        "no missing-path WARNING expected when the explicit config exists; got: "
        + str([r.getMessage() for r in missing_warnings])
    )
    # Sanity: the config was actually loaded.
    assert result.get("max_errors") == 10
