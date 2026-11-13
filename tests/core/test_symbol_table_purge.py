"""Coverage tests for senpy/core/symbol_table.py purge/rebuild methods."""

from __future__ import annotations

from senpy.core.models import FileScope
from senpy.core.symbol_table import SymbolTable
from senpy.core.symbols import LabelSymbol, VariableSymbol


class TestSymbolTablePurge:
    """Direct tests for purge_object_registries, purge_jump_sources, purge_shared_sets."""

    def test_purge_object_registries_removes_labels(self):
        """purge_object_registries removes labels from old scope from the global registries."""
        st = SymbolTable()
        scope = FileScope()
        scope.labels["test_label"] = LabelSymbol(
            name="test_label",
            file_path="/test.rpy",
            line_number=1,
            code_line="label test_label:",
        )
        st.labels["test_label"] = scope.labels["test_label"]
        st.referenced_labels.add("test_label")
        st.file_scopes = {"/test.rpy": scope}

        st.purge_object_registries(scope, {})

        assert "test_label" not in st.labels
        # referenced_labels is a shared set — purge_shared_sets handles it
        # purge_object_registries only removes from the object dicts

    def test_purge_object_registries_removes_variables(self):
        """purge_object_registries removes variables from old scope."""
        st = SymbolTable()
        scope = FileScope()
        var = VariableSymbol(
            name="test_var",
            file_path="/test.rpy",
            line_number=1,
            code_line="default test_var = 0",
            is_constant=False,
        )
        scope.variables["test_var"] = var
        st.variables["test_var"] = var
        st.file_scopes = {"/test.rpy": scope}

        st.purge_object_registries(scope, {})

        assert "test_var" not in st.variables

    def test_purge_jump_sources_removes_old_entries(self):
        """purge_jump_sources removes jump_sources entries from the purged file."""
        st = SymbolTable()
        scope = FileScope()
        scope.jump_sources["target_label"] = [("/test.rpy", 5)]
        st.jump_sources["target_label"] = [("/test.rpy", 5)]
        st.file_scopes = {"/test.rpy": scope}

        st.purge_jump_sources(scope, "/test.rpy")

        # The entry for target_label from /test.rpy should be removed.
        # If it was the only entry, the key is removed entirely.
        assert "target_label" not in st.jump_sources or "/test.rpy" not in [
            src[0] for src in st.jump_sources.get("target_label", [])
        ]

    def test_purge_shared_sets_removes_referenced_labels(self):
        """purge_shared_sets removes referenced_labels from old scope
        when no other scope has them."""
        st = SymbolTable()
        scope = FileScope()
        scope.referenced_labels.add("target1")
        scope.referenced_labels.add("target2")
        st.referenced_labels.update(scope.referenced_labels)

        # Pass file_scopes WITHOUT the purged scope — purge checks if any
        # OTHER scope still has the symbol.
        st.purge_shared_sets(scope, {})

        assert "target1" not in st.referenced_labels
        assert "target2" not in st.referenced_labels

    def test_purge_shared_sets_keeps_entries_in_other_scopes(self):
        """If another scope also references the same label, it stays."""
        st = SymbolTable()
        scope1 = FileScope()
        scope1.referenced_labels.add("shared_label")
        scope2 = FileScope()
        scope2.referenced_labels.add("shared_label")
        st.referenced_labels.add("shared_label")
        st.file_scopes = {"/a.rpy": scope1, "/b.rpy": scope2}

        # Purge scope1 — shared_label should stay because scope2 has it
        st.purge_shared_sets(scope1, {"/a.rpy": scope1, "/b.rpy": scope2})

        assert "shared_label" in st.referenced_labels


class TestSymbolTableRebuild:
    """Tests for rebuild_from_scopes."""

    def test_rebuild_from_empty_scopes(self):
        """Rebuild with no scopes produces empty aggregate sets."""
        st = SymbolTable()
        st.rebuild_from_scopes({})
        assert len(st.labels) == 0
        assert len(st.screens) == 0
        assert len(st.variables) == 0
        assert len(st.user_symbols) == 0

    def test_rebuild_merges_multiple_scopes(self):
        """Rebuild merges labels from multiple file scopes."""
        st = SymbolTable()

        scope1 = FileScope()
        scope1.labels["label_a"] = LabelSymbol(
            name="label_a", file_path="/a.rpy", line_number=1, code_line="label a:"
        )
        scope1.user_symbols.add("var_a")

        scope2 = FileScope()
        scope2.labels["label_b"] = LabelSymbol(
            name="label_b", file_path="/b.rpy", line_number=1, code_line="label b:"
        )
        scope2.user_symbols.add("var_b")

        st.rebuild_from_scopes({"/a.rpy": scope1, "/b.rpy": scope2})

        assert "label_a" in st.labels
        assert "label_b" in st.labels
        assert "var_a" in st.user_symbols
        assert "var_b" in st.user_symbols

    def test_rebuild_preserves_additional_builtins(self):
        """Rebuild keeps the additional_builtins in declared_symbols."""
        st = SymbolTable(additional_builtins={"iap", "updater"})
        st.rebuild_from_scopes({})

        assert "iap" in st.declared_symbols
        assert "updater" in st.declared_symbols
