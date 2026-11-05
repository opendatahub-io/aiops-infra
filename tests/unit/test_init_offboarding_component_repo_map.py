"""Fresh and resumed offboarding state tracks component map cleanup safely."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INIT = REPO_ROOT / "scripts" / "init_offboarding_pipeline.sh"
MAP_DEPENDENCIES = {
    "remove_krd", "remove_okc", "remove_pull_pipelines", "remove_bundle",
    "remove_operator", "sync_component_tekton",
}


def _init(workdir: Path, product: str, preserve: bool = False) -> dict:
    result = subprocess.run(
        [
            "bash", str(INIT), "--jira-url", "https://redhat.atlassian.net/browse/RHOAIENG-456",
            "--workdir-override", str(workdir), "--product-context", product,
            "--component-name", "odh-example", "--is-operator", "false",
            "--preserve-component-repo-map", str(preserve).lower(),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads((workdir / "pipeline_state.json").read_text())


def test_fresh_rhoai_state_waits_for_other_repo_cleanup_before_map_removal(tmp_path: Path):
    state = _init(tmp_path, "RHOAI")
    step = state["steps"]["remove_component_repo_map"]
    assert step["status"] == "pending"
    assert set(step["depends_on"]) == MAP_DEPENDENCIES
    assert "remove_component_repo_map" in state["steps"]["remove_component_cr"]["depends_on"]


def test_preserve_override_skips_only_component_map_cleanup(tmp_path: Path):
    state = _init(tmp_path, "RHOAI", preserve=True)
    assert state["steps"]["remove_component_repo_map"]["status"] == "skipped"
    assert state["steps"]["remove_pull_pipelines"]["status"] == "pending"


def test_odh_state_skips_map_and_rhoai_pipeline_steps(tmp_path: Path):
    state = _init(tmp_path, "ODH")
    assert state["steps"]["remove_component_repo_map"]["status"] == "skipped"
    assert state["steps"]["remove_pull_pipelines"]["status"] == "skipped"


def test_migrates_old_state_and_is_idempotent(tmp_path: Path):
    state = _init(tmp_path, "RHOAI")
    del state["steps"]["remove_component_repo_map"]
    state["steps"]["remove_component_cr"]["depends_on"].remove("remove_component_repo_map")
    (tmp_path / "pipeline_state.json").write_text(json.dumps(state))

    migrated = _init(tmp_path, "RHOAI")
    step = migrated["steps"]["remove_component_repo_map"]
    assert step["status"] == "pending"
    assert set(step["depends_on"]) == MAP_DEPENDENCIES
    assert "remove_component_repo_map" in migrated["steps"]["remove_component_cr"]["depends_on"]
    assert _init(tmp_path, "RHOAI")["steps"]["remove_component_repo_map"] == step
