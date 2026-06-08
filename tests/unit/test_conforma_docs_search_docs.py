"""Tests for conforma-docs search_docs.py."""
from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "search_docs",
    _REPO_ROOT / "skills/conforma-docs/scripts/search_docs.py",
)
search_docs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(search_docs)


class TestScoreMatch:
    def test_exact_match(self):
        assert search_docs._score_match("hermetic build", ["hermetic"]) > 0

    def test_no_match(self):
        assert search_docs._score_match("something else", ["hermetic"]) == 0

    def test_multiple_terms(self):
        score = search_docs._score_match("hermetic build is required", ["hermetic", "build"])
        assert score > search_docs._score_match("hermetic build is required", ["hermetic"])

    def test_case_insensitive(self):
        assert search_docs._score_match("HERMETIC Build", ["hermetic"]) > 0

    def test_repeated_terms_score_higher(self):
        score_once = search_docs._score_match("hermetic task", ["hermetic"])
        score_twice = search_docs._score_match("hermetic hermetic", ["hermetic"])
        assert score_twice > score_once


class TestSearch:
    def test_returns_list(self):
        results = search_docs.search("nonexistent-query-that-matches-nothing-abc123")
        assert isinstance(results, list)

    def test_empty_query(self):
        results = search_docs.search("")
        assert results == []

    def test_short_terms_filtered(self):
        results = search_docs.search("a b")
        assert results == []

    def test_max_results_respected(self):
        results = search_docs.search("policy", max_results=2)
        assert len(results) <= 2


class TestDiscoverConformaDirs:
    def test_finds_conforma_skills(self):
        dirs = search_docs._discover_conforma_dirs()
        names = [d.name for d in dirs]
        assert "conforma" in names, "Should include the router skill"
        assert "conforma-docs" in names
        assert "conforma-exception" in names

    def test_excludes_non_conforma(self):
        dirs = search_docs._discover_conforma_dirs()
        names = [d.name for d in dirs]
        for name in names:
            assert name.startswith("conforma"), f"Unexpected dir: {name}"

    def test_returns_sorted(self):
        dirs = search_docs._discover_conforma_dirs()
        names = [d.name for d in dirs]
        assert names == sorted(names)


class TestStripFrontmatterAndCodeBlocks:
    def test_strips_yaml_frontmatter(self):
        text = textwrap.dedent("""\
            ---
            name: my-skill
            description: A skill
            ---

            # Title

            Some prose here.
        """)
        result = search_docs._strip_frontmatter_and_code_blocks(text)
        assert "name: my-skill" not in result
        assert "# Title" in result
        assert "Some prose here." in result

    def test_strips_fenced_code_blocks(self):
        text = textwrap.dedent("""\
            # Title

            Some explanation.

            ```bash
            echo "hello"
            python3 scripts/foo.py
            ```

            More prose after code.
        """)
        result = search_docs._strip_frontmatter_and_code_blocks(text)
        assert 'echo "hello"' not in result
        assert "Some explanation." in result
        assert "More prose after code." in result

    def test_strips_code_blocks_with_language_tag(self):
        text = textwrap.dedent("""\
            Intro.

            ```python
            def foo():
                pass
            ```

            Outro.
        """)
        result = search_docs._strip_frontmatter_and_code_blocks(text)
        assert "def foo():" not in result
        assert "Intro." in result
        assert "Outro." in result

    def test_preserves_text_without_frontmatter(self):
        text = "# Just a title\n\nSome text."
        result = search_docs._strip_frontmatter_and_code_blocks(text)
        assert result == text

    def test_strips_both_frontmatter_and_code(self):
        text = textwrap.dedent("""\
            ---
            name: test
            ---

            # Heading

            ```yaml
            key: value
            ```

            Final text.
        """)
        result = search_docs._strip_frontmatter_and_code_blocks(text)
        assert "name: test" not in result
        assert "key: value" not in result
        assert "# Heading" in result
        assert "Final text." in result


class TestExtractSnippet:
    def test_extracts_around_match(self):
        content = "x" * 200 + "hermetic build required" + "y" * 200
        snippet = search_docs._extract_snippet(content, ["hermetic"])
        assert "hermetic" in snippet

    def test_no_match_returns_empty(self):
        snippet = search_docs._extract_snippet("some text", ["nonexistent"])
        assert snippet == ""


class TestLoadSkillDocs:
    def test_loads_at_least_one_skill_doc(self):
        docs = search_docs._load_skill_docs()
        assert len(docs) > 0
        sources = [d["source"] for d in docs]
        assert any("SKILL.md" in s for s in sources)

    def test_skill_doc_has_no_frontmatter(self):
        docs = search_docs._load_skill_docs()
        for doc in docs:
            assert "allowed-tools:" not in doc["content"], (
                f"{doc['source']} still has frontmatter in indexed content"
            )

    def test_source_includes_skill_name(self):
        docs = search_docs._load_skill_docs()
        for doc in docs:
            assert "/" in doc["source"], f"source should include skill name: {doc['source']}"


class TestLoadYamlDocs:
    def test_excludes_policy_rules_file(self):
        docs = search_docs._load_yaml_docs()
        sources = [d["source"] for d in docs]
        assert not any("conforma-release-policy-rules.yaml" in s for s in sources)

    def test_includes_other_yaml(self):
        docs = search_docs._load_yaml_docs()
        if docs:
            assert all(
                d["source"].endswith(".yaml") or d["source"].endswith(".yml")
                for d in docs
            )


class TestLoadMarkdownDocs:
    def test_loads_exception_references(self):
        docs = search_docs._load_markdown_docs()
        sources = [d["source"] for d in docs]
        assert any("conforma-exception" in s for s in sources), (
            "Should index conforma-exception/references/ markdown files"
        )

    def test_source_includes_skill_and_subdir(self):
        docs = search_docs._load_markdown_docs()
        for doc in docs:
            parts = doc["source"].split("/")
            assert len(parts) >= 3, f"source should be skill/subdir/file: {doc['source']}"


class TestIntegration:
    """Verify the full search pipeline finds content across all conforma skills."""

    def test_search_finds_policy_rule(self):
        results = search_docs.search("hermetic")
        types = [r["type"] for r in results]
        assert "policy_rule" in types

    def test_search_finds_skill_doc(self):
        results = search_docs.search("violations", max_results=20)
        types = [r["type"] for r in results]
        assert "skill_doc" in types, "Should find content in SKILL.md files"

    def test_search_finds_markdown_doc(self):
        results = search_docs.search("exception waiver", max_results=20)
        types = [r["type"] for r in results]
        assert "documentation" in types, "Should find content in markdown reference files"
