"""DiagnosticSink — Protocol re-export for backward compatibility.

Historical note: this module used to declare its own ``DiagnosticSink``
Protocol. After Phase 2 (commit 1b30cbc) introduced the broader ISP
Protocol set in ``senpy/core/protocols.py``, the two ``DiagnosticSink``
declarations drifted: ``sink.py`` omitted the ``diagnostics: list`` attribute
and used a slightly different ``_get_utf16_range`` signature. Plugin authors
and contributors saw two contracts with the same name.

The single source of truth now lives in ``senpy/core/protocols.py``. This
module re-exports it so existing imports (``from senpy.core.sink import
DiagnosticSink``, ``from senpy import DiagnosticSink``) keep resolving.

Public API:
    DiagnosticSink  — Protocol (typing only, not instantiated)
"""

from __future__ import annotations

from senpy.core.protocols import DiagnosticSink

__all__ = ["DiagnosticSink"]
