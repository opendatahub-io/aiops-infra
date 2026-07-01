"""Tests for scripts/conforma_constants.py."""

from __future__ import annotations

import conforma_constants


class TestConstants:
    def test_repo_name(self):
        assert conforma_constants.CONFORMA_REPORTER_REPO == "red-hat-data-services/conforma-reporter"

    def test_url_derived_from_repo(self):
        assert conforma_constants.CONFORMA_REPORTER_URL == (
            f"https://github.com/{conforma_constants.CONFORMA_REPORTER_REPO}"
        )

    def test_actions_url_derived_from_url(self):
        assert conforma_constants.CONFORMA_REPORTER_ACTIONS_URL.startswith(
            conforma_constants.CONFORMA_REPORTER_URL
        )
        assert "actions/workflows" in conforma_constants.CONFORMA_REPORTER_ACTIONS_URL

    def test_csv_paths_use_csv_filename(self):
        for path in conforma_constants.CSV_PATHS:
            assert path.endswith(conforma_constants.CSV_FILENAME)

    def test_warnings_csv_paths_use_warnings_filename(self):
        for path in conforma_constants.WARNINGS_CSV_PATHS:
            assert path.endswith(conforma_constants.WARNINGS_CSV_FILENAME)

    def test_verify_next_step_references_actions_url(self):
        assert conforma_constants.CONFORMA_REPORTER_ACTIONS_URL in conforma_constants.VERIFY_NEXT_STEP


class TestCsvPathsForEnvironment:
    def test_prod_returns_prod_paths(self):
        paths = conforma_constants.csv_paths_for_environment("prod")
        assert paths == conforma_constants.CSV_PATHS
        for p in paths:
            assert p.startswith("prod/")

    def test_stage_returns_stage_paths(self):
        paths = conforma_constants.csv_paths_for_environment("stage")
        assert paths == conforma_constants.STAGE_CSV_PATHS
        for p in paths:
            assert p.startswith("stage/")

    def test_warnings_prod_returns_prod_paths(self):
        paths = conforma_constants.warnings_csv_paths_for_environment("prod")
        assert paths == conforma_constants.WARNINGS_CSV_PATHS
        for p in paths:
            assert p.startswith("prod/")

    def test_warnings_stage_returns_stage_paths(self):
        paths = conforma_constants.warnings_csv_paths_for_environment("stage")
        assert paths == conforma_constants.STAGE_WARNINGS_CSV_PATHS
        for p in paths:
            assert p.startswith("stage/")


class TestBuildReportUrl:
    def test_includes_release_prod(self):
        url = conforma_constants.build_report_url("rhoai-3.5-ea.2", "prod")
        assert "rhoai-3.5-ea.2" in url
        assert conforma_constants.CONFORMA_REPORTER_URL in url
        assert conforma_constants.CSV_PATHS[0] in url

    def test_includes_release_stage(self):
        url = conforma_constants.build_report_url("rhoai-3.5-ea.2", "stage")
        assert "rhoai-3.5-ea.2" in url
        assert conforma_constants.CONFORMA_REPORTER_URL in url
        assert conforma_constants.STAGE_CSV_PATHS[0] in url

    def test_includes_blob(self):
        url = conforma_constants.build_report_url("rhoai-3.4", "prod")
        assert "/blob/" in url


class TestBuildWarningsReportUrl:
    def test_includes_release_prod(self):
        url = conforma_constants.build_warnings_report_url("rhoai-3.5-ea.1", "prod")
        assert "rhoai-3.5-ea.1" in url
        assert conforma_constants.CONFORMA_REPORTER_URL in url
        assert conforma_constants.WARNINGS_CSV_PATHS[0] in url

    def test_includes_release_stage(self):
        url = conforma_constants.build_warnings_report_url("rhoai-3.5-ea.1", "stage")
        assert "rhoai-3.5-ea.1" in url
        assert conforma_constants.CONFORMA_REPORTER_URL in url
        assert conforma_constants.STAGE_WARNINGS_CSV_PATHS[0] in url
