"""Unit tests for check_tooling_health.py."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import check_tooling_health


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


SAMPLE_CATALOG = {
    "tools": [
        {
            "id": "conforma-reporter",
            "name": "conforma-reporter GitHub Action",
            "repo": "red-hat-data-services/conforma-reporter",
            "workflow_file": "conforma-reporter.yaml",
            "expected_schedule": "daily",
            "max_acceptable_age_hours": 72,
            "failure_modes": [
                {
                    "id": "auth_expired",
                    "title": "GitHub token or Konflux credentials expired",
                    "symptoms": ["Bad credentials", "401 Unauthorized"],
                    "classification": {
                        "severity": "high",
                        "typical_owner": "devops",
                        "auto_recoverable": False,
                    },
                    "remediation": [
                        {"action": "Rotate credentials"},
                    ],
                },
                {
                    "id": "ec_policy_timeout",
                    "title": "Enterprise Contract evaluation timed out",
                    "symptoms": ["context deadline exceeded"],
                    "classification": {
                        "severity": "medium",
                        "typical_owner": "konflux_team",
                        "auto_recoverable": True,
                    },
                    "remediation": [
                        {"action": "Re-run the workflow"},
                    ],
                },
                {
                    "id": "unknown_failure",
                    "title": "Unclassified workflow failure",
                    "symptoms": [],
                    "classification": {
                        "severity": "medium",
                        "typical_owner": "devops",
                        "auto_recoverable": False,
                    },
                    "remediation": [
                        {"action": "Inspect logs"},
                    ],
                },
            ],
        }
    ]
}


def _make_run(run_id, status="completed", conclusion="success", created="2026-06-17T10:00:00Z", updated="2026-06-17T10:05:00Z", release="rhoai-3.5-ea.1", environment="prod"):
    return {
        "id": run_id,
        "status": status,
        "conclusion": conclusion,
        "created_at": created,
        "updated_at": updated,
        "html_url": f"https://github.com/org/repo/actions/runs/{run_id}",
        "head_sha": "abc123def456",
        "head_branch": "main",
        "run_attempt": 1,
        "display_title": f"Conforma Reporter (target env: {environment}): {release} (nightly)",
    }


def _api_response(runs, status_code=200):
    resp = MagicMock(status_code=status_code)
    resp.json.return_value = {"workflow_runs": runs}
    resp.text = json.dumps({"workflow_runs": runs})
    return resp


# ---------------------------------------------------------------------------
# Health classification tests
# ---------------------------------------------------------------------------


class TestClassifyHealth:
    def test_healthy_latest_success(self):
        runs = [
            check_tooling_health._parse_run(_make_run(1, conclusion="success")),
        ]
        health = check_tooling_health._classify_health(runs)
        assert health["status"] == "healthy"
        assert health["consecutive_failures"] == 0
        assert health["last_success"]["id"] == 1

    def test_unhealthy_latest_failure(self):
        runs = [
            check_tooling_health._parse_run(_make_run(3, conclusion="failure")),
            check_tooling_health._parse_run(_make_run(2, conclusion="failure")),
            check_tooling_health._parse_run(_make_run(1, conclusion="success")),
        ]
        health = check_tooling_health._classify_health(runs)
        assert health["status"] == "unhealthy"
        assert health["consecutive_failures"] == 2
        assert health["last_success"]["id"] == 1

    def test_unhealthy_cancelled(self):
        runs = [
            check_tooling_health._parse_run(_make_run(1, conclusion="cancelled")),
        ]
        health = check_tooling_health._classify_health(runs)
        assert health["status"] == "unhealthy"
        assert "cancelled" in health["reason"]

    def test_in_progress(self):
        runs = [
            check_tooling_health._parse_run(_make_run(2, status="in_progress", conclusion=None)),
            check_tooling_health._parse_run(_make_run(1, conclusion="success")),
        ]
        health = check_tooling_health._classify_health(runs)
        assert health["status"] == "in_progress"
        assert health["in_progress_run"]["id"] == 2
        assert health["last_success"]["id"] == 1

    def test_no_runs(self):
        health = check_tooling_health._classify_health([])
        assert health["status"] == "no_runs"
        assert health["last_success"] is None

    def test_all_failures_no_success(self):
        runs = [
            check_tooling_health._parse_run(_make_run(3, conclusion="failure")),
            check_tooling_health._parse_run(_make_run(2, conclusion="failure")),
            check_tooling_health._parse_run(_make_run(1, conclusion="failure")),
        ]
        health = check_tooling_health._classify_health(runs)
        assert health["status"] == "unhealthy"
        assert health["consecutive_failures"] == 3
        assert health["last_success"] is None


# ---------------------------------------------------------------------------
# Symptom matching tests
# ---------------------------------------------------------------------------


class TestClassifyFailure:
    def test_matches_auth_expired(self):
        tool_config = SAMPLE_CATALOG["tools"][0]
        result = check_tooling_health.classify_failure(
            "Error: Bad credentials for token", tool_config
        )
        assert result is not None
        assert result["id"] == "auth_expired"

    def test_matches_ec_timeout(self):
        tool_config = SAMPLE_CATALOG["tools"][0]
        result = check_tooling_health.classify_failure(
            "context deadline exceeded while waiting for EC", tool_config
        )
        assert result is not None
        assert result["id"] == "ec_policy_timeout"

    def test_falls_back_to_unknown(self):
        tool_config = SAMPLE_CATALOG["tools"][0]
        result = check_tooling_health.classify_failure(
            "some completely new error", tool_config
        )
        assert result is not None
        assert result["id"] == "unknown_failure"

    def test_case_insensitive_match(self):
        tool_config = SAMPLE_CATALOG["tools"][0]
        result = check_tooling_health.classify_failure(
            "ERROR: BAD CREDENTIALS", tool_config
        )
        assert result is not None
        assert result["id"] == "auth_expired"


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------


class TestFetchWorkflowRuns:
    @patch("check_tooling_health.requests.get")
    def test_success(self, mock_get):
        runs = [_make_run(1, release="rhoai-3.5"), _make_run(2, release="rhoai-3.5")]
        mock_get.return_value = _api_response(runs)

        result = check_tooling_health._fetch_workflow_runs(
            "org/repo", "workflow.yaml", "rhoai-3.5", 5, "token123", "prod"
        )
        assert "runs" in result
        assert len(result["runs"]) == 2

    @patch("check_tooling_health.requests.get")
    def test_filters_by_release_in_display_title(self, mock_get):
        runs = [
            _make_run(1, release="rhoai-3.5-ea.2"),
            _make_run(2, release="rhoai-3.4"),
            _make_run(3, release="rhoai-3.5-ea.2"),
            _make_run(4, release="rhoai-3.3"),
        ]
        mock_get.return_value = _api_response(runs)

        result = check_tooling_health._fetch_workflow_runs(
            "org/repo", "workflow.yaml", "rhoai-3.5-ea.2", 5, "token123", "prod"
        )
        assert "runs" in result
        assert len(result["runs"]) == 2
        assert all("rhoai-3.5-ea.2" in r["display_title"] for r in result["runs"])

    @patch("check_tooling_health.requests.get")
    def test_no_matching_runs_returns_empty(self, mock_get):
        runs = [_make_run(1, release="rhoai-3.4"), _make_run(2, release="rhoai-3.3")]
        mock_get.return_value = _api_response(runs)

        result = check_tooling_health._fetch_workflow_runs(
            "org/repo", "workflow.yaml", "rhoai-3.5-ea.2", 5, "token123", "prod"
        )
        assert "runs" in result
        assert len(result["runs"]) == 0

    @patch("check_tooling_health.requests.get")
    def test_filters_by_environment(self, mock_get):
        runs = [
            _make_run(1, release="rhoai-3.5-ea.2", environment="prod"),
            _make_run(2, release="rhoai-3.5-ea.2", environment="stage"),
            _make_run(3, release="rhoai-3.5-ea.2", environment="prod"),
            _make_run(4, release="rhoai-3.5-ea.2", environment="stage"),
        ]
        mock_get.return_value = _api_response(runs)

        result = check_tooling_health._fetch_workflow_runs(
            "org/repo", "workflow.yaml", "rhoai-3.5-ea.2", 5, "token123",
            environment="stage",
        )
        assert "runs" in result
        assert len(result["runs"]) == 2
        assert all("target env: stage" in r["display_title"] for r in result["runs"])

    @patch("check_tooling_health.requests.get")
    def test_explicit_prod_environment(self, mock_get):
        runs = [
            _make_run(1, release="rhoai-3.5-ea.2", environment="prod"),
            _make_run(2, release="rhoai-3.5-ea.2", environment="stage"),
        ]
        mock_get.return_value = _api_response(runs)

        result = check_tooling_health._fetch_workflow_runs(
            "org/repo", "workflow.yaml", "rhoai-3.5-ea.2", 5, "token123", "prod",
        )
        assert "runs" in result
        assert len(result["runs"]) == 1
        assert "target env: prod" in result["runs"][0]["display_title"]

    @patch("check_tooling_health.requests.get")
    def test_404_error(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404, text="Not found")

        result = check_tooling_health._fetch_workflow_runs(
            "org/repo", "workflow.yaml", "no-branch", 5, "token123", "prod"
        )
        assert "error" in result
        assert "404" in result["error"]

    @patch("check_tooling_health.requests.get")
    def test_401_error(self, mock_get):
        mock_get.return_value = MagicMock(status_code=401, text="Unauthorized")

        result = check_tooling_health._fetch_workflow_runs(
            "org/repo", "workflow.yaml", "main", 5, "bad_token", "prod"
        )
        assert "error" in result
        assert "401" in result["error"]

    @patch("check_tooling_health.requests.get")
    def test_network_error(self, mock_get):
        import requests

        mock_get.side_effect = requests.ConnectionError("Connection refused")

        result = check_tooling_health._fetch_workflow_runs(
            "org/repo", "workflow.yaml", "main", 5, "token123", "prod"
        )
        assert "error" in result
        assert "request failed" in result["error"]


# ---------------------------------------------------------------------------
# Full check_all_tools tests
# ---------------------------------------------------------------------------


class TestCheckAllTools:
    @patch("check_tooling_health.github_ops.get_token")
    @patch("check_tooling_health.requests.get")
    def test_healthy_result(self, mock_get, mock_token):
        mock_token.return_value = "ghp_test123"
        runs = [_make_run(1, conclusion="success")]
        mock_get.return_value = _api_response(runs)

        result = check_tooling_health.check_all_tools(
            "rhoai-3.5-ea.1", environment="prod", catalog_path=None
        )
        assert result["release"] == "rhoai-3.5-ea.1"
        assert result["overall_health"] == "healthy"
        assert len(result["tools"]) >= 0

    @patch("check_tooling_health.github_ops.get_token")
    @patch("check_tooling_health.requests.get")
    def test_unhealthy_result(self, mock_get, mock_token):
        mock_token.return_value = "ghp_test123"
        runs = [_make_run(3, conclusion="failure"), _make_run(2, conclusion="failure"), _make_run(1, conclusion="success")]
        mock_get.return_value = _api_response(runs)

        with patch("check_tooling_health.load_catalog", return_value=SAMPLE_CATALOG):
            result = check_tooling_health.check_all_tools("rhoai-3.5-ea.1", environment="prod")

        assert result["overall_health"] == "unhealthy"
        tool = result["tools"][0]
        assert tool["health"]["status"] == "unhealthy"
        assert tool["health"]["consecutive_failures"] == 2

    @patch("check_tooling_health.github_ops.get_token")
    def test_no_token(self, mock_token):
        mock_token.return_value = ""

        result = check_tooling_health.check_all_tools("rhoai-3.5-ea.1", environment="prod")
        assert result["overall_health"] == "error"
        assert "error" in result

    @patch("check_tooling_health.github_ops.get_token")
    @patch("check_tooling_health.requests.get")
    def test_in_progress_result(self, mock_get, mock_token):
        mock_token.return_value = "ghp_test123"
        runs = [
            _make_run(2, status="in_progress", conclusion=None),
            _make_run(1, conclusion="success"),
        ]
        mock_get.return_value = _api_response(runs)

        with patch("check_tooling_health.load_catalog", return_value=SAMPLE_CATALOG):
            result = check_tooling_health.check_all_tools("rhoai-3.5-ea.1", environment="prod")

        assert result["overall_health"] == "in_progress"


# ---------------------------------------------------------------------------
# Overall health computation tests
# ---------------------------------------------------------------------------


class TestComputeOverallHealth:
    def test_single_healthy(self):
        tools = [{"health": {"status": "healthy"}}]
        assert check_tooling_health._compute_overall_health(tools) == "healthy"

    def test_worst_wins(self):
        tools = [
            {"health": {"status": "healthy"}},
            {"health": {"status": "unhealthy"}},
        ]
        assert check_tooling_health._compute_overall_health(tools) == "unhealthy"

    def test_error_is_worst(self):
        tools = [
            {"health": {"status": "unhealthy"}},
            {"health": {"status": "error"}},
        ]
        assert check_tooling_health._compute_overall_health(tools) == "error"

    def test_empty_tools(self):
        assert check_tooling_health._compute_overall_health([]) == "error"


# ---------------------------------------------------------------------------
# Output file tests
# ---------------------------------------------------------------------------


class TestCLIOutput:
    @patch("check_tooling_health.github_ops.get_token")
    @patch("check_tooling_health.requests.get")
    def test_writes_json_file(self, mock_get, mock_token, tmp_path):
        mock_token.return_value = "ghp_test123"
        runs = [_make_run(1, conclusion="success")]
        mock_get.return_value = _api_response(runs)

        output_file = tmp_path / "health.json"

        with patch("check_tooling_health.load_catalog", return_value=SAMPLE_CATALOG):
            with patch("sys.argv", ["check_tooling_health.py", "--release", "rhoai-3.5-ea.1", "--environment", "prod", "--output", str(output_file)]):
                exit_code = check_tooling_health.main()

        assert exit_code == 0
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert data["release"] == "rhoai-3.5-ea.1"
        assert "tools" in data
        assert "overall_health" in data


# ---------------------------------------------------------------------------
# Resolution guide integration tests
# ---------------------------------------------------------------------------


class TestResolutionGuideIntegration:
    def test_render_tooling_health_unhealthy(self):
        from generate_resolution_guide import _render_tooling_health

        data = {
            "tools": [
                {
                    "name": "conforma-reporter",
                    "latest_run": {
                        "id": 12345,
                        "url": "https://github.com/org/repo/actions/runs/12345",
                        "conclusion": "failure",
                        "updated_at": "2026-06-17T10:05:00Z",
                    },
                    "health": {
                        "status": "unhealthy",
                        "consecutive_failures": 3,
                        "last_success": {
                            "id": 12340,
                            "url": "https://github.com/org/repo/actions/runs/12340",
                            "completed_at": "2026-06-15T10:05:00Z",
                        },
                    },
                }
            ],
        }
        result = _render_tooling_health(data)
        assert "## Tooling Health" in result
        assert "UNHEALTHY" in result
        assert "#12345" in result
        assert "conforma-reporter" in result
        assert "stale" in result

    def test_render_tooling_health_healthy(self):
        from generate_resolution_guide import _render_tooling_health

        data = {
            "tools": [
                {
                    "name": "conforma-reporter",
                    "latest_run": {
                        "id": 100,
                        "url": "https://github.com/org/repo/actions/runs/100",
                        "conclusion": "success",
                        "updated_at": "2026-06-18T10:00:00Z",
                    },
                    "health": {
                        "status": "healthy",
                        "consecutive_failures": 0,
                        "last_success": {
                            "id": 100,
                            "url": "https://github.com/org/repo/actions/runs/100",
                            "completed_at": "2026-06-18T10:00:00Z",
                        },
                    },
                }
            ],
        }
        result = _render_tooling_health(data)
        assert "## Tooling Health" in result
        assert "HEALTHY" in result
        assert "stale" not in result

    def test_render_tooling_health_empty(self):
        from generate_resolution_guide import _render_tooling_health

        result = _render_tooling_health({"tools": []})
        assert result == ""

    def test_executive_line_unhealthy(self):
        from generate_resolution_guide import _tooling_health_executive_line

        data = {
            "tools": [
                {
                    "name": "conforma-reporter",
                    "latest_run": {
                        "url": "https://github.com/org/repo/actions/runs/12345",
                    },
                    "health": {
                        "status": "unhealthy",
                        "last_success": {
                            "completed_at": "2026-06-15T10:05:00Z",
                        },
                    },
                }
            ],
        }
        line = _tooling_health_executive_line(data)
        assert line is not None
        assert "**Tooling unhealthy**" in line
        assert "conforma-reporter" in line
        assert "2026-06-15" in line

    def test_executive_line_healthy_returns_none(self):
        from generate_resolution_guide import _tooling_health_executive_line

        data = {
            "tools": [
                {
                    "name": "conforma-reporter",
                    "health": {"status": "healthy"},
                }
            ],
        }
        line = _tooling_health_executive_line(data)
        assert line is None
