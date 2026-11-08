"""Plugin autoloader — load all installed trusted plugins once per process.

This module bridges the plugin loader pipeline (`loader.py`: discover → load →
register) with Senpy's CLI entry points (`senpy/cli/main.py`, `dispatch_rule`,
`dispatch_inspect`). Before this module existed, the loader was written but
never called from production code — so installed plugins were invisible to
`senpy rule list`, `senpy inspect`, and the main lint CLI.

Design:
    Idempotent. The first call loads plugins; subsequent calls are no-ops.
    This makes it safe to call from multiple entry points (main + dispatch_rule)
    within the same process — and within the same test process, where
    `dispatch_rule([...])` is invoked many times.

    Safe. Catches all exceptions, logs a warning, never raises. A broken
    plugin must not crash the linter — it should be skipped, and the user
    should see a warning pointing at `senpy --trust-plugin`.

    Trust-on-first-use. The default trust callback (`_default_trust_callback`)
    decides: trusted plugins load; untrusted plugins in non-interactive (CI)
    or LSP mode are skipped silently; in interactive CLI the user is prompted.

What this does:
    Registers plugin rules in `_REGISTERED_LINT_RULES`, which makes them
    VISIBLE in `senpy rule list/show` and INSPECT output. Plugin rules
    are also wired into the analyzer's per-file check loop since 0.8.0
    (gated by `enable_plugins` config, default `False`). When enabled,
    `_run_plugin_rules` in `analysis_pipeline.py` instantiates each
    registered Rule and calls its `check(ctx)` method per-file.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from senpy.core.logging import get_logger

_logger = get_logger("plugins.autoload")

# Module-level guard: once plugins are loaded for this process, don't load
# them again. Tests that need a fresh load can call `reset_autoload_state()`.
# Protected by _PLUGINS_LOADED_LOCK — without it, two threads could both
# see _PLUGINS_LOADED=False and both call the loader (race condition).
# LSP doesn't call autoload from worker threads now, but the lock is cheap
# insurance against future changes (P2-9 fix).
_PLUGINS_LOADED: bool = False
_PLUGINS_LOADED_LOCK = threading.Lock()


def autoload_plugins(
    *,
    force: bool = False,
    trust_callback: Callable[[str], bool] | None = None,
) -> None:
    """Discover, trust-check, and register all installed Senpy plugins.

    Idempotent: the first call performs the work; later calls return
    immediately (unless `force=True`). Safe: any exception during
    discovery/loading/registration is caught and logged as a warning —
    a broken plugin never crashes the linter.

    After this returns, successfully loaded plugin rules are visible in
    `senpy.plugins.registry.get_registered_lint_rules()` and therefore
    in `senpy rule list/show` output.

    Args:
        force: If True, re-run the discovery+load pipeline even if it
            was already run earlier in this process. Mainly useful for
            tests that mock `_get_entry_points` and need a fresh load.
            Production code should leave this as False (default).
        trust_callback: Optional callable(name: str) -> bool passed
            through to `load_all_plugins()`. If None (default), uses
            `_default_trust_callback` (trust-on-first-use with TTY
            prompt). Production callers should leave this as None —
            tests can pass `lambda name: True` to bypass trust-check
            when injecting fake plugins.
    """
    global _PLUGINS_LOADED

    # P2-9: Lock protects the check-and-set. Without it, concurrent
    # autoload_plugins() calls race — both see False, both load. The lock
    # is held for the entire load (not just the flag check) to ensure the
    # second caller sees _PLUGINS_LOADED=True after the first completes.
    with _PLUGINS_LOADED_LOCK:
        if _PLUGINS_LOADED and not force:
            return

        try:
            # Import locally so this module has no top-level dependency on
            # loader.py — keeps import cycles impossible and lets tests mock
            # internals without triggering real plugin discovery at import time.
            from senpy.plugins.loader import load_all_plugins, register_loaded_plugins

            loaded = load_all_plugins(trust_callback=trust_callback)
            if loaded:
                register_loaded_plugins(loaded)
                names = ", ".join(ep.name for ep in loaded)
                _logger.info("Loaded %d plugin(s): %s", len(loaded), names)
        except Exception as e:  # noqa: BLE001 — autoload must never crash callers
            _logger.warning("Plugin autoload failed: %s. Continuing without plugins.", e)

        _PLUGINS_LOADED = True


def reset_autoload_state() -> None:
    """Clear the "plugins already loaded" flag.

    For tests only. After calling this, the next `autoload_plugins()` call
    will re-run discovery+load. Also clears the lint rule registry so a
    test that loads fresh fake plugins doesn't see leftovers from a
    previous autoload.

    Production code must NOT call this — it would let the same plugin
    be registered twice on a second `senpy` invocation in the same
    process (rare, but the linter is sometimes embedded).
    """
    global _PLUGINS_LOADED

    from senpy.plugins.registry import clear_registered_lint_rules

    clear_registered_lint_rules()
    _PLUGINS_LOADED = False


def is_autoload_done() -> bool:
    """Return True if `autoload_plugins()` has completed in this process.

    Useful for tests and for entry points that want to skip redundant
    work (e.g. dispatch_rule calling autoload when main() already did it).
    """
    return _PLUGINS_LOADED
