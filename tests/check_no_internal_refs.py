#!/usr/bin/env python3
"""Pre-commit hook: detect hardcoded internal hostnames and infrastructure references.

Scans tracked files for patterns that should never appear in a public repository:
internal GitLab hostnames, Konflux cluster identifiers, OpenShift internal
domains, and similar infrastructure details.

Legitimate references to these services must use environment variables
(e.g. $GITLAB_HOST) or the ~/.conforma/.env mechanism — never hardcoded values.

Usage (as pre-commit hook — see .pre-commit-config.yaml):
    python tests/check_no_internal_refs.py

Manual run (scan all tracked files):
    python tests/check_no_internal_refs.py

The same patterns are exercised by tests/unit/test_no_internal_refs.py in pytest.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ── Forbidden patterns ────────────────────────────────────────────────────
# Each tuple: (compiled regex, human-readable description)
FORBIDDEN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"gitlab\.cee\.redhat\.com"), "internal GitLab hostname"),
    (re.compile(r"stone-prod-p02"), "internal Konflux cluster ID (RHOAI)"),
    (re.compile(r"stone-prd-rh01"), "internal Konflux cluster ID (ODH)"),
    (re.compile(r"konflux\.pages\.redhat\.com"), "internal Konflux documentation host"),
]

# ── Files/directories excluded from scanning ──────────────────────────────
# Paths relative to repo root. Directories match any file underneath.
EXCLUDE_PATHS: set[str] = {
    ".git",
    ".venv",
    "tests/check_no_internal_refs.py",
    "tests/unit/test_no_internal_refs.py",
    ".claude/skills",
    "docs",
}

EXCLUDE_GLOBS: list[str] = [
    "*.pyc",
    "*.egg-info",
]


def _is_excluded(rel_path: str) -> bool:
    """Check if a path should be excluded from scanning."""
    parts = Path(rel_path).parts
    for excl in EXCLUDE_PATHS:
        excl_parts = Path(excl).parts
        if parts[: len(excl_parts)] == excl_parts:
            return True
    for glob_pat in EXCLUDE_GLOBS:
        if Path(rel_path).match(glob_pat):
            return True
    return False


def _get_tracked_files() -> list[str]:
    """Get all git-tracked files (relative to repo root)."""
    result = subprocess.run(
        ["git", "ls-files", "--cached"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        print(f"WARNING: git ls-files failed: {result.stderr.strip()}", file=sys.stderr)
        return []
    return [line for line in result.stdout.strip().splitlines() if line]


def scan_file(filepath: Path) -> list[tuple[int, str, str]]:
    """Scan a single file for forbidden patterns.

    Returns list of (line_number, matched_pattern_description, line_content).
    """
    hits: list[tuple[int, str, str]] = []
    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return hits

    for line_no, line in enumerate(content.splitlines(), start=1):
        for pattern, description in FORBIDDEN_PATTERNS:
            if pattern.search(line):
                hits.append((line_no, description, line.strip()))
                break
    return hits


def scan_repo() -> dict[str, list[tuple[int, str, str]]]:
    """Scan all tracked files and return findings keyed by relative path."""
    findings: dict[str, list[tuple[int, str, str]]] = {}
    tracked = _get_tracked_files()

    for rel_path in tracked:
        if _is_excluded(rel_path):
            continue

        filepath = REPO_ROOT / rel_path
        if not filepath.is_file():
            continue

        try:
            if filepath.stat().st_size > 1_000_000:
                continue
        except OSError:
            continue

        hits = scan_file(filepath)
        if hits:
            findings[rel_path] = hits

    return findings


def main() -> int:
    findings = scan_repo()

    if not findings:
        return 0

    total = sum(len(hits) for hits in findings.values())
    print(
        f"ERROR: Found {total} internal infrastructure reference(s) in {len(findings)} file(s).\n",
        file=sys.stderr,
    )
    print(
        "Hardcoded internal hostnames, cluster IDs, and infrastructure URLs must not\n"
        "be committed to this public repository. Use environment variables or\n"
        "~/.conforma/.env instead.\n",
        file=sys.stderr,
    )

    for rel_path, hits in sorted(findings.items()):
        print(f"  {rel_path}:", file=sys.stderr)
        for line_no, description, line_content in hits:
            preview = line_content[:120] + "..." if len(line_content) > 120 else line_content
            print(f"    L{line_no}: [{description}] {preview}", file=sys.stderr)
        print(file=sys.stderr)

    return 1


if __name__ == "__main__":
    sys.exit(main())
