"""Tests for RHEL naming and Dockerfile base-image resolution."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def run(script, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], capture_output=True, text=True)


@pytest.mark.parametrize("major", ["9", "10", "11", "123"])
def test_suffix_resolver_accepts_any_numeric_rhel_major(major):
    result = run("resolve_rhel_version.py", "--product-context", "RHOAI", "--base-rhel-version", f"rhel{major}")
    assert result.returncode == 0, result.stderr
    assert f"BASE_RHEL_VERSION=rhel{major}" in result.stdout
    assert f"IMAGE_REPO_SUFFIX=-rhel{major}" in result.stdout


@pytest.mark.parametrize("content,expected", [
    ("FROM registry.redhat.io/ubi9/ubi-minimal@sha256:abc AS build\nFROM build AS final\n", "rhel9"),
    ("FROM --platform=linux/amd64 registry.redhat.io/ubi10/ubi-minimal:10.0@sha256:abc\n", "rhel10"),
    ("FROM registry.redhat.io/ubi-minimal:9.4@sha256:abc\n", "rhel9"),
    ("FROM registry.redhat.io/rhel10/python-312@sha256:abc AS base\nFROM base\n", "rhel10"),
    ("FROM registry.redhat.io/rhel-10/python-312@sha256:abc\n", "rhel10"),
    ("FROM \\\n --platform=linux/amd64 registry.redhat.io/ubi9/ubi-minimal@sha256:abc AS runtime\n", "rhel9"),
])
def test_resolves_effective_final_stage(tmp_path, content, expected):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(content)
    result = run("resolve_base_rhel_version.py", "--dockerfile-path", str(dockerfile))
    assert result.returncode == 0, result.stderr
    assert f"BASE_RHEL_VERSION={expected}" in result.stdout


@pytest.mark.parametrize("content", [
    "FROM $BASE_IMAGE\n",
    "FROM registry.example.com/custom-base:latest\n",
    "RUN echo no base\n",
])
def test_unknown_or_unresolvable_final_base_fails(tmp_path, content):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(content)
    result = run("resolve_base_rhel_version.py", "--dockerfile-path", str(dockerfile))
    assert result.returncode != 0
    assert "ERROR:" in result.stderr


@pytest.mark.parametrize("version", ["rhel9", "rhel10", "rhel123"])
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


@pytest.mark.parametrize("version", ["rhel9", "rhel10", "rhel123"])
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
        "--base-rhel-version", "rhel10",
        "--release-category", "Generally Available",
        "--long-description", "Example component",
        "--short-description", "Example",
        "--slack-team-handle", "ai-core-platform",
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(output.read_text())["inputs"]["base_rhel_version"] == "rhel10"
