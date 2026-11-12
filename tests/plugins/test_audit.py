"""Tests for plugin import-time audit."""

from __future__ import annotations

import ast

import pytest

from senpy.plugins.audit import (
    AuditResult,
    _DangerousCodeVisitor,
    audit_plugin_source,
    audit_source,
)

# =============================================================================
# audit_source — AST-based source code scanner
# =============================================================================


class TestAuditSource:
    """Test the AST-based dangerous-pattern scanner."""

    def test_clean_code_no_warnings(self):
        """Code with no dangerous patterns produces no warnings."""
        source = "x = 1\ny = x + 2\nprint(y)\n"
        warnings = audit_source(source)
        assert warnings == []

    def test_detects_subprocess_import(self):
        """`import subprocess` is flagged."""
        source = "import subprocess\nsubprocess.run(['ls'])\n"
        warnings = audit_source(source)
        assert any("subprocess" in w for w in warnings)

    def test_detects_subprocess_from_import(self):
        """`from subprocess import run` is flagged."""
        source = "from subprocess import run\nrun(['ls'])\n"
        warnings = audit_source(source)
        assert any("subprocess" in w for w in warnings)

    def test_detects_socket_import(self):
        """`import socket` is flagged."""
        source = "import socket\ns = socket.socket()\n"
        warnings = audit_source(source)
        assert any("socket" in w for w in warnings)

    def test_detects_eval(self):
        """`eval()` is flagged."""
        source = "result = eval('1 + 2')\n"
        warnings = audit_source(source)
        assert any("eval" in w.lower() for w in warnings)

    def test_detects_exec(self):
        """`exec()` is flagged."""
        source = "exec('x = 1')\n"
        warnings = audit_source(source)
        assert any("exec" in w.lower() for w in warnings)

    def test_detects_os_system(self):
        """`os.system()` is flagged."""
        source = "import os\nos.system('rm -rf /')\n"
        warnings = audit_source(source)
        assert any("os.system" in w for w in warnings)

    def test_detects_os_popen(self):
        """`os.popen()` is flagged."""
        source = "import os\nos.popen('whoami')\n"
        warnings = audit_source(source)
        assert any("os.popen" in w for w in warnings)

    def test_detects_ctypes(self):
        """`import ctypes` is flagged."""
        source = "import ctypes\nctypes.CDLL('libc.so.6')\n"
        warnings = audit_source(source)
        assert any("ctypes" in w for w in warnings)

    def test_detects_pickle_load(self):
        """`pickle.load()` is flagged."""
        source = "import pickle\ndata = pickle.load(open('x.pkl', 'rb'))\n"
        warnings = audit_source(source)
        assert any("pickle" in w.lower() for w in warnings)

    def test_detects_pickle_loads(self):
        """`pickle.loads()` is flagged."""
        source = "import pickle\ndata = pickle.loads(b'\\x80\\x04')\n"
        warnings = audit_source(source)
        assert any("pickle" in w.lower() for w in warnings)

    def test_detects_dunder_import(self):
        """`__import__()` is flagged."""
        source = "os = __import__('os')\n"
        warnings = audit_source(source)
        assert any("__import__" in w for w in warnings)

    def test_detects_os_fork(self):
        """`os.fork()` is flagged."""
        source = "import os\npid = os.fork()\n"
        warnings = audit_source(source)
        assert any("fork" in w.lower() for w in warnings)

    def test_does_not_flag_safe_code(self):
        """Common safe patterns should NOT trigger warnings."""
        source = """
import re
import os.path
from pathlib import Path

def my_rule(lines):
    for line in lines:
        m = re.match(r'^\\s*TODO', line)
        if m:
            print("Found TODO")
"""
        warnings = audit_source(source)
        assert warnings == [], f"Safe code should produce no warnings, got: {warnings}"

    def test_dedup_identical_warnings(self):
        """Multiple occurrences of the same pattern produce one warning."""
        source = """
import subprocess
subprocess.run(['ls'])
subprocess.run(['pwd'])
subprocess.call(['echo'])
"""
        warnings = audit_source(source)
        # Should have one "subprocess.run" and one "subprocess.call" warning
        # (deduped — not three of the same)
        assert len(warnings) <= 3
        assert any("subprocess.run" in w for w in warnings)

    def test_syntax_error_produces_warning(self):
        """Code with syntax error produces a parse-error warning."""
        source = "def broken(:\n"
        warnings = audit_source(source, filename="bad.py")
        assert len(warnings) == 1
        assert "syntax error" in warnings[0].lower()
        assert "bad.py" in warnings[0]


# =============================================================================
# audit_plugin_source — multi-file audit
# =============================================================================


class TestAuditPluginSource:
    """Test the multi-file audit wrapper."""

    def test_clean_plugin_no_warnings(self):
        """A plugin with only safe code produces no warnings."""
        result = audit_plugin_source(
            "clean-plugin",
            {"rules.py": "import re\nx = 1\n"},
        )
        assert not result.has_warnings
        assert result.files_scanned == 1
        assert result.error is None

    def test_dangerous_plugin_has_warnings(self):
        """A plugin with subprocess usage produces warnings."""
        result = audit_plugin_source(
            "dangerous-plugin",
            {"rules.py": "import subprocess\nsubprocess.run(['ls'])\n"},
        )
        assert result.has_warnings
        assert any("subprocess" in w for w in result.warnings)
        assert result.files_scanned == 1

    def test_multiple_files_aggregated(self):
        """Warnings from multiple files are aggregated + deduped."""
        result = audit_plugin_source(
            "multi-file-plugin",
            {
                "__init__.py": "import socket\n",
                "rules.py": "import socket\nsocket.socket()\n",
                "helpers.py": "eval('1')\n",
            },
        )
        assert result.files_scanned == 3
        assert result.has_warnings
        # socket warning should be deduped (appears in 2 files)
        socket_warnings = [w for w in result.warnings if "socket" in w]
        assert len(socket_warnings) == 1
        assert any("eval" in w.lower() for w in result.warnings)

    def test_empty_source_files(self):
        """Empty source files produce no warnings."""
        result = audit_plugin_source("empty", {"rules.py": ""})
        assert not result.has_warnings
        assert result.files_scanned == 1


# =============================================================================
# Trust store integration
# =============================================================================


class TestAuditWarningsStorage:
    """Test that audit warnings are stored and retrieved from trust store."""

    def test_store_and_get_audit_warnings(self, monkeypatch, tmp_path):
        """store_audit_warnings → get_audit_warnings round-trip."""
        tmp_path / "trusted_plugins.json"
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))

        from senpy.plugins.security import get_audit_warnings, store_audit_warnings

        store_audit_warnings("test-plugin", ["Uses subprocess", "Uses eval"])
        retrieved = get_audit_warnings("test-plugin")
        assert retrieved == ["Uses subprocess", "Uses eval"]

    def test_get_audit_warnings_empty(self, monkeypatch, tmp_path):
        """get_audit_warnings returns [] for unknown plugin."""
        tmp_path / "trusted_plugins.json"
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))

        from senpy.plugins.security import get_audit_warnings

        assert get_audit_warnings("unknown-plugin") == []

    def test_store_overwrites_previous(self, monkeypatch, tmp_path):
        """Storing new warnings overwrites old ones for the same plugin."""
        tmp_path / "trusted_plugins.json"
        monkeypatch.setenv("SENPY_HOME", str(tmp_path))

        from senpy.plugins.security import get_audit_warnings, store_audit_warnings

        store_audit_warnings("test-plugin", ["old warning"])
        store_audit_warnings("test-plugin", ["new warning"])
        assert get_audit_warnings("test-plugin") == ["new warning"]
