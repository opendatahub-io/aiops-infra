#!/usr/bin/env python3
"""Pre-commit hook: detect broken file-path references in skills and scripts.

Scans all git-tracked files for two categories of path reference:

A. ``python3 <path>`` / ``bash <path>`` commands (in any text file).
   Resolved as repo-root-relative; flagged if the target does not exist.

B. Markdown link hrefs ``[text](relative-path)`` (in ``.md`` files only).
   Resolved relative to the containing file; flagged if the target does not
   exist after stripping ``#anchor`` / ``?query`` fragments.

Both categories auto-discover references via regex — no hardcoded file list.

An allowlist at ``tests/.path-reference-allowlist`` suppresses false positives
for runtime-generated files that are legitimately absent from git.

Usage (as pre-commit hook — see .pre-commit-config.yaml):
    python tests/check_path_references.py

The same scan is exercised by tests/unit/test_path_references.py in pytest.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent

COMMAND_PATH_PATTERN = re.compile(
    r"(?:python3|bash)\s+((?:scripts|skills)/[^\s\\\"'`]+\.(?:py|sh))"
)

MARKDOWN_LINK_PATTERN = re.compile(r"\]\(([^)]+)\)")

EXCLUDE_PATHS: set[str] = {
    ".git",
    ".venv",
    ".work",
    "__pycache__",
    "tests/check_path_references.py",
    "tests/unit/test_path_references.py",
}

COMMAND_PATH_EXCLUDE_PATHS: set[str] = {
    "tests/unit",
}

ALLOWLIST_FILE = REPO_ROOT / "tests" / ".path-reference-allowlist"


class Finding(NamedTuple):
    line_no: int
    category: str
    referenced_path: str
    suggestion: str | None


def _load_allowlist() -> set[str]:
    if not ALLOWLIST_FILE.is_file():
        return set()
    entries: set[str] = set()
    for line in ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            entries.add(stripped)
    return entries


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


def _is_excluded(rel_path: str, extra: set[str] | None = None) -> bool:
    parts = Path(rel_path).parts
    all_excludes = EXCLUDE_PATHS | (extra or set())
    for exc in all_excludes:
        exc_parts = Path(exc).parts
        if parts[: len(exc_parts)] == exc_parts:
            return True
    return False


def _find_correct_path(script_name: str) -> str | None:
    """If scripts/<name> doesn't exist at repo root, search skills/*/scripts/."""
    candidates = sorted(REPO_ROOT.glob(f"skills/*/scripts/{script_name}"))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.relative_to(REPO_ROOT))
    return None


def _strip_fragment(href: str) -> str:
    """Strip #anchor and ?query from a markdown link href."""
    for sep in ("#", "?"):
        idx = href.find(sep)
        if idx != -1:
            href = href[:idx]
    return href


def scan_command_paths(
    filepath: Path, allowlist: set[str]
) -> list[Finding]:
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    findings: list[Finding] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for match in COMMAND_PATH_PATTERN.finditer(line):
            ref_path = match.group(1)
            if "<" in ref_path or ref_path.startswith(("~/", "$")):
                continue
            if ref_path in allowlist:
                continue
            full = REPO_ROOT / ref_path
            if full.exists():
                continue
            script_name = Path(ref_path).name
            suggestion = _find_correct_path(script_name)
            findings.append(
                Finding(line_no, "command_path", ref_path, suggestion)
            )
    return findings


def scan_markdown_links(
    filepath: Path, allowlist: set[str]
) -> list[Finding]:
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    findings: list[Finding] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for match in MARKDOWN_LINK_PATTERN.finditer(line):
            href = match.group(1)
            if href.startswith(("http://", "https://", "#", "mailto:")):
                continue
            if "$" in href or '"' in href:
                continue
            if href == "url":
                continue
            clean = _strip_fragment(href)
            if not clean:
                continue
            resolved = (filepath.parent / clean).resolve()
            if resolved.exists():
                continue
            try:
                rel_resolved = str(resolved.relative_to(REPO_ROOT.resolve()))
            except ValueError:
                rel_resolved = ""
            if rel_resolved in allowlist:
                continue
            findings.append(Finding(line_no, "markdown_link", href, None))
    return findings


def scan_repo() -> dict[str, list[Finding]]:
    allowlist = _load_allowlist()
    findings: dict[str, list[Finding]] = {}

    for rel_path in _get_tracked_files():
        if _is_excluded(rel_path):
            continue
        full_path = REPO_ROOT / rel_path
        if not full_path.is_file() or full_path.stat().st_size > 1_000_000:
            continue

        hits: list[Finding] = []
        if not _is_excluded(rel_path, COMMAND_PATH_EXCLUDE_PATHS):
            hits.extend(scan_command_paths(full_path, allowlist))
        if rel_path.endswith(".md"):
            hits.extend(scan_markdown_links(full_path, allowlist))

        if hits:
            findings[rel_path] = hits

    return findings


def main() -> int:
    findings = scan_repo()
    if not findings:
        return 0

    total = sum(len(hits) for hits in findings.values())
    print(
        f"ERROR: Found {total} broken path reference(s) in {len(findings)} file(s).\n",
        file=sys.stderr,
    )
    for rel_path, hits in sorted(findings.items()):
        print(f"  {rel_path}:", file=sys.stderr)
        for f in hits:
            msg = f"    L{f.line_no}: [{f.category}] {f.referenced_path}"
            if f.suggestion:
                msg += f"  (did you mean: {f.suggestion}?)"
            print(msg, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
