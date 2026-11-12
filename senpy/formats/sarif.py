from __future__ import annotations

import json
import os

from senpy.core.models import Diagnostic
from senpy.rules.rules_info import RULES_DATABASE


def generate_sarif(diagnostics: list[Diagnostic], project_path: str) -> str:
    """Generates a SARIF v2.1.0 report for GitHub Code Scanning and other CI/CD platforms."""

    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Senpy Linter",
                        "informationUri": "https://github.com/Xilleet/senpy",
                        "rules": [],
                    }
                },
                "results": [],
            }
        ],
    }

    # 1. Populate the rules dictionary (so GitHub can show a detailed error description)
    rules_added = set()
    for rule_id, info in RULES_DATABASE.items():
        sarif["runs"][0]["tool"]["driver"]["rules"].append(  # type: ignore[index]
            {
                "id": rule_id,
                "shortDescription": {"text": info["title"]},
                "fullDescription": {"text": info["why"]},
                "helpUri": f"https://github.com/Xilleet/senpy/blob/main/RULES.md#{rule_id.lower()}",
            }
        )
        rules_added.add(rule_id)

    # Senpy severity -> SARIF mapping
    severity_map = {"ERROR": "error", "WARNING": "warning", "HINT": "note", "INFO": "note"}

    # 2. Populate the array of found issues
    for diag in diagnostics:
        # Just in case a new rule appeared that is not in the database
        if diag.code not in rules_added:
            sarif["runs"][0]["tool"]["driver"]["rules"].append(  # type: ignore[index]
                {"id": diag.code, "shortDescription": {"text": f"Rule {diag.code}"}}
            )
            rules_added.add(diag.code)

        # Paths in SARIF must be relative to the repository root (project_path)
        try:
            rel_path = os.path.relpath(diag.file_path, project_path)
        except ValueError:
            rel_path = diag.file_path

        uri = rel_path.replace("\\", "/")

        # SARIF uses 1-based numbering for lines and columns
        start_col = max(1, diag.col + 1)
        end_col = max(1, diag.end_col + 1) if diag.end_col > diag.col else start_col

        result = {
            "ruleId": diag.code,
            "level": severity_map.get(diag.severity or "", "warning"),
            "message": {"text": diag.message},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": uri},
                        "region": {
                            "startLine": max(1, diag.line_number),
                            "startColumn": start_col,
                            "endColumn": end_col,
                        },
                    }
                }
            ],
        }
        sarif["runs"][0]["results"].append(result)  # type: ignore[index]

    return json.dumps(sarif, indent=2, ensure_ascii=False)
