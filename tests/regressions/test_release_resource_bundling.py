"""Regression tests for release blocker: the frozen ``senpy.exe``
shipped in the VSIX crashed on every invocation (including ``--version``)
with ``FileNotFoundError: ...senpy\\domain\\data\\renpy_api_generated.json``.

Root cause (two halves):

1. **Data not bundled.** ``.github/workflows/release.yml`` built the exe
   with raw PyInstaller CLI args (``python -m PyInstaller --onefile ...
   senpy/cli/main.py``), bypassing ``senpy.spec`` and therefore never
   running ``collect_all('senpy')``. The JSON resource
   ``senpy/domain/data/renpy_api_generated.json`` — opened at import time
   by ``senpy/domain/renpy_api_generated.py`` — was never added to the
   bundle's datas list, so it was absent from the ``_MEI...`` extraction
   tree at runtime.

2. **Loader not bundle-aware.** The loader resolved the JSON via
   ``Path(__file__).parent / "data" / ...``, which works in a dev checkout
   and a pip-installed wheel but is fragile in a PyInstaller onefile:
   ``__file__`` points into the ``_MEI...`` temp dir, and the data file
   only resolves if it was bundled at exactly ``senpy/domain/data/``.

Fix:

- ``senpy/domain/renpy_api_generated.py`` now resolves the JSON via
  ``importlib.resources.files("senpy.domain").joinpath("data", ...)`` —
  the canonical bundle-aware resource API, honoured by PyInstaller as
  long as the data file is in the bundle's datas list.
- ``release.yml`` now builds via ``python -m PyInstaller senpy.spec``,
  and ``senpy.spec`` runs ``collect_all('senpy')`` which auto-bundles
  every non-.py file in the package (including the JSON, and any future
  data file) — so adding a new package data file no longer needs a
  matching ``--add-data`` flag.

These tests guard both halves so the class of bug cannot recur silently:
the loader must stay bundle-aware, the spec must keep ``collect_all``,
the release build must use the spec, the wheel must ship the JSON, and
the JSON must actually load.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._helpers.paths import REPO_ROOT

_PROJECT_ROOT = REPO_ROOT
_SPEC = _PROJECT_ROOT / "senpy.spec"
_RELEASE_YML = _PROJECT_ROOT / ".github" / "workflows" / "release.yml"
_LOADER = _PROJECT_ROOT / "senpy" / "domain" / "renpy_api_generated.py"
_JSON = _PROJECT_ROOT / "senpy" / "domain" / "data" / "renpy_api_generated.json"
_PYPROJECT = _PROJECT_ROOT / "pyproject.toml"


# =============================================================================
# 1. The loader loads the JSON (behavioral — catches a missing/corrupt file
#    in ANY distribution shape, before a release ships).
# =============================================================================


class TestLoaderLoadsResource:
    """The JSON resource must load and expose the documented public names.

    ``renpy_api_generated.py`` opens the JSON at import time — if the file
    is missing or unreadable, importing the module raises and every CLI /
    LSP entry point dies. This test imports the module, so a missing data
    file fails the test (and the CI release gate) before the tag ships.
    """

    def test_json_loads_and_exposes_public_names(self) -> None:
        from senpy.domain.renpy_api_generated import (
            RENPY_API_DOCS_GENERATED,
            RENPY_DOC_GENERATED_AT,
            RENPY_DOC_VERSION_GENERATED,
        )

        assert isinstance(RENPY_API_DOCS_GENERATED, dict)
        # The 8.6.1 refresh ships ~750 entries; a near-empty dict would mean
        # the JSON is truncated or the wrong file was bundled.
        assert len(RENPY_API_DOCS_GENERATED) > 100, (
            f"RENPY_API_DOCS_GENERATED unexpectedly small "
            f"({len(RENPY_API_DOCS_GENERATED)} entries) — wrong/empty JSON?"
        )
        assert RENPY_DOC_VERSION_GENERATED, "RENPY_DOC_VERSION_GENERATED empty"
        assert RENPY_DOC_GENERATED_AT, "RENPY_DOC_GENERATED_AT empty"

    def test_json_file_exists_on_disk(self) -> None:
        """The canonical JSON must exist in the source tree."""
        assert _JSON.is_file(), f"missing data file: {_JSON}"
        assert (
            _JSON.stat().st_size > 1000
        ), f"{_JSON} is suspiciously small ({_JSON.stat().st_size} bytes)"


# =============================================================================
# 2. The loader is bundle-aware (importlib.resources, NOT Path(__file__)).
# =============================================================================


class TestLoaderIsBundleAware:
    """The loader must resolve the JSON via ``importlib.resources`` so the
    path is correct inside a PyInstaller ``_MEI...`` extraction tree.

    ``Path(__file__).parent / "data" / ...`` was the pre-fix resolution; it
    works in dev and wheel but is the fragile half of the release blocker.
    """

    def test_loader_uses_importlib_resources(self) -> None:
        src = _LOADER.read_text(encoding="utf-8")
        assert "from importlib.resources import files" in src, (
            "renpy_api_generated.py must resolve the JSON via "
            "importlib.resources.files(...) (bundle-aware). "
            "Path(__file__).parent / 'data' / ... is fragile in a PyInstaller "
            "onefile and caused the 0.9.2 release blocker."
        )
        assert 'files("senpy.domain")' in src, (
            "loader must call files('senpy.domain') so the resource is "
            "located relative to the package, not __file__"
        )

    def test_loader_does_not_use_path_dunder_file(self) -> None:
        """The loader must not resolve the resource via ``Path(__file__)``.

        Checks the executable code, not the docstring (which legitimately
        references the old pattern to explain why it was replaced). The
        loader is a thin JSON reader and should not import ``pathlib.Path``
        at all — if it does, it is almost certainly to rebuild the fragile
        ``Path(__file__).parent / "data" / ...`` resolution that broke the
        frozen senpy.exe.
        """
        import ast

        tree = ast.parse(_LOADER.read_text(encoding="utf-8"))
        # Collect the source of every statement EXCEPT the module docstring
        # (the first Expr whose value is a Constant str).
        body = tree.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]
        code_lines = ast.unparse(ast.Module(body=body, type_ignores=[]))
        assert "Path(__file__)" not in code_lines, (
            "loader must not use Path(__file__) to resolve the JSON — that "
            "resolution broke the frozen senpy.exe (0.9.2 release blocker). "
            "Use importlib.resources.files('senpy.domain') instead."
        )
        # And the pathlib Path import should not be pulled in just for this.
        imported_names = {
            alias.name
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert "pathlib.Path" not in imported_names, (
            "loader should not import pathlib.Path — the bundle-aware "
            "resolution uses importlib.resources, not __file__."
        )


# =============================================================================
# 3. senpy.spec keeps collect_all (the data-bundling mechanism).
# =============================================================================


class TestSpecBundlesAllPackageData:
    """``senpy.spec`` must call ``collect_all('senpy')`` — it runs
    ``collect_data_files`` and bundles every non-.py file in the package
    (notably the JSON) into the exe. Removing it reintroduces the release
    blocker the next time someone builds from the spec.
    """

    def test_spec_contains_collect_all(self) -> None:
        src = _SPEC.read_text(encoding="utf-8")
        assert "collect_all('senpy')" in src or 'collect_all("senpy")' in src, (
            "senpy.spec must call collect_all('senpy') so package data files "
            "(senpy/domain/data/renpy_api_generated.json) are bundled into "
            "senpy.exe. Without it the frozen exe crashes at import."
        )

    def test_spec_entry_is_dunder_main(self) -> None:
        """Entry must be senpy/cli/__main__.py (calls main() + try/except),
        not senpy/cli/main.py (only defines main())."""
        src = _SPEC.read_text(encoding="utf-8")
        assert (
            "senpy/cli/__main__.py" in src or "senpy\\cli\\__main__.py" in src
        ), "senpy.spec entry must be senpy/cli/__main__.py"
        # The old, define-only entry must NOT be the Analysis target.
        assert "'senpy/cli/main.py'" not in src
        assert "'senpy\\cli\\main.py'" not in src

    def test_spec_is_used_by_release_build(self) -> None:
        """release.yml must build via ``python -m PyInstaller senpy.spec``,
        not raw CLI args (which skip collect_all)."""
        src = _RELEASE_YML.read_text(encoding="utf-8")
        assert "senpy.spec" in src, (
            "release.yml must build via senpy.spec (collect_all bundles data); "
            "raw CLI args skip collect_all and caused the 0.9.2 release blocker."
        )
        # The old raw-CLI-arg build (entry = senpy/cli/main.py, --onefile
        # --name --paths passed inline) must not survive.
        assert '"senpy/cli/main.py"' not in src, (
            "release.yml must not pass senpy/cli/main.py as a raw PyInstaller "
            "entry — use senpy.spec instead."
        )


# =============================================================================
# 4. The wheel ships the JSON (package-data declaration).
# =============================================================================


class TestWheelShipsJson:
    """``[tool.setuptools.package-data]`` must declare the JSON so
    ``pip install senpy-linter`` ships the data file alongside the loader.

    The PyInstaller exe bundles via collect_all (spec), the wheel ships via
    package-data — both must hold, or a different distribution shape breaks.
    """

    def test_package_data_declares_json(self) -> None:
        import tomllib

        with _PYPROJECT.open("rb") as f:
            data = tomllib.load(f)
        pkg_data = data.get("tool", {}).get("setuptools", {}).get("package-data", {})
        assert "senpy.domain.data" in pkg_data, (
            "pyproject.toml [tool.setuptools.package-data] must list "
            "'senpy.domain.data' so the wheel ships the JSON."
        )
        patterns = pkg_data["senpy.domain.data"]
        assert (
            "*.json" in patterns
        ), f"senpy.domain.data package-data must include '*.json' (got {patterns})"
