"""Test that no broken file-path references exist in skills and scripts.

Uses the same scanner as the pre-commit hook (tests/check_path_references.py)
but runs via pytest for CI integration and richer diagnostics.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

from check_path_references import (
    COMMAND_PATH_PATTERN,
    MARKDOWN_LINK_PATTERN,
    _find_correct_path,
    _is_excluded,
    _strip_fragment,
    scan_repo,
)


class TestNobrokenPathReferences:
    """Main integration test — fails if any broken references exist in repo."""

    def test_no_broken_path_references(self):
        findings = scan_repo()

        if findings:
            lines = ["Broken path references found:", ""]
            for rel_path, hits in sorted(findings.items()):
                for f in hits:
                    msg = f"  {rel_path}:{f.line_no} [{f.category}] {f.referenced_path}"
                    if f.suggestion:
                        msg += f"  (did you mean: {f.suggestion}?)"
                    lines.append(msg)
            pytest.fail("\n".join(lines))


class TestCommandPathPattern:
    """Verify the regex extracts python3/bash command paths correctly."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            (
                "python3 scripts/verify_conforma_prerequisites.py --fix",
                "scripts/verify_conforma_prerequisites.py",
            ),
            (
                "python3 skills/conforma-exception/scripts/verify_auth.py",
                "skills/conforma-exception/scripts/verify_auth.py",
            ),
            (
                "Run `python3 scripts/foo.py` to check",
                "scripts/foo.py",
            ),
            (
                "bash skills/conforma-report-fetch/scripts/fetch_tekton_report.sh",
                "skills/conforma-report-fetch/scripts/fetch_tekton_report.sh",
            ),
            (
                "    python3 scripts/resolve_release_context.py --query rhoai-3.5",
                "scripts/resolve_release_context.py",
            ),
        ],
        ids=lambda t: t[:50],
    )
    def test_pattern_extracts_paths(self, text, expected):
        matches = COMMAND_PATH_PATTERN.findall(text)
        assert expected in matches

    @pytest.mark.parametrize(
        "text",
        [
            "python3 ~/.conforma/component-maturity/scripts/query.py",
            "python3 $HOME/scripts/foo.py",
            "python3 /usr/bin/scripts/foo.py",
            "python3 my_local_script.py",
            "python3 foo.py",
        ],
        ids=lambda t: t[:50],
    )
    def test_pattern_does_not_match_non_repo_paths(self, text):
        matches = COMMAND_PATH_PATTERN.findall(text)
        assert len(matches) == 0


class TestMarkdownLinkPattern:
    """Verify the regex extracts markdown link hrefs."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("[README](../README.md)", "../README.md"),
            (
                "[catalog](../../references/violation-catalog.yaml)",
                "../../references/violation-catalog.yaml",
            ),
            ("[text](path/to/file.md#section)", "path/to/file.md#section"),
        ],
        ids=lambda t: t[:50],
    )
    def test_pattern_extracts_hrefs(self, text, expected):
        matches = MARKDOWN_LINK_PATTERN.findall(text)
        assert expected in matches

    @pytest.mark.parametrize(
        "text",
        [
            "[link](https://example.com)",
            "[link](http://example.com/path)",
            "[link](#anchor-only)",
            "[link](mailto:user@example.com)",
        ],
        ids=lambda t: t[:50],
    )
    def test_url_hrefs_are_extracted_but_skipped_by_scanner(self, text):
        matches = MARKDOWN_LINK_PATTERN.findall(text)
        assert len(matches) == 1


class TestStripFragment:
    """Verify anchor/query stripping from hrefs."""

    @pytest.mark.parametrize(
        "href,expected",
        [
            ("file.md#section", "file.md"),
            ("file.md?query=1", "file.md"),
            ("file.md#section?query=1", "file.md"),
            ("file.md", "file.md"),
            ("path/to/file.md#L42", "path/to/file.md"),
        ],
    )
    def test_strips_fragments(self, href, expected):
        assert _strip_fragment(href) == expected


class TestFindCorrectPath:
    """Verify the suggestion engine finds scripts in skill directories."""

    def test_finds_verify_auth_in_conforma_exception(self):
        suggestion = _find_correct_path("verify_auth.py")
        assert suggestion == "skills/conforma-exception/scripts/verify_auth.py"

    def test_finds_search_docs_in_conforma_docs(self):
        suggestion = _find_correct_path("search_docs.py")
        assert suggestion == "skills/conforma-docs/scripts/search_docs.py"

    def test_returns_none_for_repo_root_script(self):
        result = _find_correct_path("verify_conforma_prerequisites.py")
        assert result is None

    def test_returns_none_for_nonexistent_script(self):
        result = _find_correct_path("does_not_exist_anywhere.py")
        assert result is None


class TestIsExcluded:
    def test_skips_nested_plans_directories(self):
        assert _is_excluded("skills/conforma-analyze/.plans/add-todo-section-to-executive-summary.md")

    def test_does_not_skip_skill_docs(self):
        assert not _is_excluded("skills/conforma-analyze/SKILL.md")
