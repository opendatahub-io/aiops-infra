"""Tests for conforma-analyze submit_resolution_guide.py."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import submit_resolution_guide as mod


@pytest.fixture
def sample_guide(tmp_path):
    """Create a sample resolution guide file."""
    guide = tmp_path / "conforma-violations-resolution-guide.md"
    guide.write_text("# Test Guide\n\nSome content.", encoding="utf-8")
    return guide


class TestDryRun:
    def test_dry_run_does_not_call_api(self, sample_guide):
        with patch.object(mod, "_gh_api") as mock_api:
            result = mod.submit_resolution_guide(
                guide_file=str(sample_guide),
                release="rhoai-3.5-ea.2",
                target_dir="prod/release_day",
                dry_run=True,
            )
            mock_api.assert_not_called()

        assert result["dry_run"] is True
        assert result["committed"] is False
        assert "rhoai-3.5-ea.2" in result["url"]
        assert "conforma-violations-resolution-guide.md" in result["target_path"]

    def test_dry_run_uses_correct_path(self, sample_guide):
        result = mod.submit_resolution_guide(
            guide_file=str(sample_guide),
            release="rhoai-3.4",
            target_dir="prod/future/build_type_latest",
            dry_run=True,
        )
        assert result["target_path"] == "prod/future/build_type_latest/conforma-violations-resolution-guide.md"
        assert result["branch"] == "rhoai-3.4"


class TestFileNotFound:
    def test_missing_guide_file(self, tmp_path):
        result = mod.submit_resolution_guide(
            guide_file=str(tmp_path / "nonexistent.md"),
            release="rhoai-3.5-ea.2",
            target_dir="prod/release_day",
        )
        assert "error" in result
        assert result["committed"] is False


class TestBranchCheck:
    def test_branch_not_found(self, sample_guide):
        with patch.object(mod, "_gh_api") as mock_api:
            mock_api.return_value = (1, '{"message": "Not Found"}')
            result = mod.submit_resolution_guide(
                guide_file=str(sample_guide),
                release="rhoai-99.99",
                target_dir="prod/release_day",
            )
        assert "error" in result
        assert "not found" in result["error"].lower()
        assert result["committed"] is False


class TestCreateNewFile:
    def test_creates_file_when_not_exists(self, sample_guide):
        def mock_gh_api(endpoint, method="GET", input_data=None):
            if method == "GET" and "branches" in endpoint:
                return (0, '{"name": "rhoai-3.5-ea.2"}')
            if method == "GET" and "contents" in endpoint:
                return (1, '{"message": "Not Found"}')
            if method == "PUT":
                return (
                    0,
                    json.dumps(
                        {
                            "content": {
                                "html_url": "https://github.com/test/repo/blob/rhoai-3.5-ea.2/prod/release_day/conforma-violations-resolution-guide.md",
                                "sha": "abc123",
                            }
                        }
                    ),
                )
            return (1, "")

        with patch.object(mod, "_gh_api", side_effect=mock_gh_api):
            result = mod.submit_resolution_guide(
                guide_file=str(sample_guide),
                release="rhoai-3.5-ea.2",
                target_dir="prod/release_day",
            )

        assert result["committed"] is True
        assert result["overwritten"] is False
        assert result["sha"] == "abc123"


class TestUpdateExistingFile:
    def test_updates_file_with_sha(self, sample_guide):
        existing_sha = "existingsha456"

        def mock_gh_api(endpoint, method="GET", input_data=None):
            if method == "GET" and "branches" in endpoint:
                return (0, '{"name": "rhoai-3.5-ea.2"}')
            if method == "GET" and "contents" in endpoint:
                return (0, json.dumps({"sha": existing_sha}))
            if method == "PUT":
                payload = json.loads(input_data)
                assert payload["sha"] == existing_sha
                return (
                    0,
                    json.dumps(
                        {
                            "content": {
                                "html_url": "https://github.com/test/repo/blob/rhoai-3.5-ea.2/guide.md",
                                "sha": "newsha789",
                            }
                        }
                    ),
                )
            return (1, "")

        with patch.object(mod, "_gh_api", side_effect=mock_gh_api):
            result = mod.submit_resolution_guide(
                guide_file=str(sample_guide),
                release="rhoai-3.5-ea.2",
                target_dir="prod/release_day",
            )

        assert result["committed"] is True
        assert result["overwritten"] is True


class TestErrorHandling:
    def test_api_error_returns_error_dict(self, sample_guide):
        def mock_gh_api(endpoint, method="GET", input_data=None):
            if method == "GET" and "branches" in endpoint:
                return (0, '{"name": "rhoai-3.5-ea.2"}')
            if method == "GET" and "contents" in endpoint:
                return (1, "")
            if method == "PUT":
                return (1, '{"message": "Validation Failed"}')
            return (1, "")

        with patch.object(mod, "_gh_api", side_effect=mock_gh_api):
            result = mod.submit_resolution_guide(
                guide_file=str(sample_guide),
                release="rhoai-3.5-ea.2",
                target_dir="prod/release_day",
            )

        assert "error" in result
        assert result["committed"] is False
