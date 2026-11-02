# Contributing to Senpy

First of all: **thank you** for considering a contribution. Senpy is a
one-maintainer project, so every bug report, fix, rule, and doc improvement
matters.

This document covers:

- [Quick start](#quick-start)
- [Good first issues](#good-first-issues) — where to start if you want to help
- [Solo-maintainer expectations](#solo-maintainer-expectations) — read this before opening a PR
- [Project layout](#project-layout)
- [How to add a new lint rule](#how-to-add-a-new-lint-rule)
- [How to add a new formatter rule](#how-to-add-a-new-formatter-rule)
- [Testing](#testing)
- [Commit style and pull requests](#commit-style-and-pull-requests)
- [Releases](#releases)
- [Code of conduct](#code-of-conduct)

---

## Good first issues

If you want to contribute but don't know where to start, here is a list of
**low-risk, well-scoped** tasks that are genuinely useful and won't require
deep knowledge of the analyzer internals. Pick one, leave a comment on the
relevant issue (or open one if it doesn't exist), and we'll guide you.

### Rules — fixture coverage

Senpy has 40+ rules, but only 23 have fixture tests. Picking a rule and adding
fixture coverage is the single most valuable contribution a newcomer can
make — it directly improves the test suite and forces you to understand one
rule end-to-end.

| Rule | What it catches | Fixture status |
| ---- | --------------- | -------------- |
| RPY201 | Predictive state mutation in screen | missing |
| RPY202 | SetVariable leak via screen action | missing |
| RPY203 | Dead button (no `action`) | missing |
| RPY205 | Imperative `for`/`while` loop in screen | missing |
| RPY301 | Unclosed text tag | partial |
| RPY401 | Menu branch asymmetry | partial |
| RPY403 | Logical contradiction | missing |
| RPY404 | Reading a MAYBE_SET variable | partial |
| RPY502 | Unresolved sprite / transform / transition | partial |
| RPY505 | Invalid audio channel | partial |

To add fixtures for, say, `RPY401`:

1. Create `tests/fixtures/rules/RPY401/bad_branch.rpy` with a code sample that
   triggers the rule.
2. Create `tests/fixtures/rules/RPY401/bad_branch.json` with the expected
   diagnostics (look at any existing `bad_*.json` for the format).
3. Create `tests/fixtures/rules/RPY401/good_branch.rpy` with a code sample
   that does NOT trigger the rule.
4. Run `pytest tests/test_fixtures.py -k RPY401 -v` — if it passes, you're done.

### Docs — typo / clarity fixes

If you spot a typo, awkward phrasing, or unclear explanation in `README.md`,
`README_ru.md`, `RULES.md`, `ARCHITECTURE.md`, or `SECURITY.md` — just open
a PR. These are merged fast and don't need an issue first.

### Examples — new example .rpy files

The `examples/` directory currently has the plugin example and a formatter
demo. Useful additions:

- A minimal `.rpy` showing each rule category (RPY0xx, RPY1xx, RPY2xx, ...)
  with comments explaining what each rule catches.
- A "before/after" `.rpy` showing what `senpy format` does.

### Plugin rules (advanced but self-contained)

If you have a domain-specific check (e.g. "flag all dialogue lines not wrapped
in `_()`", or "flag use of `renpy.music.play` with `.mp3` instead of `.ogg`")
— write it as a plugin, not a core rule. See
[`examples/my_senpy_plugin/`](examples/my_senpy_plugin/) for a working
template. Plugin rules don't need any changes to the Senpy core.

---

## Solo-maintainer expectations

**Senpy is a one-maintainer project.** This section sets realistic
expectations so you don't get frustrated and the maintainer doesn't burn
out.

### Review time

- Bug reports and feature requests: **acknowledged within ~1 week**.
- Small PRs (typo, fixture, doc fix): **reviewed within 1–2 weeks**.
- Larger PRs (new rule, refactoring, LSP handler change): **2–4 weeks**,
  sometimes longer. The maintainer reviews every line of every PR and runs
  the change against real Ren'Py projects before merging.

If a PR sits for longer than that, please **ping with a comment** — the
maintainer sometimes loses notifications. Do not open a duplicate PR.

### What gets merged fast

- TDD-style PRs with fixtures (the test file *is* the spec).
- Single-purpose PRs (one rule, one fix, one doc section).
- PRs that follow the existing code style (me don't enforce `ruff format`,
  but match the file you're editing).
- PRs that update `CHANGELOG.md` under `[Unreleased]`.

### What gets rejected or stalled

- PRs without tests (the maintainer will ask for them).
- PRs that mix unrelated changes (a bug fix + a new feature + a refactor).
- PRs that break the existing `DiagnosticSink` Protocol contract or
  introduce import cycles (run `python scripts/check_cycles.py` locally).
- PRs that introduce security-sensitive code (pickle, subprocess, eval,
  network) without a clear justification and a security test.

### "Good enough" is good enough

The maintainer would rather merge a PR that solves a problem on 80% of
cases and is easy to read than spend three rounds of review pushing for a
"perfect" 100%. If your PR has minor style issues, the maintainer may
**fix them after merge** rather than blocking the PR. Don't be offended —
that's faster for everyone.

### Plugins are the delegation path

If you want a feature that doesn't fit any existing rule domain, or that
only makes sense for your specific Ren'Py project — **write it as a plugin,
not a core rule**. The plugin system exists exactly for this. Plugin rules:

- Don't need maintainer review to be useful (you can use them in your own
  project immediately).
- Don't risk breaking the Senpy core if they have a bug.
- Don't add to the maintainer's review burden.

See `examples/my_senpy_plugin/` and
[Plugin Development README](examples/my_senpy_plugin/MY_SENPY_PLUGIN_README.md)
for a working template.

---

## Quick start

```bash
# 1. Clone
git clone https://github.com/Xilleet/senpy.git
cd senpy

# 2. Install in editable mode with dev dependencies
pip install -e .

# 3. Run tests to confirm setup
pytest tests/

# 4. Try the CLI
senpy test_game --no-cache

# 5. Try the LSP (optional, needs VS Code)
# Open the `senpy-vscode/` folder in VS Code, press F5 to launch Extension Development Host.
```

Requirements:

- Python 3.11+
- Node.js 20+ (only if you touch the VS Code extension)
- PyInstaller (only for release builds; not needed for development)

---

## Project layout

```
senpy/
├── senpy/                       # Main Python package
│   ├── api.py                   # Public stable API: analyze_code, Diagnostic, ...
│   ├── __version__.py           # Single source of truth for version
│   ├── cli/                     # Command-line interface
│   │   ├── main.py              # argparse + dispatch (WARNING: 1163 lines, god-module)
│   │   ├── commands.py          # Per-subcommand implementations
│   │   └── unrpyc.py            # .rpyc decompilation via vendored unrpyc
│   ├── core/                    # Core analysis engine
│   │   ├── analyzer.py          # SenpyAnalyzer — the heart (1817 lines, god-module)
│   │   ├── cache.py             # Two-tier disk cache
│   │   ├── config.py            # load_config() — reads senpy.toml
│   │   ├── logging.py           # setup_logging(), get_logger() — centralized logging
│   │   ├── models.py            # Diagnostic, RULE_SEVERITY, etc.
│   │   ├── scope.py             # Variable scope tracking
│   │   ├── signature.py         # Call signature inference
│   │   ├── sink.py              # DiagnosticSink
│   │   ├── symbols.py           # VariableSymbol, LabelSymbol, ...
│   │   └── coverage.py          # Translation coverage metrics
│   ├── domain/                  # Ren'Py domain knowledge
│   │   ├── assets.py            # Asset cache (image files)
│   │   ├── rpa.py               # .rpa archive reading
│   │   ├── renpy_api.py         # Ren'Py built-in API definitions
│   │   ├── text_tags.py         # {b}, {i}, {color=...} parser
│   │   └── tsundere.py          # Easter egg banner :)
│   ├── rules/                   # Lint rules
│   │   ├── base.py              # Rule base class
│   │   ├── checkers/            # Per-domain checker modules
│   │   │   ├── state.py         # RPY1xx (state mutations)
│   │   │   ├── screen.py        # RPY2xx (screen UI)
│   │   │   ├── dialogue.py      # RPY3xx (dialogue/labels/jumps)
│   │   │   ├── flow.py          # RPY4xx (branch dataflow) + Mermaid builder
│   │   │   ├── formatting.py    # RPY0xx (style)
│   │   │   ├── asset.py         # RPY5xx (assets/transforms)
│   │   │   └── translation.py   # RPY6xx (translations) — TODO
│   │   ├── deprecated.py        # RPY107, RPY108, RPY109 (deprecated APIs)
│   │   ├── python_ast.py        # Python AST visitor for $-statements
│   │   ├── rules_info.py        # RULES_DATABASE, dynamic rule count
│   │   └── dead_code.py         # RPY701/702/703 — TODO
│   ├── formatter/               # Code formatter (like Black for Ren'Py)
│   │   ├── core.py              # register_rule decorator, Formatter class
│   │   └── rules/               # FMT-INDENT, FMT-QUOTES, etc.
│   ├── formats/                 # Output formats
│   │   ├── html_report.py       # HTML report with Mermaid graphs
│   │   ├── wiki.py              # Wiki export
│   │   ├── stats.py             # Story analytics
│   │   ├── sarif.py             # SARIF 2.1.0 for CI
│   │   ├── traceback.py         # Crash log parser
│   │   ├── ci.py                # JUnit XML, GitHub Actions annotations
│   │   └── stubs.py             # Format registry
│   ├── lsp/                     # LSP server
│   │   ├── server.py            # pygls LanguageServer setup
│   │   └── handlers/            # Per-LSP-method handlers
│   │       ├── completion.py    # textDocument/completion
│   │       ├── diagnostics.py   # textDocument/publishDiagnostics
│   │       ├── hover.py         # textDocument/hover
│   │       ├── navigation.py    # definition, references, rename, ...
│   │       ├── text_document.py # didOpen, didChange, didSave
│   │       └── workspace.py     # workspace/symbol, executeCommand
│   ├── plugins/                 # Plugin system
│   │   ├── base.py              # Rule base class with meta
│   │   ├── loader.py            # entry_points discovery + trust prompt
│   │   ├── registry.py          # @register_rule decorator
│   │   └── security.py          # API version check, trust store
│   └── vendor/                  # Vendored dependencies (do not modify directly)
│       └── unrpyc/              # .rpyc decompiler (pinned commit)
├── senpy-vscode/                # VS Code extension (TypeScript)
├── tests/                       # pytest test suite (700+ tests)
├── scripts/                     # Maintenance scripts
│   ├── check_cycles.py          # Import cycle detector
│   ├── update_renpy_api.py      # Regenerate renpy_api.py from Ren'Py source
│   └── update_unrpyc_pin.py     # Update pinned unrpyc SHA256
├── docs/                        # Documentation and images
├── examples/                    # Example plugin + demo scripts
├── test_game/                   # Tiny Ren'Py project for smoke tests
├── pyproject.toml               # Build + project metadata
├── senpy.toml                   # Default config
└── RULES.md                     # Per-rule documentation (auto-generated-ish)
```

---

## How to add a new lint rule

There are two ways: a **core rule** (in `senpy/rules/`) or a **plugin rule**
(distributed as a separate pip package). For core rules:

> **When to choose plugin over core?** If your rule only makes sense for a
> specific Ren'Py project (your visual novel, your mod), or if you're not
> sure whether the maintainer will accept it into core — **write it as a
> plugin first**. You can use it in your own project immediately, without
> waiting for review. If it turns out to be widely useful, you can later
> propose promoting it to core. See
> [`examples/my_senpy_plugin/`](examples/my_senpy_plugin/) for a template.


### 1. Pick a rule code

Rule codes follow a 3-digit prefix by domain:

| Prefix | Domain                  | Example file                |
| ------ | ----------------------- | --------------------------- |
| RPY0xx | Style / formatting      | `rules/checkers/formatting.py` |
| RPY1xx | State / Python execution | `rules/checkers/state.py`   |
| RPY2xx | Screens / UI            | `rules/checkers/screen.py`  |
| RPY3xx | Dialogue / labels / jumps | `rules/checkers/dialogue.py` |
| RPY4xx | Branch dataflow         | `rules/checkers/flow.py`    |
| RPY5xx | Assets / transforms     | `rules/checkers/asset.py`   |
| RPY6xx | Translations            | (TODO: `rules/checkers/translation.py`) |
| RPY7xx | Dead code               | `rules/dead_code.py`        |
| RPY8xx | Translation unused      | (TODO)                      |
| RPY9xx | Plugin-defined          | plugins                     |

Pick the next free number in the appropriate range. Look at
`senpy/core/models.py` `RULE_SEVERITY` for existing codes.

### 2. Register the rule severity

Edit `senpy/core/models.py`:

```python
RULE_SEVERITY: dict[str, str] = {
    ...
    "RPY705": "WARNING",  # your new rule
    ...
}
```

### 3. Write the checker logic

Add a function in the appropriate `rules/checkers/<domain>.py`. Most checkers
follow this pattern:

```python
def check_line(
    line: str,
    line_no: int,
    file_path: str,
    raw_lines: list[str],
    symbols: SymbolTable,
    sink: DiagnosticSink,
    config: dict,
) -> None:
    """RPY705: 'pass'-only label.

    A label that contains only a `pass` statement is dead code — it does
    nothing and can be removed.
    """
    # Detection logic here
    if is_pass_only_label(...):
        sink.add_diagnostic(
            code="RPY705",
            file_path=file_path,
            line_number=line_no,
            message="Label contains only 'pass' — remove or add real logic.",
            severity=RULE_SEVERITY["RPY705"],
        )
```

Wire it into the analyzer. Most checkers are called from
`core/analyzer.py:_analyze_file()`. Look at how an existing rule in the same
domain is invoked.

### 4. Add fixtures (TDD)

Create test fixtures under `tests/fixtures/rules/RPY705/`:

```
tests/fixtures/rules/RPY705/
├── bad_pass_only_label.rpy       # Example that triggers the rule
├── bad_pass_only_label.json      # Expected diagnostics
└── good_label_with_logic.rpy     # Example that does NOT trigger
```

The `.json` file format:

```json
[
  {
    "code": "RPY705",
    "line": 3,
    "message_fragment": "pass"
  }
]
```

Add a test in `tests/test_rules_rpy7xx.py` (or appropriate existing test file)
that loads the fixtures and asserts the diagnostics match. Run:

```bash
pytest tests/test_rules_rpy7xx.py -v
```

### 5. Document the rule

Add an entry to `RULES.md` under the appropriate section. Format:

```markdown
### RPY705 — Pass-only label

**Severity:** WARNING
**Quick fix:** None

A `label` whose body consists only of a `pass` statement is dead code.

#### Bad
```renpy
label empty_ending:
    pass
```

#### Good
```renpy
label empty_ending:
    $ persistent.seen_empty_ending = True
    return
```
```

### 6. Update dynamic rule count

If you added a new rule code, the rule count badge in README will auto-update
(via `rules_info.py` dynamic count). Verify:

```bash
python -c "from senpy.rules.rules_info import RULES_DATABASE; print(len(RULES_DATABASE))"
```

---

## How to add a new formatter rule

Formatter rules live in `senpy/formatter/rules/`. Each is a small module with
a `@register_rule` decorator:

```python
# senpy/formatter/rules/comment_align.py
from senpy.formatter.core import FormatterRule, register_rule


@register_rule("FMT-COMMENT-ALIGN")
class CommentAlignRule(FormatterRule):
    """Align inline comments with the surrounding code."""

    def apply(self, lines: list[str]) -> list[str]:
        # Your formatting logic
        return transformed_lines
```

Add idempotency tests in `tests/test_formatter_idempotency.py` — formatting
already-formatted code must produce zero changes.

---

## Testing

### Run the full suite

```bash
pytest tests/ -v
```

### Run with coverage

```bash
pytest tests/ --cov=senpy --cov-report=term-missing
```

The CI gate is 75%. Aim to not decrease it with your PR.

### TDD discipline

For bug fixes and new features, follow **RED → GREEN → REFACTOR**:

1. **RED**: Write a test that fails (reproduces the bug, or specifies the new behavior).
2. **GREEN**: Write the minimum code to make it pass.
3. **REFACTOR**: Clean up without changing behavior. Tests stay green.

Do not commit code without tests. The maintainer will ask for tests in code
review if missing.

### Property-based tests (advanced)

For parser/formatter/SSA, consider `hypothesis`-based tests. See
`tests/test_formatter_idempotency.py` for an example pattern.

### Testing the VS Code extension

```bash
cd senpy-vscode
npm install
npm run compile     # esbuild bundle
npm test            # existing tests in src/test/
```

For manual testing: open `senpy-vscode/` in VS Code, press `F5` to launch
Extension Development Host. Open a `.rpy` file and try hover, completions,
format-on-save.

---

## Commit style and pull requests

### Commit messages

Use the **Conventional Commits** format (without strict enforcement):

```
type(scope): short summary

Optional longer description.
```

Where `type` is one of: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`,
`perf`, `security`.

Examples:

```
feat(rules): add RPY705 — pass-only label detection

Closes #123. Adds a new dead-code rule that flags labels whose body
consists only of a `pass` statement.

Fixtures cover the basic case and a label with a docstring-only body.
```

```
security(lsp): validate file: scheme in _uri_to_path

Previously _uri_to_path accepted any URI scheme, including http: and
https:. A malicious LSP client could trick Senpy into making network
requests or reading unexpected paths.
```

### Pull request checklist

Before opening a PR:

- [ ] Tests added (TDD) and pass locally: `pytest tests/`
- [ ] No regressions in existing tests
- [ ] `RULES.md` updated if you added/changed a rule
- [ ] `CHANGELOG.md` has an entry under `[Unreleased]`
- [ ] Code follows existing style (we don't enforce ruff, but match the file you're editing)
- [ ] No `print()` statements left in code (use `logger` from `senpy.core.logging`)
- [ ] If you touched `senpy.spec` or `pyproject.toml` — verify `python -m build` works
- [ ] If you touched `senpy-vscode/` — verify `npm run compile` works
- [ ] Commit messages follow Conventional Commits

### Pull request template

See `.github/PULL_REQUEST_TEMPLATE.md` — it will auto-fill when you open a PR.

### Branch naming

- `feat/<short-description>` — new features
- `fix/<short-description>` — bug fixes
- `docs/<short-description>` — documentation only
- `release/vX.Y.Z` — release preparation

### One PR = one logical change

If you fixed a bug AND added a feature, that's two PRs. Split them. This
makes review faster and git history cleaner.

---

## Releases

**Releases are cut exclusively by the maintainer.** No contributor —
external or otherwise — can trigger a release. The release pipeline is
gated behind a `vX.Y.Z` git tag, and only the maintainer pushes tags.

### Why this matters

Senpy is a one-maintainer project. Releasing means publishing to PyPI
(where versions are immutable — you cannot re-upload the same version
number once published) and uploading a VSIX to GitHub Releases (where
users download it). A botched release cannot be silently rolled back.
Therefore the maintainer personally:

- decides when to release,
- bumps the version,
- writes the changelog,
- pushes the tag,
- verifies the published artifacts before announcing.

### What CI does automatically

- On every push to `main` or PR: runs `pytest` (ci.yml). Blocks merge if
  tests fail.
- On tag `v*.*.*` push: builds wheel + sdist + VSIX, runs smoke-test on
  `senpy.exe`, publishes to PyPI + GitHub Release (release.yml).

CI never publishes on its own — **the tag push is the trigger**, and only
the maintainer can push tags. Even a merged PR does not trigger a release;
only the maintainer's manual `git tag vX.Y.Z && git push origin vX.Y.Z` does.

### Release process (maintainer-only)

1. Confirm all tests green on `main`.
2. Update `senpy/__version__.py` (single source of truth) via
   `python bump_version.py <new-version>`.
3. Update `CHANGELOG.md` with the new version section.
4. Run `python -m build` locally to verify packaging works.
5. Commit: `git commit -am "release vX.Y.Z"`.
6. Tag: `git tag vX.Y.Z && git push origin main --tags`.
7. Watch the `release.yml` workflow in Actions tab. It runs:
   - tests (pre-release check),
   - build (wheel + sdist),
   - build-vsix (PyInstaller + smoke-test + vsce package),
   - publish-pypi (uploads to PyPI),
   - github-release (uploads VSIX + wheel to GitHub Releases).
8. Verify on PyPI (`https://pypi.org/project/senpy-linter/`) and on the
   GitHub Releases page that artifacts landed.
9. If anything went wrong: **PyPI versions are immutable** — you have to
   bump the patch version (e.g. 0.6.2 → 0.6.3) and re-release. Yanking is
   possible but does not remove the file from existing installs.

### What contributors can do

Contributors **cannot**:

- push tags (branch protection on `main` + tags),
- trigger release workflow manually (no `workflow_dispatch` on `release.yml`),
- publish to PyPI (only the maintainer's `PYPI_API_TOKEN` secret works),
- create GitHub Releases (requires `contents: write` permission, only
  the `github-actions` bot has it inside the workflow).

Contributors **can**:

- open PRs (which run CI but never trigger release),
- propose a release in a Discussion or Issue ("I think we should cut 0.6.3
  because X is fixed"),
- maintain their own fork with custom tags (irrelevant to upstream).

---

## Code of conduct

Be kind. Be patient. Assume good faith. The maintainer is one person doing
this in their free time.

### Be patient with review

The maintainer sometimes takes 1–4 weeks to review a PR (see
[Solo-maintainer expectations](#solo-maintainer-expectations)).
If your PR sits for longer than that,
**ping with a comment** instead of opening a duplicate.

### Don't aim for "perfect" — aim for "shipped"

The maintainer would rather merge a "good enough" PR today and improve it
in a follow-up than wait three months for a "perfect" one. If your PR has
rough edges, open it anyway and explain them in the description. The
maintainer will either merge as-is and fix the edges, or suggest a small
change list.

### Don't be precious about your code

Once a PR is merged, the code is **ours**. The maintainer (and
other future contributors) will refactor it, rename things, move it around.
This is normal and don't take it personally — your contribution is still
credited in the commit history and (if you want) in `CHANGELOG.md`.

### Security reports

If someone is being unkind in an issue or PR, email the maintainer
privately (see [SECURITY.md](SECURITY.md) for the channel). We will block
repeat offenders.

Security vulnerabilities are **not** reported via public GitHub Issues —
see [SECURITY.md](SECURITY.md) for the private reporting channel.

---

## Questions?

- **Bug reports / feature requests**: [GitHub Issues](https://github.com/Xilleet/senpy/issues)
- **General questions**: [GitHub Discussions](https://github.com/Xilleet/senpy/discussions)
- **Security**: see [SECURITY.md](SECURITY.md) — do NOT open public issues for security reports.

Thank you for contributing! 🐾
