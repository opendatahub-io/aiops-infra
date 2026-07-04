"""Test that no .work/ path references remain in conforma code.

Uses the same scanner as the pre-commit hook (tests/check_no_dotwork_paths.py)
but runs via pytest for CI integration and richer diagnostics.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

from check_no_dotwork_paths import DOTWORK_PATTERN, scan_repo  # noqa: E402


class TestNoDotworkPaths:
    """Ensure conforma code uses ~/.conforma/ instead of .work/."""

    def test_no_dotwork_paths_in_conforma_code(self):
        findings = scan_repo()

        if findings:
            lines = [
                ".work/ path references found in conforma code:",
                "",
            ]
            for rel_path, hits in sorted(findings.items()):
                for line_no, line_content in hits:
                    preview = line_content[:100] + "..." if len(line_content) > 100 else line_content
                    lines.append(f"  {rel_path}:{line_no}  {preview}")
            lines.append("")
            lines.append(
                "Use ~/.conforma/ instead of .work/ for all conforma runtime paths."
            )
            pytest.fail("\n".join(lines))

    @pytest.mark.parametrize(
        "text",
        [
            ".work/.env",
            ".work/bin/ec",
            ".work/20260703-120000/",
            ".work/konflux-release-data",
            ".work/component-maturity",
            'Path(".work/foo")',
            "writes to .work/ directory",
        ],
        ids=lambda t: t[:40],
    )
    def test_pattern_matches_known_dotwork_strings(self, text):
        assert DOTWORK_PATTERN.search(text), f"Pattern should match: {text}"

    @pytest.mark.parametrize(
        "text",
        [
            "network/config",
            "framework/setup",
            "homework/assignment",
            "~/.conforma/.env",
            "~/.conforma/bin/ec",
        ],
        ids=lambda t: t[:40],
    )
    def test_pattern_does_not_match_false_positives(self, text):
        assert not DOTWORK_PATTERN.search(text), f"Pattern should NOT match: {text}"
