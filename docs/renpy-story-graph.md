---
title: Ren'Py Story Graph — Visualize Branching Routes and Find Dead Ends
description: A Ren'Py story graph is a flowchart of all labels in your visual novel and the jump/call edges between them. Senpy generates Mermaid.js story graphs via --graph or --graph-file, and interactive HTML reports via --export-html. Use it to find dead ends, unreachable story islands, and routes that loop forever.
tags:
  - story-graph
  - flowchart
  - renpy
  - cluster-e
---

# Ren'Py Story Graph

A Ren'Py story graph is a **flowchart of all labels in your visual
novel** and the `jump`/`call` edges between them. It visualizes your
branching narrative as a directed graph, so you can:

- Spot **dead ends** — labels that have no outgoing `jump` or `return`.
- Spot **unreachable content** — "story islands" that loop into each
  other but have no entry point from `start`.
- Spot **routes that loop forever** — cycles that don't exit cleanly.
- See at a glance **which routes connect to which endings**.

Senpy generates story graphs via three commands:

| Command | Output | Best for |
|---|---|---|
| `senpy --graph` | Mermaid.js markdown printed to stdout | Quick terminal inspection |
| `senpy --graph-file story.md` | Mermaid.js markdown saved to a file | Embedding in a wiki or doc |
| `senpy --export-html report.html` | Standalone HTML report with interactive Mermaid | Sharing with writers, narrative review |

---

## Quick start

```bash
# Generate the story graph as a Markdown file with a Mermaid.js diagram
senpy /path/to/your/game --graph-file story.md

# Generate a standalone HTML report (interactive graph + diagnostics)
senpy /path/to/your/game --export-html report.html

# Print the Mermaid.js diagram to stdout (pipe into any Mermaid renderer)
senpy /path/to/your/game --graph
```

The Mermaid.js output looks like this (excerpt):

```mermaid
flowchart TD
    start([start]) --> intro[intro]
    intro --> chapter_one[chapter_one]
    chapter_one --> {route_a, route_b}
    route_a --> good_ending
    route_b --> bad_ending
    forgotten_draft[forgotten_draft] --> missing_secret_room[missing_secret_room]
    %% ↑ story island — nothing jumps INTO this from start
```

Open it in any Mermaid viewer (GitHub renders Mermaid in markdown
natively, VS Code has Mermaid preview extensions, mermaid.live is an
online playground).

The HTML report is a standalone file you can email to a writer or
narrative designer — no installation needed. The Mermaid.js is loaded
from a CDN with `securityLevel: 'strict'` and a CSP `default-src
'none'` policy to prevent XSS from script tags in the report.

---

## What the graph shows

Each label in your project becomes a node:

- **Start / system labels** (e.g. `start`, `splash_window`,
  `after_load`, `main_menu`) are styled as rounded rectangles — they
  are Ren'Py built-in labels called automatically by the engine.
- **Regular labels** are styled as rectangles.
- **Endings** (labels that only have incoming edges, no outgoing
  `jump` or `call`) are highlighted as terminal nodes.
- **Story islands** (subgraphs with no entry from `start`) are
  visually isolated — you can see at a glance which labels don't
  connect to the main story.

Each `jump` or `call` becomes an edge:

- **`jump`** — solid arrow.
- **`call`** — solid arrow with a small "call" label.
- **`menu:` choices** — branches from the menu node to the
  per-choice labels.

Edges are **directional** — the arrow goes from the source label to
the target.

---

## What the graph catches

### Story islands (`RPY309`)

A group of labels that reference each other in a loop, but **no
entry point exists from `start`, `splashscreen`, or main menu**.
Unreachable dead content or orphaned story routes.

```renpy
# Bad: Loops into each other, but unreachable from start!
label route_draft_a:
    "Draft scene A"
    jump route_draft_b

label route_draft_b:
    "Draft scene B"
    jump route_draft_a
```

In the graph, you'll see `route_draft_a` and `route_draft_b` as a
small isolated component, disconnected from the main `start` graph.
That's your visual cue to either:

- Connect the route via a `jump` from the main story.
- Delete it as dead content.

### Unreferenced dead labels (`RPY303`)

A label declared but **never reached by any `jump` or `call`**.
Usually an abandoned draft or a route that was cut but the label
wasn't removed.

In the graph, these appear as **isolated single nodes** (no incoming
edges, may have outgoing edges to other labels that *are* reachable).
Easy to spot — they're disconnected from the main component.

### Fallthrough hazards (`RPY308`)

A label that ends without `jump` or `return` before the next label
declaration — control flow bleeds into the next label. In the graph,
you'll see a "phantom edge" from the end of one label to the start of
the next, even though there's no `jump` in the source.

Senpy flags this with `RPY308`. In the graph, the implicit edge is
drawn with a dashed line (or annotated as "fallthrough").

### Always-false branches (`RPY403`)

A branch like `if False:` or `if x and not x:` can never execute. In
the graph, the branch target is unreachable from the source — you'll
see it as a node with no incoming edges from the condition.

Senpy flags this with `RPY403`.

---

## Use cases

### 1. Narrative review before release

Generate the HTML report and share it with your narrative designer:

```bash
senpy /path/to/game --export-html narrative_review.html
```

They open it in any browser, see the full story structure, and can
spot:

- "Wait, route_c doesn't connect to anything? I thought we cut that
  last week."
- "Why does `bad_ending` have an outgoing `jump`? Endings should be
  terminal."
- "Two `start` branches lead to the same ending — is that intended?"

### 2. Onboarding a new writer

When a new writer joins the project, give them the story graph
alongside the source. They can see the full branching structure in
one image instead of reading 50 `.rpy` files.

### 3. Auditing for cut content

After a major rewrite, generate the graph and look for:

- **Isolated nodes** — labels that became disconnected when the
  routing changed.
- **Story islands** — groups of labels that were part of a cut
  route.
- **Dangling edges** — `jump` to labels that no longer exist
  (`RPY302` flags these too, but the graph makes them visual).

### 4. Localization planning

If you're planning to translate the game, the story graph tells you
how many *routes* you have (not just how many lines). Some routes
may not be worth translating if they're cut content — the graph
makes that visible.

### 5. QA routing

QA testers can use the graph to plan playthroughs that cover every
reachable branch. Combined with `--coverage` for translations, you
get a complete "what's in the game, what's tested, what's
translated" picture.

---

## Output formats

### Mermaid.js markdown (`--graph`, `--graph-file`)

Plain markdown with a `mermaid` code block. Renders in:

- GitHub (markdown renders Mermaid natively)
- GitLab (same)
- VS Code with a Mermaid preview extension
- <https://mermaid.live> (paste and render online)
- MkDocs Material / Docusaurus / GitBook (with Mermaid plugin)

Example file (`story.md`):

```markdown
# Story Graph

\`\`\``mermaid
flowchart TD
    start([start]) --> intro[intro]
    intro --> chapter_one[chapter_one]
    ...
\`\`\`
```

Commit it to your repo or share via wiki.

### Standalone HTML report (`--export-html`)

A complete HTML page with:

- The interactive Mermaid.js graph (zoom, pan, click nodes to highlight
  edges).
- The diagnostics list (every rule that fired, with file/line/code).
- A summary table (count of errors / warnings / hints by rule).
- CSP-protected (`default-src 'none'`) so it's safe to share.

```bash
senpy /path/to/game --export-html report.html
```

Open in any browser — no server, no installation. Email it to your
narrative designer, attach it to a bug report, or commit it to your
repo as a project snapshot.

### In-editor story graph (VS Code)

If you have the Senpy VS Code extension installed:

1. Open any `.rpy` file from your project.
2. `Ctrl+Shift+P` → "Senpy: Show Story Graph".
3. A webview opens with the interactive Mermaid.js graph.

Useful for live navigation — click a node to jump to the source
label in your editor.

---

## Filtering the graph

By default, the graph shows every label. If you have a large project
(500+ labels), use rule filters to focus:

### Hide system labels

```bash
senpy /path/to/game --graph-file story.md --ignore-tag formatting
```

System labels (`start`, `splash_window`, `after_load`, `main_menu`)
are still included — they're part of the story entry points. But
you can filter out other rule-tagged labels.

### Show only reachable labels (hide story islands)

There's no single flag for this — story islands are a *property* of
the graph, not a filter. But if you've already cleaned up `RPY309`
violations, the graph will naturally show only the connected
component from `start`.

### Show only a specific route

For a focused look at one route:

```bash
senpy /path/to/game --graph-file route_a.md
# then manually edit route_a.md to keep only the labels in route A
```

This is a manual workflow — Senpy doesn't currently filter the graph
by subgraph. (Open an issue if you'd find this useful.)

---

## Limitations

- **Dynamic jumps** (`jump expression`, `call expression`) are shown
  as a single edge labeled "dynamic" — Senpy can't resolve the target
  statically. Verify these manually.
- **Python-driven `jump`** (e.g. `renpy.jump("label_" + str(x))`) is
  not detected — Senpy doesn't trace Python execution. Same as above.
- **`menu:` choice blocks** are flattened — each choice becomes an
  edge from the menu label to the choice's first label. If a choice
  has a `pass` body, the edge goes to the next statement after the
  menu, which is usually the merge point.
- **Graph size** — Mermaid.js renders fine up to ~300 nodes. Beyond
  that, the graph becomes hard to read. Use `--export-html` and zoom
  in/out for navigation.

---

## What's next?

- [**Ren'Py VS Code Extension**](renpy-vscode-extension.md) — view the
  story graph inside VS Code with `Ctrl+Shift+P` → "Senpy: Show Story
  Graph".
- [**All 53 rules**](rules/index.md) — including `RPY309` (story
  islands), `RPY303` (dead labels), `RPY308` (fallthrough), `RPY403`
  (always-false branches).
- [**CLI reference**](cli-reference.md) — `--graph`, `--graph-file`,
  `--export-html`, `--inspect`.
