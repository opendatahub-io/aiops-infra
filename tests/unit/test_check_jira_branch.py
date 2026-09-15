"""Tests for the pre-commit adapter around link-work-to-jira."""

import os
import stat
import subprocess
from pathlib import Path


HOOK = Path(__file__).parents[2] / "hooks" / "check-jira-branch.sh"


def make_fake_skill(tmp_path: Path, output: str = "", exit_code: int = 0) -> Path:
    skill_dir = tmp_path / "skill"
    script = skill_dir / "scripts" / "check-jira-state.sh"
    script.parent.mkdir(parents=True)
    script.write_text(f"#!/usr/bin/env bash\nprintf '%s\\n' {output!r}\nexit {exit_code}\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return skill_dir


def run_hook(tmp_path: Path, skill_dir: Path) -> subprocess.CompletedProcess[str]:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return subprocess.run(
        ["bash", str(HOOK)],
        cwd=tmp_path,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "LINK_WORK_TO_JIRA_SKILL_DIR": str(skill_dir),
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_allows_commit_when_skill_reports_linked_branch(tmp_path):
    skill_dir = make_fake_skill(tmp_path, "[jira-rules] [PROJ-123] linked")

    result = run_hook(tmp_path, skill_dir)

    assert result.returncode == 0


def test_blocks_commit_when_skill_reports_action_required(tmp_path):
    skill_dir = make_fake_skill(tmp_path, "[link-work-to-jira] ACTION REQUIRED: no ticket")

    result = run_hook(tmp_path, skill_dir)

    assert result.returncode == 1
    assert "current branch has no linked Jira ticket" in result.stderr


def test_blocks_commit_when_skill_is_missing(tmp_path):
    result = run_hook(tmp_path, tmp_path / "missing-skill")

    assert result.returncode == 1
    assert "skill script was not found" in result.stderr


def test_blocks_commit_when_skill_fails(tmp_path):
    skill_dir = make_fake_skill(tmp_path, "skill error", exit_code=7)

    result = run_hook(tmp_path, skill_dir)

    assert result.returncode == 1
    assert "branch validation failed" in result.stderr
