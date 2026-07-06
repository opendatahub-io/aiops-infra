#!/usr/bin/env python3
"""Pre-commit hook: reject commits if example files contain real secrets.

Checks ~/.conforma/.env.example for values that look like real tokens, passwords,
or infrastructure details rather than empty placeholders.

Usage (as pre-commit hook — see .pre-commit-config.yaml):
    python tests/check_no_secrets_in_examples.py

Exit codes:
    0 — all clean
    1 — real-looking values detected in example files
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

EXAMPLE_FILES = [
    REPO_ROOT / "env.example",
]

TOKEN_PATTERNS = [
    re.compile(r"^glpat-"),
    re.compile(r"^ATATT3"),
    re.compile(r"^ghp_"),
    re.compile(r"^gho_"),
    re.compile(r"^xoxb-"),
    re.compile(r"^xoxp-"),
    re.compile(r"^sk-"),
    re.compile(r"^Bearer\s+"),
]

SAFE_PLACEHOLDER_VALUES = {
    "",
    "releng/konflux-release-data",
    "data-hub/component-maturity",
    "https://redhat-internal.slack.com",
    "https://redhat.atlassian.net",
}


def check_env_example(filepath: Path) -> list[str]:
    """Check .env.example for non-empty token values."""
    if not filepath.is_file():
        return []
    issues = []
    for line_no, line in enumerate(filepath.read_text().splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        value = value.strip().strip("\"'")
        if not value:
            continue
        if value in SAFE_PLACEHOLDER_VALUES:
            continue
        if len(value) >= 10:
            issues.append(f"  {filepath.name}:L{line_no}: {key.strip()}= has a {len(value)}-char value (looks real)")
        for pat in TOKEN_PATTERNS:
            if pat.search(value):
                issues.append(f"  {filepath.name}:L{line_no}: {key.strip()}= matches token pattern '{pat.pattern}'")
                break
    return issues


def main() -> int:
    all_issues: list[str] = []
    for filepath in EXAMPLE_FILES:
        if filepath.name.endswith(".env.example"):
            all_issues.extend(check_env_example(filepath))

    if not all_issues:
        return 0

    print(
        "ERROR: Example files appear to contain real secrets or credentials.\n"
        "These files are committed to git — they must only contain empty placeholders.\n",
        file=sys.stderr,
    )
    for issue in all_issues:
        print(issue, file=sys.stderr)
    print(
        "\nFix: remove real values from example files. Real secrets go in ~/.conforma/.env.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
