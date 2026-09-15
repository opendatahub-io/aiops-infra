"""Extended tests for conforma-analyze violations_coverage.py — covers branches missed by the base test file.

Targets previously uncovered lines:
  _build_component_exception_details, _load_component_policy_mapping,
  _map_component_to_policy, _group_components_by_policy, _run_ec_coverage,
  check_violations_coverage (auth, no-components, self-service, labels),
  _render_violations_markdown_table (header variants), main() edge cases.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

import conforma_context_ops
import conforma_ec_validate
import conforma_jira_ops
import conforma_mr_ops
import conforma_policy_ops
import conforma_slack_ops
import component_alias_ops
import jira_ops
import slack_ops
import violations_coverage as mod


# ──────────────────────────────────────────────────────────────────────────────
# _build_component_exception_details
# ──────────────────────────────────────────────────────────────────────────────


class TestBuildComponentExceptionDetails:
    def _gate(self, **overrides):
        base = {
            "status": "blocked",
            "permanent_exclusions": [],
            "active_exceptions": [],
            "open_merge_requests": [],
        }
        base.update(overrides)
        return base

    def test_permanent_exclusion_in_policy(self, monkeypatch):
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_HOST", "gitlab.com")
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_PROJECT", "releng/policies")

        gate = self._gate(
            permanent_exclusions=[{"file": "config/x/product/rhoai.yaml", "line": 42}],
        )
        result = mod._build_component_exception_details(
            gate, ["comp-a", "comp-b"], policy_files=["config/x/product/rhoai.yaml"]
        )
        assert len(result) == 2
        for r in result:
            assert r["file"] == "rhoai.yaml"
            assert r["line"] == 42
            assert "gitlab.com" in r["url"]
            assert "#L42" in r["url"]

    def test_permanent_exclusion_outside_policy(self, monkeypatch):
        """permanent exclusion file not in policy_files → skipped."""
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_HOST", "gitlab.com")
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_PROJECT", "releng/policies")

        gate = self._gate(
            permanent_exclusions=[{"file": "config/x/product/other.yaml", "line": 10}],
        )
        result = mod._build_component_exception_details(
            gate, ["comp-a"], policy_files=["config/x/product/rhoai.yaml"]
        )
        assert result[0]["file"] is None
        assert result[0]["url"] is None

    def test_active_exception_with_coverage(self, monkeypatch):
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_HOST", "gitlab.com")
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_PROJECT", "releng/policies")

        gate = self._gate(
            active_exceptions=[
                {
                    "file": "config/x/product/rhoai.yaml",
                    "line": 99,
                    "effectiveUntil": "2027-01-15",
                    "exception_value": "exclude",
                    "covers_components": ["comp-a"],
                }
            ]
        )
        result = mod._build_component_exception_details(
            gate, ["comp-a", "comp-b"], policy_files=["config/x/product/rhoai.yaml"]
        )
        a = result[0]
        b = result[1]
        assert a["component"] == "comp-a"
        assert a["effective_until"] == "2027-01-15"
        assert a["exception_value"] == "exclude"
        assert b["component"] == "comp-b"
        assert b["file"] is None

    def test_url_without_line(self, monkeypatch):
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_HOST", "gitlab.com")
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_PROJECT", "releng/policies")

        gate = self._gate(
            active_exceptions=[
                {
                    "file": "rhoai.yaml",
                    "line": None,
                    "effectiveUntil": None,
                    "exception_value": "",
                    "covers_components": ["comp-a"],
                }
            ]
        )
        result = mod._build_component_exception_details(gate, ["comp-a"], policy_files=["rhoai.yaml"])
        assert "blob/main/rhoai.yaml" in result[0]["url"]
        assert "#L" not in result[0]["url"]

    def test_url_none_when_no_host(self, monkeypatch):
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_HOST", "")
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_PROJECT", "")

        gate = self._gate(
            active_exceptions=[
                {
                    "file": "rhoai.yaml",
                    "line": 5,
                    "effectiveUntil": "2027-01-01",
                    "exception_value": "",
                    "covers_components": ["comp-a"],
                }
            ]
        )
        result = mod._build_component_exception_details(gate, ["comp-a"])
        assert result[0]["url"] is None

    def test_no_policy_files_filtering(self, monkeypatch):
        """When policy_files is None, all files are allowed."""
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_HOST", "gitlab.com")
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_PROJECT", "releng/policies")

        gate = self._gate(
            active_exceptions=[
                {
                    "file": "any-file.yaml",
                    "line": 1,
                    "effectiveUntil": None,
                    "exception_value": "",
                    "covers_components": ["comp-a"],
                }
            ]
        )
        result = mod._build_component_exception_details(gate, ["comp-a"], policy_files=None)
        assert result[0]["file"] == "any-file.yaml"


# ──────────────────────────────────────────────────────────────────────────────
# _load_component_policy_mapping
# ──────────────────────────────────────────────────────────────────────────────


class TestLoadComponentPolicyMapping:
    def test_missing_file_returns_empty(self, tmp_path):
        result = mod._load_component_policy_mapping(mapping_file=tmp_path / "nope.yaml")
        assert result == []

    def test_loads_rules(self, tmp_path):
        mapping = tmp_path / "mapping.yaml"
        mapping.write_text(yaml.dump({"rules": [{"pattern": "*", "policy_prefix": "fbc-"}]}))
        result = mod._load_component_policy_mapping(mapping_file=mapping)
        assert len(result) == 1
        assert result[0]["policy_prefix"] == "fbc-"


# ──────────────────────────────────────────────────────────────────────────────
# _map_component_to_policy
# ──────────────────────────────────────────────────────────────────────────────


class TestMapComponentToPolicy:
    def test_pattern_match_with_prefix(self):
        paths = [Path("fbc-rhoai-prod.yaml"), Path("registry-rhoai-prod.yaml")]
        rules = [{"pattern": "odh-*", "policy_prefix": "fbc-"}]
        result = mod._map_component_to_policy("odh-model-server", paths, rules)
        assert result.name == "fbc-rhoai-prod.yaml"

    def test_no_match_returns_none(self):
        paths = [Path("fbc-rhoai-prod.yaml")]
        rules = [{"pattern": "kserve-*", "policy_prefix": "fbc-"}]
        result = mod._map_component_to_policy("odh-model-server", paths, rules)
        assert result is None

    def test_must_contain_filter(self):
        paths = [Path("fbc-rhoai-hermetic-prod.yaml"), Path("fbc-rhoai-prod.yaml")]
        rules = [{"pattern": "odh-*", "policy_prefix": "fbc-", "policy_must_contain": "hermetic"}]
        result = mod._map_component_to_policy("odh-model-server", paths, rules)
        assert result.name == "fbc-rhoai-hermetic-prod.yaml"

    def test_must_not_contain_filter(self):
        paths = [Path("fbc-rhoai-hermetic-prod.yaml"), Path("fbc-rhoai-prod.yaml")]
        rules = [{"pattern": "odh-*", "policy_prefix": "fbc-", "policy_must_not_contain": "hermetic"}]
        result = mod._map_component_to_policy("odh-model-server", paths, rules)
        assert result.name == "fbc-rhoai-prod.yaml"

    def test_no_rules_returns_none(self):
        result = mod._map_component_to_policy("comp-a", [Path("fbc.yaml")], [])
        assert result is None


# ──────────────────────────────────────────────────────────────────────────────
# _group_components_by_policy
# ──────────────────────────────────────────────────────────────────────────────


class TestGroupComponentsByPolicy:
    def test_groups_by_policy(self, capsys):
        paths = [Path("fbc-rhoai.yaml"), Path("registry-rhoai.yaml")]
        rules = [
            {"pattern": "odh-*", "policy_prefix": "fbc-"},
            {"pattern": "kserve-*", "policy_prefix": "registry-"},
        ]
        result = mod._group_components_by_policy(["odh-a", "odh-b", "kserve-c"], paths, rules)
        assert "odh-a" in result[paths[0]]
        assert "odh-b" in result[paths[0]]
        assert "kserve-c" in result[paths[1]]

    def test_unmapped_components_logged(self, capsys):
        paths = [Path("fbc-rhoai.yaml")]
        rules = [{"pattern": "odh-*", "policy_prefix": "fbc-"}]
        result = mod._group_components_by_policy(["odh-a", "unknown-comp"], paths, rules)
        captured = capsys.readouterr()
        assert "unknown-comp" in captured.err
        assert "not mapped" in captured.err


# ──────────────────────────────────────────────────────────────────────────────
# _run_ec_coverage
# ──────────────────────────────────────────────────────────────────────────────


def _mock_ec_happy(monkeypatch, tmp_path, ec_violations=None, ec_successes=None, validation=None):
    """Patch the ec_validate helpers for a happy-path _run_ec_coverage run."""
    monkeypatch.setattr(mod.conforma_ec_validate, "ensure_ec_binary", lambda *a, **k: "/usr/bin/ec")
    monkeypatch.setattr(
        mod.conforma_ec_validate, "build_snapshot_from_csv",
        lambda *a, **k: (str(tmp_path / "spec.json"), [{"name": "odh-a-v3-4", "image": "quay.io/x@sha256:aaa"}]),
    )
    monkeypatch.setattr(
        mod.conforma_ec_validate, "group_entries_by_base_image",
        lambda *a, **k: {"quay.io/x": [{"name": "odh-a-v3-4", "image": "quay.io/x@sha256:aaa"}]},
    )
    monkeypatch.setattr(
        mod.conforma_ec_validate, "prepare_policy_for_local_use",
        lambda *a, **k: str(tmp_path / "policy-local.yaml"),
    )
    monkeypatch.setattr(
        mod.conforma_ec_validate, "build_snapshot_from_entries",
        lambda *a, **k: str(tmp_path / "batch-spec.json"),
    )
    monkeypatch.setattr(
        mod.conforma_ec_validate, "run_ec_validate",
        lambda *a, **k: {"violations": {}, "successes": {}},
    )
    monkeypatch.setattr(
        mod.conforma_ec_validate, "extract_ec_violations",
        lambda *a, **k: ec_violations if ec_violations is not None else {"odh-a-v3-4": {"rule.x"}},
    )
    monkeypatch.setattr(
        mod.conforma_ec_validate, "extract_ec_successes",
        lambda *a, **k: ec_successes if ec_successes is not None else {},
    )
    monkeypatch.setattr(mod.conforma_ec_validate, "extract_csv_violations", lambda *a, **k: {})
    monkeypatch.setattr(
        mod.conforma_ec_validate, "validate_ec_against_csv",
        lambda *a, **k: validation if validation is not None
        else {"validated": True, "confirmed_violations": 1, "confirmed_covered": 0, "divergence_count": 0},
    )
    monkeypatch.setattr(
        mod, "_load_component_policy_mapping",
        lambda *a, **k: [{"pattern": "odh-*", "policy_prefix": "fbc-"}],
    )


def _make_clone(tmp_path, monkeypatch, basenames):
    """Create a minimal clone dir with policy files under the KRD path."""
    monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "test.cluster")
    policy_dir = tmp_path / "config" / "test.cluster" / "product" / "EnterpriseContractPolicy"
    policy_dir.mkdir(parents=True)
    for name in basenames:
        (policy_dir / name).write_text("exclude: []\n")
    return tmp_path


def _write_csv(tmp_path):
    csv = tmp_path / "rhoai-3.4.csv"
    csv.write_text("type,component_name,image\nviolation,odh-a-v3-4,quay.io/x@sha256:aaa\n")
    return csv


class TestRunEcCoverage:
    def test_no_policy_files_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KONFLUX_CLUSTER_DOMAIN", raising=False)
        monkeypatch.delenv("KONFLUX_CONFORMA_POLICY_DIR", raising=False)
        csv = _write_csv(tmp_path)
        with pytest.raises(conforma_ec_validate.EcValidateError, match="Cannot find any policy"):
            mod._run_ec_coverage(str(csv), str(tmp_path), ["fbc-rhoai.yaml"], "prod")

    def test_policy_dir_missing_returns_error(self, tmp_path, monkeypatch):
        """KONFLUX_CONFORMA_POLICY_DIR set but dir doesn't exist in clone."""
        monkeypatch.delenv("KONFLUX_CLUSTER_DOMAIN", raising=False)
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", "missing/dir")
        csv = _write_csv(tmp_path)
        with pytest.raises(conforma_ec_validate.EcValidateError, match="Cannot find any policy"):
            mod._run_ec_coverage(str(csv), str(tmp_path), ["fbc-rhoai.yaml"], "prod")

    def test_no_ec_dir_configured_raises(self, tmp_path, monkeypatch):
        """_find_all_policy_file_paths returns empty → error."""
        monkeypatch.setattr(mod, "_find_all_policy_file_paths", lambda *a, **k: [])
        csv = _write_csv(tmp_path)
        with pytest.raises(conforma_ec_validate.EcValidateError):
            mod._run_ec_coverage(str(csv), str(tmp_path), ["fbc-rhoai.yaml"], "prod")

    def test_full_ec_flow(self, tmp_path, monkeypatch, capsys):
        clone = _make_clone(tmp_path, monkeypatch, ["fbc-rhoai-prod.yaml"])
        csv = _write_csv(tmp_path)
        _mock_ec_happy(monkeypatch, tmp_path)
        result = mod._run_ec_coverage(str(csv), str(clone), ["fbc-rhoai-prod.yaml"], "prod")
        assert "odh-a-v3-4" in result["violations"]
        assert result["validation"]["validated"] is True
        captured = capsys.readouterr()
        assert "Baseline validation passed" in captured.err

    def test_validation_divergence_warning(self, tmp_path, monkeypatch, capsys):
        """Validation fails → divergence warning logged."""
        clone = _make_clone(tmp_path, monkeypatch, ["fbc-rhoai-prod.yaml"])
        csv = _write_csv(tmp_path)
        _mock_ec_happy(
            monkeypatch, tmp_path,
            validation={"validated": False, "confirmed_violations": 0, "confirmed_covered": 0, "divergence_count": 2},
        )
        mod._run_ec_coverage(str(csv), str(clone), ["fbc-rhoai-prod.yaml"], "prod")
        captured = capsys.readouterr()
        assert "WARNING" in captured.err
        assert "not evaluated by Conforma now" in captured.err

    def test_ec_batch_failure_continues(self, tmp_path, monkeypatch, capsys):
        """EcValidateError during a batch → logged, batch counted as failed."""
        clone = _make_clone(tmp_path, monkeypatch, ["fbc-rhoai-prod.yaml"])
        csv = _write_csv(tmp_path)
        _mock_ec_happy(monkeypatch, tmp_path)

        def _crash(*a, **k):
            raise conforma_ec_validate.EcValidateError("binary crashed")

        monkeypatch.setattr(mod.conforma_ec_validate, "run_ec_validate", _crash)
        mod._run_ec_coverage(str(csv), str(clone), ["fbc-rhoai-prod.yaml"], "prod")
        captured = capsys.readouterr()
        assert "FAILED" in captured.err
        assert "0/1 batches succeeded" in captured.err

    def test_policy_with_no_mapped_components_skipped(self, tmp_path, monkeypatch, capsys):
        """Policy with no mapped components → skipped with log message."""
        clone = _make_clone(tmp_path, monkeypatch, ["fbc-rhoai-prod.yaml", "registry-rhoai-prod.yaml"])
        csv = _write_csv(tmp_path)
        _mock_ec_happy(monkeypatch, tmp_path)
        mod._run_ec_coverage(str(csv), str(clone), ["fbc-rhoai-prod.yaml", "registry-rhoai-prod.yaml"], "prod")
        captured = capsys.readouterr()
        assert "Skipping registry-rhoai-prod.yaml" in captured.err

    def test_merge_multiple_batches(self, tmp_path, monkeypatch):
        """Multiple batches merge violations and successes."""
        clone = _make_clone(tmp_path, monkeypatch, ["fbc-rhoai-prod.yaml"])
        csv = _write_csv(tmp_path)
        _mock_ec_happy(
            monkeypatch, tmp_path,
            ec_violations={"odh-a-v3-4": {"rule.x"}},
            ec_successes={"odh-a-v3-4": {"rule.y"}},
        )
        monkeypatch.setattr(
            mod.conforma_ec_validate, "group_entries_by_base_image",
            lambda *a, **k: {
                "quay.io/x": [{"name": "odh-a-v3-4", "image": "quay.io/x@sha256:aaa"}],
                "quay.io/y": [{"name": "odh-a-v3-4", "image": "quay.io/y@sha256:bbb"}],
            },
        )
        result = mod._run_ec_coverage(str(csv), str(clone), ["fbc-rhoai-prod.yaml"], "prod")
        assert result["violations"]["odh-a-v3-4"] == {"rule.x"}
        assert result["successes"]["odh-a-v3-4"] == {"rule.y"}


# ──────────────────────────────────────────────────────────────────────────────
# check_violations_coverage
# ──────────────────────────────────────────────────────────────────────────────


def _write_violations_yaml(tmp_path, rules=None, components=None):
    data = {
        "violation_data": {
            "releases": ["rhoai-3.4"],
            "violations_by_rule": rules or {
                "hermetic_task.hermetic": {
                    "title": "Hermetic",
                    "count": 2,
                    "releases": {"rhoai-3.4": components or ["comp-a", "comp-b"]},
                }
            },
            "violations_by_component": {
                "comp-a": {"jira_component": "Model Server"},
                "comp-b": {"jira_component": None},
            },
        }
    }
    path = tmp_path / "violations.yaml"
    path.write_text(yaml.dump(data))
    return str(path)


def _mock_auth(monkeypatch):
    monkeypatch.setattr(jira_ops, "verify_auth", lambda: {"ok": True})
    monkeypatch.setattr(slack_ops, "verify_auth", lambda: {"ok": True, "team_url": "https://test.slack.com"})
    monkeypatch.setattr(conforma_mr_ops, "prefetch_open_mrs", lambda *a, **k: {})
    monkeypatch.setattr(conforma_jira_ops, "prefetch_open_jira_tickets", lambda *a, **k: {})
    monkeypatch.setattr(conforma_slack_ops, "prefetch_open_slack_threads", lambda *a, **k: {})
    monkeypatch.setattr(component_alias_ops, "load_aliases", lambda: {})
    monkeypatch.setattr(conforma_policy_ops, "refresh_clone", lambda *a, **k: None)
    monkeypatch.setattr(
        conforma_policy_ops, "check_existing_exception_gate",
        lambda *a, **k: {
            "status": "passed", "permanent_exclusions": [],
            "active_exceptions": [], "open_merge_requests": [],
        },
    )
    monkeypatch.setattr(
        conforma_policy_ops, "search_self_service_exceptions",
        lambda *a, **k: {"checked": False},
    )
    monkeypatch.setattr(mod.conforma_mr_ops, "GITLAB_HOST", "gitlab.com")
    monkeypatch.setattr(mod.conforma_mr_ops, "GITLAB_PROJECT", "releng/policies")


def _make_run_env(tmp_path, monkeypatch, components=None, ec_result=None):
    """CSV + clone + default ec result for check_violations_coverage."""
    csv_path = tmp_path / "rhoai-3.4.csv"
    csv_path.write_text("type,component_name,image\n")
    clone_dir = tmp_path / "clone"
    clone_dir.mkdir()
    if ec_result is None:
        comps = components or ["comp-a", "comp-b"]
        ec_result = {
            "violations": {c: {"hermetic_task.hermetic"} for c in comps},
            "successes": {c: set() for c in comps},
            "validation": {"validated": True, "confirmed_violations": len(comps), "confirmed_covered": 0, "divergence_count": 0},
        }
    monkeypatch.setattr(mod, "_run_ec_coverage", lambda *a, **k: ec_result)
    return str(csv_path), str(clone_dir)


class TestCheckViolationsCoverageErrors:
    def test_file_not_found(self, tmp_path):
        result = mod.check_violations_coverage(str(tmp_path / "nope.yaml"), ["fbc.yaml"], "prod")
        assert "error" in result
        assert "not found" in result["error"]

    def test_no_violations_by_rule(self, tmp_path):
        path = tmp_path / "empty.yaml"
        path.write_text(yaml.dump({"violation_data": {"violations_by_rule": {}}}))
        result = mod.check_violations_coverage(str(path), ["fbc.yaml"], "prod")
        assert "error" in result
        assert "No violations_by_rule" in result["error"]

    def test_jira_auth_failure(self, tmp_path, monkeypatch):
        vpath = _write_violations_yaml(tmp_path)
        monkeypatch.setattr(jira_ops, "verify_auth", lambda: {"ok": False, "error": "bad token"})
        result = mod.check_violations_coverage(vpath, ["fbc.yaml"], "prod", require_jira=True)
        assert "Jira auth failed" in result["error"]

    def test_slack_auth_failure(self, tmp_path, monkeypatch):
        vpath = _write_violations_yaml(tmp_path)
        _mock_auth(monkeypatch)
        monkeypatch.setattr(slack_ops, "verify_auth", lambda: {"ok": False, "error": "no slack"})
        result = mod.check_violations_coverage(vpath, ["fbc.yaml"], "prod", require_slack=True)
        assert "Slack auth failed" in result["error"]

    def test_no_csv_required(self, tmp_path, monkeypatch):
        vpath = _write_violations_yaml(tmp_path)
        _mock_auth(monkeypatch)
        result = mod.check_violations_coverage(vpath, ["fbc.yaml"], "prod", csv_path=None, require_slack=False)
        assert "csv is required" in result["error"]


class TestCheckViolationsCoverageFlow:
    def test_full_flow_with_ec(self, tmp_path, monkeypatch):
        """Happy path with all cross-reference sources populated."""
        vpath = _write_violations_yaml(tmp_path)
        csv_path, clone_dir = _make_run_env(
            tmp_path, monkeypatch,
            ec_result={
                "violations": {"comp-a": set(), "comp-b": {"hermetic_task.hermetic"}},
                "successes": {"comp-a": {"hermetic_task.hermetic"}, "comp-b": set()},
                "validation": {"validated": True, "confirmed_violations": 1, "confirmed_covered": 1, "divergence_count": 0},
            },
        )
        _mock_auth(monkeypatch)
        mr = {
            "suggestion": "extend_mr", "mr_type": "exception", "iid": 42,
            "url": "https://gitlab/mr/42", "covered": ["comp-a"],
            "rules_in_diff": ["hermetic_task.hermetic"], "title_mentions_rule": True,
        }
        monkeypatch.setattr(
            conforma_mr_ops, "prefetch_open_mrs",
            lambda *a, **k: {"hermetic_task.hermetic": [mr]},
        )
        monkeypatch.setattr(
            conforma_jira_ops, "prefetch_open_jira_tickets",
            lambda *a, **k: {"hermetic_task.hermetic": [
                {"key": "RHOAIENG-123", "url": "https://jira/RHOAIENG-123", "status": "Open",
                 "fix_versions": ["3.5"], "version_relevance": "targets_future"},
            ]},
        )
        monkeypatch.setattr(
            conforma_slack_ops, "prefetch_open_slack_threads",
            lambda *a, **k: {"hermetic_task.hermetic": [
                {"channel": "conforma", "permalink": "https://slack/p", "date": "2026-01-01", "thread_reply_count": 3},
            ]},
        )
        monkeypatch.setattr(conforma_jira_ops, "classify_ticket_version_relevance", lambda *a, **k: "targets_future")
        monkeypatch.setattr(
            conforma_policy_ops, "check_existing_exception_gate",
            lambda *a, **k: {
                "status": "partial", "permanent_exclusions": [], "active_exceptions": [], "open_merge_requests": [mr],
            },
        )
        monkeypatch.setattr(component_alias_ops, "load_aliases", lambda: {"comp-a": ["alias-a"]})

        result = mod.check_violations_coverage(
            vpath, ["fbc.yaml"], "prod", clone_dir=clone_dir, csv_path=csv_path,
            release="rhoai-3.4", require_jira=True, require_slack=True,
        )
        assert "error" not in result
        assert result["summary"]["total_violations"] == 1
        assert result["ec_validation"]["validated"] is True
        assert result["component_owners"] == {"comp-a": "Model Server"}
        v = result["violations"][0]
        assert v["coverage"] == "partially_covered"
        assert v["open_slack_label"] != ""
        assert "targets 3.5" in v["open_jira_label"]
        assert "replies" in v["open_slack_label"]
        assert "Model Server" in v["display_components"]

    def test_no_components_skipped(self, tmp_path, monkeypatch):
        vpath = _write_violations_yaml(
            tmp_path,
            rules={"empty.rule": {"title": "Empty", "count": 0, "releases": {"rhoai-3.4": []}}},
        )
        csv_path, clone_dir = _make_run_env(tmp_path, monkeypatch)
        _mock_auth(monkeypatch)
        result = mod.check_violations_coverage(
            vpath, ["fbc.yaml"], "prod", clone_dir=clone_dir, csv_path=csv_path, require_slack=False,
        )
        assert "error" not in result
        assert result["violations"][0]["coverage"] == "no_components"
        assert result["violations"][0]["status"] == "skipped"

    def _self_service_ec(self, tmp_path, monkeypatch, ss_result):
        vpath = _write_violations_yaml(tmp_path)
        csv_path, clone_dir = _make_run_env(
            tmp_path, monkeypatch,
            ec_result={
                "violations": {"comp-a": {"hermetic_task.hermetic"}, "comp-b": {"hermetic_task.hermetic"}},
                "successes": {"comp-a": set(), "comp-b": set()},
                "validation": {"validated": True, "confirmed_violations": 2, "confirmed_covered": 0, "divergence_count": 0},
            },
        )
        _mock_auth(monkeypatch)
        monkeypatch.setattr(conforma_policy_ops, "search_self_service_exceptions", lambda *a, **k: ss_result)
        return vpath, csv_path, clone_dir

    def test_self_service_rescues_components(self, tmp_path, monkeypatch):
        vpath, csv_path, clone_dir = self._self_service_ec(
            tmp_path, monkeypatch,
            {"checked": True, "covered_components": {"comp-b"}, "has_unscoped": False, "source_files": ["exceptions.yaml"]},
        )
        result = mod.check_violations_coverage(
            vpath, ["fbc.yaml"], "prod", clone_dir=clone_dir, csv_path=csv_path,
            self_service_files=["exceptions.yaml"], require_slack=False,
        )
        v = result["violations"][0]
        assert v["coverage"] == "partially_covered"
        assert "comp-b" in v["covered_components"]
        assert "comp-a" in v["uncovered_components"]

    def test_self_service_unscoped_rescues_all(self, tmp_path, monkeypatch):
        vpath, csv_path, clone_dir = self._self_service_ec(
            tmp_path, monkeypatch,
            {"checked": True, "covered_components": set(), "has_unscoped": True, "source_files": ["exceptions.yaml"]},
        )
        result = mod.check_violations_coverage(
            vpath, ["fbc.yaml"], "prod", clone_dir=clone_dir, csv_path=csv_path,
            self_service_files=["exceptions.yaml"], require_slack=False,
        )
        v = result["violations"][0]
        assert v["coverage"] == "fully_covered"
        assert len(v["covered_components"]) == 2

    def _mr_scenario(self, tmp_path, monkeypatch, mr, ec_result=None):
        """Run check_violations_coverage with a single open MR and given ec result."""
        vpath = _write_violations_yaml(tmp_path)
        csv_path, clone_dir = _make_run_env(
            tmp_path, monkeypatch, components=["comp-a"],
            ec_result=ec_result or {
                "violations": {"comp-a": set()},
                "successes": {"comp-a": {"hermetic_task.hermetic"}},
                "validation": {"validated": True, "confirmed_violations": 0, "confirmed_covered": 1, "divergence_count": 0},
            },
        )
        _mock_auth(monkeypatch)
        monkeypatch.setattr(conforma_mr_ops, "prefetch_open_mrs", lambda *a, **k: {"hermetic_task.hermetic": [mr]})
        monkeypatch.setattr(
            conforma_policy_ops, "check_existing_exception_gate",
            lambda *a, **k: {
                "status": "blocked", "permanent_exclusions": [], "active_exceptions": [], "open_merge_requests": [mr],
            },
        )
        return mod.check_violations_coverage(
            vpath, ["fbc.yaml"], "prod", clone_dir=clone_dir, csv_path=csv_path, require_slack=False,
        )

    def test_mr_discrepancy_code_only(self, tmp_path, monkeypatch):
        """Diff covers rule but title doesn't mention it → code_only."""
        mr = {
            "suggestion": "extend_mr", "mr_type": "exception", "iid": 10,
            "url": "https://gitlab/mr/10", "covered": ["comp-a"],
            "rules_in_diff": ["hermetic_task.hermetic"], "title_mentions_rule": False,
        }
        result = self._mr_scenario(tmp_path, monkeypatch, mr)
        v = result["violations"][0]
        assert v["open_merge_requests"][0]["discrepancy"] == "code_only"
        assert "code scan" in v["open_merge_requests"][0]["discrepancy_detail"]

    def test_mr_discrepancy_title_only(self, tmp_path, monkeypatch):
        """Title mentions rule but diff doesn't cover it → title_only."""
        mr = {
            "suggestion": "extend_mr", "mr_type": "exception", "iid": 10,
            "url": "https://gitlab/mr/10", "covered": ["comp-a"],
            "rules_in_diff": ["other.rule"], "title_mentions_rule": True,
        }
        result = self._mr_scenario(tmp_path, monkeypatch, mr)
        v = result["violations"][0]
        assert v["open_merge_requests"][0]["discrepancy"] == "title_only"
        assert "other.rule" in v["open_merge_requests"][0]["discrepancy_detail"]

    def test_mr_no_discrepancy(self, tmp_path, monkeypatch):
        """Diff and title agree → discrepancy is None."""
        mr = {
            "suggestion": "extend_mr", "mr_type": "exception", "iid": 10,
            "url": "https://gitlab/mr/10", "covered": ["comp-a"],
            "rules_in_diff": ["hermetic_task.hermetic"], "title_mentions_rule": True,
        }
        result = self._mr_scenario(tmp_path, monkeypatch, mr)
        v = result["violations"][0]
        assert v["open_merge_requests"][0]["discrepancy"] is None
        # 2 components in the YAML, MR covers 1 of them
        assert "covers 1/2" in v["open_mr_label"]

    def test_mr_fully_covered_label(self, tmp_path, monkeypatch):
        mr = {
            "suggestion": "fully_covered", "mr_type": "remedy", "iid": 99,
            "url": "https://gitlab/mr/99", "covered": [],
            "rules_in_diff": ["hermetic_task.hermetic"], "title_mentions_rule": True,
        }
        result = self._mr_scenario(tmp_path, monkeypatch, mr)
        v = result["violations"][0]
        assert "fully covered by" in v["open_mr_label"]
        assert "(remedy)" in v["open_mr_label"]

    def test_display_components_truncated(self, tmp_path, monkeypatch):
        """More than 3 components → truncated with '+N more'."""
        many_comps = [f"comp-{i}" for i in range(6)]
        vpath = _write_violations_yaml(tmp_path, components=many_comps)
        csv_path, clone_dir = _make_run_env(tmp_path, monkeypatch, components=many_comps)
        _mock_auth(monkeypatch)
        result = mod.check_violations_coverage(
            vpath, ["fbc.yaml"], "prod", clone_dir=clone_dir, csv_path=csv_path, require_slack=False,
        )
        v = result["violations"][0]
        assert "+3 more" in v["display_components"]

    def test_jira_ticket_non_rhoaieng_no_version_tag(self, tmp_path, monkeypatch):
        """Non-RHOAIENG ticket → no version relevance tag."""
        vpath = _write_violations_yaml(tmp_path)
        csv_path, clone_dir = _make_run_env(tmp_path, monkeypatch)
        _mock_auth(monkeypatch)
        monkeypatch.setattr(
            conforma_jira_ops, "prefetch_open_jira_tickets",
            lambda *a, **k: {"hermetic_task.hermetic": [
                {"key": "PSX-456", "url": "https://jira/PSX-456", "status": "Open",
                 "fix_versions": ["3.5"], "version_relevance": "targets_future"},
            ]},
        )
        result = mod.check_violations_coverage(
            vpath, ["fbc.yaml"], "prod", clone_dir=clone_dir, csv_path=csv_path,
            release="rhoai-3.4", require_slack=False,
        )
        v = result["violations"][0]
        assert "PSX-456" in v["open_jira_label"]
        assert "targets" not in v["open_jira_label"]

    def test_jira_ticket_no_fix_version_tag(self, tmp_path, monkeypatch):
        """RHOAIENG ticket with no fixVersion → 'no fixVersion' warning tag."""
        vpath = _write_violations_yaml(tmp_path)
        csv_path, clone_dir = _make_run_env(tmp_path, monkeypatch)
        _mock_auth(monkeypatch)
        monkeypatch.setattr(
            conforma_jira_ops, "prefetch_open_jira_tickets",
            lambda *a, **k: {"hermetic_task.hermetic": [
                {"key": "RHOAIENG-789", "url": "https://jira/RHOAIENG-789", "status": "Open",
                 "fix_versions": [], "version_relevance": "no_target_version"},
            ]},
        )
        result = mod.check_violations_coverage(
            vpath, ["fbc.yaml"], "prod", clone_dir=clone_dir, csv_path=csv_path,
            release="rhoai-3.4", require_slack=False,
        )
        v = result["violations"][0]
        assert "no fixVersion" in v["open_jira_label"]

    def test_jira_inference_match_tags(self, tmp_path, monkeypatch):
        """component_inference tickets → confirmed/unconfirmed magnifier tag."""
        vpath = _write_violations_yaml(tmp_path)
        csv_path, clone_dir = _make_run_env(tmp_path, monkeypatch)
        _mock_auth(monkeypatch)
        tickets = [
            {"key": "RHOAIENG-1", "url": "https://jira/1", "status": "Open", "fix_versions": ["3.4"],
             "version_relevance": "targets_current", "match_source": "component_inference", "inference_confidence": "confirmed"},
            {"key": "RHOAIENG-2", "url": "https://jira/2", "status": "Open", "fix_versions": ["3.4"],
             "version_relevance": "targets_current", "match_source": "component_inference", "inference_confidence": "unconfirmed"},
        ]
        monkeypatch.setattr(conforma_jira_ops, "prefetch_open_jira_tickets", lambda *a, **k: {"hermetic_task.hermetic": tickets})
        result = mod.check_violations_coverage(
            vpath, ["fbc.yaml"], "prod", clone_dir=clone_dir, csv_path=csv_path,
            release="rhoai-3.4", require_slack=False,
        )
        v = result["violations"][0]
        assert "\U0001f50d?" in v["open_jira_label"]
        assert "RHOAIENG-1" in v["open_jira_label"]
        assert "RHOAIENG-2" in v["open_jira_label"]


# ──────────────────────────────────────────────────────────────────────────────
# _render_violations_markdown_table — header/status variants
# ──────────────────────────────────────────────────────────────────────────────


class TestRenderViolationsMarkdownTableVariants:
    def _summary(self, **kw):
        base = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        base.update(kw)
        return base

    def _row(self, **kw):
        base = {
            "rule": "r.x",
            "status_label": "No exception coverage",
            "next_steps": "Fix in code or request exception",
            "next_steps_short": "Fix in code",
            "open_jira_label": "",
            "covered_count": 0,
            "total_components": 1,
            "coverage": "not_covered",
        }
        base.update(kw)
        return base

    def test_source_path_and_url_in_header(self):
        meta = {"release": "rhoai-3.4", "source_path": "reports/rhoai-3.4.csv",
                "source_url": "https://git/blob/reports/rhoai-3.4.csv"}
        md = mod._render_violations_markdown_table([self._row()], self._summary(), report_meta=meta)
        assert "[reports/rhoai-3.4.csv](https://git/blob/reports/rhoai-3.4.csv)" in md

    def test_source_path_only_in_header(self):
        meta = {"release": "rhoai-3.4", "source_path": "reports/rhoai-3.4.csv"}
        md = mod._render_violations_markdown_table([self._row()], self._summary(), report_meta=meta)
        assert "**Source**: reports/rhoai-3.4.csv" in md

    def test_created_at_in_header(self):
        meta = {"release": "rhoai-3.4", "created_at": "2026-01-15T10:00:00Z"}
        md = mod._render_violations_markdown_table([self._row()], self._summary(), report_meta=meta)
        assert "**Report date**: 2026-01-15T10:00:00Z" in md

    def test_fully_covered_status_override(self):
        row = self._row(coverage="fully_covered", covered_count=2, total_components=2)
        md = mod._render_violations_markdown_table([row], self._summary(fully_covered=1, not_covered=0))
        assert "Exception granted (2/2 components covered)" in md

    def test_partially_covered_status_override(self):
        row = self._row(coverage="partially_covered", covered_count=1, total_components=3)
        md = mod._render_violations_markdown_table([row], self._summary(partially_covered=1, not_covered=0))
        assert "Exception granted (1/3 components covered, 2 without coverage)" in md

    def test_default_meta_unknown_release(self):
        """No report_meta → release falls back to 'unknown'."""
        md = mod._render_violations_markdown_table([self._row()], self._summary())
        assert "unknown" in md


# ──────────────────────────────────────────────────────────────────────────────
# main() — edge cases
# ──────────────────────────────────────────────────────────────────────────────


class TestMainEdgeCases:
    def test_explicit_run_dir_not_found_reraises(self, tmp_path, monkeypatch):
        """Explicit --run-dir with no context.yaml → re-raises FileNotFoundError."""
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        monkeypatch.setattr(
            "sys.argv",
            ["violations_coverage.py", "--run-dir", str(tmp_path / "nope"),
             "--environment", "prod", "--policy-files", "a.yaml"],
        )
        with pytest.raises(FileNotFoundError):
            mod.main()

    def test_no_violations_yaml_error(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path / "empty"))
        monkeypatch.setattr(
            "sys.argv",
            ["violations_coverage.py", "--environment", "prod", "--policy-files", "a.yaml"],
        )
        rc = mod.main()
        assert rc == 1
        assert "violations-yaml is required" in capsys.readouterr().err

    def test_no_csv_error(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path / "empty"))
        vpath = tmp_path / "v.yaml"
        vpath.write_text("violation_data: {}\n")
        monkeypatch.setattr(
            "sys.argv",
            ["violations_coverage.py", "--violations-yaml", str(vpath),
             "--environment", "prod", "--policy-files", "a.yaml"],
        )
        rc = mod.main()
        assert rc == 1
        assert "--csv is required" in capsys.readouterr().err

    def test_error_result_returns_1(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path / "empty"))
        monkeypatch.setattr(mod, "check_violations_coverage", lambda **_kw: {"error": "boom"})
        monkeypatch.setattr(
            "sys.argv",
            ["violations_coverage.py", "--violations-yaml", "dummy.yaml",
             "--csv", "dummy.csv", "--environment", "prod",
             "--clone-dir", str(tmp_path), "--policy-files", "a.yaml"],
        )
        rc = mod.main()
        assert rc == 1

    def test_context_provides_all_args(self, tmp_path, monkeypatch):
        """context.yaml supplies yaml, csv, release, clone_dir, policy_files."""
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        run_dir = tmp_path / "20260101-000000"
        conforma_context_ops.create(run_dir, {
            "application": {"release": "rhoai-3.4", "name": "rhoai", "version": "3.4", "konflux_app": "rhoai-v3-4"},
            "environment": "prod",
            "resolve": {"policy_files": ["fbc-rhoai-prod.yaml"]},
        })
        conforma_context_ops.update_step(run_dir, "fetch", "completed", csv_files=["rhoai-3.4.csv"])
        conforma_context_ops.update_step(run_dir, "parse", "completed", violations_yaml="violations.yaml")
        conforma_context_ops.set_active(run_dir)
        (run_dir / "rhoai-3.4.csv").write_text("header\n")
        (run_dir / "violations.yaml").write_text("violation_data: {}\n")
        (tmp_path / "konflux-release-data").mkdir()

        captured = {}

        def mock_check(**kw):
            captured.update(kw)
            return {"summary": {"total_violations": 0, "fully_covered": 0, "partially_covered": 0, "not_covered": 0}, "violations": []}

        monkeypatch.setattr(mod, "check_violations_coverage", mock_check)
        monkeypatch.setattr("sys.argv", ["violations_coverage.py"])
        rc = mod.main()
        assert rc == 0
        assert captured["release"] == "rhoai-3.4"
        assert captured["clone_dir"] == str(tmp_path / "konflux-release-data")
        assert captured["policy_files"] == ["fbc-rhoai-prod.yaml"]
        assert str(run_dir) in captured["csv_path"]

    def test_successful_run_updates_step(self, tmp_path, monkeypatch):
        """run_dir + no error → update_step('coverage', 'completed')."""
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        run_dir = tmp_path / "run1"
        conforma_context_ops.create(run_dir, {
            "application": {"release": "rhoai-3.4", "name": "rhoai", "version": "3.4", "konflux_app": "rhoai-v3-4"},
            "environment": "prod",
            "resolve": {"policy_files": ["fbc.yaml"]},
        })
        conforma_context_ops.update_step(run_dir, "fetch", "completed", csv_files=["rhoai-3.4.csv"])
        conforma_context_ops.update_step(run_dir, "parse", "completed", violations_yaml="v.yaml")
        conforma_context_ops.set_active(run_dir)
        (run_dir / "rhoai-3.4.csv").write_text("h\n")
        (run_dir / "v.yaml").write_text("violation_data: {}\n")
        clone_dir = tmp_path / "clone"
        clone_dir.mkdir()

        monkeypatch.setattr(mod, "check_violations_coverage", lambda **_kw: {
            "summary": {"total_violations": 0, "fully_covered": 0, "partially_covered": 0, "not_covered": 0},
            "violations": [],
        })
        monkeypatch.setattr("sys.argv", ["violations_coverage.py", "--clone-dir", str(clone_dir)])
        rc = mod.main()
        assert rc == 0
        ctx_data = conforma_context_ops.load(run_dir)
        assert ctx_data["steps"]["coverage"]["status"] == "completed"
        assert ctx_data["steps"]["coverage"]["clone_dir"] is not None









