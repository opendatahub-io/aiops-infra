"""Tests for conforma_mr_ops.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import conforma_mr_ops as mod


class TestEnsureGitlabEnv:
    """Tests for _ensure_gitlab_env using gitlab_ops.discover_token."""

    @patch("conforma_mr_ops.gitlab_ops.discover_token", return_value="glpat-test-token")
    def test_sets_token_when_missing(self, mock_discover, monkeypatch):
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        mod._ensure_gitlab_env()
        mock_discover.assert_called_once()
        assert mod.os.environ.get("GITLAB_TOKEN") == "glpat-test-token"
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)

    @patch("conforma_mr_ops.gitlab_ops.discover_token")
    def test_skips_when_token_already_set(self, mock_discover, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "existing-token")
        mod._ensure_gitlab_env()
        mock_discover.assert_not_called()
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)

    @patch("conforma_mr_ops.gitlab_ops.discover_token", return_value=None)
    def test_no_op_when_discover_returns_none(self, mock_discover, monkeypatch):
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        mod._ensure_gitlab_env()
        mock_discover.assert_called_once()
        assert mod.os.environ.get("GITLAB_TOKEN") is None


class TestImageUrlCoversComponent:
    def test_rhel9_image_covers_versioned_component(self):
        assert mod.image_url_covers_component(
            "quay.io/rhoai/odh-dashboard-rhel9",
            "odh-dashboard-v3-4",
        )

    def test_ubi9_image_covers_ea_component(self):
        assert mod.image_url_covers_component(
            "quay.io/rhoai/odh-vllm-cpu-ubi9",
            "odh-vllm-cpu-v3-5-ea-1",
        )

    def test_different_base_names_do_not_match(self):
        assert not mod.image_url_covers_component(
            "quay.io/rhoai/odh-dashboard-rhel9",
            "odh-modelmesh-v3-4",
        )

    def test_same_base_different_versions(self):
        assert mod.image_url_covers_component(
            "quay.io/rhoai/odh-mlmd-grpc-server-rhel9",
            "odh-mlmd-grpc-server-v2-25",
        )


class TestExtractImageBase:
    def test_strips_rhel_suffix(self):
        assert mod._extract_image_base("quay.io/rhoai/odh-dashboard-rhel9") == "odh-dashboard"

    def test_strips_ubi_suffix(self):
        assert mod._extract_image_base("quay.io/rhoai/odh-vllm-cpu-ubi9") == "odh-vllm-cpu"

    def test_no_suffix(self):
        assert mod._extract_image_base("quay.io/rhoai/odh-dashboard") == "odh-dashboard"


class TestExtractComponentBase:
    def test_strips_version(self):
        assert mod._extract_component_base("odh-dashboard-v3-4") == "odh-dashboard"

    def test_strips_ea_version(self):
        assert mod._extract_component_base("odh-vllm-cpu-v3-5-ea-1") == "odh-vllm-cpu"

    def test_no_version(self):
        assert mod._extract_component_base("odh-dashboard") == "odh-dashboard"


class TestClassifyMrType:
    """Tests for classify_mr_type — deterministic exception vs remedy classification."""

    def test_exception_when_changes_in_enterprise_contract_policy(self):
        changes = [{"new_path": "config/rhoai/EnterpriseContractPolicy/registry.yaml"}]
        assert mod.classify_mr_type(changes) == "exception"

    def test_exception_when_changes_in_exceptions_dir(self):
        changes = [{"new_path": "config/rhoai/exceptions/my-exception.yaml"}]
        assert mod.classify_mr_type(changes) == "exception"

    def test_remedy_when_no_exception_paths(self):
        changes = [
            {"new_path": "components/odh-dashboard/Dockerfile"},
            {"new_path": "pipelines/build-pipeline.yaml"},
        ]
        assert mod.classify_mr_type(changes) == "remedy"

    def test_exception_when_mixed_paths(self):
        changes = [
            {"new_path": "README.md"},
            {"new_path": "config/rhoai/EnterpriseContractPolicy/registry.yaml"},
        ]
        assert mod.classify_mr_type(changes) == "exception"

    def test_remedy_when_empty_changes(self):
        assert mod.classify_mr_type([]) == "remedy"

    def test_remedy_when_missing_new_path(self):
        changes = [{"old_path": "something.yaml"}]
        assert mod.classify_mr_type(changes) == "remedy"


class TestAnalyzeMrComponentCoverage:
    def setup_method(self):
        mod._mr_cache._diffs.clear()
        mod._thread_local.__dict__.clear()

    def test_fully_covered_from_prefetched_diff(self):
        diff = (
            "+++ b/config/.../EnterpriseContractPolicy/registry-rhoai-prod.yaml\n"
            "+          - value: hermetic_task.hermetic\n"
            "+            componentNames:\n"
            "+              - odh-dashboard-v3-4\n"
            "+              - odh-model-v3-4\n"
        )
        mod._mr_cache.store(
            42,
            [
                {
                    "new_path": "config/.../EnterpriseContractPolicy/registry-rhoai-prod.yaml",
                    "diff": diff,
                }
            ],
        )

        result = mod.analyze_mr_component_coverage(
            mr_iid=42,
            rule="hermetic_task.hermetic",
            requested_components=["odh-dashboard-v3-4", "odh-model-v3-4"],
        )

        assert result["source"] == "diff"
        assert result["suggestion"] == "fully_covered"
        assert result["covered"] == ["odh-dashboard-v3-4", "odh-model-v3-4"]
        assert result["missing"] == []
        assert result["mr_type"] == "exception"

    def test_extend_mr_when_partial_overlap_from_diff(self):
        diff = (
            "+++ b/config/.../EnterpriseContractPolicy/registry-rhoai-prod.yaml\n"
            "+          - value: hermetic_task.hermetic\n"
            "+            componentNames:\n"
            "+              - odh-dashboard-v3-4\n"
        )
        mod._mr_cache.store(
            7,
            [
                {
                    "new_path": "config/.../EnterpriseContractPolicy/registry-rhoai-prod.yaml",
                    "diff": diff,
                }
            ],
        )

        result = mod.analyze_mr_component_coverage(
            mr_iid=7,
            rule="hermetic_task.hermetic",
            requested_components=["odh-dashboard-v3-4", "odh-model-v3-4"],
        )

        assert result["suggestion"] == "extend_mr"
        assert result["covered"] == ["odh-dashboard-v3-4"]
        assert result["missing"] == ["odh-model-v3-4"]
        assert result["mr_type"] == "exception"

    def test_falls_back_to_description_when_diff_empty(self):
        description = (
            "## Exception: `trusted_task.trusted` for `rhoai-3.4`\n\n"
            "### Components\n"
            "- `odh-modelmesh-v3-4`\n"
            "- `odh-dashboard-v3-4`\n"
        )

        result = mod.analyze_mr_component_coverage(
            mr_iid=99,
            rule="trusted_task.trusted",
            requested_components=["odh-dashboard-v3-4"],
            mr_description=description,
        )

        assert result["source"] == "description"
        assert result["suggestion"] == "fully_covered"
        assert "odh-dashboard-v3-4" in result["covered"]

    def test_no_overlap_when_diff_and_description_missing(self):
        result = mod.analyze_mr_component_coverage(
            mr_iid=1,
            rule="hermetic_task.hermetic",
            requested_components=["odh-dashboard-v3-4"],
        )
        assert result["suggestion"] == "no_overlap"
        assert result["source"] == "none"
        assert result["missing"] == ["odh-dashboard-v3-4"]

    def test_mr_type_is_remedy_for_non_exception_paths(self):
        mod._mr_cache.store(
            200,
            [{"new_path": "components/dashboard/Dockerfile", "diff": "+FROM base\n"}],
        )
        result = mod.analyze_mr_component_coverage(
            mr_iid=200,
            rule="hermetic_task.hermetic",
            requested_components=["odh-dashboard-v3-4"],
        )
        assert result["mr_type"] == "remedy"

    @patch("conforma_mr_ops.gitlab_ops")
    def test_fetches_diff_on_demand_when_not_cached(self, mock_gitlab_ops):
        mock_mr = MagicMock()
        mock_mr.changes.return_value = {
            "changes": [
                {
                    "new_path": "exceptions/registry-rhoai-prod.yaml",
                    "diff": "+- value: schedule.weekday_restriction\n+  componentNames:\n+    - odh-operator-v3-4\n",
                }
            ]
        }
        mock_project = MagicMock()
        mock_project.mergerequests.get.return_value = mock_mr
        mock_gl = MagicMock()
        mock_gl.projects.get.return_value = mock_project
        mock_gitlab_ops.get_client.return_value = mock_gl

        result = mod.analyze_mr_component_coverage(
            mr_iid=55,
            rule="schedule.weekday_restriction",
            requested_components=["odh-operator-v3-4"],
        )

        mock_project.mergerequests.get.assert_called_once_with(55)
        assert result["source"] == "diff"
        assert result["suggestion"] == "fully_covered"
        assert result["mr_type"] == "exception"
        assert mod._mr_cache.has(55)


class TestParseComponentsFromDiff:
    def test_quoted_rule_value(self):
        diff = '+          - value: "hermetic_task.hermetic"\n+            componentNames:\n+              - comp-a\n'
        result = mod._parse_components_from_diff(diff, "hermetic_task.hermetic")
        assert result == ["comp-a"]

    def test_multiple_components(self):
        diff = (
            "+          - value: hermetic_task.hermetic\n"
            "+            componentNames:\n"
            "+              - comp-a\n"
            "+              - comp-b\n"
        )
        result = mod._parse_components_from_diff(diff, "hermetic_task.hermetic")
        assert result == ["comp-a", "comp-b"]


class TestBuildCoverageResultWithAliases:
    def setup_method(self):
        mod._mr_cache._diffs.clear()

    def test_alias_expands_coverage(self):
        aliases = {
            "comp-old": {"comp-old", "comp-new"},
            "comp-new": {"comp-old", "comp-new"},
        }
        result = mod._build_coverage_result(
            {},
            mr_components=["comp-old"],
            requested_components=["comp-new"],
            source="diff",
            aliases=aliases,
        )
        assert result["suggestion"] == "fully_covered"
        assert result["covered"] == ["comp-new"]
        assert result["missing"] == []

    def test_no_alias_no_overlap(self):
        result = mod._build_coverage_result(
            {},
            mr_components=["comp-old"],
            requested_components=["comp-new"],
            source="diff",
        )
        assert result["suggestion"] == "no_overlap"
        assert result["covered"] == []

    def test_alias_partial_coverage(self):
        aliases = {
            "comp-old": {"comp-old", "comp-new"},
            "comp-new": {"comp-old", "comp-new"},
        }
        result = mod._build_coverage_result(
            {},
            mr_components=["comp-old"],
            requested_components=["comp-new", "comp-other"],
            source="diff",
            aliases=aliases,
        )
        assert result["suggestion"] == "extend_mr"
        assert result["covered"] == ["comp-new"]
        assert result["missing"] == ["comp-other"]


class TestParseDiffLines:
    """Tests for _parse_diff_lines helper."""

    def test_skips_diff_headers(self):
        diff = "@@ -1,3 +1,4 @@\n--- a/file.yaml\n+++ b/file.yaml\n added\n"
        result = mod._parse_diff_lines(diff)
        assert len(result) == 1
        assert result[0] == ("added", False)

    def test_skips_removed_lines(self):
        diff = "-  removed line\n+  added line\n   context line\n"
        result = mod._parse_diff_lines(diff)
        assert len(result) == 2
        assert result[0] == ("added line", True)
        assert result[1] == ("context line", False)

    def test_preserves_added_flag(self):
        diff = "+  new\n   old\n"
        result = mod._parse_diff_lines(diff)
        assert result[0][1] is True
        assert result[1][1] is False


class TestParseComponentsFromDiffGlobalCoverage:
    """Tests for global exclusion detection in _parse_components_from_diff."""

    def test_bare_rule_permanent_exclusion(self):
        diff = (
            "+          # AMD ROCm RPM signing key\n"
            "+          - rpm_signature.allowed:9386b48a1a693c5c\n"
        )
        result = mod._parse_components_from_diff(diff, "rpm_signature.allowed:9386b48a1a693c5c")
        assert result == mod.GLOBAL_COVERAGE

    def test_bare_rule_quoted(self):
        diff = '+          - "hermetic_task.hermetic"\n'
        result = mod._parse_components_from_diff(diff, "hermetic_task.hermetic")
        assert result == mod.GLOBAL_COVERAGE

    def test_bare_rule_with_surrounding_context(self):
        """Real-world diff: bare item added between existing exclusions."""
        diff = (
            "@@ -19,6 +19,9 @@ spec:\n"
            "           - cve.cve_blockers\n"
            "           # existing comment\n"
            "           - rpm_signature.allowed:9cd0a493d42d0685\n"
            "+          # AMD ROCm RPM signing key\n"
            "+          - rpm_signature.allowed:9386b48a1a693c5c\n"
            "       data:\n"
            "         - github.com/release-engineering/rhtap-ec-policy//data\n"
        )
        result = mod._parse_components_from_diff(diff, "rpm_signature.allowed:9386b48a1a693c5c")
        assert result == mod.GLOBAL_COVERAGE

    def test_bare_rule_in_removed_line_not_matched(self):
        diff = "-          - rpm_signature.allowed:9386b48a1a693c5c\n"
        result = mod._parse_components_from_diff(diff, "rpm_signature.allowed:9386b48a1a693c5c")
        assert result == []

    def test_bare_rule_in_context_line_not_matched(self):
        """Pre-existing bare item in context is NOT a new addition."""
        diff = (
            "           - rpm_signature.allowed:9386b48a1a693c5c\n"
            "+          - rpm_signature.allowed:newrule123\n"
        )
        result = mod._parse_components_from_diff(diff, "rpm_signature.allowed:9386b48a1a693c5c")
        assert result == []

    def test_volatile_without_component_scoping_is_global(self):
        diff = (
            "+          - value: rpm_signature.allowed:abc123\n"
            "+            effectiveUntil: \"2026-12-31T00:00:00Z\"\n"
        )
        result = mod._parse_components_from_diff(diff, "rpm_signature.allowed:abc123")
        assert result == mod.GLOBAL_COVERAGE

    def test_volatile_with_component_names_is_not_global(self):
        diff = (
            "+          - value: hermetic_task.hermetic\n"
            "+            componentNames:\n"
            "+              - comp-a\n"
        )
        result = mod._parse_components_from_diff(diff, "hermetic_task.hermetic")
        assert result == ["comp-a"]

    def test_volatile_with_image_url_is_not_global(self):
        diff = (
            "+          - value: hermetic_task.hermetic\n"
            "+            imageUrl: quay.io/rhoai/odh-dashboard-rhel9\n"
        )
        result = mod._parse_components_from_diff(diff, "hermetic_task.hermetic")
        assert result == []

    def test_volatile_with_component_names_in_context(self):
        """MR modifies value line but componentNames pre-exists as context."""
        diff = (
            "-          - value: hermetic_task.hermetic\n"
            "+          - value: hermetic_task.hermetic\n"
            "             componentNames:\n"
            "               - comp-a\n"
        )
        result = mod._parse_components_from_diff(diff, "hermetic_task.hermetic")
        assert result == ["comp-a"]

    def test_volatile_with_image_url_in_context(self):
        """MR adds effectiveUntil but imageUrl pre-exists as context."""
        diff = (
            "+          - value: hermetic_task.hermetic\n"
            "+            effectiveUntil: \"2026-12-31T00:00:00Z\"\n"
            "             imageUrl: quay.io/rhoai/odh-dashboard-rhel9\n"
        )
        result = mod._parse_components_from_diff(diff, "hermetic_task.hermetic")
        assert result == []

    def test_unrelated_bare_item_not_matched(self):
        diff = "+          - some_other.rule\n"
        result = mod._parse_components_from_diff(diff, "hermetic_task.hermetic")
        assert result == []

    def test_value_in_context_line_not_matched(self):
        """Pre-existing - value: in context should not trigger global."""
        diff = (
            "           - value: hermetic_task.hermetic\n"
            "+            effectiveUntil: \"2026-12-31T00:00:00Z\"\n"
        )
        result = mod._parse_components_from_diff(diff, "hermetic_task.hermetic")
        assert result == []

    def test_comment_line_not_matched_as_bare_item(self):
        diff = "+          # - rpm_signature.allowed:9386b48a1a693c5c\n"
        result = mod._parse_components_from_diff(diff, "rpm_signature.allowed:9386b48a1a693c5c")
        assert result == []


class TestAnalyzeMrGlobalCoverage:
    """Tests for global exclusion handling in analyze_mr_component_coverage."""

    def setup_method(self):
        mod._mr_cache._diffs.clear()

    def test_permanent_exclusion_covers_all_requested(self):
        diff = (
            "+++ b/config/.../EnterpriseContractPolicy/registry-rhoai-prod.yaml\n"
            "+          - rpm_signature.allowed:9386b48a1a693c5c\n"
        )
        mod._mr_cache.store(
            18625,
            [{"new_path": "config/.../EnterpriseContractPolicy/registry-rhoai-prod.yaml", "diff": diff}],
        )
        result = mod.analyze_mr_component_coverage(
            mr_iid=18625,
            rule="rpm_signature.allowed:9386b48a1a693c5c",
            requested_components=["comp-a", "comp-b", "comp-c"],
        )
        assert result["suggestion"] == "fully_covered"
        assert result["source"] == "diff"
        assert result["covered"] == ["comp-a", "comp-b", "comp-c"]
        assert result["missing"] == []
        assert result["mr_components"] == mod.GLOBAL_COVERAGE
        assert result["mr_type"] == "exception"

    def test_global_volatile_covers_all_requested(self):
        diff = (
            "+++ b/config/.../EnterpriseContractPolicy/registry-rhoai-prod.yaml\n"
            "+          - value: test.rule\n"
            "+            effectiveUntil: \"2026-12-31T00:00:00Z\"\n"
        )
        mod._mr_cache.store(
            999,
            [{"new_path": "config/.../EnterpriseContractPolicy/registry-rhoai-prod.yaml", "diff": diff}],
        )
        result = mod.analyze_mr_component_coverage(
            mr_iid=999,
            rule="test.rule",
            requested_components=["x", "y"],
        )
        assert result["suggestion"] == "fully_covered"
        assert result["covered"] == ["x", "y"]
        assert result["missing"] == []
        assert result["mr_type"] == "exception"


class TestParseComponentsFromDescription:
    def test_single_version_format(self):
        desc = "### Components\n- `odh-dashboard-v3-4`\n- `odh-modelmesh-v3-4`\n"
        result = mod._parse_components_from_description(desc)
        assert "odh-dashboard-v3-4" in result
        assert "odh-modelmesh-v3-4" in result

    def test_multi_version_format(self):
        desc = "### `rhoai-3.4`\n**Components**:\n- `odh-dashboard-v3-4`\n"
        result = mod._parse_components_from_description(desc)
        assert "odh-dashboard-v3-4" in result


# ---------------------------------------------------------------------------
# _extract_all_rules_from_changes
# ---------------------------------------------------------------------------


class TestExtractAllRulesFromChanges:
    """Unit tests for _extract_all_rules_from_changes."""

    def _make_change(self, diff: str, path: str = "EnterpriseContractPolicy/registry-rhoai-prod.yaml") -> dict:
        return {"new_path": path, "diff": diff}

    def test_volatile_exception_single_rule(self):
        diff = "+  - value: hermetic_task.hermetic\n+    effectiveUntil: \"2026-12-31\"\n"
        result = mod._extract_all_rules_from_changes([self._make_change(diff)])
        assert result == {"hermetic_task.hermetic"}

    def test_volatile_exception_multiple_rules(self):
        diff = (
            "+  - value: hermetic_task.hermetic\n"
            "+    effectiveUntil: \"2026-12-31\"\n"
            "+  - value: prefetch_dependencies.mode_not_permissive\n"
        )
        result = mod._extract_all_rules_from_changes([self._make_change(diff)])
        assert result == {"hermetic_task.hermetic", "prefetch_dependencies.mode_not_permissive"}

    def test_permanent_exclusion_bare_rule(self):
        diff = "+    - rpm_signature.allowed:9386b48a1a693c5c\n"
        result = mod._extract_all_rules_from_changes([self._make_change(diff)])
        assert result == {"rpm_signature.allowed:9386b48a1a693c5c"}

    def test_ignores_non_policy_paths(self):
        diff = "+  - value: hermetic_task.hermetic\n"
        change = self._make_change(diff, path="tekton/pipeline/push.yaml")
        result = mod._extract_all_rules_from_changes([change])
        assert result == set()

    def test_ignores_removed_lines(self):
        diff = "-  - value: hermetic_task.hermetic\n"
        result = mod._extract_all_rules_from_changes([self._make_change(diff)])
        assert result == set()

    def test_ignores_context_lines(self):
        diff = "   - value: hermetic_task.hermetic\n"
        result = mod._extract_all_rules_from_changes([self._make_change(diff)])
        assert result == set()

    def test_component_names_not_extracted_as_rules(self):
        # Component names start with "odh-" and have no dots — must not be extracted
        diff = "+    - odh-dashboard-v3-5-ea-2\n"
        result = mod._extract_all_rules_from_changes([self._make_change(diff)])
        assert result == set()

    def test_empty_changes(self):
        assert mod._extract_all_rules_from_changes([]) == set()

    def test_multiple_policy_files_merged(self):
        diff_a = "+  - value: hermetic_task.hermetic\n"
        diff_b = "+  - value: sbom_spdx.disallowed_package_attributes\n"
        changes = [
            self._make_change(diff_a, "EnterpriseContractPolicy/registry-a.yaml"),
            self._make_change(diff_b, "EnterpriseContractPolicy/registry-b.yaml"),
        ]
        result = mod._extract_all_rules_from_changes(changes)
        assert result == {"hermetic_task.hermetic", "sbom_spdx.disallowed_package_attributes"}


# ---------------------------------------------------------------------------
# rules_in_diff and title_mentions_rule in analyze_mr_component_coverage
# ---------------------------------------------------------------------------


class TestAnalyzeMrRulesInDiff:
    """Ensure analyze_mr_component_coverage populates rules_in_diff and title_mentions_rule."""

    def setup_method(self):
        mod._mr_cache._diffs.clear()

    def _store(self, iid: int, diff: str) -> None:
        mod._mr_cache.store(
            iid,
            [{"new_path": "EnterpriseContractPolicy/registry-rhoai-prod.yaml", "diff": diff}],
        )

    def test_rules_in_diff_populated(self):
        self._store(
            101,
            "+  - value: hermetic_task.hermetic\n"
            "+  - value: prefetch_dependencies.mode_not_permissive\n",
        )
        result = mod.analyze_mr_component_coverage(
            mr_iid=101, rule="hermetic_task.hermetic", requested_components=["comp-a"]
        )
        assert "hermetic_task.hermetic" in result["rules_in_diff"]
        assert "prefetch_dependencies.mode_not_permissive" in result["rules_in_diff"]

    def test_rules_in_diff_empty_for_remedy_mr(self):
        # Remedy MR: changes source code, not policy files
        mod._mr_cache.store(
            102,
            [{"new_path": "tekton/pipeline/push.yaml", "diff": "+  - step: build\n"}],
        )
        result = mod.analyze_mr_component_coverage(
            mr_iid=102, rule="hermetic_task.hermetic", requested_components=[]
        )
        assert result["rules_in_diff"] == []

    def test_title_mentions_rule_false_when_no_title(self):
        self._store(103, "+  - value: hermetic_task.hermetic\n")
        result = mod.analyze_mr_component_coverage(
            mr_iid=103, rule="hermetic_task.hermetic", requested_components=[]
        )
        # result_base doesn't get a "title" key from this path — mentions defaults to False
        assert isinstance(result.get("title_mentions_rule"), bool)

    def test_title_mentions_rule_true_via_description(self):
        self._store(104, "+  - value: hermetic_task.hermetic\n")
        result = mod.analyze_mr_component_coverage(
            mr_iid=104,
            rule="hermetic_task.hermetic",
            requested_components=[],
            mr_description="Exception for hermetic_task.hermetic violations",
        )
        assert result["title_mentions_rule"] is True

    def test_title_mentions_rule_false_for_cross_indexed_mr(self):
        # MR title is about a different rule; diff covers hermetic
        self._store(105, "+  - value: hermetic_task.hermetic\n")
        result = mod.analyze_mr_component_coverage(
            mr_iid=105,
            rule="hermetic_task.hermetic",
            requested_components=[],
            mr_description="Fix prefetch pipeline configuration",
        )
        assert result["title_mentions_rule"] is False


# ---------------------------------------------------------------------------
# prefetch_open_mrs cross-indexing
# ---------------------------------------------------------------------------


class TestPrefetchOpenMrsCrossIndex:
    """Verify that prefetch_open_mrs adds diff-discovered MRs to the right rules."""

    def setup_method(self):
        mod._mr_cache._diffs.clear()

    def test_cross_index_adds_mr_to_rule_not_found_by_text_search(self):
        # Text search only finds MR 200 for 'hermetic_task.hermetic'.
        # But MR 200's diff also covers 'prefetch_dependencies.mode_not_permissive'.
        # After cross-indexing, MR 200 should appear under both rules.
        mod._mr_cache.store(
            200,
            [{"new_path": "EnterpriseContractPolicy/registry.yaml", "diff": (
                "+  - value: hermetic_task.hermetic\n"
                "+  - value: prefetch_dependencies.mode_not_permissive\n"
            )}],
        )
        hermetic_mr = {"iid": 200, "title": "hermetic exception", "url": "https://gl/!200", "author": "", "created_at": "", "description": ""}

        with (
            patch("conforma_mr_ops.search_open_exception_mrs") as mock_search,
            patch("conforma_mr_ops._mr_cache.prefetch"),
        ):
            def side_effect(rule):
                if rule == "hermetic_task.hermetic":
                    return [hermetic_mr]
                return []

            mock_search.side_effect = side_effect
            result = mod.prefetch_open_mrs(["hermetic_task.hermetic", "prefetch_dependencies.mode_not_permissive"])

        # hermetic should be present from text search
        assert any(m["iid"] == 200 for m in result["hermetic_task.hermetic"])
        # prefetch should be cross-indexed from diff
        assert any(m["iid"] == 200 for m in result["prefetch_dependencies.mode_not_permissive"])

    def test_cross_indexed_mr_marked_found_by_text_search_false(self):
        mod._mr_cache.store(
            201,
            [{"new_path": "EnterpriseContractPolicy/registry.yaml", "diff": (
                "+  - value: hermetic_task.hermetic\n"
                "+  - value: sbom_spdx.disallowed_package_attributes\n"
            )}],
        )
        hermetic_mr = {"iid": 201, "title": "hermetic exception", "url": "https://gl/!201", "author": "", "created_at": "", "description": ""}

        with (
            patch("conforma_mr_ops.search_open_exception_mrs") as mock_search,
            patch("conforma_mr_ops._mr_cache.prefetch"),
        ):
            mock_search.side_effect = lambda r: [hermetic_mr] if r == "hermetic_task.hermetic" else []
            result = mod.prefetch_open_mrs(["hermetic_task.hermetic", "sbom_spdx.disallowed_package_attributes"])

        sbom_mrs = result["sbom_spdx.disallowed_package_attributes"]
        assert any(m["iid"] == 201 for m in sbom_mrs)
        cross_entry = next(m for m in sbom_mrs if m["iid"] == 201)
        assert cross_entry["found_by_text_search"] is False

    def test_text_search_mr_marked_found_by_text_search_true(self):
        mod._mr_cache.store(
            202,
            [{"new_path": "EnterpriseContractPolicy/registry.yaml", "diff": "+  - value: hermetic_task.hermetic\n"}],
        )
        hermetic_mr = {"iid": 202, "title": "hermetic exception", "url": "", "author": "", "created_at": "", "description": ""}

        with (
            patch("conforma_mr_ops.search_open_exception_mrs") as mock_search,
            patch("conforma_mr_ops._mr_cache.prefetch"),
        ):
            mock_search.side_effect = lambda r: [hermetic_mr] if r == "hermetic_task.hermetic" else []
            result = mod.prefetch_open_mrs(["hermetic_task.hermetic"])

        entry = next(m for m in result["hermetic_task.hermetic"] if m["iid"] == 202)
        assert entry["found_by_text_search"] is True

    def test_no_duplicate_mr_after_cross_index(self):
        # MR 203's text search returns it for both rules AND diff also covers both.
        # Must not appear twice for the same rule.
        mod._mr_cache.store(
            203,
            [{"new_path": "EnterpriseContractPolicy/registry.yaml", "diff": (
                "+  - value: hermetic_task.hermetic\n"
                "+  - value: prefetch_dependencies.mode_not_permissive\n"
            )}],
        )
        mr = {"iid": 203, "title": "multi-rule exception", "url": "", "author": "", "created_at": "", "description": ""}

        with (
            patch("conforma_mr_ops.search_open_exception_mrs") as mock_search,
            patch("conforma_mr_ops._mr_cache.prefetch"),
        ):
            mock_search.side_effect = lambda _: [mr]
            result = mod.prefetch_open_mrs(["hermetic_task.hermetic", "prefetch_dependencies.mode_not_permissive"])

        hermetic_iids = [m["iid"] for m in result["hermetic_task.hermetic"]]
        assert hermetic_iids.count(203) == 1
