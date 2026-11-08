"""Tests for --show-settings honors --config, --cache-dir covers sandbox.

Two post-0.8.3 follow-up bugs found:

 --show-settings ignores --config FILE
    ``early_exits.py:149`` called ``load_config(project_path)`` without
    passing ``config_path``. The ``--config`` flag was wired into
    ``SenpyAnalyzer.__init__`` (P1-5), but ``--show-settings`` bypasses
    the analyzer entirely — it loads config directly for display. So
    ``senpy /path --config /tmp/my.toml --show-settings`` showed the
    default config, ignoring the custom file.

 --cache-dir does not cover decompiled/rpa_extracted sandbox
    ``discover.py:189-190`` hardcoded
    ``os.path.join(args.path, ".senpy_cache", "decompiled")`` and
    ``"rpa_extracted"``. The ``--cache-dir`` flag was wired into
    ``CacheManager`` (P1-5), but the decompile/RPA sandbox directories
    were not updated — they still go to ``<project>/.senpy_cache/`` even
    when ``--cache-dir /shared/cache`` is passed. This means CI with a
    shared cache still pollutes the project dir with sandbox artifacts.

Both fixes pass the relevant flag through to the code that was bypassing it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from senpy.cli.main import parse_args

# =============================================================================
# N1: --show-settings honors --config FILE
# =============================================================================


class TestShowSettingsHonorsConfig:
    """--show-settings must load the config from --config FILE, not just defaults."""

    def test_show_settings_uses_config_file(self, tmp_path: Path, monkeypatch):
        """--config FILE must affect --show-settings output.

        Creates a custom senpy.toml with ``strict = true``, points
        ``--config`` at it, runs ``--show-settings``, verifies the
        printed output includes ``strict: True`` (proving the custom
        config was loaded, not the default empty/strict=false).
        """
        from senpy.cli._console import console
        from senpy.cli.early_exits import _handle_early_exits

        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        (game / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")
        # Custom config with strict=true (default is false).
        custom_config = tmp_path / "custom_senpy.toml"
        custom_config.write_text("[senpy]\nstrict = true\n", encoding="utf-8")
        # Default config in project (would set strict=false if loaded).
        (tmp_path / "senpy.toml").write_text("[senpy]\nstrict = false\n", encoding="utf-8")

        args = parse_args([str(tmp_path), "--config", str(custom_config), "--show-settings"])

        # Capture console output.
        import io

        from rich.console import Console as RichConsole

        captured = io.StringIO()
        test_console = RichConsole(file=captured, width=200, force_terminal=False)

        # _handle_early_exits calls sys.exit(0) — catch it.
        import sys

        with pytest.raises(SystemExit) as exc_info:
            _handle_early_exits(args, test_console, is_tsundere=False)

        assert exc_info.value.code == 0, "--show-settings must exit 0."
        output = captured.getvalue()
        # The output must reflect strict=true from the custom config.
        assert "strict: True" in output, (
            f"--show-settings must honor --config FILE. Expected 'strict: True' "
            f"in output (from custom config with strict=true), got:\n{output}"
        )

    def test_show_settings_without_config_uses_default(self, tmp_path: Path):
        """--show-settings without --config uses the default search order.

        Sanity test: without --config, the default senpy.toml in the
        project root is loaded. Guards against the fix accidentally
        breaking the default path.
        """
        import io

        from rich.console import Console as RichConsole

        from senpy.cli.early_exits import _handle_early_exits

        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        (game / "script.rpy").write_text("label start:\n    return\n", encoding="utf-8")
        (tmp_path / "senpy.toml").write_text("[senpy]\nstrict = true\n", encoding="utf-8")

        args = parse_args([str(tmp_path), "--show-settings"])

        captured = io.StringIO()
        test_console = RichConsole(file=captured, width=200, force_terminal=False)

        with pytest.raises(SystemExit) as exc_info:
            _handle_early_exits(args, test_console, is_tsundere=False)

        assert exc_info.value.code == 0
        output = captured.getvalue()
        assert "strict: True" in output, (
            f"--show-settings without --config must load default senpy.toml. "
            f"Expected 'strict: True', got:\n{output}"
        )


# =============================================================================
# N2: --cache-dir covers decompiled/rpa_extracted sandbox
# =============================================================================


class TestCacheDirCoversSandbox:
    """--cache-dir must redirect decompiled/ and rpa_extracted/ sandboxes."""

    def test_decompile_sandbox_uses_cache_dir(self, tmp_path: Path):
        """decompiled/ sandbox must be created under --cache-dir, not <project>/.senpy_cache.

        Scenario: create a project with an orphaned .rpyc file, pass
        ``--cache-dir /shared/cache --decompile``, verify the decompiled
        .rpy goes to ``/shared/cache/decompiled/`` NOT
        ``<project>/.senpy_cache/decompiled/``.
        """
        from senpy.cli.discover import discover_files
        from senpy.core.config import load_config

        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        # An orphaned .rpyc (no matching .rpy) — triggers decompile.
        # Write a minimal valid .rpyc header so the decompiler doesn't
        # crash immediately. If decompile fails, the sandbox dir is still
        # created (os.makedirs runs before decompile).
        (game / "orphan.rpyc").write_bytes(b"\x00" * 50)

        custom_cache = tmp_path / "shared_cache"
        args = parse_args([str(tmp_path), "--cache-dir", str(custom_cache), "--decompile"])
        config = load_config(str(tmp_path))

        # Run discover_files — creates sandbox dirs + attempts decompile.
        discover_files(args, config, str(tmp_path), interactive=False)

        # The decompiled sandbox must be under custom_cache, NOT under
        # <project>/.senpy_cache/.
        assert (custom_cache / "decompiled").exists(), (
            f"decompiled/ sandbox must be created under --cache-dir "
            f"({custom_cache}/decompiled), not under <project>/.senpy_cache/. "
            f"Got: {custom_cache / 'decompiled'} (exists={False})"
        )
        assert (custom_cache / "rpa_extracted").exists(), (
            f"rpa_extracted/ sandbox must be created under --cache-dir "
            f"({custom_cache}/rpa_extracted)."
        )
        # The default .senpy_cache must NOT contain decompiled/rpa_extracted.
        default_cache = tmp_path / ".senpy_cache"
        if default_cache.exists():
            assert not (default_cache / "decompiled").exists(), (
                "decompiled/ leaked into default <project>/.senpy_cache/ "
                "even though --cache-dir pointed elsewhere."
            )
            assert not (
                default_cache / "rpa_extracted"
            ).exists(), "rpa_extracted/ leaked into default <project>/.senpy_cache/."

    def test_sandbox_uses_default_without_cache_dir(self, tmp_path: Path):
        """Without --cache-dir, sandboxes go to <project>/.senpy_cache/ (default).

        Sanity test: the default path must still work after the fix.
        """
        from senpy.cli.discover import discover_files
        from senpy.core.config import load_config

        game = tmp_path / "game"
        game.mkdir(parents=True, exist_ok=True)
        (game / "orphan.rpyc").write_bytes(b"\x00" * 50)

        args = parse_args([str(tmp_path), "--decompile"])
        config = load_config(str(tmp_path))

        discover_files(args, config, str(tmp_path), interactive=False)

        default_cache = tmp_path / ".senpy_cache"
        assert (default_cache / "decompiled").exists(), (
            f"Without --cache-dir, decompiled/ must go to default "
            f"<project>/.senpy_cache/decompiled/. Got: {default_cache / 'decompiled'}"
        )
        assert (default_cache / "rpa_extracted").exists(), (
            "Without --cache-dir, rpa_extracted/ must go to default "
            "<project>/.senpy_cache/rpa_extracted/."
        )
