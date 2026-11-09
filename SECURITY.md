# Security Policy

## Supported Versions

Senpy is in active development (currently 0.9.x). Security fixes are applied
to the latest released minor version only.

| Version | Supported          |
| ------- | ------------------ |
| 0.9.x   | ✅ Active support  |
| 0.8.x   | ⚠️ Critical fixes only |
| 0.7.x   | ❌ Not supported   |
| < 0.6   | ❌ Not supported   |

## Reporting a Vulnerability

**Please DO NOT open public GitHub issues for security vulnerabilities.**

Instead, report privately via one of these channels:

### GitHub Private Vulnerability Reporting (preferred)

1. Go to <https://github.com/Xilleet/senpy/security/advisories/new>
2. Fill in the form:
   - **Title**: short summary (e.g. "Path traversal in unrpyc decompiler")
   - **Description**: what the vulnerability is, what component is affected
   - **Steps to reproduce**: minimal PoC (code snippet, .rpy file, command line)
   - **Impact**: what an attacker can achieve
   - **Severity**: your assessment (low / medium / high / critical)
3. Submit. The maintainer will be notified privately.

## Response Timeline

| Step | Target |
| ---- | ------ |
| Acknowledgment of receipt | 48 hours |
| Initial assessment (severity + scope) | 7 days |
| Fix or mitigation | 30 days (severity-dependent) |
| Public disclosure | After fix released, or 90 days from report (whichever is earlier) |

The maintainer is one person; please be patient. You will be credited in the
advisory unless you request otherwise.

## Scope

### In scope

- The `senpy/` Python package (CLI, LSP server, analyzer, formatter, plugins system).
- The `senpy-vscode/` VS Code extension.
- The vendored `senpy/vendor/unrpyc/` — but please also report upstream to
  <https://github.com/CensoredUsername/unrpyc> if the issue exists there.
- The bundled `senpy.exe` PyInstaller binary distributed via GitHub Releases.

### Out of scope

- Vulnerabilities in Ren'Py itself — report to <https://github.com/renpy/renpy>.
- Vulnerabilities in third-party plugins installed via `pip` — report to the
  plugin author. Senpy's trust-on-first-use model (see
  `examples/my_senpy_plugin/MY_SENPY_PLUGIN_README.md`) is the primary
  mitigation; plugins run with full Senpy process privileges.
- Social engineering, DoS via huge input files, or issues requiring physical
  access to the user's machine.

## Known Security Features

Senpy has several built-in defenses; please familiarize yourself before
reporting:

- **`SafeUnpickler` with module blocklist** (`senpy/vendor/unrpyc/`):
  `.rpyc` files are pickle-based; Senpy's unpickler rejects dangerous modules
  (`os`, `sys`, `subprocess`, `socket`, `shutil`, `pathlib`, `builtins`,
  `ctypes`, `multiprocessing`, `pickle`, `marshal`) even if added to the
  safe-list by accident. See `tests/test_cache_security.py`,
  `tests/test_lsp_uri_security.py`, `tests/test_unrpyc_security.py`,
  `tests/test_vendored_unrpyc.py`.
- **`UNRPYC_PINNED_SHA256`** (`senpy/cli/unrpyc.py`): downloaded unrpyc zip
  is verified against a pinned SHA256 hash. Prevents supply-chain attacks
  on the unrpyc download endpoint.
- **Plugin trust store** (`~/.senpy/trusted_plugins.json`):
  trust-on-first-use model. CI environments (non-TTY) auto-skip untrusted
  plugins (fail-safe). The trust check runs **before** `entry_point.load()`
  — a declined plugin's top-level Python code (`__init__.py`, `rules.py`,
  `@register_rule` decorators, class body) never executes. This means
  `@register_rule` import-time side effects do not mutate
  `_REGISTERED_LINT_RULES` when trust is declined, and a malicious
  plugin cannot run arbitrary code at load time. Plugin authors should
  not rely on import-time side effects for trust-gated behaviour.
- **HTML report CSP** (`senpy/formats/html_report.py`):
  `Content-Security-Policy: default-src 'self'; script-src 'self'
  'unsafe-inline' https://cdn.jsdelivr.net/npm/mermaid@10/
  https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/; style-src 'self'
  'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src
  'self'` + Mermaid `securityLevel: 'strict'`. Diagnostics' `code`,
  `severity`, `message`, `line_content` and `file_path` are HTML-escaped
  before interpolation (since 0.7.7) — prevents XSS from plugin rule
  metadata in generated reports.
  > **Known limitation:** `script-src` includes `'unsafe-inline'` to
  > support Mermaid's runtime initialization (which evaluates an inline
  > script). A nonce-based CSP is planned post-0.8 to remove this. The
  > Mermaid `securityLevel: 'strict'` setting and the HTML-escaping of
  > all diagnostic fields mitigate the inline-script risk in the
  > meantime.
- **LSP URI scheme validation + workspace containment** (`senpy/lsp/server.py`,
  0.6.2): `_uri_to_path` rejects non-`file:` URIs and (optionally)
  paths outside workspace root.
- **`execFile` instead of `exec`** (`senpy-vscode/src/extension.ts`,
  0.6.2): VS Code extension uses array-args `child_process.execFile`,
  preventing shell injection via workspace paths.
- **`os.walk(followlinks=False)`** (0.6.2): explicit symlink-loop
  protection in all filesystem walks.

## Hardening Checklist for Plugin Authors

If you write a Senpy plugin, follow these guidelines:

1. **Never `exec()` or `eval()` user input.** Ren'Py source files are
   untrusted input.
2. **No `subprocess.run()` from a plugin.** If you need external tools,
   require them as separate dependencies and document the security model.
3. **No network calls.** Plugins should be deterministic and offline.
4. **No file writes outside the project directory.** Use Senpy's
   `DiagnosticSink` API, not direct file I/O.
5. **Pin your dependencies.** A plugin is only as secure as its deps.

## No Plugin Sandbox Exists

Senpy does **not** run plugins in a sandbox. Once a plugin is loaded
(via `entry_point.load()`), it executes with the full privileges of the
Senpy process — same filesystem, network, and subprocess access as the
linter itself. The "Hardening Checklist" above is **advisory**, not
enforced: nothing in the runtime prevents a plugin from `subprocess.run`,
`socket`, `open(file, "w")`, or `os.system`.

The only enforcement layer is the **trust store** (`~/.senpy/trusted_plugins.json`)
— a plugin is loaded only after explicit user approval (or auto-skipped in
non-TTY CI environments). Users are responsible for vetting plugins
before trusting them, the same way they vet any `pip install` dependency.

A proper plugin sandbox (subinterpreters, restricted execution,
capability-based I/O) is **out of scope** for 0.8.0 and is tracked as a
post-0.8 R&D item. The current model is "trust first, run with full
privileges" — same as pytest plugins, ruff plugins, or any other
in-process plugin system.

## Disclosure Policy

- We follow **Coordinated Disclosure**. The reporter and maintainer agree on
  a disclosure timeline before public release.
- CVE numbers can be requested via GitHub Security Advisories.
- Credit is given in the release notes and the advisory, unless the reporter
  requests anonymity.

## Contact

- Security advisories: <https://github.com/Xilleet/senpy/security/advisories>
- General questions (non-sensitive): <https://github.com/Xilleet/senpy/discussions>
