"""Example Senpy plugin: detects TODO comments in .rpy files.

Second example plugin (alongside `my_senpy_plugin` which defines RPY901).
This one defines RPY902 — a HINT-severity rule that flags `# TODO:`,
`# FIXME:`, `# XXX:` and `# HACK:` comments left in Ren'Py source.

Use this plugin as a template when you want to:
  - Write a rule that scans ALL lines (not just dialogue / not just code)
  - Use HINT severity (informational, off by default in --errors-only)
  - Match case-insensitively across multiple keywords

See TODO_COMMENT_PLUGIN_README.md for installation + usage.
"""

from __future__ import annotations

__version__ = "0.1.0"
