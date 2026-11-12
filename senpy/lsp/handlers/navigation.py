"""Back-compat re-export shim for senpy.lsp.handlers.navigation.

Split this 1353-line module into
6 focused sub-modules. This file re-exports the public names so
existing imports (``from senpy.lsp.handlers.navigation import definition``)
keep working without changes.

New code should import from the focused modules directly:
    from senpy.lsp.handlers.definition import definition
    from senpy.lsp.handlers.references import references
    from senpy.lsp.handlers.rename import rename, prepare_rename
    from senpy.lsp.handlers.document_symbols import document_symbols
    from senpy.lsp.handlers.call_hierarchy import (
        prepare_call_hierarchy, incoming_calls, outgoing_calls,
    )
"""

from __future__ import annotations

# Public LSP handler functions — re-exported for back-compat.
from senpy.lsp.handlers.call_hierarchy import (
    incoming_calls,
    outgoing_calls,
    prepare_call_hierarchy,
)
from senpy.lsp.handlers.definition import definition
from senpy.lsp.handlers.document_symbols import document_symbols
from senpy.lsp.handlers.references import references
from senpy.lsp.handlers.rename import prepare_rename, rename

__all__ = [
    "definition",
    "references",
    "rename",
    "prepare_rename",
    "document_symbols",
    "prepare_call_hierarchy",
    "incoming_calls",
    "outgoing_calls",
]
