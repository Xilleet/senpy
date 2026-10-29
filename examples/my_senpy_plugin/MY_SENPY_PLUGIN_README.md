# my_senpy_plugin — Example Senpy Plugin

Minimal working example of a Senpy lint plugin. Use it as a template for your own plugins.

This plugin defines **one rule**: `RPY901` — flags dialogue lines not wrapped in `_()` for translation.

```renpy
# Bad (RPY901 fires)
label start:
    "Hello, world!"

# Good
label start:
    _("Hello, world!")
```

---

## Installation

### From source (development mode)

```bash
cd examples/my_senpy_plugin
pip install -e .
```

After this, Senpy will discover the plugin automatically on next run.

### From PyPI (when published)

```bash
pip install my-senpy-plugin
```

### Verify installation

```bash
python -c "from my_senpy_plugin.rules import HardcodedDialogueRule; print(HardcodedDialogueRule)"
# Output: <class 'my_senpy_plugin.rules.HardcodedDialogueRule'>
```

---

## First-time loading: trust prompt

When Senpy first discovers a plugin (any plugin, not just this one), it asks for trust:

```
[senpy] Plugin 'my-senpy-plugin' wants to load. Trust and enable? [y/N]:
```

| Answer | Result |
|---|---|
| `y` or `yes` | Plugin is **trusted**, added to `~/.senpy/trusted_plugins.json`, loads now and on every future run |
| `n`, Enter, or anything else | Plugin is **skipped** for this run |
| Non-interactive (CI, no TTY) | All untrusted plugins are **skipped** (fail-safe) |

### Pre-trust without prompt (for CI / automation)

```bash
# Trust explicitly before running Senpy
python -c "from senpy.plugins.security import trust_plugin; trust_plugin('my-senpy-plugin')"

# Now CI runs won't prompt — plugin loads silently
senpy /path/to/game
```

### Revoke trust

```bash
python -c "from senpy.plugins.security import untrust_plugin; untrust_plugin('my-senpy-plugin')"
```

### List all trusted plugins

```bash
python -c "from senpy.plugins.security import get_trusted_plugins; print(get_trusted_plugins())"
# Output: ['my-senpy-plugin', 'another-plugin']
```

### Trust store location

- Default: `~/.senpy/trusted_plugins.json`
- Override with env var: `SENPY_HOME=/custom/path senpy ...` → `/custom/path/trusted_plugins.json`

---

## Writing your own plugin

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

# THIS IS THE MAGIC LINE — Senpy finds your plugin via this entry point.
# Format: <plugin-name> = "<package.module>:<ClassName>"
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

# Declare which Senpy plugin API version this plugin targets.
# If Senpy's API is incompatible, the plugin is skipped with a warning
# (not crashed). Bump this only when you adopt new Senpy API features.
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
                diags.append(Diagnostic(
                    file_path=ctx.file_path,
                    line_number=line_idx,
                    line_content=raw_line.rstrip("\n\r"),
                    code="RPY902",
                    message=f"TODO comment: {stripped}",
                    severity="HINT",
                ))

        return diags
```

### Step 4: Install + test

```bash
cd my-plugin/
pip install -e .

# Run Senpy — you'll get the trust prompt
senpy /path/to/game
```

---

## Rule API reference (cheat sheet)

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

If your rule can auto-fix the issue, set `fixable=True` and provide fix fields:

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
            # Find smart quotes in code lines (not dialogue)
            stripped = raw_line.lstrip(" \t")
            if not stripped or stripped[0] in ('"', "'"):
                continue  # dialogue — skip

            for i, ch in enumerate(raw_line):
                if ch in "\u201c\u201d":  # " "
                    diags.append(Diagnostic(
                        file_path=ctx.file_path,
                        line_number=line_idx,
                        line_content=raw_line.rstrip("\n\r"),
                        code="RPY903",
                        message=f"Smart quote '{ch}' in code — use straight quote instead",
                        severity="ERROR",
                        col=i,
                        end_col=i + 1,
                        fix_title="Replace with straight quote (\")",
                        fix_replacement='"',
                        fix_start_col=i,
                        fix_end_col=i + 1,
                    ))

        return diags
```

In VS Code, users press `Ctrl+.` on the diagnostic → QuickFix applies `fix_replacement`.

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
            'label start:\n',
            '    # TODO: implement this\n',      # flagged
            '    "Hi"\n',                          # not flagged
            '    return\n',
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

After publishing, when a user runs `senpy`, your plugin is auto-discovered and they'll get the trust prompt.

---

## 🔍 Debugging: why isn't my plugin loading?

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
# Trust it: python -c "from senpy.plugins.security import trust_plugin; trust_plugin('my-plugin')"
```

### Check 4: API version compatible?

```python
python -c "
from my_plugin.rules import PLUGIN_API_VERSION
from senpy.plugins.security import check_api_version, PLUGIN_API_VERSION as senpy_ver
print(f'Plugin: {PLUGIN_API_VERSION}')
print(f'Senpy:   {senpy_ver}')
print(f'Compatible: {check_api_version(PLUGIN_API_VERSION)}')
"
```

### Check 5: Does the Rule subclass load?

```python
python -c "
from my_plugin.rules import MyRule
print(f'Class: {MyRule}')
print(f'Meta:  {MyRule.meta}')
print(f'Code:  {MyRule.meta.code}')
"
```

If any of these fail, that's your problem. Fix it, reinstall with `pip install -e .`, retry.

---

## Files in this example

| File | Purpose |
|---|---|
| `pyproject.toml` | Package metadata + `[project.entry-points."senpy.plugins"]` declaration |
| `MY_SENPY_PLUGIN_README.md` | This file — documentation |
| `my_senpy_plugin/__init__.py` | Package marker (empty except docstring) |
| `my_senpy_plugin/rules.py` | `HardcodedDialogueRule` (RPY901) implementation |

---

## Common pitfalls

1. **Hyphen vs underscore**: `pip install my-senpy-plugin` (hyphen) but `import my_senpy_plugin` (underscore). This is standard Python convention — package names use hyphens for PyPI, underscores for imports.

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

4. **Don't catch all exceptions in `check()`** — let Senpy handle isolation. If your rule throws, Senpy logs the error and skips your rule for that file, but other rules continue.

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
