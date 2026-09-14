"""Additional tests for conforma_mr_ops.py to achieve 97% coverage."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch
import argparse
import sys

import conforma_mr_ops as mod


class TestGlabGetMrs:
    """Tests for _glab_get_mrs (GitLab API search)."""

    @patch("conforma_mr_ops._get_project")
    def test_returns_mrs_from_gitlab_api(self, mock_get_project):
        """Test successful MR search via GitLab API."""
        # Mock GitLab MR objects
        mr1 = MagicMock()
        mr1.iid = 123
        mr1.title = "Test MR"
        mr1.description = "Test description"
        mr1.web_url = "https://gitlab.example.com/mr/123"
        mr1.source_branch = "feature"
        mr1.target_branch = "main"
        mr1.state = "opened"
        mr1.author = MagicMock(username="testuser")

        mr2 = MagicMock()
        mr2.iid = 124
        mr2.title = "Another MR"
        mr2.description = None
        mr2.web_url = "https://gitlab.example.com/mr/124"
        mr2.source_branch = "fix"
        mr2.target_branch = "main"
        mr2.state = "opened"
        mr2.author = None

        mock_project = MagicMock()
        mock_project.mergerequests.list.return_value = [mr1, mr2]
        mock_get_project.return_value = mock_project

        result = mod._glab_get_mrs("hermetic")

        assert len(result) == 2
        assert result[0]["iid"] == 123
        assert result[0]["title"] == "Test MR"
        assert result[0]["author"] == "testuser"
        assert result[1]["description"] == ""
        assert result[1]["author"] == ""

        mock_project.mergerequests.list.assert_called_once_with(
            state="opened",
            search="hermetic",
            per_page=20,
            get_all=False,
            timeout=15,
        )

    @patch("conforma_mr_ops._get_project")
    def test_returns_empty_on_api_error(self, mock_get_project):
        """Test returns empty list when GitLab API fails."""
        mock_get_project.side_effect = Exception("API Error")
        result = mod._glab_get_mrs("test")
        assert result == []


class TestSearchOpenExceptionMrs:
    """Tests for search_open_exception_mrs."""

    @patch("conforma_mr_ops._glab_get_mrs")
    def test_searches_full_rule_and_suffix(self, mock_glab):
        """Test searches both full rule and suffix after colon."""
        mock_glab.side_effect = [
            [{"iid": 123, "title": "MR1", "web_url": "url1", "author": "user1", "created_at": "2026-01-01", "description": "desc1"}],
            [{"iid": 124, "title": "MR2", "web_url": "url2", "author": {"username": "user2"}, "created_at": "2026-01-02", "description": ""}],
        ]

        result = mod.search_open_exception_mrs("rpm_signature.allowed:8a3872bf")

        assert len(result) == 2
        assert result[0]["iid"] == 123
        assert result[0]["author"] == "user1"
        assert result[1]["iid"] == 124
        assert result[1]["author"] == "user2"

        # Should be called twice: full rule + suffix
        assert mock_glab.call_count == 2
        mock_glab.assert_any_call("rpm_signature.allowed:8a3872bf")
        mock_glab.assert_any_call("8a3872bf")

    @patch("conforma_mr_ops._glab_get_mrs")
    def test_deduplicates_mrs_by_iid(self, mock_glab):
        """Test deduplicates MRs when both searches return the same MR."""
        same_mr = {"iid": 123, "title": "MR", "web_url": "url", "author": "user", "created_at": "2026-01-01", "description": ""}
        mock_glab.side_effect = [
            [same_mr],
            [same_mr],  # Duplicate from suffix search
        ]

        result = mod.search_open_exception_mrs("test:suffix")

        assert len(result) == 1
        assert result[0]["iid"] == 123

    @patch("conforma_mr_ops._glab_get_mrs")
    def test_truncates_long_search_terms(self, mock_glab):
        """Test truncates search terms longer than 60 chars."""
        mock_glab.return_value = []
        long_rule = "a" * 100
        mod.search_open_exception_mrs(long_rule)

        # Should truncate to 60 chars
        mock_glab.assert_called_once_with("a" * 60)

    @patch("conforma_mr_ops._glab_get_mrs")
    def test_no_suffix_search_for_rules_without_colon(self, mock_glab):
        """Test skips suffix search when rule has no colon."""
        mock_glab.return_value = []
        mod.search_open_exception_mrs("hermetic_task.hermetic")

        # Should only search once (no suffix)
        assert mock_glab.call_count == 1

    @patch("conforma_mr_ops._glab_get_mrs")
    def test_handles_author_as_dict(self, mock_glab):
        """Test handles author field as dict with username."""
        mock_glab.return_value = [
            {"iid": 123, "title": "MR", "web_url": "url", "author": {"username": "testuser"}, "created_at": "2026-01-01", "description": ""}
        ]

        result = mod.search_open_exception_mrs("test")
        assert result[0]["author"] == "testuser"


class TestMrCachePrefetch:
    """Tests for _MRCache.prefetch method."""

    def setup_method(self):
        mod._mr_cache._diffs.clear()

    @patch("conforma_mr_ops._get_project")
    def test_fetches_diffs_for_uncached_iids(self, mock_get_project):
        """Test fetches diffs for IIDs not in cache."""
        mr1 = MagicMock()
        mr1.changes.return_value = {"changes": [{"new_path": "file.yaml", "diff": "+content"}]}

        mr2 = MagicMock()
        mr2.changes.return_value = {"changes": [{"new_path": "file2.yaml", "diff": "+content2"}]}

        mock_project = MagicMock()
        mock_project.mergerequests.get = lambda iid: mr1 if iid == 100 else mr2
        mock_get_project.return_value = mock_project

        mod._mr_cache.prefetch([100, 101])

        assert mod._mr_cache.has(100)
        assert mod._mr_cache.has(101)
        assert len(mod._mr_cache.get_changes(100)) == 1
        assert len(mod._mr_cache.get_changes(101)) == 1

    @patch("conforma_mr_ops._get_project")
    def test_skips_already_cached_iids(self, mock_get_project):
        """Test doesn't re-fetch already cached diffs."""
        # Pre-populate cache
        mod._mr_cache.store(200, [{"diff": "cached"}])

        mock_project = MagicMock()
        mock_get_project.return_value = mock_project

        mod._mr_cache.prefetch([200])

        # Should not call API for cached IID
        mock_project.mergerequests.get.assert_not_called()

    @patch("conforma_mr_ops._get_project")
    def test_stores_empty_list_on_fetch_error(self, mock_get_project):
        """Test stores empty list when MR fetch fails."""
        mr = MagicMock()
        mr.changes.side_effect = Exception("API Error")

        mock_project = MagicMock()
        mock_project.mergerequests.get.return_value = mr
        mock_get_project.return_value = mock_project

        mod._mr_cache.prefetch([300])

        assert mod._mr_cache.has(300)
        assert mod._mr_cache.get_changes(300) == []

    @patch("conforma_mr_ops._get_project")
    def test_handles_project_connection_failure(self, mock_get_project):
        """Test handles failure to get GitLab project."""
        mock_get_project.side_effect = Exception("Connection failed")

        mod._mr_cache.prefetch([400, 401])

        # Should store empty lists for all IIDs
        assert mod._mr_cache.has(400)
        assert mod._mr_cache.has(401)
        assert mod._mr_cache.get_changes(400) == []
        assert mod._mr_cache.get_changes(401) == []


class TestMainCli:
    """Tests for main() CLI entry point."""

    @patch("conforma_mr_ops.search_open_exception_mrs")
    @patch("sys.argv", ["conforma_mr_ops.py", "search-open-mrs", "--rule", "hermetic_task.hermetic"])
    def test_search_open_mrs_command(self, mock_search):
        """Test search-open-mrs CLI command."""
        mock_search.return_value = [
            {"iid": 123, "title": "Test MR", "url": "https://gitlab.example.com/mr/123"}
        ]

        with patch("builtins.print") as mock_print:
            mod.main()

        mock_search.assert_called_once_with("hermetic_task.hermetic")
        # Should print JSON output
        assert mock_print.called

    @patch("conforma_mr_ops.analyze_mr_component_coverage")
    @patch("sys.argv", [
        "conforma_mr_ops.py",
        "analyze-coverage",
        "--mr-iid", "12345",
        "--rule", "test.rule",
        "--components", "comp-a,comp-b",
    ])
    def test_analyze_coverage_command(self, mock_analyze):
        """Test analyze-coverage CLI command."""
        mock_analyze.return_value = {
            "mr_iid": 12345,
            "covered": ["comp-a"],
            "missing": ["comp-b"],
        }

        with patch("builtins.print") as mock_print:
            mod.main()

        mock_analyze.assert_called_once_with(
            mr_iid=12345,
            rule="test.rule",
            requested_components=["comp-a", "comp-b"],
            relevant_policy_files=None,
        )
        assert mock_print.called

    @patch("conforma_mr_ops.analyze_mr_component_coverage")
    @patch("sys.argv", [
        "conforma_mr_ops.py",
        "analyze-coverage",
        "--mr-iid", "12345",
        "--rule", "test.rule",
        "--components", "comp-a",
        "--policy-files", "file1.yaml,file2.yaml",
    ])
    def test_analyze_coverage_with_policy_files(self, mock_analyze):
        """Test analyze-coverage with policy files filter."""
        mock_analyze.return_value = {"mr_iid": 12345}

        with patch("builtins.print"):
            mod.main()

        mock_analyze.assert_called_once_with(
            mr_iid=12345,
            rule="test.rule",
            requested_components=["comp-a"],
            relevant_policy_files=["file1.yaml", "file2.yaml"],
        )
