# Example Senpy Plugin: TODO Comment Detector (RPY902)

Second example Senpy plugin — alongside [`my_senpy_plugin`](../my_senpy_plugin/MY_SENPY_PLUGIN_README.md) (RPY901).
This one defines **one rule**: `RPY902` — flags `# TODO:`, `# FIXME:`, `# XXX:`, and `# HACK:` comments left in Ren'Py source files.

```renpy
# Bad (RPY902 fires — HINT severity, not an error, just a reminder)
label start:
    # TODO: implement the bad ending path
    # FIXME: this crashes on rollback
    "Hello, world!"

# Good
label start:
    "Hello, world."
```

The rule fires only on Ren'Py comments (lines starting with `#`). Dialogue
strings and Python statements that happen to contain the word "TODO" are
not flagged. The match is case-insensitive and respects word boundaries,
so `# todolist` (no space) does NOT fire, but `# TODO:` does.

**Severity:** `HINT` — TODO comments are reminders, not bugs. They are
suppressed in `--errors-only` mode. Use `--info` (or just run without
`--errors-only`) to see them.

---

## Installation

### From source (development mode)

```bash
cd examples/todo_comment_plugin
pip install -e .
```

After this, Senpy will discover the plugin automatically on next run.

### Trust the plugin

```bash
senpy --trust-plugin todo-comment-plugin
```

This is a one-time step. The trust is stored in `~/.senpy/trusted_plugins.json`.

### Verify installation

```bash
# RPY902 should appear in the rule list
senpy rule list --format json | python -c "
import json, sys
rules = json.load(sys.stdin)
rpy902 = [r for r in rules if r['code'] == 'RPY902']
if rpy902:
    print('OK: RPY902 is visible:', rpy902[0]['title'])
else:
    print('FAIL: RPY902 not found')
    sys.exit(1)
"

# Show the full rule detail
senpy rule show RPY902
```

### Run on a project

```bash
# Default run — HINT diagnostics are shown
senpy path/to/game/

# Errors-only — RPY902 (HINT) is suppressed
senpy path/to/game/ --errors-only

# Filter to only TODO comments (using tags)
senpy path/to/game/ --tag productivity
```

---

## How It Works

### Rule Definition

```python
from senpy.plugins import Rule, RuleMeta, RuleContext, register_rule
from senpy.api import Diagnostic

PLUGIN_API_VERSION = "1.0"

@register_rule("RPY902")
class TodoCommentRule(Rule):
    meta = RuleMeta(
        code="RPY902",
        docs="Detects TODO, FIXME, XXX, and HACK comments in .rpy files.",
        severity="HINT",
        fixable=False,
        tags=["productivity", "dead-code"],
    )

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        # ctx.file_path, ctx.lines, ctx.symbols
        # Return list of Diagnostic objects (empty if no issues)
        ...
```

### Detection Logic

The rule scans every line of the file. A line is flagged if it matches:

```python
re.compile(r"#\s*\b(TODO|FIXME|XXX|HACK)\b\s*:?", re.IGNORECASE)
```

This regex:
- Requires the line to start with `#` (a Ren'Py comment)
- Allows optional whitespace between `#` and the keyword
- Matches one of TODO, FIXME, XXX, HACK (case-insensitive)
- Requires a word boundary AFTER the keyword (so `todolist` doesn't fire)
- Optionally matches a trailing `:` or space (common but not required)

### Why HINT, Not WARNING?

TODO comments are not bugs. They are reminders that something is unfinished.
Making them `ERROR` or `WARNING` would fail CI builds for purely stylistic
reasons — most teams have TODOs in their codebase as a normal part of
development. `HINT` lets the user opt in (via `--info` or by removing
`--errors-only`) without blocking anything.

### Why Not Auto-Fixable?

Removing TODO comments automatically would lose the reminder. If a TODO
is no longer relevant, the developer should delete it manually (and
Senpy will stop reporting it on the next run).

---

## Testing the Plugin

### Unit Test (in your plugin's test suite)

```python
from senpy.plugins.base import RuleContext
from todo_comment_plugin.rules import TodoCommentRule


def test_detects_todo():
    rule = TodoCommentRule()
    ctx = RuleContext(
        file_path="test.rpy",
        lines=[
            'label start:\n',
            '    # TODO: implement this\n',  # flagged
            '    "Hello"\n',
        ],
        symbols={},
    )
    diags = rule.check(ctx)
    assert len(diags) == 1
    assert diags[0].code == "RPY902"
    assert diags[0].line_number == 2
    assert "TODO" in diags[0].message


def test_ignores_dialogue():
    rule = TodoCommentRule()
    ctx = RuleContext(
        file_path="test.rpy",
        lines=['    "TODO: this is dialogue, not a comment"\n'],
        symbols={},
    )
    assert rule.check(ctx) == []


def test_case_insensitive():
    rule = TodoCommentRule()
    ctx = RuleContext(
        file_path="test.rpy",
        lines=['    # fixme: lowercase\n'],  # flagged
        symbols={},
    )
    diags = rule.check(ctx)
    assert len(diags) == 1
    assert "FIXME" in diags[0].message  # normalized to uppercase


def test_word_boundary():
    rule = TodoCommentRule()
    ctx = RuleContext(
        file_path="test.rpy",
        lines=['    # todolist — not the keyword\n'],  # not flagged
        symbols={},
    )
    assert rule.check(ctx) == []
```

### Integration Test (via Senpy CLI)

```bash
# After `pip install -e .` and `senpy --trust-plugin todo-comment-plugin`:
senpy rule show RPY902
# Should print the rule detail panel with severity HINT, tags productivity dead-code.
```

---

## Comparison with `my_senpy_plugin` (RPY901)

| Aspect | `my_senpy_plugin` (RPY901) | `todo_comment_plugin` (RPY902) |
|---|---|---|
| What it detects | Dialogue without `_()` for translation | TODO/FIXME/XXX/HACK comments |
| Severity | `WARNING` | `HINT` |
| Line type scanned | Dialogue (starts with `"` or `'`) | Comments (starts with `#`) |
| Fixable | No | No |
| Tags | `translations`, `accessibility` | `productivity`, `dead-code` |
| Use case | Catches a real bug (missing translation) | Catches a reminder (incomplete work) |

Together, the two example plugins demonstrate:
- Two different severity levels (`WARNING` vs `HINT`)
- Two different line-type scans (dialogue vs comments)
- Two different tag taxonomies (i18n vs productivity)
- The shared plugin contract (`Rule` subclass + `RuleMeta` + `@register_rule`)

---

## Plugin Development Checklist

If you're writing your own plugin based on this one:

1. **Copy this directory** and rename `todo_comment_plugin/` to your package name.
2. **Update `pyproject.toml`** — change `name`, `description`, and the entry-point key.
3. **Update `rules.py`** — change the `@register_rule("RPY...")` code and `RuleMeta.code` to your own (use a code in the RPY9xx range to avoid clashing with built-in rules).
4. **Set `PLUGIN_API_VERSION = "1.0"`** to match Senpy's current API version.
5. **Choose severity carefully** — `ERROR` blocks CI; `WARNING` is the default visible level; `HINT` requires `--info` or non-`--errors-only` to be seen.
6. **Add tags** — they let users filter with `--tag` and `--ignore-tag`. See `senpy rule list --format json` for the existing taxonomy.
7. **Test before trusting** — run `senpy` once after install to see the trust prompt, then `senpy --trust-plugin your-plugin-name` to make it permanent.
8. **Document the rule** — your plugin's README should explain what the rule detects, why it's the chosen severity, and how to suppress it (`# noqa: RPY902` or `--ignore RPY902`).

---

## See Also

- [`my_senpy_plugin` README](../my_senpy_plugin/MY_SENPY_PLUGIN_README.md) — the other example plugin (RPY901)
- [Senpy Plugin System docs](../../README.md#plugin-system) — overview of the plugin API
- [Senpy Rules Reference](../../RULES.md) — full list of built-in rules
- [Senpy Architecture: Plugin System](../../ARCHITECTURE.md#plugin-system) — internals of how plugins are loaded
