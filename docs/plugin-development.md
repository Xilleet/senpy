---
title: Senpy Plugin Development — Write Your Own Lint Rules
description: Senpy has a plugin system — write your own lint rules as pip packages. The plugin API is stable (v1.0), supports entry-point discovery, trust-on-first-use security, and per-rule QuickFix. Two example plugins ship in the repo: my_senpy_plugin (RPY901, hardcoded dialogue) and todo_comment_plugin (RPY902, TODO comments).
tags:
  - plugins
  - development
  - reference
---

# Senpy Plugin Development

Senpy has a plugin system — you can write your own lint rules as
pip packages. The plugin API is stable (v1.0), supports entry-point
discovery, trust-on-first-use security, and per-rule QuickFix.

This page walks through:

- The plugin contract (`Rule` subclass + `RuleMeta` + `@register_rule`)
- Trust and security model
- Two example plugins shipped with Senpy (RPY901, RPY902)
- Step-by-step guide to writing your own plugin
- Publishing to PyPI

For the canonical source of truth, see the
[`examples/my_senpy_plugin/MY_SENPY_PLUGIN_README.md`](https://github.com/Xilleet/senpy/blob/main/examples/my_senpy_plugin/MY_SENPY_PLUGIN_README.md)
and
[`examples/todo_comment_plugin/TODO_COMMENT_PLUGIN_README.md`](https://github.com/Xilleet/senpy/blob/main/examples/todo_comment_plugin/TODO_COMMENT_PLUGIN_README.md)
in the repository.

---

## Why write a plugin?

Most Ren'Py linting needs are covered by Senpy's 51 built-in rules.
But every project has domain-specific checks that don't belong in
core:

- "Flag dialogue lines that aren't wrapped in `_()` for translation"
  (example plugin `RPY901`)
- "Flag `# TODO:` / `# FIXME:` comments left in the codebase"
  (example plugin `RPY902`)
- "Flag `renpy.music.play` with `.mp3` instead of `.ogg` (project
  convention)"
- "Flag `define audio.X = "..."` aliases that don't follow a naming
  convention"
- "Flag `image` definitions without a comment block"
- "Project-specific forbidden APIs"

These don't belong in core Senpy — they're project or team
conventions. The plugin system lets you ship them as separate pip
packages, installed only by projects that need them.

---

## The plugin contract

A Senpy plugin is a Python package that:

1. Declares an entry point in the `senpy.plugins` group.
2. Defines a `Rule` subclass with a `RuleMeta`.
3. Implements `check(ctx: RuleContext) -> list[Diagnostic]`.
4. Declares `PLUGIN_API_VERSION = "1.0"` at module level.

### Minimal plugin

```python
# my_plugin/rules.py
"""My custom Senpy rules."""

from senpy.api import Diagnostic
from senpy.plugins import Rule, RuleContext, RuleMeta, register_rule

PLUGIN_API_VERSION = "1.0"


@register_rule("RPY901")
class HardcodedDialogueRule(Rule):
    """Detects dialogue lines without _() for translation."""

    meta = RuleMeta(
        code="RPY901",
        docs="Detects dialogue lines without _() for translation",
        severity="WARNING",
        tags=["translations", "accessibility"],
    )

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        for line_no, raw in enumerate(ctx.lines, start=1):
            stripped = raw.lstrip(" \t")
            if not stripped or stripped[0] not in ('"', "'"):
                continue
            if stripped.startswith('_("') or stripped.startswith("_('"):
                continue  # already translated
            diags.append(
                Diagnostic(
                    file_path=ctx.file_path,
                    line_number=line_no,
                    line_content=raw.rstrip(),
                    code="RPY901",
                    message="Hardcoded dialogue without _() for translation",
                    severity="WARNING",
                )
            )
        return diags
```

### `pyproject.toml` for the plugin

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "my-senpy-plugin"   # pip name (hyphens)
version = "0.1.0"
description = "My custom Senpy lint rules"
requires-python = ">=3.11"
dependencies = [
    "senpy-linter>=0.6.0",
]

# THIS IS THE MAGIC LINE — Senpy finds your plugin via this entry point.
[project.entry-points."senpy.plugins"]
my-senpy-plugin = "my_senpy_plugin.rules:HardcodedDialogueRule"

[tool.setuptools.packages.find]
include = ["my_senpy_plugin*"]
```

---

## Plugin discovery and trust

### Discovery

Senpy discovers plugins via `importlib.metadata.entry_points()` on
the `senpy.plugins` group. Any installed package that declares an
entry point in this group is a candidate.

```bash
# List all installed Senpy plugins
python -c "
from importlib.metadata import entry_points
eps = entry_points(group='senpy.plugins')
for ep in eps:
    print(f'{ep.name} → {ep.value}')
"
```

### Trust-on-first-use

When Senpy first discovers a plugin, it asks for trust:

```
[senpy] Plugin 'my-senpy-plugin' wants to load. Trust and enable? [y/N]:
```

| Answer | Result |
|---|---|
| `y` or `yes` | Plugin is **trusted**, added to `~/.senpy/trusted_plugins.json`, loads now and on every future run |
| `n`, Enter, or anything else | Plugin is **skipped** for this run |
| Non-interactive (CI, no TTY) | All untrusted plugins are **skipped** (fail-safe) |

### Pre-trust without prompt (CI / automation)

```bash
# Trust explicitly before running Senpy
senpy --trust-plugin my-senpy-plugin

# Or via Python API
python -c "from senpy.plugins.security import trust_plugin; trust_plugin('my-senpy-plugin')"

# Now CI runs won't prompt — plugin loads silently
senpy /path/to/game
```

### Revoke trust

```bash
senpy --untrust-plugin my-senpy-plugin

# Or via Python API
python -c "from senpy.plugins.security import untrust_plugin; untrust_plugin('my-senpy-plugin')"
```

### List all trusted plugins

```bash
python -c "from senpy.plugins.security import get_trusted_plugins; print(get_trusted_plugins())"
# Output: ['my-senpy-plugin', 'another-plugin']
```

### Trust store location

- Default: `~/.senpy/trusted_plugins.json`
- Override with env var: `SENPY_HOME=/custom/path senpy ...` →
  `/custom/path/trusted_plugins.json`

### Why trust-on-first-use?

Plugins run with full Senpy process privileges — they can read any
file Senpy can read, execute arbitrary Python code in their
`check()`, and write anywhere the Senpy process can write.

Trust-on-first-use is the standard security model for plugin
systems that don't sandbox (like VS Code extensions, Neovim plugins,
etc.). The first run is interactive (TTY required); subsequent
runs are silent. CI environments (no TTY) auto-skip untrusted
plugins — fail-safe.

---

## Plugin API reference

### `RuleMeta` fields

| Field | Type | Required | Description |
|---|---|---|---|
| `code` | `str` | ✅ | Rule code, must match `RPY\d{3}` pattern (e.g. `"RPY901"`) |
| `docs` | `str` | ✅ | Human-readable description of what the rule detects |
| `severity` | `str` | ✅ | One of: `"ERROR"`, `"WARNING"`, `"HINT"`, `"INFO"` |
| `fixable` | `bool` | ❌ | `True` if rule provides `fix_replacement` in Diagnostics (default: `False`) |
| `tags` | `list[str]` | ❌ | Tags for filtering (e.g. `["performance", "translations"]`) |
| `deprecated` | `bool` | ❌ | `True` if rule is deprecated (default: `False`) |
| `replaced_by` | `str \| None` | ❌ | Code of replacement rule (default: `None`) |
| `schema` | `dict \| None` | ❌ | JSON schema for rule config (default: `None`) |

### `RuleContext` fields

| Field | Type | Description |
|---|---|---|
| `file_path` | `str` | Path to `.rpy` file being analyzed |
| `lines` | `list[str]` | Raw lines (with newlines) from the file |
| `symbols` | `dict` | Project symbols: `{"labels": {...}, "screens": {...}, "variables": {...}, ...}` |
| `analyzer` | `Any` | SenpyAnalyzer instance (for advanced queries, optional) |
| `config` | `dict \| None` | Rule-specific config from `senpy.toml` (optional) |

### `Diagnostic` fields (what `check()` returns)

| Field | Type | Required | Description |
|---|---|---|---|
| `file_path` | `str` | ✅ | Path to file with the issue |
| `line_number` | `int` | ✅ | 1-based line number |
| `line_content` | `str` | ✅ | The raw line text (for display) |
| `code` | `str` | ✅ | Rule code (matches `RuleMeta.code`) |
| `message` | `str` | ✅ | Human-readable description of the issue |
| `severity` | `str \| None` | ❌ | Override per-diagnostic (default: from `RuleMeta`) |
| `col` | `int` | ❌ | 0-based start column (UTF-16, for LSP) |
| `end_col` | `int` | ❌ | 0-based end column |
| `fix_title` | `str \| None` | ❌ | QuickFix title shown in IDE |
| `fix_replacement` | `str \| None` | ❌ | Text to replace (only if `fixable=True`) |
| `fix_start_col` | `int \| None` | ❌ | QuickFix range start |
| `fix_end_col` | `int \| None` | ❌ | QuickFix range end |

---

## Example: rule with QuickFix

If your rule can auto-fix the issue, set `fixable=True` and provide
fix fields:

```python
@register_rule("RPY903")
class FixSmartQuotesRule(Rule):
    """Replaces smart quotes in code statements with straight quotes."""

    meta = RuleMeta(
        code="RPY903",
        docs="Smart quotes (U+201C/D) in code → straight quotes",
        severity="ERROR",
        fixable=True,  # ← enables QuickFix in VS Code (Ctrl+.)
        tags=["syntax"],
    )

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        diags: list[Diagnostic] = []

        for line_idx, raw_line in enumerate(ctx.lines, start=1):
            stripped = raw_line.lstrip(" \t")
            if not stripped or stripped[0] in ('"', "'"):
                continue  # dialogue — skip

            for i, ch in enumerate(raw_line):
                if ch in "\u201c\u201d":  # " "
                    diags.append(
                        Diagnostic(
                            file_path=ctx.file_path,
                            line_number=line_idx,
                            line_content=raw_line.rstrip("\n\r"),
                            code="RPY903",
                            message=f"Smart quote '{ch}' in code — use straight quote instead",
                            severity="ERROR",
                            col=i,
                            end_col=i + 1,
                            fix_title='Replace with straight quote (")',
                            fix_replacement='"',
                            fix_start_col=i,
                            fix_end_col=i + 1,
                        )
                    )

        return diags
```

In VS Code, users press `Ctrl+.` on the diagnostic → QuickFix applies
`fix_replacement`.

---

## Example plugins shipped with Senpy

The repository ships two complete example plugins in `examples/`:

### `my_senpy_plugin` — RPY901: hardcoded dialogue

Flags dialogue lines not wrapped in `_()` for translation.

```renpy
# Bad (RPY901 fires)
label start:
    "Hello, world!"

# Good
label start:
    _("Hello, world!")
```

Severity: `WARNING`. Tags: `translations`, `accessibility`.

Source: [`examples/my_senpy_plugin/`](https://github.com/Xilleet/senpy/blob/main/examples/my_senpy_plugin/)

### `todo_comment_plugin` — RPY902: TODO comments

Flags `# TODO:`, `# FIXME:`, `# XXX:`, and `# HACK:` comments left in
Ren'Py source files.

```renpy
# Bad (RPY902 fires — HINT severity, just a reminder)
label start:
    # TODO: implement the bad ending path
    # FIXME: this crashes on rollback
    "Hello, world!"
```

Severity: `HINT` (suppressed in `--errors-only` mode). Tags:
`productivity`, `dead-code`.

The match is case-insensitive and respects word boundaries, so
`# todolist` (no space) does NOT fire, but `# TODO:` does.

Source: [`examples/todo_comment_plugin/`](https://github.com/Xilleet/senpy/blob/main/examples/todo_comment_plugin/)

---

## Step-by-step: write your own plugin

### Step 1: Create project structure

```
my-plugin/
├── pyproject.toml
├── README.md
└── my_plugin/                  # Python package (matches name in pyproject.toml)
    ├── __init__.py
    └── rules.py
```

### Step 2: `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "my-plugin"              # pip name (with hyphens)
version = "0.1.0"
description = "My custom Senpy rules"
requires-python = ">=3.11"
dependencies = [
    "senpy-linter>=0.6.0",
]

[project.entry-points."senpy.plugins"]
my-plugin = "my_plugin.rules:MyRule"

[tool.setuptools.packages.find]
include = ["my_plugin*"]
```

### Step 3: `my_plugin/rules.py`

```python
"""My custom Senpy rules."""

from __future__ import annotations

from senpy.api import Diagnostic
from senpy.plugins import Rule, RuleContext, RuleMeta, register_rule

PLUGIN_API_VERSION = "1.0"


@register_rule("RPY902")  # code must match RuleMeta.code
class MyRule(Rule):
    """Detects TODO comments in .rpy files."""

    meta = RuleMeta(
        code="RPY902",
        docs="Detects TODO comments left in code",
        severity="HINT",
        fixable=False,
        tags=["productivity"],
    )

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        diags: list[Diagnostic] = []

        for line_idx, raw_line in enumerate(ctx.lines, start=1):
            stripped = raw_line.strip()
            if stripped.startswith("#") and "TODO" in stripped.upper():
                diags.append(
                    Diagnostic(
                        file_path=ctx.file_path,
                        line_number=line_idx,
                        line_content=raw_line.rstrip("\n\r"),
                        code="RPY902",
                        message=f"TODO comment: {stripped}",
                        severity="HINT",
                    )
                )

        return diags
```

### Step 4: Install + test

```bash
cd my-plugin/
pip install -e .

# Run Senpy — you'll get the trust prompt
senpy /path/to/game
```

Or pre-trust:

```bash
senpy --trust-plugin my-plugin
senpy /path/to/game
```

---

## Testing your plugin

Create `tests/test_my_rule.py` in your plugin project:

```python
"""Tests for my_plugin.rules.MyRule."""

from my_plugin.rules import MyRule
from senpy.plugins.base import RuleContext
from senpy.api import Diagnostic


def test_rule_detects_todo():
    rule = MyRule()
    ctx = RuleContext(
        file_path="test.rpy",
        lines=[
            "label start:\n",
            "    # TODO: implement this\n",  # flagged
            '    "Hi"\n',
            "    return\n",
        ],
        symbols={},
    )
    diags = rule.check(ctx)

    assert len(diags) == 1
    assert diags[0].code == "RPY902"
    assert diags[0].line_number == 2


def test_rule_no_false_positives():
    rule = MyRule()
    ctx = RuleContext(
        file_path="test.rpy",
        lines=['    "Not a TODO, just dialogue"\n'],
        symbols={},
    )
    diags = rule.check(ctx)
    assert diags == []
```

Run with pytest:

```bash
pytest tests/
```

---

## Publishing to PyPI

When your plugin is ready, publish it so others can `pip install` it:

```bash
# 1. Build distribution
python -m build

# 2. Upload to PyPI
twine upload dist/*

# 3. Others can now install it
pip install my-senpy-plugin
```

After publishing, when a user runs `senpy`, your plugin is
auto-discovered and they'll get the trust prompt.

---

## Debugging: why isn't my plugin loading?

### Check 1: Is the plugin installed?

```bash
pip list | grep my-plugin
# Should show: my-plugin  0.1.0
```

### Check 2: Is the entry point registered?

```bash
python -c "
from importlib.metadata import entry_points
eps = entry_points(group='senpy.plugins')
for ep in eps:
    print(f'{ep.name} → {ep.value}')
"
# Should show: my-plugin → my_plugin.rules:MyRule
```

### Check 3: Is the plugin trusted?

```bash
python -c "from senpy.plugins.security import is_plugin_trusted; print(is_plugin_trusted('my-plugin'))"
# False → plugin will be skipped in non-interactive mode
# Trust it: senpy --trust-plugin my-plugin
```

### Check 4: API version compatible?

```bash
python -c "
from my_plugin.rules import PLUGIN_API_VERSION
from senpy.plugins.security import check_api_version, PLUGIN_API_VERSION as senpy_ver
print(f'Plugin: {PLUGIN_API_VERSION}')
print(f'Senpy:   {senpy_ver}')
print(f'Compatible: {check_api_version(PLUGIN_API_VERSION)}')
"
```

### Check 5: Does the Rule subclass load?

```bash
python -c "
from my_plugin.rules import MyRule
print(f'Class: {MyRule}')
print(f'Meta:  {MyRule.meta}')
print(f'Code:  {MyRule.meta.code}')
"
```

If any of these fail, that's your problem. Fix it, reinstall with
`pip install -e .`, retry.

---

## Common pitfalls

1. **Hyphen vs underscore**: `pip install my-senpy-plugin` (hyphen)
   but `import my_senpy_plugin` (underscore). This is standard Python
   convention — package names use hyphens for PyPI, underscores for
   imports.

2. **`PLUGIN_API_VERSION` must be a class attribute**, not instance:
   ```python
   # CORRECT
   class MyRule(Rule):
       PLUGIN_API_VERSION = "1.0"  # ← class-level


   # WRONG (won't be detected)
   class MyRule(Rule):
       def __init__(self):
           self.PLUGIN_API_VERSION = "1.0"  # ← instance-level, too late
   ```

3. **`RuleMeta.code` must match `@register_rule(code)`**:
   ```python
   # CORRECT
   @register_rule("RPY901")
   class MyRule(Rule):
       meta = RuleMeta(code="RPY901", ...)  # ← same code

   # WRONG (silent mismatch)
   @register_rule("RPY901")
   class MyRule(Rule):
       meta = RuleMeta(code="RPY902", ...)  # ← different code
   ```

4. **Don't catch all exceptions in `check()`** — let Senpy handle
   isolation. If your rule throws, Senpy logs the error and skips
   your rule for that file, but other rules continue.

5. **`check()` must return `list[Diagnostic]`, not `None`**:
   ```python
   # CORRECT
   def check(self, ctx):
       return []  # empty list if no issues


   # WRONG (will crash Senpy)
   def check(self, ctx):
       if not issues:
           return None  # ← use []
   ```

6. **Use the RPY9xx range for plugin codes** — built-in rules use
   RPY0xx–RPY8xx. RPY9xx is reserved for plugins, so your codes
   won't clash with future built-in rules.

---

## What's next?

- [**All 52 rules**](rules/index.md) — built-in rule reference.
- [**Configuration**](configuration.md) — `senpy.toml`, `--tag` filter
  for plugin rules.
- [**CLI reference**](cli-reference.md) — `--trust-plugin`,
  `--untrust-plugin`, `senpy rule list`.
- [**Source: example plugins**](https://github.com/Xilleet/senpy/tree/main/examples)
  — `my_senpy_plugin` and `todo_comment_plugin`.
