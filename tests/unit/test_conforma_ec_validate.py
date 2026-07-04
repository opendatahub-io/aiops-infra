"""Tests for scripts/conforma_ec_validate.py."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import conforma_ec_validate


@pytest.fixture()
def csv_file(tmp_path):
    """Create a minimal CSV report file."""
    csv = tmp_path / "report.csv"
    csv.write_text(textwrap.dedent("""\
        type,component_name,image,message,effective_on,code,title,description,solution
        violation,odh-dashboard-v3-5,quay.io/rhoai/odh-dashboard@sha256:aaa111,msg1,,sbom_spdx.allowed,Title1,Desc1,Sol1
        violation,odh-dashboard-v3-5,quay.io/rhoai/odh-dashboard@sha256:bbb222,msg2,,rpm_packages.unique_version,Title2,Desc2,Sol2
        violation,model-registry-v3-5,quay.io/rhoai/model-registry@sha256:ccc333,msg3,,hermetic_task.hermetic,Title3,Desc3,Sol3
        violation,model-registry-v3-5,quay.io/rhoai/model-registry@sha256:ccc333,msg4,,rpm_signature.allowed,Title4,Desc4,Sol4
        warning,odh-dashboard-v3-5,quay.io/rhoai/odh-dashboard@sha256:aaa111,warn,,some_warning,Warn,Warn,Warn
    """))
    return str(csv)


@pytest.fixture()
def policy_file(tmp_path):
    """Create a minimal policy YAML file with k8s publicKey."""
    policy = tmp_path / "policy.yaml"
    policy.write_text(textwrap.dedent("""\
        apiVersion: appstudio.redhat.com/v1alpha1
        kind: EnterpriseContractPolicy
        metadata:
          name: rhoai-policy
        spec:
          publicKey: 'k8s://openshift-pipelines/public-key'
          sources:
            - name: release-policies
              policy:
                - "oci::quay.io/enterprise-contract/ec-release-policy:latest"
    """))
    return str(policy)


@pytest.fixture()
def policy_file_no_k8s(tmp_path):
    """Create a policy YAML file without k8s publicKey."""
    policy = tmp_path / "policy-no-k8s.yaml"
    policy.write_text(textwrap.dedent("""\
        apiVersion: appstudio.redhat.com/v1alpha1
        kind: EnterpriseContractPolicy
        metadata:
          name: rhoai-policy
        spec:
          publicKey: 'cosign.pub'
          sources:
            - name: release-policies
              policy:
                - "oci::quay.io/enterprise-contract/ec-release-policy:latest"
    """))
    return str(policy)


class TestBuildSnapshotFromEntries:
    def test_writes_spec_json(self, tmp_path):
        entries = [
            {"name": "comp1", "containerImage": "quay.io/x@sha256:aaa"},
            {"name": "comp2", "containerImage": "quay.io/y@sha256:bbb"},
        ]
        output = str(tmp_path / "spec.json")
        path = conforma_ec_validate.build_snapshot_from_entries(entries, output)
        spec = json.loads(path.read_text())
        assert len(spec["components"]) == 2
        assert spec["components"][0]["name"] == "comp1"

    def test_creates_parent_dirs(self, tmp_path):
        entries = [{"name": "c", "containerImage": "img"}]
        output = str(tmp_path / "nested" / "dir" / "spec.json")
        path = conforma_ec_validate.build_snapshot_from_entries(entries, output)
        assert path.exists()

    def test_empty_entries_raises(self, tmp_path):
        with pytest.raises(conforma_ec_validate.EcValidateError, match="No entries"):
            conforma_ec_validate.build_snapshot_from_entries(
                [], str(tmp_path / "spec.json")
            )


class TestGroupEntriesByBaseImage:
    def test_groups_by_base_url(self):
        entries = [
            {"name": "comp1", "containerImage": "quay.io/rhoai/img@sha256:aaa"},
            {"name": "comp1", "containerImage": "quay.io/rhoai/img@sha256:bbb"},
            {"name": "comp2", "containerImage": "quay.io/rhoai/other@sha256:ccc"},
        ]
        groups = conforma_ec_validate.group_entries_by_base_image(entries)
        assert len(groups) == 2
        assert len(groups["quay.io/rhoai/img"]) == 2
        assert len(groups["quay.io/rhoai/other"]) == 1

    def test_handles_no_digest(self):
        entries = [{"name": "c", "containerImage": "quay.io/img:latest"}]
        groups = conforma_ec_validate.group_entries_by_base_image(entries)
        assert "quay.io/img:latest" in groups

    def test_empty_entries(self):
        assert conforma_ec_validate.group_entries_by_base_image([]) == {}

    def test_preserves_insertion_order(self):
        entries = [
            {"name": "c1", "containerImage": "quay.io/b@sha256:111"},
            {"name": "c2", "containerImage": "quay.io/a@sha256:222"},
            {"name": "c1", "containerImage": "quay.io/b@sha256:333"},
        ]
        groups = conforma_ec_validate.group_entries_by_base_image(entries)
        keys = list(groups.keys())
        assert keys == ["quay.io/b", "quay.io/a"]


class TestBuildSnapshotFromCsv:
    def test_deduplicates_by_digest(self, csv_file, tmp_path):
        output = str(tmp_path / "spec.json")
        path, entries = conforma_ec_validate.build_snapshot_from_csv(csv_file, output)

        spec = json.loads(Path(output).read_text())
        names = [c["name"] for c in spec["components"]]

        assert "odh-dashboard-v3-5" in names
        assert "model-registry-v3-5" in names
        assert len(spec["components"]) == 3

    def test_returns_entries_list(self, csv_file, tmp_path):
        output = str(tmp_path / "spec.json")
        path, entries = conforma_ec_validate.build_snapshot_from_csv(csv_file, output)
        assert len(entries) == 3
        assert all("name" in e and "containerImage" in e for e in entries)
        assert path.exists()

    def test_component_images_have_digests(self, csv_file, tmp_path):
        output = str(tmp_path / "spec.json")
        _path, entries = conforma_ec_validate.build_snapshot_from_csv(csv_file, output)
        for entry in entries:
            assert "@sha256:" in entry["containerImage"]

    def test_empty_csv_raises(self, tmp_path):
        empty = tmp_path / "empty.csv"
        empty.write_text("type,component_name,image,code\n")
        with pytest.raises(conforma_ec_validate.EcValidateError, match="No valid"):
            conforma_ec_validate.build_snapshot_from_csv(
                str(empty), str(tmp_path / "out.json")
            )

    def test_creates_parent_dirs(self, csv_file, tmp_path):
        output = str(tmp_path / "nested" / "dir" / "spec.json")
        path, _entries = conforma_ec_validate.build_snapshot_from_csv(csv_file, output)
        assert path.exists()

    def test_spec_json_structure(self, csv_file, tmp_path):
        output = str(tmp_path / "spec.json")
        conforma_ec_validate.build_snapshot_from_csv(csv_file, output)
        spec = json.loads(Path(output).read_text())
        assert "components" in spec
        for comp in spec["components"]:
            assert "name" in comp
            assert "containerImage" in comp


class TestPreparePolicyForLocalUse:
    def test_replaces_k8s_public_key(self, policy_file, tmp_path):
        import yaml

        output = str(tmp_path / "local-policy.yaml")
        conforma_ec_validate.prepare_policy_for_local_use(policy_file, output)

        with open(output) as f:
            doc = yaml.safe_load(f)

        assert "publicKey" not in doc["spec"]
        assert "identity" in doc["spec"]
        assert "issuer" in doc["spec"]["identity"]
        assert "subject" in doc["spec"]["identity"]

    def test_preserves_non_k8s_key(self, policy_file_no_k8s, tmp_path):
        import yaml

        output = str(tmp_path / "local-policy.yaml")
        conforma_ec_validate.prepare_policy_for_local_use(policy_file_no_k8s, output)

        with open(output) as f:
            doc = yaml.safe_load(f)

        assert doc["spec"]["publicKey"] == "cosign.pub"
        assert "identity" not in doc["spec"]

    def test_preserves_sources(self, policy_file, tmp_path):
        import yaml

        output = str(tmp_path / "local-policy.yaml")
        conforma_ec_validate.prepare_policy_for_local_use(policy_file, output)

        with open(output) as f:
            doc = yaml.safe_load(f)

        assert len(doc["spec"]["sources"]) == 1
        assert doc["spec"]["sources"][0]["name"] == "release-policies"


class TestExtractCsvViolations:
    def test_extracts_violations_only(self, csv_file):
        result = conforma_ec_validate.extract_csv_violations(csv_file)
        assert "odh-dashboard-v3-5" in result
        assert "model-registry-v3-5" in result
        assert len(result) == 2

    def test_skips_warnings(self, csv_file):
        result = conforma_ec_validate.extract_csv_violations(csv_file)
        all_codes = set()
        for codes in result.values():
            all_codes.update(codes)
        assert "some_warning" not in all_codes

    def test_groups_by_component(self, csv_file):
        result = conforma_ec_validate.extract_csv_violations(csv_file)
        assert result["odh-dashboard-v3-5"] == {
            "sbom_spdx.allowed", "rpm_packages.unique_version"
        }
        assert result["model-registry-v3-5"] == {
            "hermetic_task.hermetic", "rpm_signature.allowed"
        }


class TestExtractEcViolations:
    def test_extracts_from_ec_output(self):
        ec_output = {
            "components": [
                {
                    "name": "odh-dashboard-v3-5",
                    "violations": [
                        {"metadata": {"code": "sbom_spdx.allowed"}},
                    ],
                },
                {
                    "name": "model-registry-v3-5",
                    "violations": [
                        {"metadata": {"code": "hermetic_task.hermetic"}},
                        {"metadata": {"code": "rpm_signature.allowed"}},
                    ],
                },
            ]
        }
        result = conforma_ec_validate.extract_ec_violations(ec_output)
        assert result["odh-dashboard-v3-5"] == {"sbom_spdx.allowed"}
        assert result["model-registry-v3-5"] == {
            "hermetic_task.hermetic", "rpm_signature.allowed"
        }

    def test_normalizes_component_names_with_digest_suffix(self):
        ec_output = {
            "components": [
                {
                    "name": "odh-dashboard-v3-5-sha256:aaa111bbb222-amd64",
                    "violations": [
                        {"metadata": {"code": "sbom_spdx.allowed"}},
                    ],
                },
            ]
        }
        result = conforma_ec_validate.extract_ec_violations(ec_output)
        assert "odh-dashboard-v3-5" in result

    def test_empty_components(self):
        result = conforma_ec_validate.extract_ec_violations({"components": []})
        assert result == {}

    def test_no_violations_key(self):
        ec_output = {"components": [{"name": "comp1"}]}
        result = conforma_ec_validate.extract_ec_violations(ec_output)
        assert result["comp1"] == set()

    def test_merges_violations_across_arch_variants(self):
        ec_output = {
            "components": [
                {
                    "name": "comp-sha256:aaa111-amd64",
                    "violations": [{"metadata": {"code": "rule.a"}}],
                },
                {
                    "name": "comp-sha256:bbb222-arm64",
                    "violations": [{"metadata": {"code": "rule.b"}}],
                },
            ]
        }
        result = conforma_ec_validate.extract_ec_violations(ec_output)
        assert result["comp"] == {"rule.a", "rule.b"}


class TestNormalizeEcComponentName:
    def test_strips_sha256_arch_suffix(self):
        assert conforma_ec_validate._normalize_ec_component_name(
            "odh-dashboard-v3-5-sha256:abc123def456-amd64"
        ) == "odh-dashboard-v3-5"

    def test_preserves_plain_name(self):
        assert conforma_ec_validate._normalize_ec_component_name(
            "model-registry-v3-5"
        ) == "model-registry-v3-5"

    def test_preserves_name_with_other_hyphens(self):
        assert conforma_ec_validate._normalize_ec_component_name(
            "odh-vllm-cpu-v3-5"
        ) == "odh-vllm-cpu-v3-5"


class TestExtractEcSuccesses:
    def test_extracts_from_ec_output(self):
        ec_output = {
            "components": [
                {
                    "name": "odh-dashboard-v3-5",
                    "successes": [
                        {"metadata": {"code": "hermetic_task.hermetic"}},
                    ],
                },
                {
                    "name": "model-registry-v3-5",
                    "successes": [
                        {"metadata": {"code": "sbom_spdx.allowed"}},
                        {"metadata": {"code": "rpm_packages.unique_version"}},
                    ],
                },
            ]
        }
        result = conforma_ec_validate.extract_ec_successes(ec_output)
        assert result["odh-dashboard-v3-5"] == {"hermetic_task.hermetic"}
        assert result["model-registry-v3-5"] == {
            "sbom_spdx.allowed", "rpm_packages.unique_version"
        }

    def test_normalizes_component_names(self):
        ec_output = {
            "components": [
                {
                    "name": "comp-sha256:aaa111bbb222-amd64",
                    "successes": [{"metadata": {"code": "rule.a"}}],
                },
            ]
        }
        result = conforma_ec_validate.extract_ec_successes(ec_output)
        assert "comp" in result
        assert result["comp"] == {"rule.a"}

    def test_empty_components(self):
        result = conforma_ec_validate.extract_ec_successes({"components": []})
        assert result == {}

    def test_no_successes_key(self):
        ec_output = {"components": [{"name": "comp1"}]}
        result = conforma_ec_validate.extract_ec_successes(ec_output)
        assert result["comp1"] == set()

    def test_merges_successes_across_arch_variants(self):
        ec_output = {
            "components": [
                {
                    "name": "comp-sha256:aaa111-amd64",
                    "successes": [{"metadata": {"code": "rule.a"}}],
                },
                {
                    "name": "comp-sha256:bbb222-arm64",
                    "successes": [{"metadata": {"code": "rule.b"}}],
                },
            ]
        }
        result = conforma_ec_validate.extract_ec_successes(ec_output)
        assert result["comp"] == {"rule.a", "rule.b"}


class TestValidateEcAgainstCsv:
    def test_all_confirmed(self):
        csv_viols = {"comp1": {"rule.a", "rule.b"}}
        ec_viols = {"comp1": {"rule.a"}}
        ec_succ = {"comp1": {"rule.b"}}
        result = conforma_ec_validate.validate_ec_against_csv(csv_viols, ec_viols, ec_succ)
        assert result["validated"] is True
        assert result["confirmed_violations"] == 1
        assert result["confirmed_covered"] == 1
        assert result["divergence_count"] == 0
        assert result["divergences"] == []

    def test_all_divergent(self):
        csv_viols = {"comp1": {"rule.a", "rule.b"}}
        ec_viols = {"comp1": set()}
        ec_succ = {"comp1": set()}
        result = conforma_ec_validate.validate_ec_against_csv(csv_viols, ec_viols, ec_succ)
        assert result["validated"] is False
        assert result["divergence_count"] == 2
        assert len(result["divergences"]) == 2

    def test_mixed(self):
        csv_viols = {"comp1": {"rule.a", "rule.b", "rule.c"}}
        ec_viols = {"comp1": {"rule.a"}}
        ec_succ = {"comp1": {"rule.b"}}
        result = conforma_ec_validate.validate_ec_against_csv(csv_viols, ec_viols, ec_succ)
        assert result["validated"] is False
        assert result["confirmed_violations"] == 1
        assert result["confirmed_covered"] == 1
        assert result["divergence_count"] == 1
        assert result["divergences"][0]["violation_code"] == "rule.c"
        assert "source CSV report" in result["divergences"][0]["reason"]
        assert "policy may have changed" in result["divergences"][0]["reason"]

    def test_empty_csv(self):
        result = conforma_ec_validate.validate_ec_against_csv({}, {}, {})
        assert result["validated"] is True
        assert result["total_csv_violations"] == 0

    def test_multi_component(self):
        csv_viols = {"comp1": {"rule.a"}, "comp2": {"rule.b"}}
        ec_viols = {"comp1": {"rule.a"}}
        ec_succ = {"comp2": set()}
        result = conforma_ec_validate.validate_ec_against_csv(csv_viols, ec_viols, ec_succ)
        assert result["validated"] is False
        assert result["confirmed_violations"] == 1
        assert result["divergence_count"] == 1
        assert result["divergences"][0]["component"] == "comp2"

    def test_component_not_in_ec_output(self):
        csv_viols = {"comp1": {"rule.a"}}
        ec_viols = {}
        ec_succ = {}
        result = conforma_ec_validate.validate_ec_against_csv(csv_viols, ec_viols, ec_succ)
        assert result["validated"] is False
        assert result["divergence_count"] == 1


class TestCompareCoverage:
    def test_all_uncovered_two_way(self):
        csv_viols = {"comp1": {"rule.a", "rule.b"}}
        ec_viols = {"comp1": {"rule.a", "rule.b"}}
        result = conforma_ec_validate.compare_coverage(csv_viols, ec_viols)

        assert result["covered_count"] == 0
        assert result["uncovered_count"] == 2
        assert result["coverage_source"] == "ec_validate_image"

    def test_all_covered_two_way(self):
        csv_viols = {"comp1": {"rule.a", "rule.b"}}
        ec_viols = {"comp1": set()}
        result = conforma_ec_validate.compare_coverage(csv_viols, ec_viols)

        assert result["covered_count"] == 2
        assert result["uncovered_count"] == 0

    def test_partial_coverage_two_way(self):
        csv_viols = {"comp1": {"rule.a", "rule.b", "rule.c"}}
        ec_viols = {"comp1": {"rule.b"}}
        result = conforma_ec_validate.compare_coverage(csv_viols, ec_viols)

        assert result["covered_count"] == 2
        assert result["uncovered_count"] == 1
        uncovered_codes = {v["violation_code"] for v in result["uncovered"]}
        assert uncovered_codes == {"rule.b"}

    def test_component_not_in_ec_output_two_way(self):
        csv_viols = {"comp1": {"rule.a"}}
        ec_viols = {}
        result = conforma_ec_validate.compare_coverage(csv_viols, ec_viols)

        assert result["covered_count"] == 1
        assert result["uncovered_count"] == 0

    def test_three_way_all_covered(self):
        csv_viols = {"comp1": {"rule.a", "rule.b"}}
        ec_viols = {"comp1": set()}
        ec_succ = {"comp1": {"rule.a", "rule.b"}}
        result = conforma_ec_validate.compare_coverage(csv_viols, ec_viols, ec_succ)

        assert result["covered_count"] == 2
        assert result["uncovered_count"] == 0
        assert "divergent_count" not in result

    def test_three_way_all_uncovered(self):
        csv_viols = {"comp1": {"rule.a", "rule.b"}}
        ec_viols = {"comp1": {"rule.a", "rule.b"}}
        ec_succ = {"comp1": set()}
        result = conforma_ec_validate.compare_coverage(csv_viols, ec_viols, ec_succ)

        assert result["covered_count"] == 0
        assert result["uncovered_count"] == 2

    def test_three_way_divergent(self):
        csv_viols = {"comp1": {"rule.a", "rule.b"}}
        ec_viols = {"comp1": set()}
        ec_succ = {"comp1": {"rule.a"}}
        result = conforma_ec_validate.compare_coverage(csv_viols, ec_viols, ec_succ)

        assert result["covered_count"] == 1
        assert result["uncovered_count"] == 1
        assert result["divergent_count"] == 1
        assert result["divergent"][0]["violation_code"] == "rule.b"
        assert result["divergent"][0]["divergent"] is True

    def test_three_way_mixed(self):
        csv_viols = {"comp1": {"rule.a", "rule.b", "rule.c"}}
        ec_viols = {"comp1": {"rule.a"}}
        ec_succ = {"comp1": {"rule.b"}}
        result = conforma_ec_validate.compare_coverage(csv_viols, ec_viols, ec_succ)

        assert result["uncovered_count"] == 2
        assert result["covered_count"] == 1
        assert result["divergent_count"] == 1
        covered_codes = {v["violation_code"] for v in result["covered"]}
        assert covered_codes == {"rule.b"}

    def test_multi_component(self):
        csv_viols = {
            "comp1": {"rule.a"},
            "comp2": {"rule.b", "rule.c"},
        }
        ec_viols = {
            "comp1": {"rule.a"},
            "comp2": {"rule.c"},
        }
        result = conforma_ec_validate.compare_coverage(csv_viols, ec_viols)

        assert result["total_csv_violations"] == 3
        assert result["covered_count"] == 1
        assert result["uncovered_count"] == 2

    def test_output_structure(self):
        csv_viols = {"comp1": {"rule.a"}}
        ec_viols = {"comp1": {"rule.a"}}
        result = conforma_ec_validate.compare_coverage(csv_viols, ec_viols)

        assert "coverage_source" in result
        assert "total_csv_violations" in result
        assert "covered_count" in result
        assert "uncovered_count" in result
        assert "covered" in result
        assert "uncovered" in result

        for entry in result["uncovered"]:
            assert "component" in entry
            assert "violation_code" in entry


class TestEnsureEcBinary:
    @patch("conforma_ec_validate._find_ec_candidates")
    @patch("conforma_ec_validate._verify_ec_binary")
    def test_returns_first_working_candidate(self, mock_verify, mock_find):
        mock_find.return_value = [Path("/usr/bin/ec"), Path("~/.conforma/bin/ec")]
        mock_verify.side_effect = [False, True]

        result = conforma_ec_validate.ensure_ec_binary()
        assert result == Path("~/.conforma/bin/ec")

    @patch("conforma_ec_validate._find_ec_candidates")
    @patch("conforma_ec_validate._verify_ec_binary")
    @patch("conforma_ec_validate._download_ec_binary")
    def test_downloads_when_no_candidates(self, mock_dl, mock_verify, mock_find):
        mock_find.return_value = []
        mock_dl.return_value = Path("~/.conforma/bin/ec")

        result = conforma_ec_validate.ensure_ec_binary()
        mock_dl.assert_called_once()
        assert result == Path("~/.conforma/bin/ec")

    @patch("conforma_ec_validate._find_ec_candidates")
    @patch("conforma_ec_validate._verify_ec_binary")
    @patch("conforma_ec_validate._download_ec_binary")
    def test_downloads_when_no_working_candidates(self, mock_dl, mock_verify, mock_find):
        mock_find.return_value = [Path("/usr/bin/ec")]
        mock_verify.return_value = False
        mock_dl.return_value = Path("~/.conforma/bin/ec")

        result = conforma_ec_validate.ensure_ec_binary()
        mock_dl.assert_called_once()


class TestDownloadEcBinary:
    @patch("platform.system", return_value="Linux")
    @patch("platform.machine", return_value="x86_64")
    @patch("urllib.request.urlretrieve")
    @patch("conforma_ec_validate._verify_ec_binary", return_value=True)
    def test_downloads_correct_binary(self, mock_verify, mock_retrieve, mock_machine, mock_system, tmp_path):
        ec_path = tmp_path / "bin" / "ec"

        def fake_download(url, dest):
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(b"fake-ec-binary")

        mock_retrieve.side_effect = fake_download

        with patch.object(conforma_ec_validate, "EC_BINARY_DIR", tmp_path / "bin"):
            with patch.object(conforma_ec_validate, "EC_BINARY_PATH", ec_path):
                result = conforma_ec_validate._download_ec_binary()
                call_url = mock_retrieve.call_args[0][0]
                assert "ec_linux_amd64" in call_url

    @patch("platform.system", return_value="Windows")
    @patch("platform.machine", return_value="AMD64")
    def test_unsupported_platform_raises(self, mock_machine, mock_system):
        with pytest.raises(conforma_ec_validate.EcValidateError, match="No ec binary"):
            conforma_ec_validate._download_ec_binary()


class TestRunEcValidate:
    @patch("subprocess.run")
    def test_hard_fails_on_missing_output(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=1, stderr="failed", stdout=""
        )
        with pytest.raises(conforma_ec_validate.EcValidateError, match="did not produce"):
            conforma_ec_validate.run_ec_validate(
                ec_binary=Path("/usr/bin/ec"),
                spec_json=str(tmp_path / "spec.json"),
                policy_file=str(tmp_path / "policy.yaml"),
                output_dir=str(tmp_path / "output"),
            )

    @patch("subprocess.run")
    def test_returns_parsed_json(self, mock_run, tmp_path):
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        violations_json = out_dir / "ec-violations.json"
        violations_json.write_text(json.dumps({
            "components": [
                {"name": "comp1", "violations": [{"metadata": {"code": "rule.a"}}]},
            ]
        }))

        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        result = conforma_ec_validate.run_ec_validate(
            ec_binary=Path("/usr/bin/ec"),
            spec_json=str(tmp_path / "spec.json"),
            policy_file=str(tmp_path / "policy.yaml"),
            output_dir=str(out_dir),
        )

        assert "components" in result
        assert len(result["components"]) == 1

    @patch("subprocess.run")
    def test_passes_correct_flags(self, mock_run, tmp_path):
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        (out_dir / "ec-violations.json").write_text('{"components": []}')
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        conforma_ec_validate.run_ec_validate(
            ec_binary=Path("/usr/bin/ec"),
            spec_json=str(tmp_path / "spec.json"),
            policy_file=str(tmp_path / "policy.yaml"),
            output_dir=str(out_dir),
        )

        cmd = mock_run.call_args[0][0]
        assert "--ignore-rekor" in cmd
        assert "--skip-image-sig-check" in cmd
        assert "--skip-att-sig-check" in cmd
        assert "--show-successes" in cmd
        assert "--images" in cmd
        assert "--policy" in cmd
