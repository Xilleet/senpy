"""senpy.lsp.handlers — LSP-обработчики, вынесенные из server.py.

Введено в 0.6.0 при рефакторинге lsp/server.py в class SenpyLSPServer.
Каждый модуль содержит handler-функции для своей группы LSP-методов:

  text_document.py  ← did_open / did_save / did_change / did_close / did_change_watched_files
  navigation.py     ← definition / references / rename / prepare_rename / document_symbols
  hover.py          ← hover
  completion.py     ← completions
  diagnostics.py    ← code_action / publish
  workspace.py      ← workspace_symbol / folding_range / document_highlight

Handler-функции принимают (ls, params) и делегируют в server_mod для доступа
к shared state (_active_analyzer, _symbol_snapshot, _analysis_lock, ...).
Это позволяет:
  - тестировать handlers изолированно (mock server_mod)
  - переносить логику в class SenpyLSPServer без дублирования
  - добавлять новые handlers (documentColor, signatureHelp, ...) без роста server.py
"""
