<p align="center">
  <a href="https://pypi.org/project/senpy-linter/"><img src="https://img.shields.io/pypi/v/senpy-linter.svg?logo=python&logoColor=white" alt="PyPI version"></a>
  <a href="https://pypi.org/project/senpy-linter/"><img src="https://img.shields.io/pypi/dm/senpy-linter.svg?label=PyPI%20downloads" alt="PyPI downloads"></a>
  <a href="https://open-vsx.org/extension/xilleet/senpy-vscode"><img src="https://img.shields.io/badge/Open%20VSX-0.8.0-success?logo=eclipse&logoColor=white" alt="Open VSX"></a>
  <a href="https://github.com/Xilleet/senpy/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Xilleet/senpy/ci.yml?branch=main&label=CI" alt="CI Status"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="License: MIT"></a>
</p>

**Senpy** is a fast static analyzer, semantic linter, control-flow analyzer and
VS Code language server for **Ren'Py visual novels**. It detects undefined
variables, broken labels, control-flow bugs, rollback/save issues, and
translation errors — without requiring the Ren'Py SDK.

---

## Install

**Python CLI / CI:**
```bash
pip install senpy-linter
```

**VS Code / VSCodium / Cursor / GitLab Web IDE / Eclipse Theia:**
Search for `Senpy` in the extensions panel, or install directly from
**Open VSX**: https://open-vsx.org/extension/xilleet/senpy-vscode

**VS Code (Microsoft Marketplace unavailable):**
Download the `senpy-vscode-X.X.X.vsix` asset attached to this release →
*Extensions → ⋯ → Install from VSIX*.
