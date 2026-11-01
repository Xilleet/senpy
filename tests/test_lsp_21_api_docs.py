"""auto-generated API docs merge + lookup tests.

Covers three layers:

1. ``scripts/fetch_renpy_docs.py`` — parser unit tests on synthetic RST
   and Python source samples. These don't hit the network; they verify
   the regex/directive walker produces correct entries from known input.

2. ``senpy/domain/renpy_api_generated.py`` — sanity checks on the
   generated module: it exists, imports cleanly, has the expected
   shape (dict of dicts), and contains entries from namespaces that
   the curated dict does NOT cover (config.*, gui.*, build.*,
   style/transform properties).

3. ``senpy/domain/renpy_api.py`` — merge logic: ``RENPY_API_DOCS_ALL``
   is curated ∪ generated with curated winning on key collision, and
   ``get_renpy_api_hover`` looks up via the merged dict.

The integration test (hover on ``config.name`` resolves to a generated
entry with the right signature) is the end-to-end proof that 
closes the coverage gap.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make scripts/ importable so we can test the fetcher without installing it.
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scripts.fetch_renpy_docs import (  # noqa: E402
    _RE_ARGS_DIRECTIVE,
    _RE_CLASS,
    _RE_FUNC,
    _RE_PROP,
    _RE_VAR,
    _collect_python_docstring,
    _extract_signature_from_init,
    _namespace_of,
    collect_description,
    parse_rpy_file,
    parse_rst_file,
    serialize_python_module,
)
from senpy.domain.renpy_api import (  # noqa: E402
    RENPY_API_DOCS,
    RENPY_API_DOCS_ALL,
    get_renpy_api_hover,
)
from senpy.domain.renpy_api_generated import (  # noqa: E402
    RENPY_API_DOCS_GENERATED,
    RENPY_DOC_GENERATED_AT,
    RENPY_DOC_VERSION_GENERATED,
)

# =============================================================================
# Section 1: RST directive regexes
# =============================================================================


class TestRstDirectiveRegexes:
    """Verify the regex matchers for RST directives behave as expected."""

    def test_var_with_default(self):
        m = _RE_VAR.match(".. var:: config.name = \"My Game\"")
        assert m is not None
        assert m.group(1) == "config.name"
        assert m.group(2) == '"My Game"'

    def test_var_without_default(self):
        m = _RE_VAR.match(".. var:: config.name")
        assert m is not None
        assert m.group(1) == "config.name"
        assert m.group(2) is None

    def test_var_rejects_non_var_directive(self):
        assert _RE_VAR.match(".. function:: renpy.pause()") is None
        assert _RE_VAR.match(".. class:: Foo") is None

    def test_function_directive(self):
        m = _RE_FUNC.match(".. function:: renpy.pause(delay=None, hard=False)")
        assert m is not None
        assert m.group(1) == "renpy.pause"
        assert m.group(2) == "delay=None, hard=False"

    def test_function_no_params_rejected(self):
        # The regex requires parentheses; bare names don't match.
        # Ren'Py RST always uses ``.. function:: name(params)`` so this
        # is the right behavior.
        assert _RE_FUNC.match(".. function:: renpy.foo") is None

    def test_class_with_params(self):
        m = _RE_CLASS.match(".. class:: Dissolve(time, alpha=False)")
        assert m is not None
        assert m.group(1) == "Dissolve"
        assert m.group(2) == "time, alpha=False"

    def test_class_without_params(self):
        m = _RE_CLASS.match(".. class:: Null()")
        assert m is not None
        assert m.group(1) == "Null"
        assert m.group(2) == ""

    def test_class_no_parens(self):
        # Class without parentheses is also valid RST.
        m = _RE_CLASS.match(".. class:: Null")
        assert m is not None
        assert m.group(1) == "Null"

    def test_style_property(self):
        m = _RE_PROP.match(".. style-property:: background")
        assert m is not None
        assert m.group(1) == "background"

    def test_transform_property(self):
        m = _RE_PROP.match(".. transform-property:: xpos")
        assert m is not None
        assert m.group(1) == "xpos"

    def test_property_rejects_other_directives(self):
        assert _RE_PROP.match(".. var:: config.name") is None
        assert _RE_PROP.match(".. function:: foo()") is None


class TestNamespaceOf:
    def test_config(self):
        assert _namespace_of("config.name") == "config"

    def test_gui(self):
        assert _namespace_of("gui.text_color") == "gui"

    def test_build(self):
        assert _namespace_of("build.directory_name") == "build"

    def test_renpy(self):
        assert _namespace_of("renpy.pause") == "renpy"

    def test_unnamespaced(self):
        assert _namespace_of("Dissolve") is None
        assert _namespace_of("background") is None


# =============================================================================
# Section 2: collect_description — RST block walker
# =============================================================================


class TestCollectDescription:
    """Description collection: indented block following an RST directive."""

    def test_simple_description(self):
        lines = [
            ".. var:: config.name",
            "",
            "    A string giving a human-readable name for the game.",
            "",
            ".. var:: config.version",
        ]
        desc = collect_description(lines, 1)
        assert "human-readable name" in desc

    def test_stops_at_next_directive(self):
        lines = [
            ".. var:: config.name",
            "",
            "    First entry description.",
            "",
            ".. var:: config.version",
            "",
            "    Second entry description.",
        ]
        desc = collect_description(lines, 1)
        assert "First entry" in desc
        assert "Second entry" not in desc

    def test_strips_one_indent_level(self):
        lines = [
            ".. var:: config.name",
            "",
            "    Line one.",
            "    Line two.",
        ]
        desc = collect_description(lines, 1)
        assert "Line one." in desc
        assert "Line two." in desc
        # No leading 4-space indent in output.
        assert "    Line" not in desc

    def test_cleans_rst_roles(self):
        lines = [
            ".. function:: renpy.pause(delay=None)",
            "",
            "    Pauses for :func:`delay` seconds. See :ref:`pausing`.",
        ]
        desc = collect_description(lines, 1)
        assert "`delay`" in desc
        assert "`pausing`" in desc
        assert ":func:" not in desc
        assert ":ref:" not in desc

    def test_converts_rst_literals(self):
        lines = [
            ".. var:: foo",
            "",
            "    Use ``renpy.pause()`` to pause.",
        ]
        desc = collect_description(lines, 1)
        assert "`renpy.pause()`" in desc
        assert "``" not in desc

    def test_empty_description_returns_empty(self):
        lines = [
            ".. var:: foo",
            ".. var:: bar",
        ]
        desc = collect_description(lines, 1)
        assert desc == ""

    def test_handles_tabs(self):
        lines = [
            ".. var:: foo",
            "",
            "\tTabbed description.",
        ]
        desc = collect_description(lines, 1)
        assert "Tabbed description." in desc


# =============================================================================
# Section 3: parse_rst_file — full RST parsing pipeline
# =============================================================================


class TestParseRstFile:
    """End-to-end RST parsing on synthetic input."""

    def test_var_directive(self):
        rst = """.. var:: config.name = "My Game"

    A string giving a human-readable name for the game.
"""
        entries = parse_rst_file(rst, "config.rst")
        assert len(entries) == 1
        e = entries[0]
        assert e["name"] == "config.name"
        assert "My Game" in e["signature"]
        assert "human-readable name" in e["description"]
        assert e["category"] == "variable"
        assert e["namespace"] == "config"

    def test_function_directive(self):
        rst = """.. function:: renpy.pause(delay=None, hard=False)

    Pauses script execution for ``delay`` seconds.
"""
        entries = parse_rst_file(rst, "other.rst")
        assert len(entries) == 1
        e = entries[0]
        assert e["name"] == "renpy.pause"
        assert e["signature"] == "renpy.pause(delay=None, hard=False)"
        assert e["category"] == "function"
        assert e["namespace"] == "renpy"

    def test_class_directive_in_transitions_file(self):
        rst = """.. class:: Dissolve(time, alpha=False)

    Returns a transition that dissolves from old to new.
"""
        entries = parse_rst_file(rst, "transitions.rst")
        assert len(entries) == 1
        e = entries[0]
        assert e["name"] == "Dissolve"
        assert e["category"] == "transition"  # filename-based inference

    def test_class_directive_in_screen_actions_file(self):
        rst = """.. class:: Jump(label)

    Jump to ``label`` when the button is activated.
"""
        entries = parse_rst_file(rst, "screen_actions.rst")
        assert len(entries) == 1
        e = entries[0]
        assert e["name"] == "Jump"
        assert e["category"] == "action"  # filename-based inference

    def test_style_property_directive(self):
        rst = """.. style-property:: background

    The background of the displayable.
"""
        entries = parse_rst_file(rst, "style_properties.rst")
        assert len(entries) == 1
        e = entries[0]
        assert e["name"] == "background"
        assert e["category"] == "property"

    def test_transform_property_directive(self):
        rst = """.. transform-property:: xpos

    The horizontal position of the displayable.
"""
        entries = parse_rst_file(rst, "transform_properties.rst")
        assert len(entries) == 1
        e = entries[0]
        assert e["name"] == "xpos"
        assert e["category"] == "property"

    def test_definition_list_var(self):
        # The second pass picks up :var:`ns.name` items.
        rst = """:var:`gui.text_color`

    The color of dialogue text.
"""
        entries = parse_rst_file(rst, "gui.rst")
        # Filter to just the gui.text_color entry.
        matches = [e for e in entries if e["name"] == "gui.text_color"]
        assert len(matches) == 1
        e = matches[0]
        assert e["category"] == "variable"
        assert e["namespace"] == "gui"

    def test_definition_list_skips_if_already_seen(self):
        # If a .. var:: directive already extracted the entry, the
        # :var:`...` definition-list pass should skip it.
        rst = """.. var:: config.name

    First definition.

:var:`config.name`

    Should not produce a duplicate.
"""
        entries = parse_rst_file(rst, "config.rst")
        matches = [e for e in entries if e["name"] == "config.name"]
        assert len(matches) == 1

    def test_multiple_entries_in_one_file(self):
        rst = """.. var:: config.name

    Name of the game.

.. var:: config.version

    Version string.

.. function:: renpy.pause(delay=None)

    Pause execution.
"""
        entries = parse_rst_file(rst, "config.rst")
        names = [e["name"] for e in entries]
        assert "config.name" in names
        assert "config.version" in names
        assert "renpy.pause" in names
        assert len(entries) == 3


# =============================================================================
# Section 4: Python source (.rpy) parsing for action classes
# =============================================================================


class TestParseRpyFile:
    """Action/class extraction from Ren'Py .rpy source files."""

    def test_class_with_docstring_and_init(self):
        # Docstring goes FIRST in the class body (Python convention).
        rpy = '''class Jump(Action):
    """Causes the game to jump to ``label`` when the button is activated."""
    def __init__(self, label):
        self.label = label
'''
        entries = parse_rpy_file(rpy, "00action_control.rpy")
        # The class has an Action parent → category=action.
        assert any(e["name"] == "Jump" and e["category"] == "action" for e in entries)

    def test_class_with_args_directive(self):
        rpy = '''class FileSave(Action):
    """Saves the game.

    :args: (name, page=None, slot=False)
    """
    def __init__(self, name, page=None, slot=False):
        self.name = name
'''
        entries = parse_rpy_file(rpy, "00action_file.rpy")
        assert len(entries) == 1
        e = entries[0]
        assert e["name"] == "FileSave"
        assert e["signature"] == "FileSave(name, page=None, slot=False)"
        assert "Saves the game" in e["description"]

    def test_class_without_docstring_skipped(self):
        rpy = '''class InternalHelper:
    def __init__(self):
        pass
'''
        entries = parse_rpy_file(rpy, "00action_other.rpy")
        # No triple-quoted docstring → not extracted.
        assert all(e["name"] != "InternalHelper" for e in entries)

    def test_class_with_transition_name(self):
        rpy = '''class Dissolve:
    """Dissolves from old to new."""
'''
        entries = parse_rpy_file(rpy, "00definitions.rpy")
        assert any(e["name"] == "Dissolve" and e["category"] == "transition" for e in entries)

    def test_single_line_docstring(self):
        rpy = '''class NullAction:
    """Does nothing."""
'''
        entries = parse_rpy_file(rpy, "00action_other.rpy")
        assert len(entries) == 1
        assert entries[0]["description"] == "Does nothing."


class TestCollectPythonDocstring:
    def test_single_line(self):
        lines = ['    """Does nothing."""']
        assert _collect_python_docstring(lines, 0) == "Does nothing."

    def test_multi_line(self):
        lines = [
            '    """First line.',
            "",
            "    Second paragraph.",
            '    """',
        ]
        result = _collect_python_docstring(lines, 0)
        assert "First line." in result
        assert "Second paragraph." in result

    def test_no_docstring(self):
        lines = ["    pass"]
        assert _collect_python_docstring(lines, 0) == ""


class TestExtractSignatureFromInit:
    def test_finds_init(self):
        lines = [
            "class Foo:",
            "    def __init__(self, x, y=1):",
            "        pass",
        ]
        sig = _extract_signature_from_init(lines, 0, "Foo")
        assert sig == "Foo(x, y=1)"

    def test_no_init_returns_default(self):
        lines = [
            "class Foo:",
            "    pass",
        ]
        assert _extract_signature_from_init(lines, 0, "Foo") == "Foo()"

    def test_stops_at_next_class(self):
        lines = [
            "class Foo:",
            "class Bar:",
            "    def __init__(self, x):",
            "        pass",
        ]
        # __init__ belongs to Bar, but we're looking inside Foo — so we
        # should NOT pick it up.
        assert _extract_signature_from_init(lines, 0, "Foo") == "Foo()"


# =============================================================================
# Section 5: serialize_python_module — output writer
# =============================================================================


class TestSerializePythonModule:
    def test_renders_valid_python(self):
        entries = [
            {
                "name": "config.name",
                "signature": 'config.name = "My Game"',
                "description": "Name of the game.",
                "category": "variable",
                "namespace": "config",
            },
            {
                "name": "renpy.pause",
                "signature": "renpy.pause(delay=None)",
                "description": "Pause execution.",
                "category": "function",
                "namespace": "renpy",
            },
        ]
        out = serialize_python_module("8.5.3", "2026-11-01T00:00:00Z", entries)
        # Must be valid Python.
        ns = {}
        exec(out, ns)
        assert "RENPY_API_DOCS_GENERATED" in ns
        assert ns["RENPY_DOC_VERSION_GENERATED"] == "8.5.3"
        assert ns["RENPY_DOC_GENERATED_AT"] == "2026-11-01T00:00:00Z"

        gen = ns["RENPY_API_DOCS_GENERATED"]
        assert "config.name" in gen
        assert gen["config.name"]["signature"] == 'config.name = "My Game"'
        assert gen["config.name"]["category"] == "variable"
        assert gen["config.name"]["namespace"] == "config"

    def test_deduplicates_by_name(self):
        entries = [
            {"name": "dup", "signature": "first", "description": "first", "category": "variable"},
            {"name": "dup", "signature": "second", "description": "second", "category": "variable"},
        ]
        out = serialize_python_module("8.5.3", "2026-11-01T00:00:00Z", entries)
        ns = {}
        exec(out, ns)
        gen = ns["RENPY_API_DOCS_GENERATED"]
        # First occurrence wins (matches TS behavior).
        assert len(gen) == 1
        assert gen["dup"]["signature"] == "first"

    def test_sorts_entries_by_name(self):
        entries = [
            {"name": "zeta", "signature": "z", "description": "z", "category": "variable"},
            {"name": "alpha", "signature": "a", "description": "a", "category": "variable"},
        ]
        out = serialize_python_module("8.5.3", "2026-11-01T00:00:00Z", entries)
        # alpha should appear before zeta in the source.
        # repr() of a str uses single quotes by default for short ASCII names.
        assert out.index("'alpha'") < out.index("'zeta'")

    def test_synthesizes_url_for_config(self):
        entries = [
            {
                "name": "config.name",
                "signature": "config.name",
                "description": "x",
                "category": "variable",
                "namespace": "config",
            }
        ]
        out = serialize_python_module("8.5.3", "2026-11-01T00:00:00Z", entries)
        assert "https://www.renpy.org/doc/html/config.html#var-config-name" in out


# =============================================================================
# Section 6: Generated module sanity
# =============================================================================


class TestGeneratedModule:
    """Sanity checks on the committed renpy_api_generated.py module."""

    def test_module_loads(self):
        assert isinstance(RENPY_API_DOCS_GENERATED, dict)
        assert len(RENPY_API_DOCS_GENERATED) > 0

    def test_version_is_set(self):
        assert RENPY_DOC_VERSION_GENERATED
        # Must look like a Ren'Py version (digits and dots).
        assert any(c.isdigit() for c in RENPY_DOC_VERSION_GENERATED)

    def test_generated_at_is_iso(self):
        # ISO 8601: YYYY-MM-DDTHH:MM:SSZ
        assert "T" in RENPY_DOC_GENERATED_AT
        assert RENPY_DOC_GENERATED_AT.endswith("Z")

    def test_has_config_namespace(self):
        config_entries = [
            e for e in RENPY_API_DOCS_GENERATED.values()
            if e.get("namespace") == "config"
        ]
        # The config.rst file alone yields ~286 entries.
        assert len(config_entries) > 100, (
            "Expected ~100+ config.* entries in generated data; "
            f"got {len(config_entries)}."
        )

    def test_has_gui_namespace(self):
        gui_entries = [
            e for e in RENPY_API_DOCS_GENERATED.values()
            if e.get("namespace") == "gui"
        ]
        assert len(gui_entries) > 50, (
            "Expected ~50+ gui.* entries in generated data; "
            f"got {len(gui_entries)}."
        )

    def test_has_build_namespace(self):
        build_entries = [
            e for e in RENPY_API_DOCS_GENERATED.values()
            if e.get("namespace") == "build"
        ]
        assert len(build_entries) > 5, (
            "Expected ~5+ build.* entries in generated data; "
            f"got {len(build_entries)}."
        )

    def test_has_style_and_transform_properties(self):
        prop_entries = [
            e for e in RENPY_API_DOCS_GENERATED.values()
            if e.get("category") == "property"
        ]
        assert len(prop_entries) > 50, (
            "Expected ~50+ style/transform property entries; "
            f"got {len(prop_entries)}."
        )

    def test_entries_have_required_fields(self):
        for name, entry in list(RENPY_API_DOCS_GENERATED.items())[:50]:
            assert "signature" in entry, f"{name} missing signature"
            assert "doc" in entry, f"{name} missing doc"
            assert isinstance(entry["signature"], str)
            assert isinstance(entry["doc"], str)


# =============================================================================
# Section 7: Merge logic — curated + generated
# =============================================================================


class TestMergeLogic:
    """RENPY_API_DOCS_ALL = {**generated, **curated}, curated wins."""

    def test_merged_dict_size(self):
        # Merged should be at least as big as the larger of the two.
        assert len(RENPY_API_DOCS_ALL) >= max(len(RENPY_API_DOCS), len(RENPY_API_DOCS_GENERATED))

    def test_curated_entries_preserved(self):
        # A few well-known curated entries should still be there with
        # their richer schema (example, url).
        for name in ("Call", "Jump", "Function", "renpy.pause"):
            assert name in RENPY_API_DOCS_ALL
            assert name in RENPY_API_DOCS  # Specifically curated, not just generated

    def test_curated_wins_on_collision(self):
        # Both curated and generated have "renpy.pause" (and other renpy.*
        # functions). The merged entry should be the curated one.
        # The curated entry has an "example" field; the generated one
        # does not. So if example is present, curated won.
        for name in ("renpy.pause", "renpy.transition"):
            if name in RENPY_API_DOCS and name in RENPY_API_DOCS_GENERATED:
                merged_entry = RENPY_API_DOCS_ALL[name]
                curated_entry = RENPY_API_DOCS[name]
                # Signatures may differ slightly (whitespace, default values);
                # what matters is that the curated schema wins. The curated
                # entry has a 'url' field; check it matches.
                assert merged_entry.get("url") == curated_entry.get("url"), (
                    f"{name}: merged entry does not match curated on 'url' field — "
                    "curated should win on collision."
                )

    def test_generated_only_entries_present(self):
        # config.* is in generated but not curated.
        config_only = [
            name for name in RENPY_API_DOCS_GENERATED
            if name.startswith("config.") and name not in RENPY_API_DOCS
        ]
        assert len(config_only) > 50, "Expected config.* to be generated-only"
        for name in config_only[:5]:
            assert name in RENPY_API_DOCS_ALL


# =============================================================================
# Section 8: End-to-end hover integration
# =============================================================================


class TestHoverIntegration:
    """End-to-end: get_renpy_api_hover resolves both curated and generated entries."""

    def test_curated_entry_hover(self):
        # renpy.pause is in the curated dict.
        hover = get_renpy_api_hover("renpy.pause")
        assert hover is not None
        assert "renpy.pause" in hover
        assert "**Ren'Py Engine API**" in hover

    def test_generated_entry_hover_config(self):
        # config.name is generated-only — this is the win.
        hover = get_renpy_api_hover("config.name")
        assert hover is not None, (
            "config.name should resolve via the generated dict — if this fails, "
            "the merge logic or the generated module is broken."
        )
        assert "config.name" in hover
        assert "**Ren'Py Engine API**" in hover

    def test_generated_entry_hover_gui(self):
        # gui.text_color is generated-only.
        # First find any gui.* entry that's actually in the generated dict.
        gui_entries = [
            n for n in RENPY_API_DOCS_GENERATED if n.startswith("gui.")
        ]
        assert gui_entries, "No gui.* entries in generated dict"
        sample = gui_entries[0]
        hover = get_renpy_api_hover(sample)
        assert hover is not None
        assert sample in hover

    def test_unknown_symbol_returns_none(self):
        assert get_renpy_api_hover("definitely_not_a_real_renpy_symbol") is None

    def test_hover_includes_url_when_present(self):
        # Both curated and generated entries have URLs.
        hover = get_renpy_api_hover("renpy.pause")
        assert hover is not None
        assert "renpy.org" in hover

    def test_hover_for_property_category(self):
        # A style or transform property — these are generated-only.
        prop_entries = [
            n for n, e in RENPY_API_DOCS_GENERATED.items()
            if e.get("category") == "property"
        ]
        assert prop_entries, "No property entries in generated dict"
        sample = prop_entries[0]
        hover = get_renpy_api_hover(sample)
        assert hover is not None
        assert sample in hover


# =============================================================================
# Section 9: Backward compatibility
# =============================================================================


class TestBackwardCompat:
    """ must not break callers of the existing API."""

    def test_renpy_api_docs_dict_still_importable(self):
        # Existing code imports RENPY_API_DOCS directly.
        from senpy.domain.renpy_api import RENPY_API_DOCS
        assert isinstance(RENPY_API_DOCS, dict)
        assert len(RENPY_API_DOCS) > 100

    def test_get_renpy_api_hover_signature_unchanged(self):
        # The function still takes a single str and returns str | None.
        result = get_renpy_api_hover("Call")
        assert isinstance(result, str)
        assert get_renpy_api_hover("nonexistent_xyz") is None

    def test_imports_test_still_passes(self):
        # The test_imports.py test asserts RENPY_API_DOCS has > 100 entries.
        # After , RENPY_API_DOCS itself is unchanged (curated only);
        # the merge is in RENPY_API_DOCS_ALL. So this test should still pass.
        assert len(RENPY_API_DOCS) > 100
