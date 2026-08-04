#!/usr/bin/env python3
"""Check whether a checkout is ready for local development and Codex use."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def version(command: list[str]) -> str | None:
    executable = shutil.which(command[0])
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, *command[1:]], capture_output=True, text=True, timeout=10, check=False
        )
    except OSError:
        return None
    return (result.stdout or result.stderr).strip().splitlines()[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="Fail on missing optional development tools")
    args = parser.parse_args()

    checks: list[tuple[str, bool, bool, str]] = []

    def add(name: str, ok: bool, required: bool, detail: str) -> None:
        checks.append((name, ok, required, detail))

    add("Python >=3.10", sys.version_info >= (3, 10), True, sys.version.split()[0])
    for name, command, required in (
        ("Git", ["git", "--version"], True),
        ("uv", ["uv", "--version"], True),
        ("Node.js", ["node", "--version"], True),
        ("npm", ["npm", "--version"], True),
        ("pdftotext", ["pdftotext", "-v"], args.strict),
    ):
        value = version(command)
        add(name, value is not None, required, value or "not found")

    node_value = version(["node", "--version"])
    if node_value:
        try:
            node_parts = tuple(int(part) for part in node_value.lstrip("v").split(".")[:3])
            add("Node.js >=22.13", node_parts >= (22, 13, 0), True, node_value)
        except ValueError:
            add("Node.js version parse", False, True, node_value)

    for relative in (
        "AGENTS.md",
        "pyproject.toml",
        "webapp/package-lock.json",
        "data/Annual-Reports",
        "data/DigitalMeasure-Reports",
    ):
        path = ROOT / relative
        add(relative, path.exists(), True, "present" if path.exists() else "missing")

    nested_git = ROOT / "webapp/.git"
    add(
        "single Git repository",
        not nested_git.exists(),
        True,
        "ready" if not nested_git.exists() else "webapp/.git is still a nested repository; consolidate before publishing",
    )

    secret_paths = [ROOT / ".secrets", ROOT / ".env"]
    exposed = []
    for secret_path in secret_paths:
        if secret_path.exists():
            check = subprocess.run(
                ["git", "check-ignore", "-q", str(secret_path)], cwd=ROOT, check=False
            )
            if check.returncode != 0:
                exposed.append(str(secret_path.relative_to(ROOT)))
    add("secret paths ignored", not exposed, True, "ignored" if not exposed else ", ".join(exposed))

    for name, ok, required, detail in checks:
        marker = "OK" if ok else ("FAIL" if required else "WARN")
        print(f"[{marker:4}] {name}: {detail}")

    failed = [name for name, ok, required, _ in checks if required and not ok]
    print("\n" + json.dumps({"ready": not failed, "blocking_checks": failed}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
