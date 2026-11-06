"""Fresh and resumed pipeline state includes the final RHOAI mapping action."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INIT = REPO_ROOT / "scripts" / "init_pipeline.sh"
EXPECTED_DEPENDENCIES = {
    "quay", "slack_handle", "delivery_repo", "krd", "krd_rpa", "okc",
    "pull_pipelines", "bundle", "operator", "product_listing", "auto_merge",
    "renovate", "renovate_sync",
}


def _init(workdir: Path, product: str, operator: str = "false") -> dict:
    result = subprocess.run(
        [
            "bash", str(INIT), "--jira-url", "https://redhat.atlassian.net/browse/RHOAIENG-123",
            "--workdir-override", str(workdir), "--product-context", product,
            "--component-name", "odh-example", "--is-operator", operator,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads((workdir / "pipeline_state.json").read_text())


def test_fresh_rhoai_state_has_final_mapping_action(tmp_path: Path):
    state = _init(tmp_path, "RHOAI")
    step = state["steps"]["component_repo_map"]
    assert step["status"] == "pending"
    assert set(step["depends_on"]) == EXPECTED_DEPENDENCIES
    assert step["pr_url"] == ""
    assert step["label_raised"] == "component-repo-map-pr-raised"
    assert "label_done" not in step  # verification on main is required


def test_migrates_old_rhoai_state_and_is_idempotent(tmp_path: Path):
    state = _init(tmp_path, "RHOAI", operator="true")
    del state["steps"]["component_repo_map"]
    state_path = tmp_path / "pipeline_state.json"
    state_path.write_text(json.dumps(state))

    migrated = _init(tmp_path, "RHOAI", operator="true")
    step = migrated["steps"]["component_repo_map"]
    assert step["status"] == "pending"
    assert set(step["depends_on"]) == EXPECTED_DEPENDENCIES
    assert migrated["steps"]["operator"]["status"] == "pending"

    again = _init(tmp_path, "RHOAI", operator="true")
    assert again["steps"]["component_repo_map"] == step


def test_odh_state_skips_rhoai_mapping_action(tmp_path: Path):
    state = _init(tmp_path, "ODH")
    assert state["steps"]["component_repo_map"]["status"] == "skipped"
