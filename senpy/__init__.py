"""Senpy — semantic linter & LSP for Ren'Py.

Re-exports для backward compat: после реструктуризации 0.5.4 (файлы
переехали в core/, rules/, lsp/, cli/, formats/, domain/) старые импорты
продолжают работать:
    from senpy import SenpyAnalyzer           # → senpy.core.analyzer
    from senpy import Diagnostic, RULE_SEVERITY  # → senpy.core.models
    from senpy import main                    # → senpy.cli.main
"""
from __future__ import annotations

# Version
from senpy.__version__ import VERSION_WITH_PREFIX, __version__

# CLI
from senpy.cli.main import main
from senpy.cli.unrpyc import (
    decompile_to_sandbox,
    extract_scripts_from_rpa,
    find_unrpyc_executable,
    load_config,
)

# Core
from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.cache import CachedFileEntry, CacheManager, CacheManifest, SafeCacheUnpickler
from senpy.core.constants import SENPY_VERSION
from senpy.core.models import RULE_SEVERITY, AnalysisResult, Diagnostic, FileScope
from senpy.core.sink import DiagnosticSink
from senpy.core.symbols import (
    ImageSymbol,
    LabelSymbol,
    ScreenSymbol,
    TransformSymbol,
    VariableSymbol,
)

__all__ = [
    # Core
    "SenpyAnalyzer",
    "CacheManager", "CacheManifest", "CachedFileEntry", "SafeCacheUnpickler",
    "load_config",
    "SENPY_VERSION",
    "Diagnostic", "RULE_SEVERITY", "AnalysisResult", "FileScope",
    "DiagnosticSink",
    "VariableSymbol", "LabelSymbol", "ScreenSymbol", "ImageSymbol", "TransformSymbol",
    # CLI
    "main",
    # Version
    "__version__", "VERSION_WITH_PREFIX",
]
