"""Tests for the formerly-dead CLI flags.

Four flags were declared in ``args.py`` but never wired to their
consumers:

  - ``--cache-dir DIR``  — ``CacheManager`` hardcoded ``.senpy_cache``.
  - ``--config FILE``    — ``load_config(args.path)`` ignored ``args.config``.
  - ``--statistics``     — summary table always printed (flag was a no-op).
  - ``--respect-gitignore`` — file discovery used ``IGNORED_DIRS``, not
    ``.gitignore``.

fix:
  - ``--cache-dir`` and ``--config`` are now wired through to their
    consumers (CacheManager and load_config respectively).
  - ``--statistics`` and ``--respect-gitignore`` are removed (they were
    no-ops; removing them makes the CLI contract honest).

This module guards both halves of the fix:
  - ``TestCacheDirWired`` — ``--cache-dir`` actually changes the cache
    location on disk.
  - ``TestConfigFileWired`` — ``--config`` actually loads the named file
    (and ``SENPY_CONFIG`` env var works too).
  - ``TestStatisticsAndRespectGitignoreRemoved`` — argparse rejects the
    removed flags with exit 2.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from senpy.cli.main import parse_args

# =============================================================================
# --cache-dir wired to CacheManager
# =============================================================================


class TestCacheDirWired:
    """``--cache-dir DIR`` must actually change where the cache is written."""

    def test_cache_dir_flag_parsed(self):
        """``--cache-dir`` sets ``args.cache_dir`` to the given path."""
        args = parse_args(["--cache-dir", "/tmp/custom_cache", "."])
        assert args.cache_dir == "/tmp/custom_cache", (
            "--cache-dir must be parsed into args.cache_dir. "
            "Running `senpy --cache-dir /tmp/x .` should set args.cache_dir='/tmp/x'."
        )

    def test_cache_dir_default_none(self):
        """Without ``--cache-dir``, ``args.cache_dir is None``."""
        args = parse_args([])
        assert (
            args.cache_dir is None
        ), "args.cache_dir must default to None when --cache-dir is not passed."

    def test_cache_dir_creates_cache_at_custom_location(self, tmp_path: Path):
        """``SenpyAnalyzer(cache_dir=...)`` must write the cache to the custom dir.

        Integration test: create a project, run the analyzer with a custom
        cache_dir, verify the cache manifest appears at that location (NOT
        at the default ``<project>/.senpy_cache``).
        """
        from senpy.core.analyzer import SenpyAnalyzer

        game = tmp_path / "game"
        game.mkdir()
        (game / "script.rpy").write_text(
            'label start:\n    "Hello"\n    return\n', encoding="utf-8"
        )
        custom_cache = tmp_path / "custom_cache"

        analyzer = SenpyAnalyzer(str(tmp_path), no_cache=False, cache_dir=str(custom_cache))
        analyzer.run(quiet=True)

        # The cache manifest must appear at the custom location.
        assert custom_cache.exists(), (
            f"Custom cache dir {custom_cache} was not created — "
            f"SenpyAnalyzer(cache_dir=...) must write the cache there."
        )
        assert (custom_cache / "cache.pkl").exists(), (
            f"cache.pkl not found in custom cache dir {custom_cache}. "
            f"save_manifest() must write to the custom location."
        )
        # The default .senpy_cache must NOT be created.
        assert not (tmp_path / ".senpy_cache").exists(), (
            "Default .senpy_cache was created even though --cache-dir pointed "
            "elsewhere. CacheManager must use the custom dir exclusively."
        )


# =============================================================================
# --config wired to load_config
# =============================================================================


class TestConfigFileWired:
    """``--config FILE`` must actually load the named config file."""

    def test_config_flag_parsed(self):
        """``--config FILE`` sets ``args.config`` to the given path."""
        args = parse_args(["--config", "/tmp/my_senpy.toml", "."])
        assert args.config == "/tmp/my_senpy.toml", (
            "--config must be parsed into args.config. "
            "Running `senpy --config /tmp/x.toml .` should set args.config='/tmp/x.toml'."
        )

    def test_config_default_none(self):
        """Without ``--config``, ``args.config is None``."""
        args = parse_args([])
        assert args.config is None, "args.config must default to None when --config is not passed."

    def test_config_file_loaded_when_passed(self, tmp_path: Path, monkeypatch):
        """``--config FILE`` must cause load_config to read FILE, not the default.

        Creates a custom senpy.toml with ``strict = true``, points ``--config``
        at it, runs the analyzer, and verifies ``analyzer.strict is True``
        (proving the custom config was loaded, not the default).
        """
        from senpy.core.analyzer import SenpyAnalyzer

        game = tmp_path / "game"
        game.mkdir()
        (game / "script.rpy").write_text(
            'label start:\n    "Hello"\n    return\n', encoding="utf-8"
        )
        # Custom config with strict=true (default is false).
        custom_config = tmp_path / "custom_senpy.toml"
        custom_config.write_text("[senpy]\nstrict = true\n", encoding="utf-8")
        # Default config (would set strict=false if loaded by mistake).
        (tmp_path / "senpy.toml").write_text("[senpy]\nstrict = false\n", encoding="utf-8")

        # No SENPY_CONFIG env var — must come from the constructor.
        monkeypatch.delenv("SENPY_CONFIG", raising=False)

        analyzer = SenpyAnalyzer(str(tmp_path), config_path=str(custom_config))
        analyzer.run(quiet=True)

        assert analyzer.strict is True, (
            f"--config {custom_config} was not honored: analyzer.strict is "
            f"{analyzer.strict}, expected True. load_config must read the "
            f"custom config file when config_path is passed."
        )

    def test_config_from_env_var(self, tmp_path: Path, monkeypatch):
        """``SENPY_CONFIG`` env var must work as an alternative to ``--config``.

        Sets the env var, runs the analyzer (without explicit config_path),
        verifies the custom config is loaded.
        """
        from senpy.core.analyzer import SenpyAnalyzer

        game = tmp_path / "game"
        game.mkdir()
        (game / "script.rpy").write_text(
            'label start:\n    "Hello"\n    return\n', encoding="utf-8"
        )
        custom_config = tmp_path / "custom_senpy.toml"
        custom_config.write_text("[senpy]\nstrict = true\n", encoding="utf-8")
        (tmp_path / "senpy.toml").write_text("[senpy]\nstrict = false\n", encoding="utf-8")

        monkeypatch.setenv("SENPY_CONFIG", str(custom_config))

        analyzer = SenpyAnalyzer(str(tmp_path))
        analyzer.run(quiet=True)

        assert analyzer.strict is True, (
            f"SENPY_CONFIG env var was not honored: analyzer.strict is "
            f"{analyzer.strict}, expected True. load_config must check "
            f"SENPY_CONFIG when no explicit config_path is passed."
        )


# =============================================================================
# --statistics and --respect-gitignore removed
# =============================================================================


class TestStatisticsAndRespectGitignoreRemoved:
    """The removed flags must be rejected by argparse with exit 2."""

    def test_statistics_flag_rejected(self):
        """``--statistics`` must no longer be accepted (it was a no-op).

        argparse raises SystemExit(2) on unrecognized arguments. We
        catch it and assert the exit code. The flag was a no-op (summary
        table always printed in render_text) — removing it makes the
        CLI contract honest.
        """
        with pytest.raises(SystemExit) as exc_info:
            parse_args(["--statistics", "."])
        assert exc_info.value.code == 2, (
            "--statistics should be rejected with exit 2 (argparse convention "
            "for unrecognized arguments). Got exit code "
            f"{exc_info.value.code}."
        )

    def test_respect_gitignore_flag_rejected(self):
        """``--respect-gitignore`` must no longer be accepted (it was a no-op).

        File discovery uses IGNORED_DIRS (hardcoded set in constants.py),
        not .gitignore parsing. The flag was a no-op — removing it makes
        the CLI contract honest.
        """
        with pytest.raises(SystemExit) as exc_info:
            parse_args(["--respect-gitignore", "."])
        assert exc_info.value.code == 2, (
            "--respect-gitignore should be rejected with exit 2 (argparse "
            "convention for unrecognized arguments). Got exit code "
            f"{exc_info.value.code}."
        )

    def test_no_statistics_attr_after_parse(self):
        """``args.statistics`` must not exist after parse_args.

        Guards against accidentally leaving the attribute on Namespace
        (e.g. via a deprecated alias). The flag is gone, the attribute
        must be gone too.
        """
        args = parse_args(["."])
        assert not hasattr(args, "statistics"), (
            "args.statistics must not exist — the --statistics flag was "
            "removed. If a deprecated alias is needed, document it; "
            "otherwise the attribute must be absent."
        )

    def test_no_respect_gitignore_attr_after_parse(self):
        """``args.respect_gitignore`` must not exist after parse_args."""
        args = parse_args(["."])
        assert not hasattr(args, "respect_gitignore"), (
            "args.respect_gitignore must not exist — the --respect-gitignore " "flag was removed."
        )
