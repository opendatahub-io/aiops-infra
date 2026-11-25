from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
CLUSTERS = ("stone-prod-p01", "stone-prod-p02")


def _write(path: Path, text: str, executable: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if executable:
        path.chmod(0o755)


def _git(path: Path, *args: str):
    return subprocess.run(
        ["git", "-C", str(path), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def onboarding(tmp_path: Path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("run_step_krd.sh", "edit_yaml.py"):
        shutil.copy(ROOT / "scripts" / name, scripts / name)
    _write(scripts / "parse_component_details.sh", """#!/bin/bash
echo 'COMPONENT_NAME=odh-sample PRODUCT_CONTEXT='"${TEST_PRODUCT:-RHOAI}"' QUAY_ORG=rhoai KONFLUX_NAMESPACE=rhoai-tenant REPO_URL=https://github.com/red-hat-data-services/sample REPO_BRANCH=rhoai-3.7-ea.1'
""")
    _write(scripts / "check_konflux_component.sh", "#!/bin/bash\ntouch \"$WORKDIR/checked-cluster\"\nexit 0\n")
    _write(scripts / "setup_gitlab_playpen.sh", """#!/bin/bash
printf '%s\n' "$*" > "$WORKDIR/setup-args"
printf '%s\n' "$WORKDIR/krd" test-branch
""")
    _write(scripts / "update_pipeline_state.sh", "#!/bin/bash\nprintf '%s\n' \"$*\" >> \"$WORKDIR/state-updates\"\n")
    tools = tmp_path / "bin"
    real_uv = shutil.which("uv")
    _write(tools / "uv", f"""#!/bin/bash
script="$3"
shift 3
case "$script" in
  */edit_yaml.py) exec {real_uv} run --script "$script" "$@" ;;
  */raise_gitlab_mr.py) echo https://gitlab.example/krd/-/merge_requests/1 ;;
esac
""", True)
    _write(tools / "yamllint", "#!/bin/bash\nexit 0\n", True)
    git = shutil.which("git")
    _write(tools / "git", f"""#!/bin/bash
if [[ "$1" == push ]]; then
  touch "$WORKDIR/pushed"
  exit 0
fi
exec {git} "$@"
""", True)
    _write(tmp_path / "pipeline_state.json", '{"steps":{"krd":{}}}')
    _write(tmp_path / "component_onboarding_details.yaml", """inputs:
  context_path: .
  dockerfile_path: Dockerfile.konflux
  target_rhoai_version: "3.7-ea-1"
""")
    clone = tmp_path / "krd"
    for cluster in CLUSTERS:
        tenant = clone / "tenants-config/cluster" / cluster / "tenants/rhoai-tenant"
        _write(tenant / "kustomization.yaml", "resources:\n  - v3.7-ea.1/\n")
        _write(tenant / "v3.7-ea.1/ProjectDevelopmentStream-v3.7-ea.1.yaml", """---
apiVersion: projctl.konflux.dev/v1beta1
kind: ProjectDevelopmentStreamTemplate
metadata:
  name: rhoai-template-v3-7-ea-1
spec:
  resources:
    - apiVersion: appstudio.redhat.com/v1alpha1
      kind: Application
      metadata:
        name: rhoai-{{.versionName}}
""")
    _write(clone / "tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant/automation/resources.yaml", """---
apiVersion: appstudio.redhat.com/v1alpha1
kind: Application
metadata:
  name: automation
spec:
  displayName: automation
""")
    for script in ("build-manifests.sh", "verify-manifests.sh"):
        _write(clone / "tenants-config" / script, "#!/bin/bash\nexit 0\n", True)
    _git(clone, "init")
    _git(clone, "config", "user.email", "test@example.com")
    _git(clone, "config", "user.name", "Test")
    _git(clone, "add", ".")
    _git(clone, "commit", "-m", "fixture")
    env = dict(os.environ, HOME=str(tmp_path), WORKDIR=str(tmp_path), PATH=f"{tools}:{os.environ['PATH']}")

    def run(product="RHOAI"):
        return subprocess.run(
            ["bash", str(scripts / "run_step_krd.sh"), "--jira-url", "https://jira.example/RHAI-1"],
            cwd=tmp_path, env=dict(env, TEST_PRODUCT=product), capture_output=True, text=True,
        )

    return tmp_path, clone, run


def test_registers_both_clusters_and_initializes_p01_automation(onboarding):
    workdir, clone, run = onboarding
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (workdir / "checked-cluster").exists()
    assert (workdir / "pushed").exists()
    for cluster in CLUSTERS:
        tenant = clone / "tenants-config/cluster" / cluster / "tenants/rhoai-tenant"
        pds = list(yaml.safe_load_all((tenant / "v3.7-ea.1/ProjectDevelopmentStream-v3.7-ea.1.yaml").read_text()))
        components = [r for r in pds[0]["spec"]["resources"] if r["kind"] == "Component"]
        assert len(components) == 1
        component = components[0]
        assert component["metadata"]["name"] == "odh-sample-{{.versionName}}"
        assert component["spec"]["application"] == "rhoai-{{.versionName}}"
        assert component["metadata"]["annotations"]["build.appstudio.openshift.io/request"] == "configure-pac-no-mr"
        assert "build-pipeline-" + component["metadata"]["name"].replace("{{.versionName}}", "v3-7-ea-1") == "build-pipeline-odh-sample-v3-7-ea-1"
        automation = list(yaml.safe_load_all((tenant / "automation/resources.yaml").read_text()))
        assert [(r["kind"], r["metadata"]["name"]) for r in automation] == [
            ("Application", "automation"), ("Component", "pr-pipelines-odh-sample"),
        ]
        assert yaml.safe_load((tenant / "automation/kustomization.yaml").read_text())["resources"] == ["resources.yaml"]
        assert "automation/" in yaml.safe_load((tenant / "kustomization.yaml").read_text())["resources"]
        assert f"auto-generated/cluster/{cluster}/tenants/rhoai-tenant" in (workdir / "setup-args").read_text()


def test_rerun_is_noop_only_after_both_clusters_are_registered(onboarding):
    workdir, clone, run = onboarding
    assert run().returncode == 0
    before = _git(clone, "rev-parse", "HEAD")
    result = run()
    assert result.returncode == 2, result.stdout + result.stderr
    assert _git(clone, "rev-parse", "HEAD") == before
    assert not _git(clone, "status", "--porcelain")
    assert "--status done" in (workdir / "state-updates").read_text()


def test_existing_p02_registration_does_not_skip_missing_p01_component(onboarding):
    _, clone, run = onboarding
    assert run().returncode == 0
    p02 = clone / "tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant"
    before = {path: path.read_bytes() for path in p02.rglob("*.yaml")}
    p01_pds = clone / "tenants-config/cluster/stone-prod-p01/tenants/rhoai-tenant/v3.7-ea.1/ProjectDevelopmentStream-v3.7-ea.1.yaml"
    document = yaml.safe_load(p01_pds.read_text())
    document["spec"]["resources"] = [
        r for r in document["spec"]["resources"] if r["kind"] != "Component"
    ]
    p01_pds.write_text(yaml.safe_dump(document))
    _git(clone, "add", ".")
    _git(clone, "commit", "-m", "remove P01 component")
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "odh-sample-{{.versionName}}" in p01_pds.read_text()
    assert all(path.read_bytes() == content for path, content in before.items())


@pytest.mark.parametrize("cluster", CLUSTERS)
def test_missing_stream_blocks_before_changes(onboarding, cluster):
    workdir, clone, run = onboarding
    pds = clone / f"tenants-config/cluster/{cluster}/tenants/rhoai-tenant/v3.7-ea.1/ProjectDevelopmentStream-v3.7-ea.1.yaml"
    pds.unlink()
    before = _git(clone, "status", "--porcelain")
    result = run()
    assert result.returncode == 1
    assert cluster in result.stderr
    assert not (workdir / "pushed").exists()
    assert _git(clone, "status", "--porcelain") == before


def test_odh_keeps_existing_single_cluster_shortcut(onboarding):
    workdir, clone, run = onboarding
    result = run("ODH")
    assert result.returncode == 2, result.stdout + result.stderr
    assert (workdir / "checked-cluster").exists()
    assert not (workdir / "setup-args").exists()
    assert not _git(clone, "status", "--porcelain")


def _render_pipelinerun(mode: str, *extra: str) -> dict:
    renderer = ROOT / "scripts/render_rhoai_pipelinerun.sh"
    result = subprocess.run(
        [
            "bash",
            str(renderer),
            "--mode",
            mode,
            "--component-name",
            "odh-sample",
            "--version-var",
            "v3-7-ea-1",
            "--branch-name",
            "rhoai-3.7-ea.1",
            "--repo-url",
            "https://github.com/red-hat-data-services/sample",
            "--context-path",
            ".",
            "--dockerfile-path",
            "Dockerfile.konflux",
            "--rhoai-minor-version",
            "3.7.0-ea.1",
            *extra,
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    return yaml.safe_load(result.stdout)


def test_push_template_routes_to_p02_and_keeps_versioned_service_account():
    doc = _render_pipelinerun(
        "push", "--platforms", "linux/x86_64,linux-m2xlarge/arm64"
    )
    expression = doc["metadata"]["annotations"]["pipelinesascode.tekton.dev/on-cel-expression"]
    assert expression.startswith('konflux_cluster == "stone-prod-p02"\n&& event == "push"\n')
    assert 'target_branch == "rhoai-3.7-ea.1"' in expression
    assert doc["spec"]["taskRunTemplate"]["serviceAccountName"] == "build-pipeline-odh-sample-v3-7-ea-1"
    assert "podTemplate" not in doc["spec"]["taskRunTemplate"]
    params = {item["name"]: item["value"] for item in doc["spec"]["params"]}
    assert params["build-platforms"] == ["linux/x86_64", "linux-m2xlarge/arm64"]
    assert "additional-tags" in params
    assert "on-comment" not in doc["metadata"]["annotations"]
    assert "timeouts" not in doc["spec"]
    assert doc["spec"]["taskRunSpecs"][0]["pipelineTaskName"] == "rpms-signature-scan"


def test_pull_request_and_push_templates_share_common_fields():
    pr = _render_pipelinerun("pull-request")
    push = _render_pipelinerun("push", "--platforms", "linux/x86_64,linux-s390x/s390x")

    pr_params = {item["name"]: item["value"] for item in pr["spec"]["params"]}
    push_params = {item["name"]: item["value"] for item in push["spec"]["params"]}

    common = {
        "git-url",
        "revision",
        "output-image",
        "dockerfile",
        "path-context",
        "hermetic",
        "rhoai-version",
        "build-source-image",
        "build-image-index",
        "build-platforms",
    }
    assert common <= pr_params.keys()
    assert common <= push_params.keys()
    for name in common:
        if name in {"output-image", "build-platforms"}:
            continue
        assert pr_params[name] == push_params[name]

    assert pr["metadata"]["labels"] == push["metadata"]["labels"]
    assert pr["spec"]["taskRunTemplate"] == push["spec"]["taskRunTemplate"]
    assert pr["spec"]["taskRunSpecs"] == push["spec"]["taskRunSpecs"]
    assert pr["spec"]["workspaces"] == push["spec"]["workspaces"]

    # Intentional event-specific differences.
    assert pr_params["build-platforms"] == ["linux/x86_64", "linux-m2xlarge/arm64"]
    assert push_params["build-platforms"] == ["linux/x86_64", "linux-s390x/s390x"]
    assert "additional-tags" not in pr_params
    assert "additional-tags" in push_params
    assert pr_params["additional-labels"] == [
        "version=on-pr-{{revision}}",
        "io.openshift.tags=odh-sample",
    ]
    assert "additional-labels" not in push_params
    assert pr_params["image-expires-after"] == "30d"
    assert "image-expires-after" not in push_params
    assert pr["metadata"]["annotations"]["build.appstudio.redhat.com/pull_request_number"] == (
        "{{pull_request_number}}"
    )
    assert "build.appstudio.redhat.com/pull_request_number" not in push["metadata"]["annotations"]
