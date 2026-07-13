"""Tests for conforma-remedy match_violation.py."""

from __future__ import annotations

import pytest

# Minimal catalog data — mirrors violation-catalog.yaml structure
SAMPLE_CATALOG = {
    "violations": [
        {
            "id": "hermetic_task.hermetic",
            "type": "conforma_violation",
            "title": "Build task was not invoked with the hermetic parameter set",
            "description": "All container images must be built in Hermetic environment.",
            "conforma_rule_codes": ["hermetic_task.hermetic"],
            "aliases": ["hermetic", "hermetic build", "non-hermetic"],
            "classification": {
                "resolution_path": "code_fix",
                "fixable_at_code_level": True,
                "typical_owner": "component_team",
                "estimated_effort": "medium",
                "requires_rebuild": True,
            },
            "symptoms": ["Build task was not invoked with the hermetic parameter set"],
            "fix_steps": [
                {"action": "Set hermetic=true in the PipelineRun YAML", "reference": "https://konflux-ci.dev/docs/building/hermetic-builds/"},
                {"action": "Enable prefetch-dependencies"},
                {"action": "Rebuild the component in Konflux"},
            ],
            "exception_context": {
                "when_to_exception": "Only if hermetic is genuinely not feasible.",
                "exception_template_category": "non_hermetic_build",
            },
        },
        {
            "id": "rpm_signature.allowed",
            "type": "conforma_violation",
            "title": "RPM not signed with allowed key",
            "description": "RPMs must be signed with a Red Hat key.",
            "conforma_rule_codes": ["rpm_signature.allowed"],
            "aliases": ["rpm signing", "rpm signature"],
            "classification": {
                "resolution_path": "mixed",
                "fixable_at_code_level": False,
                "typical_owner": "devops",
                "estimated_effort": "high",
                "requires_rebuild": True,
            },
            "symptoms": ["RPM not signed with allowed key"],
            "fix_steps": [
                {"action": "Ensure RPMs come from signed repos"},
            ],
            "exception_context": {
                "when_to_exception": "When third-party RPMs cannot be replaced.",
                "exception_template_category": "rpm_signature",
            },
        },
        {
            "id": "no_conforma_report_in_slack",
            "type": "operational_issue",
            "title": "No Conforma report in Slack",
            "description": "The conforma-reporter did not post results to Slack.",
            "aliases": ["no report", "missing slack report"],
            "classification": {
                "resolution_path": "operational",
                "typical_owner": "devops",
                "estimated_effort": "low",
                "requires_rebuild": False,
            },
            "symptoms": ["No conforma report found in Slack channel"],
            "fix_steps": [
                {"action": "Check conforma-reporter GitHub Actions workflow"},
            ],
        },
    ],
    "known_false_alerts": [
        {
            "id": "fbc_single_component_no_failed_tests",
            "title": "FBC single component failures",
            "conforma_rule_codes": ["test.no_failed_tests"],
            "action": "ignore",
            "condition": "FBC single-component push pipeline (not nightly)",
            "applies_to": "rhoai-fbc-fragment",
        },
    ],
}

# Minimal JSON fallback entries — mirrors conforma-rule-catalog-full.json
SAMPLE_JSON_FALLBACK = [
    {
        "rule_id": "cve__cve_blockers",
        "rule_package": "cve",
        "rule_name": "CVE blockers",
        "description": "Blocks release if critical CVEs are found.",
        "policy_type": "release",
        "collections": ["cve"],
    },
    {
        "rule_id": "hermetic_task__hermetic",
        "rule_package": "hermetic_task",
        "rule_name": "Hermetic build check",
        "description": "Checks that builds are hermetic.",
        "policy_type": "release",
        "collections": ["hermetic"],
    },
]


@pytest.fixture()
def matcher(tmp_path):
    """Create a ViolationMatcher with sample data files."""
    import json as json_mod

    import yaml

    yaml_path = tmp_path / "violation-catalog.yaml"
    yaml_path.write_text(yaml.dump(SAMPLE_CATALOG, default_flow_style=False))

    json_path = tmp_path / "conforma-rule-catalog-full.json"
    json_path.write_text(json_mod.dumps(SAMPLE_JSON_FALLBACK))

    import match_violation

    return match_violation.ViolationMatcher(
        catalog_path=str(yaml_path),
        fallback_path=str(json_path),
    )


# ── Exact rule code match ────────────────────────────────────────────


class TestMatchByRuleCode:
    def test_exact_match(self, matcher):
        result = matcher.match("hermetic_task.hermetic")
        assert result is not None
        assert result.id == "hermetic_task.hermetic"
        assert result.source == "catalog"

    def test_exact_match_returns_fix_steps(self, matcher):
        result = matcher.match("hermetic_task.hermetic")
        assert len(result.fix_steps) == 3
        assert "hermetic=true" in result.fix_steps[0]["action"]

    def test_exact_match_returns_classification(self, matcher):
        result = matcher.match("hermetic_task.hermetic")
        assert result.classification["resolution_path"] == "code_fix"
        assert result.classification["requires_rebuild"] is True

    def test_match_different_rule(self, matcher):
        result = matcher.match("rpm_signature.allowed")
        assert result is not None
        assert result.id == "rpm_signature.allowed"
        assert result.classification["resolution_path"] == "mixed"

    def test_match_via_conforma_rule_codes_field(self, matcher):
        result = matcher.match("hermetic_task.hermetic")
        assert result is not None


# ── Alias match ──────────────────────────────────────────────────────


class TestMatchByAlias:
    def test_alias_exact(self, matcher):
        result = matcher.match("hermetic build")
        assert result is not None
        assert result.id == "hermetic_task.hermetic"

    def test_alias_case_insensitive(self, matcher):
        result = matcher.match("Hermetic Build")
        assert result is not None
        assert result.id == "hermetic_task.hermetic"

    def test_alias_partial_no_match(self, matcher):
        result = matcher.match("herm")
        assert result is None

    def test_alias_for_operational_issue(self, matcher):
        result = matcher.match("no report")
        assert result is not None
        assert result.id == "no_conforma_report_in_slack"
        assert result.type == "operational_issue"

    def test_rpm_alias(self, matcher):
        result = matcher.match("rpm signing")
        assert result is not None
        assert result.id == "rpm_signature.allowed"


# ── Symptom match ────────────────────────────────────────────────────


class TestMatchBySymptom:
    def test_exact_symptom(self, matcher):
        result = matcher.match("Build task was not invoked with the hermetic parameter set")
        assert result is not None
        assert result.id == "hermetic_task.hermetic"

    def test_symptom_substring(self, matcher):
        result = matcher.match("not invoked with the hermetic parameter")
        assert result is not None
        assert result.id == "hermetic_task.hermetic"

    def test_symptom_case_insensitive(self, matcher):
        result = matcher.match("build task was not invoked with the hermetic parameter set")
        assert result is not None

    def test_no_symptom_match(self, matcher):
        result = matcher.match("completely unrelated error message xyz")
        assert result is None


# ── JSON fallback ────────────────────────────────────────────────────


class TestJsonFallback:
    def test_fallback_for_unknown_yaml_rule(self, matcher):
        result = matcher.match("cve__cve_blockers")
        assert result is not None
        assert result.source == "fallback"
        assert result.rule_name == "CVE blockers"
        assert result.description == "Blocks release if critical CVEs are found."

    def test_fallback_has_no_fix_steps(self, matcher):
        result = matcher.match("cve__cve_blockers")
        assert len(result.fix_steps) == 0

    def test_yaml_takes_precedence_over_json(self, matcher):
        result = matcher.match("hermetic_task.hermetic")
        assert result.source == "catalog"
        assert len(result.fix_steps) > 0


# ── Unknown / no match ──────────────────────────────────────────────


class TestNoMatch:
    def test_unknown_rule_returns_none(self, matcher):
        result = matcher.match("totally.unknown.rule")
        assert result is None

    def test_empty_string_returns_none(self, matcher):
        result = matcher.match("")
        assert result is None

    def test_none_input_returns_none(self, matcher):
        result = matcher.match(None)
        assert result is None


# ── Known false alerts ───────────────────────────────────────────────


class TestFalseAlertDetection:
    def test_detect_false_alert_by_rule_code(self, matcher):
        alerts = matcher.check_false_alerts("test.no_failed_tests")
        assert len(alerts) == 1
        assert alerts[0]["id"] == "fbc_single_component_no_failed_tests"
        assert alerts[0]["action"] == "ignore"

    def test_detect_false_alert_with_component(self, matcher):
        alerts = matcher.check_false_alerts(
            "test.no_failed_tests", component="rhoai-fbc-fragment"
        )
        assert len(alerts) == 1
        assert alerts[0]["applies_to"] == "rhoai-fbc-fragment"

    def test_no_false_alert_for_other_rules(self, matcher):
        alerts = matcher.check_false_alerts("hermetic_task.hermetic")
        assert alerts == []

    def test_no_false_alert_for_unknown_rule(self, matcher):
        alerts = matcher.check_false_alerts("unknown.rule")
        assert alerts == []


# ── MatchResult dataclass ────────────────────────────────────────────


class TestMatchResult:
    def test_result_is_immutable(self, matcher):
        result = matcher.match("hermetic_task.hermetic")
        with pytest.raises(AttributeError):
            result.id = "something_else"

    def test_catalog_result_has_all_fields(self, matcher):
        result = matcher.match("hermetic_task.hermetic")
        assert result.id == "hermetic_task.hermetic"
        assert result.source == "catalog"
        assert result.title != ""
        assert result.description != ""
        assert result.type == "conforma_violation"
        assert result.classification is not None
        assert len(result.fix_steps) > 0
        assert result.exception_context is not None
        assert "hermetic" in result.aliases

    def test_fallback_result_has_basic_fields(self, matcher):
        result = matcher.match("cve__cve_blockers")
        assert result.id == "cve__cve_blockers"
        assert result.source == "fallback"
        assert result.rule_name == "CVE blockers"
        assert result.policy_type == "release"
        assert "cve" in result.collections
        assert len(result.fix_steps) == 0
        assert result.classification is None


# ── Input sanitization ───────────────────────────────────────────────


class TestSanitization:
    def test_strips_surrounding_quotes(self, matcher):
        result = matcher.match('"hermetic_task.hermetic"')
        assert result is not None
        assert result.id == "hermetic_task.hermetic"

    def test_strips_single_quotes(self, matcher):
        result = matcher.match("'hermetic_task.hermetic'")
        assert result is not None
        assert result.id == "hermetic_task.hermetic"

    def test_strips_deny_prefix(self, matcher):
        result = matcher.match("deny: hermetic_task.hermetic")
        assert result is not None
        assert result.id == "hermetic_task.hermetic"

    def test_strips_warn_prefix(self, matcher):
        result = matcher.match("warn: hermetic_task.hermetic")
        assert result is not None
        assert result.id == "hermetic_task.hermetic"

    def test_strips_violation_prefix(self, matcher):
        result = matcher.match("violation: hermetic_task.hermetic")
        assert result is not None
        assert result.id == "hermetic_task.hermetic"

    def test_handles_trailing_newline(self, matcher):
        result = matcher.match("hermetic_task.hermetic\n")
        assert result is not None
        assert result.id == "hermetic_task.hermetic"

    def test_handles_windows_newline(self, matcher):
        result = matcher.match("hermetic_task.hermetic\r\n")
        assert result is not None
        assert result.id == "hermetic_task.hermetic"

    def test_collapses_extra_spaces(self, matcher):
        result = matcher.match("  hermetic   build  ")
        assert result is not None
        assert result.id == "hermetic_task.hermetic"

    def test_quoted_symptom_message(self, matcher):
        result = matcher.match(
            'Task "xyz" Build task was not invoked with the hermetic parameter set'
        )
        assert result is not None
        assert result.id == "hermetic_task.hermetic"


# ── Edge cases and error handling ────────────────────────────────────


class TestEdgeCases:
    def test_only_whitespace_variants(self, matcher):
        for ws in [" ", "\t", "\n", "\r\n", "  \t\n  "]:
            assert matcher.match(ws) is None

    def test_only_prefix_no_rule(self, matcher):
        assert matcher.match("deny:") is None
        assert matcher.match("warn: ") is None
        assert matcher.match("violation:  ") is None

    def test_only_quotes(self, matcher):
        assert matcher.match('""') is None
        assert matcher.match("''") is None

    def test_very_long_input(self, matcher):
        result = matcher.match("x" * 10_000)
        assert result is None

    def test_special_characters_no_crash(self, matcher):
        for char in ["@", "#", "$", "%", "^", "&", "*", "(", ")", "!", "~"]:
            result = matcher.match(char * 5)
            assert result is None

    def test_unicode_input(self, matcher):
        assert matcher.match("hérmetic_task.hérmetic") is None
        assert matcher.match("构建任务") is None

    def test_regex_metacharacters_safe(self, matcher):
        for dangerous in [".*", "(.+)", "[a-z]", "\\d+", "a{1,3}"]:
            result = matcher.match(dangerous)
            assert result is None

    def test_newlines_inside_query(self, matcher):
        result = matcher.match("hermetic\n_task.hermetic")
        assert result is None

    def test_mixed_case_prefix(self, matcher):
        result = matcher.match("DENY: hermetic_task.hermetic")
        assert result is not None
        assert result.id == "hermetic_task.hermetic"

    def test_multiple_prefixes_only_strips_first(self, matcher):
        result = matcher.match("deny: deny: hermetic_task.hermetic")
        assert result is None


class TestCorruptData:
    def test_missing_catalog_file(self, tmp_path):
        import json as json_mod
        import match_violation

        json_path = tmp_path / "fallback.json"
        json_path.write_text(json_mod.dumps(SAMPLE_JSON_FALLBACK))

        with pytest.raises(FileNotFoundError):
            match_violation.ViolationMatcher(
                catalog_path=str(tmp_path / "nonexistent.yaml"),
                fallback_path=str(json_path),
            )

    def test_missing_fallback_file_is_ok(self, tmp_path):
        import yaml
        import match_violation

        yaml_path = tmp_path / "catalog.yaml"
        yaml_path.write_text(yaml.dump(SAMPLE_CATALOG))

        m = match_violation.ViolationMatcher(
            catalog_path=str(yaml_path),
            fallback_path=str(tmp_path / "nonexistent.json"),
        )
        result = m.match("hermetic_task.hermetic")
        assert result is not None
        assert result.source == "catalog"

    def test_empty_catalog(self, tmp_path):
        import json as json_mod
        import yaml
        import match_violation

        yaml_path = tmp_path / "catalog.yaml"
        yaml_path.write_text(yaml.dump({"violations": [], "known_false_alerts": []}))

        json_path = tmp_path / "fallback.json"
        json_path.write_text(json_mod.dumps([]))

        m = match_violation.ViolationMatcher(
            catalog_path=str(yaml_path),
            fallback_path=str(json_path),
        )
        assert m.match("hermetic_task.hermetic") is None
        assert m.check_false_alerts("test.no_failed_tests") == []

    def test_catalog_missing_optional_fields(self, tmp_path):
        """Violations with minimal fields should not crash."""
        import yaml
        import match_violation

        minimal = {
            "violations": [
                {"id": "minimal.rule", "type": "conforma_violation"},
            ],
            "known_false_alerts": [],
        }
        yaml_path = tmp_path / "catalog.yaml"
        yaml_path.write_text(yaml.dump(minimal))

        m = match_violation.ViolationMatcher(
            catalog_path=str(yaml_path),
            fallback_path=str(tmp_path / "none.json"),
        )
        result = m.match("minimal.rule")
        assert result is not None
        assert result.id == "minimal.rule"
        assert result.title == ""
        assert len(result.fix_steps) == 0
        assert result.classification is None


class TestSanitizeQueryUnit:
    """Direct tests for the sanitize_query function."""

    def test_strips_and_lowercases(self):
        from remedy_matchers import sanitize_query

        assert sanitize_query("  HELLO  ") == "hello"

    def test_removes_deny_prefix(self):
        from remedy_matchers import sanitize_query

        assert sanitize_query("deny: some.rule") == "some.rule"

    def test_removes_warn_prefix(self):
        from remedy_matchers import sanitize_query

        assert sanitize_query("warn: some.rule") == "some.rule"

    def test_removes_failure_prefix(self):
        from remedy_matchers import sanitize_query

        assert sanitize_query("failure: some.rule") == "some.rule"

    def test_removes_surrounding_double_quotes(self):
        from remedy_matchers import sanitize_query

        assert sanitize_query('"some.rule"') == "some.rule"

    def test_removes_surrounding_single_quotes(self):
        from remedy_matchers import sanitize_query

        assert sanitize_query("'some.rule'") == "some.rule"

    def test_collapses_whitespace(self):
        from remedy_matchers import sanitize_query

        assert sanitize_query("hermetic   build") == "hermetic build"

    def test_strips_carriage_return(self):
        from remedy_matchers import sanitize_query

        assert sanitize_query("rule\r\n") == "rule"

    def test_combined_dirty_input(self):
        from remedy_matchers import sanitize_query

        assert sanitize_query('  DENY:  "hermetic_task.hermetic"\r\n  ') == "hermetic_task.hermetic"
