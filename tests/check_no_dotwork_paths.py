#!/usr/bin/env python3
"""Pre-commit hook: detect .work/ path references in conforma code.

All conforma runtime state (secrets, runs, clones, binaries) lives in
~/.conforma/, not in .work/ relative to the repo root.  This scanner
catches regressions after the migration.

Usage (as pre-commit hook — see .pre-commit-config.yaml):
    python tests/check_no_dotwork_paths.py

The same scan is exercised by tests/unit/test_no_dotwork_paths.py in pytest.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DOTWORK_PATTERN = re.compile(r"(?<!\w)\.work/")

EXCLUDE_PATHS: set[str] = {
    ".work",
    ".git",
    ".githooks",
    ".venv",
    ".cursor",
    # non-conforma script that legitimately uses .work/
    "scripts/extract_user_coding_preferences.py",
    # shell script not yet migrated
    "scripts/install_slackdump.sh",
    # legacy shell hook not yet migrated
    "hooks",
    # repo-level docs (separate migration)
    "README.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "ARCHITECTURE.md",
    # the scanner and test themselves reference .work/ in patterns/messages
    "tests/check_no_dotwork_paths.py",
    "tests/unit/test_no_dotwork_paths.py",
    # pre-commit hook that scans .work/.env.example (repo artifact)
    "tests/check_no_secrets_in_examples.py",
    # pre-commit config references the hook name
    ".pre-commit-config.yaml",
}

EXCLUDE_GLOBS: list[str] = [
    "*.pyc",
    "*.egg-info",
    ".gitignore",
]

LINE_SKIP_PATTERNS = [
    re.compile(r"_LEGACY_DOTENV_PATH"),
    re.compile(r'assert\s+"\.work/.*"\s+not\s+in'),
    re.compile(r"assert\s+\"\.work/.*\"\s+not\s+in"),
]


def _get_tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        return []
    return [f for f in result.stdout.strip().splitlines() if f]


def _is_excluded(rel_path: str) -> bool:
    parts = Path(rel_path).parts
    for exc in EXCLUDE_PATHS:
        exc_parts = Path(exc).parts
        if parts[: len(exc_parts)] == exc_parts:
            return True
    for glob in EXCLUDE_GLOBS:
        if Path(rel_path).match(glob):
            return True
    return False


def _skip_line(line: str) -> bool:
    for pat in LINE_SKIP_PATTERNS:
        if pat.search(line):
            return True
    return False


def scan_file(filepath: Path) -> list[tuple[int, str]]:
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    hits = []
    for line_no, line in enumerate(text.splitlines(), 1):
        if DOTWORK_PATTERN.search(line) and not _skip_line(line):
            hits.append((line_no, line.strip()))
    return hits


def scan_repo() -> dict[str, list[tuple[int, str]]]:
    findings: dict[str, list[tuple[int, str]]] = {}
    for rel_path in _get_tracked_files():
        if _is_excluded(rel_path):
            continue
        full_path = REPO_ROOT / rel_path
        if not full_path.is_file() or full_path.stat().st_size > 1_000_000:
            continue
        hits = scan_file(full_path)
        if hits:
            findings[rel_path] = hits
    return findings


def main() -> int:
    findings = scan_repo()
    if not findings:
        return 0

    total = sum(len(hits) for hits in findings.values())
    print(
        f"ERROR: Found {total} .work/ path reference(s) in {len(findings)} file(s).\n",
        file=sys.stderr,
    )
    print(
        "Conforma runtime state must live in ~/.conforma/, not .work/.\n"
        "Replace .work/ paths with ~/.conforma/ equivalents.\n",
        file=sys.stderr,
    )
    for rel_path, hits in sorted(findings.items()):
        print(f"  {rel_path}:", file=sys.stderr)
        for line_no, line_content in hits:
            preview = line_content[:120] + "..." if len(line_content) > 120 else line_content
            print(f"    L{line_no}: {preview}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
