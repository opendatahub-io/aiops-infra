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
                "or .work/.env instead of hardcoded values."
            )
            pytest.fail("\n".join(lines))

    @pytest.mark.parametrize(
        "pattern_desc",
        [desc for _, desc in FORBIDDEN_PATTERNS],
        ids=[desc.replace(" ", "_") for _, desc in FORBIDDEN_PATTERNS],
    )
    def test_pattern_catches_known_examples(self, pattern_desc):
        """Verify each forbidden pattern matches at least one known example."""
        examples = {
            "internal GitLab hostname": "GITLAB_HOST = gitlab.cee.redhat.com",
            "internal Konflux cluster ID (RHOAI)": "config/stone-prod-p02.hjvn.p1/product/",
            "internal Konflux cluster ID (ODH)": "api.stone-prd-rh01.pg1f.p1.openshiftapps.com",
            "internal OpenShift cluster domain": "https://api.cluster.openshiftapps.com:6443",
            "internal Konflux documentation host": "https://konflux.pages.redhat.com/docs/",
            "internal Tekton Results route": "tekton-results-tekton-results.apps.cluster.example.com",
        }

        example = examples.get(pattern_desc)
        assert example is not None, f"No example string for pattern: {pattern_desc}"

        matched = False
        for pattern, desc in FORBIDDEN_PATTERNS:
            if desc == pattern_desc and pattern.search(example):
                matched = True
                break
        assert matched, f"Pattern '{pattern_desc}' did not match example: {example}"
