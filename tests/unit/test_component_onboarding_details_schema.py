"""Tests for schemas/component_onboarding_details.schema.json."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_PATH = REPO_ROOT / "schemas" / "component_onboarding_details.schema.json"


def _schema() -> dict:
    return json.loads(Path(SCHEMA_PATH).read_text(encoding="utf-8"))


def _odh_payload(component_name: str) -> dict:
    return {
        "inputs": {
            "product_context": "ODH",
            "component_name": component_name,
            "repo_url": "https://github.com/opendatahub-io/example",
            "repo_branch": "main",
            "context_path": "./",
            "dockerfile_path": "Dockerfile",
            "is_operator": False,
            "build_type": "CI",
            "slack_team_handle": "openshift-ai-devtestops-ic",
        }
    }


def _errors_for(component_name: str) -> list[str]:
    validator = Draft202012Validator(_schema())
    return [
        e.message
        for e in validator.iter_errors(_odh_payload(component_name))
        if list(e.absolute_path)[-1:] == ["component_name"] or "component_name" in e.message
    ]


def _run_validate_cli(tmp_path: Path, component_name: str) -> subprocess.CompletedProcess:
    yaml_file = tmp_path / "component_onboarding_details.yaml"
    yaml_file.write_text(yaml.safe_dump(_odh_payload(component_name)), encoding="utf-8")
    return subprocess.run(
        [
            "uv",
            "run",
            "--script",
            str(REPO_ROOT / "scripts" / "validate_yaml_schema.py"),
            str(yaml_file),
            str(SCHEMA_PATH),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


class TestSlackTeamHandleOptional:
    """slack_team_handle/slack_team_channel must NOT be required — many components
    were already onboarded/in-flight before RHOAIENG-85559 added these fields, and
    their pipeline_state.json 'validate' step is already marked done and never
    re-validated, but any *not-yet-validated* older YAML must still pass here."""

    def test_accepts_payload_without_slack_team_handle(self):
        payload = _odh_payload("odh-dashboard")
        del payload["inputs"]["slack_team_handle"]
        validator = Draft202012Validator(_schema())
        validator.validate(payload)  # must not raise

    def test_accepts_payload_with_slack_team_handle_and_channel(self):
        payload = _odh_payload("odh-dashboard")
        payload["inputs"]["slack_team_channel"] = "forum-openshift-ai-operator"
        validator = Draft202012Validator(_schema())
        validator.validate(payload)  # must not raise

    def test_rejects_invalid_slack_team_handle_format_when_present(self):
        payload = _odh_payload("odh-dashboard")
        payload["inputs"]["slack_team_handle"] = "Not A Handle"
        validator = Draft202012Validator(_schema())
        with pytest.raises(Exception):
            validator.validate(payload)


class TestComponentNameAccepted:
    @pytest.mark.parametrize(
        "component_name",
        [
            "odh-dashboard",
            "odh-my-component",
            "odh-vllm",
            "odh-vllm-cpu",
            "odh-ml-pipelines",
            "odh-component-1",
        ],
    )
    def test_accepts_base_names_without_version_suffix(self, component_name: str):
        validator = Draft202012Validator(_schema())
        validator.validate(_odh_payload(component_name))


class TestComponentNameRejectsVersionSuffix:
    @pytest.mark.parametrize(
        "component_name",
        [
            "odh-foo-v2",
            "odh-bar-3-4",
            "odh-dashboard-v3-4",
            "odh-mlflow-v3-5-ea-1",
            "odh-operator-fbc-v2-25",
        ],
    )
    def test_rejects_trailing_version_like_suffix(self, component_name: str):
        errors = _errors_for(component_name)
        assert errors, f"expected {component_name!r} to fail schema validation"


class TestComponentNameKeepsMainConstraints:
    def test_still_rejects_rhel9_suffix(self):
        errors = _errors_for("odh-dashboard-rhel9")
        assert errors, "expected odh-dashboard-rhel9 to fail schema validation"

    def test_still_enforces_max_length(self):
        too_long = "odh-" + ("a" * 48)
        assert len(too_long) == 52
        errors = _errors_for(too_long)
        assert errors, "expected names longer than 51 characters to fail schema validation"


class TestValidateYamlSchemaCli:
    def test_cli_accepts_base_name(self, tmp_path):
        result = _run_validate_cli(tmp_path, "odh-dashboard")
        assert result.returncode == 0, result.stderr
        assert "Validation passed." in result.stdout

    def test_cli_rejects_version_suffix(self, tmp_path):
        result = _run_validate_cli(tmp_path, "odh-foo-v2")
        assert result.returncode == 1
        assert "component_name" in result.stderr
        assert "version-like suffix" in result.stderr
