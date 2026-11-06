"""Test mode fails closed unless repo overrides point to dedicated forks."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CHECK = REPO_ROOT / "scripts" / "check_test_repo_overrides.sh"
RESOLVE_OPERATOR = REPO_ROOT / "scripts" / "resolve_operator_url.sh"

GITHUB_REPOS = {
    "ODH_KONFLUX_CENTRAL_REPO_URL": "https://github.com/rhoai-rhtap/odh-konflux-central.git",
    "RHOAI_KONFLUX_CENTRAL_REPO_URL": "https://github.com/rhoai-rhtap/konflux-central.git",
    "ODH_OPERATOR_REPO_URL": "https://github.com/rhoai-rhtap/opendatahub-operator.git",
    "RHOAI_OPERATOR_REPO_URL": "https://github.com/rhoai-rhtap/rhods-operator.git",
    "ODH_BUILD_CONFIG_REPO_URL": "https://github.com/rhoai-rhtap/ODH-Build-Config.git",
    "RHOAI_BUILD_CONFIG_REPO_URL": "https://github.com/rhoai-rhtap/RHOAI-Build-Config.git",
    "RHODS_DEVOPS_INFRA_REPO_URL": "https://github.com/rhoai-rhtap/rhods-devops-infra.git",
}
GITLAB_REPOS = {
    "APP_INTERFACE_REPO_URL": "https://gitlab.cee.redhat.com/jstetina/app-interface.git",
    "KONFLUX_RELEASE_DATA_REPO_URL": "https://gitlab.cee.redhat.com/jstetina/konflux-release-data.git",
    "PYXIS_REPO_CONFIGS_REPO_URL": "https://gitlab.cee.redhat.com/jstetina/pyxis-repo-configs.git",
}


def _env() -> dict[str, str]:
    return {
        **os.environ,
        "AIOPS_TEST_REPO_MODE": "true",
        "AIOPS_TEST_GITHUB_OWNER": "rhoai-rhtap",
        "AIOPS_TEST_GITLAB_NAMESPACE": "jstetina",
        **GITHUB_REPOS,
        **GITLAB_REPOS,
    }


def test_accepts_dedicated_test_org_and_personal_gitlab_forks():
    result = subprocess.run(
        ["bash", str(CHECK), "--component-repo-url", "https://github.com/rhoai-rhtap/odh-ai-first-demo"],
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert result.returncode == 0, result.stderr
    assert "overrides verified" in result.stdout


def test_rejects_a_default_github_repository():
    env = _env()
    env["RHOAI_KONFLUX_CENTRAL_REPO_URL"] = "https://github.com/red-hat-data-services/konflux-central.git"
    result = subprocess.run(["bash", str(CHECK)], capture_output=True, text=True, env=env)
    assert result.returncode == 1
    assert "outside the test forks" in result.stderr


def test_rejects_missing_overrides():
    env = _env()
    del env["KONFLUX_RELEASE_DATA_REPO_URL"]
    result = subprocess.run(["bash", str(CHECK)], capture_output=True, text=True, env=env)
    assert result.returncode == 1
    assert "must be explicitly set" in result.stderr


def test_rejects_component_repo_outside_test_org():
    result = subprocess.run(
        ["bash", str(CHECK), "--component-repo-url", "https://github.com/red-hat-data-services/real-component"],
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert result.returncode == 1
    assert "component repo URL is not in the test GitHub org" in result.stderr


def test_rhoai_operator_override_is_used_instead_of_production_default():
    result = subprocess.run(
        ["bash", str(RESOLVE_OPERATOR), "--product-context", "RHOAI"],
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert result.returncode == 0, result.stderr
    assert "ODH_OPERATOR_URL=https://github.com/rhoai-rhtap/rhods-operator.git" in result.stdout
