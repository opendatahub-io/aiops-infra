"""Offboarding map overrides and additional component removals are validated."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA = REPO_ROOT / "schemas" / "component_offboarding_details.schema.json"
GENERATOR = REPO_ROOT / "scripts" / "generate_offboarding_yaml.py"


def test_schema_accepts_preserve_override_and_multiple_map_components():
    payload = {
        "inputs": {
            "product_context": "RHOAI",
            "component_name": "odh-eval-hub",
            "repo_url": "https://github.com/red-hat-data-services/eval-hub",
            "target_rhoai_version": "3.6",
            "is_operator": False,
            "preserve_component_repo_map": False,
            "component_repo_map_components": [
                "odh-eval-hub-inspectai",
                "odh-eval-hub-lighteval",
            ],
        }
    }
    Draft202012Validator(json.loads(SCHEMA.read_text())).validate(payload)


def test_schema_rejects_non_boolean_preserve_override():
    payload = {
        "inputs": {
            "product_context": "RHOAI",
            "component_name": "odh-eval-hub",
            "repo_url": "https://github.com/red-hat-data-services/eval-hub",
            "target_rhoai_version": "3.6",
            "is_operator": False,
            "preserve_component_repo_map": "yes",
        }
    }
    with pytest.raises(Exception):
        Draft202012Validator(json.loads(SCHEMA.read_text())).validate(payload)


def test_generator_emits_explicit_preserve_and_extra_components(tmp_path: Path):
    output = tmp_path / "component_offboarding_details.yaml"
    result = subprocess.run(
        [
            "python", str(GENERATOR), "--output", str(output),
            "--product-context", "RHOAI", "--component-name", "odh-eval-hub",
            "--repo-url", "https://github.com/red-hat-data-services/eval-hub",
            "--target-rhoai-version", "3.6", "--preserve-component-repo-map",
            "--component-repo-map-component", "odh-eval-hub-inspectai",
            "--component-repo-map-component", "odh-eval-hub-lighteval",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    details = yaml.safe_load(output.read_text())
    Draft202012Validator(json.loads(SCHEMA.read_text())).validate(details)
    assert details["inputs"]["preserve_component_repo_map"] is True
    assert details["inputs"]["component_repo_map_components"] == [
        "odh-eval-hub-inspectai",
        "odh-eval-hub-lighteval",
    ]
