"""Tests for scripts/component_catalog_ops.py."""

from __future__ import annotations

from component_catalog_ops import (
    _build_lookup_index,
    _extract_jira_component,
    _strip_os_suffix,
    _strip_version_suffix,
    extract_components_from_ticket,
    resolve_jira_component,
    resolve_jira_components,
)

MOCK_CATALOG = [
    {"name": "odh-workbench-jupyter-trustyai-cpu-py312-rhel9", "jira_components": ["Notebooks Server"]},
    {"name": "odh-dashboard-rhel9", "jira_components": ["Dashboard"]},
    {"name": "rhoai-fbc-fragment", "jira_components": ["Build and Release"]},
    {"name": "odh-vllm-cpu-rhel9", "jira_components": ["Serving"]},
    {"name": "odh-spark-operator-rhel9", "jira_components": ["Workload Orchestration"]},
    {"name": "odh-training-cuda128-torch29-py312-rhel9", "jira_components": ["Training"]},
    {"name": "odh-training-rocm64-torch29-py312-rhel9", "jira_components": ["Training"]},
    {"name": "odh-pipeline-runtime-datascience-cpu-py312-rhel9", "jira_components": ["Data Science Pipelines"]},
    {"name": "ray", "jira_components": ["Workload Orchestration"]},
    {"name": "odh-openvino-model-server-rhel9", "jira_components": ["Serving"]},
    # Midstream entry without odh- prefix (Konflux name adds odh-)
    {"name": "model-registry-job-async-upload", "jira_components": ["AI Hub"]},
    # Entry with singular field format (backward compat)
    {"name": "codeflare-operator", "jira_component": "Workload Orchestration"},
    # Entry without jira_component (unmapped)
    {"name": "openshift-utils", "jira_components": []},
    {"name": "tracer", "jira_components": []},
]


class TestStripVersionSuffix:
    def test_strip_ea_version(self):
        assert _strip_version_suffix("odh-dashboard-v3-5-ea-1") == "odh-dashboard"

    def test_strip_ga_version(self):
        assert _strip_version_suffix("rhoai-fbc-fragment-v3-5") == "rhoai-fbc-fragment"

    def test_strip_two_digit_version(self):
        assert _strip_version_suffix("odh-dashboard-v2-25") == "odh-dashboard"

    def test_no_version_suffix(self):
        assert _strip_version_suffix("rhoai-fbc-fragment") == "rhoai-fbc-fragment"

    def test_digits_in_base_name(self):
        assert (
            _strip_version_suffix("odh-training-cuda128-torch29-py312-v3-5-ea-1")
            == "odh-training-cuda128-torch29-py312"
        )

    def test_digits_in_base_no_version(self):
        assert _strip_version_suffix("odh-training-cuda128-torch29-py312") == "odh-training-cuda128-torch29-py312"

    def test_rocm_with_version(self):
        assert (
            _strip_version_suffix("odh-training-rocm64-torch29-py312-v3-5-ea-1") == "odh-training-rocm64-torch29-py312"
        )


class TestStripOsSuffix:
    def test_strip_rhel9(self):
        assert _strip_os_suffix("odh-dashboard-rhel9") == "odh-dashboard"

    def test_strip_ubi9(self):
        assert _strip_os_suffix("odh-dashboard-ubi9") == "odh-dashboard"

    def test_no_os_suffix(self):
        assert _strip_os_suffix("rhoai-fbc-fragment") == "rhoai-fbc-fragment"

    def test_rhel8(self):
        assert _strip_os_suffix("some-image-rhel8") == "some-image"

    def test_digits_in_base(self):
        assert _strip_os_suffix("odh-training-cuda128-torch29-py312-rhel9") == "odh-training-cuda128-torch29-py312"


class TestExtractJiraComponent:
    def test_list_format(self):
        assert _extract_jira_component({"jira_components": ["AI Hub"]}) == "AI Hub"

    def test_string_format(self):
        assert _extract_jira_component({"jira_component": "Dashboard"}) == "Dashboard"

    def test_empty_list(self):
        assert _extract_jira_component({"jira_components": []}) is None

    def test_no_field(self):
        assert _extract_jira_component({"name": "test"}) is None

    def test_list_takes_first(self):
        assert _extract_jira_component({"jira_components": ["A", "B"]}) == "A"


class TestBuildLookupIndex:
    def test_includes_raw_and_stripped(self):
        index = _build_lookup_index(MOCK_CATALOG)
        assert index["odh-dashboard-rhel9"] == "Dashboard"
        assert index["odh-dashboard"] == "Dashboard"

    def test_bare_names_included(self):
        index = _build_lookup_index(MOCK_CATALOG)
        assert index["rhoai-fbc-fragment"] == "Build and Release"
        assert index["ray"] == "Workload Orchestration"

    def test_unmapped_excluded(self):
        index = _build_lookup_index(MOCK_CATALOG)
        assert "openshift-utils" not in index
        assert "tracer" not in index

    def test_odh_prefix_added(self):
        index = _build_lookup_index(MOCK_CATALOG)
        assert index["odh-model-registry-job-async-upload"] == "AI Hub"

    def test_singular_field_compat(self):
        index = _build_lookup_index(MOCK_CATALOG)
        assert index["codeflare-operator"] == "Workload Orchestration"

    def test_repo_basename_in_index(self):
        catalog = [
            {
                "name": "odh-vllm-gaudi-rhel9",
                "jira_components": ["Model Runtimes"],
                "repos": ["red-hat-data-services/vllm-gaudi"],
            },
        ]
        index = _build_lookup_index(catalog)
        assert index["vllm-gaudi"] == "Model Runtimes"
        assert index["odh-vllm-gaudi"] == "Model Runtimes"

    def test_repo_underscore_normalized(self):
        catalog = [
            {
                "name": "odh-openvino-model-server-rhel9",
                "jira_components": ["Model Runtimes"],
                "repos": ["red-hat-data-services/openvino_model_server"],
            },
        ]
        index = _build_lookup_index(catalog)
        assert index["openvino_model_server"] == "Model Runtimes"
        assert index["openvino-model-server"] == "Model Runtimes"
        assert index["odh-openvino-model-server"] == "Model Runtimes"


class TestResolveJiraComponent:
    def test_exact_match(self):
        assert resolve_jira_component("odh-dashboard-rhel9", MOCK_CATALOG) == "Dashboard"

    def test_version_stripped_match(self):
        assert resolve_jira_component("odh-dashboard-v3-5-ea-1", MOCK_CATALOG) == "Dashboard"

    def test_bare_name_with_version(self):
        assert resolve_jira_component("rhoai-fbc-fragment-v3-5", MOCK_CATALOG) == "Build and Release"

    def test_bare_name_no_version(self):
        assert resolve_jira_component("rhoai-fbc-fragment", MOCK_CATALOG) == "Build and Release"

    def test_digits_in_base_with_version(self):
        assert resolve_jira_component("odh-training-cuda128-torch29-py312-v3-5-ea-1", MOCK_CATALOG) == "Training"

    def test_rocm_with_version(self):
        assert resolve_jira_component("odh-training-rocm64-torch29-py312-v3-5-ea-1", MOCK_CATALOG) == "Training"

    def test_unmapped_returns_none(self):
        assert resolve_jira_component("some-unknown-component-v3-5", MOCK_CATALOG) is None

    def test_bare_unmapped_returns_none(self):
        assert resolve_jira_component("openshift-utils", MOCK_CATALOG) is None

    def test_pipeline_runtime(self):
        assert (
            resolve_jira_component("odh-pipeline-runtime-datascience-cpu-py312-v3-5-ea-1", MOCK_CATALOG)
            == "Data Science Pipelines"
        )

    def test_odh_prefix_match(self):
        assert resolve_jira_component("odh-model-registry-job-async-upload-v3-4", MOCK_CATALOG) == "AI Hub"

    def test_singular_field_compat(self):
        assert resolve_jira_component("odh-codeflare-operator-v3-5", MOCK_CATALOG) == "Workload Orchestration"

    def test_os_suffix_input_stripped(self):
        assert resolve_jira_component("odh-dashboard-rhel9", MOCK_CATALOG) == "Dashboard"

    def test_os_suffix_input_on_catalog_without_os(self):
        """Image name with OS suffix resolves via OS-strip + odh-prefix matching."""
        catalog = [{"name": "vllm", "jira_components": ["Model Runtimes"]}]
        assert resolve_jira_component("odh-vllm-rhel9", catalog) == "Model Runtimes"
        assert resolve_jira_component("vllm-rhel9", catalog) == "Model Runtimes"


class TestResolveJiraComponents:
    def test_batch_resolution(self):
        names = [
            "odh-dashboard-v3-5-ea-1",
            "rhoai-fbc-fragment-v3-5",
            "odh-vllm-cpu-v3-5-ea-1",
        ]
        result = resolve_jira_components(names, MOCK_CATALOG)
        assert result == {
            "odh-dashboard-v3-5-ea-1": "Dashboard",
            "rhoai-fbc-fragment-v3-5": "Build and Release",
            "odh-vllm-cpu-v3-5-ea-1": "Serving",
        }

    def test_mixed_mapped_and_unmapped(self):
        names = ["odh-dashboard-v3-5-ea-1", "some-unknown-v3-5"]
        result = resolve_jira_components(names, MOCK_CATALOG)
        assert result["odh-dashboard-v3-5-ea-1"] == "Dashboard"
        assert result["some-unknown-v3-5"] is None

    def test_multiple_map_to_same_component(self):
        names = [
            "odh-training-cuda128-torch29-py312-v3-5-ea-1",
            "odh-training-rocm64-torch29-py312-v3-5-ea-1",
        ]
        result = resolve_jira_components(names, MOCK_CATALOG)
        assert result["odh-training-cuda128-torch29-py312-v3-5-ea-1"] == "Training"
        assert result["odh-training-rocm64-torch29-py312-v3-5-ea-1"] == "Training"

    def test_empty_list(self):
        assert resolve_jira_components([], MOCK_CATALOG) == {}

    def test_all_unmapped(self):
        names = ["foo-v3-5", "bar-v2-25"]
        result = resolve_jira_components(names, MOCK_CATALOG)
        assert all(v is None for v in result.values())


class TestExtractComponentsFromTicket:
    def test_from_exception_label(self):
        labels = [
            "conforma-exception-ai-skill",
            "Exception-hermetic_task.hermetic:odh-dashboard-v3-5-ea-1",
            "conforma-violation",
        ]
        result = extract_components_from_ticket(labels, None)
        assert result == ["odh-dashboard-v3-5-ea-1"]

    def test_from_exception_label_space_separator(self):
        labels = ["Exception - rpm_signature.allowed:odh-vllm-cpu-v3-5-ea-1"]
        result = extract_components_from_ticket(labels, None)
        assert result == ["odh-vllm-cpu-v3-5-ea-1"]

    def test_from_plain_text_description(self):
        desc = "Affected images: odh-vllm-gaudi-rhel9, odh-vllm-cpu-rhel9 need legal review."
        result = extract_components_from_ticket([], desc)
        assert result == ["odh-vllm-cpu-rhel9", "odh-vllm-gaudi-rhel9"]

    def test_from_adf_description(self):
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Container: odh-openvino-model-server-rhel9"}],
                }
            ],
        }
        result = extract_components_from_ticket([], adf)
        assert result == ["odh-openvino-model-server-rhel9"]

    def test_from_quay_url_in_description(self):
        desc = "See quay.io/rhoai/odh-spark-operator-rhel9@sha256:abc123 for details."
        result = extract_components_from_ticket([], desc)
        assert "odh-spark-operator-rhel9" in result

    def test_combined_labels_and_description(self):
        labels = ["Exception-rule:odh-dashboard-v3-5"]
        desc = "Also affected: odh-vllm-gaudi-rhel9"
        result = extract_components_from_ticket(labels, desc)
        assert "odh-dashboard-v3-5" in result
        assert "odh-vllm-gaudi-rhel9" in result

    def test_empty_inputs(self):
        assert extract_components_from_ticket([], None) == []
        assert extract_components_from_ticket([], "") == []
        assert extract_components_from_ticket(None, None) == []

    def test_deduplication(self):
        desc = "odh-vllm-gaudi-rhel9 and odh-vllm-gaudi-rhel9 again"
        result = extract_components_from_ticket([], desc)
        assert result == ["odh-vllm-gaudi-rhel9"]
