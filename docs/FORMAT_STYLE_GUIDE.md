# Senpy Format Style Guide

This document describes the formatting rules applied by `senpy format`
(the standalone formatter subcommand, separate from the linter). The
formatter is **opinionated** — like `black` for Python or `rustfmt`
for Rust — there are no configuration options for individual rules
(except `string_style`, see FMT-STRING-CONSISTENCY below). The goal
is **idempotent** output: `senpy format format(x) == senpy format(x)`.

> **Status:** This is a stub covering the 9 formatter rules shipped
> in Senpy 0.7.4+. The full style guide (with before/after examples
> for every rule, edge cases, and rationale) is tracked separately.
> The current document is enough to understand what `senpy format` will
> do to your `.rpy` files, but does not yet cover every edge case.

## Quick reference

| #  | Rule ID                   | What it does                                          | Default |
|----|---------------------------|-------------------------------------------------------|---------|
| 1  | `FMT-INDENT`              | Tab → 4 spaces; normalize mixed indentation           | on      |
| 2  | `FMT-BLANK-LINES`         | Collapse 3+ blank lines → 2                           | on      |
| 3  | `FMT-TRAILING-WS`         | Strip trailing whitespace from every line             | on      |
| 4  | `FMT-QUOTES`              | Smart/curly quotes → straight quotes in **code** lines | on      |
| 5  | `FMT-OP-SPACING`          | Single space around binary operators in **code**      | on      |
| 6  | `FMT-COMMA-SPACING`       | Single space after `,` in **code**                    | on      |
| 7  | `FMT-COLON-SPACING`       | No space before `:` that opens a block                | on      |
| 8  | `FMT-STRING-CONSISTENCY`  | Normalize quote style of single-line string literals  | on (`string_style = "double"`) |
| 9  | `FMT-EOF-NEWLINE`         | Ensure exactly one `\n` at end of file (**last**)     | on      |

(8 unique rules + EOF-NEWLINE = 9 entries in the table; the worklog
counts 8 because EOF-NEWLINE is structurally part of the
whitespace-cleanup family. Either count is correct.)

## Rule order

Rules are applied in registration order (defined by import order in
`senpy/formatter/rules/__init__.py`). Order matters — some rules
rely on the output of earlier rules:

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

## Future work

The following are tracked for a future release (not yet scheduled):

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
code. They will be **off by default** and **on by default**
after a feedback period.
