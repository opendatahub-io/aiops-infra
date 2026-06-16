"""Tests for conforma-report-fetch fetch_csv_reports.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


import fetch_csv_reports


class TestGetGithubToken:
    def setup_method(self):
        fetch_csv_reports._github_token_cache = None

    def test_token_from_gh_cli(self):
        mock_result = MagicMock(returncode=0, stdout="ghp_abc123\n")
        with patch("fetch_csv_reports.subprocess.run", return_value=mock_result):
            token = fetch_csv_reports._get_github_token()
        assert token == "ghp_abc123"

    def test_token_cached(self):
        fetch_csv_reports._github_token_cache = "cached_token"
        token = fetch_csv_reports._get_github_token()
        assert token == "cached_token"

    def test_token_failure(self):
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

    def test_curl_failure(self, tmp_path):
        fetch_csv_reports._github_token_cache = "token123"
        output = tmp_path / "test.csv"
        mock_result = MagicMock(returncode=22, stderr="404 Not Found")
        with patch("fetch_csv_reports.subprocess.run", return_value=mock_result):
            result = fetch_csv_reports._download_file_raw("path.csv", "main", output)
        assert result is not None
        assert "404" in result["error"]

    def test_successful_download(self, tmp_path):
        fetch_csv_reports._github_token_cache = "token123"
        output = tmp_path / "test.csv"
        output.write_text("type,component_name\nviolation,comp-a\n")

        mock_result = MagicMock(returncode=0)
        with patch("fetch_csv_reports.subprocess.run", return_value=mock_result):
            result = fetch_csv_reports._download_file_raw("path.csv", "main", output)
        assert result is None

    def teardown_method(self):
        fetch_csv_reports._github_token_cache = None


class TestFetchWarningsCsvForRelease:
    def setup_method(self):
        fetch_csv_reports._github_token_cache = "token123"

    def test_all_paths_fail(self, tmp_path):
        def mock_download(csv_path, ref, output_file):
            return {"error": f"404 for {csv_path}"}

        with patch.object(fetch_csv_reports, "_download_file_raw", side_effect=mock_download):
            result = fetch_csv_reports.fetch_warnings_csv_for_release("rhoai-3.4", tmp_path)
        assert result["status"] == "failed"
        assert result["path"] is None

    def test_first_path_succeeds(self, tmp_path):
        def mock_download(csv_path, ref, output_file):
            if "release_day" in csv_path and "warnings" in csv_path:
                output_file.write_text("type,component_name\nwarning,comp-a\n")
                return None
            return {"error": "not found"}

        mock_date = MagicMock(returncode=0, stdout="2026-06-01T00:00:00Z\n")
        with (
            patch.object(fetch_csv_reports, "_download_file_raw", side_effect=mock_download),
            patch("fetch_csv_reports.subprocess.run", return_value=mock_date),
        ):
            result = fetch_csv_reports.fetch_warnings_csv_for_release("rhoai-3.4", tmp_path)
        assert result["status"] == "fetched"
        assert result["path"] is not None
        assert result["path"].endswith("-warnings.csv")

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
        mock_result = MagicMock(returncode=0, stdout=yaml_content.encode("utf-8"))
        with patch("fetch_csv_reports.subprocess.run", return_value=mock_result):
            releases = fetch_csv_reports.fetch_supported_releases()
        assert "rhoai-3.4" in releases
        assert "rhoai-3.5-ea.1" in releases

    def test_curl_failure(self):
        fetch_csv_reports._github_token_cache = "token123"
        mock_result = MagicMock(returncode=1, stdout=b"")
        with patch("fetch_csv_reports.subprocess.run", return_value=mock_result):
            releases = fetch_csv_reports.fetch_supported_releases()
        assert releases == []

    def test_invalid_yaml(self):
        fetch_csv_reports._github_token_cache = "token123"
        mock_result = MagicMock(returncode=0, stdout=b"not: valid: yaml: [[[")
        with patch("fetch_csv_reports.subprocess.run", return_value=mock_result):
            releases = fetch_csv_reports.fetch_supported_releases()
        assert releases == []

    def teardown_method(self):
        fetch_csv_reports._github_token_cache = None


class TestFetchCsvForRelease:
    def setup_method(self):
        fetch_csv_reports._github_token_cache = "token123"

    def test_all_paths_fail(self, tmp_path):
        def mock_download(csv_path, ref, output_file):
            return {"error": f"404 for {csv_path}"}

        with patch.object(fetch_csv_reports, "_download_file_raw", side_effect=mock_download):
            result = fetch_csv_reports.fetch_csv_for_release("rhoai-3.4", tmp_path)
        assert result["status"] == "failed"
        assert result["path"] is None

    def test_first_path_succeeds(self, tmp_path):
        def mock_download(csv_path, ref, output_file):
            if "release_day" in csv_path:
                output_file.write_text("type,component_name\nviolation,comp-a\n")
                return None
            return {"error": "not found"}

        mock_date = MagicMock(returncode=0, stdout="2026-06-01T00:00:00Z\n")
        with (
            patch.object(fetch_csv_reports, "_download_file_raw", side_effect=mock_download),
            patch("fetch_csv_reports.subprocess.run", return_value=mock_date),
        ):
            result = fetch_csv_reports.fetch_csv_for_release("rhoai-3.4", tmp_path)
        assert result["status"] == "fetched"
        assert result["path"] is not None
        assert "release_day" in result["source_path"]

    def teardown_method(self):
        fetch_csv_reports._github_token_cache = None
