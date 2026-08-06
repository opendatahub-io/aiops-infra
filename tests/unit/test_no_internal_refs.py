"""Test that no internal infrastructure references are hardcoded in the repo.

Uses the same patterns as the pre-commit hook (tests/check_no_internal_refs.py)
but runs via pytest for CI integration and richer diagnostics.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

from check_no_internal_refs import FORBIDDEN_PATTERNS, scan_repo  # noqa: E402


class TestNoInternalRefs:
    """Ensure no internal hostnames or cluster IDs leak into tracked files."""

    def test_no_forbidden_patterns_in_repo(self):
        findings = scan_repo()

        if findings:
            lines = [
                "Internal infrastructure references found in tracked files:",
                "",
            ]
            for rel_path, hits in sorted(findings.items()):
                for line_no, description, line_content in hits:
                    preview = line_content[:100] + "..." if len(line_content) > 100 else line_content
                    lines.append(f"  {rel_path}:{line_no} [{description}] {preview}")
            lines.append("")
            lines.append(
                "Use environment variables ($GITLAB_HOST, $KONFLUX_CLUSTER_DOMAIN, etc.) "
                "or ~/.conforma/.env instead of hardcoded values."
            )
            pytest.fail("\n".join(lines))

    @pytest.mark.parametrize(
        "pattern_desc",
        [desc for _, desc in FORBIDDEN_PATTERNS],
        ids=[desc.replace(" ", "_") for _, desc in FORBIDDEN_PATTERNS],
    )
    def test_pattern_catches_known_examples(self, pattern_desc):
        """Verify each forbidden pattern matches a string derived from itself."""
        for pattern, desc in FORBIDDEN_PATTERNS:
            if desc == pattern_desc:
                example = f"HOST = {pattern.pattern.replace(chr(92), '')}"
                assert pattern.search(example), (
                    f"Pattern '{pattern_desc}' did not match its own derived example: {example}"
                )
                return
        pytest.fail(f"No pattern found with description: {pattern_desc}")
