<!-- Thanks for contributing to Senpy! Please review the CONTRIBUTING.md first. -->

## Summary

<!-- One or two sentences: what does this PR do? -->

## Type of change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Refactor (no functional change)
- [ ] Performance improvement
- [ ] Security fix
- [ ] Test improvement

## Backlog reference

<!-- If this PR closes an issue or implements a backlog item, link it. -->

- Closes #
- Backlog ID (e.g. `LSP-19`, `SEC-6`):

## Changes

<!-- List the main changes. Bullet points, one logical change per bullet. -->

-

## TDD

- [ ] Tests written **before** implementation (RED)
- [ ] Implementation written to make tests pass (GREEN)
- [ ] Code cleaned up without changing behavior (REFACTOR)
- [ ] All tests pass locally: `pytest tests/`
- [ ] No regressions in existing tests

## Checklist

- [ ] Code follows existing style in the file(s) I touched
- [ ] No `print()` statements left in code (use `logger` from `senpy.core.logging`)
- [ ] `RULES.md` updated if I added/changed a rule
- [ ] `CHANGELOG.md` has an entry under `[Unreleased]`
- [ ] If I touched `senpy.spec` or `pyproject.toml` — verified `python -m build` works
- [ ] If I touched `senpy-vscode/` — verified `npm run compile` works
- [ ] Commit messages follow Conventional Commits (`feat:`, `fix:`, `docs:`, etc.)
- [ ] One PR = one logical change (split if needed)

## Notes for reviewer

<!-- Anything the reviewer should pay extra attention to?
     - Risky areas touched?
     - Performance implications?
     - Backward compatibility concerns?
-->

## Smoke test (if applicable)

<!-- For CLI changes: paste output of `senpy test_game --no-cache` before and after.
     For LSP changes: describe manual testing steps in VS Code.
     For formatter changes: paste before/after of a sample .rpy file.
-->

```
Paste output / before-after here.
```
