---
title: Ren'Py VS Code Extension — Senpy LSP Features & Shortcuts
description: Senpy is a Ren'Py VS Code extension with 20+ Language Server Protocol handlers — real-time diagnostics, go-to-definition, hover docs, autocomplete, rename, find references, signature help, story graph visualization. Available on Open VSX for VSCodium, Cursor, GitLab Web IDE, Eclipse Theia. For VS Code by Microsoft, install the VSIX from GitHub Releases.
tags:
  - vscode
  - lsp
  - renpy
  - cluster-c
---

# Ren'Py VS Code Extension

Senpy ships a full **Language Server Protocol** implementation with
20+ handlers. It turns VS Code (and any editor that supports LSP) into
a Ren'Py IDE — with real-time diagnostics, go-to-definition, hover
docs, autocomplete, rename, find references, and an interactive story
graph.

The extension is distributed via **Open VSX**, the Eclipse Foundation's
vendor-neutral extension registry.Editors that use Open VSX as their
default extension source (VSCodium, Cursor, GitLab Web IDE, Eclipse
Theia, VSCodium-based forks) find Senpy through their built-in
extension search.

For **VS Code by Microsoft**, the Open VSX listing isn't visible in
the in-editor search — install the VSIX from GitHub Releases instead
(see [Install — VSIX from GitHub Releases](install.md#option-3-vsix-from-github-releases-vs-code-by-microsoft)).

---

## What you get

### Real-time diagnostics

Every keystroke triggers an incremental analysis (~0.04s with the
two-tier disk cache) and updates the squiggles in your editor. You
see the same 52 rules the CLI runs, in real time.

- **Red squiggle** — `ERROR` severity (e.g. `RPY105` define mutation)
- **Yellow squiggle** — `WARNING` (e.g. `RPY104` missing `default`)
- **Blue squiggle** — `INFO` / `HINT` (e.g. `RPY303` unreferenced label)

Hover over a squiggle to see the rule code, severity, and full
message. `Ctrl+.` (or `Cmd+.` on macOS) opens the QuickFix menu.

### QuickFix (auto-fix in editor)

Some rules ship with an auto-fix that you can apply without leaving
the editor. Press `Ctrl+.` on a diagnostic and pick from the available
fixes:

| Rule | QuickFix |
|---|---|
| `RPY001` (tab indentation) | Convert tabs to 4 spaces |
| `RPY002` (smart quotes in code) | Replace `"` / `"` with `"` |
| `RPY107` (deprecated Ren'Py API) | Replace `LiveComposite` with `Composite`, `DynamicCharacter` with `Character`, etc. |
| `RPY206` (function call in screen action) | Wrap with `Function()`: `action heal_player()` → `action Function(heal_player)` |
| `RPY208` (SetVariable on screen-local) | Replace `SetVariable` with `SetScreenVariable` |
| `RPY301` (unclosed text tag) | Insert the matching `{/tag}` at the end of the dialogue |
| `RPY302` (broken jump) | Suggest closest matching label name |
| `RPY502` (unresolved sprite/transform) | Suggest closest matching image attribute |

### Go to Definition (`F12`)

Jump to the declaration of any symbol:

- `jump my_label` → opens the file containing `label my_label:`
- `use my_screen` → opens the file containing `screen my_screen():`
- `show eileen at slide_in` → opens the file containing `transform slide_in:`
- `define player_name = "Eileen"` → opens the file containing the `define`
- `image bg_forest = "forest.png"` → opens the file containing the `image`

Right-click → "Go to Definition" or `F12`. `Alt+F12` opens it in a peek
window without leaving your current file.

### Find All References (`Shift+F12`)

Find every place a symbol is used:

- For a **label**: every `jump`, `call`, and `use screen` that targets
  it.
- For a **screen**: every `show screen`, `call screen`, and `use` that
  references it.
- For a **transform**: every `show ... at <transform>`.
- For a **variable** / **define**: every `$`, every `if`, every `[var]`
  interpolation in dialogue.

Right-click → "Find All References" or `Shift+F12`. Results group by
file.

### Rename Symbol (`F2`)

Rename a label, screen, transform, or define — Senpy updates every
reference across the entire project:

- `F2` on `label chapter_1:` → rename to `chapter_1_intro:` → every
  `jump chapter_1` becomes `jump chapter_1_intro` in every file.
- Same for screens, transforms, and `define` constants.

Renaming is safe — Senpy only renames identifiers it can resolve
statically. Dynamic jumps (`jump expression`) are flagged with a
warning so you can verify them manually.

### Hover documentation

Hover over a symbol to see context-sensitive info:

| Hover target | What you see |
|---|---|
| Ren'Py built-in function (`renpy.show`, `Character(...)`, `play`, `nvl`, ...) | Documentation for 975 Ren'Py API entries (auto-collected from Ren'Py 8.5.3 RST sources) |
| Label name (`jump my_label`) | File path + line + a one-line preview of the label's content |
| Screen name (`use my_screen`) | File path + parameters |
| Image reference (`show sayori 1a`) | Inline preview of the sprite with size metadata (PNG/JPEG/WEBP/GIF/BMP header parsed; no Pillow needed) |
| Audio reference (`play music "bgm.ogg"`) | Inline "Play" link that opens VS Code's media viewer |
| Video file (`.mp4`, `.webm`, etc.) | "Open in default app" link via the `senpy.openExternal` command |

### Autocomplete (`Ctrl+Space`)

Context-aware completions:

- After `jump` / `call`: every label in the project, fuzzy-matched.
- After `use` / `show screen` / `call screen`: every screen.
- After `show <character>`: every attribute of that character's
  layeredimage (e.g. `1a`, `1b`, `2a`, `happy`, `sad`).
- After `play` / `queue` / `stop`: registered audio channels + every
  audio file in `audio/` and `.rpa` archives.
- After `$` / `if` / `while`: every `default` and `define` variable
  in scope.

### Document Symbols (`Ctrl+Shift+O`)

Outline view of the current file — labels, screens, transforms,
images, init blocks. Click any symbol to jump to it.

### Workspace Symbol (`Ctrl+T`)

Global symbol search across all `.rpy` files in your project. Type
`chapter` to find every label, screen, or define whose name contains
"chapter" — across every file, not just the current one.

### Code Folding

Auto-folds:

- `label` blocks
- `screen` blocks
- `menu:` blocks
- `init python:` blocks
- `python:` blocks

Click the chevron in the gutter to fold. Useful in long files with
many labels.

### Document Highlight

Place the cursor on a symbol — every other occurrence of the same
symbol in the file is highlighted. Helps spot "where is this variable
used in this label?".

### Color Swatches

Hex color literals (`#ff69b4`, `#1f1f28`) show up as clickable color
swatches in the editor. Click to open the color picker and edit the
value inline.

### Signature Help (`Ctrl+Shift+Space`)

When you type `call dungeon(` or `use inventory(`, Senpy shows the
parameter signatures:

```
call dungeon(difficulty, party_size=4)
                 ^^^^^^^^^^
                 required (str)
```

Helps avoid `RPY310` (call argument mismatch) and `RPY207` (screen
parameter mismatch) without leaving the editor.

### Call Hierarchy (right-click → "Find Callers")

Right-click a label → "Find Callers" — see every `jump` and `call`
that targets this label, recursively. Useful for tracing story flow
without running the game.

### Format Document (`Shift+Alt+F`)

Run the Senpy formatter (8 rules: indent, blank lines, trailing
whitespace, smart quotes, op/comma/colon spacing, string consistency).
See [Formatter](formatter.md) for the full style guide.

### Story Graph (`Ctrl+Shift+P` → "Senpy: Show Story Graph")

Opens a webview with an interactive **Mermaid.js flowchart** of all
labels in your project and the `jump`/`call` edges between them. See
[Ren'Py Story Graph](renpy-story-graph.md) for the full feature.

---

## Configuration

The extension contributes one setting under `senpy.*`:

```json
{
  "senpy.executablePath": ""
}
```

- **Empty (default)**: the extension uses the bundled `senpy.exe`
  (Windows) or `senpy` from `PATH` (Linux/macOS).
- **Custom path**: set to a specific `senpy` binary, e.g.
  `C:/Python311/Scripts/senpy.exe` or `/usr/local/bin/senpy`. Useful
  when you have multiple Senpy versions installed.

Configuration via `senpy.toml` is read from your project root — see
[Configuration](configuration.md).

---

## Activation

The extension activates when:

- A `.rpy` or `.rpym` file is opened (`onLanguage:renpy`)
- A workspace contains `*.rpy` files (`workspaceContains:**/*.rpy`)
- The command `senpy.showStoryGraph` is invoked

Once activated, the LSP server starts and stays running until VS Code
is closed. Use `Ctrl+Shift+P` → "Senpy: Restart Language Server" to
restart it (e.g. after editing `senpy.toml` to apply new rule
overrides).

---

## How it's different from `vscode-language-renpy`

The official [`vscode-language-renpy`](https://github.com/renpy/vscode-language-renpy)
extension (152 ⭐, maintained by the Ren'Py team) provides syntax
highlighting and basic snippets. Senpy provides **semantic analysis**
on top of that — it understands variables, control flow, screens,
and translation files, not just text.

| Capability | `vscode-language-renpy` | Senpy |
|---|---|---|
| Syntax highlighting | ✅ | ✅ (TextMate grammar copied from renpy-magic, MIT) |
| Language configuration (brackets, comments) | ✅ | ✅ |
| Snippets | ✅ basic | ❌ |
| **Real-time diagnostics** | ❌ | ✅ 52 rules, runs on every keystroke |
| **Go-to-definition** | ❌ | ✅ labels, screens, transforms, defines |
| **Find references** | ❌ | ✅ across the whole project |
| **Hover docs** | ❌ | ✅ 975 Ren'Py API entries + asset previews |
| **Rename symbol** | ❌ | ✅ labels, screens, transforms, defines |
| **Semantic tokens** | ❌ | ✅ |
| **Story graph visualization** | ❌ | ✅ Mermaid diagram of branching routes |
| **Save / rollback safety checks** | ❌ | ✅ |
| **Translation validator** | ❌ | ✅ `game/tl/` mismatch detection + coverage |

The two extensions are **complementary and can be installed
side-by-side**. If you want both syntax highlighting (official) and
semantic diagnostics (Senpy), install both. See [Comparison](comparison.md)
for the full table.

---

## Performance

Senpy is designed for large projects. The two-tier disk cache
(`.senpy_cache/`) keeps incremental analysis at ~0.04s on a 70,000-line
project — fast enough that you don't notice the analysis running on
every keystroke.

The LSP server uses a **reader-writer lock** (`_RWLock` with writer
preference) so multiple read operations (hover, completion, definition)
can run in parallel, and write operations (file change, full re-analysis)
get exclusive access. Each URI has its own debounce timer so rapid
typing doesn't trigger multiple parallel analyses — only the last
change within the debounce window gets analyzed.

If the LSP server feels slow:

1. Check the Output panel (View → Output → "Senpy" channel) for errors.
2. Run `senpy --clear-cache /path/to/game` once to rebuild the cache
   from scratch (corrupted cache can cause slow incremental paths).
3. Restart the LSP server: `Ctrl+Shift+P` → "Senpy: Restart Language
   Server".

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Extension doesn't activate when I open `.rpy` | Make sure the file association is `renpy`. Check the bottom-right of the status bar — it should say "Ren'Py". If it says "Plain Text", click and select "Ren'Py". |
| No squiggles, but extension is active | Check the Output panel for the "Senpy" channel. If you see `senpy.exe not found`, install `senpy-linter` via `pip` (Linux/macOS) or download the latest VSIX from GitHub Releases (Windows). |
| Squiggles are stale after editing `senpy.toml` | Restart the LSP server: `Ctrl+Shift+P` → "Senpy: Restart Language Server". |
| Story Graph webview is blank | The webview needs internet access to load Mermaid.js from a CDN. If you're offline, the graph won't render — use `senpy --graph-file story.md` from the CLI instead, which produces a static Mermaid markdown you can open in any Mermaid viewer. |
| Rename fails with "cannot rename dynamic reference" | Senpy doesn't rename dynamic jumps (`jump expression`) because the target can't be resolved statically. Rename the label manually and update the dynamic expression. |

---

## What's next?

- [**Install**](install.md) — three ways to install (Open VSX, VSIX, pip).
- [**Configuration**](configuration.md) — `senpy.toml`, rule severities,
  strict mode, ignore lists.
- [**Ren'Py Story Graph**](renpy-story-graph.md) — visualize all
  labels and jumps in a Mermaid.js flowchart.
- [**Comparison with `vscode-language-renpy`**](comparison.md) — when
  to use each.
