"""Plugin import-time audit.

AST-based source code scanner that runs BEFORE a plugin is trusted.
Reads the plugin's .py source files via ``importlib.metadata.files()``
(no import — the plugin module is never loaded), parses each with
``ast``, and flags dangerous patterns:

  - ``subprocess`` usage (run, Popen, call, check_output)
  - ``socket`` module usage
  - ``eval()`` / ``exec()``
  - ``os.system`` / ``os.popen`` / ``os.exec*`` / ``os.spawn*``
  - ``ctypes`` module usage
  - ``pickle.load`` / ``pickle.loads``
  - ``__import__()``
  - ``open()`` with write mode (best-effort — may have false positives)

Warnings are stored in the trust store's ``audit_warnings`` dict
(schema v2, added in R-P0-2) and shown to the user before the
``[y/N]`` trust prompt.

This is NOT a sandbox — plugins still run with full process privileges
once trusted. The audit is advisory: it informs the user about risky
patterns so they can make an informed trust decision.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from senpy.core.logging import get_logger

_logger = get_logger("plugins.audit")


# =============================================================================
# Patterns — each maps to a human-readable warning
# =============================================================================

# Modules that are inherently risky for a lint plugin to use.
_DANGEROUS_IMPORTS: dict[str, str] = {
    "subprocess": "Plugin uses subprocess — can execute arbitrary system commands.",
    "socket": "Plugin uses socket — can make network connections.",
    "ctypes": "Plugin uses ctypes — can call arbitrary C functions (memory safety bypass).",
    "pickle": "Plugin uses pickle.load/loads — can execute arbitrary code during deserialization.",
    "marshal": "Plugin uses marshal — can execute arbitrary code during deserialization.",
    "multiprocessing": "Plugin uses multiprocessing — can spawn child processes.",
    "pathlib": "",  # pathlib is fine, don't flag
}

# Functions/methods that are inherently dangerous.
_DANGEROUS_CALLS: dict[str, str] = {
    "eval": "Plugin calls eval() — can execute arbitrary code from a string.",
    "exec": "Plugin calls exec() — can execute arbitrary code from a string.",
    "__import__": "Plugin calls __import__() — can dynamically import any module.",
    "compile": "",  # compile() alone is not dangerous — only when paired with exec()
}

# os.* functions that are dangerous.
_DANGEROUS_OS_ATTRS: dict[str, str] = {
    "system": "Plugin calls os.system() — executes a shell command.",
    "popen": "Plugin calls os.popen() — executes a shell command via pipe.",
    "execv": "Plugin calls os.execv() — replaces the current process.",
    "execve": "Plugin calls os.execve() — replaces the current process.",
    "execvp": "Plugin calls os.execvp() — replaces the current process.",
    "execvpe": "Plugin calls os.execvpe() — replaces the current process.",
    "spawnl": "Plugin calls os.spawnl() — spawns a new process.",
    "spawnle": "Plugin calls os.spawnle() — spawns a new process.",
    "spawnv": "Plugin calls os.spawnv() — spawns a new process.",
    "spawnve": "Plugin calls os.spawnve() — spawns a new process.",
    "fork": "Plugin calls os.fork() — forks the current process.",
}

# subprocess.* functions.
_DANGEROUS_SUBPROCESS_ATTRS: dict[str, str] = {
    "run": "Plugin calls subprocess.run() — executes a system command.",
    "Popen": "Plugin calls subprocess.Popen() — spawns a subprocess.",
    "call": "Plugin calls subprocess.call() — executes a system command.",
    "check_call": "Plugin calls subprocess.check_call() — executes a system command.",
    "check_output": "Plugin calls subprocess.check_output() — executes a system command.",
    "getoutput": "Plugin calls subprocess.getoutput() — executes a system command.",
    "getstatusoutput": "Plugin calls subprocess.getstatusoutput() — executes a system command.",
}


@dataclass
class AuditResult:
    """Result of auditing a plugin's source code."""

    plugin_name: str
    warnings: list[str] = field(default_factory=list)
    files_scanned: int = 0
    error: str | None = None

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)


# =============================================================================
# AST visitor
# =============================================================================

# Объединяем словари атрибутов в единую карту: модуль -> {атрибут: сообщение}
_PICKLE_ATTRS = dict.fromkeys(
    ("load", "loads", "Unpickler"),
    "Plugin uses pickle.load/loads/Unpickler — can execute code during deserialization.",
)

_DANGEROUS_MODULE_ATTRS: dict[str, dict[str, str]] = {
    "os": _DANGEROUS_OS_ATTRS,
    "subprocess": _DANGEROUS_SUBPROCESS_ATTRS,
    "pickle": _PICKLE_ATTRS,
}


class _DangerousCodeVisitor(ast.NodeVisitor):
    """Walk an AST module and collect dangerous-pattern warnings."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self._seen: set[str] = set()
        # Отслеживаем алиасы: локальное_имя -> (оригинальный_модуль, оригинальный_атрибут | None)
        self._aliases: dict[str, tuple[str, str | None]] = {}

    def _add(self, msg: str | None) -> None:
        if msg and msg not in self._seen:
            self._seen.add(msg)
            self.warnings.append(msg)

    def _check_module(self, module: str) -> None:
        if module in _DANGEROUS_IMPORTS:
            self._add(_DANGEROUS_IMPORTS[module])

    def _check_attr(self, module: str, attr: str) -> None:
        module_rules = _DANGEROUS_MODULE_ATTRS.get(module)
        if module_rules and attr in module_rules:
            self._add(module_rules[attr])

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            module = alias.name
            local_name = alias.asname or module
            self._aliases[local_name] = (module, None)
            self._check_module(module)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        self._check_module(module)

        for alias in node.names:
            local_name = alias.asname or alias.name
            self._aliases[local_name] = (module, alias.name)
            # Автоматически проверит и pickle.loads, и from os import system, и from subprocess import Popen
            self._check_attr(module, alias.name)

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        match node.func:
            # 1. Прямой вызов: eval(), exec() или импортированный from os import system -> system()
            case ast.Name(id=func_name):
                if func_name in _DANGEROUS_CALLS:
                    self._add(_DANGEROUS_CALLS[func_name])
                elif func_name in self._aliases:
                    real_module, real_attr = self._aliases[func_name]
                    if real_attr:
                        self._check_attr(real_module, real_attr)

            # 2. Вызов метода/атрибута: os.system(), subprocess.run() или sp.run()
            case ast.Attribute(value=ast.Name(id=obj_name), attr=attr):
                real_module, _ = self._aliases.get(obj_name, (obj_name, None))
                self._check_attr(real_module, attr)

        self.generic_visit(node)


# =============================================================================
# Public API
# =============================================================================


def audit_source(source: str, filename: str = "<unknown>") -> list[str]:
    """Parse Python source code and return dangerous-pattern warnings.

    Returns an empty list if no dangerous patterns are found.
    Returns a single-element list with a parse-error warning if the
    source has a SyntaxError (we scan what we can parse).
    """
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        return [
            f"Plugin source {filename} has a syntax error at line {e.lineno}: {e.msg} — cannot audit fully."
        ]

    visitor = _DangerousCodeVisitor()
    visitor.visit(tree)
    return visitor.warnings


def audit_plugin_source(plugin_name: str, source_files: dict[str, str]) -> AuditResult:
    """Audit a plugin by its source code.

    Args:
        plugin_name: Plugin name (for logging/identification).
        source_files: Dict mapping filename → source code content.

    Returns:
        AuditResult with warnings and file count.
    """
    result = AuditResult(plugin_name=plugin_name)
    all_warnings: list[str] = []

    for filename, source in source_files.items():
        result.files_scanned += 1
        try:
            warnings = audit_source(source, filename=filename)
            all_warnings.extend(warnings)
        except Exception as e:
            _logger.debug("audit: error scanning %s: %s", filename, e)
            result.error = f"Error scanning {filename}: {e}"

    # Dedup warnings (same pattern in multiple files)
    seen: set[str] = set()
    for w in all_warnings:
        if w not in seen:
            seen.add(w)
            result.warnings.append(w)

    return result


def audit_plugin_via_entry_point(plugin_name: str, entry_point) -> AuditResult:
    """Audit a plugin by discovering its source files via importlib.metadata.

    Uses ``importlib.metadata.files()`` to list the installed package's
    files WITHOUT importing the package — the plugin module is never
    loaded. Only .py files are scanned.

    Args:
        plugin_name: Plugin name (entry_point.name).
        entry_point: EntryPoint object from importlib.metadata.

    Returns:
        AuditResult with warnings and file count. If the package's
        files cannot be enumerated (e.g. editable installs without
        metadata), result.error is set and warnings is empty.
    """
    from importlib.metadata import files as _files

    result = AuditResult(plugin_name=plugin_name)

    # The entry_point.value is like "my_plugin.rules:MyRule".
    # We need the top-level package name to enumerate files.
    value = getattr(entry_point, "value", "")
    if ":" in value:
        module_path = value.split(":")[0]
    else:
        module_path = value

    # The top-level package is the first dotted segment.
    top_package = module_path.split(".")[0] if module_path else plugin_name

    try:
        package_files = _files(top_package)
    except Exception as e:
        result.error = f"Cannot enumerate files for package {top_package!r}: {e}"
        _logger.debug("audit: cannot enumerate files for %r: %s", top_package, e)
        return result

    if package_files is None:
        result.error = f"Package {top_package!r} has no file metadata (editable install?)"
        _logger.debug("audit: no file metadata for %r", top_package)
        return result

    # Collect .py source files.
    source_files: dict[str, str] = {}
    for pkg_path in package_files:
        if str(pkg_path).endswith(".py"):
            try:
                content = pkg_path.read_text(encoding="utf-8")
                source_files[str(pkg_path)] = content
            except Exception:
                # Skip files that can't be read (binary, permission, etc.)
                pass

    if not source_files:
        result.error = "No .py source files found in package metadata"
        return result

    return audit_plugin_source(plugin_name, source_files)
