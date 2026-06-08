"""Tests for conforma-exception consolidate_mrs.py GitLab helpers."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch


consolidate_mrs = importlib.import_module("consolidate_mrs")


def _mock_gl_client(responses: list | None = None) -> MagicMock:
    """Create a mock GitLab client that returns canned responses."""
    gl = MagicMock()
    if responses:
        gl.http_get.side_effect = list(responses)
        gl.http_post.side_effect = list(responses)
        gl.http_put.side_effect = list(responses)
    return gl


SAMPLE_DIFF = """
+# impacted versions: rhoai-3.3
+componentNames:
+- odh-mlflow-v3-3
+- odh-dashboard-v3-3
+effectiveUntil: "2026-10-10T00:00:00Z"
"""


class TestFindOpenMrs:
    def test_filters_mrs_referencing_psx_key(self):
        api_mrs = [
            {
                "iid": 100,
                "title": "Exception for PSX-1042 rhoai-3.3",
                "description": "PSX ticket PSX-1042",
                "web_url": "https://gitlab.example.com/mr/100",
            },
            {
                "iid": 101,
                "title": "Unrelated MR",
                "description": "No ticket reference",
                "web_url": "https://gitlab.example.com/mr/101",
            },
            {
                "iid": 102,
                "title": "Another PSX-1042 MR",
                "description": "covers rhoai-3.4",
                "web_url": "https://gitlab.example.com/mr/102",
            },
        ]

        gl = _mock_gl_client()
        gl.http_get.return_value = api_mrs
        with patch("consolidate_mrs.gitlab_ops.get_client", return_value=gl):
            matched = consolidate_mrs.find_open_mrs("PSX-1042", "fake-token")

        assert len(matched) == 2
        assert {m["iid"] for m in matched} == {100, 102}

    def test_case_insensitive_match(self):
        api_mrs = [
            {
                "iid": 200,
                "title": "psx-999 exception",
                "description": "",
                "web_url": "https://gitlab.example.com/mr/200",
            }
        ]
        gl = _mock_gl_client()
        gl.http_get.return_value = api_mrs
        with patch("consolidate_mrs.gitlab_ops.get_client", return_value=gl):
            matched = consolidate_mrs.find_open_mrs("PSX-999", "fake-token")
        assert len(matched) == 1
        assert matched[0]["iid"] == 200


class TestExtractVersionSpecsFromMr:
    def test_parses_version_components_and_effective_until(self):
        changes_payload = {
            "changes": [
                {"diff": SAMPLE_DIFF},
            ]
        }

        gl = _mock_gl_client()
        gl.http_get.return_value = changes_payload
        with patch("consolidate_mrs.gitlab_ops.get_client", return_value=gl):
            spec = consolidate_mrs.extract_version_specs_from_mr(42, "fake-token")

        assert spec == {
            "version": "rhoai-3.3",
            "components": ["odh-mlflow-v3-3", "odh-dashboard-v3-3"],
            "effective_until": "2026-10-10T00:00:00Z",
        }

    def test_returns_none_when_parsing_fails(self):
        changes_payload = {"changes": [{"diff": "+ unrelated change\n"}]}

        gl = _mock_gl_client()
        gl.http_get.return_value = changes_payload
        with patch("consolidate_mrs.gitlab_ops.get_client", return_value=gl):
            spec = consolidate_mrs.extract_version_specs_from_mr(99, "fake-token")

        assert spec is None


class TestCloseMrWithComment:
    def test_posts_comment_and_closes_mr(self):
        gl = _mock_gl_client()
        gl.http_post.return_value = {"id": 1, "body": "comment"}
        gl.http_put.return_value = {"iid": 50, "state": "closed"}

        with patch("consolidate_mrs.gitlab_ops.get_client", return_value=gl):
            result = consolidate_mrs.close_mr_with_comment(50, 999, "fake-token")

        assert result == {"iid": 50, "state": "closed"}
        gl.http_post.assert_called_once()
        gl.http_put.assert_called_once()

        post_call = gl.http_post.call_args
        assert "merge_requests/50/notes" in post_call[0][0]
        assert "consolidated MR !999" in post_call[1]["post_data"]["body"]

    def test_close_mr_unknown_state_when_missing_from_response(self):
        gl = _mock_gl_client()
        gl.http_post.return_value = {"id": 1}
        gl.http_put.return_value = {}

        with patch("consolidate_mrs.gitlab_ops.get_client", return_value=gl):
            result = consolidate_mrs.close_mr_with_comment(77, 888, "fake-token")
        assert result == {"iid": 77, "state": "unknown"}
