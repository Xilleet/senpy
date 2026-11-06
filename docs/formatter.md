---
title: Senpy Formatter — Code Style for Ren'Py (.rpy)
description: Senpy ships a `senpy format` subcommand that formats .rpy files in place, like `black` for Python or `rustfmt` for Rust. 9 opinionated formatter rules — indent, blank lines, trailing whitespace, smart quotes, op/comma/colon spacing, string consistency. Idempotent: format(format(x)) == format(x).
tags:
  - formatter
  - reference
---

# Senpy Formatter

Senpy ships a `senpy format` subcommand that formats `.rpy` files in
place, like `black` for Python or `rustfmt` for Rust. The formatter is
**opinionated** — there are no per-rule configuration options (except
`string_style`, see below). The goal is **idempotent** output:
`senpy format format(x) == senpy format(x)`.

This page is the canonical style guide. For the source of truth, see
[`docs/FORMAT_STYLE_GUIDE.md`](https://github.com/Xilleet/senpy/blob/main/docs/FORMAT_STYLE_GUIDE.md)
in the repository.

---

## Quick reference

| # | Rule ID | What it does | Default |
|---|---|---|---|
| 1 | `FMT-INDENT` | Tab → 4 spaces; normalize mixed indentation | on |
| 2 | `FMT-BLANK-LINES` | Collapse 3+ blank lines → 2 | on |
| 3 | `FMT-TRAILING-WS` | Strip trailing whitespace from every line | on |
| 4 | `FMT-QUOTES` | Smart/curly quotes → straight quotes in **code** lines | on |
| 5 | `FMT-OP-SPACING` | Single space around binary operators in **code** | on |
| 6 | `FMT-COMMA-SPACING` | Single space after `,` in **code** | on |
| 7 | `FMT-COLON-SPACING` | No space before `:` that opens a block | on |
| 8 | `FMT-STRING-CONSISTENCY` | Normalize quote style of single-line string literals | on (`string_style = "double"`) |
| 9 | `FMT-EOF-NEWLINE` | Ensure exactly one `\n` at end of file | on |

---

## Rule order

Rules are applied in registration order (defined by import order in
`senpy/formatter/rules/__init__.py`). Order matters — some rules rely
on the output of earlier rules:

1. **FMT-INDENT** (must be first — other rules rely on the `indent`
   field of `FormatContext` which is computed from leading whitespace)
2. **FMT-BLANK-LINES** (collapse before strip — cheaper)
3. **FMT-TRAILING-WS** (strip trailing whitespace)
4. **FMT-QUOTES** (smart quotes → straight, in code only)
5. **FMT-OP-SPACING** (binary operators in code)
6. **FMT-COMMA-SPACING** (after commas in code)
7. **FMT-COLON-SPACING** (before block-opening colons)
8. **FMT-STRING-CONSISTENCY** (normalize outer quotes of string
   literals in code; configurable via `FormatConfig.string_style`)
9. **FMT-EOF-NEWLINE** (**must be last** — adds the final `\n` if
   missing; everything else operates on existing line content)

---

## What is NOT touched

The formatter is deliberately conservative. The following are **never**
modified:

- **Dialogue lines** — any line whose first non-whitespace character is
  `'` or `"`. Ren'Py dialogue convention is independent of code style,
  and reformatting dialogue could break character voice, translation
  memory, or voice-line timing.
- **Triple-quoted strings** (`"""..."""`, `'''...'''`) — too easy to
  break (closing quote matching, escape sequences, docstrings).
- **Skip blocks** — anything between `# senpy: format off` and
  `# senpy: format on`. This is the escape hatch for code that must
  not be reformatted (e.g. ASCII art, alignment-sensitive tables).
- **Comments** — content of `#` comments is preserved verbatim. Only
  their leading whitespace is normalized by FMT-INDENT.

---

## Configuration

The formatter is **opinionated by default**, but exposes one tunable
in `FormatConfig`:

```python
from senpy.formatter import FormatConfig, Formatter

# Default: 'hi' → "hi" (Ren'Py convention)
f1 = Formatter(FormatConfig())

# Reverse: "hi" → 'hi'
f2 = Formatter(FormatConfig(string_style="single"))

# Disable string-quote normalization entirely
f3 = Formatter(FormatConfig(string_style="preserve"))
```

`string_style` is the **only** tunable parameter. Other formatting
decisions (indent size, max blank lines, op spacing) are baked in.
This matches the philosophy of `black` — fewer options means more
consistent output across projects.

---

## Idempotency invariant

Every rule is designed to be idempotent:

```python
once = formatter.format_code(source)
twice = formatter.format_code(once)
assert once == twice  # ALWAYS true
```

If you find a case where `format(format(x)) != format(x)`, that's a
bug — please open an issue with a minimal reproducer. The test suite
includes idempotency tests for every rule (see
`tests/test_formatter_idempotency.py`).

---

## CLI usage

```bash
# Format files in place (like black with no args)
senpy format game/script.rpy
senpy format game/                   # recursively

# Check mode: exit 1 if any file would be changed (CI-friendly)
senpy format --check game/

# Diff mode: print unified diff of what would change
senpy format --diff game/script.rpy

# Format from stdin (editor integration)
echo 'label start:\n\t"Hi"\n' | senpy format --stdin-filename test.rpy
```

### When to use each mode

- **No flags** — interactive use, format in place. Run before
  committing.
- **`--check`** — CI gate. Add to a pre-commit hook or a CI workflow
  to fail if any file would be reformatted.
- **`--diff`** — review what the formatter would change before
  applying it.
- **`--stdin-filename`** — editor integration (e.g. format on save in
  VS Code without the Senpy LSP).

---

## Skip blocks

To disable formatting for a specific block of code, wrap it with
`# senpy: format off` and `# senpy: format on`:

```renpy
# senpy: format off
$ x = {                  # hand-aligned dict
    "key1":  "value1",
    "key2":  "value2",
}
# senpy: format on
```

The formatter preserves everything between the markers verbatim.

For a single line you want to skip:

```renpy
$ x = 1   # senpy: format skip
```

The line is preserved as-is.

Use these for:

- **Hand-aligned tables** (ASCII art, key-value pairs aligned in
  columns)
- **External code** (pasted Python that should not be reformatted to
  match Ren'Py convention)
- **Code that depends on specific whitespace** (rare, but exists)

---

## VS Code integration

The Senpy VS Code extension exposes two formatter commands:

- **Format Document** — `Shift+Alt+F` — runs the formatter on the
  current file.
- **Format Selection** — `Ctrl+K Ctrl+F` — runs the formatter on the
  selected range.

The formatter also runs automatically on save if you enable
`editor.formatOnSave` in your VS Code settings:

```json
{
  "[renpy]": {
    "editor.formatOnSave": true,
    "editor.defaultFormatter": "xilleet.senpy-vscode"
  }
}
```

---

## Future work

The following are planned for 0.7.6+:

- **FMT-LABEL-ALIGN** — align `label X:` declarations in a column.
- **FMT-ATL-ALIGN** — align ATL statement blocks.
- **FMT-SCREEN-ALIGN** — align screen property assignments.
- **FMT-MENU-CHOICE-ALIGN** — align menu choice captions.
- **FMT-SHOW-ONE-LINE** — collapse single-statement `show` blocks.
- **FMT-LABEL-SEP** — enforce blank lines around `label` declarations.
- **FMT-INIT-SEP** — enforce blank lines around `init python:` blocks.
- **FMT-COMMENT-ALIGN** — align consecutive `#` comments.

These alignment rules are more invasive than the current whitespace
rules and will need careful design to avoid breaking hand-aligned
code. They will be **off by default** in 0.7.6 and **on by default**
after a feedback period.

---

## What's next?

- [**CLI reference**](cli-reference.md) — `senpy format` subcommand
  flags.
- [**Configuration**](configuration.md) — `senpy.toml` (the formatter
  reads no config from `senpy.toml`; only `FormatConfig.string_style`
  via Python API).
- [**Install**](install.md) — `pip install senpy-linter`.
