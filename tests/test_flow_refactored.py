"""TDD тесты для flow.py _parse/_analyze/_merge методов — Phase 4, Step 2 (0.5.7).

RED: эти тесты падают, потому что методы ещё не существуют.
GREEN: после extraction из analyze_menu_flow — тесты проходят.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _make_analyzer():
    """Создаёт mock analyzer для StoryFlowAnalyzer."""
    from unittest.mock import MagicMock
    analyzer = MagicMock()
    analyzer.labels = {}
    analyzer.user_symbols = set()
    analyzer.declared_symbols = set()
    analyzer.jump_sources = {}
    analyzer.screens = {}
    analyzer.screen_action_jumps = {}
    analyzer.used_screens = set()
    analyzer.screen_uses = {}
    analyzer.fixable_count = 0
    analyzer.fixed_count = 0
    analyzer.fix = False
    return analyzer


def _make_flow(analyzer=None):
    from senpy.rules.flow import StoryFlowAnalyzer
    return StoryFlowAnalyzer(analyzer or _make_analyzer())


class TestParseMenuChoices:
    """_parse_menu_choices — парсинг choices из menu-блока."""

    def test_method_exists(self):
        from senpy.rules.flow import StoryFlowAnalyzer
        assert hasattr(StoryFlowAnalyzer, "_parse_menu_choices")

    def test_empty_menu(self):
        """Пустой menu: — нет choices."""
        from senpy.rules.flow import StoryFlowAnalyzer
        flow = _make_flow()
        lines = ["menu:", "    return"]
        idx, choices, _ = flow._parse_menu_choices(lines, 1, 0, "test.rpy", {})
        assert len(choices) == 0

    def test_single_choice(self):
        """Один choice с return."""
        from senpy.rules.flow import FlowBranch
        flow = _make_flow()
        lines = ["menu:", '    "Go left":', "        jump left_path"]
        idx, choices, _ = flow._parse_menu_choices(lines, 1, 0, "test.rpy", {})
        assert len(choices) == 1
        assert choices[0].name == "Go left"
        assert choices[0].terminates is True  # jump = terminating

    def test_two_choices(self):
        """Два choice."""
        flow = _make_flow()
        lines = [
            "menu:",
            '    "Go left":',
            "        jump left_path",
            '    "Go right":',
            "        jump right_path",
        ]
        idx, choices, _ = flow._parse_menu_choices(lines, 1, 0, "test.rpy", {})
        assert len(choices) == 2
        assert choices[0].name == "Go left"
        assert choices[1].name == "Go right"

    def test_choice_with_variable_assignment(self):
        """Choice с $ var = value — defined_vars обновляется."""
        flow = _make_flow()
        lines = ["menu:", '    "Option":', "        $ flag = True"]
        idx, choices, _ = flow._parse_menu_choices(lines, 1, 0, "test.rpy", {})
        assert len(choices) == 1
        assert "flag" in choices[0].defined_vars

    def test_empty_choice_rpy402(self):
        """Choice без statements — RPY402."""
        analyzer = _make_analyzer()
        diagnostics = []
        analyzer._add_diagnostic = lambda diag, noqa: diagnostics.append(diag)
        flow = _make_flow(analyzer)
        lines = ["menu:", '    "Empty":', '    "Has body":', "        return"]
        idx, choices, _ = flow._parse_menu_choices(lines, 1, 0, "test.rpy", {})
        # RPY402 должен сработать для "Empty"
        assert any(d.code == "RPY402" for d in diagnostics)


class TestAnalyzeChoiceBody:
    """_analyze_choice_body — анализ тела choice (вложенные menu, jump, $)."""

    def test_method_exists(self):
        from senpy.rules.flow import StoryFlowAnalyzer
        assert hasattr(StoryFlowAnalyzer, "_analyze_choice_body")


class TestMergeMenuBranches:
    """_merge_menu_branches — слияние веток + RPY401."""

    def test_method_exists(self):
        from senpy.rules.flow import StoryFlowAnalyzer
        assert hasattr(StoryFlowAnalyzer, "_merge_menu_branches")


class TestAnalyzeMenuFlowRefactored:
    """Интеграционный тест: analyze_menu_flow вызывает _parse/_analyze/_merge."""

    def test_menu_with_two_choices(self):
        """analyze_menu_flow обрабатывает menu с двумя choices."""
        flow = _make_flow()
        lines = [
            "menu:",
            '    "Go left":',
            "        jump left_path",
            '    "Go right":',
            "        jump right_path",
        ]
        idx, uninit, guaranteed, terminates = flow.analyze_menu_flow(
            lines, 1, 0, "test.rpy", {}
        )
        assert terminates is True  # обе ветки terminate (jump)

    def test_menu_with_non_terminating_choice(self):
        """Choice без jump/return — terminates=False."""
        flow = _make_flow()
        lines = ["menu:", '    "Option":', "        $ x = 1"]
        idx, uninit, guaranteed, terminates = flow.analyze_menu_flow(
            lines, 1, 0, "test.rpy", {}
        )
        assert terminates is False
        assert "x" in guaranteed


class TestMermaidBuilder:
    """generate_mermaid_graph → MermaidBuilder (Phase 4 Step 3)."""

    def test_mermaid_builder_exists(self):
        """MermaidBuilder класс должен существовать."""
        from senpy.rules.flow import MermaidBuilder
        assert MermaidBuilder is not None

    def test_build_returns_string(self):
        """MermaidBuilder.build() возвращает строку."""
        from senpy.rules.flow import MermaidBuilder
        analyzer = _make_analyzer()
        builder = MermaidBuilder(analyzer)
        result = builder.build()
        assert isinstance(result, str)
        assert "```mermaid" in result
        assert "graph TD" in result

    def test_empty_project(self):
        """Пустой проект — минимальный граф."""
        from senpy.rules.flow import MermaidBuilder
        analyzer = _make_analyzer()
        builder = MermaidBuilder(analyzer)
        result = builder.build()
        assert "No static jumps" in result or "graph TD" in result

    def test_label_with_return(self):
        """Label с return — узел имеет форму ([...])."""
        from senpy.core.symbols import LabelSymbol
        from senpy.rules.flow import MermaidBuilder
        analyzer = _make_analyzer()
        lbl = LabelSymbol(name="start", file_path="test.rpy", line_number=1, code_line="label start:")
        lbl.has_return = True
        analyzer.labels = {"start": lbl}
        builder = MermaidBuilder(analyzer)
        result = builder.build()
        assert "([\"" in result or '(["' in result
