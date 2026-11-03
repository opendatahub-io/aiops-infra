"""Tests for RHEL naming and Dockerfile base-image resolution."""

import subprocess
import sys
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from resolve_rhel_version import resolve_base_rhel_version  # noqa: E402


def run(script, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], capture_output=True, text=True)


@pytest.mark.parametrize("major", ["9"])
def test_suffix_resolver_accepts_schema_enum_values(major):
    result = run("resolve_rhel_version.py", "--product-context", "RHOAI", "--base-rhel-version", f"rhel{major}")
    assert result.returncode == 0, result.stderr
    assert f"BASE_RHEL_VERSION=rhel{major}" in result.stdout
    assert f"IMAGE_REPO_SUFFIX=-rhel{major}" in result.stdout


@pytest.mark.parametrize("major", ["8", "10", "11", "123"])
def test_suffix_resolver_rejects_values_outside_schema_enum(major):
    result = run("resolve_rhel_version.py", "--product-context", "RHOAI", "--base-rhel-version", f"rhel{major}")
    assert result.returncode != 0
    assert "allowed values: rhel9" in result.stderr


def test_resolver_uses_temporary_rhel9_placeholder():
    assert resolve_base_rhel_version() == "rhel9"
    result = run("resolve_rhel_version.py", "--product-context", "RHOAI")
    assert result.returncode == 0, result.stderr
    assert "BASE_RHEL_VERSION=rhel9" in result.stdout
    assert "IMAGE_REPO_SUFFIX=-rhel9" in result.stdout


def test_allowed_versions_come_from_schema_enum(tmp_path):
    schema_path = ROOT / "schemas" / "component_onboarding_details.schema.json"
    schema = json.loads(schema_path.read_text())
    version_schema = schema["properties"]["inputs"]["properties"]["base_rhel_version"]
    version_schema["enum"] = ["rhel12"]
    modified = tmp_path / "schema.json"
    modified.write_text(json.dumps(schema))

    assert resolve_base_rhel_version("rhel12", modified) == "rhel12"
    with pytest.raises(ValueError, match="allowed values: rhel12"):
        resolve_base_rhel_version("rhel9", modified)


@pytest.mark.parametrize("version", ["rhel9"])
def test_component_details_parser_uses_jira_yaml_version(tmp_path, version):
    workdir = tmp_path / "RHOAIENG-123"
    workdir.mkdir()
    (workdir / "component_onboarding_details.yaml").write_text(yaml.safe_dump({"inputs": {
        "product_context": "RHOAI",
        "component_name": "odh-example",
        "repo_url": "https://github.com/example/component",
        "repo_branch": "rhoai-3.7",
        "context_path": "./",
        "dockerfile_path": "Dockerfile.konflux",
        "is_operator": False,
        "base_rhel_version": version,
    }}))
    result = subprocess.run([
        "bash", str(SCRIPTS / "parse_component_details.sh"),
        "--workdir", str(workdir), "--jira-id", "RHOAIENG-123",
        "--scripts-dir", str(SCRIPTS),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert f"BASE_RHEL_VERSION={version}" in result.stdout
    assert f"IMAGE_REPO_SUFFIX=-{version}" in result.stdout
    assert f"QUAY_REPO_URI=quay.io/rhoai/odh-example-{version}" in result.stdout


def test_component_details_parser_defaults_legacy_ticket_to_rhel9(tmp_path):
    workdir = tmp_path / "RHOAIENG-123"
    workdir.mkdir()
    (workdir / "component_onboarding_details.yaml").write_text(yaml.safe_dump({"inputs": {
        "product_context": "RHOAI",
        "component_name": "odh-example",
        "repo_url": "https://github.com/example/component",
        "repo_branch": "rhoai-3.7",
        "context_path": "./",
        "dockerfile_path": "Dockerfile.konflux",
        "is_operator": False,
    }}))
    result = subprocess.run([
        "bash", str(SCRIPTS / "parse_component_details.sh"),
        "--workdir", str(workdir), "--jira-id", "RHOAIENG-123",
        "--scripts-dir", str(SCRIPTS),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "BASE_RHEL_VERSION=rhel9" in result.stdout
    assert "QUAY_REPO_URI=quay.io/rhoai/odh-example-rhel9" in result.stdout


@pytest.mark.parametrize("version", ["rhel9"])
def test_repository_name_parser_uses_explicit_version(version):
    result = subprocess.run([
        "bash", str(SCRIPTS / "parse_rhoai_version.sh"),
        "--version", "3.7-ea-2", "--component", "odh-example",
        "--base-rhel-version", version,
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert f"REPOSITORY_NAME=rhoai/odh-example-{version}" in result.stdout
    assert "VERSION_VAR=v3-7-ea-2" in result.stdout


def test_generator_records_detected_rhel_version(tmp_path):
    output = tmp_path / "details.yaml"
    result = subprocess.run([
        sys.executable, str(SCRIPTS / "generate_onboarding_yaml.py"),
        "--output", str(output),
        "--product-context", "RHOAI",
        "--component-name", "odh-example",
        "--repo-url", "https://github.com/example/component",
        "--repo-branch", "rhoai-3.7",
        "--context-path", "./",
        "--dockerfile-path", "Dockerfile.konflux",
        "--target-rhoai-version", "3.7",
        "--base-rhel-version", "rhel9",
        "--release-category", "Generally Available",
        "--long-description", "Example component",
        "--short-description", "Example",
        "--slack-team-handle", "ai-core-platform",
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(output.read_text())["inputs"]["base_rhel_version"] == "rhel9"
