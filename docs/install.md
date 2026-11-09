---
title: Install Senpy
description: Three ways to install Senpy — Python CLI via pip, VS Code extension via Open VSX (VSCodium, Cursor, GitLab Web IDE, Eclipse Theia), and standalone VSIX from GitHub Releases for VS Code users. Choose the path that fits your workflow.
tags:
  - install
  - getting-started
---

# Install Senpy

Senpy is distributed through three channels. Pick the one that matches
your workflow — they all use the same analyzer engine and the same 53 rules.

| Channel | Best for | Setup |
|---|---|---|
| **`pip install senpy-linter`** | Python CLI, CI/CD, Linux/macOS, advanced users | One command |
| **Open VSX extension** | VSCodium, Cursor, GitLab Web IDE, Eclipse Theia, Neovim | In-editor search |
| **VSIX from GitHub Releases** | VS Code (Microsoft edition), offline install | Download + "Install from VSIX" |

---

## Option 1 — Python CLI via pip

This is the fastest path for CI/CD, Linux/macOS users, and anyone who
already has Python 3.11+ installed.

```bash
pip install senpy-linter
```

Verify:

```bash
senpy --version
senpy --rules    # list all 53 rules
```

Requirements:

- Python 3.11, 3.12, 3.13, or 3.14 (CPython)
- Tested on Ubuntu, Windows, macOS (CI matrix: 9 jobs across OS × Python)
- No Ren'Py SDK required — Senpy is a standalone analyzer

Dependencies (installed automatically):

- `rich` (terminal rendering)
- `pygls` (LSP server, only needed for `--lsp`)
- `lsprotocol` (LSP wire protocol)
- `pydantic` v2 (config validation)

### Upgrade

```bash
pip install --upgrade senpy-linter
```

### Uninstall

```bash
pip uninstall senpy-linter
```

### Troubleshooting pip install

| Symptom | Fix |
|---|---|
| `command not found: senpy` after install | Your `pip` user scripts dir is not on `PATH`. Add `~/.local/bin` (Linux/macOS) or `%APPDATA%\Python\Scripts` (Windows) to your `PATH`. |
| `ModuleNotFoundError: No module named 'senpy'` | You have multiple Pythons. Try `python -m senpy.cli` or install with the same `python` you'll use to run it (`python -m pip install senpy-linter`). |
| `ERROR: Could not find a version` | Senpy requires Python 3.11+. Check your Python version with `python --version`. |
| Slow install / network blocked | Use a mirror: `pip install senpy-linter -i https://pypi.org/simple/` or your internal index. |

---

## Option 2 — Open VSX extension (VSCodium, Cursor, GitLab Web IDE, Eclipse Theia)

The Senpy VS Code extension is published on
[Open VSX](https://open-vsx.org/extension/xilleet/senpy-vscode), the
Eclipse Foundation's vendor-neutral extension registry.Editors that use Open VSX as their default extension source find Senpy
automatically through their built-in extension search.

### VSCodium

1. Open the Extensions panel (`Ctrl+Shift+X` / `Cmd+Shift+X`).
2. Search for `Senpy`.
3. Click Install.

### Cursor

Cursor uses Open VSX as its extension source.

1. Open the Extensions panel.
2. Search for `Senpy`.
3. Click Install.

### GitLab Web IDE

The GitLab Web IDE supports Open VSX extensions.

1. Open the Web IDE.
2. Open the Extensions panel.
3. Search for `Senpy` and install.

### Eclipse Theia

Theia uses Open VSX as its default extension source — Senpy will appear
in the extension search.

### Direct Open VSX link

<https://open-vsx.org/extension/xilleet/senpy-vscode>

---

## Option 3 — VSIX from GitHub Releases (VS Code by Microsoft)

The Microsoft VS Code Marketplace is **not available** for Senpy —
Microsoft Azure DevOps blocks publisher accounts for users in some
regions. We use Open VSX as the primary registry and GitHub Releases as
the secondary channel for VS Code users.

To install in VS Code (Microsoft edition):

1. Go to <https://github.com/Xilleet/senpy/releases/latest>.
2. Download the `senpy-vscode-X.X.X.vsix` asset (the latest is ~17 MB).
3. In VS Code, open the Extensions panel.
4. Click the `⋯` menu (top-right of the panel) → **Install from VSIX…**.
5. Select the downloaded `.vsix` file.
6. Reload VS Code when prompted.

The Windows VSIX includes a **bundled `senpy.exe`** (PyInstaller-built)
so you do not need to install Python, `pip`, or anything else — the
extension works out of the box.

On Linux/macOS, the extension will use your installed `senpy` from
`pip install senpy-linter`. If you don't have it, install it first
(see Option 1 above).

---

## Verifying the installation

Whichever channel you chose, the verification is the same:

### CLI

```bash
senpy --version
# senpy 0.9.0

senpy --rules
# prints a table of all 53 rules with severity + tags

senpy path/to/your/renpy/game
# analyzes the project, prints diagnostics + summary line
```

### VS Code / VSCodium / Cursor

1. Open any `.rpy` file from your Ren'Py project.
2. The status bar should show "Senpy" with the analysis result.
3. Diagnostics (red/yellow/blue squiggles) appear under each issue.
4. `Ctrl+.` (or `Cmd+.` on macOS) on a diagnostic shows QuickFix options.
5. `F12` on a label name jumps to its definition.
6. `Ctrl+Shift+P` → "Senpy: Show Story Graph" opens a Mermaid.js
   flowchart of the story flow.

If the extension does not activate:

- Check the Output panel (View → Output → "Senpy" channel) for errors.
- Check that the bundled `senpy.exe` exists (Windows) or that `senpy`
  is on `PATH` (Linux/macOS).
- Open the command palette → "Senpy: Restart Language Server".

---

## What gets installed where?

| Component | Location | Size |
|---|---|---|
| `senpy` Python package | `site-packages/senpy/` | ~400 KB (wheel) |
| `senpy` CLI entrypoint | `bin/senpy` (Linux/macOS) or `Scripts\senpy.exe` (Windows) | small |
| `.senpy_cache/` (project cache) | Created in your project root on first run | Project-dependent |
| `~/.senpy/trusted_plugins.json` | Plugin trust store (only if you install a plugin) | tiny |
| VS Code extension | `~/.vscode/extensions/xilleet.senpy-vscode-*/` | ~17 MB (includes `senpy.exe` on Windows) |

---

## Next steps

- **Try it on your project** — `senpy /path/to/your/game` and read the
  summary. Don't panic if there are many warnings; most projects have
  accumulated technical debt.
- **Set up [configuration](configuration.md)** — `senpy.toml` lets you
  ignore noisy rules, change severities, and enable `strict` mode.
- **Add Senpy to [CI](renpy-github-actions.md)** — `senpy --init-ci`
  generates a GitHub Actions workflow that runs Senpy on every PR and
  uploads SARIF to GitHub Code Scanning.
- **Browse [all 53 rules](rules/index.md)** — each rule has a page
  explaining what it catches, why it matters, and a real `.rpy` example
  before/after.
