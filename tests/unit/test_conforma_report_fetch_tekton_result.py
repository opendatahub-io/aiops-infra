"""Tests for conforma-report-fetch fetch_conforma_tekton_result.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import fetch_conforma_tekton_result as ftr


# ---------------------------------------------------------------------------
# Version parsing
# ---------------------------------------------------------------------------


class TestParseVersionShortcode:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("3.5", "v3-5"),
            ("3.5ea.2", "v3-5-ea-2"),
            ("3.5-ea.1", "v3-5-ea-1"),
            ("3.5 ea 1", "v3-5-ea-1"),
            ("v3.5", "v3-5"),
            ("rhoai-3.5", "v3-5"),
            ("rhoai 3.5ea.2", "v3-5-ea-2"),
            ("RHOAI-3.5", "v3-5"),
        ],
    )
    def test_valid_shortcodes(self, raw, expected):
        assert ftr.parse_version_shortcode(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "conforma-registry-rhoai-prod-v3-5-abcde",
            "some-random-string",
            "",
        ],
    )
    def test_non_shortcodes(self, raw):
        assert ftr.parse_version_shortcode(raw) is None


class TestVersionDirToSlug:
    @pytest.mark.parametrize(
        "version_dir, expected",
        [
            ("v3.5", "v3-5"),
            ("v3.5-ea.1", "v3-5-ea-1"),
            ("v3.5-ea.2", "v3-5-ea-2"),
        ],
    )
    def test_slug_conversion(self, version_dir, expected):
        assert ftr.version_dir_to_slug(version_dir) == expected


# ---------------------------------------------------------------------------
# ITS prefix construction
# ---------------------------------------------------------------------------


class TestBuildItsPrefix:
    @pytest.mark.parametrize(
        "policy_type, app_name, environment, version_slug, expected",
        [
            ("registry", "rhoai", "prod", "v3-5", "conforma-registry-rhoai-prod-v3-5"),
            ("registry", "rhoai", "stage", "v3-5-ea-1", "conforma-registry-rhoai-stage-v3-5-ea-1"),
            ("chart", "rhoai", "prod", "v3-5", "conforma-registry-rhoai-chart-prod-v3-5"),
            ("chart", "rhoai", "stage", "v3-5-ea-2", "conforma-registry-rhoai-chart-stage-v3-5-ea-2"),
            ("fbc", "rhoai", "prod", "v3-5", "conforma-fbc-rhoai-prod-v3-5"),
            ("fbc", "rhoai", "stage", "v3-5-ea-1", "conforma-fbc-rhoai-stage-v3-5-ea-1"),
        ],
    )
    def test_prefix_for_all_types(self, policy_type, app_name, environment, version_slug, expected):
        assert ftr.build_its_prefix(policy_type, app_name, environment, version_slug) == expected

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown policy type"):
            ftr.build_its_prefix("unknown", "rhoai", "prod", "v3-5")


# ---------------------------------------------------------------------------
# Regex filtering
# ---------------------------------------------------------------------------


class TestPipelineRunRegexFiltering:
    """Verify that the regex pattern correctly matches primary/future runs
    and avoids GA/EA cross-matching."""

    def test_ga_prefix_matches_ga_run(self):
        import re
        prefix = "conforma-registry-rhoai-prod-v3-5"
        regex = re.compile(f"^{re.escape(prefix)}-[a-z0-9]+$")
        assert regex.match("conforma-registry-rhoai-prod-v3-5-abcde")

    def test_ga_prefix_does_not_match_ea_run(self):
        import re
        prefix = "conforma-registry-rhoai-prod-v3-5"
        regex = re.compile(f"^{re.escape(prefix)}-[a-z0-9]+$")
        assert not regex.match("conforma-registry-rhoai-prod-v3-5-ea-1-fghij")

    def test_ea_prefix_matches_ea_run(self):
        import re
        prefix = "conforma-registry-rhoai-prod-v3-5-ea-1"
        regex = re.compile(f"^{re.escape(prefix)}-[a-z0-9]+$")
        assert regex.match("conforma-registry-rhoai-prod-v3-5-ea-1-xyz12")

    def test_does_not_match_future_suffix(self):
        import re
        prefix = "conforma-registry-rhoai-prod-v3-5"
        regex = re.compile(f"^{re.escape(prefix)}-[a-z0-9]+$")
        assert not regex.match("conforma-registry-rhoai-prod-v3-5-future-abc12")

    def test_does_not_match_single_component(self):
        import re
        prefix = "conforma-registry-rhoai-prod-v3-5"
        regex = re.compile(f"^{re.escape(prefix)}-[a-z0-9]+$")
        assert not regex.match("conforma-registry-rhoai-prod-v3-5-single-component-abc12")


# ---------------------------------------------------------------------------
# PipelineRun discovery
# ---------------------------------------------------------------------------


class TestDiscoverPipelinerun:
    def test_primary_match_from_live_cluster(self):
        runs = [
            "conforma-registry-rhoai-prod-v3-5-abc12",
            "conforma-registry-rhoai-prod-v3-5-def34",
        ]
        with patch.object(ftr, "_oc_list_pipelineruns", return_value=runs):
            result = ftr.discover_pipelinerun(
                "conforma-registry-rhoai-prod-v3-5",
                "rhoai-tenant", "https://api.example.com", "token",
            )
        assert result == "conforma-registry-rhoai-prod-v3-5-def34"

    def test_future_fallback(self):
        runs = [
            "conforma-registry-rhoai-prod-v3-5-future-abc12",
            "conforma-registry-rhoai-prod-v3-5-future-def34",
        ]
        with patch.object(ftr, "_oc_list_pipelineruns", return_value=runs):
            result = ftr.discover_pipelinerun(
                "conforma-registry-rhoai-prod-v3-5",
                "rhoai-tenant", "https://api.example.com", "token",
            )
        assert result == "conforma-registry-rhoai-prod-v3-5-future-def34"

    def test_archive_fallback(self):
        with (
            patch.object(ftr, "_oc_list_pipelineruns", return_value=[]),
            patch.object(ftr, "_search_tekton_api_for_name",
                         return_value="conforma-registry-rhoai-prod-v3-5-xyz99"),
        ):
            result = ftr.discover_pipelinerun(
                "conforma-registry-rhoai-prod-v3-5",
                "rhoai-tenant", "https://api.example.com", "token",
            )
        assert result == "conforma-registry-rhoai-prod-v3-5-xyz99"

    def test_nothing_found(self):
        with (
            patch.object(ftr, "_oc_list_pipelineruns", return_value=[]),
            patch.object(ftr, "_search_tekton_api_for_name", return_value=None),
        ):
            result = ftr.discover_pipelinerun(
                "conforma-registry-rhoai-prod-v3-5",
                "rhoai-tenant", "https://api.example.com", "token",
            )
        assert result is None

    def test_ga_runs_excluded_when_searching_ea(self):
        runs = [
            "conforma-registry-rhoai-prod-v3-5-abc12",
            "conforma-registry-rhoai-prod-v3-5-ea-1-def34",
        ]
        with patch.object(ftr, "_oc_list_pipelineruns", return_value=runs):
            result = ftr.discover_pipelinerun(
                "conforma-registry-rhoai-prod-v3-5-ea-1",
                "rhoai-tenant", "https://api.example.com", "token",
            )
        assert result == "conforma-registry-rhoai-prod-v3-5-ea-1-def34"

    def test_newest_run_selected(self):
        runs = [
            "conforma-registry-rhoai-prod-v3-5-aaa11",
            "conforma-registry-rhoai-prod-v3-5-bbb22",
            "conforma-registry-rhoai-prod-v3-5-ccc33",
        ]
        with patch.object(ftr, "_oc_list_pipelineruns", return_value=runs):
            result = ftr.discover_pipelinerun(
                "conforma-registry-rhoai-prod-v3-5",
                "rhoai-tenant", "https://api.example.com", "token",
            )
        assert result == "conforma-registry-rhoai-prod-v3-5-ccc33"


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------


class TestResolve:
    def test_cli_wins(self):
        assert ftr._resolve("cli_val", {"a": "ctx_val"}, "a", default="def") == "cli_val"

    def test_context_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "env_val")
        assert ftr._resolve(None, {"a": "ctx_val"}, "a", env_var="MY_VAR", default="def") == "ctx_val"

    def test_env_wins_over_default(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "env_val")
        assert ftr._resolve(None, None, "a.b", env_var="MY_VAR", default="def") == "env_val"

    def test_default_used_last(self, monkeypatch):
        monkeypatch.delenv("MY_VAR", raising=False)
        assert ftr._resolve(None, None, "a.b", env_var="MY_VAR", default="def") == "def"

    def test_nested_context_key(self):
        ctx = {"resolve": {"tenant": "my-ns"}}
        assert ftr._resolve(None, ctx, "resolve.tenant") == "my-ns"

    def test_missing_nested_key(self):
        ctx = {"resolve": {}}
        assert ftr._resolve(None, ctx, "resolve.tenant", default="fallback") == "fallback"


# ---------------------------------------------------------------------------
# Log extraction
# ---------------------------------------------------------------------------


class TestExtractReportFromLog:
    SAMPLE_LOG = (
        "step-init :- Initializing...\n"
        "step-init :- Done.\n"
        "step-detailed-report :-\n"
        "{\"components\": [{\"name\": \"comp-a\"}]}\n"
        "{\"violations\": [{\"code\": \"hermetic_task.hermetic\"}]}\n"
        "step-summary :- Summary goes here.\n"
    )

    def test_extracts_report_section(self):
        report = ftr.extract_report_from_log(self.SAMPLE_LOG)
        assert '{"components"' in report
        assert '{"violations"' in report

    def test_excludes_other_steps(self):
        report = ftr.extract_report_from_log(self.SAMPLE_LOG)
        assert "Initializing" not in report
        assert "Summary goes here" not in report

    def test_empty_log(self):
        assert ftr.extract_report_from_log("") == ""

    def test_no_matching_step(self):
        log = "step-other :- Some content\nstep-another :- More content\n"
        assert ftr.extract_report_from_log(log) == ""

    def test_custom_step_name(self):
        log = "my-step :-\ndata line 1\ndata line 2\nstep-next :- end\n"
        report = ftr.extract_report_from_log(log, step_name="my-step")
        assert "data line 1" in report
        assert "data line 2" in report


# ---------------------------------------------------------------------------
# Handover assembly
# ---------------------------------------------------------------------------


class TestBuildHandover:
    def test_success_handover(self):
        h = ftr.build_handover({}, "run-abc", "rhoai-tenant", "/tmp/report.json")
        assert h["report_fetch"]["status"] == "completed"
        assert h["report_fetch"]["raw_report_path"] == "/tmp/report.json"
        assert h["report_fetch"]["error"] is None
        assert h["metadata"]["pipeline_run"] == "run-abc"
        assert h["metadata"]["namespace"] == "rhoai-tenant"
        assert h["violation_parse"] is None
        assert h["investigation"] is None

    def test_failure_handover(self):
        h = ftr.build_handover({}, "run-abc", "rhoai-tenant", None, error="Log empty")
        assert h["report_fetch"]["status"] == "failed"
        assert h["report_fetch"]["error"] == "Log empty"

    def test_preserves_initial_state(self):
        initial = {"custom_key": "custom_value", "metadata": {"extra": "data"}}
        h = ftr.build_handover(initial, "run-abc", "rhoai-tenant", "/tmp/r.json")
        assert h["custom_key"] == "custom_value"
        assert h["metadata"]["extra"] == "data"
        assert h["metadata"]["pipeline_run"] == "run-abc"

    def test_does_not_overwrite_existing_metadata_fields(self):
        initial = {"metadata": {"created_at": "2026-01-01T00:00:00Z"}}
        h = ftr.build_handover(initial, "run-abc", "rhoai-tenant", "/tmp/r.json")
        assert h["metadata"]["created_at"] == "2026-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestGetToken:
    def test_env_token(self, monkeypatch):
        monkeypatch.setenv("KONFLUX_TOKEN", "env-token-123")
        assert ftr._get_token() == "env-token-123"

    def test_oc_fallback(self, monkeypatch):
        monkeypatch.delenv("KONFLUX_TOKEN", raising=False)
        mock_proc = MagicMock(returncode=0, stdout="oc-token-456\n")
        with patch("fetch_conforma_tekton_result.subprocess.run", return_value=mock_proc):
            assert ftr._get_token() == "oc-token-456"

    def test_no_auth_exits(self, monkeypatch):
        monkeypatch.delenv("KONFLUX_TOKEN", raising=False)
        mock_proc = MagicMock(returncode=1, stdout="")
        with (
            patch("fetch_conforma_tekton_result.subprocess.run", return_value=mock_proc),
            pytest.raises(SystemExit),
        ):
            ftr._get_token()


# ---------------------------------------------------------------------------
# Context step writes
# ---------------------------------------------------------------------------


class TestWriteStepStatus:
    def test_completed_step(self, tmp_path):
        import conforma_context_ops
        conforma_context_ops.create(tmp_path, {"steps": {}})

        config = {"run_dir": tmp_path, "policy_type": "registry"}
        ftr._write_step_status(config, "run-abc", "/tmp/report.json", None)

        ctx = conforma_context_ops.load(tmp_path)
        assert ctx["steps"]["tekton_fetch"]["status"] == "completed"
        assert ctx["steps"]["tekton_fetch"]["raw_report_path"] == "/tmp/report.json"
        assert ctx["steps"]["tekton_fetch"]["pipeline_run"] == "run-abc"

    def test_failed_step(self, tmp_path):
        import conforma_context_ops
        conforma_context_ops.create(tmp_path, {"steps": {}})

        config = {"run_dir": tmp_path, "policy_type": "registry"}
        ftr._write_step_status(config, "run-abc", None, "Something went wrong")

        ctx = conforma_context_ops.load(tmp_path)
        assert ctx["steps"]["tekton_fetch"]["status"] == "failed"
        assert ctx["steps"]["tekton_fetch"]["error"] == "Something went wrong"

    def test_no_run_dir_is_noop(self):
        config = {"run_dir": None, "policy_type": "registry"}
        ftr._write_step_status(config, "run-abc", "/tmp/report.json", None)


# ---------------------------------------------------------------------------
# UUID resolution
# ---------------------------------------------------------------------------


class TestResolvePipelinerunUuid:
    def test_live_cluster(self):
        mock_proc = MagicMock(returncode=0, stdout="uuid-1234-5678\n")
        with patch("fetch_conforma_tekton_result.subprocess.run", return_value=mock_proc):
            result = ftr._resolve_pipelinerun_uuid(
                "run-abc", "rhoai-tenant", "https://api.example.com", "token",
            )
        assert result == "uuid-1234-5678"

    def test_api_fallback(self):
        mock_proc = MagicMock(returncode=1, stdout="")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "records": [{"name": "rhoai-tenant/results/aaa-bbb-ccc/records/ddd"}]
        }
        mock_resp.raise_for_status = MagicMock()

        with (
            patch("fetch_conforma_tekton_result.subprocess.run", return_value=mock_proc),
            patch("fetch_conforma_tekton_result.requests.get", return_value=mock_resp),
        ):
            result = ftr._resolve_pipelinerun_uuid(
                "run-abc", "rhoai-tenant", "https://api.example.com", "token",
            )
        assert result == "aaa-bbb-ccc"

    def test_not_found(self):
        mock_proc = MagicMock(returncode=1, stdout="")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"records": []}
        mock_resp.raise_for_status = MagicMock()

        with (
            patch("fetch_conforma_tekton_result.subprocess.run", return_value=mock_proc),
            patch("fetch_conforma_tekton_result.requests.get", return_value=mock_resp),
        ):
            result = ftr._resolve_pipelinerun_uuid(
                "run-abc", "rhoai-tenant", "https://api.example.com", "token",
            )
        assert result is None


# ---------------------------------------------------------------------------
# Write output
# ---------------------------------------------------------------------------


class TestWriteOutput:
    def test_writes_to_file(self, tmp_path):
        output_file = tmp_path / "output.json"
        handover = {"report_fetch": {"status": "completed"}}
        ftr._write_output(handover, str(output_file))
        loaded = json.loads(output_file.read_text())
        assert loaded["report_fetch"]["status"] == "completed"

    def test_writes_to_stdout(self, capsys):
        handover = {"report_fetch": {"status": "completed"}}
        ftr._write_output(handover, None)
        captured = capsys.readouterr()
        loaded = json.loads(captured.out)
        assert loaded["report_fetch"]["status"] == "completed"
