#!/usr/bin/env python3
"""Pre-commit hook: detect conditional command variants in workflow .md files.

Scans workflow markdown files under skills/ for fenced bash code blocks that
contain paired conditional comments (e.g. ``# With Slack`` / ``# Without Slack``
within the same workflow step). Such pairs mean the agent must choose between
commands at runtime, making the command string non-deterministic and triggering
permission prompt churn.

Auto-discovers workflow .md files via ``git ls-files``.

Usage (as pre-commit hook — see .pre-commit-config.yaml):
    python tests/check_workflow_determinism.py

The same logic is exercised by tests/unit/test_check_workflow_determinism.py.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CONDITIONAL_COMMENT_RE = re.compile(
    r"^#\s*(With(?:out)?)\s+(.+)",
    re.IGNORECASE,
)

STEP_HEADING_RE = re.compile(r"^#{1,4}\s+.*(?:Step|step)\s+\d+", re.IGNORECASE)

CONTEXT_YAML_FLAGS = ["--release", "--releases", "--environment", "--run-dir",
                      "--require-slack", "--output-dir"]

EXTRACT_AND_PASS_RE = re.compile(
    r"extract\b.*\b(?:pass|run with)\b.*(`--\w+`)",
    re.IGNORECASE,
)

PASS_VIA_FLAG_RE = re.compile(
    r"pass\b.*\bvia\s+(`--\w+`)",
    re.IGNORECASE,
)


def discover_workflow_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--", "skills/"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    return [
        REPO_ROOT / f
        for f in result.stdout.splitlines()
        if f.endswith(".md") and "/workflows/" in f
    ]


def extract_bash_blocks(content: str) -> list[dict]:
    """Extract fenced bash code blocks with their preceding step context.

    Returns a list of dicts with keys: step, comments, line_no.
    """
    lines = content.splitlines()
    blocks = []
    current_step = "(preamble)"
    in_bash = False
    block_comments: list[str] = []
    block_start = 0

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        if STEP_HEADING_RE.match(stripped):
            current_step = stripped

        if stripped.startswith("```bash"):
            in_bash = True
            block_comments = []
            block_start = i
            continue

        if in_bash and stripped.startswith("```"):
            blocks.append({
                "step": current_step,
                "comments": block_comments,
                "line_no": block_start,
            })
            in_bash = False
            continue

        if in_bash and stripped.startswith("#"):
            block_comments.append(stripped)

    return blocks


def find_conditional_pairs(blocks: list[dict]) -> list[dict]:
    """Find blocks in the same step that have paired With/Without comments."""
    from collections import defaultdict

    step_groups: dict[str, list[dict]] = defaultdict(list)
    for block in blocks:
        step_groups[block["step"]].append(block)

    findings = []
    for step, step_blocks in step_groups.items():
        with_topics: dict[str, list[int]] = defaultdict(list)
        without_topics: dict[str, list[int]] = defaultdict(list)

        for block in step_blocks:
            for comment in block["comments"]:
                m = CONDITIONAL_COMMENT_RE.match(comment.lstrip("#").strip())
                if not m:
                    m = CONDITIONAL_COMMENT_RE.match(comment)
                if m:
                    kind = m.group(1).lower()
                    topic = m.group(2).strip().rstrip(":")
                    if kind == "with":
                        with_topics[topic.lower()].append(block["line_no"])
                    else:
                        without_topics[topic.lower()].append(block["line_no"])

        for topic in with_topics:
            if topic in without_topics:
                findings.append({
                    "step": step,
                    "topic": topic,
                    "with_lines": with_topics[topic],
                    "without_lines": without_topics[topic],
                })

    return findings


def find_extract_and_pass_instructions(content: str) -> list[dict]:
    """Find prose lines that instruct the model to extract user data and pass via CLI flags."""
    findings = []
    in_code_block = False
    for i, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        matched_flags: set[str] = set()
        for pattern in (EXTRACT_AND_PASS_RE, PASS_VIA_FLAG_RE):
            m = pattern.search(stripped)
            if m:
                flag = m.group(1).strip("`")
                if flag in CONTEXT_YAML_FLAGS and flag not in matched_flags:
                    matched_flags.add(flag)
                    findings.append({"line_no": i, "flag": flag, "text": stripped})
    return findings


def check_file(path: Path) -> list[str]:
    content = path.read_text(encoding="utf-8")
    blocks = extract_bash_blocks(content)
    pairs = find_conditional_pairs(blocks)

    errors = []
    rel = path.relative_to(REPO_ROOT)
    for pair in pairs:
        with_lns = ", ".join(str(n) for n in pair["with_lines"])
        without_lns = ", ".join(str(n) for n in pair["without_lines"])
        errors.append(
            f"{rel}: {pair['step']} — paired conditional "
            f"'# With {pair['topic']}' (line {with_lns}) / "
            f"'# Without {pair['topic']}' (line {without_lns})"
        )

    for finding in find_extract_and_pass_instructions(content):
        errors.append(
            f"{rel}: line {finding['line_no']} — prose instructs model to "
            f"extract user data and pass via '{finding['flag']}' "
            f"(should use context.yaml instead)"
        )

    return errors


def main() -> int:
    files = discover_workflow_files()
    all_errors: list[str] = []
    for f in files:
        all_errors.extend(check_file(f))

    if all_errors:
        print("Workflow determinism check FAILED:", file=sys.stderr)
        for e in all_errors:
            print(f"  {e}", file=sys.stderr)
        print(
            "\nConditional command pairs make workflow commands non-deterministic.",
            file=sys.stderr,
        )
        print(
            "Replace paired With/Without blocks with a single fixed command "
            "that reads parameters from context.yaml.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
