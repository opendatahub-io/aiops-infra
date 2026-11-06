"""The onboarding summary reports map PR and verification states."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_progress_summary as summary  # noqa: E402


def _state(status: str, url: str = "") -> dict:
    return {
        "steps": {
            "component_repo_map": {"status": status, "pr_url": url},
        }
    }


def test_open_mapping_pr_is_in_pending_summary_with_link():
    url = "https://github.com/red-hat-data-services/konflux-central/pull/4067"
    result = summary.build_pending_summary(
        _state("pr_raised", url), "odh-example", "RHOAI", ""
    )
    assert "Register GAP component/image map" in result
    assert url in result


def test_verified_noop_is_reported_done_without_pr():
    result = summary.build_full_summary(_state("done"), "odh-example", "RHOAI")
    assert f"Register GAP component/image map|{summary.status_emoji('done')}|—" in result


def test_failed_mapping_action_is_visible_as_closed():
    result = summary.build_full_summary(
        _state("closed", "https://github.com/red-hat-data-services/konflux-central/pull/4067"),
        "odh-example",
        "RHOAI",
    )
    assert f"Register GAP component/image map|{summary.status_emoji('closed')}|" in result


def test_merged_mapping_pr_is_not_misreported_as_verified():
    result = summary.build_full_summary(
        _state("merged", "https://github.com/red-hat-data-services/konflux-central/pull/4067"),
        "odh-example",
        "RHOAI",
    )
    assert f"Register GAP component/image map|{summary.status_emoji('merged')}|" in result
