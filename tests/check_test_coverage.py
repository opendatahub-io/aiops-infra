#!/usr/bin/env python3
"""Pre-commit hook: verify that every staged Python script has a test file.

Scans staged files for .py files in scripts/ and skills/*/scripts/,
checks that a corresponding test file exists in tests/unit/, and fails
the commit if any are missing (unless the file is on the ignore list).

Usage (as pre-commit hook — see .pre-commit-config.yaml):
    python tests/check_test_coverage.py <staged-files...>

Manual run:
    python tests/check_test_coverage.py scripts/gitlab_ops.py skills/conforma-analyze/scripts/parse_violations.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests" / "unit"
IGNORE_LIST_PATH = Path(__file__).resolve().parent / ".test-ignore-list"

SKIP_FILENAMES = {"__init__.py", "_setup_env.py", "conftest.py"}


def _load_ignore_list() -> set[str]:
    """Load the ignore list (paths relative to repo root)."""
    if not IGNORE_LIST_PATH.exists():
        return set()
    entries = set()
    for line in IGNORE_LIST_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            entries.add(line)
    return entries


def _expected_test_file(script_path: str) -> str:
    """Compute the expected test file name for a script path.

    scripts/gitlab_ops.py -> test_gitlab_ops.py
    skills/conforma-exception/scripts/create_gitlab_mr.py
      -> test_conforma_exception_create_gitlab_mr.py
    """
    parts = Path(script_path).parts

    if parts[0] == "scripts":
        return f"test_{parts[-1]}"

    if parts[0] == "skills" and "scripts" in parts:
        skill_name = parts[1].replace("-", "_")
        script_name = parts[-1]
        return f"test_{skill_name}_{script_name}"

    if parts[0] == ".claude" and parts[1] == "skills" and "scripts" in parts:
        skill_name = parts[2].replace("-", "_")
        script_name = parts[-1]
        return f"test_{skill_name}_{script_name}"

    return f"test_{parts[-1]}"


def _is_checkable(path: str) -> bool:
    """Return True if this path is a Python script that needs a test."""
    p = Path(path)
    if p.suffix != ".py":
        return False
    if p.name in SKIP_FILENAMES:
        return False

    parts = p.parts
    if parts[0] == "scripts":
        return True
    if parts[0] == "skills" and "scripts" in parts:
        return True
    if parts[0] == ".claude" and parts[1] == "skills" and "scripts" in parts:
        return True

    return False


def main() -> int:
    if len(sys.argv) < 2:
        return 0

    ignore_list = _load_ignore_list()
    failures: list[tuple[str, str]] = []

    for filepath in sys.argv[1:]:
        rel_path = str(Path(filepath).relative_to(REPO_ROOT)) if Path(filepath).is_absolute() else filepath

        if not _is_checkable(rel_path):
            continue

        if rel_path in ignore_list:
            continue

        expected_test = _expected_test_file(rel_path)
        test_path = TESTS_DIR / expected_test

        if not test_path.exists():
            failures.append((rel_path, expected_test))

    if failures:
        print("ERROR: The following scripts are missing test files:\n", file=sys.stderr)
        for script, expected in failures:
            print(f"  {script}", file=sys.stderr)
            print(f"    Expected: tests/unit/{expected}", file=sys.stderr)
            print(file=sys.stderr)
        print(
            "Add the test file, or if this is a legacy script that cannot "
            "be tested yet,\nadd it to tests/.test-ignore-list",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
