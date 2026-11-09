"""Characterization test for production logging initialization.

The ``setup_logging()`` function in ``senpy.core.logging`` is the public
entry point that installs a ``NullHandler`` on the ``"senpy"`` logger.
Without it, Python's ``lastResort`` handler (a ``_StderrHandler`` at
WARNING level) emits log records directly to stderr — which in LSP
mode is the JSON-RPC transport channel, breaking the protocol.

Contract this test guards
-------------------------
Production entry points MUST initialize the Senpy logger so that
``logging.getLogger("senpy").handlers`` is non-empty (at minimum a
``NullHandler``). This prevents ``lastResort`` from firing on
WARNING+ log records emitted before the entry point returns.

Historical bug
---------------------
``setup_logging()`` was implemented and documented (see docstring at
``senpy/core/logging.py:21-22``) but never called from production
code — only self-referenced. In LSP mode, any ``logger.warning()``
from plugin loading, config parsing, or analysis would write to
stderr and corrupt the LSP transport.

The fix wires ``setup_logging(verbose=False)`` into:
  - ``cli.runner.main()`` — at the very top, before ``autoload_plugins()``
    (which itself logs WARNINGs about broken/skipped plugins).
  - ``lsp.server.start_lsp()`` — defense-in-depth, in case the LSP
    server is started directly without going through ``main()``.
"""

from __future__ import annotations

import logging

import pytest

from senpy.core.logging import LOGGER_NAME


def _senpy_handlers() -> list[logging.Handler]:
    """Return the current handlers on the 'senpy' logger.

    Helper so tests don't repeat the ``logging.getLogger`` dance.
    """
    return logging.getLogger(LOGGER_NAME).handlers


def _reset_senpy_logger() -> None:
    """Strip all handlers from the 'senpy' logger.

    Used to simulate the pre-``setup_logging`` state: no handlers,
    so ``lastResort`` would fire on WARNING+ records. This is the
    exact state production code must NOT be in after ``main()`` /
    ``start_lsp()`` returns.
    """
    senpy_logger = logging.getLogger(LOGGER_NAME)
    for h in list(senpy_logger.handlers):
        senpy_logger.removeHandler(h)
        try:
            h.close()
        except Exception:  # noqa: BLE001 — cleanup must not fail the test
            pass


class TestProductionLoggingInit:
    """Verify production entry points initialize the Senpy logger."""

    def test_main_initializes_senpy_logger(self, tmp_path, monkeypatch):
        """``cli.runner.main()`` must call setup_logging before returning.

        Simulates the pre-fix state (no handlers) and verifies that
        after ``main()`` runs (even on a trivial --version invocation),
        the 'senpy' logger has at least one handler — so ``lastResort``
        will not fire on WARNING+ records.
        """
        # Start from a clean slate: no handlers on 'senpy' logger.
        _reset_senpy_logger()
        assert _senpy_handlers() == [], "precondition: senpy logger has no handlers"

        # Invoke main() with --version: cheapest path through main()
        # that still exercises the setup_logging call site (it's at the
        # very top of main(), before autoload_plugins and early exits).
        from senpy.cli.runner import main

        monkeypatch.setattr("sys.argv", ["senpy", "--version"])
        try:
            main()
        except SystemExit:
            pass  # --version calls sys.exit(0)

        # The 'senpy' logger MUST have at least one handler now.
        # Without setup_logging, it would still be empty and WARNING+
        # records would hit lastResort (stderr).
        handlers = _senpy_handlers()
        assert handlers, (
            "main() returned without initializing the 'senpy' logger. "
            "WARNING+ log records will hit Python's lastResort handler "
            "(stderr), which in LSP mode corrupts the JSON-RPC transport. "
            "Call setup_logging(verbose=False) at the top of main()."
        )

    def test_start_lsp_initializes_senpy_logger(self, monkeypatch):
        """``lsp.server.start_lsp()`` must ensure logging is initialized.

        Defense-in-depth: ``start_lsp`` may be called directly without
        going through ``main()`` (e.g. by an embedded host). It must
        not rely on a prior ``setup_logging`` call.
        """
        _reset_senpy_logger()
        assert _senpy_handlers() == [], "precondition: senpy logger has no handlers"

        # start_lsp() blocks on server.start_io() — we stub it out so
        # the function returns immediately after the setup_logging call.
        from senpy.lsp import server as server_mod

        captured = {}

        def fake_start_io():
            # Capture handler state INSIDE start_lsp, after setup_logging
            # should have run but before any LSP I/O.
            captured["handlers"] = list(_senpy_handlers())
            # Return immediately — don't actually run the LSP loop.

        monkeypatch.setattr(server_mod.server, "start_io", fake_start_io)

        from senpy.lsp.server import start_lsp

        start_lsp()

        handlers = captured.get("handlers", [])
        assert handlers, (
            "start_lsp() invoked server.start_io() without initializing the "
            "'senpy' logger. WARNING+ log records during LSP session will hit "
            "lastResort (stderr) and corrupt the JSON-RPC transport. "
            "Call setup_logging(verbose=False) at the top of start_lsp()."
        )

    def test_setup_logging_idempotent_across_main_and_lsp(self, tmp_path, monkeypatch):
        """Calling main() then start_lsp() must not duplicate handlers.

        setup_logging is idempotent (clears old handlers before adding
        new ones), so the second call (from start_lsp) replaces rather
        than appends. This test guards against accidental removal of
        the idempotency clear in setup_logging.
        """
        _reset_senpy_logger()

        from senpy.cli.runner import main

        monkeypatch.setattr("sys.argv", ["senpy", "--version"])
        try:
            main()
        except SystemExit:
            pass
        handlers_after_main = _senpy_handlers()
        assert handlers_after_main, "main() did not initialize logging"

        # Now simulate start_lsp being called (e.g. main() then --lsp
        # path, or an embedded host calling start_lsp after main).
        from senpy.lsp import server as server_mod

        monkeypatch.setattr(server_mod.server, "start_io", lambda: None)
        from senpy.lsp.server import start_lsp

        start_lsp()
        handlers_after_lsp = _senpy_handlers()

        # Idempotent: handler count should not grow unboundedly.
        # NullHandler (always) + possibly StreamHandler (verbose) — but
        # verbose=False in both call sites, so just NullHandler.
        assert len(handlers_after_lsp) <= len(handlers_after_main), (
            f"start_lsp() duplicated handlers: {len(handlers_after_main)} → "
            f"{len(handlers_after_lsp)}. setup_logging must be idempotent."
        )

    def test_senpy_logger_does_not_use_lastresort_after_main(self, tmp_path, monkeypatch):
        """No WARNING record should leak to stderr after main() initializes logging.

        This is the actual LSP-transport-corruption scenario: without
        setup_logging, a logger.warning() call goes through lastResort
        (a stderr handler) and writes the formatted message to stderr.
        After the fix, NullHandler swallows it silently.

        Implementation note: we capture the 'senpy' logger's effective
        handler state directly (not stderr) because pytest's capsys
        captures sys.stderr at a level that interferes with Python's
        lastResort handler semantics. The real contract is: after
        main(), the 'senpy' logger must have a handler that is NOT
        the lastResort handler — i.e. setup_logging must have run.
        """
        _reset_senpy_logger()

        from senpy.cli.runner import main

        monkeypatch.setattr("sys.argv", ["senpy", "--version"])
        try:
            main()
        except SystemExit:
            pass

        # The 'senpy' logger must have at least one handler that is NOT
        # the lastResort handler. lastResort only fires when NO handler
        # is found on the logger or any parent — so the presence of any
        # explicit handler (NullHandler counts) suppresses lastResort.
        handlers = _senpy_handlers()
        assert handlers, (
            "After main(), 'senpy' logger has no handlers. WARNING records "
            "will hit Python's lastResort handler (stderr) and corrupt the "
            "LSP JSON-RPC transport. setup_logging must be called in main()."
        )
        # Verify the handler is a real installed handler (NullHandler
        # or StreamHandler/FileHandler), not the lastResort pseudo-handler.
        for h in handlers:
            assert h is not logging.lastResort, (
                "The only handler on the 'senpy' logger is Python's lastResort. "
                "This means setup_logging did not run — lastResort will write "
                "WARNING+ records to stderr and corrupt LSP transport."
            )

    def test_setup_logging_called_before_autoload_plugins(self, tmp_path, monkeypatch):
        """setup_logging must run BEFORE autoload_plugins.

        autoload_plugins() emits WARNING records for broken/skipped
        plugins. If setup_logging runs AFTER autoload, those warnings
        hit lastResort (stderr) before the NullHandler is installed —
        defeating the fix for LSP mode.

        This test verifies ordering by patching autoload_plugins to
        capture the handler state at the moment it runs.
        """
        _reset_senpy_logger()

        captured = {}

        # Patch autoload_plugins to capture handler state at call time.
        # We import the module path used by main() so the patch lands
        # in the right namespace.
        import senpy.cli.runner as runner_mod
        import senpy.plugins.autoload as autoload_mod

        original_autoload = autoload_mod.autoload_plugins

        def spy_autoload():
            captured["handlers_at_autoload"] = list(_senpy_handlers())
            # Don't actually run autoload — it's slow and irrelevant here.
            # The spy's only job is to capture handler state at call time.

        monkeypatch.setattr("senpy.plugins.autoload.autoload_plugins", spy_autoload)
        # runner.main() does `from senpy.plugins.autoload import autoload_plugins`
        # at call time — so the patch on the module attr lands correctly.

        monkeypatch.setattr("sys.argv", ["senpy", "--version"])
        try:
            runner_mod.main()
        except SystemExit:
            pass

        handlers_at_autoload = captured.get("handlers_at_autoload")
        assert handlers_at_autoload is not None, (
            "autoload_plugins was not called from main() — test setup is wrong "
            "or main() exited early before reaching autoload."
        )
        assert handlers_at_autoload, (
            "autoload_plugins() ran with an empty 'senpy' logger.handlers list. "
            "WARNING records from plugin loading (broken plugins, skipped rules) "
            "hit lastResort (stderr) and corrupt LSP transport. "
            "Move setup_logging() to the very top of main(), BEFORE autoload_plugins()."
        )
        # Restore (monkeypatch handles teardown, but we reference original
        # for clarity — not strictly needed).
        _ = original_autoload


@pytest.fixture(autouse=True)
def _restore_logging_after_test():
    """Ensure each test starts clean and leaves logging in a sane state.

    Tests in this module deliberately strip the 'senpy' logger handlers
    to simulate the pre-fix state. Without this fixture, the stripped
    state would leak into other test modules (e.g. test_logging,
    test_config_logging) that expect setup_logging to have run.
    """
    yield
    # Restore: re-run setup_logging with defaults so the next test (and
    # subsequent test modules) see a properly initialized logger.
    from senpy.core.logging import setup_logging

    setup_logging()
