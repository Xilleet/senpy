"""QUA-10: plugin loader должен использовать logging, а не print().

Контракт:
  - Все warning-сообщения из loader.py идут через logger.warning().
  - capsys (stdout/stderr capture) НЕ должен содержать "[senpy.plugins] WARNING"
    в выводе — логи идут через logging, не через print().
  - caplog должен ловить эти же сообщения на уровне WARNING.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from senpy.core.logging import setup_logging
from senpy.plugins import loader as loader_mod


@pytest.fixture(autouse=True)
def reset_logging():
    """Чистая конфигурация логгера перед каждым тестом."""
    setup_logging()  # NullHandler, propagate=True (caplog работает)
    yield


def _make_entry_point(name: str, rule_cls=None, raises: type | None = None):
    """Фабрика mock EntryPoint."""
    ep = MagicMock()
    ep.name = name
    if raises is not None:
        ep.load.side_effect = raises("boom")
    else:
        ep.load.return_value = rule_cls
    return ep


def test_load_plugin_failed_import_logs_warning(capsys, caplog):
    """Если плагин падает при импорте — логируется warning, не print()."""
    from senpy.plugins.base import Rule

    class _GoodRule(Rule):
        pass

    ep = _make_entry_point("bad_plugin", raises=ImportError)

    with caplog.at_level(logging.WARNING, logger="senpy.plugins"):
        result = loader_mod.load_plugin(ep, trust_callback=lambda _: False)

    assert result is None
    # НЕ должно быть print() в stderr
    captured = capsys.readouterr()
    assert "WARNING" not in captured.err
    assert "WARNING" not in captured.out
    # ДОЛЖНО быть в caplog
    assert any(
        "Failed to load plugin" in r.message and "bad_plugin" in r.message
        for r in caplog.records
    ), f"warning not logged: {caplog.records}"


def test_load_plugin_not_rule_subclass_logs_warning(capsys, caplog):
    """Если entry_point указывает не на Rule subclass — логируется warning."""
    ep = _make_entry_point("not_a_rule", rule_cls=str)  # str — не Rule

    with caplog.at_level(logging.WARNING, logger="senpy.plugins"):
        result = loader_mod.load_plugin(ep, trust_callback=lambda _: False)

    assert result is None
    captured = capsys.readouterr()
    assert "WARNING" not in captured.err
    assert any(
        "Rule subclass" in r.message and "not_a_rule" in r.message
        for r in caplog.records
    ), f"warning not logged: {caplog.records}"


def test_trust_plugin_prompt_logs_info(capsys, caplog, monkeypatch):
    """Когда юзер соглашается trust'нуть плагин — логируется info."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "y")

    with caplog.at_level(logging.INFO, logger="senpy.plugins"):
        # untrust before to trigger the prompt path
        from senpy.plugins.security import untrust_plugin
        untrust_plugin("trustme_test")
        result = loader_mod._default_trust_callback("trustme_test")

    assert result is True
    captured = capsys.readouterr()
    # print() должен исчезнуть после миграции
    assert "trust store" not in captured.out
    assert "trust store" not in captured.err


def test_register_loaded_plugins_logs_warning_for_no_meta(capsys, caplog):
    """Плагин без meta логирует warning, не печатает."""
    from senpy.plugins.base import Rule
    from senpy.plugins.loader import _LoadedEntryPoint

    class _NoMetaRule(Rule):
        meta = None

    loaded = [
        _LoadedEntryPoint(
            name="no_meta_plugin",
            rule_cls=_NoMetaRule,
        )
    ]

    with caplog.at_level(logging.WARNING, logger="senpy.plugins"):
        loader_mod.register_loaded_plugins(loaded)

    captured = capsys.readouterr()
    assert "WARNING" not in captured.err
    assert any(
        "no meta" in r.message.lower() and "no_meta_plugin" in r.message
        for r in caplog.records
    ), f"warning not logged: {caplog.records}"
