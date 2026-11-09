"""Shared mocks for Под-спринт 3 (color & formatting LSP tests).

Extracted from `tests/test_0_6_0_subprint_3a.py` so that
`test_0_6_0_subprint_3b.py` can import `MockDocument`, `MockWorkspace`
without depending on a sibling test module being importable.

NOTE: these classes are intentionally different from the ones in
`tests/_helpers/lsp.py` (different constructor signatures, different
semantics). Do not merge them.
"""

from __future__ import annotations


class MockDocument:
    """Minimal mock of pygls TextDocument for testing."""

    def __init__(self, uri: str, source: str):
        self.uri = uri
        self._source = source
        # Split into lines, preserve newlines
        self.lines = source.splitlines(keepends=True)

    @property
    def source(self) -> str:
        return self._source

    def __len__(self) -> int:
        return len(self.lines)


class MockWorkspace:
    """Minimal mock of pygls Workspace."""

    def __init__(
        self, documents: dict[str, MockDocument] | None = None, root_path: str | None = None
    ):
        self._documents = documents or {}
        self.root_path = root_path

    def get_text_document(self, uri: str) -> MockDocument | None:
        return self._documents.get(uri)
