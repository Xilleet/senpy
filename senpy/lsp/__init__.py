"""senpy.lsp.handlers — LSP handlers extracted from server.py.

Introduced in 0.6.0 when refactoring lsp/server.py into class SenpyLSPServer.
Each module contains handler functions for its group of LSP methods:

  text_document.py  ← did_open / did_save / did_change / did_close / did_change_watched_files
  navigation.py     ← definition / references / rename / prepare_rename / document_symbols
  hover.py          ← hover
  completion.py     ← completions
  diagnostics.py    ← code_action / publish
  workspace.py      ← workspace_symbol / folding_range / document_highlight

Handler functions take (ls, params) and delegate to server_mod for access
to shared state (_active_analyzer, _symbol_snapshot, _analysis_lock, ...).
This allows:
  - testing handlers in isolation (mock server_mod)
  - moving logic into class SenpyLSPServer without duplication
  - adding new handlers (documentColor, signatureHelp, ...) without growing server.py
"""
