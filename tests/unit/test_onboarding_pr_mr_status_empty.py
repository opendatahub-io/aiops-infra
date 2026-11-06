"""An empty onboarding PR status worklist is a successful no-op."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_onboarding_checker_succeeds_when_no_prs_are_raised(tmp_path: Path):
    state = tmp_path / "pipeline_state.json"
    state.write_text(json.dumps({"steps": {}}))
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "check_pr_mr_status.sh"),
         "--state", str(state), "--scripts-dir", str(REPO_ROOT / "scripts")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
