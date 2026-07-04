"""Tests for conforma-analyze submit_resolution_guide.py.

The guide is submitted to {environment}/conforma-status-and-resolution-guide.md on the
release branch. Legacy guides in prod/future/build_type_latest/ and the repo root are
cleaned up automatically when --metadata-file is provided.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

import conforma_context_ops
import submit_resolution_guide as mod


@pytest.fixture
def sample_guide(tmp_path):
    """Create a sample resolution guide file."""
    guide = tmp_path / "conforma-status-and-resolution-guide.md"
    guide.write_text("# Test Guide\n\nSome content.", encoding="utf-8")
    return guide


@pytest.fixture
def sample_metadata(tmp_path):
    """Create a sample fetch-metadata.json file."""
    meta = tmp_path / "fetch-metadata.json"
    meta.write_text(json.dumps({
        "releases": {
            "rhoai-3.5-ea.2": {
                "path": "~/.conforma/20260610/rhoai-3.5-ea.2.csv",
                "source_path": "prod/future/build_type_latest/conforma-violations-report.csv",
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
                environment="prod",
                dry_run=True,
            )
            mock_get.assert_not_called()
            mock_put.assert_not_called()

        assert result["dry_run"] is True
        assert result["committed"] is False
        assert "rhoai-3.5-ea.2" in result["url"]
        assert result["target_path"] == "prod/conforma-status-and-resolution-guide.md"

    def test_dry_run_targets_environment_dir(self, sample_guide):
        result = mod.submit_resolution_guide(
            guide_file=str(sample_guide),
            release="rhoai-3.4",
            environment="prod",
            dry_run=True,
        )
        assert result["target_path"] == "prod/conforma-status-and-resolution-guide.md"
        assert result["branch"] == "rhoai-3.4"

    def test_dry_run_stage_environment(self, sample_guide):
        result = mod.submit_resolution_guide(
            guide_file=str(sample_guide),
            release="rhoai-3.5-ea.2",
            environment="stage",
            dry_run=True,
        )
        assert result["target_path"] == "stage/conforma-status-and-resolution-guide.md"
        assert "stage" in result["url"]


class TestFileNotFound:
    def test_missing_guide_file(self, tmp_path):
        result = mod.submit_resolution_guide(
            guide_file=str(tmp_path / "nonexistent.md"),
            release="rhoai-3.5-ea.2",
            environment="prod",
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
                environment="prod",
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
                "html_url": "https://github.com/test/repo/blob/rhoai-3.5-ea.2/prod/conforma-status-and-resolution-guide.md",
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
                environment="prod",
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
                environment="prod",
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
        assert result == "prod/future/build_type_latest/conforma-violations-resolution-guide.md"

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


class TestEnvironmentTargetPath:
    def test_prod_targets_prod_dir(self, sample_guide):
        result = mod.submit_resolution_guide(
            guide_file=str(sample_guide),
            release="rhoai-3.5-ea.2",
            environment="prod",
            dry_run=True,
        )
        assert result["target_path"] == "prod/conforma-status-and-resolution-guide.md"

    def test_stage_targets_stage_dir(self, sample_guide):
        result = mod.submit_resolution_guide(
            guide_file=str(sample_guide),
            release="rhoai-3.5-ea.2",
            environment="stage",
            dry_run=True,
        )
        assert result["target_path"] == "stage/conforma-status-and-resolution-guide.md"

    def test_no_error_without_metadata(self, sample_guide):
        result = mod.submit_resolution_guide(
            guide_file=str(sample_guide),
            release="rhoai-3.5-ea.2",
            environment="prod",
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
                environment="prod",
            )

        assert "error" in result
        assert result["committed"] is False


class TestContextIntegration:
    """Tests for context-based parameter discovery in main()."""

    def _setup_run_with_guide(self, tmp_path):
        """Create a run directory with context.yaml and a guide file."""
        run_dir = tmp_path / "20260703-120000"
        run_dir.mkdir()

        guide = run_dir / "conforma-status-and-resolution-guide.md"
        guide.write_text("# Guide\n\nContent.", encoding="utf-8")

        context = {
            "application": {"release": "rhoai-3.5-ea.2"},
            "environment": "prod",
            "run": {"run_dir": conforma_context_ops.contract_home(run_dir)},
            "steps": {
                "resolution_guide": {
                    "status": "completed",
                    "guide_file": "conforma-status-and-resolution-guide.md",
                },
            },
        }
        context_path = run_dir / "context.yaml"
        context_path.write_text(yaml.dump(context), encoding="utf-8")

        work_dir = tmp_path / ".conforma"
        work_dir.mkdir(exist_ok=True)
        active_link = work_dir / ".conforma-active"
        active_link.symlink_to(run_dir)

        return run_dir, work_dir

    def test_reads_params_from_context(self, tmp_path, monkeypatch):
        """Zero-arg invocation resolves guide, release, environment from context."""
        run_dir, work_dir = self._setup_run_with_guide(tmp_path)
        monkeypatch.setenv("CONFORMA_WORKDIR", str(work_dir))
        monkeypatch.setattr("sys.argv", ["submit_resolution_guide.py", "--dry-run"])

        rc = mod.main()
        assert rc == 0

    def test_updates_context_after_submit(self, tmp_path, monkeypatch):
        """Non-dry-run submit records steps.submit in context."""
        run_dir, work_dir = self._setup_run_with_guide(tmp_path)
        monkeypatch.setenv("CONFORMA_WORKDIR", str(work_dir))
        monkeypatch.setattr("sys.argv", ["submit_resolution_guide.py"])

        branch_resp = MagicMock(status_code=200)
        contents_resp = MagicMock(status_code=404)
        put_resp = MagicMock(status_code=201)
        put_resp.json.return_value = {
            "content": {"html_url": "https://github.com/test/blob/guide.md", "sha": "abc"}
        }

        def mock_get(url, **kwargs):
            if "branches" in url:
                return branch_resp
            return contents_resp

        with (
            patch.object(mod, "_get_github_token", return_value="token"),
            patch.object(mod.requests, "get", side_effect=mock_get),
            patch.object(mod.requests, "put", return_value=put_resp),
            patch.object(mod.requests, "delete", return_value=MagicMock(status_code=404)),
        ):
            rc = mod.main()

        assert rc == 0
        ctx = conforma_context_ops.load(run_dir)
        assert ctx["steps"]["submit"]["status"] == "completed"

    def test_cli_overrides_context(self, tmp_path, monkeypatch):
        """Explicit CLI args override context values."""
        run_dir, work_dir = self._setup_run_with_guide(tmp_path)
        guide = tmp_path / "other-guide.md"
        guide.write_text("# Other\n\nContent.", encoding="utf-8")
        monkeypatch.setenv("CONFORMA_WORKDIR", str(work_dir))
        monkeypatch.setattr("sys.argv", [
            "submit_resolution_guide.py",
            "--guide-file", str(guide),
            "--release", "rhoai-3.4",
            "--environment", "stage",
            "--dry-run",
        ])

        rc = mod.main()
        assert rc == 0

    def test_no_context_requires_explicit_args(self, tmp_path, monkeypatch):
        """Without context and without required args, main() exits with error."""
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path / "empty"))
        monkeypatch.setattr("sys.argv", ["submit_resolution_guide.py", "--dry-run"])

        with pytest.raises(SystemExit):
            mod.main()
