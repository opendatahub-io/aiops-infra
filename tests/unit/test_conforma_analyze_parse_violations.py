"""Tests for conforma-analyze parse_violations.py."""

from __future__ import annotations


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

    def test_extracts_rule_codes(self, tmp_csv):
        records = parse_violations.parse_csv_file(tmp_csv, "rhoai-3.4")
        rules = {r["rule"] for r in records}
        assert "hermetic_task.hermetic" in rules
        assert "trusted_task.trusted" in rules

    def test_extracts_rpm_key_suffix(self, tmp_csv):
        records = parse_violations.parse_csv_file(tmp_csv, "rhoai-3.4")
        rpm_records = [r for r in records if r["base_code"] == "rpm_signature.allowed"]
        assert len(rpm_records) == 1
        assert rpm_records[0]["rule"] == "rpm_signature.allowed:1234567890abcdef"

    def test_preserves_base_code(self, tmp_csv):
        records = parse_violations.parse_csv_file(tmp_csv, "rhoai-3.4")
        for r in records:
            assert "base_code" in r
            assert ":" not in r["base_code"]

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
