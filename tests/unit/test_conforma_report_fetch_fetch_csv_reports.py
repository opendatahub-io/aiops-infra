"""Tests for conforma-report-fetch fetch_csv_reports.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import conforma_context_ops
import fetch_csv_reports


class TestGetGithubToken:
    def setup_method(self):
        fetch_csv_reports._github_token_cache = None

    def test_token_from_gh_cli(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        mock_result = MagicMock(returncode=0, stdout="ghp_abc123\n")
        with patch("fetch_csv_reports.subprocess.run", return_value=mock_result):
            token = fetch_csv_reports._get_github_token()
        assert token == "ghp_abc123"

    def test_token_cached(self):
        fetch_csv_reports._github_token_cache = "cached_token"
        token = fetch_csv_reports._get_github_token()
        assert token == "cached_token"

    def test_token_failure(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        mock_result = MagicMock(returncode=1, stdout="")
        with patch("fetch_csv_reports.subprocess.run", return_value=mock_result):
            token = fetch_csv_reports._get_github_token()
        assert token == ""

    def teardown_method(self):
        fetch_csv_reports._github_token_cache = None


class TestDownloadFileRaw:
    def setup_method(self):
        fetch_csv_reports._github_token_cache = None

    def test_no_token(self, tmp_path):
        fetch_csv_reports._github_token_cache = ""
        output = tmp_path / "test.csv"
        result = fetch_csv_reports._download_file_raw("path.csv", "main", output)
        assert result is not None
        assert "token" in result["error"].lower()

    def test_file_not_found(self, tmp_path):
        fetch_csv_reports._github_token_cache = "token123"
        output = tmp_path / "test.csv"
        resp = MagicMock(status_code=404)
        with patch("fetch_csv_reports.requests.get", return_value=resp):
            result = fetch_csv_reports._download_file_raw("path.csv", "main", output)
        assert result is not None
        assert "not found" in result["error"].lower()

    def test_successful_download(self, tmp_path):
        fetch_csv_reports._github_token_cache = "token123"
        output = tmp_path / "test.csv"
        csv_content = b"type,component_name\nviolation,comp-a\n"
        resp = MagicMock(status_code=200)
        resp.iter_content.return_value = [csv_content]
        with patch("fetch_csv_reports.requests.get", return_value=resp):
            result = fetch_csv_reports._download_file_raw("path.csv", "main", output)
        assert result is None
        assert output.exists()
        assert output.stat().st_size > 0

    def teardown_method(self):
        fetch_csv_reports._github_token_cache = None


class TestFetchWarningsCsvForRelease:
    def setup_method(self):
        fetch_csv_reports._github_token_cache = "token123"

    def test_all_paths_fail(self, tmp_path):
        def mock_download(csv_path, ref, output_file):
            return {"error": f"404 for {csv_path}"}

        with patch.object(fetch_csv_reports, "_download_file_raw", side_effect=mock_download):
            result = fetch_csv_reports.fetch_warnings_csv_for_release("rhoai-3.4", tmp_path, "prod")
        assert result["status"] == "failed"
        assert result["path"] is None

    def test_first_path_succeeds(self, tmp_path):
        def mock_download(csv_path, ref, output_file):
            if "build_type_latest" in csv_path and "warnings" in csv_path:
                output_file.write_text("type,component_name\nwarning,comp-a\n")
                return None
            return {"error": "not found"}

        commit_resp = MagicMock(status_code=200)
        commit_resp.json.return_value = [{"commit": {"committer": {"date": "2026-06-01T00:00:00Z"}}, "sha": "abc"}]
        with (
            patch.object(fetch_csv_reports, "_download_file_raw", side_effect=mock_download),
            patch("fetch_csv_reports.requests.get", return_value=commit_resp),
        ):
            result = fetch_csv_reports.fetch_warnings_csv_for_release("rhoai-3.4", tmp_path, "prod")
        assert result["status"] == "fetched"
        assert result["path"] is not None
        assert result["path"].endswith("-warnings.csv")

    def test_stage_environment_uses_stage_paths(self, tmp_path):
        attempted_paths = []

        def mock_download(csv_path, ref, output_file):
            attempted_paths.append(csv_path)
            return {"error": f"404 for {csv_path}"}

        with patch.object(fetch_csv_reports, "_download_file_raw", side_effect=mock_download):
            fetch_csv_reports.fetch_warnings_csv_for_release("rhoai-3.4", tmp_path, "stage")
        assert all("stage/" in p for p in attempted_paths)

    def teardown_method(self):
        fetch_csv_reports._github_token_cache = None


class TestCopyLocalCsvs:
    def test_copy_named_csv(self, tmp_path):
        local_dir = tmp_path / "local"
        local_dir.mkdir()
        csv_file = local_dir / "rhoai-3.4.csv"
        csv_file.write_text("type,component_name\nviolation,comp-a\n")

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        results, warnings = fetch_csv_reports.copy_local_csvs(local_dir, ["rhoai-3.4"], output_dir)
        assert len(results) == 1
        assert results[0]["status"] == "copied"
        assert (output_dir / "rhoai-3.4.csv").exists()

    def test_copy_from_subdirectory(self, tmp_path):
        local_dir = tmp_path / "local"
        release_dir = local_dir / "rhoai-3.4"
        release_dir.mkdir(parents=True)
        csv_file = release_dir / "conforma-violations-report.csv"
        csv_file.write_text("type,component_name\nviolation,comp-a\n")

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        results, warnings = fetch_csv_reports.copy_local_csvs(local_dir, ["rhoai-3.4"], output_dir)
        assert len(results) == 1
        assert results[0]["status"] == "copied"

    def test_missing_csv(self, tmp_path):
        local_dir = tmp_path / "local"
        local_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        results, warnings = fetch_csv_reports.copy_local_csvs(local_dir, ["rhoai-3.4"], output_dir)
        assert len(results) == 1
        assert results[0]["status"] == "failed"

    def test_copies_warnings_csv(self, tmp_path):
        local_dir = tmp_path / "local"
        local_dir.mkdir()
        (local_dir / "rhoai-3.4.csv").write_text("type,component_name\nviolation,comp-a\n")
        (local_dir / "rhoai-3.4-warnings.csv").write_text("type,component_name\nwarning,comp-b\n")

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        results, warnings = fetch_csv_reports.copy_local_csvs(local_dir, ["rhoai-3.4"], output_dir)
        assert len(warnings) == 1
        assert warnings[0]["status"] == "copied"
        assert (output_dir / "rhoai-3.4-warnings.csv").exists()

    def test_skip_warnings_when_disabled(self, tmp_path):
        local_dir = tmp_path / "local"
        local_dir.mkdir()
        (local_dir / "rhoai-3.4.csv").write_text("type,component_name\nviolation,comp-a\n")
        (local_dir / "rhoai-3.4-warnings.csv").write_text("type,component_name\nwarning,comp-b\n")

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        results, warnings = fetch_csv_reports.copy_local_csvs(
            local_dir, ["rhoai-3.4"], output_dir, include_warnings=False
        )
        assert len(warnings) == 0


class TestFetchSupportedReleases:
    def setup_method(self):
        fetch_csv_reports._github_token_cache = None

    def test_no_token(self):
        fetch_csv_reports._github_token_cache = ""
        releases = fetch_csv_reports.fetch_supported_releases()
        assert releases == []

    def test_parses_yaml_response(self):
        fetch_csv_reports._github_token_cache = "token123"
        yaml_content = (
            "supported:\n  - rhoai-3.4:\n      branch: rhoai-3.4\n  - rhoai-3.5:\n      branch: rhoai-3.5-ea.1\n"
        )
        resp = MagicMock(status_code=200)
        resp.text = yaml_content
        with patch("fetch_csv_reports.requests.get", return_value=resp):
            releases = fetch_csv_reports.fetch_supported_releases()
        assert "rhoai-3.4" in releases
        assert "rhoai-3.5-ea.1" in releases

    def test_http_failure(self):
        fetch_csv_reports._github_token_cache = "token123"
        resp = MagicMock(status_code=404)
        with patch("fetch_csv_reports.requests.get", return_value=resp):
            releases = fetch_csv_reports.fetch_supported_releases()
        assert releases == []

    def test_invalid_yaml(self):
        fetch_csv_reports._github_token_cache = "token123"
        resp = MagicMock(status_code=200)
        resp.text = "not: valid: yaml: [[["
        with patch("fetch_csv_reports.requests.get", return_value=resp):
            releases = fetch_csv_reports.fetch_supported_releases()
        assert releases == []

    def teardown_method(self):
        fetch_csv_reports._github_token_cache = None


class TestMainRequiresReleasesOrAll:
    """Layer 2 guardrail: fetch_csv_reports.main() refuses to run without --releases or --all."""

    def setup_method(self):
        fetch_csv_reports._github_token_cache = "token123"

    def test_no_releases_no_all_exits_with_error(self, monkeypatch, capsys):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(Path("/tmp/empty-workdir")))
        monkeypatch.setattr(
            "sys.argv",
            [
                "fetch_csv_reports.py",
                "--output-dir",
                "/tmp/test",
                "--environment",
                "prod",
            ],
        )
        rc = fetch_csv_reports.main()
        assert rc == 1
        captured = capsys.readouterr()
        assert "--releases" in captured.err
        assert "--all" in captured.err

    def test_all_flag_triggers_auto_detection(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "sys.argv",
            [
                "fetch_csv_reports.py",
                "--all",
                "--output-dir",
                str(tmp_path),
                "--metadata-file",
                str(tmp_path / "meta.json"),
                "--environment",
                "prod",
            ],
        )
        monkeypatch.setattr(
            fetch_csv_reports,
            "fetch_supported_releases",
            lambda: ["rhoai-3.5-ea.1"],
        )

        def mock_fetch(release, output_dir, environment="prod"):
            (output_dir / f"{release}.csv").write_text("type,component_name\nviolation,comp-a\n")
            return {
                "release": release,
                "status": "fetched",
                "path": str(output_dir / f"{release}.csv"),
                "size_bytes": 10,
                "source_path": "prod/build_type_latest/report.csv",
                "created_at": "",
                "source_sha": "",
            }

        monkeypatch.setattr(fetch_csv_reports, "fetch_csv_for_release", mock_fetch)
        monkeypatch.setattr(
            fetch_csv_reports,
            "fetch_warnings_csv_for_release",
            lambda r, d, **kw: {"release": r, "status": "failed", "error": "no warnings", "path": None},
        )

        rc = fetch_csv_reports.main()
        assert rc == 0

    def test_releases_flag_works(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "sys.argv",
            [
                "fetch_csv_reports.py",
                "--releases",
                "rhoai-3.5-ea.1",
                "--output-dir",
                str(tmp_path),
                "--metadata-file",
                str(tmp_path / "meta.json"),
                "--environment",
                "prod",
            ],
        )

        def mock_fetch(release, output_dir, environment="prod"):
            (output_dir / f"{release}.csv").write_text("type,component_name\nviolation,comp-a\n")
            return {
                "release": release,
                "status": "fetched",
                "path": str(output_dir / f"{release}.csv"),
                "size_bytes": 10,
                "source_path": "prod/build_type_latest/report.csv",
                "created_at": "",
                "source_sha": "",
            }

        monkeypatch.setattr(fetch_csv_reports, "fetch_csv_for_release", mock_fetch)
        monkeypatch.setattr(
            fetch_csv_reports,
            "fetch_warnings_csv_for_release",
            lambda r, d, **kw: {"release": r, "status": "failed", "error": "no warnings", "path": None},
        )

        rc = fetch_csv_reports.main()
        assert rc == 0
        assert (tmp_path / "rhoai-3.5-ea.1.csv").exists()

    def teardown_method(self):
        fetch_csv_reports._github_token_cache = None


class TestFetchCsvForRelease:
    def setup_method(self):
        fetch_csv_reports._github_token_cache = "token123"

    def test_all_paths_fail(self, tmp_path):
        def mock_download(csv_path, ref, output_file):
            return {"error": f"404 for {csv_path}"}

        with patch.object(fetch_csv_reports, "_download_file_raw", side_effect=mock_download):
            result = fetch_csv_reports.fetch_csv_for_release("rhoai-3.4", tmp_path, "prod")
        assert result["status"] == "failed"
        assert result["path"] is None

    def test_first_path_succeeds(self, tmp_path):
        def mock_download(csv_path, ref, output_file):
            if "build_type_latest" in csv_path:
                output_file.write_text("type,component_name\nviolation,comp-a\n")
                return None
            return {"error": "not found"}

        commit_resp = MagicMock(status_code=200)
        commit_resp.json.return_value = [{"commit": {"committer": {"date": "2026-06-01T00:00:00Z"}}, "sha": "abc"}]
        with (
            patch.object(fetch_csv_reports, "_download_file_raw", side_effect=mock_download),
            patch("fetch_csv_reports.requests.get", return_value=commit_resp),
        ):
            result = fetch_csv_reports.fetch_csv_for_release("rhoai-3.4", tmp_path, "prod")
        assert result["status"] == "fetched"
        assert result["path"] is not None
        assert "build_type_latest" in result["source_path"]

    def test_stage_environment_uses_stage_paths(self, tmp_path):
        attempted_paths = []

        def mock_download(csv_path, ref, output_file):
            attempted_paths.append(csv_path)
            return {"error": f"404 for {csv_path}"}

        with patch.object(fetch_csv_reports, "_download_file_raw", side_effect=mock_download):
            fetch_csv_reports.fetch_csv_for_release("rhoai-3.4", tmp_path, "stage")
        assert all("stage/" in p for p in attempted_paths)

    def teardown_method(self):
        fetch_csv_reports._github_token_cache = None


class TestNightlyComparisonFetch:
    def setup_method(self):
        fetch_csv_reports._github_token_cache = "token123"

    def test_fetches_exact_same_branch_paths_and_metadata(self, tmp_path):
        fetched = []

        def mock_download(path, ref, output_file):
            fetched.append((path, ref))
            output_file.write_text("type,component_name,code\nviolation,comp-a,rule.a\n")
            return None

        with (
            patch.object(fetch_csv_reports, "_download_file_raw", side_effect=mock_download),
            patch.object(
                fetch_csv_reports,
                "_fetch_last_commit_info",
                return_value={"date": "2026-09-24T00:00:00Z", "sha": "abc123"},
            ),
        ):
            result = fetch_csv_reports.fetch_nightly_comparison("rhoai-3.6-ea.2", tmp_path)

        assert result["status"] == "completed"
        assert fetched == [
            (
                "prod/future/build_type_nightly/conforma-violations-report.csv",
                "rhoai-3.6-ea.2",
            ),
            (
                "stage/future/build_type_latest/conforma-violations-report.csv",
                "rhoai-3.6-ea.2",
            ),
            ("prod/conforma-resolution-guide.md", "rhoai-3.6-ea.2"),
            (
                "prod/future/build_type_nightly/conforma-warnings-report.csv",
                "rhoai-3.6-ea.2",
            ),
        ]
        assert result["results"]["latest_comparison"]["source_sha"] == "abc123"
        assert result["results"]["resolution_guide"]["path"].endswith(
            "rhoai-3.6-ea.2-prod-conforma-resolution-guide.md"
        )

    def test_missing_commit_metadata_fails_closed(self, tmp_path):
        def download(path, ref, output_file):
            output_file.write_text("content")
            return None

        with (
            patch.object(fetch_csv_reports, "_download_file_raw", side_effect=download),
            patch.object(fetch_csv_reports, "_fetch_last_commit_info", return_value={"date": "", "sha": ""}),
        ):
            result = fetch_csv_reports.fetch_fixed_report_for_release(
                "rhoai-3.6-ea.2", tmp_path, "stage", "latest"
            )

        assert result["status"] == "failed"
        assert "commit metadata" in result["error"]

    def teardown_method(self):
        fetch_csv_reports._github_token_cache = None


class TestNightlyComparisonGate:
    def test_requires_explicit_nightly_build_type(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(
            "sys.argv",
            [
                "fetch_csv_reports.py",
                "--releases",
                "rhoai-3.6-ea.2",
                "--nightly-comparison",
                "--environment",
                "prod",
                "--output-dir",
                str(tmp_path),
            ],
        )

        assert fetch_csv_reports.main() == 1
        assert "build_type=nightly" in capsys.readouterr().err

    def test_comparison_records_both_reports_in_context(self, tmp_path, monkeypatch):
        run_dir = tmp_path / "run"
        conforma_context_ops.create(
            run_dir,
            {
                "application": {"release": "rhoai-3.6-ea.2"},
                "environment": "prod",
                "build_type": "nightly",
            },
        )
        conforma_context_ops.set_active(run_dir)
        primary_path = run_dir / "rhoai-3.6-ea.2.csv"
        latest_path = run_dir / "rhoai-3.6-ea.2-stage-latest.csv"
        guide_path = run_dir / "rhoai-3.6-ea.2-prod-conforma-resolution-guide.md"
        for path in (primary_path, latest_path, guide_path):
            path.write_text("content")

        def artifact(path, source_path, environment, build_type):
            return {
                "release": "rhoai-3.6-ea.2",
                "status": "fetched",
                "path": str(path),
                "source_path": source_path,
                "created_at": "2026-09-24T00:00:00Z",
                "source_sha": "abc123",
                "environment": environment,
                "build_type": build_type,
            }

        monkeypatch.setattr(
            fetch_csv_reports,
            "fetch_nightly_comparison",
            lambda release, output_dir, include_warnings=True: {
                "status": "completed",
                "results": {
                    "primary": artifact(primary_path, "prod/future/build_type_nightly/conforma-violations-report.csv", "prod", "nightly"),
                    "latest_comparison": artifact(latest_path, "stage/future/build_type_latest/conforma-violations-report.csv", "stage", "latest"),
                    "resolution_guide": artifact(guide_path, "prod/conforma-resolution-guide.md", "prod", "nightly"),
                    "warnings": artifact(run_dir / "warnings.csv", "prod/future/build_type_nightly/conforma-warnings-report.csv", "prod", "nightly"),
                },
                "failures": [],
            },
        )
        monkeypatch.setattr(
            "sys.argv",
            [
                "fetch_csv_reports.py",
                "--nightly-comparison",
                "--output-dir",
                str(run_dir),
                "--metadata-file",
                str(run_dir / "metadata.json"),
            ],
        )

        assert fetch_csv_reports.main() == 0
        context = conforma_context_ops.load(run_dir)
        assert context["steps"]["fetch"]["build_type"] == "nightly"
        assert context["steps"]["fetch"]["latest_comparison_report"]["build_type"] == "latest"
        assert context["steps"]["fetch"]["production_resolution_guide"]["source_path"] == "prod/conforma-resolution-guide.md"


class TestContextIntegration:
    """Tests for context.yaml auto-discovery and update."""

    def setup_method(self):
        fetch_csv_reports._github_token_cache = "token123"

    def _mock_fetch(self, release, output_dir, environment="prod"):
        (output_dir / f"{release}.csv").write_text("type,component_name\nviolation,comp-a\n")
        return {
            "release": release,
            "status": "fetched",
            "path": str(output_dir / f"{release}.csv"),
            "size_bytes": 40,
            "source_path": "prod/build_type_latest/report.csv",
            "created_at": "2026-07-01T00:00:00Z",
            "source_sha": "abc123",
        }

    def _mock_warn_fetch(self, release, output_dir, environment="prod"):
        return {"release": release, "status": "failed", "error": "no warnings", "path": None}

    def test_reads_release_and_env_from_context(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        run_dir = tmp_path / "20260703-120000"
        conforma_context_ops.create(
            run_dir,
            {
                "application": {
                    "name": "rhoai",
                    "release": "rhoai-3.5-ea.1",
                    "version": "3.5-ea.1",
                    "konflux_app": "rhoai-v3-5-ea-1",
                },
                "environment": "prod",
            },
        )
        conforma_context_ops.set_active(run_dir)

        monkeypatch.setattr(
            "sys.argv",
            [
                "fetch_csv_reports.py",
                "--metadata-file",
                str(tmp_path / "meta.json"),
            ],
        )
        monkeypatch.setattr(fetch_csv_reports, "fetch_csv_for_release", self._mock_fetch)
        monkeypatch.setattr(fetch_csv_reports, "fetch_warnings_csv_for_release", self._mock_warn_fetch)

        rc = fetch_csv_reports.main()
        assert rc == 0
        assert (run_dir / "rhoai-3.5-ea.1.csv").is_file()

    def test_updates_context_after_fetch(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        run_dir = tmp_path / "20260703-120000"
        conforma_context_ops.create(
            run_dir,
            {
                "application": {"name": "rhoai", "release": "rhoai-3.4", "version": "3.4", "konflux_app": "rhoai-v3-4"},
                "environment": "prod",
            },
        )
        conforma_context_ops.set_active(run_dir)

        monkeypatch.setattr(
            "sys.argv",
            [
                "fetch_csv_reports.py",
                "--metadata-file",
                str(tmp_path / "meta.json"),
            ],
        )
        monkeypatch.setattr(fetch_csv_reports, "fetch_csv_for_release", self._mock_fetch)
        monkeypatch.setattr(fetch_csv_reports, "fetch_warnings_csv_for_release", self._mock_warn_fetch)

        fetch_csv_reports.main()

        ctx = conforma_context_ops.load(run_dir)
        assert ctx["steps"]["fetch"]["status"] == "completed"
        assert "rhoai-3.4.csv" in ctx["steps"]["fetch"]["csv_files"]
        assert ctx["steps"]["fetch"]["source_sha"] == "abc123"

    def test_cli_release_overrides_context(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        run_dir = tmp_path / "20260703-120000"
        conforma_context_ops.create(
            run_dir,
            {
                "application": {"name": "rhoai", "release": "rhoai-3.4", "version": "3.4", "konflux_app": "rhoai-v3-4"},
                "environment": "prod",
            },
        )
        conforma_context_ops.set_active(run_dir)

        monkeypatch.setattr(
            "sys.argv",
            [
                "fetch_csv_reports.py",
                "--releases",
                "rhoai-3.5-ea.1",
                "--metadata-file",
                str(tmp_path / "meta.json"),
            ],
        )
        monkeypatch.setattr(fetch_csv_reports, "fetch_csv_for_release", self._mock_fetch)
        monkeypatch.setattr(fetch_csv_reports, "fetch_warnings_csv_for_release", self._mock_warn_fetch)

        fetch_csv_reports.main()
        assert (run_dir / "rhoai-3.5-ea.1.csv").is_file()
        assert not (run_dir / "rhoai-3.4.csv").exists()

    def test_explicit_run_dir(self, tmp_path, monkeypatch):
        run_dir = tmp_path / "my-run"
        conforma_context_ops.create(
            run_dir,
            {
                "application": {"name": "rhoai", "release": "rhoai-3.4", "version": "3.4", "konflux_app": "rhoai-v3-4"},
                "environment": "stage",
            },
        )

        monkeypatch.setattr(
            "sys.argv",
            [
                "fetch_csv_reports.py",
                "--run-dir",
                str(run_dir),
                "--metadata-file",
                str(tmp_path / "meta.json"),
            ],
        )
        monkeypatch.setattr(fetch_csv_reports, "fetch_csv_for_release", self._mock_fetch)
        monkeypatch.setattr(fetch_csv_reports, "fetch_warnings_csv_for_release", self._mock_warn_fetch)

        rc = fetch_csv_reports.main()
        assert rc == 0

    def test_no_context_requires_explicit_args(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        monkeypatch.setattr(
            "sys.argv",
            [
                "fetch_csv_reports.py",
                "--output-dir",
                str(tmp_path),
            ],
        )

        with pytest.raises(SystemExit):
            fetch_csv_reports.main()

    def teardown_method(self):
        fetch_csv_reports._github_token_cache = None
