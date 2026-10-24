from __future__ import annotations

import os

WORKFLOW_TEMPLATE = """name: Senpy Code Scanning

on:
  push:
    branches: [ "main", "master" ]
  pull_request:
    branches: [ "main", "master" ]
  workflow_dispatch:

permissions:
  contents: read
  security-events: write

jobs:
  senpy-scan:
    name: Senpy Semantic Lint
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install Senpy
        run: pip install --upgrade senpy-linter

      - name: Run Senpy Analysis
        run: senpy {scan_target} --format sarif --output-file senpy.sarif
        continue-on-error: true

      - name: Upload SARIF report to GitHub Code Scanning
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: senpy.sarif
          category: senpy
"""


def find_repo_root(start_path: str) -> str:
    """Определяет корень репозитория по наличию .git или расположению папки game/."""
    abs_path = os.path.abspath(start_path)
    curr = abs_path
    while curr and os.path.dirname(curr) != curr:
        if os.path.exists(os.path.join(curr, ".git")):
            return curr
        curr = os.path.dirname(curr)

    if os.path.basename(abs_path).lower() == "game":
        return os.path.dirname(abs_path)
    return abs_path


def init_ci_workflow(target_path: str) -> tuple[str, bool]:
    """
    Создаёт файл .github/workflows/senpy.yml.
    Возвращает (путь_к_файлу, был_ли_создан).
    """
    repo_root = find_repo_root(target_path)
    workflows_dir = os.path.join(repo_root, ".github", "workflows")
    os.makedirs(workflows_dir, exist_ok=True)

    workflow_file = os.path.join(workflows_dir, "senpy.yml")

    # Если в корне есть папка game/, сканируем её, иначе корень
    scan_target = "game/" if os.path.isdir(os.path.join(repo_root, "game")) else "."
    content = WORKFLOW_TEMPLATE.format(scan_target=scan_target)

    with open(workflow_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)

    return workflow_file, True