"""Tests for conforma-analyze submit_resolution_guide.py.

The guide is always submitted to the root of the release branch
(conforma-resolution-guide.md). Legacy guides in prod/release_day/ are
cleaned up automatically when --metadata-file is provided.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

import submit_resolution_guide as mod


@pytest.fixture
def sample_guide(tmp_path):
    """Create a sample resolution guide file."""
    guide = tmp_path / "conforma-resolution-guide.md"
    guide.write_text("# Test Guide\n\nSome content.", encoding="utf-8")
    return guide


@pytest.fixture
def sample_metadata(tmp_path):
    """Create a sample fetch-metadata.json file."""
    meta = tmp_path / "fetch-metadata.json"
    meta.write_text(json.dumps({
        "releases": {
            "rhoai-3.5-ea.2": {
                "path": ".work/20260610/rhoai-3.5-ea.2.csv",
                "source_path": "prod/release_day/conforma-violations-report.csv",
                "created_at": "2026-06-10T12:00:00Z",
                "source_sha": "abc123",
            }
        }
    }), encoding="utf-8")
    return meta


class TestDryRun:
    def test_dry_run_does_not_call_api(self, sample_guide):
        with patch.object(mod.requests, "get") as mock_get, patch.object(mod.requests, "put") as mock_put:
            result = mod.submit_resolution_guide(
                guide_file=str(sample_guide),
                release="rhoai-3.5-ea.2",
                dry_run=True,
            )
            mock_get.assert_not_called()
            mock_put.assert_not_called()

        assert result["dry_run"] is True
        assert result["committed"] is False
        assert "rhoai-3.5-ea.2" in result["url"]
        assert result["target_path"] == "conforma-resolution-guide.md"

    def test_dry_run_targets_root(self, sample_guide):
        result = mod.submit_resolution_guide(
            guide_file=str(sample_guide),
            release="rhoai-3.4",
            dry_run=True,
        )
        assert result["target_path"] == "conforma-resolution-guide.md"
        assert result["branch"] == "rhoai-3.4"


class TestFileNotFound:
    def test_missing_guide_file(self, tmp_path):
        result = mod.submit_resolution_guide(
            guide_file=str(tmp_path / "nonexistent.md"),
            release="rhoai-3.5-ea.2",
        )
        assert "error" in result
        assert result["committed"] is False


class TestBranchCheck:
    def test_branch_not_found(self, sample_guide):
        branch_resp = MagicMock(status_code=404)
        with (
            patch.object(mod, "_get_github_token", return_value="token"),
            patch.object(mod.requests, "get", return_value=branch_resp),
        ):
            result = mod.submit_resolution_guide(
                guide_file=str(sample_guide),
                release="rhoai-99.99",
            )
        assert "error" in result
        assert "not found" in result["error"].lower()
        assert result["committed"] is False


class TestCreateNewFile:
    def test_creates_file_when_not_exists(self, sample_guide):
        branch_resp = MagicMock(status_code=200)
        contents_resp = MagicMock(status_code=404)
        put_resp = MagicMock(status_code=201)
        put_resp.json.return_value = {
            "content": {
                "html_url": "https://github.com/test/repo/blob/rhoai-3.5-ea.2/conforma-resolution-guide.md",
                "sha": "abc123",
            }
        }

        def mock_get(url, **kwargs):
            if "branches" in url:
                return branch_resp
            return contents_resp

        with (
            patch.object(mod, "_get_github_token", return_value="token"),
            patch.object(mod.requests, "get", side_effect=mock_get),
            patch.object(mod.requests, "put", return_value=put_resp),
        ):
            result = mod.submit_resolution_guide(
                guide_file=str(sample_guide),
                release="rhoai-3.5-ea.2",
            )

        assert result["committed"] is True
        assert result["overwritten"] is False
        assert result["sha"] == "abc123"


class TestUpdateExistingFile:
    def test_updates_file_with_sha(self, sample_guide):
        existing_sha = "existingsha456"
        branch_resp = MagicMock(status_code=200)
        contents_resp = MagicMock(status_code=200)
        contents_resp.json.return_value = {"sha": existing_sha}
        put_resp = MagicMock(status_code=200)
        put_resp.json.return_value = {
            "content": {
                "html_url": "https://github.com/test/repo/blob/rhoai-3.5-ea.2/guide.md",
                "sha": "newsha789",
            }
        }

        def mock_get(url, **kwargs):
            if "branches" in url:
                return branch_resp
            return contents_resp

        with (
            patch.object(mod, "_get_github_token", return_value="token"),
            patch.object(mod.requests, "get", side_effect=mock_get),
            patch.object(mod.requests, "put", return_value=put_resp) as mock_put,
        ):
            result = mod.submit_resolution_guide(
                guide_file=str(sample_guide),
                release="rhoai-3.5-ea.2",
            )

        assert result["committed"] is True
        assert result["overwritten"] is True
        payload = mock_put.call_args[1]["json"]
        assert payload["sha"] == existing_sha


class TestResolveOldPath:
    def test_derives_old_path_from_metadata(self, sample_metadata):
        result = mod._resolve_old_path(
            metadata_file=str(sample_metadata),
            release="rhoai-3.5-ea.2",
        )
        assert result == "prod/release_day/conforma-violations-resolution-guide.md"

    def test_returns_none_without_metadata(self):
        assert mod._resolve_old_path(None, "rhoai-3.5-ea.2") is None

    def test_returns_none_for_missing_file(self, tmp_path):
        result = mod._resolve_old_path(
            str(tmp_path / "nonexistent.json"), "rhoai-3.5-ea.2"
        )
        assert result is None

    def test_returns_none_for_missing_release_key(self, sample_metadata):
        result = mod._resolve_old_path(str(sample_metadata), "rhoai-99.99")
        assert result is None

    def test_returns_none_for_malformed_json(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        assert mod._resolve_old_path(str(bad), "rhoai-3.5-ea.2") is None


class TestRootDirSubmission:
    def test_always_targets_root(self, sample_guide):
        result = mod.submit_resolution_guide(
            guide_file=str(sample_guide),
            release="rhoai-3.5-ea.2",
            dry_run=True,
        )
        assert result["target_path"] == "conforma-resolution-guide.md"
        assert result["committed"] is False

    def test_no_error_without_metadata(self, sample_guide):
        result = mod.submit_resolution_guide(
            guide_file=str(sample_guide),
            release="rhoai-3.5-ea.2",
            dry_run=True,
        )
        assert "error" not in result


class TestErrorHandling:
    def test_api_error_returns_error_dict(self, sample_guide):
        branch_resp = MagicMock(status_code=200)
        contents_resp = MagicMock(status_code=404)
        put_resp = MagicMock(status_code=422)
        put_resp.json.return_value = {"message": "Validation Failed"}
        put_resp.text = "Validation Failed"

        def mock_get(url, **kwargs):
            if "branches" in url:
                return branch_resp
            return contents_resp

        with (
            patch.object(mod, "_get_github_token", return_value="token"),
            patch.object(mod.requests, "get", side_effect=mock_get),
            patch.object(mod.requests, "put", return_value=put_resp),
        ):
            result = mod.submit_resolution_guide(
                guide_file=str(sample_guide),
                release="rhoai-3.5-ea.2",
            )

        assert "error" in result
        assert result["committed"] is False
