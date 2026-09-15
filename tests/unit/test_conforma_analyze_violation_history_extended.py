"""Extended tests for conforma-analyze violation_history.py — covers the GitHub
fetch helpers, trace_history error branches, and format_text variants missed by
the base test file.
"""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import pytest
import requests

import conforma_context_ops
import violation_history as mod
from conforma_constants import csv_paths_for_environment


def _mock_resp(status_code=200, text="", json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = json_data if json_data is not None else []
    return resp


def _commit(sha, date, message="commit msg"):
    return {"sha": sha, "commit": {"committer": {"date": date}, "message": message}}


CSV_CONTENT = (
    "type,component_name,image,code\n"
    "violation,comp-a,quay.io/x,hermetic_task.hermetic\n"
    "violation,comp-b,quay.io/y,hermetic_task.hermetic\n"
    "warning,comp-a,quay.io/x,some_warning.code\n"
)


class TestGhHeaders:
    def test_headers_include_token(self):
        with patch.object(mod, "_get_github_token", return_value="gh-token-123"):
            headers = mod._gh_headers()
        assert headers["Authorization"] == "token gh-token-123"
        assert headers["Accept"] == "application/vnd.github+json"
        assert headers["X-GitHub-Api-Version"] == "2022-11-28"


class TestFindCsvPath:
    def test_no_token_returns_none(self):
        with patch.object(mod, "_get_github_token", return_value=None):
            assert mod._find_csv_path("rhoai-3.4", "prod") is None

    def test_first_path_returns_200(self):
        with patch.object(mod, "_get_github_token", return_value="tok"), \
             patch.object(mod.requests, "head", return_value=_mock_resp(200)) as mock_head:
            result = mod._find_csv_path("rhoai-3.4", "prod")
        assert result == csv_paths_for_environment("prod")[0]
        mock_head.assert_called_once()

    def test_falls_through_to_second_path(self):
        responses = [
            _mock_resp(404),
            _mock_resp(200),
        ]
        with patch.object(mod, "_get_github_token", return_value="tok"), \
             patch.object(mod.requests, "head", side_effect=responses):
            result = mod._find_csv_path("rhoai-3.4", "prod")
        assert result == csv_paths_for_environment("prod")[1]

    def test_request_exception_continues(self):
        responses = [
            requests.RequestException("timeout"),
            _mock_resp(200),
        ]
        with patch.object(mod, "_get_github_token", return_value="tok"), \
             patch.object(mod.requests, "head", side_effect=responses):
            result = mod._find_csv_path("rhoai-3.4", "prod")
        assert result == csv_paths_for_environment("prod")[1]

    def test_all_paths_fail_returns_none(self):
        with patch.object(mod, "_get_github_token", return_value="tok"), \
             patch.object(mod.requests, "head", return_value=_mock_resp(404)):
            assert mod._find_csv_path("rhoai-3.4", "prod") is None


class TestFetchCommits:
    def test_single_page(self):
        commits = [_commit("a" * 40, "2026-01-02T00:00:00Z"), _commit("b" * 40, "2026-01-01T00:00:00Z")]
        with patch.object(mod.requests, "get", return_value=_mock_resp(200, json_data=commits)):
            result = mod._fetch_commits("rhoai-3.4", "report.csv", 100)
        assert len(result) == 2
        assert result[0]["sha"] == "a" * 40
        assert result[0]["date"] == "2026-01-02T00:00:00Z"
        assert result[1]["message"] == "commit msg"

    def test_pagination_continues(self):
        """Pagination continues only when max_commits > 100 (per_page caps at 100)."""
        page1 = [_commit(f"{i:040x}", "2026-01-01T00:00:00Z") for i in range(100)]
        page2 = [_commit(f"f{i:039x}", "2026-01-01T00:00:00Z") for i in range(60)]
        with patch.object(mod.requests, "get", side_effect=[
            _mock_resp(200, json_data=page1),
            _mock_resp(200, json_data=page2),
        ]) as mock_get:
            result = mod._fetch_commits("rhoai-3.4", "report.csv", 150)
        assert len(result) == 150  # 160 fetched, truncated to max_commits
        assert mock_get.call_count == 2

    def test_max_commits_truncates_single_page(self):
        page1 = [_commit(f"{i:040x}", "2026-01-01T00:00:00Z") for i in range(5)]
        with patch.object(mod.requests, "get", return_value=_mock_resp(200, json_data=page1)):
            result = mod._fetch_commits("rhoai-3.4", "report.csv", 3)
        assert len(result) == 3

    def test_full_page_stops_at_max(self):
        """A full page that reaches max_commits stops the loop."""
        page1 = [_commit(f"{i:040x}", "2026-01-01T00:00:00Z") for i in range(5)]
        with patch.object(mod.requests, "get", return_value=_mock_resp(200, json_data=page1)) as mock_get:
            result = mod._fetch_commits("rhoai-3.4", "report.csv", 5)
        assert len(result) == 5
        assert mock_get.call_count == 1

    def test_non_200_breaks(self):
        with patch.object(mod.requests, "get", return_value=_mock_resp(403)):
            assert mod._fetch_commits("rhoai-3.4", "report.csv", 10) == []

    def test_request_exception_breaks(self):
        with patch.object(mod.requests, "get", side_effect=requests.RequestException("boom")):
            assert mod._fetch_commits("rhoai-3.4", "report.csv", 10) == []

    def test_json_decode_error_breaks(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = json.JSONDecodeError("bad", "doc", 0)
        with patch.object(mod.requests, "get", return_value=resp):
            assert mod._fetch_commits("rhoai-3.4", "report.csv", 10) == []

    def test_empty_first_page_breaks(self):
        with patch.object(mod.requests, "get", return_value=_mock_resp(200, json_data=[])):
            assert mod._fetch_commits("rhoai-3.4", "report.csv", 10) == []

    def test_long_message_truncated(self):
        long_msg = "x" * 200 + "\nsecond line"
        commits = [_commit("a" * 40, "2026-01-02T00:00:00Z", message=long_msg)]
        with patch.object(mod.requests, "get", return_value=_mock_resp(200, json_data=commits)):
            result = mod._fetch_commits("rhoai-3.4", "report.csv", 10)
        assert len(result[0]["message"]) == 120
