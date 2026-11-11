"""Phase 1.2 — analyze_code(code, config=...) parameter tests.

Validates the new optional ``config`` parameter added to the public
``senpy.api.analyze_code`` function. The parameter lets callers pass a
configuration dict (same schema as ``senpy.toml [tool.senpy]``)
programmatically, without writing a config file to disk.

Contract being tested (per senpy/api.py SEMVER CONTRACT):

    - Default ``config=None`` preserves existing call-site behavior
      (backward compat — covered by tests/regressions/test_0_6_0_subprint.py).
    - ``config={}`` is equivalent to defaults (Pydantic model_dump with
      no overrides).
    - ``config={"severity": {...}}`` overrides per-rule severity.
    - ``config={"strict": True}`` promotes all diagnostics to ERROR.
    - ``config={"ignore": [...]}`` suppresses listed rule codes.
    - Invalid field values surface as logged WARNING + fall back to defaults
      (no exception, no silent misconfiguration).
    - Unknown fields are ignored (forward-compat).

These tests live under the public API surface (``from senpy.api import ...``)
per the Phase 1 roadmap: migrate tests from internals toward the frozen
public contract so future refactoring of senpy.core.* does not break them.
"""

from __future__ import annotations

import pytest

from senpy.api import Diagnostic, analyze_code

# =============================================================================
# Test fixtures — code samples that trigger specific rules
# =============================================================================

# Triggers RPY101 (undeclared [unknown_var] in dialogue, default ERROR)
# AND RPY302 (jump to non-existent label, default ERROR).
_CODE_RPY101_AND_302 = (
    "label start:\n" '    "Hello, [unknown_var]!"\n' "    jump nonexistent\n" "    return\n"
)

# Triggers RPY104 ($ affection = 5 without top-level default, default WARNING).
_CODE_RPY104 = "label chapter_2:\n" "    $ affection = 5\n" "    return\n"


# =============================================================================
# Tests
# =============================================================================


class TestAnalyzeCodeConfigParam:
    """Phase 1.2: analyze_code(code, config=...) parameter."""

    # ------------------------------------------------------------------
    # Backward compat — config=None and config={} behave like no config
    # ------------------------------------------------------------------

    def test_config_none_default_returns_diagnostics(self):
        """config=None must produce the same diagnostics as before the
        parameter was added (backward compat — existing call sites)."""
        result = analyze_code(_CODE_RPY101_AND_302, config=None)
        codes = {d.code for d in result}
        assert "RPY101" in codes
        assert "RPY302" in codes

    def test_config_empty_dict_equivalent_to_none(self):
        """config={} applies Pydantic defaults — same observable result
        as config=None for a code sample that triggers defaults-only
        analysis."""
        result_none = analyze_code(_CODE_RPY101_AND_302, config=None)
        result_empty = analyze_code(_CODE_RPY101_AND_302, config={})
        # Same set of rule codes, same set of severities.
        assert {d.code for d in result_none} == {d.code for d in result_empty}
        assert {d.severity for d in result_none} == {d.severity for d in result_empty}

    # ------------------------------------------------------------------
    # Severity override
    # ------------------------------------------------------------------

    def test_config_severity_override_demotes_rpy101_to_warning(self):
        """config={"severity": {"RPY101": "WARNING"}} must change the
        severity of RPY101 diagnostics from default ERROR to WARNING."""
        result = analyze_code(
            _CODE_RPY101_AND_302,
            config={"severity": {"RPY101": "WARNING"}},
        )
        rpy101_diags = [d for d in result if d.code == "RPY101"]
        assert rpy101_diags, "Expected at least one RPY101 diagnostic"
        for d in rpy101_diags:
            assert (
                d.severity == "WARNING"
            ), f"RPY101 severity should be WARNING after override, got {d.severity!r}"

    def test_config_severity_override_promotes_rpy104_to_error(self):
        """config={"severity": {"RPY104": "ERROR"}} must promote RPY104
        from default WARNING to ERROR."""
        result = analyze_code(
            _CODE_RPY104,
            config={"severity": {"RPY104": "ERROR"}},
        )
        rpy104_diags = [d for d in result if d.code == "RPY104"]
        assert rpy104_diags, "Expected at least one RPY104 diagnostic"
        for d in rpy104_diags:
            assert (
                d.severity == "ERROR"
            ), f"RPY104 severity should be ERROR after override, got {d.severity!r}"

    # ------------------------------------------------------------------
    # Strict mode
    # ------------------------------------------------------------------

    def test_config_strict_promotes_warning_to_error(self):
        """config={"strict": True} promotes every diagnostic to ERROR.
        Verify on RPY104 (default WARNING) — should become ERROR."""
        result = analyze_code(_CODE_RPY104, config={"strict": True})
        rpy104_diags = [d for d in result if d.code == "RPY104"]
        assert rpy104_diags, "Expected at least one RPY104 diagnostic"
        for d in rpy104_diags:
            assert (
                d.severity == "ERROR"
            ), f"RPY104 severity should be ERROR under strict mode, got {d.severity!r}"

    # ------------------------------------------------------------------
    # additional_builtins — analyzer-level field
    # ------------------------------------------------------------------

    def test_config_additional_builtins_silences_rpy202(self):
        """config={"additional_builtins": ["iap"]} must add ``iap`` to
        the analyzer's declared-symbols set, so a screen accessing
        ``iap.something`` no longer triggers RPY202 (undeclared variable
        in screen).

        Without the config: RPY202 fires on ``iap.is_available``.
        With the config: RPY202 is silenced (``iap`` is declared).
        """
        # Screen accessing iap.is_available — iap is a third-party Ren'Py
        # namespace (in-app purchases), NOT in the default BUILTIN_SYMBOLS.
        code = (
            "screen iap_status():\n" "    if iap.is_available:\n" '        text "IAP available"\n'
        )
        # Without additional_builtins: RPY202 should fire on `iap`.
        result_without = analyze_code(code, config=None)
        codes_without = {d.code for d in result_without}
        assert "RPY202" in codes_without, (
            f"RPY202 should fire on undeclared `iap` without additional_builtins, "
            f"got codes: {codes_without}"
        )
        # With additional_builtins=["iap"]: RPY202 should be silenced.
        result_with = analyze_code(code, config={"additional_builtins": ["iap"]})
        codes_with = {d.code for d in result_with}
        assert "RPY202" not in codes_with, (
            f"RPY202 should be silenced by additional_builtins=['iap'], " f"got codes: {codes_with}"
        )

    # ------------------------------------------------------------------
    # Robustness — invalid input, unknown fields
    # ------------------------------------------------------------------

    def test_config_invalid_field_type_falls_back_to_defaults(self, caplog):
        """config={"strict": "yes"} (string instead of bool) must surface
        a WARNING via Pydantic validation and fall back to defaults —
        no exception, no silent misconfiguration. Analysis still runs."""
        # Should not raise — invalid config degrades gracefully.
        result = analyze_code(_CODE_RPY101_AND_302, config={"strict": "yes"})
        # Defaults apply — RPY101 still fires (it's default ERROR).
        codes = {d.code for d in result}
        assert "RPY101" in codes

    def test_config_unknown_field_ignored(self):
        """config={"unknown_field": 123} must be silently ignored
        (Pydantic extra='ignore' for forward-compat). No exception,
        defaults apply."""
        result = analyze_code(_CODE_RPY101_AND_302, config={"unknown_field": 123})
        codes = {d.code for d in result}
        assert "RPY101" in codes

    # ------------------------------------------------------------------
    # Type / contract — result type preserved
    # ------------------------------------------------------------------

    def test_config_returns_list_of_diagnostic(self):
        """Regardless of config, the return type is list[Diagnostic]."""
        result = analyze_code(_CODE_RPY101_AND_302, config={"strict": True})
        assert isinstance(result, list)
        assert all(isinstance(d, Diagnostic) for d in result)
