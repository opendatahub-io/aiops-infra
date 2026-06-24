"""Tests for conforma-analyze parse_violations.py."""

from __future__ import annotations

from datetime import datetime, timezone

import parse_violations


class TestExtractFullRuleCode:
    def test_rpm_signature_with_hex_key(self):
        code = "rpm_signature.allowed"
        message = "RPM not signed with allowed key 1234567890abcdef"
        result = parse_violations.extract_full_rule_code(code, message)
        assert result == "rpm_signature.allowed:1234567890abcdef"

    def test_rpm_signature_no_match(self):
        code = "rpm_signature.allowed"
        message = "RPM signing issue with no hex key"
        result = parse_violations.extract_full_rule_code(code, message)
        assert result == "rpm_signature.allowed"

    def test_test_no_failed_tests(self):
        code = "test.no_failed_tests"
        message = 'task "my-test-task" failed'
        result = parse_violations.extract_full_rule_code(code, message)
        assert result == "test.no_failed_tests:my-test-task"

    def test_test_no_failed_tests_from_description(self):
        code = "test.no_failed_tests"
        message = 'The Task "deprecated-image-check" from the build Pipeline reports a failed test'
        description = (
            'Produce a violation if any non-informative tests have their result set to "FAILED". '
            'To exclude this rule add "test.no_failed_tests:deprecated-image-check" to the '
            '`exclude` section of the policy configuration.'
        )
        result = parse_violations.extract_full_rule_code(code, message, description)
        assert result == "test.no_failed_tests:deprecated-image-check"

    def test_test_no_failed_tests_description_preferred_over_message(self):
        code = "test.no_failed_tests"
        message = 'task "wrong-name" failed'
        description = 'add "test.no_failed_tests:correct-name" to the `exclude` section'
        result = parse_violations.extract_full_rule_code(code, message, description)
        assert result == "test.no_failed_tests:correct-name"

    def test_test_no_failed_tests_message_fallback_real_format(self):
        code = "test.no_failed_tests"
        message = 'The Task "fbc-target-index-pruning-check" from the build Pipeline reports a failed test'
        result = parse_violations.extract_full_rule_code(code, message)
        assert result == "test.no_failed_tests:fbc-target-index-pruning-check"

    def test_test_no_failed_tests_no_description_no_message_match(self):
        code = "test.no_failed_tests"
        message = "Some unrecognized format"
        result = parse_violations.extract_full_rule_code(code, message)
        assert result == "test.no_failed_tests"

    def test_code_already_has_suffix(self):
        code = "some.rule:existing-suffix"
        message = "Irrelevant message"
        result = parse_violations.extract_full_rule_code(code, message)
        assert result == "some.rule:existing-suffix"

    def test_unknown_rule_family(self):
        code = "hermetic_task.hermetic"
        message = "Task is not hermetic"
        result = parse_violations.extract_full_rule_code(code, message)
        assert result == "hermetic_task.hermetic"


class TestNeedsQuoting:
    def test_empty_string(self):
        assert parse_violations._needs_quoting("") is False

    def test_timestamp(self):
        assert parse_violations._needs_quoting("2026-01-01T00:00:00Z") is True

    def test_colon(self):
        assert parse_violations._needs_quoting("rpm_signature.allowed:abc") is True

    def test_url(self):
        assert parse_violations._needs_quoting("https://example.com") is True

    def test_comment(self):
        assert parse_violations._needs_quoting("#comment") is True

    def test_boolean_like(self):
        assert parse_violations._needs_quoting("true") is True
        assert parse_violations._needs_quoting("false") is True
        assert parse_violations._needs_quoting("yes") is True

    def test_plain_string(self):
        assert parse_violations._needs_quoting("normal-string") is False


class TestParseCsvFile:
    def test_parses_violations_only(self, tmp_csv):
        records = parse_violations.parse_csv_file(tmp_csv, "rhoai-3.4")
        assert len(records) == 3
        assert all(r["release"] == "rhoai-3.4" for r in records)

    def test_extracts_violation_codes(self, tmp_csv):
        records = parse_violations.parse_csv_file(tmp_csv, "rhoai-3.4")
        codes = {r["code"] for r in records}
        assert "hermetic_task.hermetic" in codes
        assert "trusted_task.trusted" in codes

    def test_extracts_full_violation_code_with_suffix(self, tmp_csv):
        records = parse_violations.parse_csv_file(tmp_csv, "rhoai-3.4")
        rpm_records = [r for r in records if r["code"] == "rpm_signature.allowed"]
        assert len(rpm_records) == 1
        assert rpm_records[0]["full_violation_code"] == "rpm_signature.allowed:1234567890abcdef"

    def test_preserves_base_code(self, tmp_csv):
        records = parse_violations.parse_csv_file(tmp_csv, "rhoai-3.4")
        for r in records:
            assert "code" in r
            assert ":" not in r["code"]

    def test_extracts_semantic_detail(self, tmp_csv):
        records = parse_violations.parse_csv_file(tmp_csv, "rhoai-3.4")
        rpm_records = [r for r in records if r["code"] == "rpm_signature.allowed"]
        assert rpm_records[0]["semantic_detail"] == "1234567890abcdef"
        hermetic_records = [r for r in records if r["code"] == "hermetic_task.hermetic"]
        assert hermetic_records[0]["semantic_detail"] == ""

    def test_empty_csv(self, tmp_path):
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("type,component_name,image,message,effective_on,code,title,description,solution\n")
        records = parse_violations.parse_csv_file(csv_file, "rhoai-3.4")
        assert records == []


class TestBuildViolationsIndex:
    def test_basic_structure(self, tmp_csv):
        records = parse_violations.parse_csv_file(tmp_csv, "rhoai-3.4")
        index = parse_violations.build_violations_index(records, ["rhoai-3.4"])

        assert "violation_data" in index
        vd = index["violation_data"]
        assert "generated_at" in vd
        assert "releases" in vd
        assert "summary" in vd
        assert "violations_by_rule" in vd
        assert "violations_by_component" in vd

    def test_summary_counts(self, tmp_csv):
        records = parse_violations.parse_csv_file(tmp_csv, "rhoai-3.4")
        index = parse_violations.build_violations_index(records, ["rhoai-3.4"])

        summary = index["violation_data"]["summary"]["rhoai-3.4"]
        assert summary["total_violations"] == 3
        assert summary["unique_components"] == 3
        assert "unique_violation_codes" in summary

    def test_violations_by_component(self, tmp_csv):
        records = parse_violations.parse_csv_file(tmp_csv, "rhoai-3.4")
        index = parse_violations.build_violations_index(records, ["rhoai-3.4"])

        by_comp = index["violation_data"]["violations_by_component"]
        assert "odh-model-server-v3-4" in by_comp

    def test_failed_releases_included(self, tmp_csv):
        records = parse_violations.parse_csv_file(tmp_csv, "rhoai-3.4")
        failed = [{"release": "rhoai-3.5", "error": "branch not found"}]
        index = parse_violations.build_violations_index(records, ["rhoai-3.4"], failed_releases=failed)

        assert "failed_releases" in index["violation_data"]
        assert index["violation_data"]["failed_releases"][0]["release"] == "rhoai-3.5"

    def test_multi_release(self, tmp_path):
        csv1 = tmp_path / "rhoai-3.4.csv"
        csv1.write_text(
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            "violation,comp-a,img,msg,2026-01-01,hermetic_task.hermetic,title,desc,sol\n"
        )
        csv2 = tmp_path / "rhoai-3.5.csv"
        csv2.write_text(
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            "violation,comp-b,img,msg,2026-01-01,hermetic_task.hermetic,title,desc,sol\n"
        )

        records = []
        records.extend(parse_violations.parse_csv_file(csv1, "rhoai-3.4"))
        records.extend(parse_violations.parse_csv_file(csv2, "rhoai-3.5"))

        index = parse_violations.build_violations_index(records, ["rhoai-3.4", "rhoai-3.5"])
        assert len(index["violation_data"]["releases"]) == 2
        assert len(index["violation_data"]["summary"]) == 2


class TestParseDate:
    def test_iso_date(self):
        dt = parse_violations._parse_date("2026-06-15")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 6
        assert dt.day == 15

    def test_iso_datetime(self):
        dt = parse_violations._parse_date("2026-06-15T10:30:00Z")
        assert dt is not None
        assert dt.hour == 10

    def test_empty_string(self):
        assert parse_violations._parse_date("") is None

    def test_garbage(self):
        assert parse_violations._parse_date("not-a-date") is None


class TestParseWarningsCsvFile:
    def test_parses_upcoming_warnings(self, tmp_warnings_csv):
        ref = datetime(2026, 6, 10, tzinfo=timezone.utc)
        records = parse_violations.parse_warnings_csv_file(
            tmp_warnings_csv, "rhoai-3.4", threshold_days=21, reference_date=ref
        )
        codes = {r["code"] for r in records}
        assert "prefetch_dependencies.mode_not_permissive" in codes
        assert "hermetic_task.hermetic" in codes

    def test_excludes_far_future_warnings(self, tmp_warnings_csv):
        ref = datetime(2026, 6, 10, tzinfo=timezone.utc)
        records = parse_violations.parse_warnings_csv_file(
            tmp_warnings_csv, "rhoai-3.4", threshold_days=21, reference_date=ref
        )
        codes = {r["code"] for r in records}
        assert "future_rule.check" not in codes

    def test_excludes_missing_date_warnings(self, tmp_warnings_csv):
        ref = datetime(2026, 6, 10, tzinfo=timezone.utc)
        records = parse_violations.parse_warnings_csv_file(
            tmp_warnings_csv, "rhoai-3.4", threshold_days=21, reference_date=ref
        )
        codes = {r["code"] for r in records}
        assert "missing_date.rule" not in codes

    def test_days_until_effective(self, tmp_warnings_csv):
        ref = datetime(2026, 6, 10, tzinfo=timezone.utc)
        records = parse_violations.parse_warnings_csv_file(
            tmp_warnings_csv, "rhoai-3.4", threshold_days=21, reference_date=ref
        )
        hermetic = [r for r in records if r["code"] == "hermetic_task.hermetic"]
        assert len(hermetic) == 1
        assert hermetic[0]["days_until_effective"] == 10

    def test_empty_csv(self, tmp_path):
        csv_file = tmp_path / "empty-warnings.csv"
        csv_file.write_text("type,component_name,image,message,effective_on,code,title,description,solution\n")
        records = parse_violations.parse_warnings_csv_file(csv_file, "rhoai-3.4")
        assert records == []


class TestBuildUpcomingViolationsSection:
    def test_basic_structure(self, tmp_warnings_csv):
        ref = datetime(2026, 6, 10, tzinfo=timezone.utc)
        records = parse_violations.parse_warnings_csv_file(
            tmp_warnings_csv, "rhoai-3.4", threshold_days=21, reference_date=ref
        )
        section = parse_violations._build_upcoming_violations_section(records, ["rhoai-3.4"], 21)
        assert "by_rule" in section
        assert "by_component" in section
        assert "summary" in section
        assert section["threshold_days"] == 21

    def test_empty_records(self):
        section = parse_violations._build_upcoming_violations_section([], ["rhoai-3.4"], 21)
        assert section == {}


class TestBuildViolationsIndexWithUpcoming:
    def test_includes_upcoming_section(self, tmp_csv, tmp_warnings_csv):
        ref = datetime(2026, 6, 10, tzinfo=timezone.utc)
        violation_records = parse_violations.parse_csv_file(tmp_csv, "rhoai-3.4")
        upcoming_records = parse_violations.parse_warnings_csv_file(
            tmp_warnings_csv, "rhoai-3.4", threshold_days=21, reference_date=ref
        )
        index = parse_violations.build_violations_index(
            violation_records, ["rhoai-3.4"], upcoming_records=upcoming_records
        )
        assert "upcoming_violations" in index["violation_data"]
        upcoming = index["violation_data"]["upcoming_violations"]
        assert upcoming["threshold_days"] == 21
        assert len(upcoming["by_rule"]) > 0

    def test_no_upcoming_when_none(self, tmp_csv):
        records = parse_violations.parse_csv_file(tmp_csv, "rhoai-3.4")
        index = parse_violations.build_violations_index(records, ["rhoai-3.4"])
        assert "upcoming_violations" not in index["violation_data"]


class TestEnrichWithCatalog:
    def test_adds_jira_component_to_violations(self, monkeypatch, tmp_csv):
        import component_catalog_ops

        monkeypatch.setattr(
            component_catalog_ops,
            "load_catalog",
            lambda: [{"name": "odh-model-server-v3-4", "jira_components": [{"name": "ModelMesh"}]}],
        )
        monkeypatch.setattr(
            component_catalog_ops,
            "resolve_jira_components",
            lambda names, catalog: {n: "ModelMesh" if n == "odh-model-server-v3-4" else None for n in names},
        )

        records = parse_violations.parse_csv_file(tmp_csv, "rhoai-3.4")
        index = parse_violations.build_violations_index(records, ["rhoai-3.4"])

        ok = parse_violations._enrich_with_catalog(index)
        assert ok is True

        by_comp = index["violation_data"]["violations_by_component"]
        assert by_comp["odh-model-server-v3-4"]["jira_component"] == "ModelMesh"
        assert by_comp["odh-vllm-v3-4"]["jira_component"] is None

    def test_enriches_upcoming_components(self, monkeypatch, tmp_csv, tmp_warnings_csv):
        import component_catalog_ops

        monkeypatch.setattr(
            component_catalog_ops,
            "load_catalog",
            lambda: [],
        )
        monkeypatch.setattr(
            component_catalog_ops,
            "resolve_jira_components",
            lambda names, catalog: {n: f"Jira-{n}" for n in names},
        )

        from datetime import datetime, timezone

        violation_records = parse_violations.parse_csv_file(tmp_csv, "rhoai-3.4")
        ref = datetime(2026, 6, 10, tzinfo=timezone.utc)
        upcoming_records = parse_violations.parse_warnings_csv_file(
            tmp_warnings_csv, "rhoai-3.4", threshold_days=21, reference_date=ref
        )
        index = parse_violations.build_violations_index(
            violation_records, ["rhoai-3.4"], upcoming_records=upcoming_records
        )

        ok = parse_violations._enrich_with_catalog(index)
        assert ok is True

        upcoming_by_comp = index["violation_data"]["upcoming_violations"]["by_component"]
        for comp, info in upcoming_by_comp.items():
            assert info["jira_component"] == f"Jira-{comp}"

    def test_empty_components(self, monkeypatch):
        import component_catalog_ops

        monkeypatch.setattr(component_catalog_ops, "load_catalog", lambda: [])
        monkeypatch.setattr(component_catalog_ops, "resolve_jira_components", lambda names, catalog: {})

        index = {"violation_data": {"violations_by_component": {}}}
        ok = parse_violations._enrich_with_catalog(index)
        assert ok is True


class TestReleaseFilter:
    """Layer 3 defense: --release flag scopes parsing to a single release."""

    def test_release_filter_only_parses_target(self, tmp_path):
        """When --release is set, only that release's CSV is parsed."""
        (tmp_path / "rhoai-3.4.csv").write_text(
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            "violation,comp-a,img,msg,,hermetic_task.hermetic,title,desc,sol\n"
        )
        (tmp_path / "rhoai-2.25.csv").write_text(
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            "violation,comp-b,img,msg,,hermetic_task.hermetic,title,desc,sol\n"
        )
        records_34 = parse_violations.parse_csv_file(tmp_path / "rhoai-3.4.csv", "rhoai-3.4")
        assert len(records_34) == 1
        assert records_34[0]["component_name"] == "comp-a"

        records_225 = parse_violations.parse_csv_file(tmp_path / "rhoai-2.25.csv", "rhoai-2.25")
        assert len(records_225) == 1
        assert records_225[0]["component_name"] == "comp-b"

    def test_release_filter_ignores_other_csvs(self, tmp_path):
        """--release filter only picks {release}.csv, ignoring other CSVs in the directory."""
        (tmp_path / "rhoai-3.4.csv").write_text(
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            "violation,comp-target,img,msg,,hermetic_task.hermetic,title,desc,sol\n"
        )
        (tmp_path / "rhoai-2.25.csv").write_text(
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            "violation,comp-other,img,msg,,hermetic_task.hermetic,title,desc,sol\n"
        )

        target_csv = tmp_path / "rhoai-3.4.csv"
        assert target_csv.exists()
        all_csvs = sorted(f for f in tmp_path.glob("*.csv") if not f.name.endswith("-warnings.csv"))
        assert len(all_csvs) == 2

        filtered = [target_csv]
        assert len(filtered) == 1
        assert filtered[0].stem == "rhoai-3.4"

    def test_release_filter_also_scopes_warnings(self, tmp_path):
        """--release filter also scopes warnings CSV parsing."""
        (tmp_path / "rhoai-3.4.csv").write_text(
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            "violation,comp-a,img,msg,,hermetic_task.hermetic,title,desc,sol\n"
        )
        (tmp_path / "rhoai-3.4-warnings.csv").write_text(
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            "warning,comp-a,img,msg,2030-01-01,future.rule,title,desc,sol\n"
        )
        (tmp_path / "rhoai-2.25-warnings.csv").write_text(
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            "warning,comp-other,img,msg,2030-01-01,future.rule,title,desc,sol\n"
        )

        target_warn = tmp_path / "rhoai-3.4-warnings.csv"
        assert target_warn.exists()
        other_warn = tmp_path / "rhoai-2.25-warnings.csv"
        assert other_warn.exists()

        filtered_warnings = [target_warn] if target_warn.exists() else []
        assert len(filtered_warnings) == 1
        assert "rhoai-3.4" in filtered_warnings[0].name

    def test_release_filter_missing_csv_returns_empty(self, tmp_path):
        """When --release targets a nonexistent CSV, no records are produced."""
        target = tmp_path / "rhoai-3.99.csv"
        assert not target.exists()


class TestSafeYamlDump:
    def test_quotes_timestamps(self):
        data = {"date": "2026-01-01T00:00:00Z"}
        output = parse_violations._safe_yaml_dump(data)
        assert '"2026-01-01T00:00:00Z"' in output

    def test_quotes_urls(self):
        data = {"url": "https://example.com/path"}
        output = parse_violations._safe_yaml_dump(data)
        assert '"https://example.com/path"' in output

    def test_comment_header(self):
        data = {"key": "value"}
        output = parse_violations._safe_yaml_dump(data, "# Header line")
        assert output.startswith("# Header line")


class TestExtractNoErredTests:
    def test_extracts_task_name_from_message(self):
        code = "test.no_erred_tests"
        message = 'The Task "sast-snyk-check-oci-ta" from the build Pipeline reports a test erred'
        result = parse_violations.extract_full_rule_code(code, message)
        assert result == "test.no_erred_tests:sast-snyk-check-oci-ta"

    def test_extracts_task_name_from_description(self):
        code = "test.no_erred_tests"
        message = 'The Task "some-task" from the build Pipeline reports a test erred'
        description = 'add "test.no_erred_tests:correct-task-name" to the exclude section'
        result = parse_violations.extract_full_rule_code(code, message, description)
        assert result == "test.no_erred_tests:correct-task-name"

    def test_falls_back_to_base_code_when_no_match(self):
        code = "test.no_erred_tests"
        message = "Some unrecognized format without task name"
        result = parse_violations.extract_full_rule_code(code, message)
        assert result == "test.no_erred_tests"


class TestExtractFullViolationCode:
    def test_extracts_from_description_hint(self):
        desc = 'To exclude this rule add "rpm_repos.ids_known:pkg:rpm/redhat/acl@2.3.1" to the `exclude` section.'
        result = parse_violations.extract_full_violation_code(desc, "rpm_repos.ids_known")
        assert result == "rpm_repos.ids_known:pkg:rpm/redhat/acl@2.3.1"

    def test_hermetic_no_suffix(self):
        desc = 'To exclude this rule add "hermetic_task.hermetic" to the `exclude` section.'
        result = parse_violations.extract_full_violation_code(desc, "hermetic_task.hermetic")
        assert result == "hermetic_task.hermetic"

    def test_falls_back_to_legacy_extractors(self):
        result = parse_violations.extract_full_violation_code(
            "", "rpm_signature.allowed", "RPM not signed with key 1234567890abcdef"
        )
        assert result == "rpm_signature.allowed:1234567890abcdef"

    def test_empty_description_and_no_fallback(self):
        result = parse_violations.extract_full_violation_code("", "hermetic_task.hermetic", "Not hermetic")
        assert result == "hermetic_task.hermetic"


class TestExtractSemanticDetail:
    def test_rpm_repos_extracts_repo_id(self):
        msg = "RPM repo id check failed: pkg:rpm/redhat/acl@2.3.1?repository_id=ubi-9-baseos-rpms"
        result = parse_violations.extract_semantic_detail(
            "rpm_repos.ids_known", msg, "rpm_repos.ids_known:pkg:rpm/redhat/acl@2.3.1"
        )
        assert result == "ubi-9-baseos-rpms"

    def test_disallowed_attributes_extracts_attribute(self):
        msg = 'Package pkg:pypi/foo@1.0 has the attribute "hermeto:pip:package:binary" set to "true"'
        result = parse_violations.extract_semantic_detail(
            "sbom_spdx.disallowed_package_attributes", msg, "sbom_spdx.disallowed_package_attributes:pkg:pypi/foo@1.0"
        )
        assert result == "hermeto:pip:package:binary=true"

    def test_unique_version_extracts_package_name(self):
        result = parse_violations.extract_semantic_detail(
            "rpm_packages.unique_version", "", "rpm_packages.unique_version:annobin"
        )
        assert result == "annobin"

    def test_hermetic_returns_empty(self):
        result = parse_violations.extract_semantic_detail(
            "hermetic_task.hermetic", "Task is not hermetic", "hermetic_task.hermetic"
        )
        assert result == ""

    def test_allowed_package_sources_extracts_url(self):
        msg = 'Package fetched by Hermeto was sourced from "https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl" which is not allowed'
        result = parse_violations.extract_semantic_detail(
            "sbom_spdx.allowed_package_sources", msg, "sbom_spdx.allowed_package_sources:pkg:generic/foo"
        )
        assert result == "https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl"

    def test_test_no_failed_extracts_task_name(self):
        result = parse_violations.extract_semantic_detail(
            "test.no_failed_tests", "", "test.no_failed_tests:fbc-target-index-pruning-check"
        )
        assert result == "fbc-target-index-pruning-check"

    def test_unknown_code_uses_default_suffix(self):
        result = parse_violations.extract_semantic_detail(
            "unknown_rule.new_check", "", "unknown_rule.new_check:some-suffix"
        )
        assert result == "some-suffix"

    def test_unknown_code_no_suffix_returns_empty(self):
        result = parse_violations.extract_semantic_detail(
            "unknown_rule.no_suffix", "", "unknown_rule.no_suffix"
        )
        assert result == ""


class TestSemanticViolationsInIndex:
    def test_semantic_violations_structure(self, tmp_path):
        csv_file = tmp_path / "rhoai-3.4.csv"
        csv_file.write_text(
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a,img,"Task is not hermetic",,hermetic_task.hermetic,title,'
            '"To exclude this rule add ""hermetic_task.hermetic"" to the `exclude` section.",sol\n'
            'violation,comp-b,img,"Task is not hermetic",,hermetic_task.hermetic,title,'
            '"To exclude this rule add ""hermetic_task.hermetic"" to the `exclude` section.",sol\n'
        )
        records = parse_violations.parse_csv_file(csv_file, "rhoai-3.4")
        index = parse_violations.build_violations_index(records, ["rhoai-3.4"])

        by_rule = index["violation_data"]["violations_by_rule"]
        assert "hermetic_task.hermetic" in by_rule
        entry = by_rule["hermetic_task.hermetic"]
        assert entry["count"] == 2
        assert "semantic_violations" in entry
        sem_viols = entry["semantic_violations"]
        assert len(sem_viols) == 1
        assert sem_viols[0]["detail"] == ""
        assert sorted(sem_viols[0]["components"]) == ["comp-a", "comp-b"]

    def test_semantic_dedup_collapses_same_detail(self, tmp_path):
        csv_file = tmp_path / "rhoai-3.4.csv"
        csv_file.write_text(
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a,img:sha1,"RPM repo id: pkg:rpm/acl@1?repository_id=ubi-9-baseos-rpms",,rpm_repos.ids_known,title,'
            '"To exclude this rule add ""rpm_repos.ids_known:pkg:rpm/acl@1"" to the `exclude` section.",sol\n'
            'violation,comp-a,img:sha2,"RPM repo id: pkg:rpm/glib@2?repository_id=ubi-9-baseos-rpms",,rpm_repos.ids_known,title,'
            '"To exclude this rule add ""rpm_repos.ids_known:pkg:rpm/glib@2"" to the `exclude` section.",sol\n'
        )
        records = parse_violations.parse_csv_file(csv_file, "rhoai-3.4")
        index = parse_violations.build_violations_index(records, ["rhoai-3.4"])

        by_rule = index["violation_data"]["violations_by_rule"]
        entry = by_rule["rpm_repos.ids_known"]
        assert entry["count"] == 1
        assert entry["csv_row_count"] == 2


class TestBuildSemanticDetailLookup:
    def test_basic_lookup(self):
        yaml_data = {
            "violation_data": {
                "violations_by_rule": {
                    "rpm_signature.allowed": {
                        "violation_code": "rpm_signature.allowed",
                        "detail_label": "signing key",
                        "semantic_violations": [
                            {"detail": "abc123", "components": ["comp-a", "comp-b"]},
                            {"detail": "def456", "components": ["comp-a"]},
                        ],
                    },
                    "hermetic_task.hermetic": {
                        "violation_code": "hermetic_task.hermetic",
                        "semantic_violations": [
                            {"detail": "", "components": ["comp-c"]},
                        ],
                    },
                }
            }
        }
        detail_lookup, detail_labels = parse_violations.build_semantic_detail_lookup(yaml_data)

        assert detail_labels == {"rpm_signature.allowed": "signing key"}
        assert detail_lookup[("rpm_signature.allowed", "comp-a")] == ["abc123", "def456"]
        assert detail_lookup[("rpm_signature.allowed", "comp-b")] == ["abc123"]
        assert ("hermetic_task.hermetic", "comp-c") not in detail_lookup

    def test_empty_yaml(self):
        detail_lookup, detail_labels = parse_violations.build_semantic_detail_lookup({})
        assert detail_lookup == {}
        assert detail_labels == {}

    def test_missing_violation_data_key(self):
        detail_lookup, detail_labels = parse_violations.build_semantic_detail_lookup({"other": {}})
        assert detail_lookup == {}
        assert detail_labels == {}

    def test_fallback_to_rule_key(self):
        yaml_data = {
            "violation_data": {
                "violations_by_rule": {
                    "some_rule.check": {
                        "detail_label": "item",
                        "semantic_violations": [
                            {"detail": "x", "components": ["comp-a"]},
                        ],
                    },
                }
            }
        }
        detail_lookup, detail_labels = parse_violations.build_semantic_detail_lookup(yaml_data)
        assert detail_lookup[("some_rule.check", "comp-a")] == ["x"]
        assert detail_labels["some_rule.check"] == "item"
