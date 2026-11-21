# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
# PyInstaller spec for the standalone senpy.exe shipped inside the VSIX.
#
# THIS SPEC IS THE RELEASE BUILD. ``.github/workflows/release.yml`` runs
# ``python -m PyInstaller senpy.spec`` (NOT CLI args) so that the options
# below are the single source of truth for the frozen executable.
#
# ``collect_all('senpy')`` is load-bearing: it runs collect_data_files +
# collect_submodules + collect_dynamic_libs and bundles EVERY non-.py file
# in the senpy package into the exe's datas list. Without it, runtime-loaded
# package data (notably senpy/domain/data/renpy_api_generated.json, opened
# at import time by senpy/domain/renpy_api_generated.py via
# importlib.resources) is missing from the _MEI... extraction tree and the
# frozen exe crashes with FileNotFoundError on every invocation — including
# ``--version`` (0.9.2 release blocker). collect_all is what makes adding a
# new package data file NOT require a matching --add-data flag here.
#
# Entry point is senpy/cli/__main__.py (not main.py): __main__.py actually
# *calls* main() and wraps the import in try/except so an import-time
# failure prints "SENPY FATAL ERROR: ..." instead of a bare traceback.
# Forward-slash path works on the Windows runner and is portable.
# =============================================================================
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
tmp_ret = collect_all('senpy')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['senpy/cli/__main__.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='senpy',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
