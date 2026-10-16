"""Rendered RHOAI pull-request PipelineRuns follow the GAP Stage 2 shape."""

from __future__ import annotations

import codecs
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "run_step_create_pull_pipelines.sh"

# Parsed from konflux-central main after RHOAIENG-97051 PR #3630 and the
# pipelineRef escape fix in PR #3682.
EVAL_HUB_CEL = (
    'event == "pull_request"\n'
    "&& (files.all.exists(p, ! p.matches('^\\\\.tekton/')) "
    '|| ".tekton/odh-eval-hub-pull-request.yaml".pathChanged())'
)
PIPELINE_REF_VALUE = (
    '{{ cel: pac.target_branch.matches("^rhoai-\\\\d+\\\\.\\\\d+(-ea\\\\.\\\\d+)?$") '
    '? pac.target_branch : "main" }}'
)


def _details(
    *,
    component_name: str = "odh-eval-hub",
    version: str = "3.6",
    context_path: str = ".",
    dockerfile_path: str = "Dockerfile.konflux",
    architectures: list[str] | None = None,
    repo_url: str = "https://github.com/red-hat-data-services/eval-hub",
) -> str:
    arches = architectures if architectures is not None else ["x86_64", "arm64"]
    arch_lines = "\n".join(f"    - {arch}" for arch in arches)
    return f"""inputs:
  product_context: RHOAI
  component_name: {component_name}
  repo_url: {repo_url}
  repo_branch: rhoai-3.6
  context_path: {context_path}
  dockerfile_path: {dockerfile_path}
  architectures:
{arch_lines}
  target_rhoai_version: "{version}"
  is_operator: false
  long_description: Example component
  short_description: Example
  release_category: Generally Available
"""


def _render(
    tmp_path: Path,
    details: str,
    prefetch: str | None = None,
) -> dict:
    details_path = tmp_path / "component_onboarding_details.yaml"
    details_path.write_text(details, encoding="utf-8")
    command = [
        "bash",
        str(SCRIPT),
        "--render-only",
        "--details",
        str(details_path),
    ]
    if prefetch is not None:
        command.extend(["--prefetch-input", prefetch])
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    document = yaml.safe_load(result.stdout)
    assert isinstance(document, dict)
    return document


def _param(document: dict, name: str):
    matches = [item for item in document["spec"]["params"] if item["name"] == name]
    assert len(matches) == 1, name
    return matches[0]["value"]


def _pipeline_revision_for(document: dict, target_branch: str) -> str:
    revision = next(
        item["value"]
        for item in document["spec"]["pipelineRef"]["params"]
        if item["name"] == "revision"
    )
    match = re.search(r'matches\("(.+)"\)', revision)
    assert match, revision
    pattern = codecs.decode(match.group(1), "unicode_escape")
    if re.fullmatch(pattern, target_branch):
        return target_branch
    return "main"


def _cel_triggers(expression: str, changed_files: list[str]) -> bool:
    assert 'event == "pull_request"' in expression
    assert 'event == "push"' not in expression
    assert "target_branch ==" not in expression
    own_file = re.search(r'"(\.tekton/[^"]+)"\.pathChanged\(\)', expression)
    assert own_file, expression
    pattern_source = re.search(r"matches\('([^']+)'\)", expression)
    assert pattern_source, expression
    pattern = codecs.decode(pattern_source.group(1), "unicode_escape")
    outside_tekton = any(re.match(pattern, path) is None for path in changed_files)
    return outside_tekton or own_file.group(1) in changed_files


class TestStage2PullPipeline:
    def test_eval_hub_matches_gap_stage2_configuration(self, tmp_path: Path):
        document = _render(
            tmp_path,
            _details(),
            prefetch='[{"type": "gomod", "path": "."}]',
        )
        annotations = document["metadata"]["annotations"]
        labels = document["metadata"]["labels"]

        assert labels["appstudio.openshift.io/application"] == "rhoai-v3-6"
        assert labels["appstudio.openshift.io/component"] == "odh-eval-hub-v3-6"
        assert (
            document["spec"]["taskRunTemplate"]["serviceAccountName"]
            == "build-pipeline-odh-eval-hub-v3-6"
        )
        assert _param(document, "output-image") == (
            "quay.io/rhoai/odh-eval-hub-rhel9:on-pr-{{pull_request_number}}"
        )
        assert _param(document, "image-expires-after") == "30d"
        assert _param(document, "rhoai-version") == "3.6.0"
        assert _param(document, "build-platforms") == [
            "linux/x86_64",
            "linux-m2xlarge/arm64",
        ]
        assert _param(document, "prefetch-input").strip() == (
            '[{"type": "gomod", "path": "."}]'
        )
        assert _param(document, "hermetic") is True
        assert _param(document, "build-source-image") is True
        assert _param(document, "build-image-index") is True
        assert annotations["pipelinesascode.tekton.dev/on-comment"] == "^/build-konflux"
        assert annotations["pipelinesascode.tekton.dev/on-cel-expression"] == EVAL_HUB_CEL
        assert "pipelinesascode.tekton.dev/on-label" not in annotations
        assert "pipelinesascode.tekton.dev/on-target-branch" not in annotations
        assert "pipelinesascode.tekton.dev/on-event" not in annotations
        assert all(item["name"] != "additional-tags" for item in document["spec"]["params"])
        assert "pull-request-pipelines" not in _param(document, "output-image")
        revision = next(
            item["value"]
            for item in document["spec"]["pipelineRef"]["params"]
            if item["name"] == "revision"
        )
        assert revision == PIPELINE_REF_VALUE
        assert document["spec"]["pipelineRef"]["params"][-1] == {
            "name": "pathInRepo",
            "value": "pipelines/multi-arch-container-build.yaml",
        }

    def test_pipeline_ref_selects_release_branches_and_falls_back_to_main(
        self, tmp_path: Path
    ):
        document = _render(tmp_path, _details())
        assert _pipeline_revision_for(document, "main") == "main"
        assert _pipeline_revision_for(document, "rhoai-3.6") == "rhoai-3.6"
        assert _pipeline_revision_for(document, "rhoai-3.6-ea.1") == "rhoai-3.6-ea.1"
        assert _pipeline_revision_for(document, "rhoai-3.6-ea-1") == "main"
        assert _pipeline_revision_for(document, "feature-branch") == "main"

    def test_version_identifiers_follow_the_onboarding_input(self, tmp_path: Path):
        document = _render(
            tmp_path,
            _details(component_name="odh-sample", version="3.7"),
        )
        rendered = yaml.safe_dump(document)
        assert document["metadata"]["labels"]["appstudio.openshift.io/application"] == (
            "rhoai-v3-7"
        )
        assert document["metadata"]["labels"]["appstudio.openshift.io/component"] == (
            "odh-sample-v3-7"
        )
        assert (
            document["spec"]["taskRunTemplate"]["serviceAccountName"]
            == "build-pipeline-odh-sample-v3-7"
        )
        assert _param(document, "rhoai-version") == "3.7.0"
        assert "v3-6" not in rendered
        assert "3.6.0" not in rendered

    def test_ea_version_uses_parser_identifiers(self, tmp_path: Path):
        document = _render(
            tmp_path,
            _details(component_name="odh-sample", version="3.6-ea-1"),
        )
        assert document["metadata"]["labels"]["appstudio.openshift.io/application"] == (
            "rhoai-v3-6-ea-1"
        )
        assert document["metadata"]["labels"]["appstudio.openshift.io/component"] == (
            "odh-sample-v3-6-ea-1"
        )
        assert (
            document["spec"]["taskRunTemplate"]["serviceAccountName"]
            == "build-pipeline-odh-sample-v3-6-ea-1"
        )
        assert _param(document, "rhoai-version") == "3.6.0-ea.1"
        assert _param(document, "output-image") == (
            "quay.io/rhoai/odh-sample-rhel9:on-pr-{{pull_request_number}}"
        )

    def test_multi_arch_and_prefetch_are_retained(self, tmp_path: Path):
        document = _render(
            tmp_path,
            _details(
                architectures=["x86_64", "arm64", "ppc64le", "s390x"],
                context_path="./",
                dockerfile_path="Dockerfile.konflux",
            ),
            prefetch='[{"type": "gomod", "path": "."}]',
        )
        assert _param(document, "build-platforms") == [
            "linux/x86_64",
            "linux-m2xlarge/arm64",
            "linux/ppc64le",
            "linux/s390x",
        ]
        assert _param(document, "prefetch-input").strip() == (
            '[{"type": "gomod", "path": "."}]'
        )
        assert _param(document, "path-context") == "."
        assert _param(document, "dockerfile") == "Dockerfile.konflux"

    def test_empty_prefetch_is_omitted(self, tmp_path: Path):
        document = _render(tmp_path, _details(), prefetch="[]")
        assert all(item["name"] != "prefetch-input" for item in document["spec"]["params"])

    @pytest.mark.parametrize(
        ("changed_files", "expected"),
        [
            (["Dockerfile.konflux"], True),
            (["src/main.go", ".tekton/other.yaml"], True),
            ([".tekton/odh-eval-hub-pull-request.yaml"], True),
            ([".tekton/odh-eval-hub-v3-6-push.yaml"], False),
            ([".tekton/unrelated.yaml"], False),
        ],
    )
    def test_on_cel_file_filter(self, tmp_path: Path, changed_files: list[str], expected: bool):
        document = _render(tmp_path, _details())
        expression = document["metadata"]["annotations"][
            "pipelinesascode.tekton.dev/on-cel-expression"
        ]
        assert _cel_triggers(expression, changed_files) is expected

    def test_generation_pr_targets_konflux_central_main(self):
        script = SCRIPT.read_text(encoding="utf-8")
        assert '--src-branch  "main"' in script
        assert '--dest-branch "main"' in script
        assert "ref=main" in script
