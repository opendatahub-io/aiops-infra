"""Tests for conforma-exception manage_exceptions.py."""

from __future__ import annotations

from pathlib import Path

import manage_exceptions as mod


EC_POLICY_DIR = Path("config/stone-prod-p02.hjvn.p1/product/EnterpriseContractPolicy")

SAMPLE_POLICY_YAML = """\
apiVersion: enterprisecontract.io/v1alpha1
kind: EnterpriseContractPolicy
spec:
  configuration:
    volatileCriteria:
          # https://issues.redhat.com/browse/RHOAIENG-200
          # impacted versions: rhoai-3.4
          - value: hermetic_task.hermetic
            componentNames:
              - odh-dashboard-v3-4
            effectiveUntil: "2020-01-01T00:00:00Z"
            reference: https://issues.redhat.com/browse/PSX-10
          # impacted versions: rhoai-3.5
          - value: trusted_task.trusted
            componentNames:
              - odh-model-v3-5
            effectiveUntil: "2099-12-01T00:00:00Z"
            reference: https://issues.redhat.com/browse/PSX-11
          - value: rpm_signature.allowed:deadbeef
            effectiveUntil: "2099-06-01T00:00:00Z"
            reference: https://issues.redhat.com/browse/PSX-12
"""


def _make_exception(rule: str, effective_until: str, **extra) -> dict:
    return {
        "rule": rule,
        "file": "config/.../registry-rhoai-prod.yaml",
        "has_component_names": True,
        "component_names": ["odh-dashboard-v3-4"],
        "effective_until": effective_until,
        "is_unscoped": False,
        **extra,
    }


def _setup_policy_clone(tmp_path: Path) -> Path:
    """Create a minimal konflux-release-data clone with sample policy files."""
    clone_dir = tmp_path / "konflux-release-data"
    policy_dir = clone_dir / EC_POLICY_DIR
    policy_dir.mkdir(parents=True)

    (policy_dir / "registry-rhoai-prod.yaml").write_text(SAMPLE_POLICY_YAML, encoding="utf-8")
    (policy_dir / "fbc-rhoai-prod.yaml").write_text(
        "spec:\n  configuration:\n    volatileCriteria:\n",
        encoding="utf-8",
    )
    return clone_dir


class TestFilterExpired:
    def test_filters_only_expired_exceptions(self):
        exceptions = [
            _make_exception("hermetic_task.hermetic", "2020-01-01T00:00:00Z"),
            _make_exception("trusted_task.trusted", "2099-12-01T00:00:00Z"),
            _make_exception("schedule.weekday", "not-a-date"),
        ]

        expired = mod.filter_expired(exceptions)

        assert len(expired) == 1
        assert expired[0]["rule"] == "hermetic_task.hermetic"
        assert expired[0]["is_expired"] is True
        assert expired[0]["expired_days_ago"] > 0

    def test_sorts_by_effective_until(self):
        exceptions = [
            _make_exception("rule.b", "2020-03-01T00:00:00Z"),
            _make_exception("rule.a", "2020-01-01T00:00:00Z"),
        ]
        expired = mod.filter_expired(exceptions)
        assert [e["rule"] for e in expired] == ["rule.a", "rule.b"]


class TestAnnotateExpiry:
    def test_annotates_expired_and_active(self):
        exceptions = [
            _make_exception("expired.rule", "2020-01-01T00:00:00Z"),
            _make_exception("active.rule", "2099-12-01T00:00:00Z"),
        ]

        annotated = mod.annotate_expiry(exceptions)

        assert len(annotated) == 2
        expired_entry = next(e for e in annotated if e["rule"] == "expired.rule")
        active_entry = next(e for e in annotated if e["rule"] == "active.rule")
        assert expired_entry["is_expired"] is True
        assert "expired_days_ago" in expired_entry
        assert expired_entry["expired_days_ago"] > 0
        assert active_entry["is_expired"] is False
        assert active_entry["expires_in_days"] > 0

    def test_skips_unparseable_dates(self):
        annotated = mod.annotate_expiry(
            [
                _make_exception("bad.date", "invalid"),
            ]
        )
        assert annotated == []


class TestAssessException:
    def _violations(self) -> dict:
        return {
            "hermetic_task.hermetic": {
                "releases": {
                    "rhoai-3.4": ["odh-dashboard-v3-4", "odh-other-v3-4"],
                    "rhoai-3.5": [],
                },
            },
            "trusted_task.trusted": {
                "releases": {
                    "rhoai-3.4": ["odh-model-v3-4"],
                    "rhoai-3.5": ["odh-model-v3-5"],
                },
            },
        }

    def test_still_needed_when_all_components_still_violating(self):
        exc = {
            "rule": "hermetic_task.hermetic",
            "has_component_names": True,
            "component_names": ["odh-dashboard-v3-4"],
            "is_unscoped": False,
            "is_expired": True,
        }
        result = mod.assess_exception(exc, self._violations(), ["rhoai-3.4", "rhoai-3.5"])
        assert result["classification"] == "still_needed"
        assert result["match_type"] == "exact"
        assert result["recommended_action"] == "extend"
        assert result["evidence"]["still_violating_components"] == ["odh-dashboard-v3-4"]

    def test_no_longer_needed_when_violations_resolved(self):
        exc = {
            "rule": "hermetic_task.hermetic",
            "has_component_names": True,
            "component_names": ["odh-dashboard-v3-4"],
            "is_unscoped": False,
            "is_expired": True,
        }
        result = mod.assess_exception(
            exc,
            {"hermetic_task.hermetic": {"releases": {"rhoai-3.4": [], "rhoai-3.5": []}}},
            ["rhoai-3.4", "rhoai-3.5"],
        )
        assert result["classification"] == "no_longer_needed"
        assert result["recommended_action"] == "remove"

    def test_partially_needed_when_some_components_resolved(self):
        exc = {
            "rule": "hermetic_task.hermetic",
            "has_component_names": True,
            "component_names": ["odh-dashboard-v3-4", "odh-other-v3-4"],
            "is_unscoped": False,
            "is_expired": True,
        }
        violations = {
            "hermetic_task.hermetic": {
                "releases": {
                    "rhoai-3.4": ["odh-dashboard-v3-4"],
                    "rhoai-3.5": [],
                },
            },
        }
        result = mod.assess_exception(exc, violations, ["rhoai-3.4", "rhoai-3.5"])
        assert result["classification"] == "partially_needed"
        assert result["recommended_action"] == "narrow_and_extend"
        assert set(result["evidence"]["still_violating_components"]) == {"odh-dashboard-v3-4"}

    def test_unscoped_still_needed_when_any_release_has_violations(self):
        exc = {
            "rule": "trusted_task.trusted",
            "has_component_names": False,
            "component_names": [],
            "is_unscoped": True,
            "is_expired": False,
        }
        result = mod.assess_exception(exc, self._violations(), ["rhoai-3.4", "rhoai-3.5"])
        assert result["classification"] == "still_needed"
        assert result["recommended_action"] == "keep"

    def test_no_match_classified_no_longer_needed(self):
        exc = {
            "rule": "unknown.rule",
            "has_component_names": True,
            "component_names": ["odh-dashboard-v3-4"],
            "is_unscoped": False,
            "is_expired": True,
        }
        result = mod.assess_exception(exc, self._violations(), ["rhoai-3.4"])
        assert result["classification"] == "no_longer_needed"
        assert result["match_type"] == "none"
        assert result["recommended_action"] == "remove"

    def test_prefix_rule_match(self):
        exc = {
            "rule": "rpm_signature.allowed:abc123",
            "has_component_names": True,
            "component_names": ["odh-operator-v3-4"],
            "is_unscoped": False,
            "is_expired": True,
        }
        violations = {
            "rpm_signature.allowed:def456": {
                "base_code": "rpm_signature.allowed",
                "releases": {"rhoai-3.4": ["odh-operator-v3-4"]},
            },
        }
        result = mod.assess_exception(exc, violations, ["rhoai-3.4"])
        assert result["match_type"] == "prefix"
        assert result["classification"] == "still_needed"


class TestScanAllExceptions:
    def test_scans_policy_files_in_clone_dir(self, tmp_path):
        clone_dir = _setup_policy_clone(tmp_path)
        exceptions = mod.scan_all_exceptions(clone_dir, "prod")

        rules = {e["rule"] for e in exceptions}
        assert "hermetic_task.hermetic" in rules
        assert "trusted_task.trusted" in rules
        assert "rpm_signature.allowed:deadbeef" in rules

        hermetic = next(e for e in exceptions if e["rule"] == "hermetic_task.hermetic")
        assert hermetic["has_component_names"] is True
        assert hermetic["component_names"] == ["odh-dashboard-v3-4"]
        assert hermetic["reference"] == "https://issues.redhat.com/browse/PSX-10"
        assert "RHOAIENG-200" in hermetic["comment_header_lines"][0]
        assert hermetic["file"].endswith("registry-rhoai-prod.yaml")

        unscoped = next(e for e in exceptions if e["rule"] == "rpm_signature.allowed:deadbeef")
        assert unscoped["is_unscoped"] is True
        assert unscoped["has_component_names"] is False

    def test_returns_empty_when_policy_dir_missing(self, tmp_path):
        clone_dir = tmp_path / "empty-clone"
        clone_dir.mkdir()
        assert mod.scan_all_exceptions(clone_dir, "prod") == []
