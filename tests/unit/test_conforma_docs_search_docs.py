"""Tests for conforma-docs search_docs.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

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
