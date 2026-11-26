"""RED tests for small fixes noticed during
reconnaissance of the GitLab cluster.

FIX-53 (python_ast.py): ``_visit_import_from`` lacks ``fix_replacement``
for ``from random import X`` — QuickFix asymmetry with ``_visit_import``
which does offer ``fix_replacement="from renpy import random"`` for
``import random``. The fix adds ``fix_replacement`` for single-name
imports (multiple names are too complex for a single-line replacement).

FIX-65 (commands.py): ``handle_export_html`` duplicates filtering logic
(``ignored_codes``, ``errors_only``, ``info``) but misses ``--select``
and ``--tag`` filters. Result: ``senpy --select RPY104 --export-html
report.html`` produces a report with ALL diagnostics, ignoring the
``--select`` flag. Fix: delegate to ``filter_diagnostics()`` from
``senpy/cli/filters.py``.

FIX-67 (plugins/audit.py): module docstring promises ``open() with
write mode (best-effort — may have false positives)`` check, but no
such check exists in ``_DangerousCodeVisitor``. A plugin doing
``open("/etc/passwd", "w").write(...)`` gets zero warnings despite
the docstring claim. Fix: implement the check — flag ``open(path, mode)``
where ``mode`` is a string literal containing ``"w"``, ``"a"``, or
``"x"`` (write/append/exclusive-create).

Per the project methodology ("если то что заметил - можно починить
сразу - чини, это не scope"), these are fixed in the same patch as
the FIX-57+58 cluster.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console

from senpy.api import analyze_code
from senpy.cli.commands import handle_export_html
from senpy.core.analyzer import SenpyAnalyzer
from senpy.plugins.audit import audit_source

# =============================================================================
# FIX-53: _visit_import_from missing fix_replacement
# =============================================================================


class TestRpy106ImportFromFixReplacement:
    """RPY106 emitted by ``_visit_import_from`` must offer a ``fix_replacement``.

    ``_visit_import`` (for ``import random``) already offers
    ``fix_replacement="from renpy import random"``. The ``from random
    import X`` form should offer an analogous fix so users get a
    one-click QuickFix in their editor regardless of import style.
    """

    def _rpy106_for(self, code: str):
        """Run analyze_code and return the first RPY106 diagnostic (or None)."""
        diags = analyze_code(code)
        for d in diags:
            if d.code == "RPY106":
                return d
        return None

    def test_import_random_has_fix_replacement_baseline(self):
        """Baseline: ``import random`` already has fix_replacement (not regressed)."""
        code = "init python:\n    import random\n\nlabel start:\n    return\n"
        d = self._rpy106_for(code)
        assert d is not None, "RPY106 should fire for 'import random'"
        assert d.fix_replacement == "from renpy import random"
        assert d.fix_title is not None

    def test_from_random_import_randint_has_fix_replacement(self):
        """``from random import randint`` must offer a fix_replacement.

        RED today: ``_visit_import_from`` emits the diagnostic but leaves
        ``fix_replacement=None`` — no QuickFix in the editor.
        """
        code = "init python:\n    from random import randint\n\nlabel start:\n    return\n"
        d = self._rpy106_for(code)
        assert d is not None, "RPY106 should fire for 'from random import randint'"
        assert d.fix_replacement is not None, (
            "RPY106 for 'from random import randint' must offer a fix_replacement — "
            "users get a one-click QuickFix for 'import random' but not for "
            "'from random import X'. Asymmetric QuickFix coverage."
        )
        assert d.fix_title is not None, "fix_title must also be set"

    def test_from_random_import_random_has_fix_replacement(self):
        """``from random import random`` must offer ``from renpy import random``."""
        code = "init python:\n    from random import random\n\nlabel start:\n    return\n"
        d = self._rpy106_for(code)
        assert d is not None
        assert d.fix_replacement == "from renpy import random", (
            f"expected 'from renpy import random' (no 'as' needed when importing "
            f"the 'random' name), got: {d.fix_replacement!r}"
        )

    def test_from_random_import_random_as_rng_preserves_alias(self):
        """``from random import random as rng`` → ``from renpy import random as rng``.

        The local name ``rng`` must be preserved so existing references
        to ``rng`` continue to resolve (semantically ``rng`` was a
        function, now it's the renpy.random module — but at least the
        name binding is preserved).
        """
        code = "init python:\n    from random import random as rng\n\nlabel start:\n    return\n"
        d = self._rpy106_for(code)
        assert d is not None
        assert d.fix_replacement == "from renpy import random as rng", (
            f"expected 'from renpy import random as rng' (preserve alias), "
            f"got: {d.fix_replacement!r}"
        )

    def test_from_random_import_randint_as_ri_preserves_alias(self):
        """``from random import randint as ri`` → ``from renpy import random as ri``."""
        code = "init python:\n    from random import randint as ri\n\nlabel start:\n    return\n"
        d = self._rpy106_for(code)
        assert d is not None
        assert d.fix_replacement == "from renpy import random as ri", (
            f"expected 'from renpy import random as ri' (preserve alias), "
            f"got: {d.fix_replacement!r}"
        )

    def test_from_random_import_multiple_names_no_fix_replacement(self):
        """``from random import randint, choice`` → no fix_replacement.

        Multi-name imports can't be replaced in a single line — the
        user would need to rename call sites for BOTH names. We emit
        the diagnostic but no QuickFix (the user manually migrates).
        """
        code = "init python:\n    from random import randint, choice\n\nlabel start:\n    return\n"
        d = self._rpy106_for(code)
        assert d is not None, "RPY106 should still fire for multi-name imports"
        # No fix_replacement for multi-name imports — too complex for a
        # single-line text replacement.
        assert d.fix_replacement is None, (
            f"multi-name import should NOT offer fix_replacement (too complex), "
            f"got: {d.fix_replacement!r}"
        )


# =============================================================================
# FIX-65: handle_export_html missing --select / --tag filters
# =============================================================================


@pytest.fixture
def setup_project_with_multiple_diagnostics(tmp_path: Path):
    """Build a Ren'Py project that produces both RPY104 and RPY105 diagnostics.

    RPY104: dynamic assignment without top-level 'default' ($ x = 1 in a label).
    RPY105: mutation of a 'define' constant (define CONST = 5; $ CONST = 6).

    Having two distinct rule codes lets us verify that --select RPY104
    filters out RPY105 from the HTML report.
    """
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "script.rpy").write_text(
        "define CONST = 5\n"
        "default y = 0\n"
        "label start:\n"
        "    $ x = 1\n"  # RPY104: dynamic assignment without default
        "    $ CONST = 6\n"  # RPY105: mutation of define constant
        "    return\n",
        encoding="utf-8",
    )
    analyzer = SenpyAnalyzer(str(tmp_path))
    result = analyzer.run(quiet=True)
    return analyzer, result


class TestHandleExportHtmlSelectFilter:
    """``handle_export_html`` must respect ``--select`` and ``--tag`` filters.

    Currently it duplicates filtering logic inline (``ignored_codes``,
    ``errors_only``, ``info``) but does NOT call ``filter_diagnostics()``
    from ``senpy/cli/filters.py`` — so ``--select RPY104`` and
    ``--tag rollback`` are silently ignored in the HTML report.
    """

    def test_select_filter_excludes_other_codes_from_html(
        self, setup_project_with_multiple_diagnostics, tmp_path: Path, monkeypatch
    ):
        """``--select RPY104`` must produce an HTML report containing only
        RPY104 diagnostics — not RPY105.

        Spies on ``generate_html_report`` and inspects the ``diagnostics``
        kwarg. RED today: the inline filter passes ALL diagnostics through
        (it doesn't check ``args.select``).
        """
        analyzer, result = setup_project_with_multiple_diagnostics
        # Sanity: the project actually produces both codes.
        codes = {d.code for d in result.diagnostics}
        assert "RPY104" in codes, f"fixture broken: expected RPY104 in {codes}"
        assert "RPY105" in codes, f"fixture broken: expected RPY105 in {codes}"

        out_html = tmp_path / "report.html"
        args = SimpleNamespace(
            export_html=str(out_html),
            errors_only=False,
            info=True,
            # FIX-65 test: --select RPY104 should filter OUT RPY105.
            select=["RPY104"],
            extend_select=None,
            extend_ignore=None,
            tag=None,
            ignore_tag=None,
        )
        console = Console(legacy_windows=False)

        import senpy.formats.html_report as html_mod

        captured: dict[str, object] = {}
        real_generate = html_mod.generate_html_report

        def spy(**kwargs):
            captured.update(kwargs)
            return real_generate(**kwargs)

        monkeypatch.setattr(html_mod, "generate_html_report", spy)

        handle_export_html(
            args,
            result,
            analyzer,
            console,
            is_tsundere=False,
            ignored_codes=set(),
            elapsed=0.0,
        )

        passed_codes = {d.code for d in captured["diagnostics"]}
        assert passed_codes == {"RPY104"}, (
            f"--select RPY104 should filter OUT RPY105 from HTML report, "
            f"but the HTML received codes: {passed_codes}"
        )

    def test_ignore_filter_excludes_ignored_codes_from_html(
        self, setup_project_with_multiple_diagnostics, tmp_path: Path, monkeypatch
    ):
        """``ignored_codes={'RPY105'}`` must exclude RPY105 from HTML report.

        This already works today (the inline filter checks ``ignored_codes``)
        — the test exists to prevent regression when we switch to
        ``filter_diagnostics()``.
        """
        analyzer, result = setup_project_with_multiple_diagnostics
        out_html = tmp_path / "report.html"
        args = SimpleNamespace(
            export_html=str(out_html),
            errors_only=False,
            info=True,
            select=None,
            extend_select=None,
            extend_ignore=None,
            tag=None,
            ignore_tag=None,
        )
        console = Console(legacy_windows=False)

        import senpy.formats.html_report as html_mod

        captured: dict[str, object] = {}
        real_generate = html_mod.generate_html_report

        def spy(**kwargs):
            captured.update(kwargs)
            return real_generate(**kwargs)

        monkeypatch.setattr(html_mod, "generate_html_report", spy)

        handle_export_html(
            args,
            result,
            analyzer,
            console,
            is_tsundere=False,
            ignored_codes={"RPY105"},
            elapsed=0.0,
        )

        passed_codes = {d.code for d in captured["diagnostics"]}
        assert (
            "RPY105" not in passed_codes
        ), f"RPY105 should be filtered out by ignored_codes, but HTML got: {passed_codes}"
        assert (
            "RPY104" in passed_codes
        ), f"RPY104 should still be present (only RPY105 ignored), got: {passed_codes}"


# =============================================================================
# FIX-67: plugins/audit.py open() write-mode check (docstring lies)
# =============================================================================


class TestAuditOpenWriteModeCheck:
    """``audit_source`` must flag ``open(path, "w")`` (write mode).

    The module docstring promises: ``open() with write mode (best-effort
    — may have false positives)``. The check is missing —
    ``_DangerousCodeVisitor.visit_Call`` only checks ``_DANGEROUS_CALLS``
    (eval/exec/__import__/compile) and attribute calls (os.system,
    subprocess.run, etc.). ``open`` is not in either set, so a plugin
    doing ``open("/etc/passwd", "w").write(...)`` gets zero warnings.

    The check is best-effort: it only flags calls where the mode is a
    string literal containing ``"w"``, ``"a"``, or ``"x"`` (write,
    append, exclusive-create). Read mode (``"r"`` or no mode arg) is
    safe. Variable mode (``open(path, mode_var)``) can't be analyzed
    statically — we don't flag it (best-effort, may have false negatives).
    """

    def test_open_write_mode_flagged(self):
        """``open("file.txt", "w")`` must produce a warning."""
        source = (
            "def write_config(path):\n"
            "    f = open(path, 'w')\n"
            "    f.write('data')\n"
            "    f.close()\n"
        )
        warnings = audit_source(source, filename="plugin.py")
        assert any(
            "open" in w.lower() and "write" in w.lower() for w in warnings
        ), f"open(path, 'w') must be flagged as a write-mode open(), got warnings: {warnings}"

    def test_open_append_mode_flagged(self):
        """``open("file.txt", "a")`` must produce a warning."""
        source = "f = open('log.txt', 'a')\n"
        warnings = audit_source(source, filename="plugin.py")
        assert any(
            "open" in w.lower() and ("write" in w.lower() or "append" in w.lower())
            for w in warnings
        ), f"open(path, 'a') must be flagged as append-mode open(), got warnings: {warnings}"

    def test_open_exclusive_create_mode_flagged(self):
        """``open("file.txt", "x")`` must produce a warning."""
        source = "f = open('lock.tmp', 'x')\n"
        warnings = audit_source(source, filename="plugin.py")
        assert any(
            "open" in w.lower() and ("write" in w.lower() or "create" in w.lower())
            for w in warnings
        ), f"open(path, 'x') must be flagged as exclusive-create open(), got warnings: {warnings}"

    def test_open_read_mode_not_flagged(self):
        """``open("file.txt", "r")`` must NOT produce a warning (read is safe)."""
        source = (
            "def read_config(path):\n"
            "    with open(path, 'r') as f:\n"
            "        return f.read()\n"
        )
        warnings = audit_source(source, filename="plugin.py")
        assert not any(
            "open" in w.lower() and "write" in w.lower() for w in warnings
        ), f"open(path, 'r') is read-only — must NOT be flagged, got warnings: {warnings}"

    def test_open_default_mode_not_flagged(self):
        """``open("file.txt")`` (no mode arg) defaults to read — must NOT be flagged."""
        source = "data = open('file.txt').read()\n"
        warnings = audit_source(source, filename="plugin.py")
        assert not any(
            "open" in w.lower() and "write" in w.lower() for w in warnings
        ), f"open(path) defaults to read — must NOT be flagged, got warnings: {warnings}"

    def test_open_with_binary_write_flagged(self):
        """``open("file.bin", "wb")`` (binary write) must be flagged."""
        source = "with open('data.bin', 'wb') as f:\n    f.write(b'\\x00')\n"
        warnings = audit_source(source, filename="plugin.py")
        assert any(
            "open" in w.lower() for w in warnings
        ), f"open(path, 'wb') must be flagged, got warnings: {warnings}"

    def test_open_with_plus_mode_flagged(self):
        """``open("file.txt", "r+")`` (read+write) must be flagged — has write capability."""
        source = "f = open('config.txt', 'r+')\n"
        warnings = audit_source(source, filename="plugin.py")
        assert any(
            "open" in w.lower() for w in warnings
        ), f"open(path, 'r+') has write capability — must be flagged, got warnings: {warnings}"
